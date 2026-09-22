#!/usr/bin/env python3
"""
ReelFrame Desktop App — Windows Native (WebView2-powered)
Author: Raliq Hidayat BM3
Repository: https://github.com/kouji999/ReelFrame
"""
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Console / logging safety (must run before ANY print()).
#
# The Windows console defaults to a legacy code page (cp1252/cp437 on many
# machines). Printing a non-ASCII glyph (e.g. "←") into that codec raises
# UnicodeEncodeError and — inside a PyInstaller one-file/one-dir bootstrap —
# kills the whole process, which is the classic "black window flashes then
# vanishes" symptom. Force UTF-8 with safe fallbacks so a stray glyph can
# never take the app down again.
# ---------------------------------------------------------------------------
def _make_std_streams_utf8_safe() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            # Python 3.7+: reconfigure the underlying TextIOWrapper to UTF-8
            # and replace (never raise) on characters the terminal can't map.
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            # Non-reconfigurable stream (e.g. pythonw, redirected pipe):
            # wrap it in a tolerant writer.
            try:
                import io
                setattr(
                    sys,
                    stream_name,
                    io.TextIOWrapper(
                        stream.buffer, encoding="utf-8", errors="replace", line_buffering=True
                    ),
                )
            except Exception:
                pass


_make_std_streams_utf8_safe()


def _safe_print(*args, **kwargs) -> None:
    """print() that can never crash the process on an encoding error."""
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            text = " ".join(str(a) for a in args)
            sys.stdout.buffer.write(text.encode("utf-8", "replace") + b"\n")
            sys.stdout.buffer.flush()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Crash log — always give the user something to read instead of a silent exit.
# When frozen by PyInstaller, __file__ lives inside the (read-only) bundle, so
# write logs next to the executable / in the user profile instead.
# ---------------------------------------------------------------------------
def _resolve_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resolve_log_dir() -> Path:
    """Prefer a user-writable location so the frozen app can always log."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(_resolve_app_dir() / "logs")
    candidates.append(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ReelFrame" / "logs")
    candidates.append(Path.home() / ".reelframe" / "logs")
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".writetest"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return c
        except Exception:
            continue
    return Path.home()


SCRIPT_DIR = _resolve_app_dir()
LOG_DIR = _resolve_log_dir()
LOG_FILE = LOG_DIR / "reelframe-desktop.log"


def log(message: str) -> None:
    _safe_print(message)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
    except Exception:
        pass


def show_fatal_error(message: str, detail: str) -> None:
    """Best-effort: make a fatal startup error visible on a GUI-only launch."""
    _safe_print("\n" + "=" * 66)
    _safe_print("  ReelFrame could not start")
    _safe_print("=" * 66)
    _safe_print(message)
    if detail:
        _safe_print("\n--- technical detail ---")
        _safe_print(detail)
    _safe_print(f"\nFull log: {LOG_FILE}")
    _safe_print("=" * 66)

    # If we're in a console-less launch, pop a native dialog so it's not silent.
    title = "ReelFrame - Startup Error"
    body = f"{message}\n\n{detail[:800]}\n\nLog: {LOG_FILE}"
    shown = False
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, body, title, 0x10)  # MB_ICONERROR
            shown = True
        elif sys.platform == "darwin":
            # AppleScript dialog; quote-escape for safety.
            esc = body.replace("\\", "\\\\").replace('"', '\\"')
            import subprocess
            subprocess.run(
                ["osascript", "-e",
                 f'display dialog "{esc}" with title "{title}" buttons {{"OK"}} default button "OK" with icon stop'],
                check=False,
            )
            shown = True
    except Exception:
        pass

    # Keep the console window alive briefly so a double-click user can read it.
    if not shown:
        try:
            _safe_print("\nPress Enter to close...")
            input()
        except Exception:
            pass


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


def wait_for_server(port: int, timeout: float = 20.0) -> bool:
    """Poll until uvicorn actually accepts connections (instead of a blind sleep)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main() -> None:
    port = find_free_port(7860)
    local_url = f"http://127.0.0.1:{port}"
    lan_ip = get_local_ip()
    network_url = f"http://{lan_ip}:{port}"

    t = threading.Thread(target=run_server, args=(port,), daemon=True)
    t.start()

    if not wait_for_server(port):
        raise RuntimeError(
            f"Backend server did not come up on port {port} within 20s. "
            "Check that the ReelFrame server dependencies are installed."
        )

    # ASCII-only banner: safe on any code page (no ← arrow).
    banner = [
        "=" * 60,
        "  ReelFrame - Local 4K AI Video & Image Upscaler",
        "  Author : Raliq Hidayat BM3",
        f"  Desktop: {local_url}",
        f"  Network: {network_url}   (open this on your iPhone/iPad)",
        "=" * 60,
    ]
    for line in banner:
        log(line)

    if HAS_WEBVIEW:
        webview.create_window(
            title="ReelFrame - Local 4K AI Upscaler",
            url=local_url,
            width=1180,
            height=880,
            min_size=(960, 680),
            background_color="#070a12",
            text_select=True,
        )
        webview.start(debug=False)
    else:
        import webbrowser

        webbrowser.open(local_url)
        log("[info] pywebview not found - opened in your browser instead.")
        log("[info] Press Ctrl+C to stop the server.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level safety net on purpose
        show_fatal_error(
            "ReelFrame hit an unexpected error while starting.",
            f"{exc}\n\n{traceback.format_exc()}",
        )
        log("FATAL: " + traceback.format_exc())
        sys.exit(1)
