# REPTIL — Reliable Enterprise Platform for Technology, Integration & Logistics

**Tagline:** Reliable Systems. Connected Business.

Dokumen ini adalah panduan rancangan (design blueprint) platform REPTIL berbasis Python.
Target audiens: presentasi ke perusahaan menengah–besar, sekaligus acuan teknis tim pengembang.

---

## 1. Ringkasan Eksekutif

REPTIL adalah platform operasi bisnis terintegrasi yang menyatukan:

- **Operasional inti** — master data, persediaan, pembelian, penjualan, laporan.
- **Integrasi & middleware** — konektor ke ERP/e-commerce/bank/ekspedisi, API gateway, orkestrasi data.
- **Logistik** — manajemen pengiriman, armada, rute, dan pelacakan.

Prinsip rancangan:

1. **Andal (Reliable)** — transaksi aman (ACID), audit trail penuh, tidak ada data hilang diam-diam.
2. **Terintegrasi (Connected)** — semua modul berbagi satu sumber kebenaran; integrasi luar lewat kontrak API yang jelas.
3. **Siap tumbuh (Scalable)** — modular monolith hari ini, dapat dipecah jadi service bila skala menuntut.

---

## 2. Keputusan Arsitektur

| Keputusan | Pilihan | Alasan |
|---|---|---|
| Gaya arsitektur | **Modular monolith** (modul per domain, batas tegas via Python package) | Cepat dikembangkan, mudah di-audit, tetap bisa di-scale horizontal di level worker/queue dulu |
| Bahasa | **Python 3.12** | Sesuai permintaan; dukungan typing modern (`Self`, `TypeAlias`, `tomllib`) |
| Web framework | **FastAPI** | Async, schema otomatis (OpenAPI), cocok untuk API-first dan integrasi B2B |
| ORM / Migrasi | **SQLAlchemy 2.x + Alembic** | Standar industri Python, migrasi terkontrol |
| Antre kerja | **Celery + Redis** | Job berat: sinkronisasi integrasi, kalkulasi laporan, ekspor, webhook retry |
| Cache & broker | **Redis** | Cache, broker Celery, rate limit, idempotency key |
| Database | **PostgreSQL 16** | ACID, JSONB untuk payload integrasi, row-level security bila multi-tenant |
| Auth | **OIDC/OAuth2** (Keycloak opsional) + JWT internal | SSO ke direktori perusahaan (LDAP/AD) — nilai jual besar di klien korporat |
| Deployment | **Docker Compose** (dev/UAT) → **Kubernetes** (produksi besar) | Portabel ke on-prem maupun cloud |
| Document store | **PostgreSQL JSONB** dulu | Hindari Elasticsearch di fase awal; cukup untuk pencarian laporan |

---

## 3. Struktur Repository

```
aplikasireptil/
├── docs/
│   └── DESAIN.md                  # dokumen ini
├── docker-compose.yml             # app + postgres + redis + worker + beat
├── docker-compose.override.yml    # lingkungan dev (hot reload)
├── pyproject.toml                 # dependensi & tooling (uv/pip)
├── alembic.ini
├── migrations/                    # versi skema database
├── src/
│   └── reptil/
│       ├── main.py                # bootstrap FastAPI app
│       ├── core/                  # cross-cutting: config, db, security, logging, errors
│       │   ├── config.py          # pydantic-settings, .env
│       │   ├── db.py              # engine, session, unit-of-work
│       │   ├── security.py        # JWT, hash password, RBAC dependency
│       │   ├── audit.py           # audit trail service
│       │   └── events.py          # in-process domain event bus
│       ├── modules/
│       │   ├── identity/          # auth, user, role, organisasi
│       │   ├── masterdata/        # partner, item, gudang, satuan, akun COA
│       │   ├── inventory/         # stok, mutasi, stock opname
│       │   ├── purchasing/        # PR → PO → GR → invoice
│       │   ├── sales/             # quotation → SO → delivery → invoice
│       │   ├── finance/           # AP/AR, jurnal umum, kas/bank
│       │   ├── logistics/         # shipment, armada, rute, tracking
│       │   ├── integration/       # konektor, webhook, orkestrasi, DLQ
│       │   └── reporting/         # dashboard, export, scheduled report
│       │       # pola per modul:
│       │       #   models.py | schemas.py | repository.py |
│       │       #   service.py | api.py | events.py
│       ├── shared/                # model & util lintas modul (hati-hati: harus stabil)
│       └── workers/               # task Celery per modul
├── tests/
│   ├── unit/                      # service & domain logic
│   ├── integration/               # butuh postgres (testcontainers)
│   └── e2e/
└── scripts/                       # seed data, demo data presentasi
```

**Aturan batas modul (enforce dengan `import-linter`):**

- Modul A boleh memanggil modul B hanya lewat `service.py`/`api.py` publiknya — jangan import `models.py` internal.
- Komunikasi dalam aplikasi sebisa mungkin lewat **domain events** (`events.py`), bukan panggilan langsung.
- `shared/` hanya berisi entitas yang benar-benar lintas modul (Partner, Item, Organisation).

---

## 4. Peta Modul & Alur Utama

### 4.1 Identity & Organisasi
- User, Role, Permission (RBAC), multi-cabang/perusahaan (`Organisation`).
- Login JWT (access 15 mnt, refresh 7 hari), SSO OIDC opsional.
- **Email unik global**: satu email satu akun; `organisation_id` pada akun menentukan
  data perusahaan mana yang terlihat — pengguna tidak perlu memilih organisasi saat login.
- Semua dokumen bisnis membawa `organisation_id` + `created_by` + audit trail.

### 4.1b Pengaturan & Profil (konfigurasi tersimpan di database)
Tabel `app_settings` (satu baris per organisasi) menyimpan seluruh identitas yang
dipakai antarmuka dan dokumen, sehingga **tidak ada nama perusahaan/logo yang di-hardcode**:

| Kelompok | Field | Dipakai di |
|---|---|---|
| Aplikasi | `app_name`, `app_tagline`, `app_logo` (bytea) | sidebar, judul halaman, halaman login, favicon |
| Perusahaan | `company_name`, `company_address`, `company_phone`, `company_email`, `company_npwp`, `company_logo` (bytea) | kop faktur PDF, header dashboard, footer |
| Faktur | `invoice_note`, `invoice_terms` | catatan & syarat di bawah tabel faktur |

Keputusan penting:

- **Logo disimpan sebagai `bytea` di database**, bukan berkas di disk — ikut ter-backup
  bersama data, tidak perlu volume terpisah, dan konsisten saat aplikasi di-scale ke banyak replika.
- Disajikan ulang lewat `GET /logo/{aplikasi|perusahaan}?v=<timestamp>` dengan
  `Cache-Control` panjang; parameter `v` dipakai sebagai cache-busting setiap logo diganti.
- Validasi unggahan di server: hanya PNG/JPEG/WEBP untuk logo aplikasi, hanya PNG/JPEG untuk
  logo perusahaan (agar dapat disematkan ke PDF), maksimum 2 MB. **Isi berkas benar-benar
  dibaca** (Pillow) sehingga berkas teks ber-MIME gambar tetap ditolak, lalu sisi terpanjang
  dibatasi 1000 px dan dikompres ulang agar tabel dan PDF faktur tidak membengkak.
- Penyimpanan bersifat **parsial**: hanya field yang dikirim yang diperbarui, sehingga
  unggah logo saja tidak menghapus data profil lain.
- Form membawa `rev` (`updated_at` baris tersebut) sebagai **kunci optimistis**: menyimpan
  form lama setelah data berubah di tab/jendela lain ditolak dengan pesan agar halaman dimuat
  ulang — mencegah nilai lama menimpa nilai baru tanpa disadari.
- Setiap organisasi punya identitas sendiri — perusahaan berbeda dapat memakai kop faktur berbeda.

Profil disuntikkan ke konteks semua halaman (`web/common.py`) sebagai objek `Profil`, dan
ke pembuat PDF sebagai parameter — jadi tidak ada query pengaturan berulang per halaman selain satu kali per permintaan.

Footer informasi sistem (nama aplikasi, versi, lingkungan, versi PostgreSQL, versi Python,
waktu server WIB) dirender dari `core/sysinfo.py`; versi database di-cache karena jarang berubah.

### 4.2 Master Data
- **Partner** (customer & supplier digabung dengan tipe), **Item** (SKU, satuan, berat/volume — penting untuk logistik), **Gudang**, daftar harga, chart of accounts (COA).
- Master data adalah kontrak bersama; perubahan besar dipublikasikan sebagai event.

### 4.3 Inventory
- Stock per item × gudang, mutasi (masuk/keluar/pindah), reserved stock untuk SO/PO.
- Stock opname dengan approval. Semua pergerakan lewat `StockMovement` berversi — tidak pernah UPDATE saldo langsung (saldo = agregat dari mutasi, disimpan ter-agregasi untuk performa).

### 4.4 Purchasing (hulu)
`PurchaseRequisition → PurchaseOrder → GoodsReceipt → SupplierInvoice → Payment`
- GR otomatis membuat mutasi stok + event `goods.received`.

### 4.5 Sales (hilir)
`Quotation → SalesOrder → DeliveryOrder → CustomerInvoice → Receipt`
- SO mem-*reserve* stok; DO memotong stok nyata saat dikirim.

### 4.6 Finance (AP/AR + jurnal umum sederhana)
Terpasang di `modules/finance` — AP/AR mengikuti faktur Purchasing/Sales, plus buku besar
double-entry kecil. Petanya:

`SupplierInvoice → Payment (keluar)` dan `CustomerInvoice → Payment (masuk)`, keduanya
memengaruhi `JournalEntry → JournalLine` dan `Account` (COA).

- **Bagan akun bawaan** (`pastikan_coa`, idempoten) — 8 akun: Kas & Bank (1-100),
  Piutang Usaha (1-200), Persediaan (1-300), Utang Usaha (2-100), Modal (3-100),
  Penjualan (4-100), HPP (5-100), Beban Lain-lain (5-900).
- **Jurnal otomatis** (idempoten per dokumen, dicek dari `ref_type` + `ref_id`):

  | Kejadian | Debit | Kredit |
  |---|---|---|
  | Faktur pembelian | Persediaan | Utang Usaha |
  | Faktur penjualan | Piutang Usaha | Penjualan |
  | (harga pokok, bila `harga_beli` > 0) | HPP | Persediaan |
  | Pembayaran utang (keluar) | Utang Usaha | Kas & Bank |
  | Penerimaan piutang (masuk) | Kas & Bank | Piutang Usaha |

- **Sisa tagihan = total − alokasi pembayaran** (`payment_allocations`), bukan kolom yang
  di-update: satu sumber kebenaran seperti kartu stok, bebas race. Status faktur
  (`unpaid` → `partial` → `paid`) selalu diturunkan dari sisa.
- **Jurnal harus seimbang** — `buat_jurnal` menolak bila debit ≠ kredit, ada baris nol,
  atau satu baris berisi debit dan kredit sekaligus.
- **Pembatalan pembayaran bersifat non-destruktif**: alokasi dihapus, jurnal ditandai
  `void` (bukan dihapus) sehingga jejak audit tetap ada dan neraca saldo tetap konsisten.
- **Laporan**: neraca saldo (`/finance/trial-balance`), jurnal umum (`/finance/journal`),
  daftar utang/piutang dengan **aging** (belum jatuh tempo / 1–30 / 31–60 / 61–90 / >90 hari),
  dan ringkasan (total AP/AR, jatuh tempo 7 hari, saldo kas, laba kotor bulan berjalan).
- **Penyederhanaan yang disengaja**: HPP dihitung dari `harga_beli` item saat ini (bukan
  biaya rata-rata saat barang keluar); pembelian langsung masuk Persediaan pada faktur
  (bukan saat penerimaan barang). Full ledger per-tanggal bisa menyusul.

### 4.7 Logistics
- **Shipment**: DO → paket (parsing dari item & berat/volume) → armada/kurir → status.
- **Armada/Kendaraan**: kapasitas (m3/kg), status, pengemudi.
- **Rute**: multi-stop, perhitungan beban dasar (jarak × berat/volume).
- **Tracking**: `ShipmentStatusHistory` (created → picked_up → in_transit → delivered/failed), update manual, dari kurir eksternal, atau webhook.
- Integrasi dengan ekspedisi (JNE/J&T/SiCepat/resi API) lewat modul Integration.

### 4.8 Integration & Middleware
- **Outbound**: adapter per sistem (Shopee/Tokopedia, Accurate/Zahir, bank VA, ekspedisi) — tiap adapter punya *mapper* ke skema internal REPTIL.
- **Inbound webhook**: endpoint bertanda tangan (HMAC), idempotency key, masuk antrean, diproses asinkron.
- **Scheduler**: sinkronisasi berkala (polling) + retry dengan backoff eksponensial.
- **Dead letter queue**: gagal setelah N kali → antrean inspeksi + UI admin untuk replay/manual mapping.
- **Audit payload**: setiap panggilan luar dicatat (request/response, status, latensi) di tabel `integration_log` (JSONB).
- Kontrak API publik REPTIL sendiri: `/api/v1` — OpenAPI otomatis, versikan sejak awal.

### 4.9 Reporting
Terpasang di `modules/reporting` — semua laporan **membaca** sumber yang sudah ada
(faktur, mutasi stok, jurnal), tidak ada angka yang disimpan ulang, jadi mustahil
"beda angka" antara laporan dan buku besar.

- **Ringkasan** (`/reports`): penjualan periode, HPP, laba kotor, laba bersih, nilai
  persediaan, sisa utang/piutang, penjualan harian, item terlaris — semuanya mengikuti
  rentang tanggal (default: bulan berjalan).
- **Analisis penjualan** (`/reports/sales`): per hari/bulan, per item, per pelanggan.
- **Laba rugi** (`/reports/profit-loss`): pendapatan & beban per akun dari jurnal
  berstatus `posted`; HPP dibaca dari akun HPP (5-100) sehingga **selalu sama** dengan
  neraca saldo (cadangan: qty × harga beli bila akun HPP tidak ada).
- **Nilai persediaan** (`/reports/stock`): saldo semua gudang × harga beli & harga jual,
  penanda item di bawah minimum.
- **Ekspor 11 jenis laporan** ke **CSV** (UTF-8 + BOM, pemisah desimal titik) dan
  **Excel .xlsx** (`openpyxl`: judul, catatan periode, kepala berformat, angka bertipe
  numerik siap dijumlahkan/di-pivot, kolom auto-lebar, baris kepala dibekukan) lewat
  `/reports/export/{jenis}?format=csv|xlsx&dari=&sampai=`.
- Dua laporan bersifat **posisi terkini** (stok, neraca) sehingga tidak dibatasi tanggal —
  keterangannya ikut menyesuaikan.
- Masih menyusul: ekspor asinkron lewat **Celery** untuk data besar, dan laporan
  terjadwal via email.

---

## 5. Model Data Inti (sketsa)

```
Organisation 1─* User, * Partner, * Item, * Warehouse, * Document
AppSetting 1─1 Organisation  (profil aplikasi & perusahaan; logo sebagai bytea)
Partner (tipe: customer|supplier|both)
Item (sku, nama, berat_kg, volume_m3, tipe: produk|jasa)
Warehouse
PurchaseOrder 1─* PurchaseOrderLine ─> Item
SalesOrder     1─* SalesOrderLine     ─> Item
DeliveryOrder  1─* Shipment 1─* ShipmentStatusHistory
Shipment       >? Vehicle, >? Carrier
StockMovement  (item, warehouse, qty, ref_type, ref_id)   ← immutable
Invoice (tipe: AP|AR) 1─* JournalEntry > JournalLine (COA)
Account (COA: kode, nama, tipe: asset|liability|equity|revenue|expense)
JournalEntry (number JU-YYYY-NNNN, sumber, ref_type+ref_id, status: posted|void) 1─* JournalLine (debit|credit)
Payment (arah: masuk|keluar, akun kas) 1─* PaymentAllocation ─> PurchaseInvoice | SalesInvoice
IntegrationConnection (sistem, kredensial ter-encrypt, mode)
IntegrationJob (connection, payload, status, attempt, next_retry_at)
IntegrationLog  (job, direction, request JSONB, response JSONB, http_status, durasi_ms)
AuditTrail (entity, entity_id, action, before/after JSONB, user, ts)
```

Aturan umum: setiap tabel transaksional punya `id UUID`, `organisation_id`, `created_at`, `updated_at`, `created_by`. Uang disimpan `Numeric(18,2)` — **tidak pernah float**. Qty bisa `Numeric(12,3)`.

---

## 6. Pola Teknis Wajib

1. **Unit of Work & transaksi** — satu request = satu transaksi DB; service tidak commit sendiri-sendiri.
2. **Idempotency** — endpoint pembuatan dokumen menerima `Idempotency-Key`; webhook juga.
3. **Domain events in-process** → dipetakan ke Celery task untuk pekerjaan asinkron (kirim email, panggil eksternal). Tidak perlu Kafka di skala awal; abstraksi event-nya siap diganti bila perlu.
4. **Validation berlapis** — Pydantic untuk skema API, validasi bisnis di service (mis. qty PO tidak boleh negatif, SHM stok tidak cukup).
5. **Error handling terpusat** — exception domain (`NotFoundError`, `BusinessRuleError`, `ConflictError`) dipetakan otomatis ke HTTP oleh `register_exception_handlers` (terpasang di `main.py`): API menerima amplop `{"error": {"code", "message", "detail"}}`, browser menerima halaman HTML ringkas (hanya bila `Accept` memuat `text/html`). Error tak terduga dicatat lengkap (traceback) lewat logger terstruktur dan ke pengguna hanya tampil pesan umum.
6. **Logging terstruktur** (structlog JSON) + `correlation_id` mengalir dari API → Celery → panggilan eksternal. (`correlation_id` disertakan otomatis di payload error 500; middleware pengisi per-request belum dipasang.)
7. **Keamanan** — RBAC per endpoint, enkripsi kredensial eksternal (Fernet/AES dari `cryptography`), secret via env/Docker secret, dependensi di-scan (`pip-audit`).

---

## 7. Deployment (Docker)

`docker-compose.yml` produksi/UAT:

| Service | Image | Catatan |
|---|---|---|
| `api` | build dari Dockerfile (uvicorn) | replica bisa ditambah |
| `worker` | image sama, command `celery -A reptil.workers` | bisa di-scale terpisah |
| `beat` | scheduler Celery | 1 instance saja |
| `postgres` | postgres:16-alpine | volume + backup harian `pg_dump` |
| `redis` | redis:7-alpine | persistence AOF |
| (opsional) `keycloak` | quay.io/keycloak | untuk SSO perusahaan |

Catatan produksi on-prem klien: TLS di depan (nginx/traefik), backup terjadwal, monitoring dasar (Prometheus + Grafana) menyusul — jangan dibebani di demo pertama.

---

## 8. Quality Gate
- **Test**: pytest + testcontainers-PostgreSQL untuk integration test; target modul kritis (inventory, integrasi) ≥ 80%.
- **Tipe & style**: mypy (strict), ruff.
- **Kontrak API**: snapshot test OpenAPI agar perubahan terdeteksi.
- **CI** (saat repo sudah di Git): ruff → mypy → pytest → build image.
- **Seed demo**: `scripts/seed_admin.py --with-demo` membuat organisasi, user admin, gudang, partner, item contoh, dan bagan akun. Aman diulang; tambahkan `--keep-password` bila dijalankan di database berisi data nyata (tanpa itu, password user yang sudah ada akan direset).

---

## 8b. Status Implementasi (per Oktober 2026)

| Fase | Isi | Status |
|---|---|---|
| Fondasi | Docker/venv, core (config, db, security, errors, parsing), identity + masterdata, Alembic | ✅ |
| Autentikasi | Login bcrypt + JWT (cookie & Bearer), RBAC dependency, halaman login & dashboard | ✅ |
| Master data | CRUD Partner / Item / Gudang dengan validasi | ✅ |
| Inventory | Mutasi stok append-only, saldo per gudang, kartu stok, peringatan minimum | ✅ |
| Purchasing | PO → Terima Barang → Faktur Pembelian → lunas | ✅ |
| Sales | SO → Kirim Barang (validasi stok) → Faktur Penjualan → lunas | ✅ |
| Export PDF | Faktur penjualan & pembelian (terbilang, kop, tanda tangan) | ✅ |
| Pengaturan | Profil aplikasi & perusahaan di database (nama, logo, NPWP, catatan/syarat faktur) + footer informasi sistem | ✅ |
| Logistik lanjutan | Shipment, armada, rute, tracking | ⏳ belum |
| Integrasi | Konektor eksternal, webhook, DLQ | ⏳ belum |
| Finance | COA, jurnal otomatis dari faktur & pembayaran, pembayaran sebagian, aging AP/AR, neraca saldo, ringkasan | ✅ |
| Reporting | Ringkasan, analisis penjualan (harian/bulanan, per item, per pelanggan), laba rugi, nilai persediaan, ekspor CSV & XLSX (11 jenis) | ✅ |

---

## 9. Roadmap

**Fase 0 — Fondasi (minggu 1–2)**
Repo, Docker Compose, core (config/db/security/errors/audit), modul identity + master data, seed.

**Fase 1 — Operasional inti (minggu 3–6)**
Inventory, Purchasing, Sales sampai DO, laporan dasar, RBAC tuntas, audit trail.

**Fase 2 — Logistik (minggu 7–9)**
Shipment, armada, tracking, integrasi 1 kurir eksternal sebagai pembuktian.

**Fase 3 — Integration & Finance (minggu 10–13)**
Framework konektor, webhook + DLQ + UI admin replay, 2–3 konektor nyata, AP/AR ringan.

**Fase 4 — Pematangan (lanjut)**
SSO Keycloak, K8s manifest, monitoring, performa & indexing, dokumentasi API untuk mitra.

---

## 10. Poin Jual untuk Presentasi (bahasa bisnis)

- Satu platform menghubungkan pembelian → stok → penjualan → pengiriman → keuangan: **tidak ada data ganda antar departemen**.
- Semua transaksi tercatat lengkap (**audit trail**) — siap untuk kebutuhan serifikasi & akuntabilitas.
- Terbuka ke sistem yang sudah dipakai (ERP, marketplace, ekspedisi, bank) — **tidak perlu membuang investasi lama**.
- Berjalan on-premise maupun cloud — menghormati kebijakan data perusahaan klien.
- Dibangun dengan Python yang matang & open source: biaya lisensi rendah, talenta mudah ditemukan, mudah dikustomisasi.

---

*Status: panduan rancangan awal — semua keputusan di atas dapat direvisi saat discovery bersama calon klien.*
