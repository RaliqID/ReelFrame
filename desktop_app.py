#!/usr/bin/env python3
"""
ReelFrame Desktop App — Windows Native (WebView2-powered)
Author: Raliq Hidayat BM3
Repository: https://github.com/kouji999/ReelFrame
"""
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import webview
    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False

import uvicorn
from gui import app as fastapi_app


def find_free_port(start: int = 7860) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def run_server(port: int) -> None:
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main() -> None:
    port = find_free_port(7860)
    local_url = f"http://127.0.0.1:{port}"
    lan_ip = get_local_ip()
    network_url = f"http://{lan_ip}:{port}"

    t = threading.Thread(target=run_server, args=(port,), daemon=True)
    t.start()
    time.sleep(1.5)  # wait for uvicorn to bind

    banner = [
        "=" * 60,
        "  ReelFrame — Local 4K AI Video & Image Upscaler",
        "  Author : Raliq Hidayat BM3",
        f"  Desktop: {local_url}",
        f"  Network: {network_url}  ← Open on iPhone/iPad",
        "=" * 60,
    ]
    print("\n".join(banner))

    if HAS_WEBVIEW:
        window = webview.create_window(
            title="ReelFrame 🎬⚡ — Local 4K AI Upscaler",
            url=local_url,
            width=1180,
            height=880,
            min_size=(960, 680),
            background_color="#070a12",
            text_select=True,
        )
        webview.start(debug=False)
    else:
        # Fallback: open in system default browser
        import webbrowser
        webbrowser.open(local_url)
        print("[info] pywebview not found — opened in browser instead.")
        print("[info] Press Ctrl+C to stop the server.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
