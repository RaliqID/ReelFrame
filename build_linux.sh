#!/usr/bin/env bash
# Build a standalone ReelFrame for Linux (dir bundle + optional AppImage).
# Run on Linux:  bash build_linux.sh
set -e
cd "$(dirname "$0")"

echo "======================================================="
echo "  ReelFrame - Build Linux App"
echo "  Author: Raliq Hidayat BM3"
echo "======================================================="

if [ ! -x ".venv/bin/python" ]; then
  echo "[!] No venv. Running setup first..."
  bash setup.sh
fi

echo "[*] Ensuring PyInstaller + Linux webview backend are installed..."
.venv/bin/python -m pip install --upgrade pyinstaller
# pywebview on Linux uses GTK/Qt via WebKit; install the GTK extra.
.venv/bin/python -m pip install "pywebview[gtk]" || .venv/bin/python -m pip install pywebview

echo "[*] Building ReelFrame (Linux bundle)..."
.venv/bin/python -m PyInstaller ReelFrame.spec --noconfirm --clean

echo
echo "======================================================="
echo "  Build complete:  dist/ReelFrame/ReelFrame"
echo "  Run it directly, or create an AppImage (optional):"
echo "    - download appimagetool"
echo "    - see AppDir section in this script"
echo "======================================================="

# --- Optional AppImage packaging -------------------------------------------
# Uncomment to auto-build an AppImage if appimagetool is on PATH.
#
# APPDIR="build/ReelFrame.AppDir"
# rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/bin"
# cp -r dist/ReelFrame/* "$APPDIR/usr/bin/"
# cp web/icon.png "$APPDIR/reelframe.png"
# cat > "$APPDIR/ReelFrame.desktop" <<'EOF'
# [Desktop Entry]
# Name=ReelFrame
# Exec=ReelFrame
# Icon=reelframe
# Type=Application
# Categories=AudioVideo;Graphics;
# Comment=Local 4K AI Video & Image Upscaler
# EOF
# cat > "$APPDIR/AppRun" <<'EOF'
# #!/bin/bash
# HERE="$(dirname "$(readlink -f "${0}")")"
# exec "${HERE}/usr/bin/ReelFrame" "$@"
# EOF
# chmod +x "$APPDIR/AppRun"
# if command -v appimagetool >/dev/null 2>&1; then
#   appimagetool "$APPDIR" installer/output/ReelFrame-x86_64.AppImage
#   echo "AppImage: installer/output/ReelFrame-x86_64.AppImage"
# fi
