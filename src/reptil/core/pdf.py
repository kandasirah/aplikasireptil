"""Pembuat PDF faktur REPTIL (fpdf2) — dipakai faktur penjualan & pembelian."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from fpdf import FPDF

from reptil.core.terbilang import terbilang_rupiah

VERDE = (15, 81, 50)
ABU = (107, 124, 115)
GARIS = (200, 210, 203)

# Font Unicode (DejaVu) bila tersedia — kalau tidak, kembali ke font core + sanitasi ASCII
_DEJAVU_DIR = Path("/usr/share/fonts/truetype/dejavu")
_TTF = {
    "": _DEJAVU_DIR / "DejaVuSans.ttf",
    "B": _DEJAVU_DIR / "DejaVuSans-Bold.ttf",
    "I": _DEJAVU_DIR / "DejaVuSans-Oblique.ttf",
}
PAKAI_TTF = all(p.exists() for p in _TTF.values())
FAMILY = "DejaVu" if PAKAI_TTF else "Helvetica"

# Karakter tipografis yang tidak ada di latin-1 (dipakai bila font core)
_GANTI = {
    "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u00b7": "-", "\u2026": "...", "\u00a0": " ",
}


def _ascii_safe(teks: str) -> str:
    for asal, tujuan in _GANTI.items():
        teks = teks.replace(asal, tujuan)
    return teks.encode("latin-1", "replace").decode("latin-1")


def rupiah(nilai: Decimal | float | int) -> str:
    """1250000.5 → '1.250.000,50' (format Indonesia)."""
    n = Decimal(str(nilai)).quantize(Decimal("0.01"))
    bulat, sen = divmod(abs(n), Decimal("1"))
    teks = f"{int(bulat):,}".replace(",", ".")
    if sen:
        teks += f",{int(sen * 100):02d}"
    return f"{'-' if n < 0 else ''}{teks}"


def qty_teks(nilai: Decimal | float | int | None) -> str:
    """10.000 → '10', 2.500 → '2,5' (tanpa nol ekor, koma desimal Indonesia)."""
    if nilai is None:
        return "0"
    n = Decimal(str(nilai)).normalize()
    teks = f"{n:f}".rstrip("0").rstrip(".") if "." in f"{n:f}" else f"{n:f}"
    return teks.replace(".", ",")


STATUS_ID = {
    "unpaid": "Belum dibayar",
    "paid": "Lunas",
    "cancelled": "Dibatalkan",
    "draft": "Draft",
}


def tanggal_id(d: date | None) -> str:
    if d is None:
        return "-"
    bulan = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
             "Agustus", "September", "Oktober", "November", "Desember"]
    return f"{d.day} {bulan[d.month]} {d.year}"


class _InvoicePDF(FPDF):
    def __init__(self, *, judul: str, nomor: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.judul = judul
        self.nomor = nomor
        if PAKAI_TTF:
            for gaya, path in _TTF.items():
                self.add_font("DejaVu", gaya, str(path))
        self.set_auto_page_break(auto=True, margin=25)
        self.set_margins(15, 15, 15)

    def normalize_text(self, text: str) -> str:
        """Cegah error encoding: font core hanya mendukung latin-1."""
        if not PAKAI_TTF:
            text = _ascii_safe(text)
        return super().normalize_text(text)

    def header(self) -> None:
        self.set_font(FAMILY, "B", 9)
        self.set_text_color(*ABU)
        self.cell(0, 5, f"{self.judul} — {self.nomor}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def footer(self) -> None:
        self.set_y(-18)
        self.set_font(FAMILY, "", 8)
        self.set_text_color(*ABU)
        self.cell(0, 5, f"Halaman {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)


def build_invoice_pdf(
    *,
    judul: str,
    nomor: str,
    organisasi: dict,
    pihak_label: str,
    pihak: dict,
    tanggal: date,
    jatuh_tempo: date | None,
    referensi: str | None,
    lines: list[dict],
    total: Decimal,
    catatan: str | None = None,
    syarat: str | None = None,
    status: str | None = None,
) -> bytes:
    """Susun PDF faktur dan kembalikan bytes-nya.

    lines: list of dict dengan kunci nama, qty, satuan, harga, subtotal
    organisasi: dict dengan kunci nama, alamat, telepon, email, npwp, logo (bytes)
    """
    pdf = _InvoicePDF(judul=judul, nomor=nomor)
    pdf.add_page()

    # ------------------------------------------------------------- kop
    y_kop = pdf.get_y()
    x_teks = pdf.l_margin
    logo = organisasi.get("logo")
    if logo:
        try:
            pdf.image(BytesIO(logo), x=pdf.l_margin, y=y_kop, w=20)
            x_teks = pdf.l_margin + 24
        except Exception:  # noqa: BLE001 — logo rusak/format tak dikenal: lanjut tanpa logo
            x_teks = pdf.l_margin

    pdf.set_xy(x_teks, y_kop)
    pdf.set_font(FAMILY, "B", 18)
    pdf.set_text_color(*VERDE)
    pdf.cell(0, 9, organisasi.get("nama") or "REPTIL", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FAMILY, "", 9)
    pdf.set_text_color(*ABU)
    pdf.set_x(x_teks)
    if organisasi.get("alamat"):
        pdf.multi_cell(0, 4.5, organisasi["alamat"])
        pdf.set_x(x_teks)
    kontak = " · ".join(x for x in [organisasi.get("telepon"), organisasi.get("email")] if x)
    if kontak:
        pdf.cell(0, 4.5, kontak, new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(x_teks)
    if organisasi.get("npwp"):
        pdf.cell(0, 4.5, f"NPWP: {organisasi['npwp']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)
    pdf.set_draw_color(*GARIS)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    # ----------------------------------------------------- judul & no
    pdf.set_font(FAMILY, "B", 14)
    pdf.cell(110, 8, judul.upper(), new_x="RIGHT", new_y="TOP")
    pdf.set_font(FAMILY, "B", 11)
    pdf.cell(0, 8, nomor, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # ------------------------------------------------- data pihak
    pdf.set_font(FAMILY, "", 9)
    y_awal = pdf.get_y()
    pdf.set_font(FAMILY, "B", 9)
    pdf.cell(35, 5, pihak_label, new_x="RIGHT", new_y="TOP")
    pdf.set_font(FAMILY, "B", 10)
    pdf.cell(0, 5, pihak.get("nama") or "-", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FAMILY, "", 9)
    if pihak.get("alamat"):
        pdf.set_x(pdf.l_margin + 35)
        pdf.multi_cell(0, 4.5, pihak["alamat"])
    if pihak.get("telepon"):
        pdf.set_x(pdf.l_margin + 35)
        pdf.cell(0, 4.5, f"Telp: {pihak['telepon']}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(pdf.l_margin + 110, y_awal)
    for label, nilai in (
        ("Tanggal", tanggal_id(tanggal)),
        ("Jatuh tempo", tanggal_id(jatuh_tempo)),
        ("Referensi", referensi or "-"),
        ("Status", STATUS_ID.get((status or "").lower(), (status or "-").upper())),
    ):
        pdf.set_x(pdf.l_margin + 110)
        pdf.set_font(FAMILY, "", 9)
        pdf.cell(30, 5, label, new_x="RIGHT", new_y="TOP")
        pdf.cell(0, 5, f": {nilai}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(pdf.l_margin)

    # --------------------------------------------------------- tabel
    pdf.ln(4)
    lebar = (12, 78, 20, 16, 30, 34)  # total 190 = lebar area A4
    pdf.set_fill_color(*VERDE)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(FAMILY, "B", 9)
    for w, judul_kolom in zip(lebar, ("No", "Item", "Qty", "Satuan", "Harga", "Jumlah")):
        pdf.cell(w, 8, judul_kolom, border=0, align="C" if judul_kolom != "Item" else "L", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font(FAMILY, "", 9)
    for i, line in enumerate(lines, start=1):
        pdf.set_draw_color(*GARIS)
        tinggi = 7
        pdf.cell(12, tinggi, str(i), border="B", align="C")
        pdf.cell(78, tinggi, (line.get("nama") or "")[:52], border="B")
        pdf.cell(20, tinggi, qty_teks(line["qty"]), border="B", align="C")
        pdf.cell(16, tinggi, (line.get("satuan") or "")[:10], border="B", align="C")
        pdf.cell(30, tinggi, rupiah(line["harga"]), border="B", align="R")
        pdf.cell(34, tinggi, rupiah(line["subtotal"]), border="B", align="R")
        pdf.ln()

    # ------------------------------------------------------- total
    pdf.ln(2)
    pdf.set_font(FAMILY, "B", 10)
    pdf.cell(126, 8, "TOTAL", align="R")
    pdf.cell(34, 8, rupiah(total), align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    pdf.set_font(FAMILY, "I", 9)
    pdf.set_text_color(*ABU)
    pdf.multi_cell(0, 4.5, f"Terbilang: {terbilang_rupiah(total)}")
    pdf.set_text_color(0, 0, 0)

    if catatan:
        pdf.ln(2)
        pdf.set_font(FAMILY, "", 9)
        pdf.multi_cell(0, 4.5, f"Catatan: {catatan}")

    if syarat:
        pdf.ln(2)
        pdf.set_font(FAMILY, "I", 8)
        pdf.set_text_color(*ABU)
        pdf.multi_cell(0, 4.2, f"Syarat & Ketentuan: {syarat}")
        pdf.set_text_color(0, 0, 0)

    # --------------------------------------------------- tanda tangan
    pdf.ln(10)
    y_ttd = pdf.get_y()
    pdf.set_font(FAMILY, "", 9)
    pdf.set_xy(pdf.l_margin, y_ttd)
    pdf.cell(0, 5, "Diterima oleh,", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(pdf.l_margin + 105, y_ttd)
    pdf.cell(0, 5, "Hormat kami,", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(16)
    pdf.set_x(pdf.l_margin)
    pdf.cell(90, 5, "( ______________________ )")
    pdf.set_x(pdf.l_margin + 105)
    pdf.cell(0, 5, "( ______________________ )", new_x="LMARGIN", new_y="NEXT")

    keluaran = pdf.output()
    return bytes(keluaran)
