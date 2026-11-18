#!/bin/sh
# One-click user-level install from the portable tarball. No root needed.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ukui-dynamic-island"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

printf '安装到 %s ...\n' "$APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -a "$HERE/ukui-dynamic-island" "$APP_DIR/app"

mkdir -p "$BIN_DIR" "$DESKTOP_DIR"
ln -sf "$APP_DIR/app/ukui-dynamic-island" "$BIN_DIR/ukui-dynamic-island"

sed "s#@EXEC@#$APP_DIR/app/ukui-dynamic-island#" "$HERE/ukui-dynamic-island.desktop" \
  > "$DESKTOP_DIR/ukui-dynamic-island.desktop"

printf '\n完成。\n  启动: ukui-dynamic-island  或从应用菜单打开“UKUI 灵动岛”\n'
printf '  卸载: rm -rf "%s" "%s/ukui-dynamic-island.desktop" "%s/ukui-dynamic-island"\n' \
  "$APP_DIR" "$DESKTOP_DIR" "$BIN_DIR"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf '  提示: %s 不在 PATH 中\n' "$BIN_DIR" ;;
esac
