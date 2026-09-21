# ReelFrame 🎬⚡

### Local 4K AI Video & Image Super-Resolution Engine
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CUDA](https://img.shields.io/badge/CUDA-12.4%2B-green.svg)](https://developer.nvidia.com/cuda-toolkit)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.6-orange.svg)](https://pytorch.org)
[![Python](https://img.shields.io/badge/Python-3.11%2B-yellow.svg)](https://python.org)
[![Author](https://img.shields.io/badge/Author-Raliq%20Hidayat%20BM3-purple.svg)](https://github.com/kouji999)

**ReelFrame** is a professional-grade, fully local AI super-resolution pipeline for creators and video editors. Upscale vertical reels, shorts, cinematic footage, and photos to pristine 4K on your own GPU — zero cloud, zero subscriptions.

Uses **Real-ESRGAN** + **NVIDIA NVENC hardware acceleration** through a zero-disk streaming pipeline. Available as a **Web Dashboard**, **Windows Native App**, and **iOS Mobile Companion**.

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
| 🧠 **AI Super-Resolution** | Real-ESRGAN models (SRVGGNet + RRDBNet) — photo-realistic 4K upscaling |
| ⚡ **GPU Accelerated** | CUDA fp16 inference, threaded pipe, >95% GPU utilization |
| 🛡️ **4GB VRAM Safe** | Smart overlapping tiling — zero CUDA OOM on RTX 3050/4GB cards |
| 🎬 **Video + Photo** | MP4, MOV, MKV, WebM, PNG, JPG, WebP — all in one engine |
| 📂 **Batch Processing** | Drop a whole folder, upscale everything in one command |
| 🔊 **Bit-Perfect Audio** | Audio stream copied without re-encoding |
| 🌐 **Web Dashboard** | Live progress, presets, history, real-time queue |
| 🖥️ **Windows Desktop App** | Native WebView2 window (no browser needed) |
| 📱 **iOS Companion** | Control ReelFrame from your iPhone via WiFi |
| 🎛️ **Social Presets** | Reels 4K, Cinema 4K, Photo Sharp, Anime — one click |
| 🔧 **Denoise & Sharpen** | Pre-upscale denoising + post-upscale unsharp mask |

---

## 💻 Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| **GPU** | NVIDIA 4GB VRAM (RTX 3050 Laptop), CUDA 11.8+ | RTX 3060 / 4060 Ti / 4090 |
| **RAM** | 8 GB | 16 GB+ |
| **OS** | Windows 10/11 64-bit | Windows 11 |
| **Python** | 3.11+ | 3.13 |

---

## 🚀 Quick Start — Windows

### Option 1: Web Dashboard (Recommended)
```batch
setup.bat        ← first-time setup (installs everything)
run_gui.bat      ← opens http://127.0.0.1:7860 in your browser
```

### Option 2: Native Desktop App
```batch
setup.bat        ← first-time setup
run_app.bat      ← launches as a native Windows window
```

### Option 3: CLI
```powershell
# Activate venv
.venv\Scripts\activate

# Upscale a reel (1080p → 4K vertical)
python upscale.py input.mp4

# Upscale a photo
python upscale.py photo.png -o photo_4k.png

# Batch upscale folder
python upscale.py "D:\Reels\" -o "D:\Reels\4K"

# Custom quality + denoise + sharpen
python upscale.py clip.mp4 --cq 18 --denoise 0.3 --sharpen 0.5
```

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
| `--model` | `realesr-general-x4v3.pth` | Model weights (in `./models/`) |
| `--downscale` | `0.5` | Post-SR scale (0.5 + x4 = 2× output) |
| `--tile` | `512` | Tile size for VRAM safety (`0` = disabled) |
| `--cq` | `20` | NVENC quality (16=best, 28=smallest) |
| `--preset` | `p4` | NVENC speed (`p1`=fastest … `p7`=best) |
| `--encoder` | `hevc_nvenc` | `hevc_nvenc`, `h264_nvenc`, `av1_nvenc`, `libx265` |
| `--format` | `mp4` | Output container / image format |
| `--denoise` | `0.0` | Pre-upscale Gaussian blur (0–1) |
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
├── upscale.py          — Core AI engine (video + image + batch)
├── gui.py              — FastAPI web server + REST API
├── desktop_app.py      — Windows native desktop app (WebView2)
├── web/
│   └── index.html      — Web dashboard UI (4 tabs + history + queue)
├── ios-app/
│   ├── App.tsx         — React Native iOS companion app
│   ├── app.json        — Expo config + iOS permissions
│   └── package.json    — RN dependencies
├── models/             — AI model weights (.pth)
├── outputs/            — Processed 4K output files
├── download_models.py  — Model weight downloader
├── setup.bat           — Automated Windows setup
├── run_gui.bat         — Start web dashboard
├── run_app.bat         — Start native desktop app
└── download_models.bat — Download model weights (Windows)
```

---

## 👨‍💻 Author

**Raliq Hidayat BM3**
- GitHub: [@kouji999](https://github.com/kouji999)
- Repository: [github.com/kouji999/ReelFrame](https://github.com/kouji999/ReelFrame)

---

## 📜 License

MIT — see [LICENSE](LICENSE). Pretrained model weights are subject to their own licenses (Real-ESRGAN / GFPGAN).
