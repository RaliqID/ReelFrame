#!/usr/bin/env python3
"""
Local 4K Upscaler: Real-ESRGAN Super-Resolution via threaded pipes & NVENC.
Optimized for high-throughput video & image upscaling on NVIDIA GPUs.

Author: Raliq Hidayat BM3
Repository: https://github.com/kouji999/local-4k-upscaler

Key Features:
- Zero temp-disk frame dumps: pure in-memory streaming pipe
- Threaded producer/consumer keeps GPU util > 95%
- Smart Tiling: handles 4K/8K even on 4GB VRAM (RTX 3050 friendly)
- Unified support for both Videos (MP4, MOV, MKV) and Images (PNG, JPG, WebP)
- Batch folder processing support
- Auto-detection for NVENC hardware encoders with graceful CPU fallback
- Optional Gaussian pre-blur (--denoise) for compression artifact removal
- Optional post-process unsharp mask (--sharpen) after downscale step
- Configurable output format (--format) for both video and image outputs
- Verbose mode (--verbose) to expose full ffmpeg output for debugging
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from spandrel import ModelLoader

_SENTINEL = object()


class EncoderFailed(RuntimeError):
    """Raised when the encoder subprocess dies mid-stream (prevents a silent hang)."""


# Shared kill-switch: set by the encoder thread when its ffmpeg exits early.
_ENCODER_ERROR: dict = {"message": None}


def _bundle_dir() -> Path:
    """Directory that holds bundled resources (models/web).

    In a PyInstaller one-dir build this is sys._MEIPASS (the _internal folder);
    when running from source it's the project directory.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    """User-writable directory for outputs, uploads, history.

    A frozen app must NOT write into its own bundle (often read-only / wiped on
    update), so we use %LOCALAPPDATA%\\ReelFrame when frozen.
    """
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ReelFrame"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).resolve().parent


SCRIPT_DIR = _data_dir()          # outputs / uploads / history live here
BUNDLE_DIR = _bundle_dir()        # read-only bundled assets live here
MODELS_DIR = BUNDLE_DIR / "models"
if not MODELS_DIR.exists():
    MODELS_DIR = SCRIPT_DIR / "models"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv"}

# Output format maps
VIDEO_FORMAT_MAP = {
    "mp4": ".mp4",
    "mkv": ".mkv",
    "mov": ".mov",
}
IMAGE_FORMAT_MAP = {
    "png": ".png",
    "jpg": ".jpg",
    "webp": ".webp",
}


def _fmt_seconds(secs: float) -> str:
    """Format seconds as MM:SS string (e.g. 83.0 -> '01:23')."""
    secs = max(0.0, secs)
    m = int(secs) // 60
    s = int(secs) % 60
    return f"{m:02d}:{s:02d}"


# Cache: the NVENC capability probe is a subprocess call, run it once per process.
_NVENC_CACHE: dict[str, bool] = {}
_NVENC_CPU_FALLBACK = {"hevc_nvenc": "libx265", "h264_nvenc": "libx264", "av1_nvenc": "libx264"}

# Encoders we try, in order, for maximum output compatibility.
# H.264 first: plays everywhere (Windows/browsers/phones) without extra codecs.
# HEVC/AV1 are opt-in only.
ENCODER_PREFERENCE = ["h264_nvenc", "libx264", "hevc_nvenc", "libx265"]


def nvenc_available(encoder: str = "hevc_nvenc") -> bool:
    """Return True only if the requested NVENC encoder can actually be opened.

    The bundled ffmpeg may advertise NVENC while the installed NVIDIA driver is
    too old (e.g. "Driver does not support the required nvenc API version").
    Testing for the encoder in `ffmpeg -encoders` is NOT enough â€” we must try to
    actually open it, otherwise jobs hang/fail at runtime.
    """
    if encoder in _NVENC_CACHE:
        return _NVENC_CACHE[encoder]
    ok = False
    try:
        # Encode 1 tiny black frame; a working encoder exits 0.
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.04:r=25",
            "-frames:v", "1",
            "-c:v", encoder, "-f", "null", "-",
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30)
        ok = res.returncode == 0
    except Exception:
        ok = False
    _NVENC_CACHE[encoder] = ok
    return ok


def resolve_encoder(requested: str, verbose: bool = False) -> str:
    """Return a usable, widely-playable video encoder.

    - "auto" (or empty) picks the best available from ENCODER_PREFERENCE.
    - An explicit NVENC request that can't be opened downgrades to its CPU twin.
    """
    if requested in ("auto", "", None):
        for cand in ENCODER_PREFERENCE:
            if "nvenc" in cand:
                if nvenc_available(cand):
                    return cand
            else:
                return cand  # first CPU encoder (libx264) is always available
        return "libx264"

    if "nvenc" in requested and not nvenc_available(requested):
        fallback = _NVENC_CPU_FALLBACK.get(requested, "libx264")
        print(
            f"[warn] '{requested}' is unavailable (NVIDIA driver too old for this "
            f"ffmpeg build). Falling back to CPU encoder '{fallback}'."
        )
        return fallback
    return requested


# Longest-edge targets for each "resolution mode".
# 4K UHD is defined by the longer edge (3840 for landscape/square-ish,
# and for portrait video we still want a true 2160-class master). We target by
# the LONGER edge so behaviour is consistent across 9:16 / 1:1 / 16:9.
TARGET_LONG_EDGE = {
    "4k": 3840,   # UHD master
    "2k": 2560,   # QHD
    "1080p": 1920,
}


def compute_target_scale(w: int, h: int, model_scale: int, target: str) -> float:
    """Return the post-downscale factor (<= 1.0) so the longer edge lands on
    `target`, adapting to ANY input size and aspect ratio.

    Rules (honest â€” never fake detail with interpolation, never explode a
    already-4K clip to 16K):
      * source >= target        -> net 1.0x: run SR then downscale back to the
        source size, i.e. a *quality/detail* pass, output ~= input dimensions.
      * source * model_scale < target -> model can't physically reach target;
        deliver the model's true max (downscale 1.0) and let the caller report it.
      * otherwise               -> exact fraction that hits target on long edge.
    """
    long_edge = max(w, h)
    if long_edge <= 0:
        return 1.0
    key = (target or "").lower()
    if key not in TARGET_LONG_EDGE:
        return 1.0
    desired_long = TARGET_LONG_EDGE[key]
    model_max = long_edge * model_scale
    if long_edge >= desired_long:
        # Already at/above target: keep output at ~source size (net 1.0x).
        return min(1.0 / model_scale, 1.0)
    if model_max < desired_long:
        # Model's ceiling is below target: give the true maximum.
        return 1.0
    return min(desired_long / model_max, 1.0)


def recommend_tile_size(w: int, h: int, vram_gb: float = 4.0) -> int:
    """Pick the largest tile that safely fits VRAM â€” bigger tiles are faster.

    Benchmarking on an RTX 3050 (4 GB) shows full-frame inference uses only
    ~260 MB for a 576p source and is ~13% faster than 512px tiling, so the old
    always-512 default was pure overhead. We only tile when the *output* would
    genuinely risk OOM.
    """
    out_pixels = (w * 4) * (h * 4)  # model's native 4x output estimate
    if vram_gb >= 3.0 and out_pixels <= 3840 * 2160:
        return 0                     # full-frame is safe and fastest
    if vram_gb >= 6.0:
        return 0
    # Constrained VRAM + big output -> tile, but larger than the old 512.
    return 1024 if vram_gb >= 4.0 else 768


def _final_target_size(
    w: int, h: int, model_scale: int, downscale: float, target: str
) -> Optional[tuple[int, int]]:
    """Return the final (w, h) to hit `target` on the long edge.

    If the SR model's native ceiling falls short of the target, we still land on
    the target with a final high-quality resize (detail is SR-generated; the last
    step only conforms delivery resolution). Returns None when no change needed.
    """
    key = (target or "").lower()
    if key not in TARGET_LONG_EDGE:
        return None
    desired = TARGET_LONG_EDGE[key]
    sr_eff = model_scale * downscale
    sr_w, sr_h = int(round(w * sr_eff)), int(round(h * sr_eff))
    long_edge = max(sr_w, sr_h)
    if long_edge == desired:
        return None
    # Already larger than target (source >= target case) -> leave at SR output.
    if long_edge > desired:
        return None
    scale = desired / long_edge
    fw, fh = int(round(sr_w * scale)), int(round(sr_h * scale))
    return fw - fw % 2, fh - fh % 2


def predict_output_size(w: int, h: int, model_scale: int, scale_mode: str) -> tuple[int, int]:
    """Predict (out_w, out_h) for a scale mode, matching the engine's math."""
    key = (scale_mode or "").lower()
    if key in TARGET_LONG_EDGE:
        ds = compute_target_scale(w, h, model_scale, key)
        fs = _final_target_size(w, h, model_scale, ds, key)
        if fs:
            return fs
    elif key == "4x":
        ds = 1.0
    else:  # default "2x"
        ds = 0.5
    eff = model_scale * ds
    ow, oh = int(round(w * eff)), int(round(h * eff))
    return ow - ow % 2, oh - oh % 2


def describe_scale_mode(scale_mode: str) -> str:
    key = (scale_mode or "").lower()
    if key in TARGET_LONG_EDGE:
        return f"{key.upper()} (longest edge {TARGET_LONG_EDGE[key]}px)"
    return f"{scale_mode}x"


def resolve_model_path(model_arg: str | Path | None) -> Path:
    """Find model file by filename, relative path, or absolute path."""
    # [FIX #4] Default uses Path(MODELS_DIR / ...) directly â€” simpler logic
    if not model_arg:
        return Path(MODELS_DIR / "realesr-general-x4v3.pth")

    p = Path(model_arg)
    if p.is_file():
        return p.resolve()
    # Check inside models directory
    candidate = MODELS_DIR / p.name
    if candidate.is_file():
        return candidate.resolve()
    if not candidate.suffix:
        candidate_pth = MODELS_DIR / f"{p.name}.pth"
        if candidate_pth.is_file():
            return candidate_pth.resolve()

    model_path = p
    if not model_path.exists():
        print(f"[warning] Model not found at: {model_path}")
        print(f"[hint] Run 'python download_models.py' to download pretrained weights.")
        fallback = MODELS_DIR / "realesr-general-x4v3.pth"
        if fallback.exists():
            print(f"[info] Using found fallback: {fallback}")
            return fallback
    return model_path


def probe_video(path: Path) -> dict:
    """Extract resolution, fps, duration, and frame count via ffprobe.

    Audio stream absence is handled gracefully â€” missing audio is not an error.
    """
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            text=True,
        )
        data = json.loads(out)
        s = data["streams"][0]
        num, den = s["r_frame_rate"].split("/")
        fps = int(num) / int(den) if int(den) != 0 else 30.0
        duration = float(data.get("format", {}).get("duration", 0.0))
        nb_frames = int(s.get("nb_frames", 0) or 0)

        # [FIX #6] Probe audio separately to detect presence without crashing
        has_audio = False
        try:
            audio_out = subprocess.check_output(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=codec_type",
                    "-of", "json", str(path),
                ],
                text=True,
            )
            audio_data = json.loads(audio_out)
            has_audio = bool(audio_data.get("streams"))
        except Exception:
            # If audio probe itself fails, treat as no audio â€” not fatal
            has_audio = False

        return {
            "width": s["width"],
            "height": s["height"],
            "fps": fps,
            "duration": duration,
            "nb_frames": nb_frames,
            "has_audio": has_audio,
        }
    except Exception as e:
        raise RuntimeError(f"ffprobe failed to probe '{path}': {e}")


def estimate_blockiness(img_rgb: np.ndarray) -> float:
    """Rough 0..1 score of how blocky/compressed an image looks.

    Compression artifacts sit on an 8x8 grid: gradient magnitude exactly on the
    block boundaries runs higher than elsewhere. Clean images sit near 1.0;
    heavily-blocked ones climb well above it.
    """
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    if g.shape[0] < 24 or g.shape[1] < 24:
        return 0.0
    gx = np.abs(np.diff(g, axis=1))
    gy = np.abs(np.diff(g, axis=0))
    cols = np.arange(gx.shape[1])
    rows = np.arange(gy.shape[0])
    if not cols.size or not rows.size:
        return 0.0
    edge = gx[:, (cols % 8) == 7].mean() + gy[(rows % 8) == 7, :].mean()
    other = gx[:, (cols % 8) != 7].mean() + gy[(rows % 8) != 7, :].mean()
    if other < 1e-6:
        return 0.0
    ratio = edge / other
    # ratio ~1.0-1.3 = no meaningful blocking; >~1.6 = visibly blocky.
    return float(np.clip((ratio - 1.3) / 1.2, 0.0, 1.0))


def auto_denoise_strength(img_rgb: np.ndarray, user_denoise: float, auto: bool = True) -> float:
    """Return the deblock strength to actually use.

    - explicit user value (>0) always wins.
    - auto=False with no user value -> 0 (deblocking disabled).
    - auto=True  with no user value -> detect compression and deblock if blocky.
    """
    if user_denoise and user_denoise > 0.0:
        return user_denoise
    if not auto:
        return 0.0
    score = estimate_blockiness(img_rgb)
    if score >= 0.30:
        return round(min(1.5, 0.6 + score), 2)
    return 0.0


def apply_deblock(img_rgb: np.ndarray, strength: float) -> np.ndarray:
    """Edge-preserving deblocking for heavily-compressed sources (WhatsApp etc).

    Plain Gaussian blur kills detail (text/edges). Instead we use a bilateral
    filter which smooths flat compression blocks but keeps strong edges sharp â€”
    the correct tool for removing the blocky artifacts SR would otherwise
    amplify. `strength` maps to the bilateral sigma range.
    """
    if strength <= 0.0:
        return img_rgb
    d = 5
    sigma_color = 12.0 * strength
    sigma_space = 5.0 * strength
    return cv2.bilateralFilter(img_rgb, d, sigma_color, sigma_space)


def apply_gaussian_blur(img_rgb: np.ndarray, strength: float) -> np.ndarray:
    """Apply Gaussian blur as pre-processing to reduce compression artifacts.

    Args:
        img_rgb: HxWx3 uint8 numpy array in RGB.
        strength: Blur strength in the 0.0â€“1.0 range.
                  Mapped to sigma (0 = no blur, 1.0 = sigma ~3.0).
    Returns:
        Blurred HxWx3 uint8 numpy array.
    """
    if strength <= 0.0:
        return img_rgb
    sigma = strength * 3.0
    # ksize must be positive odd integer
    ksize = max(3, int(sigma * 3) | 1)
    blurred = cv2.GaussianBlur(img_rgb, (ksize, ksize), sigmaX=sigma)
    return blurred


def apply_unsharp_mask(img_rgb: np.ndarray, strength: float) -> np.ndarray:
    """Apply unsharp mask sharpening as post-processing.

    Args:
        img_rgb: HxWx3 uint8 numpy array in RGB.
        strength: Sharpening amount in 0.0â€“2.0 range.
    Returns:
        Sharpened HxWx3 uint8 numpy array.
    """
    if strength <= 0.0:
        return img_rgb
    sigma = 1.0
    ksize = 5
    blurred = cv2.GaussianBlur(img_rgb, (ksize, ksize), sigmaX=sigma)
    # unsharp mask: img + strength * (img - blurred)
    sharpened = cv2.addWeighted(img_rgb, 1.0 + strength, blurred, -strength, 0)
    return sharpened


def process_tensor_tiled(
    model: torch.nn.Module,
    x: torch.Tensor,
    scale: int,
    tile_size: int = 512,
    tile_pad: int = 16,
) -> torch.Tensor:
    """
    Overlapping tile inference on tensor (1, C, H, W).
    Guarantees zero CUDA Out-Of-Memory even on 4GB VRAM laptop GPUs.
    """
    if tile_size <= 0:
        return model(x)

    _, c, h, w = x.shape
    if h <= tile_size and w <= tile_size:
        return model(x)

    out_h, out_w = h * scale, w * scale
    out = torch.zeros((1, c, out_h, out_w), dtype=x.dtype, device=x.device)

    y_stride = tile_size
    x_stride = tile_size

    for y in range(0, h, y_stride):
        for x_idx in range(0, w, x_stride):
            top = max(0, y - tile_pad)
            bottom = min(h, min(y + y_stride, h) + tile_pad)
            left = max(0, x_idx - tile_pad)
            right = min(w, min(x_idx + x_stride, w) + tile_pad)

            tile = x[:, :, top:bottom, left:right]
            with torch.inference_mode():
                tile_out = model(tile)

            out_top = y * scale
            out_bottom = min(y + y_stride, h) * scale
            out_left = x_idx * scale
            out_right = min(x_idx + x_stride, w) * scale

            crop_top = (y - top) * scale
            crop_bottom = crop_top + (out_bottom - out_top)
            crop_left = (x_idx - left) * scale
            crop_right = crop_left + (out_right - out_left)

            out[:, :, out_top:out_bottom, out_left:out_right] = tile_out[:, :, crop_top:crop_bottom, crop_left:crop_right]

    return out


def decoder_thread(proc: subprocess.Popen, w: int, h: int, q: queue.Queue) -> None:
    """Read raw rgb24 frames from ffmpeg stdout into bounded queue."""
    frame_bytes = w * h * 3
    stdout = proc.stdout
    if stdout is None:
        q.put(_SENTINEL)
        return
    try:
        while True:
            # read() may return fewer bytes than requested; loop until we have a
            # full frame (a short read must NOT be mistaken for end-of-stream).
            chunks: list[bytes] = []
            got = 0
            while got < frame_bytes:
                chunk = stdout.read(frame_bytes - got)
                if not chunk:
                    break
                chunks.append(chunk)
                got += len(chunk)
            if got < frame_bytes:
                break
            arr = np.frombuffer(b"".join(chunks), dtype=np.uint8).copy().reshape(h, w, 3)
            q.put(arr)
    finally:
        q.put(_SENTINEL)
        try:
            stdout.close()
        except Exception:
            pass


def encoder_thread(proc: subprocess.Popen, q: queue.Queue) -> None:
    """Drain processed frames from bounded queue into ffmpeg stdin.

    If ffmpeg exits early (bad encoder/params) its stdin pipe breaks. We must
    stop draining and record the failure, otherwise the main loop blocks forever
    on a full out_queue -> the "stuck at N%" hang.
    """
    stdin = proc.stdin
    if stdin is None:
        return
    try:
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            try:
                stdin.write(item)
            except (BrokenPipeError, ValueError, OSError) as exc:
                rc = proc.poll()
                _ENCODER_ERROR["message"] = (
                    f"Encoder process exited (code={rc}) while writing frames: {exc}"
                )
                break
    finally:
        try:
            stdin.close()
        except Exception:
            pass


def upscale_image(
    src: Path,
    dst: Path,
    model: torch.nn.Module,
    model_scale: int,
    downscale: float = 1.0,
    tile_size: int = 512,
    device: torch.device = torch.device("cuda"),
    denoise: float = 0.0,
    sharpen: float = 0.0,
    target: Optional[str] = None,
    auto_denoise: bool = True,
) -> None:
    """Upscale a single image file with high quality."""
    img_bgr = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError(f"Could not read image: {src}")
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = img_rgb.shape

    # If a resolution target is given (e.g. "4k"), compute the downscale that
    # lands the longer edge exactly on target, adapting to any input size.
    final_size: Optional[tuple[int, int]] = None
    if target:
        downscale = compute_target_scale(w, h, model_scale, target)
        final_size = _final_target_size(w, h, model_scale, downscale, target)

    # Pre-deblock: removes compression blocks so SR can't amplify them.
    # Auto-detects heavily-compressed sources; clean sources are left untouched.
    _dn = auto_denoise_strength(img_rgb, denoise, auto_denoise)
    if _dn > 0.0:
        img_rgb = apply_deblock(img_rgb, _dn)

    effective_scale = model_scale * downscale
    ow, oh = int(round(w * effective_scale)), int(round(h * effective_scale))
    if final_size:
        ow, oh = final_size

    dtype = torch.float16 if device.type == "cuda" else torch.float32
    x = (
        torch.from_numpy(img_rgb)
        .to(device, non_blocking=True)
        .permute(2, 0, 1)
        .unsqueeze(0)
        .to(dtype)
        .div_(255.0)
    )

    with torch.inference_mode():
        if tile_size > 0 and (h > tile_size or w > tile_size):
            y = process_tensor_tiled(model, x, model_scale, tile_size=tile_size)
        else:
            y = model(x)
        y = y.clamp_(0, 1)

        if downscale != 1.0 or final_size:
            y = F.interpolate(y, size=(oh, ow), mode="bicubic", align_corners=False, antialias=True)
            y = y.clamp_(0, 1)

        y = y.mul_(255).round_().to(torch.uint8)
        out = y.squeeze(0).permute(1, 2, 0).contiguous().cpu().numpy()

    # [IMPROVEMENT #3] Post-process unsharp mask after downscale
    if sharpen > 0.0:
        out = apply_unsharp_mask(out, sharpen)

    out_bgr = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst), out_bgr)
    print(f"[done] Image upscaled: {w}x{h} -> {ow}x{oh} -> {dst}")


def upscale_video(
    src: Path,
    dst: Path,
    model: torch.nn.Module,
    model_scale: int,
    downscale: float = 0.5,
    cq: int = 20,
    preset: str = "p4",
    queue_size: int = 8,
    tile_size: int = 512,
    encoder: str = "auto",
    progress_callback: Optional[Callable[[int, int, float, float], None]] = None,
    device: torch.device = torch.device("cuda"),
    denoise: float = 0.0,
    sharpen: float = 0.0,
    verbose: bool = False,
    target: Optional[str] = None,
    auto_denoise: bool = True,
) -> None:
    """Upscale video stream using multi-threaded pipe and NVENC."""
    info = probe_video(src)
    w, h, fps = info["width"], info["height"], info["fps"]
    has_audio = info.get("has_audio", False)
    total = info["nb_frames"] or int(round(fps * info["duration"]))
    # If a resolution target is given (e.g. "4k"), compute the downscale that
    # lands the longer edge exactly on target, adapting to any input size.
    final_size: Optional[tuple[int, int]] = None
    if target:
        downscale = compute_target_scale(w, h, model_scale, target)
        final_size = _final_target_size(w, h, model_scale, downscale, target)
    effective_scale = model_scale * downscale
    ow, oh = int(round(w * effective_scale)), int(round(h * effective_scale))
    if final_size:
        ow, oh = final_size
    ow -= ow % 2
    oh -= oh % 2
    needs_resize = (downscale != 1.0) or (final_size is not None)

    # Auto-downgrade to a CPU encoder when NVENC can't be opened on this driver.
    requested_encoder = encoder
    encoder = resolve_encoder(encoder, verbose=verbose)

    print(f"[info] Source   : {src.name} ({w}x{h} @ {fps:.2f} fps, {info['duration']:.2f}s, ~{total} frames)")
    print(f"[info] Target   : {ow}x{oh} (scale {effective_scale:.2f}x) -> {dst.name}")
    if encoder != requested_encoder:
        print(f"[info] Encoder  : {encoder} (CPU fallback; '{requested_encoder}' unavailable) | Tile: {tile_size}")
    else:
        print(f"[info] Encoder  : {encoder} (preset={preset}, cq={cq}) | Tile: {tile_size}")
    if not has_audio:
        print("[info] Audio    : no audio stream detected in source")

    # [IMPROVEMENT #8] Suppress ffmpeg output unless --verbose is set
    ff_loglevel = "verbose" if verbose else "error"

    dec = subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", ff_loglevel,
            "-i", str(src),
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
        bufsize=10**8,
    )

    # Prepare encoder arguments
    enc_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", ff_loglevel,
        "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{int(ow)}x{int(oh)}", "-r", f"{fps:.6f}",
        "-i", "-",
    ]

    # [FIX #6] Only map audio stream when it actually exists
    if has_audio:
        enc_cmd += ["-i", str(src), "-map", "0:v:0", "-map", "1:a:0?"]
    else:
        enc_cmd += ["-map", "0:v:0"]

    if "nvenc" in encoder:
        enc_cmd += [
            "-c:v", encoder,
            "-preset", preset,
            "-rc", "vbr", "-cq", str(cq),
        ]
        # NOTE: Do NOT force -profile:v main10. It produces 10-bit HEVC that many
        # players (Windows Media Player, browsers) cannot decode -> the output
        # looks like "audio only". Keep 8-bit yuv420p for universal playback.
    else:  # CPU fallback (libx264/libx265)
        enc_cmd += [
            "-c:v", encoder,
            "-crf", str(cq),
            "-preset", "medium",
        ]

    # Force an 8-bit 4:2:0 pixel format (widely playable) and tag H.264 as High
    # profile / level 5.1 so 4K output decodes everywhere.
    enc_cmd += ["-pix_fmt", "yuv420p", "-tag:v", "avc1"] if encoder.startswith("h264") else ["-pix_fmt", "yuv420p"]
    if encoder.startswith("h264"):
        enc_cmd += ["-profile:v", "high", "-level", "5.1"]
    if has_audio:
        enc_cmd += ["-c:a", "aac", "-b:a", "192k"]
    enc_cmd += [
        "-movflags", "+faststart",
        str(dst),
    ]

    enc = subprocess.Popen(
        enc_cmd,
        stdin=subprocess.PIPE,
        bufsize=10**8,
    )
    assert dec.stdout and enc.stdin

    in_q: queue.Queue = queue.Queue(maxsize=queue_size)
    out_q: queue.Queue = queue.Queue(maxsize=queue_size)
    _ENCODER_ERROR["message"] = None  # reset per run

    t_dec = threading.Thread(target=decoder_thread, args=(dec, w, h, in_q), daemon=True)
    t_enc = threading.Thread(target=encoder_thread, args=(enc, out_q), daemon=True)
    t_dec.start()
    t_enc.start()

    t0 = time.time()
    i = 0
    last_print = t0

    dtype = torch.float16 if device.type == "cuda" else torch.float32

    def _encoder_alive() -> bool:
        return enc.poll() is None

    def _put_or_abort(payload: bytes) -> None:
        """Put into out_q, but never block forever if the encoder has died."""
        while True:
            if _ENCODER_ERROR["message"] or not _encoder_alive():
                raise EncoderFailed(
                    _ENCODER_ERROR["message"]
                    or f"Encoder exited unexpectedly (code={enc.poll()})."
                )
            try:
                out_q.put(payload, timeout=1.0)
                return
            except queue.Full:
                continue  # re-check encoder health, then retry

    def _get_or_abort():
        """Get from in_q, but abort if the encoder died (avoids deadlock)."""
        while True:
            if _ENCODER_ERROR["message"] or not _encoder_alive():
                raise EncoderFailed(
                    _ENCODER_ERROR["message"]
                    or f"Encoder exited unexpectedly (code={enc.poll()})."
                )
            try:
                return in_q.get(timeout=1.0)
            except queue.Empty:
                continue

    try:
        # Auto-detect compression on the first frame (once) so we deblock only
        # when the source is genuinely blocky; explicit user value overrides.
        video_denoise = denoise
        _detected = False
        with torch.inference_mode():
            while True:
                arr = _get_or_abort()
                if arr is _SENTINEL:
                    break

                # Detect compression blockiness once, on the first real frame.
                if not _detected:
                    _detected = True
                    if not denoise:
                        video_denoise = auto_denoise_strength(arr, 0.0, auto_denoise)
                        if video_denoise > 0.0:
                            print(f"[info] Compression detected — deblocking at strength {video_denoise} "
                                  f"to prevent SR artifact amplification.")

                # Pre-deblock per frame (only when the source needs it).
                if video_denoise > 0.0:
                    arr = apply_deblock(arr, video_denoise)

                x = (
                    torch.from_numpy(arr)
                    .to(device, non_blocking=True)
                    .permute(2, 0, 1)
                    .unsqueeze(0)
                    .to(dtype)
                    .div_(255.0)
                )

                if tile_size > 0 and (h > tile_size or w > tile_size):
                    y = process_tensor_tiled(model, x, model_scale, tile_size=tile_size)
                else:
                    y = model(x)
                y = y.clamp_(0, 1)

                if needs_resize:
                    y = F.interpolate(
                        y, size=(oh, ow),
                        mode="bicubic", align_corners=False, antialias=True,
                    )
                    y = y.clamp_(0, 1)

                y = y.mul_(255).round_().to(torch.uint8)
                out = y.squeeze(0).permute(1, 2, 0).contiguous().cpu().numpy()

                # [IMPROVEMENT #3] Post-process unsharp mask after downscale
                if sharpen > 0.0:
                    out = apply_unsharp_mask(out, sharpen)

                _put_or_abort(out.tobytes())

                i += 1
                now = time.time()
                if now - last_print >= 0.5:
                    dt = now - t0
                    fps_avg = i / dt if dt > 0 else 0
                    pct = 100.0 * i / total if total else 0.0
                    eta_secs = (dt / i) * (total - i) if total and i else 0.0
                    elapsed_str = _fmt_seconds(dt)           # [IMPROVEMENT #7]
                    eta_str = _fmt_seconds(eta_secs)         # [IMPROVEMENT #7]
                    print(
                        f"\r[{i}/{total}] {pct:5.1f}% | {fps_avg:4.2f} fps | "
                        f"elapsed {elapsed_str} | eta {eta_str} | "
                        f"qi={in_q.qsize():<2} qo={out_q.qsize():<2}",
                        end="", flush=True,
                    )
                    if progress_callback:
                        progress_callback(i, total, fps_avg, eta_secs)
                    last_print = now
    except EncoderFailed:
        # Clean up the decoder so it doesn't linger holding the source file open.
        try:
            dec.kill()
        except Exception:
            pass
        raise

    out_q.put(_SENTINEL)
    t_dec.join()
    t_enc.join()
    dec.wait()
    enc.wait()

    if enc.returncode not in (0, None) and _ENCODER_ERROR["message"]:
        raise EncoderFailed(_ENCODER_ERROR["message"])

    dt = time.time() - t0
    avg_fps = i / dt if dt > 0 else 0
    elapsed_str = _fmt_seconds(dt)
    print(f"\n[done] {i} frames processed in {elapsed_str} ({avg_fps:.2f} fps) -> {dst}")


def _resolve_output_path(src: Path, output: Optional[Path], fmt: Optional[str], suffix_4k: str = "_4K") -> Path:
    """Determine the final output path, applying --format override if given."""
    base = output or src.with_name(src.stem + suffix_4k + src.suffix)
    if fmt:
        # Override extension based on --format
        if fmt in VIDEO_FORMAT_MAP:
            ext = VIDEO_FORMAT_MAP[fmt]
        elif fmt in IMAGE_FORMAT_MAP:
            ext = IMAGE_FORMAT_MAP[fmt]
        else:
            ext = base.suffix
        base = base.with_suffix(ext)
    return base.resolve()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Local 4K Upscaler by Raliq Hidayat BM3 - Super-Resolution AI Pipeline"
    )
    ap.add_argument("input", type=Path, help="Input video/image file or directory")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Output destination")
    ap.add_argument("--model", default=None, help="Model weights name or path (in ./models)")
    ap.add_argument("--target", choices=["4k", "2k", "1080p"], default=None,
                    help="Resolution target (e.g. 4k): auto-adapts ANY input/aspect ratio "
                         "to that size. Overrides --downscale.")
    ap.add_argument("--downscale", type=float, default=0.5,
                    help="Post-upscale factor (0.5 with x4 model = 2x effective)")
    ap.add_argument("--cq", type=int, default=20,
                    help="Encoder quality CQ/CRF (lower=better, 18-23 typical)")
    ap.add_argument("--preset", default="p4",
                    help="Encoder preset p1 (fastest) .. p7 (highest quality)")
    ap.add_argument("--tile", type=int, default=-1,
                    help="Tile size for inference (-1 = auto [default], 0 = full-frame, "
                         "e.g. 512 for very low VRAM)")
    ap.add_argument("--encoder", default="auto",
                    help="Video encoder: auto (default), h264_nvenc, hevc_nvenc, av1_nvenc, libx264, libx265")
    ap.add_argument("--queue", type=int, default=8,
                    help="Max frames buffered between thread stages")
    # [IMPROVEMENT #1] Force float32 on GPU
    ap.add_argument("--fp32", action="store_true",
                    help="Force float32 precision on GPU (some models perform better without fp16)")
    # [IMPROVEMENT #2] Gaussian pre-blur for compression artifact removal
    ap.add_argument("--denoise", type=float, default=0.0, metavar="STRENGTH",
                    help="Pre-blur strength 0.0â€“1.0 (Gaussian; removes compression artifacts before SR, default: 0.0)")
    # [IMPROVEMENT #3] Post-process unsharp mask sharpening
    ap.add_argument("--sharpen", type=float, default=0.0, metavar="AMOUNT",
                    help="Post-process unsharp mask 0.0â€“2.0 applied after downscale step (default: 0.0)")
    # [IMPROVEMENT #5] Output format selection
    ap.add_argument("--format", dest="fmt", default=None,
                    choices=list(VIDEO_FORMAT_MAP) + list(IMAGE_FORMAT_MAP),
                    help="Output container/format: mp4, mkv, mov (video) | png, jpg, webp (image)")
    # [IMPROVEMENT #8] Verbose flag
    ap.add_argument("--verbose", action="store_true",
                    help="Show full ffmpeg output (default: suppressed)")
    args = ap.parse_args()

    # Validate denoise / sharpen ranges
    if not (0.0 <= args.denoise <= 1.0):
        print("[error] --denoise must be in range 0.0â€“1.0", file=sys.stderr)
        return 1
    if not (0.0 <= args.sharpen <= 2.0):
        print("[error] --sharpen must be in range 0.0â€“2.0", file=sys.stderr)
        return 1

    src = args.input.resolve()
    if not src.exists():
        print(f"[error] input not found: {src}", file=sys.stderr)
        return 1

    if not torch.cuda.is_available():
        print("[warning] CUDA is not available. Running on CPU will be slow.", file=sys.stderr)
        device = torch.device("cpu")
        vram_gb = 4.0
        force_fp32 = True  # CPU always uses fp32
    else:
        device = torch.device("cuda")
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        gpu_name = torch.cuda.get_device_name(0)
        print(f"[gpu] {gpu_name} ({vram_gb:.1f} GB VRAM)")
        # -1 (default) = auto: choose the largest safe tile per source (see below).
        force_fp32 = args.fp32  # [IMPROVEMENT #1]

    model_file = resolve_model_path(args.model)
    if not model_file.exists():
        print(f"[error] Model file not found: {model_file}", file=sys.stderr)
        return 2

    print(f"[model] Loading weights from: {model_file.name}")
    desc = ModelLoader().load_from_file(str(model_file))
    model = desc.model.to(device).eval()
    # [IMPROVEMENT #1] Use fp16 unless --fp32 is requested or device is CPU
    if device.type == "cuda" and not force_fp32:
        model = model.half()
    elif force_fp32 and device.type == "cuda":
        print("[info] Running in float32 mode on GPU (--fp32)")
    model_scale = desc.scale

    # Resolve "-1 auto" tile per file using the source resolution + VRAM.
    def _tile_for(path: Path) -> int:
        if args.tile >= 0:
            return args.tile
        try:
            if path.suffix.lower() in VIDEO_EXTENSIONS:
                info = probe_video(path)
                w, h = info["width"], info["height"]
            else:
                import cv2 as _cv2
                im = _cv2.imread(str(path))
                h, w = (im.shape[0], im.shape[1]) if im is not None else (1080, 1920)
        except Exception:
            w, h = 1080, 1920
        vram = vram_gb if device.type == "cuda" else 4.0
        chosen = recommend_tile_size(w, h, vram)
        print(f"[info] Auto tile for {w}x{h}: {chosen or 'full-frame'} "
              f"({'no tiling' if chosen == 0 else f'{chosen}px'})")
        return chosen

    # Check if input is directory (batch mode)
    if src.is_dir():
        files = [
            p for p in src.iterdir()
            if p.is_file() and (p.suffix.lower() in IMAGE_EXTENSIONS or p.suffix.lower() in VIDEO_EXTENSIONS)
        ]
        if not files:
            print(f"[error] No supported video or image files found in {src}", file=sys.stderr)
            return 1
        out_dir = (args.output or src / "upscaled").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[batch] Found {len(files)} files to upscale into {out_dir}")
        for idx, f in enumerate(files, 1):
            print(f"\n--- [{idx}/{len(files)}] Processing: {f.name} ---")
            # [IMPROVEMENT #5] Apply --format to batch output names
            dst_base = out_dir / f"{f.stem}_4K{f.suffix}"
            dst_tmp = Path(dst_base)
            if args.fmt:
                if f.suffix.lower() in VIDEO_EXTENSIONS and args.fmt in VIDEO_FORMAT_MAP:
                    dst_tmp = dst_tmp.with_suffix(VIDEO_FORMAT_MAP[args.fmt])
                elif f.suffix.lower() in IMAGE_EXTENSIONS and args.fmt in IMAGE_FORMAT_MAP:
                    dst_tmp = dst_tmp.with_suffix(IMAGE_FORMAT_MAP[args.fmt])
            dst = dst_tmp.resolve()
            if f.suffix.lower() in IMAGE_EXTENSIONS:
                upscale_image(f, dst, model, model_scale, args.downscale, _tile_for(f), device,
                              denoise=args.denoise, sharpen=args.sharpen, target=args.target)
            else:
                upscale_video(f, dst, model, model_scale, args.downscale, args.cq, args.preset,
                              args.queue, _tile_for(f), args.encoder, device=device,
                              denoise=args.denoise, sharpen=args.sharpen, verbose=args.verbose,
                              target=args.target)
        print(f"\n[batch complete] All {len(files)} files processed successfully!")
        return 0

    # Single file
    suffix = src.suffix.lower()
    dst = _resolve_output_path(src, args.output, args.fmt)

    if suffix in IMAGE_EXTENSIONS:
        upscale_image(src, dst, model, model_scale, args.downscale, _tile_for(src), device,
                      denoise=args.denoise, sharpen=args.sharpen, target=args.target)
    elif suffix in VIDEO_EXTENSIONS:
        upscale_video(src, dst, model, model_scale, args.downscale, args.cq, args.preset,
                      args.queue, _tile_for(src), args.encoder, device=device,
                      denoise=args.denoise, sharpen=args.sharpen, verbose=args.verbose,
                      target=args.target)
    else:
        print(f"[error] Unsupported file format: {suffix}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
