# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para Voxly (menu bar app, sin ventana).
# Build:  ~/.dictador/venv/bin/pyinstaller Voxly.spec

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
    name="Voxly",
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
    name="Voxly",
)

# .app bundle (LSUIElement para menu bar sin icono en Dock)
app = BUNDLE(
    coll,
    name="Voxly.app",
    icon="assets/Voxly.icns",
    # OJO: el identifier va como argumento propio y el dict se llama `info_plist`
    # (con `plist=` PyInstaller lo ignora en silencio y el app sale sin
    # NSMicrophoneUsageDescription → macOS entrega silencio del micrófono).
    # El identifier debe coincidir con el de la firma (TCC lo exige).
    # Se mantiene el bundle id original a propósito: los permisos TCC concedidos
    # (Accesibilidad/Monitorización/Micrófono) están ligados a él + al cert
    # "Dictador Dev" — cambiarlo obligaría a re-concederlos.
    bundle_identifier="com.eduardocrovetto.dictador",
    info_plist={
        "CFBundleName": "Voxly",
        "CFBundleDisplayName": "Voxly",
        "CFBundleIdentifier": "com.eduardocrovetto.dictador",
        "CFBundleVersion": "1.0.1",
        "CFBundleShortVersionString": "1.0.1",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,        # app de menu bar: sin Dock, sin menú principal
        "NSMicrophoneUsageDescription": "Voxly needs the microphone to transcribe your voice.",
        "NSSpeechRecognitionUsageDescription": "Voxly transcribes your dictation locally.",
    },
)
