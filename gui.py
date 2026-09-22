#!/usr/bin/env python3
"""
Local 4K Upscaler Web GUI (ReelFrame)
FastAPI-powered modern web dashboard with real-time progress and GPU metrics.

Author: Raliq Hidayat BM3
Repository: https://github.com/kouji999/ReelFrame
"""
from __future__ import annotations

import math
import os
import queue
import shutil
import sys
import threading
import time
import uuid
import webbrowser
import json
import subprocess
import zipfile
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# Import core upscaling logic
from upscale import (
    BUNDLE_DIR,
    IMAGE_EXTENSIONS,
    MODELS_DIR,
    SCRIPT_DIR,
    TARGET_LONG_EDGE,
    VIDEO_EXTENSIONS,
    EncoderFailed,
    compute_target_scale,
    describe_scale_mode,
    nvenc_available,
    recommend_tile_size,
    resolve_encoder,
    resolve_model_path,
    upscale_image,
    upscale_video,
)
from spandrel import ModelLoader

app = FastAPI(title="ReelFrame - AI 4K Upscaler by Raliq Hidayat BM3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = SCRIPT_DIR / "temp_uploads"
OUTPUT_DIR = SCRIPT_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = SCRIPT_DIR / "history.json"

# In-memory jobs tracker
JOBS: Dict[str, Dict[str, Any]] = {}

# Global model cache to avoid re-loading on each upscale
LOADED_MODELS: Dict[str, Any] = {}
MODEL_LOCK = threading.Lock()


def safe_filename(name: Optional[str], fallback: str = "upload") -> str:
    """Return a filesystem-safe base name.

    Guards against: None (multipart clients may omit filename), path traversal
    ("../../etc"), Windows-reserved characters, and empty-after-strip names.
    """
    if not name:
        return fallback
    # Strip any directory component (handles both / and \ separators).
    base = os.path.basename(name.replace("\\", "/")).strip()
    # Remove characters illegal on Windows and any separators that slipped through.
    base = "".join(ch for ch in base if ch not in '<>:"/\\|?*' and ord(ch) >= 32)
    base = base.strip(". ")
    return base or fallback


def choose_model_for_target(model_name: str, src_w: int, src_h: int, target: Optional[str]) -> str:
    """If a 4K target is requested but the chosen model can't reach it, upgrade
    to a 4x model automatically. Keeps quality honest (no fake interpolation).

    e.g. RealESRGAN_x2plus (2x) on a 576p input can only reach 1152p, so we swap
    in a 4x model so the master genuinely lands at 4K.
    """
    if not target or target not in TARGET_LONG_EDGE:
        return model_name
    long_edge = max(src_w, src_h)
    desired = TARGET_LONG_EDGE[target]
    if long_edge >= desired:
        return model_name  # already there; no upgrade needed
    need = desired / long_edge
    is_2x_model = "x2plus" in model_name.lower()
    if is_2x_model and need > 2.0:
        # 2x model insufficient -> upgrade to the fast 4x general model if present.
        for cand in ("realesr-general-x4v3.pth", "RealESRGAN_x4plus.pth"):
            if (MODELS_DIR / cand).exists():
                return cand
    return model_name


def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving history: {e}")

HISTORY = load_history()

# ---------------------------------------------------------------------------
# Serial job queue — one upscale at a time.
#
# Running several SR jobs at once splits the same CPU/GPU between them and
# makes EVERY job crawl (the "everything is stuck at 5%" symptom). We instead
# enqueue jobs and process them FIFO, which is far faster overall and keeps the
# UI honest about what's actually running.
# ---------------------------------------------------------------------------
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
_QUEUE_WORKER: Optional[threading.Thread] = None
_QUEUE_LOCK = threading.Lock()


def _queue_worker() -> None:
    while True:
        job_id = JOB_QUEUE.get()
        try:
            job = JOBS.get(job_id)
            if job is None or job.get("status") == "cancelled":
                continue
            run_upscale_job(
                job_id,
                Path(job["input_path"]),
                Path(job["output_path"]),
                job["model"],
                job["scale_mode"],
                job["tile"],
                job["cq"],
                job.get("denoise", -1.0),
            )
        except Exception as exc:  # noqa: BLE001 - worker must never die
            job = JOBS.get(job_id)
            if job is not None and job.get("status") not in ("cancelled", "error"):
                job["status"] = "error"
                job["error"] = str(exc)
                job["log"] = (job.get("log") or "") + f"\n[ERROR] {exc}"
        finally:
            JOB_QUEUE.task_done()


def ensure_queue_worker() -> None:
    global _QUEUE_WORKER
    with _QUEUE_LOCK:
        if _QUEUE_WORKER is None or not _QUEUE_WORKER.is_alive():
            _QUEUE_WORKER = threading.Thread(target=_queue_worker, daemon=True, name="reelframe-queue")
            _QUEUE_WORKER.start()


def enqueue_job(job_id: str) -> None:
    ensure_queue_worker()
    JOB_QUEUE.put(job_id)


def queue_position(job_id: str) -> Optional[int]:
    """1-based position of a queued job, or None if it's not waiting."""
    with JOB_QUEUE.mutex:
        pending = list(JOB_QUEUE.queue)
    return pending.index(job_id) + 1 if job_id in pending else None


def get_cached_model(model_name: str, device: torch.device):
    with MODEL_LOCK:
        if model_name in LOADED_MODELS:
            return LOADED_MODELS[model_name]
        
        model_file = resolve_model_path(model_name)
        if not model_file.exists():
            raise FileNotFoundError(f"Model file not found: {model_file}")
        
        desc = ModelLoader().load_from_file(str(model_file))
        model = desc.model.to(device).eval()
        if device.type == "cuda":
            model = model.half()
        LOADED_MODELS[model_name] = (model, desc.scale)
        return LOADED_MODELS[model_name]


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    # Assets live in the bundle; fall back to the project dir for source runs.
    for base in (BUNDLE_DIR, SCRIPT_DIR):
        index_path = base / "web" / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>ReelFrame</h1><p>web/index.html not found in the app bundle.</p>",
        status_code=500,
    )


@app.get("/favicon.ico")
async def favicon():
    for base in (BUNDLE_DIR, SCRIPT_DIR):
        for name in ("icon.ico", "favicon.ico"):
            p = base / "web" / name
            if p.exists():
                return FileResponse(path=p, media_type="image/x-icon")
    return JSONResponse(status_code=404, content={"error": "no favicon"})


@app.get("/api/system-info")
async def get_system_info():
    cuda_avail = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_avail else "No NVIDIA GPU found"
    vram_gb = (
        round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)
        if cuda_avail
        else 0
    )
    
    models = []
    if MODELS_DIR.exists():
        for p in MODELS_DIR.glob("*.pth"):
            models.append(p.name)

    return {
        "cuda_available": cuda_avail,
        "gpu_name": gpu_name,
        "vram_gb": vram_gb,
        "models": models,
        "author": "Raliq Hidayat BM3"
    }

@app.get("/api/capabilities")
async def get_capabilities():
    """Report which video encoders are actually usable on this machine."""
    hevc_gpu = nvenc_available("hevc_nvenc")
    h264_gpu = nvenc_available("h264_nvenc")
    active = resolve_encoder("auto")
    return {
        "nvenc_hevc": hevc_gpu,
        "nvenc_h264": h264_gpu,
        "gpu_encoder": "h264_nvenc" if h264_gpu else ("hevc_nvenc" if hevc_gpu else None),
        "active_encoder": active,
        "hardware_accelerated": "nvenc" in active,
        "output_codec": "h264" if active.startswith("h264") or active == "libx264" else "hevc",
        "note": (
            "GPU encoding active."
            if "nvenc" in active
            else "GPU encoder unavailable (NVIDIA driver too old for this ffmpeg build). "
                 "Using CPU encoding (libx264, H.264) — slower but plays everywhere."
        ),
    }


@app.get("/api/gpu-info")
async def get_gpu_info():
    cuda_avail = torch.cuda.is_available()
    if cuda_avail:
        props = torch.cuda.get_device_properties(0)
        return {
            # Fields consumed by the web UI (Settings tab).
            "cuda_available": True,
            "gpu_name": props.name,
            "vram_gb": round(props.total_memory / (1024 ** 3), 1),
            "cuda_version": torch.version.cuda,
            # Backward-compatible raw fields.
            "name": props.name,
            "vram_total": props.total_memory,
            "vram_used": torch.cuda.memory_allocated(0),
        }
    return {
        "cuda_available": False,
        "gpu_name": "No NVIDIA GPU found",
        "vram_gb": 0,
        "cuda_version": None,
        "error": "No NVIDIA GPU found",
    }

@app.get("/api/jobs")
async def get_all_jobs():
    return JOBS

@app.delete("/api/job/{job_id}")
async def cancel_job(job_id: str):
    if job_id not in JOBS:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    job = JOBS[job_id]
    if job["status"] in ["processing", "queued"]:
        job["status"] = "cancelled"
        job["log"] += "\n[INFO] Job cancelled by user."
        # If there's a subprocess we can't easily kill it here without PID tracking, 
        # but setting status to cancelled handles the queue side.
        
        # Add to history as cancelled
        HISTORY.append({
            "job_id": job_id,
            "input_filename": job["input_filename"],
            "output_filename": job["output_filename"],
            "timestamp": time.time(),
            "status": "cancelled",
            "resolution": "Unknown"
        })
        save_history(HISTORY)
    return {"status": "cancelled"}

@app.get("/api/history")
async def get_history():
    return HISTORY

def probe_file_logic(path: str) -> dict:
    """Probe video or image file to extract exact resolution, fps, duration, and aspect ratio."""
    p = Path(path)
    suffix = p.suffix.lower()

    # If it's an image, read dimensions directly via cv2 / PIL
    if suffix in IMAGE_EXTENSIONS:
        try:
            import cv2
            img = cv2.imread(path)
            if img is not None:
                h, w = img.shape[:2]
                gcd = math.gcd(w, h)
                ratio_str = f"{w//gcd}:{h//gcd}"
                return {
                    "type": "image",
                    "width": w,
                    "height": h,
                    "aspect_ratio": ratio_str,
                    "fps": 0,
                    "duration": 0,
                    "has_audio": False,
                }
        except Exception:
            pass

    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"error": "ffprobe failed"}
        data = json.loads(result.stdout)
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

        if not video_stream:
            return {"error": "no video/image stream found"}

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        fps_str = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = map(int, fps_str.split("/"))
            fps = num / den if den != 0 else 0
        except Exception:
            fps = 0
        duration = float(data.get("format", {}).get("duration", 0))

        # Calculate exact mathematical aspect ratio
        if width > 0 and height > 0:
            gcd = math.gcd(width, height)
            ratio_str = f"{width//gcd}:{height//gcd}"
        else:
            ratio_str = "Unknown"

        return {
            "type": "video",
            "width": width,
            "height": height,
            "aspect_ratio": ratio_str,
            "fps": round(fps, 2),
            "duration": round(duration, 2),
            "has_audio": audio_stream is not None,
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/probe")
async def probe_file_get(path: str = Query(...)):
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return probe_file_logic(path)

@app.post("/api/probe")
async def probe_file_post(file: UploadFile = File(...)):
    temp_path = UPLOAD_DIR / f"probe_{uuid.uuid4()}_{safe_filename(file.filename)}"
    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = probe_file_logic(str(temp_path))
        return result
    finally:
        if temp_path.exists():
            temp_path.unlink()


def run_upscale_job(job_id: str, input_path: Path, output_path: Path, model_name: str, scale_str: str, tile_size: int, cq: int, denoise: float = -1.0):
    job = JOBS[job_id]
    if job["status"] == "cancelled":
        return
    # denoise: -1.0 = auto-detect, 0.0 = off, >0 = explicit deblock strength
    user_denoise = 0.0 if denoise < 0 else denoise
    auto_denoise = denoise < 0
        
    job["status"] = "processing"
    job["started_at"] = time.time()
    job["log"] = f"Starting upscale job {job_id}...\n"
    
    start_time = time.time()

    def _describe_output() -> str:
        """Probe the finished file so History shows a real resolution, not a placeholder."""
        try:
            info = probe_file_logic(str(output_path))
            w, h = info.get("width"), info.get("height")
            if w and h:
                return f"{w}x{h}"
        except Exception:
            pass
        return "Done"

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, model_scale = get_cached_model(model_name, device)

        # Scale can be a fixed multiplier ("2x"/"4x") or a resolution target
        # ("4k"/"2k"/"1080p") that adapts to ANY input size/aspect ratio.
        scale_key = (scale_str or "2x").lower()
        target = scale_key if scale_key in TARGET_LONG_EDGE else None
        downscale = 0.5 if scale_key == "2x" else 1.0
        if target:
            downscale = 1.0  # engine computes the exact factor from the source
        scale_label = describe_scale_mode(scale_key)

        suffix = input_path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            job["log"] += f"Processing image {input_path.name} ({scale_label})...\n"
            upscale_image(
                src=input_path,
                dst=output_path,
                model=model,
                model_scale=model_scale,
                downscale=downscale,
                tile_size=tile_size,
                device=device,
                denoise=user_denoise,
                auto_denoise=auto_denoise,
                target=target,
            )
            job["progress"] = 100.0
            if job["status"] != "cancelled":
                job["status"] = "completed"
                elapsed = time.time() - start_time
                resolution_out = _describe_output()
                job["output_resolution"] = resolution_out
                job["log"] += (
                    f"Successfully upscaled image to {output_path.name} "
                    f"({resolution_out}) in {elapsed:.1f}s\n"
                )
                
                HISTORY.append({
                    "job_id": job_id,
                    "input_filename": job["input_filename"],
                    "output_filename": job["output_filename"],
                    "timestamp": time.time(),
                    "status": "completed",
                    "resolution": resolution_out
                })
                save_history(HISTORY)

        elif suffix in VIDEO_EXTENSIONS:
            def on_progress(frame_i: int, total_frames: int, fps: float, eta: float):
                if job["status"] == "cancelled":
                    raise InterruptedError("Job cancelled by user")
                job["current_frame"] = frame_i
                job["total_frames"] = total_frames
                job["fps"] = fps
                job["eta"] = eta
                job["progress"] = round((frame_i / total_frames) * 100.0, 1) if total_frames else 0.0
                job["log"] = f"Processing frame {frame_i}/{total_frames} ({job['progress']}%) at {fps:.2f} fps. ETA: {round(eta)}s"

            try:
                upscale_video(
                    src=input_path,
                    dst=output_path,
                    model=model,
                    model_scale=model_scale,
                    downscale=downscale,
                    cq=cq,
                    preset="p4",
                    queue_size=8,
                    tile_size=tile_size,
                    encoder="auto",
                    progress_callback=on_progress,
                    device=device,
                    target=target,
                    denoise=user_denoise,
                    auto_denoise=auto_denoise,
                )
                job["progress"] = 100.0
                if job["status"] != "cancelled":
                    job["status"] = "completed"
                    elapsed = time.time() - start_time
                    resolution_out = _describe_output()
                    job["output_resolution"] = resolution_out
                    job["log"] += (
                        f"\nVideo upscaling finished successfully -> {output_path.name} "
                        f"({resolution_out}) in {elapsed:.1f}s"
                    )
                    HISTORY.append({
                        "job_id": job_id,
                        "input_filename": job["input_filename"],
                        "output_filename": job["output_filename"],
                        "timestamp": time.time(),
                        "status": "completed",
                        "resolution": resolution_out
                    })
                    save_history(HISTORY)
            except InterruptedError:
                job["log"] += "\n[INFO] Upscaling interrupted."
            except EncoderFailed as enc_err:
                job["log"] += (
                    f"\n[ERROR] Video encoder failed: {enc_err}\n"
                    "[hint] Your NVIDIA driver may be too old for GPU encoding. "
                    "ReelFrame auto-falls back to CPU, but double-check the log above."
                )
                raise
        else:
            raise ValueError(f"Unsupported format {suffix}")

    except Exception as e:
        if job["status"] != "cancelled":
            job["status"] = "error"
            job["error"] = str(e)
            job["log"] += f"\n[ERROR] {e}"
            HISTORY.append({
                "job_id": job_id,
                "input_filename": job["input_filename"],
                "output_filename": job["output_filename"],
                "timestamp": time.time(),
                "status": "error",
                "resolution": "Failed"
            })
            save_history(HISTORY)


@app.post("/api/upscale")
async def start_upscale_api(
    file: UploadFile = File(...),
    model: str = Form("realesr-general-x4v3.pth"),
    scale: str = Form("4k"),
    tile: int = Form(-1),
    cq: int = Form(20),
    denoise: str = Form("auto"),
):
    job_id = str(uuid.uuid4())[:8]
    clean_name = safe_filename(file.filename)
    ext = Path(clean_name).suffix
    saved_input = UPLOAD_DIR / f"{job_id}_input{ext}"

    # Output suffix reflects the real scale mode (e.g. _4K, _2K, _1080p, _2x).
    scale_key = (scale or "2x").lower()
    suffix = scale_key.upper() if scale_key in TARGET_LONG_EDGE else scale_key
    output_filename = f"{Path(clean_name).stem}_{suffix}{ext}"
    saved_output = OUTPUT_DIR / f"{job_id}_{output_filename}"

    with saved_input.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Auto-upgrade the model if the requested target needs more than the
    # chosen model can natively deliver (honest 4K, no fake interpolation).
    probe = probe_file_logic(str(saved_input))
    src_w = int(probe.get("width") or 0)
    src_h = int(probe.get("height") or 0)
    chosen_model = choose_model_for_target(model, src_w, src_h, suffix.lower() if suffix.lower() in TARGET_LONG_EDGE else None)

    # Auto tile size (-1 = auto): pick the largest tile that safely fits VRAM.
    # Full-frame is faster; only tile when the output would risk OOM.
    if tile is None or tile < 0:
        vram_gb = 0.0
        if torch.cuda.is_available():
            try:
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            except Exception:
                vram_gb = 4.0
        resolved_tile = recommend_tile_size(src_w or 1080, src_h or 1920, vram_gb)
    else:
        resolved_tile = tile

    # Compression-cleanup (deblock) strength: "auto" -> detect per source.
    try:
        denoise_value = 0.0 if str(denoise) == "0" else (
            -1.0 if str(denoise) in ("auto", "") else float(denoise)
        )
    except (TypeError, ValueError):
        denoise_value = -1.0

    JOBS[job_id] = {
        "job_id": job_id,
        "input_filename": clean_name,
        "output_filename": output_filename,
        "input_path": str(saved_input),
        "output_path": str(saved_output),
        "status": "queued",
        "progress": 0.0,
        "current_frame": 0,
        "total_frames": 0,
        "fps": 0.0,
        "eta": 0.0,
        "scale_mode": scale_key,
        "model": chosen_model,
        "tile": resolved_tile,
        "cq": cq,
        "denoise": denoise_value,
        "source_resolution": f"{src_w}x{src_h}" if src_w and src_h else None,
        "queued_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "log": "Uploaded and queued...",
        "error": None,
    }

    # Serial queue: one job at a time (prevents parallel jobs starving each other).
    enqueue_job(job_id)

    return {"status": "queued", "job_id": job_id, "position": queue_position(job_id)}


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in JOBS:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    job = JOBS[job_id]
    # Surface queue position so the UI can show "queued (position N)".
    if job.get("status") == "queued":
        job["queue_position"] = queue_position(job_id)
    return job


def resolve_job_output(job_id: str) -> Optional[Path]:
    """Locate a finished output file for a job id.

    Works for the current session (JOBS) AND for any past job recorded in
    history.json — so History downloads keep working after an app restart.
    """
    # 1) Live in-memory job.
    job = JOBS.get(job_id)
    if job and job.get("output_path"):
        p = Path(job["output_path"])
        if p.exists():
            return p

    # 2) Persisted history (find by output filename, then by job id prefix).
    record = next((h for h in HISTORY if h.get("job_id") == job_id), None)
    if record:
        out_name = record.get("output_filename")
        if out_name:
            candidate = OUTPUT_DIR / out_name
            if candidate.exists():
                return candidate
            # Files are stored as "<job_id>_<output_filename>".
            candidate = OUTPUT_DIR / f"{job_id}_{out_name}"
            if candidate.exists():
                return candidate

    # 3) Last resort: any file in OUTPUT_DIR prefixed with the job id.
    matches = sorted(OUTPUT_DIR.glob(f"{job_id}_*"))
    return matches[-1] if matches else None


def _download_names(job_id: str) -> tuple[str, str]:
    """Return (output_filename_for_user, zip_member_name)."""
    job = JOBS.get(job_id)
    record = next((h for h in HISTORY if h.get("job_id") == job_id), None)
    name = (
        (job or {}).get("output_filename")
        or (record or {}).get("output_filename")
        or "reelframe_output"
    )
    return safe_filename(name, "reelframe_output"), safe_filename(name, "reelframe_output")


@app.get("/api/download/{job_id}")
async def download_result(job_id: str):
    """Serve the raw output file (video/image) — used for the Queue tab."""
    output_path = resolve_job_output(job_id)
    if output_path is None:
        return JSONResponse(status_code=404, content={"error": "Result file not found"})
    filename, _ = _download_names(job_id)
    media = _guess_media_type(output_path)
    return FileResponse(path=output_path, filename=filename, media_type=media)


@app.get("/api/download-zip/{job_id}")
async def download_zip(job_id: str):
    """Download the result as a .zip archive (History tab).

    The zip contains the real output file with its original extension, so a
    video stays a video and a photo stays a photo — just neatly packaged.
    """
    output_path = resolve_job_output(job_id)
    if output_path is None:
        return JSONResponse(status_code=404, content={"error": "Result file not found"})

    _, member_name = _download_names(job_id)
    zip_name = f"{Path(member_name).stem}.zip"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(output_path, arcname=member_name)
        # Small manifest so the user can see where it came from / how big it is.
        zf.writestr(
            "ReelFrame_info.txt",
            (
                "ReelFrame — Local 4K AI Upscaler\n"
                f"Output file : {member_name}\n"
                f"Size        : {output_path.stat().st_size:,} bytes\n"
                f"Created     : {datetime.now().isoformat(timespec='seconds')}\n"
                "Author      : Raliq Hidayat BM3\n"
            ),
        )
    buffer.seek(0)

    headers = {
        # Content-Disposition with filename triggers a direct save to the
        # browser's default Downloads folder (no intermediate "Save as" in
        # Chrome/Edge when downloads are set to auto-save).
        "Content-Disposition": f'attachment; filename="{zip_name}"',
        "X-ReelFrame-Filename": zip_name,
    }
    return Response(content=buffer.getvalue(), media_type="application/zip", headers=headers)


def _guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
        ".webm": "video/webm", ".m4v": "video/x-m4v", ".avi": "video/x-msvideo",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".bmp": "image/bmp", ".tiff": "image/tiff",
        ".zip": "application/zip",
    }.get(ext, "application/octet-stream")


def main():
    host = "127.0.0.1"
    port = 7860
    url = f"http://{host}:{port}"
    print("=" * 60)
    print(" Local 4K Upscaler — Web Interface")
    print(" Author: Raliq Hidayat BM3")
    print(f" URL: {url}")
    print("=" * 60)

    # Open browser automatically after 1 second
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
