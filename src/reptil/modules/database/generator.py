"""Pembuat data demo REPTIL — riwayat transaksi yang konsisten dan sehat.

Prinsip yang dipegang:

* **Aturan sama dengan aplikasi.** Pembelian → penerimaan (stok masuk) → faktur
  (Dr Persediaan / Cr Utang); penjualan → pengiriman (stok keluar) → faktur
  (Dr Piutang / Cr Penjualan, plus Dr HPP / Cr Persediaan); pembayaran →
  Dr Utang / Cr Kas atau Dr Kas / Cr Piutang. Tidak ada angka yang "ditempel".
* **Sehat by design.** Ada saldo awal (setoran modal + stok awal) sehingga kas
  tidak pernah negatif dan akun Modal terpakai; stok tidak pernah negatif karena
  qty penjualan dibatasi saldo; setiap jurnal seimbang; nilai persediaan di buku
  besar sama dengan nilai stok di laporan.
* **Papan umur piutang/utang terisi.** Faktur lama dipastikan lunas, sisanya
  dibiarkan jatuh tempo dalam rentang 0-200 hari sehingga semua kolom aging
  (belum jatuh tempo, 1-30, 31-60, 61-90, > 90) terisi wajar.
* **Deterministis.** Memakai seed tetap, jadi parameter yang sama menghasilkan
  data yang sama.
* **Komit per bulan.** Bila proses gagal di tengah, data sampai bulan terakhir
  yang selesai tetap utuh dan konsisten.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from reptil.modules.finance import service as fin
from reptil.modules.finance.models import (
    AKUN_HPP,
    AKUN_KAS,
    AKUN_MODAL,
    AKUN_PENJUALAN,
    AKUN_PERSEDIAAN,
    AKUN_PIUTANG,
    AKUN_UTANG,
    Account,
    JournalEntry,
    JournalLine,
    Payment,
    PaymentAllocation,
)
from reptil.modules.inventory.models import StockMovement
from reptil.modules.logistics.models import (
    Carrier,
    Route,
    RouteStop,
    Shipment,
    ShipmentLine,
    ShipmentStatusHistory,
    Vehicle,
)
from reptil.modules.masterdata.models import Item, Partner, Warehouse
from reptil.modules.purchasing.models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from reptil.modules.sales.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesOrder,
    SalesOrderLine,
)

ZONA = ZoneInfo("Asia/Jakarta")
RUPIAH = Decimal("0.01")
TIGA = Decimal("0.001")

BULAN_MAKS = 120
PER_BULAN_MAKS = 40
SKALA_MIN = Decimal("0.2")
SKALA_MAKS = Decimal("5")

# ------------------------------------------------------------------ katalog demo
# (sku, nama, satuan, harga beli, faktor harga jual, berat kg, volume m3, stok minimum)
KATALOG_ITEM: tuple[tuple[str, str, str, int, str, str, str, int], ...] = (
    ("RPT-001", "Kandang Kaca 60cm", "pcs", 450_000, "1.42", "12.500", "0.180", 8),
    ("RPT-002", "Lampu UVB 10.0 26W", "pcs", 120_000, "1.55", "0.300", "0.001", 12),
    ("RPT-003", "Pakan Jangkrik Premium 1kg", "pack", 35_000, "1.60", "1.100", "0.004", 25),
    ("RPT-004", "Substrat Cocopeat 5L", "pack", 28_000, "1.75", "2.400", "0.010", 20),
    ("RPT-005", "Water Dish Keramik Besar", "pcs", 65_000, "1.55", "1.800", "0.006", 10),
    ("RPT-006", "Thermostat Digital Reptil", "pcs", 210_000, "1.48", "0.900", "0.003", 8),
    ("RPT-007", "Kandang Plastik XL", "pcs", 180_000, "1.45", "5.200", "0.075", 10),
    ("RPT-008", "Vitamin & Kalsium Reptil 100ml", "botol", 42_000, "1.80", "0.400", "0.001", 18),
    ("RPT-009", "Humidifier Mini Terrarium", "pcs", 165_000, "1.50", "1.600", "0.006", 8),
    ("RPT-010", "Pemanas Ceramic 60W", "pcs", 95_000, "1.52", "0.700", "0.002", 12),
    ("TRR-001", "Terrarium Kaca 80cm + Kabinet", "unit", 650_000, "1.38", "38.000", "0.450", 4),
    ("TRR-002", "Terrarium Bioaktif 100cm", "unit", 1_250_000, "1.35", "62.000", "0.780", 3),
)

KATALOG_PELANGGAN: tuple[tuple[str, str, str, str], ...] = (
    (
        "CUS-001",
        "PT Mitra Retail Nusantara",
        "Jakarta Selatan",
        "Jl. Pasar Minggu Raya No. 12, Jakarta Selatan",
    ),
    ("CUS-002", "Toko Hewan Sahabat Reptil", "Bandung", "Jl. Sukajadi No. 88, Bandung"),
    ("CUS-003", "CV Exotic Pets Bali", "Denpasar", "Jl. Teuku Umar No. 45, Denpasar"),
    ("CUS-004", "Zoo & Pet Supply Semarang", "Semarang", "Jl. Majapahit No. 210, Semarang"),
    ("CUS-005", "Reptil Mania Store", "Surabaya", "Jl. Rungkut Asri Timur No. 7, Surabaya"),
    ("CUS-006", "Hobi Reptil Medan", "Medan", "Jl. Gatot Subroto No. 153, Medan"),
    ("CUS-007", "Aquatic & Reptile Center", "Yogyakarta", "Jl. Magelang KM 5, Yogyakarta"),
)

KATALOG_PEMASOK: tuple[tuple[str, str, str, str], ...] = (
    (
        "SUP-001",
        "CV Pakan Sehat Nusantara",
        "Bekasi",
        "Kawasan Industri Jababeka Blok C-12, Bekasi",
    ),
    ("SUP-002", "PT Terrarium Kaca Indonesia", "Tangerang", "Jl. Raya Serpong KM 8, Tangerang"),
    ("SUP-003", "UD Sumber Plastik Jaya", "Sidoarjo", "Jl. Lingkar Timur No. 21, Sidoarjo"),
    ("SUP-004", "PT Lampu Reptil Global", "Jakarta Barat", "Jl. Daan Mogot KM 19, Jakarta Barat"),
    ("SUP-005", "CV Nutrisi Satwa Prima", "Bogor", "Jl. Raya Tajur No. 56, Bogor"),
    ("SUP-006", "PT Keramik Indah Abadi", "Klaten", "Jl. Solo-Yogya KM 12, Klaten"),
)

KATALOG_EKSPEDISI: tuple[tuple[str, str, str], ...] = (
    ("JNE", "JNE Express", "https://track.jne.co.id/{resi}"),
    ("SICEPAT", "SiCepat Ekspres", "https://www.sicepat.com/checkAwb/{resi}"),
    ("JNT", "J&T Express", "https://www.jet.co.id/track?awb={resi}"),
)

KATALOG_ARMADA: tuple[tuple[str, str, str, str, int, str, str, str], ...] = (
    (
        "ARM-01",
        "Truk Box Engkel",
        "truk",
        "B 9012 RPT",
        2_500,
        "12.000",
        "Budi Santoso",
        "0811-2001-101",
    ),
    (
        "ARM-02",
        "Gran Max Pick Up",
        "pickup",
        "B 9345 RPT",
        1_200,
        "6.500",
        "Agus Wirawan",
        "0811-2001-102",
    ),
    (
        "ARM-03",
        "Motor Roda Tiga",
        "motor",
        "B 6677 RPT",
        350,
        "1.800",
        "Slamet Riyadi",
        "0811-2001-103",
    ),
)

CATATAN_KIRIM = (
    "Kirim pagi sebelum jam 10",
    "Barang mudah pecah",
    "Packing kayu",
    "Prioritas pelanggan",
)


def rupiah(nilai: object) -> Decimal:
    return Decimal(str(nilai or 0)).quantize(RUPIAH, rounding=ROUND_HALF_UP)


def qty3(nilai: object) -> Decimal:
    return Decimal(str(nilai or 0)).quantize(TIGA, rounding=ROUND_HALF_UP)


def _saat(tanggal: date, jam: int = 9, menit: int = 0) -> datetime:
    return datetime.combine(tanggal, time(hour=jam, minute=menit), tzinfo=ZONA)


@dataclass
class OpsiDemo:
    """Parameter pembuatan data demo (dipakai UI dan skrip CLI)."""

    bulan: int = 60
    per_bulan: int = 12
    skala: Decimal = Decimal("1")
    seed: int = 20261017
    logistik: bool = True
    akhir: date | None = None

    def normalisasi(self) -> OpsiDemo:
        return OpsiDemo(
            bulan=max(1, min(int(self.bulan), BULAN_MAKS)),
            per_bulan=max(1, min(int(self.per_bulan), PER_BULAN_MAKS)),
            skala=max(SKALA_MIN, min(Decimal(str(self.skala)), SKALA_MAKS)),
            seed=int(self.seed),
            logistik=bool(self.logistik),
            akhir=self.akhir or date.today(),
        )


@dataclass
class RencanaBayar:
    """Rencana pembayaran/penerimaan satu faktur."""

    jenis: str  # 'jual' | 'beli'
    faktur: object
    partner_id: uuid.UUID
    jatuh_tempo: date
    nilai: Decimal
    tanggal: date | None  # None = tetap terbuka (untuk demo aging)
    metode: str = "transfer"


@dataclass
class BarisJurnal:
    akun_id: uuid.UUID
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str | None = None
    partner_id: uuid.UUID | None = None


@dataclass
class HasilDemo:
    bulan: int = 0
    faktur_jual: int = 0
    faktur_beli: int = 0
    pembayaran: int = 0
    pengiriman: int = 0
    baris_jurnal: int = 0
    total_penjualan: Decimal = Decimal("0")
    total_pembelian: Decimal = Decimal("0")
    total_hpp: Decimal = Decimal("0")
    kas: Decimal = Decimal("0")
    nilai_persediaan: Decimal = Decimal("0")
    per_jurnal: dict[str, int] = field(default_factory=dict)


class Penomoran:
    """Penomoran PREFIX-TAHUN-URUT yang sadar data lama (aman bila menumpuk data)."""

    def __init__(self) -> None:
        self._urut: dict[tuple[str, int], int] = {}

    def setel(self, awalan: str, tahun: int, urut_terakhir: int) -> None:
        self._urut[(awalan, tahun)] = max(self._urut.get((awalan, tahun), 0), urut_terakhir)

    def ambil(self, awalan: str, tahun: int) -> str:
        kunci = (awalan, tahun)
        self._urut[kunci] = self._urut.get(kunci, 0) + 1
        return f"{awalan}-{tahun}-{self._urut[kunci]:04d}"


class PembangkitDemo:
    """Mesin pembuat data demo. Satu instance = satu kali jalan."""

    def __init__(self, db: Session, organisation_id: uuid.UUID, opsi: OpsiDemo, lapor=None):
        self.db = db
        self.organisation_id = organisation_id
        self.opsi = opsi.normalisasi()
        self._lapor_cb = lapor or (lambda *_: None)
        self.acak = random.Random(self.opsi.seed)
        self.hari_ini = self.opsi.akhir or date.today()
        self.penomoran = Penomoran()

        self.akun: dict[str, Account] = {}
        self.gudang: list[Warehouse] = []
        self.item: list[Item] = []
        self.pelanggan: list[Partner] = []
        self.pemasok: list[Partner] = []
        self.ekspedisi: list[Carrier] = []
        self.armada: list[Vehicle] = []

        self.saldo: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
        self.rencana: list[RencanaBayar] = []
        self.kas = Decimal("0")
        self.hasil = HasilDemo()
        self._bulan_terakhir: int = 0

    # ---------------------------------------------------------------- utilitas
    def _lapor(self, persen: int, tahap: str) -> None:
        self._lapor_cb(max(0, min(100, int(persen))), tahap)

    def _uang(self, nilai: Decimal) -> Decimal:
        return rupiah(nilai)

    def _tgl_bulan(self, awal: date, akhir: date, hari_maks: int | None = None) -> date:
        batas = (akhir - awal).days if hari_maks is None else min(hari_maks, (akhir - awal).days)
        return awal + timedelta(days=self.acak.randint(0, max(0, batas)))

    def _tanggal_valid(self, tanggal: date, minimum: date | None = None) -> date:
        if minimum is not None and tanggal < minimum:
            tanggal = minimum
        return min(tanggal, self.hari_ini)

    def _saldo(self, item_id: uuid.UUID, gudang_id: uuid.UUID) -> Decimal:
        return self.saldo.get((item_id, gudang_id), Decimal("0"))

    def _tambah_saldo(self, item_id: uuid.UUID, gudang_id: uuid.UUID, qty: Decimal) -> None:
        self.saldo[(item_id, gudang_id)] = self._saldo(item_id, gudang_id) + qty

    def _nilai_persediaan(self) -> Decimal:
        total = Decimal("0")
        for (item_id, _gudang_id), qty in self.saldo.items():
            item = self._item_by_id[item_id]
            total += qty * rupiah(item.harga_beli)
        return total

    # -------------------------------------------------------- penomoran lama
    def _siapkan_penomoran(self) -> None:
        """Baca nomor tertinggi tiap (prefix, tahun) agar tidak bentrok."""
        pasangan = (
            ("SO", SalesOrder),
            ("PO", PurchaseOrder),
            ("FJ", SalesInvoice),
            ("FB", PurchaseInvoice),
            ("TM", Payment),
            ("JU", JournalEntry),
            ("SJ", Shipment),
            ("RT", Route),
        )
        for awalan, model in pasangan:
            nomor = self.db.execute(
                select(model.number).where(
                    model.organisation_id == self.organisation_id,
                    model.number.like(f"{awalan}-%"),
                )
            ).scalars()
            for nilai in nomor:
                bagian = nilai.rsplit("-", 1)
                if len(bagian) != 2 or not bagian[1].isdigit():
                    continue
                tahun_bagian = nilai[len(awalan) + 1 : -len(bagian[1]) - 1]
                if not tahun_bagian.isdigit():
                    continue
                self.penomoran.setel(awalan, int(tahun_bagian), int(bagian[1]))
        # BY (pembayaran keluar) satu tabel dengan TM
        for nilai in self.db.execute(
            select(Payment.number).where(
                Payment.organisation_id == self.organisation_id, Payment.number.like("BY-%")
            )
        ).scalars():
            bagian = nilai.rsplit("-", 1)
            if len(bagian) == 2 and bagian[1].isdigit():
                self.penomoran.setel("BY", int(nilai[3:7]), int(bagian[1]))

    # ------------------------------------------------------------- data dasar
    def _pastikan_dasar(self) -> None:
        self.akun = fin.pastikan_coa(self.db, self.organisation_id)

        gudang = list(
            self.db.execute(
                select(Warehouse).where(Warehouse.organisation_id == self.organisation_id)
            ).scalars()
        )
        ada_kode = {g.kode for g in gudang}
        if not gudang:
            gudang.append(
                Warehouse(
                    organisation_id=self.organisation_id,
                    kode="GDG-01",
                    nama="Gudang Utama",
                    alamat="Jl. Reptil Raya No. 1, Jakarta Selatan",
                    is_default=True,
                )
            )
            ada_kode.add("GDG-01")
        if len(gudang) < 2:
            kode = "GDG-02"
            nomor = 2
            while kode in ada_kode:
                nomor += 1
                kode = f"GDG-{nomor:02d}"
            gudang.append(
                Warehouse(
                    organisation_id=self.organisation_id,
                    kode=kode,
                    nama="Gudang Cabang Bandung",
                    alamat="Jl. Sukajadi No. 90, Bandung",
                )
            )
        self.db.add_all(gudang)
        self.db.flush()

        ada_sku = set(
            self.db.execute(
                select(Item.sku).where(Item.organisation_id == self.organisation_id)
            ).scalars()
        )
        if len(ada_sku) < 5:
            baru = []
            for sku, nama, satuan, beli, faktor, berat, volume, minimum in KATALOG_ITEM:
                if sku in ada_sku:
                    continue
                baru.append(
                    Item(
                        organisation_id=self.organisation_id,
                        sku=sku,
                        nama=nama,
                        tipe="produk",
                        satuan=satuan,
                        harga_beli=rupiah(beli),
                        harga_jual=rupiah(Decimal(beli) * Decimal(faktor)),
                        berat_kg=Decimal(berat),
                        volume_m3=Decimal(volume),
                        stok_minimum=Decimal(minimum),
                    )
                )
            if baru:
                self.db.add_all(baru)
                self.db.flush()

        def _partner(katalog: tuple, tipe: str) -> None:
            ada = set(
                self.db.execute(
                    select(Partner.kode).where(
                        Partner.organisation_id == self.organisation_id, Partner.tipe == tipe
                    )
                ).scalars()
            )
            baru = []
            for kode, nama, _kota, alamat in katalog:
                if kode in ada:
                    continue
                baru.append(
                    Partner(
                        organisation_id=self.organisation_id,
                        kode=kode,
                        nama=nama,
                        tipe=tipe,
                        alamat=alamat,
                        telepon="021-5550" + kode[-3:],
                        email=f"{kode.lower()}@reptil-demo.co.id",
                    )
                )
            if baru:
                self.db.add_all(baru)
                self.db.flush()

        _partner(KATALOG_PELANGGAN, "customer")
        _partner(KATALOG_PEMASOK, "supplier")

        ada_ekspedisi = set(
            self.db.execute(
                select(Carrier.kode).where(Carrier.organisation_id == self.organisation_id)
            ).scalars()
        )
        baru = [
            Carrier(
                organisation_id=self.organisation_id,
                kode=kode,
                nama=nama,
                telepon="021-1500" + str(index),
                tracking_url=url,
            )
            for index, (kode, nama, url) in enumerate(KATALOG_EKSPEDISI, start=1)
            if kode not in ada_ekspedisi
        ]
        if baru:
            self.db.add_all(baru)
            self.db.flush()

        ada_armada = set(
            self.db.execute(
                select(Vehicle.kode).where(Vehicle.organisation_id == self.organisation_id)
            ).scalars()
        )
        baru = [
            Vehicle(
                organisation_id=self.organisation_id,
                kode=kode,
                nama=nama,
                tipe=tipe,
                plat=plat,
                kapasitas_kg=Decimal(str(kg)),
                kapasitas_m3=Decimal(m3),
                pengemudi=pengemudi,
                telepon_pengemudi=telepon,
            )
            for kode, nama, tipe, plat, kg, m3, pengemudi, telepon in KATALOG_ARMADA
            if kode not in ada_armada
        ]
        if baru:
            self.db.add_all(baru)
            self.db.flush()

    def _muat_master(self) -> None:
        oid = self.organisation_id
        self.gudang = list(
            self.db.execute(
                select(Warehouse)
                .where(Warehouse.organisation_id == oid)
                .order_by(Warehouse.is_default.desc(), Warehouse.kode)
            ).scalars()
        )
        self.item = list(
            self.db.execute(
                select(Item)
                .where(Item.organisation_id == oid, Item.is_active.is_(True))
                .order_by(Item.sku)
            ).scalars()
        )
        self.pelanggan = list(
            self.db.execute(
                select(Partner).where(
                    Partner.organisation_id == oid,
                    Partner.is_active.is_(True),
                    Partner.tipe.in_(("customer", "both")),
                )
            ).scalars()
        )
        self.pemasok = list(
            self.db.execute(
                select(Partner).where(
                    Partner.organisation_id == oid,
                    Partner.is_active.is_(True),
                    Partner.tipe.in_(("supplier", "both")),
                )
            ).scalars()
        )
        self.ekspedisi = list(
            self.db.execute(
                select(Carrier).where(Carrier.organisation_id == oid, Carrier.is_active.is_(True))
            ).scalars()
        )
        self.armada = list(
            self.db.execute(
                select(Vehicle).where(Vehicle.organisation_id == oid, Vehicle.is_active.is_(True))
            ).scalars()
        )
        self._item_by_id = {item.id: item for item in self.item}
        if not self.gudang or not self.item or not self.pelanggan or not self.pemasok:
            raise ValueError(
                "Data dasar tidak lengkap (gudang/item/pelanggan/pemasok) — periksa kembali."
            )

    # ------------------------------------------------------------------ jurnal
    def _jurnal(
        self,
        *,
        tanggal: date,
        memo: str,
        sumber: str,
        baris: list[BarisJurnal],
        ref_type: str | None = None,
        ref_id: uuid.UUID | None = None,
    ) -> JournalEntry:
        debit = sum((b.debit for b in baris), Decimal("0"))
        entri = JournalEntry(
            organisation_id=self.organisation_id,
            number=self.penomoran.ambil("JU", tanggal.year),
            tanggal=tanggal,
            memo=memo,
            sumber=sumber,
            ref_type=ref_type,
            ref_id=ref_id,
            status="posted",
            total=self._uang(debit),
            created_at=_saat(tanggal, 10),
        )
        for urut, b in enumerate(baris, start=1):
            entri.lines.append(
                JournalLine(
                    line_no=urut,
                    account_id=b.akun_id,
                    partner_id=b.partner_id,
                    debit=self._uang(b.debit),
                    credit=self._uang(b.credit),
                    memo=b.memo,
                )
            )
        self.db.add(entri)
        self.hasil.baris_jurnal += len(baris)
        self.hasil.per_jurnal[sumber] = self.hasil.per_jurnal.get(sumber, 0) + 1
        return entri

    # -------------------------------------------------------------- saldo awal
    def _saldo_awal(self, bulan_pertama: date) -> None:
        """Setoran modal + stok awal. Ini yang membuat kas & Modal sehat sejak awal."""
        tanggal = bulan_pertama - timedelta(days=1)
        # stok awal ≈ 2 bulan permintaan pertama, dibagi rata ke dua gudang
        pasangan = [(item, gudang) for item in self.item for gudang in self.gudang[:2]]
        nilai_per_pasangan = self._perkiraan_hpp(0) * Decimal("2.0") / Decimal(len(pasangan))
        stok: list[tuple[Item, Warehouse, Decimal, Decimal]] = []
        for item, gudang in pasangan:
            harga = rupiah(item.harga_beli)
            dasar = nilai_per_pasangan / harga if harga else Decimal("10")
            qty = qty3(
                max(
                    Decimal("5"),
                    (dasar * Decimal(str(self.acak.uniform(0.7, 1.3)))).quantize(Decimal("1")),
                )
            )
            stok.append((item, gudang, qty, harga))
            self._tambah_saldo(item.id, gudang.id, qty)

        nilai_stok = sum((qty * harga for _i, _g, qty, harga in stok), Decimal("0"))
        # modal kerja ≈ 3 bulan permintaan, supaya kas tidak pernah negatif
        modal_kerja = rupiah(max(self._perkiraan_hpp(0) * Decimal("3"), Decimal("30000000")))
        modal = rupiah(nilai_stok + modal_kerja)

        for item, gudang, qty, _harga in stok:
            movement = StockMovement(
                organisation_id=self.organisation_id,
                item_id=item.id,
                warehouse_id=gudang.id,
                qty=qty,
                ref_type="opening",
                ref_number="SALDO-AWAL",
                note="Stok awal data demo",
                created_at=_saat(tanggal, 8),
            )
            self.db.add(movement)

        self._jurnal(
            tanggal=tanggal,
            memo="Saldo awal perusahaan — setoran modal & stok awal (data demo)",
            sumber="manual",
            baris=[
                BarisJurnal(self.akun[AKUN_KAS].id, debit=modal_kerja, memo="Setoran modal ke kas"),
                BarisJurnal(
                    self.akun[AKUN_PERSEDIAAN].id, debit=nilai_stok, memo="Stok awal persediaan"
                ),
                BarisJurnal(self.akun[AKUN_MODAL].id, credit=modal, memo="Modal pemilik"),
            ],
        )
        self.kas = modal_kerja
        self.db.flush()

    # --------------------------------------------------------------- bulanan
    def _daftar_bulan(self) -> list[tuple[date, date]]:
        akhir = self.hari_ini
        index = akhir.year * 12 + (akhir.month - 1) - (self.opsi.bulan - 1)
        hasil: list[tuple[date, date]] = []
        for i in range(self.opsi.bulan):
            tahun, bulan_index = divmod(index + i, 12)
            awal = date(tahun, bulan_index + 1, 1)
            if bulan_index == 11:
                akhir_bulan = date(tahun, 12, 31)
            else:
                akhir_bulan = date(tahun, bulan_index + 2, 1) - timedelta(days=1)
            akhir_bulan = min(akhir_bulan, akhir)
            if awal <= akhir_bulan:
                hasil.append((awal, akhir_bulan))
        return hasil

    def _bulan_penjualan(self, awal: date, akhir: date, bulan_ke: int) -> Decimal:
        jumlah_so = max(2, round(self.opsi.per_bulan * (1 + Decimal("0.01") * bulan_ke)))
        hpp_total = Decimal("0")
        for _ in range(jumlah_so):
            pelanggan = self.acak.choice(self.pelanggan)
            gudang = self._pilih_gudang()
            if gudang is None:
                continue
            baris_item: list[tuple[Item, Decimal]] = []
            for item in self.acak.sample(self.item, k=self.acak.randint(1, min(4, len(self.item)))):
                tersedia = self._saldo(item.id, gudang.id)
                if tersedia < 1:
                    continue
                rencana = (
                    Decimal(self.acak.randint(4, 30)) * self.opsi.skala * self._faktor_item(item)
                )
                qty = min(
                    max(Decimal("1"), rencana.quantize(Decimal("1"))),
                    tersedia.quantize(Decimal("1")),
                )
                if qty < 1:
                    continue
                baris_item.append((item, qty))
            if not baris_item:
                continue

            tgl_so = self._tgl_bulan(awal, akhir)
            tgl_kirim = self._tanggal_valid(
                tgl_so + timedelta(days=self.acak.randint(1, 5)), tgl_so
            )
            if tgl_kirim > self.hari_ini:
                continue
            tgl_faktur = self._tanggal_valid(
                tgl_kirim + timedelta(days=self.acak.randint(0, 3)), tgl_kirim
            )

            total = Decimal("0")
            hpp = Decimal("0")
            order = SalesOrder(
                id=uuid.uuid4(),
                organisation_id=self.organisation_id,
                number=self.penomoran.ambil("SO", tgl_so.year),
                customer_id=pelanggan.id,
                warehouse_id=gudang.id,
                tanggal=tgl_so,
                status="invoiced",
                catatan="Pesanan data demo",
                delivered_at=_saat(tgl_kirim, 10),
                created_at=_saat(tgl_so, 9),
            )
            for urut, (item, qty) in enumerate(baris_item, start=1):
                harga = rupiah(item.harga_jual)
                subtotal = self._uang(qty * harga)
                total += subtotal
                hpp += qty * rupiah(item.harga_beli)
                order.lines.append(
                    SalesOrderLine(
                        line_no=urut,
                        item_id=item.id,
                        qty=qty3(qty),
                        harga=harga,
                        subtotal=subtotal,
                    )
                )
            order.total = self._uang(total)
            self.db.add(order)

            for item, qty in baris_item:
                self._tambah_saldo(item.id, gudang.id, -qty)
                self.db.add(
                    StockMovement(
                        organisation_id=self.organisation_id,
                        item_id=item.id,
                        warehouse_id=gudang.id,
                        qty=-qty3(qty),
                        ref_type="sales_delivery",
                        ref_id=order.id,
                        ref_number=order.number,
                        note="Pengiriman data demo",
                        created_at=_saat(tgl_kirim, 10),
                    )
                )

            faktur = SalesInvoice(
                id=uuid.uuid4(),
                organisation_id=self.organisation_id,
                number=self.penomoran.ambil("FJ", tgl_faktur.year),
                order_id=order.id,
                customer_id=pelanggan.id,
                tanggal=tgl_faktur,
                jatuh_tempo=tgl_faktur + timedelta(days=30),
                status="unpaid",
                catatan="Faktur data demo",
                total=self._uang(total),
                created_at=_saat(tgl_faktur, 11),
            )
            for urut, (item, qty) in enumerate(baris_item, start=1):
                faktur.lines.append(
                    SalesInvoiceLine(
                        line_no=urut,
                        item_id=item.id,
                        deskripsi=item.nama,
                        qty=qty3(qty),
                        harga=rupiah(item.harga_jual),
                        subtotal=self._uang(qty * rupiah(item.harga_jual)),
                    )
                )
            self.db.add(faktur)

            self._jurnal(
                tanggal=tgl_faktur,
                memo=f"Faktur penjualan {faktur.number} — {pelanggan.nama}",
                sumber="faktur_jual",
                ref_type="sales_invoice",
                ref_id=faktur.id,
                baris=[
                    BarisJurnal(
                        self.akun[AKUN_PIUTANG].id,
                        debit=faktur.total,
                        memo=faktur.number,
                        partner_id=pelanggan.id,
                    ),
                    BarisJurnal(
                        self.akun[AKUN_PENJUALAN].id,
                        credit=faktur.total,
                        memo=f"Penjualan {pelanggan.nama}",
                    ),
                ],
            )
            hpp = self._uang(hpp)
            if hpp > 0:
                self._jurnal(
                    tanggal=tgl_faktur,
                    memo=f"Harga pokok penjualan {faktur.number}",
                    sumber="faktur_jual",
                    ref_type="sales_invoice",
                    ref_id=faktur.id,
                    baris=[
                        BarisJurnal(self.akun[AKUN_HPP].id, debit=hpp, memo=faktur.number),
                        BarisJurnal(
                            self.akun[AKUN_PERSEDIAAN].id, credit=hpp, memo="Pemakaian persediaan"
                        ),
                    ],
                )

            self._rencanakan(
                jenis="jual",
                faktur=faktur,
                partner_id=pelanggan.id,
                jatuh_tempo=faktur.jatuh_tempo,
                total=faktur.total,
            )
            if self.opsi.logistik and self.acak.random() < 0.32:
                self._kirim(pelanggan, gudang, order, baris_item, tgl_kirim)

            self.hasil.faktur_jual += 1
            self.hasil.total_penjualan += faktur.total
            self.hasil.total_hpp += hpp
            hpp_total += hpp
        return hpp_total

    def _perkiraan_hpp(self, bulan_ke: int) -> Decimal:
        """Perkiraan HPP bulan ke-`bulan_ke`: jumlah pesanan x rata-rata nilai baris.

        Dipakai sebagai dasar keputusan pembelian (lihat ``_bulan_pembelian``) dan
        sebagai ukuran besar stok awal.
        """
        jumlah_so = self._jumlah_so(bulan_ke)
        baris = Decimal(jumlah_so) * Decimal("2.5")
        baris_per_item = baris / Decimal(len(self.item))
        total = Decimal("0")
        for item in self.item:
            qty = baris_per_item * Decimal("17") * self.opsi.skala * self._faktor_item(item)
            total += qty * rupiah(item.harga_beli)
        return rupiah(total)

    def _jumlah_so(self, bulan_ke: int) -> int:
        """Jumlah pesanan penjualan bulan ke-`bulan_ke` (tumbuh 1% per bulan)."""
        return max(2, round(self.opsi.per_bulan * (1 + Decimal("0.01") * bulan_ke)))

    def _hitung_faktor(self, item: Item) -> Decimal:
        """Faktor permintaan per item: barang murah terjual lebih banyak unit.

        Akar kuadrat dari rasio harga rata-rata/harga item, dibatasi 0,3-3,5 —
        supaya item murah tidak menumpuk dan item mahal tidak kehabisan stok.
        """
        harga = rupiah(item.harga_beli)
        if not harga or not self._rata_harga_beli:
            return Decimal("1")
        rasio = (self._rata_harga_beli / harga).sqrt()
        return min(max(rasio, Decimal("0.3")), Decimal("3.5"))

    def _faktor_item(self, item: Item) -> Decimal:
        return self._faktor.get(item.id, Decimal("1"))

    def _pilih_gudang(self) -> Warehouse | None:
        """Gudang dengan total stok terbanyak (agar stok selalu tersedia)."""
        terbaik, nilai = None, Decimal("-1")
        for gudang in self.gudang:
            total = sum(
                (q for (item_id, gid), q in self.saldo.items() if gid == gudang.id), Decimal("0")
            )
            if total > nilai:
                terbaik, nilai = gudang, total
        return terbaik

    def _bulan_pembelian(self, awal: date, akhir: date, bulan_ke: int) -> None:
        """Belanja barang **per item** agar tiap item punya stok ≈ 2 bulan permintaan.

        Kebutuhan dihitung dari perkiraan permintaan (bukan HPP yang sudah terjadi)
        supaya tidak terjebak lingkaran "stok kurang → beli sedikit → stok tetap
        kurang". Qty per item = target stok dikurangi stok sekarang, lalu dibagi ke beberapa
        pesanan pembelian.
        """
        baris = Decimal(self._jumlah_so(bulan_ke)) * Decimal("2.5")
        baris_per_item = baris / Decimal(len(self.item))
        kebutuhan: list[tuple[Item, Decimal]] = []
        for item in self.item:
            permintaan = baris_per_item * Decimal("17") * self.opsi.skala * self._faktor_item(item)
            target = permintaan * Decimal("2.0")
            stok = sum(
                (q for (item_id, _g), q in self.saldo.items() if item_id == item.id),
                Decimal("0"),
            )
            butuh = target - stok
            if butuh < 1:
                continue
            qty = max(
                Decimal("2"),
                (butuh * Decimal(str(self.acak.uniform(0.85, 1.15)))).quantize(Decimal("1")),
            )
            kebutuhan.append((item, qty))
        if not kebutuhan:
            return

        jumlah_po = max(2, round(self.opsi.per_bulan / 3))
        self.acak.shuffle(kebutuhan)
        for urutan_po in range(jumlah_po):
            porsi_items = kebutuhan[urutan_po::jumlah_po]
            if not porsi_items:
                continue
            pemasok = self.acak.choice(self.pemasok)
            gudang = self.acak.choice(self.gudang[:2])
            tgl_po = self._tgl_bulan(awal, akhir, hari_maks=15)
            tgl_terima = self._tanggal_valid(
                tgl_po + timedelta(days=self.acak.randint(2, 6)), tgl_po
            )
            if tgl_terima > self.hari_ini:
                continue
            tgl_faktur = self._tanggal_valid(
                tgl_terima + timedelta(days=self.acak.randint(1, 4)), tgl_terima
            )

            order = PurchaseOrder(
                id=uuid.uuid4(),
                organisation_id=self.organisation_id,
                number=self.penomoran.ambil("PO", tgl_po.year),
                supplier_id=pemasok.id,
                warehouse_id=gudang.id,
                tanggal=tgl_po,
                status="invoiced",
                catatan="Pesanan pembelian data demo",
                received_at=_saat(tgl_terima, 9),
                created_at=_saat(tgl_po, 8),
            )
            total_po = Decimal("0")
            rincian: list[tuple[Item, Decimal, Decimal]] = []
            for urut, (item, qty) in enumerate(porsi_items, start=1):
                harga = rupiah(item.harga_beli)
                subtotal = self._uang(qty * harga)
                total_po += subtotal
                rincian.append((item, qty, harga))
                order.lines.append(
                    PurchaseOrderLine(
                        line_no=urut,
                        item_id=item.id,
                        qty=qty3(qty),
                        harga=harga,
                        subtotal=subtotal,
                    )
                )
            order.total = self._uang(total_po)
            self.db.add(order)

            for item, qty, _harga in rincian:
                self._tambah_saldo(item.id, gudang.id, qty)
                self.db.add(
                    StockMovement(
                        organisation_id=self.organisation_id,
                        item_id=item.id,
                        warehouse_id=gudang.id,
                        qty=qty3(qty),
                        ref_type="purchase_receipt",
                        ref_id=order.id,
                        ref_number=order.number,
                        note="Penerimaan data demo",
                        created_at=_saat(tgl_terima, 9),
                    )
                )

            faktur = PurchaseInvoice(
                id=uuid.uuid4(),
                organisation_id=self.organisation_id,
                number=self.penomoran.ambil("FB", tgl_faktur.year),
                order_id=order.id,
                supplier_id=pemasok.id,
                supplier_ref=f"SUP/{tgl_faktur.year}/{self.acak.randint(1000, 9999)}",
                tanggal=tgl_faktur,
                jatuh_tempo=tgl_faktur + timedelta(days=30),
                status="unpaid",
                catatan="Faktur pembelian data demo",
                total=self._uang(total_po),
                created_at=_saat(tgl_faktur, 10),
            )
            for urut, (item, qty, harga) in enumerate(rincian, start=1):
                faktur.lines.append(
                    PurchaseInvoiceLine(
                        line_no=urut,
                        item_id=item.id,
                        deskripsi=item.nama,
                        qty=qty3(qty),
                        harga=harga,
                        subtotal=self._uang(qty * harga),
                    )
                )
            self.db.add(faktur)

            self._jurnal(
                tanggal=tgl_faktur,
                memo=f"Faktur pembelian {faktur.number} — {pemasok.nama}",
                sumber="faktur_beli",
                ref_type="purchase_invoice",
                ref_id=faktur.id,
                baris=[
                    BarisJurnal(
                        self.akun[AKUN_PERSEDIAAN].id,
                        debit=faktur.total,
                        memo=faktur.number,
                    ),
                    BarisJurnal(
                        self.akun[AKUN_UTANG].id,
                        credit=faktur.total,
                        memo=faktur.number,
                        partner_id=pemasok.id,
                    ),
                ],
            )
            self._rencanakan(
                jenis="beli",
                faktur=faktur,
                partner_id=pemasok.id,
                jatuh_tempo=faktur.jatuh_tempo,
                total=faktur.total,
            )
            self.hasil.faktur_beli += 1
            self.hasil.total_pembelian += faktur.total

    # ------------------------------------------------------------- pembayaran
    def _rencanakan(
        self,
        *,
        jenis: str,
        faktur,
        partner_id: uuid.UUID,
        jatuh_tempo: date,
        total: Decimal,
    ) -> None:
        """Tentukan nasib tagihan agar papan umur terisi wajar.

        Faktur yang jatuh temponya lebih dari 180 hari lalu dipastikan lunas
        (walau terlambat), sisanya dipilih acak: lunas tepat waktu, dibayar
        sebagian, atau dibiarkan terbuka. Dengan begitu tidak ada tunggakan
        berumur tahunan, tetapi tiap kolom umur (1-30 s/d > 90 hari) tetap terisi.
        """
        umur_jatuh = (self.hari_ini - jatuh_tempo).days
        if umur_jatuh > 180:
            nasib = "lunas"
        else:
            nasib = self.acak.choices(("lunas", "sebagian", "terbuka"), weights=(80, 7, 13))[0]

        metode = "transfer" if self.acak.random() < 0.85 else "tunai"
        if nasib == "sebagian":
            porsi = Decimal(str(self.acak.uniform(0.35, 0.7)))
            nilai = self._uang(total * porsi)
            tanggal = jatuh_tempo + timedelta(days=self.acak.randint(0, 15))
        elif nasib == "terbuka":
            if umur_jatuh <= 25:
                # masih baru: mungkin dibayar sesudah jatuh tempo
                nilai = total
                tanggal = jatuh_tempo + timedelta(days=self.acak.randint(20, 60))
            else:
                nilai = total
                tanggal = None  # sengaja dibiarkan terbuka (piutang tak tertagih)
        else:
            nilai = total
            geser = self.acak.randint(-6, 12) if jenis == "jual" else self.acak.randint(-2, 14)
            tanggal = jatuh_tempo + timedelta(days=geser)

        if tanggal is not None and tanggal > self.hari_ini:
            tanggal = None  # belum dibayar sampai hari ini → masuk papan umur
        self.rencana.append(
            RencanaBayar(
                jenis=jenis,
                faktur=faktur,
                partner_id=partner_id,
                jatuh_tempo=jatuh_tempo,
                nilai=nilai,
                tanggal=tanggal,
                metode=metode,
            )
        )

    def _bayar_jatuh_tempo(self, awal: date, akhir: date) -> None:
        """Bayar/tagih semua rencana yang tanggalnya jatuh pada bulan ini."""
        sisa: list[RencanaBayar] = []
        for rencana in self.rencana:
            if rencana.tanggal is None or rencana.tanggal > akhir:
                sisa.append(rencana)
                continue
            if rencana.tanggal < awal:
                rencana.tanggal = awal  # jangan menumpuk di bulan lampau
            self._bayar(rencana)
        self.rencana = sisa

    def _bayar(self, rencana: RencanaBayar) -> None:
        arah = "masuk" if rencana.jenis == "jual" else "keluar"
        tanggal = rencana.tanggal
        awalan = "TM" if arah == "masuk" else "BY"
        pembayaran = Payment(
            id=uuid.uuid4(),
            organisation_id=self.organisation_id,
            number=self.penomoran.ambil(awalan, tanggal.year),
            arah=arah,
            tanggal=tanggal,
            partner_id=rencana.partner_id,
            akun_id=self.akun[AKUN_KAS].id,
            jumlah=rencana.nilai,
            metode=rencana.metode,
            referensi=f"DEMO/{tanggal.year}/{self.acak.randint(10000, 99999)}",
            catatan="Pembayaran data demo",
            created_at=_saat(tanggal, 13),
        )
        if arah == "masuk":
            pembayaran.allocations.append(
                PaymentAllocation(sales_invoice_id=rencana.faktur.id, jumlah=rencana.nilai)
            )
        else:
            pembayaran.allocations.append(
                PaymentAllocation(purchase_invoice_id=rencana.faktur.id, jumlah=rencana.nilai)
            )
        self.db.add(pembayaran)

        partner = self._partner_by_id[rencana.partner_id]
        label = "Penerimaan" if arah == "masuk" else "Pembayaran"
        if arah == "masuk":
            baris = [
                BarisJurnal(
                    self.akun[AKUN_KAS].id, debit=rencana.nilai, memo=f"{label} {partner.nama}"
                ),
                BarisJurnal(
                    self.akun[AKUN_PIUTANG].id,
                    credit=rencana.nilai,
                    memo=rencana.faktur.number,
                    partner_id=rencana.partner_id,
                ),
            ]
        else:
            baris = [
                BarisJurnal(
                    self.akun[AKUN_UTANG].id,
                    debit=rencana.nilai,
                    memo=rencana.faktur.number,
                    partner_id=rencana.partner_id,
                ),
                BarisJurnal(
                    self.akun[AKUN_KAS].id, credit=rencana.nilai, memo=f"{label} {partner.nama}"
                ),
            ]
        self._jurnal(
            tanggal=tanggal,
            memo=f"{label} {rencana.faktur.number} — {partner.nama}",
            sumber="pembayaran",
            ref_type="sales_payment" if arah == "masuk" else "purchase_payment",
            ref_id=pembayaran.id,
            baris=baris,
        )

        sisa = rupiah(rencana.faktur.total) - rencana.nilai
        if sisa <= 0:
            rencana.faktur.status = "paid"
            rencana.faktur.paid_at = _saat(tanggal, 13)
        else:
            rencana.faktur.status = "partial"
        self.kas += rencana.nilai if arah == "masuk" else -rencana.nilai
        self.hasil.pembayaran += 1

    def _jaga_kas(self, awal: date, akhir: date) -> None:
        """Kas tidak boleh negatif: bila menipis, tambah setoran modal."""
        if self.kas >= Decimal("50000000"):
            return
        tambahan = rupiah(Decimal("150000000") * self.opsi.skala - self.kas)
        tanggal = self._tanggal_valid(akhir, awal)
        self._jurnal(
            tanggal=tanggal,
            memo="Setoran modal tambahan (data demo)",
            sumber="manual",
            baris=[
                BarisJurnal(self.akun[AKUN_KAS].id, debit=tambahan, memo="Setoran modal tambahan"),
                BarisJurnal(self.akun[AKUN_MODAL].id, credit=tambahan, memo="Modal pemilik"),
            ],
        )
        self.kas += tambahan

    # ------------------------------------------------------------- pengiriman
    def _kirim(
        self,
        pelanggan: Partner,
        gudang: Warehouse,
        order: SalesOrder,
        baris_item: list[tuple[Item, Decimal]],
        tgl_kirim: date,
    ) -> None:
        umur = (self.hari_ini - tgl_kirim).days
        if umur > 3:
            status = "failed" if self.acak.random() < 0.02 else "delivered"
        elif umur > 1:
            status = self.acak.choice(("in_transit", "delivered", "delivered"))
        else:
            status = self.acak.choice(("created", "picked_up", "in_transit"))

        pakai_armada = self.acak.random() < 0.45 and self.armada
        ekspedisi = (
            None if pakai_armada else (self.acak.choice(self.ekspedisi) if self.ekspedisi else None)
        )
        armada = self.acak.choice(self.armada) if pakai_armada else None
        berat = sum(
            (qty * (item.berat_kg or Decimal("0")) for item, qty in baris_item), Decimal("0")
        )
        volume = sum(
            (qty * (item.volume_m3 or Decimal("0")) for item, qty in baris_item), Decimal("0")
        )
        kirim = Shipment(
            id=uuid.uuid4(),
            organisation_id=self.organisation_id,
            number=self.penomoran.ambil("SJ", tgl_kirim.year),
            sales_order_id=order.id,
            customer_id=pelanggan.id,
            warehouse_id=gudang.id,
            vehicle_id=armada.id if armada else None,
            carrier_id=ekspedisi.id if ekspedisi else None,
            resi=(
                f"{ekspedisi.kode}{tgl_kirim.year}{self.acak.randint(100000, 999999)}"
                if ekspedisi
                else None
            ),
            alamat_kirim=pelanggan.alamat,
            penerima=pelanggan.nama,
            telepon_penerima=pelanggan.telepon,
            status=status,
            total_berat_kg=qty3(berat),
            total_volume_m3=qty3(volume),
            catatan=self.acak.choice(CATATAN_KIRIM) if self.acak.random() < 0.3 else None,
            shipped_at=_saat(tgl_kirim, 10),
            delivered_at=(
                _saat(tgl_kirim + timedelta(days=self.acak.randint(1, 4)), 16)
                if status == "delivered"
                else None
            ),
            created_at=_saat(tgl_kirim, 9),
        )
        for urut, (item, qty) in enumerate(baris_item, start=1):
            kirim.lines.append(
                ShipmentLine(
                    line_no=urut,
                    item_id=item.id,
                    qty=qty3(qty),
                    berat_kg=qty3(qty * (item.berat_kg or Decimal("0"))),
                    volume_m3=qty3(qty * (item.volume_m3 or Decimal("0"))),
                )
            )
        rangkaian = ["created"]
        if status in ("picked_up", "in_transit", "delivered", "failed"):
            rangkaian.append("picked_up")
        if status in ("in_transit", "delivered", "failed"):
            rangkaian.append("in_transit")
        rangkaian.append(status)
        for i, tahap in enumerate(rangkaian):
            kirim.history.append(
                ShipmentStatusHistory(
                    status=tahap,
                    note={
                        "created": "Pengiriman dibuat",
                        "picked_up": "Barang diambil kurir",
                        "in_transit": "Dalam perjalanan",
                        "delivered": "Diterima pelanggan",
                        "failed": "Pengiriman gagal — akan dikirim ulang",
                    }.get(tahap),
                    created_at=_saat(tgl_kirim + timedelta(days=i // 2), 10 + (i % 2) * 3),
                )
            )
        self.db.add(kirim)
        self.hasil.pengiriman += 1
        if self._jadwal_rute.get(tgl_kirim) is None:
            self._jadwal_rute[tgl_kirim] = []
        if len(self._jadwal_rute[tgl_kirim]) < 5:
            self._jadwal_rute[tgl_kirim].append((kirim, pelanggan))

    def _buat_rute(self, akhir: date) -> None:
        """Rute multi-stop untuk pengiriman 90 hari terakhir (demo modul logistik)."""
        batas = akhir - timedelta(days=90)
        for tanggal in sorted(self._jadwal_rute):
            if tanggal < batas:
                continue
            kiriman = self._jadwal_rute[tanggal]
            armada = self.acak.choice(self.armada) if self.armada else None
            rute = Route(
                organisation_id=self.organisation_id,
                number=self.penomoran.ambil("RT", tanggal.year),
                nama=f"Rute {tanggal.strftime('%d/%m')} — {kiriman[0][1].nama}",
                tanggal=tanggal,
                vehicle_id=armada.id if armada else None,
                status="selesai" if (self.hari_ini - tanggal).days > 7 else "berjalan",
                catatan="Rute data demo",
                created_at=_saat(tanggal, 6),
            )
            for urut, (kirim, pelanggan) in enumerate(kiriman, start=1):
                rute.stops.append(
                    RouteStop(
                        urutan=urut,
                        shipment_id=kirim.id,
                        alamat=pelanggan.alamat or pelanggan.nama,
                        jarak_km=Decimal(str(self.acak.uniform(4, 35))).quantize(Decimal("0.01")),
                        status="tiba" if rute.status == "selesai" else "pending",
                        arrived_at=_saat(tanggal, 8 + urut) if rute.status == "selesai" else None,
                        created_at=_saat(tanggal, 6),
                    )
                )
            self.db.add(rute)
        self._jadwal_rute.clear()

    # ------------------------------------------------------------------ jalankan
    def jalankan(self) -> HasilDemo:
        self._lapor(1, "Menyiapkan bagan akun & data dasar")
        self._pastikan_dasar()
        self._lapor(4, "Memuat data master")
        self._muat_master()
        self._partner_by_id = {partner.id: partner for partner in (*self.pelanggan, *self.pemasok)}
        self._rata_harga_beli = (
            sum((rupiah(item.harga_beli) for item in self.item), Decimal("0")) / len(self.item)
            if self.item
            else Decimal("0")
        )
        self._faktor = {item.id: self._hitung_faktor(item) for item in self.item}
        self._jadwal_rute: dict[date, list] = {}

        self._lapor(6, "Membaca penomoran dokumen lama")
        self._siapkan_penomoran()

        bulan = self._daftar_bulan()
        if not bulan:
            raise ValueError("Rentang bulan kosong — periksa parameter.")
        self._lapor(8, "Membuat saldo awal (modal & stok awal)")
        self._saldo_awal(bulan[0][0])
        self.db.commit()

        total = len(bulan)
        for urut, (awal, akhir) in enumerate(bulan, start=1):
            self._lapor(
                8 + int(88 * (urut - 1) / total),
                f"Bulan {urut}/{total} — {awal.strftime('%b %Y')}",
            )
            self._bayar_jatuh_tempo(awal, akhir)
            self._bulan_pembelian(awal, akhir, urut - 1)
            self._bulan_penjualan(awal, akhir, urut - 1)
            self._jaga_kas(awal, akhir)
            self.db.commit()

        if self.opsi.logistik:
            self._lapor(96, "Menyusun rute pengiriman")
            self._buat_rute(bulan[-1][1])
            self.db.commit()

        self._lapor(98, "Menyelaraskan status faktur")
        fin.sinkron_status_faktur(self.db, self.organisation_id)
        self.db.commit()

        self.hasil.bulan = total
        self.hasil.kas = self.kas
        self.hasil.nilai_persediaan = self._nilai_persediaan()
        self._lapor(100, "Selesai")
        return self.hasil


def perkiraan(opsi: OpsiDemo) -> dict:
    """Perkiraan jumlah dokumen/baris — ditampilkan sebelum job dijalankan."""
    o = opsi.normalisasi()
    faktur_jual = sum(max(2, round(o.per_bulan * (1 + 0.01 * m))) for m in range(o.bulan))
    po_per_bulan = max(2, round(o.per_bulan / 3))
    faktur_beli = o.bulan * po_per_bulan
    pembayaran = int((faktur_jual + faktur_beli) * 0.9)
    pengiriman = int(faktur_jual * 0.32) if o.logistik else 0
    baris = faktur_jual * 3 + faktur_beli * 3 + pembayaran * 2 + (faktur_jual + faktur_beli) * 6
    return {
        "faktur_jual": faktur_jual,
        "faktur_beli": faktur_beli,
        "pembayaran": pembayaran,
        "pengiriman": pengiriman,
        "perkiraan_baris": baris + pengiriman * 5 + faktur_jual * 2 + faktur_beli * 2,
        "mulai": (o.akhir - timedelta(days=o.bulan * 30)).isoformat(),
        "selesai": o.akhir.isoformat(),
    }


def bangkitkan(db: Session, *, organisation_id: uuid.UUID, opsi: OpsiDemo, lapor=None) -> dict:
    """Titik masuk: hasilkan data demo, kembalikan ringkasan (dict) untuk UI."""
    pembangkit = PembangkitDemo(db, organisation_id, opsi, lapor=lapor)
    hasil = pembangkit.jalankan()
    return {
        "bulan": hasil.bulan,
        "faktur_jual": hasil.faktur_jual,
        "faktur_beli": hasil.faktur_beli,
        "pembayaran": hasil.pembayaran,
        "pengiriman": hasil.pengiriman,
        "baris_jurnal": hasil.baris_jurnal,
        "total_penjualan": str(hasil.total_penjualan),
        "total_pembelian": str(hasil.total_pembelian),
        "total_hpp": str(hasil.total_hpp),
        "kas": str(rupiah(hasil.kas)),
        "nilai_persediaan": str(rupiah(hasil.nilai_persediaan)),
        "per_jurnal": hasil.per_jurnal,
    }
