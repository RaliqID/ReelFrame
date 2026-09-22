#!/usr/bin/env bash
# ReelFrame — macOS / Linux native window launcher (pywebview)
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[!] Virtual environment not found. Running setup first..."
  bash setup.sh
fi

echo "======================================================="
echo "  ReelFrame - Native Desktop Window"
echo "======================================================="
exec .venv/bin/python desktop_app.py
