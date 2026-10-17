# REPTIL

**Reliable Enterprise Platform for Technology, Integration & Logistics**

> Reliable Systems. Connected Business.

Platform operasi bisnis terintegrasi berbasis Python — menyatukan master data, persediaan,
pembelian, penjualan, dan logistik dalam satu alur kerja yang saling terhubung.

## Dokumen

- [Panduan Rancangan (Design Blueprint)](docs/DESAIN.md) — arsitektur, struktur modul, model data, roadmap.
- [Pemaketan `.deb`](docs/PAKET_DEB.md) — build & pasang paket aplikasi (tanpa PostgreSQL/pgAdmin).

## Teknologi

Python 3.12 · FastAPI · SQLAlchemy 2 + Alembic · PostgreSQL · bcrypt + JWT · Jinja2 · fpdf2 · Pillow · openpyxl · (Redis/Celery menyusul)

## Fitur yang Sudah Jalan

| Bagian | Detail |
|---|---|
| **Autentikasi** | Login email + password (bcrypt), JWT via cookie (halaman) & Bearer (API), RBAC, audit `last_login_at` |
| **Master Data** | Partner (pelanggan/pemasok/keduanya), Item (SKU, harga beli/jual, berat, volume, stok minimum), Gudang — lengkap dengan pencarian & validasi kode unik |
| **Pembelian** | PO multi-baris → **Terima Barang** (stok masuk otomatis) → **Faktur Pembelian** → bayar (penuh/sebagian) |
| **Penjualan** | SO multi-baris → **Kirim Barang** (stok keluar + validasi stok cukup) → **Faktur Penjualan** → terima pembayaran (penuh/sebagian) |
| **Keuangan** | AP/AR dari faktur + **aging** (belum jatuh tempo s.d. >90 hari), pembayaran/penerimaan dengan alokasi ke faktur, **jurnal otomatis** (COA bawaan), bagan akun, jurnal umum, neraca saldo seimbang, ringkasan (saldo kas, laba kotor bulan ini) |
| **Laporan** | Ringkasan periode, **analisis penjualan** (harian/bulanan, per item, per pelanggan), **laba rugi** dari jurnal, **nilai persediaan**, serta **ekspor CSV & Excel** untuk 11 jenis laporan |
| **Inventory** | Saldo stok per item × gudang, kartu stok (mutasi append-only), peringatan stok di bawah minimum |
| **Invoice PDF** | Cetak faktur penjualan & pembelian: kop perusahaan, data pihak, tabel item, total, **terbilang Bahasa Indonesia**, kolom tanda tangan |
| **Dashboard** | Ringkasan partner/item/gudang, PO menunggu, utang, SO menunggu kirim, piutang, item di bawah minimum, plus **informasi sistem** di bagian bawah |
| **Pengaturan** | Profil aplikasi (nama, tagline, logo), profil perusahaan (nama, alamat, telepon, email, NPWP, logo), dan konfigurasi faktur (catatan & syarat) — semuanya **tersimpan di database**, tiap logo maksimal 2 MB |

### Aturan bisnis yang ditegakkan

- Stok **tidak pernah** di-`UPDATE` langsung — selalu dari mutasi (`stock_movements`), sehingga bisa diaudit.
- Pengiriman ditolak bila stok tidak cukup (pesan menyebut item dan jumlah tersedia).
- Barang hanya bisa diterima sekali; faktur hanya untuk dokumen yang sudah diterima/dikirim.
- **Sisa tagihan dihitung dari alokasi pembayaran** — status faktur (`unpaid` → `partial` → `paid`) selalu diturunkan dari angka itu, bukan ditandai manual.
- Pembayaran tidak boleh melebihi sisa tagihan; pembatalan pembayaran menandai jurnalnya `void` (bukan menghapus) agar jejak audit tetap ada.
- Jurnal menolak entri yang tidak seimbang (debit ≠ kredit) atau bernilai nol.
- Semua data terikat ke organisasi pengguna (multi-cabang sejak awal).

## Menjalankan

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env          # isi kredensial database
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_admin.py --with-demo --password 'Admin#2026'
.venv/bin/uvicorn reptil.main:app --reload --app-dir src
```

Buka <http://127.0.0.1:8000/login> — login seed: `admin@reptil.co.id` / `Admin#2026`.

> `seed_admin.py` aman diulang, **kecuali** password: secara default user yang sudah ada akan
> direset ke `--password`. Di database berisi data nyata, jalankan dengan `--keep-password`
> agar password siapa pun tidak tersentuh.

> Email unik global — satu email satu akun, organisasi mengikuti akun tersebut.

## Alur Coba Cepat

1. **Master data** → tambah pemasok + pelanggan + item (isi harga beli & jual).
2. **Pembelian** → PO Baru → simpan → klik **Terima** (stok masuk) → **Buat Faktur** → **Cetak PDF**.
3. **Penjualan** → SO Baru (qty melebihi stok akan ditolak saat kirim) → **Kirim** → **Buat Faktur** → **Cetak PDF**.
4. **Inventory** → lihat saldo berubah di Saldo Stok & Kartu Stok.
5. **Keuangan** → **Utang/Piutang Usaha** (lihat aging) → **Catat Pembayaran** (isi sebagian untuk uji status *Dibayar sebagian*) → **Jurnal Umum** & **Neraca Saldo** (pastikan *Seimbang*).
6. **Laporan** → pilih periode → **Analisis Penjualan** / **Laba Rugi** / **Nilai Persediaan** → tombol **CSV** atau **Excel** untuk mengunduh.

## Endpoint

| Endpoint | Keterangan |
|---|---|
| `POST /api/v1/auth/login` · `GET /api/v1/auth/me` | API autentikasi (Bearer token) |
| `GET/POST /login` · `GET /logout` · `GET /dashboard` | Halaman web + sesi cookie JWT |
| `/master/partners` · `/master/items` · `/master/warehouses` | Master data (list, `/new`, `/{id}/edit`) |
| `/purchases/orders` · `/purchases/orders/{id}` · `/purchases/invoices` | Pembelian + aksi receive/invoice/pay |
| `/sales/orders` · `/sales/orders/{id}` · `/sales/invoices` | Penjualan + aksi deliver/invoice/pay |
| `/sales/invoices/{id}/pdf` · `/purchases/invoices/{id}/pdf` | Export faktur PDF |
| `/inventory/stock` · `/inventory/movements` | Saldo stok & kartu stok |
| `/finance` · `/finance/payables` · `/finance/receivables` | Ringkasan keuangan · daftar utang · daftar piutang (dengan aging) |
| `/finance/payments` · `/finance/payments/new` · `/finance/payments/{id}` | Daftar, catat, dan rincian pembayaran/penerimaan (aksi `/{id}/hapus` untuk membatalkan) |
| `/finance/journal` · `/finance/journal/{id}` · `/finance/trial-balance` | Jurnal umum, detail, neraca saldo |
| `/finance/accounts` | Bagan akun (tambah/ubah nama & status aktif) |
| `/reports` · `/reports/sales` · `/reports/profit-loss` · `/reports/stock` | Ringkasan laporan · analisis penjualan · laba rugi · nilai persediaan |
| `/reports/export/{jenis}?format=csv\|xlsx&dari=&sampai=` | Unduh laporan (11 jenis: `stok`, `mutasi`, `faktur-jual`, `faktur-beli`, `utang`, `piutang`, `jurnal`, `neraca`, `laba-rugi`, `penjualan-harian`, `penjualan-item`) |
| `/pengaturan` · `GET /logo/{aplikasi\|perusahaan}` | Profil aplikasi & perusahaan (termasuk unggah logo) · penyajian logo |
| `GET /health` · `GET /docs` | Status aplikasi · OpenAPI |

### Izin (RBAC)

`masterdata.read/write` · `inventory.read` · `purchasing.read/write` · `sales.read/write` · `finance.read/write` · `reports.read` · `settings.read/write` — `"*"` berarti superadmin.
Role disimpan di tabel `roles.permissions` (JSONB) dan diperiksa lewat dependency `require_permission("kode")`.

## Perintah Berguna

```bash
.venv/bin/python scripts/check_db.py                   # tes koneksi database
.venv/bin/alembic revision --autogenerate -m "pesan"   # migrasi baru
.venv/bin/alembic upgrade head                         # terapkan migrasi
.venv/bin/python scripts/backfill_finance.py           # jurnal & status faktur untuk data lama (idempoten)
```
