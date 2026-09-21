#!/usr/bin/env python3
"""
Local 4K Upscaler Web GUI (ReelFrame)
FastAPI-powered modern web dashboard with real-time progress and GPU metrics.

Author: Raliq Hidayat BM3
Repository: https://github.com/kouji999/ReelFrame
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import uuid
import webbrowser
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Import core upscaling logic
from upscale import (
    IMAGE_EXTENSIONS,
    MODELS_DIR,
    SCRIPT_DIR,
    VIDEO_EXTENSIONS,
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
    index_path = SCRIPT_DIR / "web" / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


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

@app.get("/api/gpu-info")
async def get_gpu_info():
    cuda_avail = torch.cuda.is_available()
    if cuda_avail:
        return {
            "name": torch.cuda.get_device_name(0),
            "vram_total": torch.cuda.get_device_properties(0).total_memory,
            "vram_used": torch.cuda.memory_allocated(0),
            "cuda_version": torch.version.cuda
        }
    return {"error": "No NVIDIA GPU found"}

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
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"error": "ffprobe failed"}
        data = json.loads(result.stdout)
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        
        if not video_stream:
            # Maybe it's an image?
            if "format" in data:
                # Basic fallback
                pass
            return {"error": "no video/image stream found"}
        
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        fps_str = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = map(int, fps_str.split('/'))
            fps = num / den if den != 0 else 0
        except:
            fps = 0
        duration = float(data.get("format", {}).get("duration", 0))
        
        return {
            "width": width,
            "height": height,
            "fps": round(fps, 2),
            "duration": round(duration, 2),
            "has_audio": audio_stream is not None
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
    temp_path = UPLOAD_DIR / f"probe_{uuid.uuid4()}_{file.filename}"
    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = probe_file_logic(str(temp_path))
        return result
    finally:
        if temp_path.exists():
            temp_path.unlink()


def run_upscale_job(job_id: str, input_path: Path, output_path: Path, model_name: str, scale_str: str, tile_size: int, cq: int):
    job = JOBS[job_id]
    if job["status"] == "cancelled":
        return
        
    job["status"] = "processing"
    job["log"] = f"Starting upscale job {job_id}...\n"
    
    start_time = time.time()
    resolution_out = "4K" # placeholder, we don't have the actual output res easily without probe

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, model_scale = get_cached_model(model_name, device)

        # Determine downscale factor:
        downscale = 0.5 if scale_str == "2x" else 1.0

        suffix = input_path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            job["log"] += f"Processing image {input_path.name}...\n"
            upscale_image(
                src=input_path,
                dst=output_path,
                model=model,
                model_scale=model_scale,
                downscale=downscale,
                tile_size=tile_size,
                device=device,
            )
            job["progress"] = 100.0
            if job["status"] != "cancelled":
                job["status"] = "completed"
                job["log"] += f"Successfully upscaled image to {output_path.name}!\n"
                
                HISTORY.append({
                    "job_id": job_id,
                    "input_filename": job["input_filename"],
                    "output_filename": job["output_filename"],
                    "timestamp": time.time(),
                    "status": "completed",
                    "resolution": "Image Upscaled"
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
                    encoder="hevc_nvenc",
                    progress_callback=on_progress,
                    device=device,
                )
                job["progress"] = 100.0
                if job["status"] != "cancelled":
                    job["status"] = "completed"
                    job["log"] += f"\nVideo upscaling finished successfully -> {output_path.name}"
                    HISTORY.append({
                        "job_id": job_id,
                        "input_filename": job["input_filename"],
                        "output_filename": job["output_filename"],
                        "timestamp": time.time(),
                        "status": "completed",
                        "resolution": "Video Upscaled"
                    })
                    save_history(HISTORY)
            except InterruptedError:
                job["log"] += "\n[INFO] Upscaling interrupted."
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
    scale: str = Form("2x"),
    tile: int = Form(512),
    cq: int = Form(20),
):
    job_id = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix
    saved_input = UPLOAD_DIR / f"{job_id}_input{ext}"
    output_filename = f"{Path(file.filename).stem}_4K{ext}"
    saved_output = OUTPUT_DIR / f"{job_id}_{output_filename}"

    with saved_input.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    JOBS[job_id] = {
        "job_id": job_id,
        "input_filename": file.filename,
        "output_filename": output_filename,
        "input_path": str(saved_input),
        "output_path": str(saved_output),
        "status": "queued",
        "progress": 0.0,
        "current_frame": 0,
        "total_frames": 0,
        "fps": 0.0,
        "eta": 0.0,
        "log": "Uploaded and queued...",
        "error": None,
    }

    thread = threading.Thread(
        target=run_upscale_job,
        args=(job_id, saved_input, saved_output, model, scale, tile, cq),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "job_id": job_id}


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in JOBS:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return JOBS[job_id]


@app.get("/api/download/{job_id}")
async def download_result(job_id: str):
    if job_id not in JOBS:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    job = JOBS[job_id]
    output_path = Path(job["output_path"])
    if job["status"] != "completed" or not output_path.exists():
        return JSONResponse(status_code=400, content={"error": "Result file not ready"})
    return FileResponse(
        path=output_path,
        filename=job["output_filename"],
        media_type="application/octet-stream",
    )


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
