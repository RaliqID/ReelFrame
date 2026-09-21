#!/usr/bin/env python3
"""
Download pretrained Real-ESRGAN / GFPGAN weights into ./models.

Author: Raliq Hidayat BM3
Repository: https://github.com/kouji999/local-4k-upscaler

Run once after cloning or setting up:
    python download_models.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODELS = {
    # Default fast model — SRVGGNet, x4 scale, ~5 MB.
    # Designed for general video; use with `--downscale 0.5` to land on x2 effective.
    "realesr-general-x4v3.pth": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/"
        "v0.2.5.0/realesr-general-x4v3.pth",
        4_885_111,
    ),
    # High-quality photo model — RRDB, x4 scale, ~67 MB.
    "RealESRGAN_x4plus.pth": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/"
        "v0.1.0/RealESRGAN_x4plus.pth",
        67_021_117,
    ),
    # High-quality 2x model — RRDB, x2 scale, ~67 MB. Slower but great for
    # heavily degraded sources (JPEG noise, low res, scratches).
    "RealESRGAN_x2plus.pth": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/"
        "v0.2.1/RealESRGAN_x2plus.pth",
        67_061_725,
    ),
    # Anime optimized model — ~18 MB.
    "RealESRGAN_x4plus_anime_6B.pth": (
        "https://github.com/xinntao/Real-ESRGAN/releases/download/"
        "v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        18_787_160,
    ),
    # Optional face-restoration model (~349 MB).
    "GFPGANv1.4.pth": (
        "https://github.com/TencentARC/GFPGAN/releases/download/"
        "v1.3.0/GFPGANv1.4.pth",
        348_632_874,
    ),
}

OUT_DIR = Path(__file__).resolve().parent / "models"


def fetch(url: str, dest: Path, expected_size: int | None = None) -> None:
    """Stream `url` to `dest` with a clean progress bar."""
    print(f"--> Downloading {dest.name}...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req) as resp, dest.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or expected_size or 0)
        read = 0
        chunk = 1 << 20  # 1 MB
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            out.write(buf)
            read += len(buf)
            if total:
                pct = 100.0 * read / total
                bar = "#" * int(pct / 2)
                mb_read = read / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                print(f"\r    [{bar:<50}] {pct:5.1f}% ({mb_read:.1f}/{mb_total:.1f} MB)",
                      end="", flush=True)
        print()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])  # optional name filter (e.g. python download_models.py default)

    # By default, prioritize essential models if no specific argument is given
    targets = MODELS.items()
    if "default" in only:
        only = {"realesr-general-x4v3.pth"}

    for name, (url, size) in targets:
        if only and name not in only and not any(arg in name for arg in only):
            continue
        dest = OUT_DIR / name
        if dest.exists() and dest.stat().st_size == size:
            print(f"== {name}: already present, skipping")
            continue
        try:
            fetch(url, dest, size)
        except Exception as e:
            print(f"!! Failed to download {name}: {e}", file=sys.stderr)
            if name == "realesr-general-x4v3.pth":
                return 1

    print(f"\nAll done! Weights are in: {OUT_DIR.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
