#!/usr/bin/env bash
# ReelFrame — macOS / Linux web dashboard launcher
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[!] Virtual environment not found. Running setup first..."
  bash setup.sh
fi

echo "======================================================="
echo "  ReelFrame - Local 4K AI Video & Image Upscaler"
echo "  Web dashboard: http://127.0.0.1:7860"
echo "======================================================="
exec .venv/bin/python gui.py
