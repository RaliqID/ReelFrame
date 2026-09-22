#!/usr/bin/env bash
# ReelFrame — macOS / Linux setup
# Author: Raliq Hidayat BM3
set -e
cd "$(dirname "$0")"

echo "======================================================="
echo "  ReelFrame - AI Environment Setup (macOS / Linux)"
echo "  Author: Raliq Hidayat BM3"
echo "======================================================="

if [ ! -d ".venv" ]; then
  echo "[*] Creating Python virtual environment in .venv ..."
  python3 -m venv .venv
fi

echo "[*] Upgrading pip..."
.venv/bin/python -m pip install --upgrade pip

# Apple Silicon / macOS: install plain torch (MPS acceleration is built in).
# On Linux with an NVIDIA GPU you may prefer the CUDA wheel instead.
if [[ "$(uname)" == "Darwin" ]]; then
  echo "[*] macOS detected - installing PyTorch (Metal/MPS support)..."
  .venv/bin/python -m pip install torch torchvision
else
  echo "[*] Linux detected - installing PyTorch (CUDA 12.4)..."
  .venv/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 || \
    .venv/bin/python -m pip install torch torchvision
fi

echo "[*] Installing dependencies from requirements.txt..."
.venv/bin/python -m pip install -r requirements.txt

echo "[*] Downloading default AI models..."
.venv/bin/python download_models.py default || true

echo
echo "======================================================="
echo "  Setup complete!"
echo "  Run:  ./run_gui.sh    (web dashboard)"
echo "        ./run_app.sh    (native window)"
echo "======================================================="
