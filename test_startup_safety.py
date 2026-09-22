"""Regression tests for ReelFrame startup/encoding safety.

Bug history:
  "black window flashes then closes" — desktop_app.py printed a non-ASCII glyph
  ('\u2190') to a cp1252 Windows console, raising UnicodeEncodeError inside the
  PyInstaller bootstrap and killing the process before the window could show.

These tests lock in the fix so it can never regress silently.
"""
import importlib
import io
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))


class _Cp1252Stream(io.TextIOBase):
    """A stream that raises UnicodeEncodeError on non-cp1252 text (like a real console)."""

    def write(self, s):  # type: ignore[override]
        s.encode("cp1252")
        return len(s)

    def flush(self):  # type: ignore[override]
        pass


def test_banner_is_ascii_safe():
    """The startup banner must contain no glyph a legacy code page can't encode."""
    src = (SCRIPT_DIR / "desktop_app.py").read_text(encoding="utf-8")
    i = src.index("banner = [")
    j = src.index("]", i)
    block = src[i : j + 1]
    bad = [(c, hex(ord(c))) for c in block if ord(c) > 127]
    assert not bad, f"non-ASCII glyphs in banner (will crash cp1252 consoles): {bad}"


def test_safe_print_survives_broken_console():
    """_safe_print must never propagate an encoding error."""
    mod = importlib.import_module("desktop_app")
    original = sys.stdout
    sys.stdout = _Cp1252Stream()
    try:
        mod._safe_print("arrow: \u2190\u2192\u2191\u2193  emoji: \U0001f3ac")
    finally:
        sys.stdout = original  # no exception == pass


def test_safe_filename_hardening():
    """Upload filenames are sanitized (no traversal, no reserved chars, no None)."""
    gui = importlib.import_module("gui")
    assert gui.safe_filename(None) == "upload"
    assert gui.safe_filename("") == "upload"
    assert gui.safe_filename("../../etc/passwd") == "passwd"
    assert gui.safe_filename(r"..\..\windows\system32\evil.exe") == "evil.exe"
    assert "/" not in gui.safe_filename("a/b/c.mp4")
    assert "\\" not in gui.safe_filename("a\\b.mp4")
    assert gui.safe_filename("..") == "upload"


if __name__ == "__main__":
    test_banner_is_ascii_safe()
    print("PASS test_banner_is_ascii_safe")
    test_safe_print_survives_broken_console()
    print("PASS test_safe_print_survives_broken_console")
    test_safe_filename_hardening()
    print("PASS test_safe_filename_hardening")
    print("\nAll regression tests passed.")
