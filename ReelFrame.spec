# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ReelFrame (Windows desktop app).

Key points:
  * console=False  -> no black console window flashes on launch. The app shows
    a native error dialog + writes logs/reelframe-desktop.log if startup fails,
    so problems are never silent.
  * icon           -> brand icon from web/icon.ico.
  * hiddenimports  -> uvicorn/pywebview/pythonnet/spandrel plugin modules that
    PyInstaller can't discover by static analysis.
"""
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

datas = [
    ('web', 'web'),          # UI + favicon + icon assets
    ('models', 'models'),    # AI model weights (present at build time)
]

hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespans',
    'uvicorn.lifespans.on',
    'engineio.async_drivers.asgi',
    'webview',
    'webview.platforms.winforms',
    'clr',
    'pythonnet',
    'fastapi',
    'starlette',
    'pydantic',
    'spandrel',
    'spandrel.architectures',
    'cv2',
    'torch',
    'torchvision',
    'PIL',
    'tqdm',
    'multipart',
    'requests',
    'python_multipart',
]
hiddenimports += collect_submodules('spandrel.architectures')

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PySide2', 'PySide6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ReelFrame',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # windowed app: no console flash
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/icon.ico',           # brand icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ReelFrame',
)
