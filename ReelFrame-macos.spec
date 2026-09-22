# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ReelFrame on macOS — builds ReelFrame.app.

Usage:
    pyinstaller ReelFrame-macos.spec --noconfirm --clean
Result:
    dist/ReelFrame.app   (drag to /Applications)

Note: macOS requires pywebview's native backend (pyobjc, pulled in by
pywebview[macos]). Torch runs on Metal/MPS automatically.
"""
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('web', 'web'),
    ('models', 'models'),
]

hiddenimports = [
    'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespans', 'uvicorn.lifespans.on',
    'webview', 'webview.platforms.cocoa',
    'fastapi', 'starlette', 'pydantic', 'spandrel',
    'cv2', 'torch', 'torchvision', 'PIL', 'tqdm', 'multipart', 'requests',
    'python_multipart',
]
hiddenimports += collect_submodules('spandrel.architectures')

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PySide2', 'PySide6'],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ReelFrame',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='ReelFrame',
)

app = BUNDLE(
    coll,
    name='ReelFrame.app',
    icon='web/icon.icns',
    bundle_identifier='com.raliqbm3.reelframe',
    info_plist={
        'CFBundleName': 'ReelFrame',
        'CFBundleDisplayName': 'ReelFrame',
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleVersion': '2.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'NSRequiresAquaSystemAppearance': False,
    },
)
