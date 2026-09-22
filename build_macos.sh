#!/usr/bin/env bash
# Build ReelFrame.app for macOS.
# Run on a Mac:  bash build_macos.sh
set -e
cd "$(dirname "$0")"

echo "======================================================="
echo "  ReelFrame - Build macOS App"
echo "  Author: Raliq Hidayat BM3"
echo "======================================================="

# Need the icon in .icns form for the .app bundle.
if [ ! -f "web/icon.icns" ]; then
  echo "[*] Creating web/icon.icns from web/icon.png ..."
  if command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
    mkdir -p web/icon.iconset
    for s in 16 32 64 128 256 512 1024; do
      sips -z $s $s web/icon.png --out "web/icon.iconset/icon_${s}x${s}.png" >/dev/null
      d=$((s*2))
      sips -z $d $d web/icon.png --out "web/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns web/icon.iconset -o web/icon.icns
    rm -rf web/icon.iconset
  else
    echo "[!] iconutil/sips not found; copying PNG as placeholder icns."
    cp web/icon.png web/icon.icns
  fi
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[!] No venv. Running setup first..."
  bash setup.sh
fi

echo "[*] Ensuring PyInstaller + macOS webview backend are installed..."
.venv/bin/python -m pip install --upgrade pyinstaller
.venv/bin/python -m pip install "pywebview[macos]" pyobjc-framework-WebKit || .venv/bin/python -m pip install pywebview

echo "[*] Building ReelFrame.app ..."
.venv/bin/python -m PyInstaller ReelFrame-macos.spec --noconfirm --clean

echo
echo "======================================================="
echo "  Build complete:  dist/ReelFrame.app"
echo "  Drag it into /Applications, then double-click to run."
echo "  (First launch may need: right-click → Open, to allow it.)"
echo "======================================================="
