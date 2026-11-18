#!/bin/sh
# Build the arm64 .deb + portable tarball with the distro PySide2 package.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

PYTHON=${PYTHON:-python3}
VENV="$ROOT/.build-venv-arm64"
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/pip" -q install "pyinstaller==6.11.1" "jeepney>=0.8"

VERSION=$("$VENV/bin/python" -c "import island; print(island.__version__)")
OUT="$ROOT/out-arm64"
rm -rf "$ROOT/build-arm64" "$ROOT/dist-arm64" "$OUT"
mkdir -p "$OUT"

printf '== PyInstaller %s (arm64)\n' "$VERSION"
"$VENV/bin/pyinstaller" --clean --noconfirm \
  --distpath "$ROOT/dist-arm64" --workpath "$ROOT/build-arm64" \
  "$ROOT/packaging/ukui-dynamic-island.spec"

printf '== .deb (arm64)\n'
PKG="$ROOT/build-arm64/deb"
mkdir -p "$PKG/opt/ukui-dynamic-island" "$PKG/usr/bin" \
  "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps" \
  "$PKG/usr/share/doc/ukui-dynamic-island" "$PKG/DEBIAN"
cp -a "$ROOT/dist-arm64/ukui-dynamic-island/." "$PKG/opt/ukui-dynamic-island/"
ln -sf /opt/ukui-dynamic-island/ukui-dynamic-island "$PKG/usr/bin/ukui-dynamic-island"
cp "$ROOT/packaging/deb/usr/share/applications/ukui-dynamic-island.desktop" \
  "$PKG/usr/share/applications/"
cp "$ROOT/assets/ukui-dynamic-island.svg" \
  "$PKG/usr/share/icons/hicolor/scalable/apps/ukui-dynamic-island.svg"
cp "$ROOT/LICENSE" "$PKG/usr/share/doc/ukui-dynamic-island/copyright"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$PKG/usr/share/doc/ukui-dynamic-island/"
cp "$ROOT/packaging/deb/DEBIAN/postinst" "$ROOT/packaging/deb/DEBIAN/postrm" "$PKG/DEBIAN/"
chmod 0755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
SIZE=$(du -sk "$PKG" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" \
  -e "s/^Architecture: amd64$/Architecture: arm64/" \
  "$ROOT/packaging/deb/DEBIAN/control.in" > "$PKG/DEBIAN/control"
chmod 0644 "$PKG/DEBIAN/control"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/ukui-dynamic-island_${VERSION}_arm64.deb" >/dev/null

printf '== portable tar.gz (arm64)\n'
PORT="$ROOT/build-arm64/portable"
mkdir -p "$PORT"
cp -a "$ROOT/dist-arm64/ukui-dynamic-island" "$PORT/ukui-dynamic-island"
cp "$ROOT/packaging/portable/run.sh" "$PORT/run.sh"
cp "$ROOT/packaging/portable/ukui-dynamic-island.desktop" "$PORT/ukui-dynamic-island.desktop"
cp "$ROOT/packaging/install.sh" "$PORT/install.sh"
cp "$ROOT/LICENSE" "$ROOT/THIRD_PARTY_NOTICES.md" "$PORT/"
chmod 0755 "$PORT/run.sh" "$PORT/install.sh"
tar -C "$PORT" -czf "$OUT/ukui-dynamic-island-${VERSION}-aarch64.tar.gz" .

printf '== checksums\n'
(cd "$OUT" && sha256sum ./* > SHA256SUMS.txt && cat SHA256SUMS.txt)
printf '\n产物: %s\n' "$OUT"
