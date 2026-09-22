# ReelFrame 🎬⚡

### Local 4K AI Video & Image Super-Resolution Engine
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CUDA](https://img.shields.io/badge/CUDA-12.4%2B-green.svg)](https://developer.nvidia.com/cuda-toolkit)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.6-orange.svg)](https://pytorch.org)
[![Python](https://img.shields.io/badge/Python-3.11%2B-yellow.svg)](https://python.org)
[![Author](https://img.shields.io/badge/Author-Raliq%20Hidayat%20BM3-purple.svg)](https://github.com/kouji999)

**ReelFrame** is a professional-grade, fully local AI super-resolution pipeline for creators and video editors. Upscale vertical reels, shorts, cinematic footage, and photos to pristine 4K on your own GPU — zero cloud, zero subscriptions.

Uses **Real-ESRGAN** for AI super-resolution with a zero-disk streaming pipeline, and
auto-selects the fastest working video encoder (**H.264**, the most compatible format —
plays in every player and browser without extra codecs). Available as a **Web Dashboard**,
**Windows Native App**, and **iOS Mobile Companion**.

> **v2 — Reliability & True-4K update**
> - Fixed the *"app won't open — black window flashes then closes"* crash (console encoding).
> - Fixed video jobs **hanging forever** mid-encode (deadlock-proof pipeline).
> - Fixed outputs that played as **audio-only** (now always H.264).
> - Added a real **4K target mode** that adapts to any input size/aspect ratio.
> - Added **edge-preserving deblocking** so compressed sources don't produce block artifacts.
> - Jobs now run **one at a time** with auto tile sizing — typically **10–30× faster** than before.
> - History downloads a ready-to-use **.zip** straight to your Downloads folder.


---

```
                     ┌──────────────────────────────────────────┐
                     │    Web GUI (browser) / Desktop App       │
                     │    iOS Companion (same WiFi → PC GPU)    │
                     └──────────────────┬───────────────────────┘
                                        │
                    ┌───────────────────┼────────────────────┐
                    │                  │                      │
              Upload File           Queue Job             Job History
                    │                  │                      │
                    └──────────────────┴──────────────────────┘
                                        │
                              ┌─────────▼──────────┐
                              │   FastAPI Backend   │
                              │   (gui.py server)   │
                              └─────────┬──────────┘
                                        │
                ┌───────────────────────┼──────────────────────────┐
                │                       │                           │
         Decoder Thread          GPU Inference              Encoder Thread
        (ffmpeg → rgb24)    (Real-ESRGAN + Tiling)     (HEVC NVENC → MP4)
                │                       │                           │
                └───────────────────────┴───────────────────────────┘
                                        │
                              ┌─────────▼──────────┐
                              │  4K UHD Master Out  │
                              │  (Zero temp files)  │
                              └────────────────────┘
```

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 **AI Super-Resolution** | Real-ESRGAN models (SRVGGNet + RRDBNet) — photo-realistic upscaling |
| 🎯 **True 4K Target** | Pick "4K" and any source becomes genuine 4K UHD (auto-adapts aspect ratio) |
| ⚡ **GPU Accelerated** | CUDA fp16 inference, threaded pipe; auto CPU fallback when NVENC is unavailable |
| 🛡️ **4GB VRAM Safe** | Auto tile sizing — full-frame for small sources, tiling only when needed (no OOM) |
| 🎬 **Video + Photo** | MP4, MOV, MKV, WebM, PNG, JPG, WebP — all in one engine |
| 🔧 **Compression Cleanup** | Edge-preserving deblocking stops block artifacts on compressed sources (WhatsApp etc.) |
| 🎞️ **Universal Playback** | Outputs H.264 by default — plays natively on Windows, browsers, and phones |
| 📂 **Batch Processing** | Drop a whole folder, upscale everything (serialized for max throughput) |
| 🔊 **Audio Preserved** | Audio re-encoded to AAC so the track always plays |
| 🌐 **Web Dashboard** | Live progress, real-time queue, history, system info |
| 🗜️ **Zip Downloads** | History downloads a `.zip` (original-format file inside) to your Downloads folder |
| 🖥️ **Windows Desktop App** | Native WebView2 window + crash log & error dialog (never fails silently) |
| 📱 **iOS Companion** | Control ReelFrame from your iPhone via WiFi |
| 🔧 **Denoise & Sharpen** | Pre-upscale cleanup + post-upscale unsharp mask |

---

## 💻 Hardware & OS Requirements

| Component | Minimum | Recommended |
|---|---|---|
| **GPU** | NVIDIA 4 GB VRAM (RTX 3050), CUDA 11.8+ — *or* Apple Silicon (MPS) / CPU | RTX 3060 / 4060 Ti / 4090 |
| **RAM** | 8 GB | 16 GB+ |
| **OS** | Windows 10/11, macOS 12+, or Linux | Windows 11 / macOS Sonoma |
| **Python** | 3.11+ | 3.13 |

> **GPU acceleration:** NVIDIA CUDA is fastest. On macOS the Metal/MPS backend is used.
> NVENC hardware encoding is used automatically when available; otherwise the app falls
> back to a CPU encoder (`libx264`) so it always works — just slower.

---

## 🚀 Quick Start

### Windows

```batch
setup.bat        ← first-time setup (installs everything)
run_gui.bat      ← web dashboard  (http://127.0.0.1:7860)
run_app.bat      ← native desktop window
build_desktop.bat ← build dist\ReelFrame\ReelFrame.exe
```

### macOS / Linux

```bash
bash setup.sh    # first-time setup
bash run_gui.sh  # web dashboard (http://127.0.0.1:7860)
bash run_app.sh  # native window (pywebview)
```

### CLI (any OS)

```bash
.venv/bin/python upscale.py input.mp4 --target 4k     # macOS/Linux
.venv\Scripts\python.exe upscale.py input.mp4 --target 4k   # Windows
```

### CLI (any OS)

```bash
.venv/bin/python upscale.py input.mp4 --target 4k     # macOS/Linux
.venv\Scripts\python.exe upscale.py input.mp4 --target 4k   # Windows
```

---

## 📦 Get the App (Windows / macOS / Linux)

> **Important:** `.app` and `.dmg` **cannot be built on Windows** — PyInstaller does not
> cross-compile. Each OS builds on its own machine. Use one of the two ways below.

### ✅ Option A — Download a prebuilt app from GitHub (no Mac needed)

The repo includes a **cloud build** (`.github/workflows/build-apps.yml`) that compiles
Windows, macOS and Linux apps automatically:

1. Push a version tag to trigger it:
   ```bash
   git tag v2.0.0
   git push origin v2.0.0
   ```
   *(or go to **Actions → Build Apps → Run workflow** and run it manually)*
2. When it finishes, download from either:
   - the run's **Artifacts** section, or
   - the **Releases** page (when triggered by a tag)
3. You get:
   | OS | File | How to use |
   |---|---|---|
   | **Windows** | `ReelFrame-Setup-2.0.0.exe` | double-click to install |
   | **macOS** | `ReelFrame-2.0.0-macos.dmg` | open → drag **ReelFrame** into Applications |
   | **Linux** | `ReelFrame-2.0.0-x86_64.AppImage` | `chmod +x` then double-click |

> macOS note: the app is unsigned, so the first launch needs **right-click → Open**
> (or System Settings → Privacy & Security → Open Anyway).

### Option B — Build on your own machine

**Windows**
```batch
build_windows_installer.bat
```
→ `installer\output\ReelFrame-Setup-2.0.0.exe` (installer) and `dist\ReelFrame\ReelFrame.exe` (portable)

**macOS** (run on a Mac)
```bash
bash build_macos.sh
```
→ `dist/ReelFrame.app` — drag into `/Applications`

**Linux** (run on Linux)
```bash
bash build_linux.sh
```
→ `dist/ReelFrame/ReelFrame` (bundle; the script also shows how to make an `.AppImage`)

> Just want to *run* it without building? Use `run_app.bat` / `bash run_app.sh`
> (or `run_gui.*` for the browser dashboard) — see Quick Start above.

---

## 📱 iOS Companion App

Control ReelFrame from your iPhone on the same WiFi:
1. Run `run_app.bat` — note the **Network IP** displayed
2. Install [**Expo Go**](https://apps.apple.com/app/expo-go/id982107779) on iPhone
3. Open `ios-app/`, run `npm install && npx expo start`
4. Scan the QR code with Expo Go
5. Enter your PC's IP — you're connected!

See [IOS_COMPANION.md](IOS_COMPANION.md) for full setup guide.

---

## 🎛️ CLI Reference

| Flag | Default | Description |
|---|---|---|
| `input` | *required* | Video/image file or directory |
| `-o` / `--output` | `[name]_4K.[ext]` | Output path |
| `--target` | *(none)* | **`4k` / `2k` / `1080p`** — auto-adapts any input/aspect ratio to this size. Overrides `--downscale` |
| `--model` | `realesr-general-x4v3.pth` | Model weights (in `./models/`) |
| `--downscale` | `0.5` | Post-SR scale (0.5 + x4 = 2× output) |
| `--tile` | `-1` (auto) | Tile size (`-1` auto, `0` full-frame, e.g. `512` for very low VRAM) |
| `--cq` | `20` | Encoder quality CQ/CRF (lower = better, 18–23 typical) |
| `--preset` | `p4` | Encoder preset `p1` (fastest) … `p7` (best) |
| `--encoder` | `auto` | `auto`, `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `libx264`, `libx265` |
| `--format` | `mp4` | Output container / image format |
| `--denoise` | `0.0` | Pre-upscale cleanup strength (0–1) — auto-detects compressed sources |
| `--sharpen` | `0.0` | Post-upscale unsharp mask (0–2) |
| `--fp32` | off | Force float32 on GPU (slower, more precise) |
| `--verbose` | off | Show full ffmpeg output |

---

## 🧠 Supported Models

```batch
python download_models.py           # download all
python download_models.py default   # download default only (~5 MB)
```

| Model | Scale | Size | Best For |
|---|---|---|---|
| `realesr-general-x4v3.pth` | 4× | 5 MB | **Default** — fast video, general footage |
| `RealESRGAN_x4plus.pth` | 4× | 67 MB | Ultra-detailed photography |
| `RealESRGAN_x4plus_anime_6B.pth` | 4× | 18 MB | Anime, cartoons, 2D artwork |
| `RealESRGAN_x2plus.pth` | 2× | 67 MB | Degraded/noisy video restoration |
| `GFPGANv1.4.pth` | — | 349 MB | Face enhancement & recovery |

---

## 📁 Project Structure

```
ReelFrame/
├── upscale.py          — Core AI engine (video + image + batch + 4K target)
├── gui.py              — FastAPI web server + REST API
├── desktop_app.py      — Windows native desktop app (WebView2, crash-safe)
├── ReelFrame.spec      — PyInstaller build config (Windows/Linux, windowed, icon)
├── ReelFrame-macos.spec— PyInstaller build config (macOS .app bundle)
├── installer/
│   └── ReelFrame.iss   — Inno Setup script → ReelFrame-Setup.exe
├── make_icon.py        — Generates the brand .ico/.png
├── web/
│   ├── index.html      — Web dashboard UI (4 tabs + history + live queue)
│   ├── icon.ico        — App icon (also served as favicon)
│   └── icon.png        — App icon (PNG)
├── ios-app/            — React Native iOS companion (Expo)
├── models/             — AI model weights (.pth)
├── outputs/            — Processed output files (writable data dir)
├── test_startup_safety.py — Regression tests (encoding + filename safety)
├── test_api_e2e.py     — End-to-end API test suite
├── setup.bat / .sh     — Automated setup (Windows / macOS+Linux)
├── run_gui.bat / .sh   — Start web dashboard
├── run_app.bat / .sh   — Start native desktop app
├── build_desktop.bat   — Build portable Windows app
├── build_windows_installer.bat — Build portable app + installer
├── build_macos.sh      — Build macOS .app
├── build_linux.sh      — Build Linux bundle (+ optional AppImage)
└── download_models.py  — Model weight downloader
```

> **Where files are written:** running from source, outputs go to `./outputs/`.
> The packaged desktop app writes to `%LOCALAPPDATA%\ReelFrame\` (outputs, uploads,
> history, logs) so it never writes inside its own install folder.

---

## 👨‍💻 Author

**Raliq Hidayat BM3**
- GitHub: [@kouji999](https://github.com/kouji999)
- Repository: [github.com/kouji999/ReelFrame](https://github.com/kouji999/ReelFrame)

---

## 📜 License

MIT — see [LICENSE](LICENSE). Pretrained model weights are subject to their own licenses (Real-ESRGAN / GFPGAN).
