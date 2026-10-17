# Pemaketan REPTIL sebagai `.deb`

Panduan membangun dan memasang paket Debian (`reptil_<versi>_<arch>.deb`) untuk REPTIL.

> **Prinsip:** paket ini **hanya berisi aplikasi**. PostgreSQL dan pgAdmin **tidak**
> dibundel dan **tidak** ikut terpasang (mereka ada di `Suggests`, bukan `Depends`).
> Aplikasi hanya "ditunjuk" ke instance PostgreSQL yang sudah ada lewat
> `/etc/reptil/reptil.env`. Karena paket ini tidak pernah membuka port PostgreSQL,
> **mustahil bentrok** dengan port PostgreSQL/pgAdmin. Satu-satunya port yang
> dipegang paket ini adalah port web aplikasi, dan itu dipilih otomatis.

---

## 1. Isi paket

| Path di sistem | Isi |
|---|---|
| `/opt/reptil/app` | Kode aplikasi: `src/`, `migrations/`, `scripts/`, `alembic.ini` |
| `/opt/reptil/venv` | Virtualenv Python + seluruh dependensi (dibuat dengan `--copies`) |
| `/opt/reptil/bin` | Perintah bantu: `reptil-run`, `reptil-migrate`, `reptil-seed`, `reptil-check` |
| `/lib/systemd/system/reptil.service` | Unit systemd |
| `/usr/share/reptil/reptil.env.example` | Contoh konfigurasi |
| `/usr/share/reptil/free_port.py` | Pencari port bebas yang dipakai `postinst` |
| `/usr/share/lintian/overrides/reptil` | Pengabaian lintian untuk penyimpangan yang disengaja |
| `/etc/reptil/reptil.env` | **Dibuat saat instalasi** dari contoh di atas — bukan bagian paket |

Venv dibuat pada path final `/opt/reptil/venv`, sehingga shebang di dalam
`/opt/reptil/venv/bin/*` langsung menunjuk ke lokasi yang benar di sistem target.

---

## 2. Membangun paket

Prasyarat di mesin build: `python3` (3.12), `python3-venv`, `dpkg-deb` (>= 1.19,
untuk `--root-owner-group`), dan akses jaringan untuk mengunduh dependensi.

```bash
scripts/build_deb.sh                       # versi diambil dari pyproject.toml + "-1"
VERSION=0.2.0-1 scripts/build_deb.sh       # versi khusus
ARCH=arm64 scripts/build_deb.sh            # arsitektur lain
```

Hasil: `.deb-build/reptil_<versi>_<arch>.deb`.

Yang dilakukan skrip:

1. Menyalin `src/`, `migrations/`, `scripts/`, `alembic.ini`, `pyproject.toml`.
2. Membuat venv `--copies` dan memasang dependensi **dibaca dari
   `[project].dependencies` di `pyproject.toml`** (satu sumber kebenaran).
3. Menulis ulang path venv staging → `/opt/reptil/venv` (shebang, `activate*`,
   `pyvenv.cfg`).
4. Memasang berkas paket (wrapper, unit systemd, contoh konfigurasi, pencari port,
   lintian override, changelog, copyright, maintainer script), lalu menormalkan
   izin (direktori `0755`, berkas `0644`, executable `0755`).
5. Mengisi `Version`/`Installed-Size` pada `DEBIAN/control`, lalu
   `dpkg-deb --root-owner-group --build`.

Penting: karena dependensi runtime diambil dari `pyproject.toml`, pastikan
`pyproject.toml` lengkap. (Catatan: `jinja2` pernah terlewat di `pyproject.toml`
meski dipakai `Jinja2Templates` — sudah diperbaiki.)

---

## 3. Memasang paket

```bash
sudo apt install ./.deb-build/reptil_0.1.0-1_amd64.deb
# atau
sudo dpkg -i ./.deb-build/reptil_0.1.0-1_amd64.deb
sudo apt-get -f install     # menuntaskan dependensi bila perlu
```

`postinst` akan:

1. Membuat akun sistem `reptil` (tanpa login).
2. Membuat `/etc/reptil/reptil.env` (sekali saja) dari contoh, lalu:
   - memilih **port aplikasi bebas** (mulai dari 8010, naik sampai 8109);
   - mengisi `SECRET_KEY` acak.
3. Mengaktifkan & menjalankan `reptil.service`.
4. Mencoba menjalankan migrasi (**best-effort** — tidak menggagalkan instalasi
   bila PostgreSQL belum diisi/dijangkau).

---

## 4. Menyambungkan ke PostgreSQL yang sudah ada

PostgreSQL dipasang/dikelola terpisah (server lain atau mesin yang sama).
Sunting konfigurasi:

```bash
sudo nano /etc/reptil/reptil.env
```

Isi minimal salah satu dari:

```ini
DATABASE_URL=postgresql+psycopg://reptil:PASSWORD@192.168.246.129:5432/aplikasireptil
# atau komponen terpisah:
DATABASE_HOST=192.168.246.129
DATABASE_PORT=5432
DATABASE_NAME=aplikasireptil
DATABASE_USER=reptil
DATABASE_PASSWORD=PASSWORD
```

Lalu:

```bash
sudo reptil-check        # uji koneksi
sudo reptil-migrate      # terapkan migrasi (alembic upgrade head)
sudo reptil-seed --with-demo --password 'Admin#2026'   # data awal (opsional)
sudo systemctl restart reptil
```

Akses: `http://<host>:<APP_PORT>/login`.

---

## 5. Port — mengapa tidak bentrok

| Port | Dipakai oleh | Dikelola oleh |
|---|---|---|
| 5432 (atau lainnya) | PostgreSQL | pemasangan PostgreSQL terpisah |
| 5050 (atau lainnya) | pgAdmin | pemasangan pgAdmin terpisah |
| 8000 | uvicorn dev (opsional) | developer |
| **8010+** | **REPTIL (paket ini)** | `postinst` cari yang bebas |

Paket REPTIL hanya membuka port aplikasi. Nilainya disimpan di `APP_PORT` pada
`/etc/reptil/reptil.env`, dan `reptil.service` (`ExecStart=/opt/reptil/bin/reptil-run`)
membacanya. Karena `postinst` memilih port yang **terbukti bebas** saat instalasi,
instalasi tidak akan gagal/bentrok. Jika Anda ingin port tetap, cukup tulis nilai
`APP_PORT` yang diinginkan (service akan gagal start bila port itu sudah dipakai —
ubah dan `systemctl restart reptil`).

Konfigurasi hanya dibuat **sekali**; upgrade paket tidak menimpa perubahan Anda.

---

## 6. Operasional

```bash
systemctl status reptil
journalctl -u reptil -f
sudo reptil-migrate                       # migrasi setelah upgrade kode
sudo systemctl restart reptil
```

Upgrade paket:

```bash
sudo apt install ./.deb-build/reptil_<versi-baru>_amd64.deb
```

Menghapus:

```bash
sudo apt remove reptil        # hentikan + lepas, /etc/reptil tetap ada
sudo apt purge reptil         # + hapus /etc/reptil dan akun sistem reptil
```

---

## 7. Catatan

- **Venv di dalam `.deb` menyimpang dari kebijakan Debian.** Peringatan lintian
  `dir-or-file-in-opt`, `embedded-library`, `unstripped-binary-or-object`, dan
  sejenisnya memang tidak terhindarkan; sebagian besar sudah diredam lewat
  `/usr/share/lintian/overrides/reptil` karena disengaja.
- Venv dibangun untuk **Python 3.12** di **amd64** — paket hanya jalan pada target
  dengan Python 3.12 (ditegakkan lewat `Depends: python3 (>= 3.12), python3 (<< 3.13)`).
  Untuk arsitektur/seri Python lain, bangun ulang di lingkungan yang sesuai.
- Untuk membangun di mesin tanpa jaringan, siapkan cache pip
  (`pip download -r ... -d ./wheelhouse`) lalu sesuaikan skrip build untuk memakai
  `--find-links ./wheelhouse --no-index`.
