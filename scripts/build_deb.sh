#!/usr/bin/env bash
#
# build_deb.sh - membangun paket .deb REPTIL (aplikasi saja).
#
# Paket berisi:
#   /opt/reptil/app        kode aplikasi (src, migrations, scripts, alembic.ini)
#   /opt/reptil/venv       virtualenv Python + seluruh dependensi
#   /opt/reptil/bin        perintah reptil-run / -migrate / -seed / -check
#   /lib/systemd/system/reptil.service
#   /etc/reptil/reptil.env  (DIBUAT saat instalasi, bukan bagian paket)
#
# Paket TIDAK memuat PostgreSQL maupun pgAdmin.
#
# Pemakaian:
#   scripts/build_deb.sh
#   VERSION=0.2.0-1 scripts/build_deb.sh
#
# Hasil: .deb-build/reptil_<versi>_<arch>.deb
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG=reptil
PKGDIR="$ROOT/packaging"
ARCH="${ARCH:-$(dpkg --print-architecture)}"

if [ -z "${VERSION:-}" ]; then
    BASE="$(python3 - "$ROOT/pyproject.toml" <<'PY'
import sys, tomllib
print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])
PY
)"
    VERSION="${BASE}-1"
fi

BUILD="$ROOT/.deb-build"
STAGE="$BUILD/${PKG}_${VERSION}_${ARCH}"
APPDIR="$STAGE/opt/reptil/app"
VENVDIR="$STAGE/opt/reptil/venv"
FINAL_VENV="/opt/reptil/venv"

echo ">> REPTIL $VERSION ($ARCH) | Python $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"

# --- 0. Bersihkan -----------------------------------------------------------
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/reptil/bin" \
         "$STAGE/lib/systemd/system" \
         "$STAGE/usr/share/doc/$PKG" \
         "$STAGE/usr/share/reptil" \
         "$APPDIR"

# --- 1. Salin kode aplikasi -------------------------------------------------
echo ">> menyalin kode aplikasi"
cp -a "$ROOT/src" "$APPDIR/src"
cp -a "$ROOT/migrations" "$APPDIR/migrations"
cp -a "$ROOT/scripts" "$APPDIR/scripts"
install -m 0644 "$ROOT/alembic.ini"    "$APPDIR/alembic.ini"
install -m 0644 "$ROOT/pyproject.toml" "$APPDIR/pyproject.toml"
if [ -f "$ROOT/README.md" ]; then install -m 0644 "$ROOT/README.md" "$APPDIR/README.md"; fi
if [ -f "$ROOT/logo.jpeg" ]; then install -m 0644 "$ROOT/logo.jpeg" "$APPDIR/logo.jpeg"; fi
find "$APPDIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APPDIR" -type f -name '*.pyc' -delete
# Skrip build tidak ikut dikirim ke dalam paket
rm -f "$APPDIR/scripts/build_deb.sh"

# --- 2. Virtualenv ----------------------------------------------------------
echo ">> membuat virtualenv (--copies)"
python3 -m venv --copies "$VENVDIR"
"$VENVDIR/bin/python" -m pip install --no-compile --upgrade pip wheel >/dev/null

REQ="$BUILD/runtime-requirements.txt"
python3 - "$ROOT/pyproject.toml" "$REQ" <<'PY'
import sys, tomllib
deps = tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]
with open(sys.argv[2], "w") as fh:
    fh.write("\n".join(deps) + "\n")
PY

echo ">> memasang dependensi dari pyproject.toml"
"$VENVDIR/bin/python" -m pip install --no-compile --requirement "$REQ" >/dev/null

# Buang cache bytecode agar tidak memicu peringatan lintian
find "$VENVDIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$VENVDIR" -type f -name '*.pyc' -delete

# --- 3. Tulis ulang path venv ke lokasi final -------------------------------
echo ">> menyesuaikan path venv -> $FINAL_VENV"
if grep -rIl -e "^#!$VENVDIR" "$VENVDIR/bin" > "$BUILD/_shebangs.txt" 2>/dev/null; then :; fi
while IFS= read -r f; do
    sed -i "1s|^#!$VENVDIR|#!$FINAL_VENV|" "$f"
done < "$BUILD/_shebangs.txt"
for f in activate activate.csh activate.fish; do
    if [ -f "$VENVDIR/bin/$f" ]; then
        sed -i "s|$VENVDIR|$FINAL_VENV|g" "$VENVDIR/bin/$f"
    fi
done
sed -i "s|$VENVDIR|$FINAL_VENV|g" "$VENVDIR/pyvenv.cfg"

# --- 4. Berkas paket --------------------------------------------------------
echo ">> memasang berkas paket"
install -m 0755 "$PKGDIR/bin/reptil-run"     "$STAGE/opt/reptil/bin/reptil-run"
install -m 0755 "$PKGDIR/bin/reptil-migrate" "$STAGE/opt/reptil/bin/reptil-migrate"
install -m 0755 "$PKGDIR/bin/reptil-seed"    "$STAGE/opt/reptil/bin/reptil-seed"
install -m 0755 "$PKGDIR/bin/reptil-check"   "$STAGE/opt/reptil/bin/reptil-check"
install -m 0644 "$PKGDIR/reptil.service"     "$STAGE/lib/systemd/system/reptil.service"
install -m 0644 "$PKGDIR/reptil.env.example" "$STAGE/usr/share/reptil/reptil.env.example"
install -m 0644 "$PKGDIR/free_port.py"       "$STAGE/usr/share/reptil/free_port.py"
mkdir -p "$STAGE/usr/share/lintian/overrides"
install -m 0644 "$PKGDIR/lintian-overrides"  "$STAGE/usr/share/lintian/overrides/$PKG"
install -m 0644 "$PKGDIR/copyright"          "$STAGE/usr/share/doc/$PKG/copyright"
gzip -9n -c "$PKGDIR/changelog" > "$STAGE/usr/share/doc/$PKG/changelog.Debian.gz"
if [ -f "$ROOT/README.md" ]; then install -m 0644 "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/README.md"; fi

install -m 0755 "$PKGDIR/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$PKGDIR/prerm"    "$STAGE/DEBIAN/prerm"
install -m 0755 "$PKGDIR/postrm"   "$STAGE/DEBIAN/postrm"

# --- 4b. Normalisasi izin (hindari 0664/0775 dari umask mesin build) --------
echo ">> menormalkan izin berkas"
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -name '*.so' -exec chmod 0644 {} +
find "$STAGE" -type f -name '*.so.*' -exec chmod 0644 {} +
# Modul .py tidak pernah perlu executable (diimpor, bukan dijalankan langsung)
find "$VENVDIR/lib" -type f -name '*.py' -exec chmod 0644 {} +
# Skrip aplikasi memang bisa dieksekusi langsung
find "$APPDIR/scripts" -type f -name '*.py' -exec chmod 0755 {} +
find "$STAGE" -type f -perm /111 -exec chmod 0755 {} +
find "$STAGE" -type f ! -perm /111 -exec chmod 0644 {} +

# --- 5. DEBIAN/control (Version + Installed-Size) ---------------------------
SIZE="$(du -sk "$STAGE" | cut -f1)"
sed -e "s|^Version:.*|Version: $VERSION|" \
    -e "s|^Architecture:.*|Architecture: $ARCH|" \
    -e "s|^Installed-Size:.*|Installed-Size: $SIZE|" \
    "$PKGDIR/control" > "$STAGE/DEBIAN/control"
chmod 0644 "$STAGE/DEBIAN/control"

# --- 6. Bangun paket --------------------------------------------------------
OUT="$BUILD/${PKG}_${VERSION}_${ARCH}.deb"
echo ">> dpkg-deb --build"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT" >/dev/null

echo
echo ">> SELESAI: $OUT"
ls -lh "$OUT"
echo
echo "Instalasi:  sudo apt install \"$OUT\""
echo "   (atau)   sudo dpkg -i \"$OUT\" && sudo apt-get -f install"
