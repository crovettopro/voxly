# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para Voooxly (menu bar app, sin ventana).
# Build:  ~/.voooxly/venv/bin/pyinstaller Voooxly.spec

block_cipher = None

hiddenimports = [
    "pynput.keyboard._darwin",
    "pynput.mouse._darwin",
    "pynput._util.darwin",
    "rumps",
    "AppKit",
    "Quartz",
    "ApplicationServices",
    "Cocoa",
    "sounddevice",
    "webrtcvad",
    "numpy",
    "yaml",
    "requests",
    "anthropic",
    "Security",
]

datas = [
    ("config.yaml", "."),
    (".env.example", "."),
    ("assets/menubar.png", "assets"),
    ("assets/menubar@2x.png", "assets"),
    ("assets/menubar-rec.png", "assets"),
    ("assets/menubar-rec@2x.png", "assets"),
]

# whisper-server embebido + sus dylibs/backends (generado por
# scripts/bundle-whisper.sh) — el receptor no necesita Homebrew.
import glob as _glob

vendor_whisper = [(p, "whisper") for p in _glob.glob("vendor/whisper/*")]
if not vendor_whisper:
    raise SystemExit("vendor/whisper vacío: ejecuta scripts/bundle-whisper.sh antes del build")

a = Analysis(
    ["entry.py"],
    pathex=["src"],
    binaries=vendor_whisper,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "tkinter"],
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
    name="Voooxly",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # app de menu bar: sin consola
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
    name="Voooxly",
)

# .app bundle (LSUIElement para menu bar sin icono en Dock)
app = BUNDLE(
    coll,
    name="Voooxly.app",
    icon="assets/Voooxly.icns",
    # OJO: el identifier va como argumento propio y el dict se llama `info_plist`
    # (con `plist=` PyInstaller lo ignora en silencio y el app sale sin
    # NSMicrophoneUsageDescription → macOS entrega silencio del micrófono).
    # El identifier debe coincidir con el de la firma (TCC lo exige).
    # OJO: los permisos TCC (Accesibilidad/Monitorización/Micrófono) cuelgan de
    # este identifier + el certificado. Tocarlo obliga a re-concederlos TODOS,
    # así que no se cambia salvo por un renombrado de marca como el de 1.0.0.
    bundle_identifier="com.eduardocrovetto.voooxly",
    info_plist={
        "CFBundleName": "Voooxly",
        "CFBundleDisplayName": "Voooxly",
        "CFBundleIdentifier": "com.eduardocrovetto.voooxly",
        "CFBundleVersion": "1.5.1",
        "CFBundleShortVersionString": "1.5.1",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,        # app de menu bar: sin Dock, sin menú principal
        "NSMicrophoneUsageDescription": "Voooxly needs the microphone to transcribe your voice.",
        "NSSpeechRecognitionUsageDescription": "Voooxly transcribes your dictation locally.",
    },
)
