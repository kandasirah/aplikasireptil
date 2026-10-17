# Panduan Rilis & Build .deb

Cara merilis versi baru REPTIL dan membangun paket `.deb` otomatis lewat GitHub Actions.

## Prinsip

Workflow `.github/workflows/release.yml` hanya terpicu pada dua kondisi:

1. **Push tag `v*`** → build `.deb` + buat GitHub Release otomatis.
2. **Jalankan manual** (tab Actions → Run workflow) → build `.deb` sebagai artifact (bukan release).

Push biasa ke `main` **tidak** memicu build. Hanya tag yang menjadi penanda rilis resmi.

## Langkah Rilis Baru

```bash
# 1. Naikkan versi di pyproject.toml
#    Contoh: 0.1.0 -> 0.1.1
sed -i 's/^version = "0.1.0"/version = "0.1.1"/' pyproject.toml

# 2. Commit perubahan versi
git add pyproject.toml
git commit -m "release: bump versi ke 0.1.1"
git push origin main

# 3. Buat tag annotated dan push — workflow otomatis berjalan
git tag -a v0.1.1 -m "Release v0.1.1"
git push origin v0.1.1
```

Setelah tag ter-push, pantau proses build di:

<https://github.com/kandasirah/aplikasireptil/actions>

Jika sukses, GitHub Release otomatis dibuat dengan file `.deb` terlampir.

## Konvensi Penomoran Versi

- Format: `MAJOR.MINOR.PATCH` (contoh `0.1.0`, `0.2.1`).
- `PATCH` — perbaikan bug, tidak ada fitur baru.
- `MINOR` — fitur baru, backward compatible.
- `MAJOR` — perubahan besar / breaking change.
- Tag selalu diawali `v` (contoh `v0.1.1`), cocok dengan pola `v*` di workflow.
- Versi di `pyproject.toml` **harus cocok** dengan tag (tanpa awalan `v`).

## Versi di `pyproject.toml` vs Tag

| `pyproject.toml` | Tag      | `.deb` hasil   |
|------------------|----------|----------------|
| `0.1.0`          | `v0.1.0` | `reptil_0.1.0-1_amd64.deb` |
| `0.1.1`          | `v0.1.1` | `reptil_0.1.1-1_amd64.deb` |
| `0.2.0`          | `v0.2.0` | `reptil_0.2.0-1_amd64.deb` |

## Build Manual (tanpa release)

Bila ingin mencoba build tanpa membuat release:

1. Buka tab **Actions** di GitHub.
2. Pilih workflow **Build DEB**.
3. Klik **Run workflow**.
4. Hasil `.deb` tersedia sebagai artifact (retensi 7 hari).

## Catatan Teknis

- Workflow memerlukan `permissions: contents: write` (sudah diatur) untuk membuat release.
- Token `GITHUB_TOKEN` bawaan dipakai — tidak perlu secret tambahan.
- Build dijalankan di `ubuntu-24.04` dengan Python 3.12.
- Versi `.deb` diturunkan dari `pyproject.toml` + sufiks `-1` (Debian revision).
- File `.deb` ditemukan otomatis di `.deb-build/` setelah `scripts/build_deb.sh` selesai.

## Troubleshooting

| Masalah | Penyebab | Solusi |
|---------|----------|--------|
| Workflow tidak jalan saat push tag | Workflow belum terdaftar saat tag diterima | Re-tag di commit terbaru, lalu push ulang |
| Build gagal: file `.deb` tidak ditemukan | `scripts/build_deb.sh` error | Jalankan build lokal untuk debug |
| Versi `.deb` salah | `pyproject.toml` tidak di-bump sebelum tag | Update versi, re-tag, push ulang |
| Release tidak dibuat | `permissions` atau `GITHUB_TOKEN` bermasalah | Pastikan `contents: write` ada di workflow |
