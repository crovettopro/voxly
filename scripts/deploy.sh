#!/bin/bash
# Build + deploy local de Voxly.app a /Applications.
#
# - Compila con PyInstaller (el spec ya lleva bundle_identifier + info_plist correctos)
# - Firma SIEMPRE en /Applications (en dist/ iCloud re-inyecta xattrs y la firma
#   falla con "resource fork ... detritus not allowed")
# - Usa la identidad "Dictador Dev" si existe (permisos TCC estables entre builds;
#   créala con scripts/make-cert.sh). Si no, firma ad-hoc: cada rebuild invalida
#   Accesibilidad/Monitorización de entrada/Micrófono y hay que re-concederlos.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${DICTADOR_VENV:-$HOME/.dictador/venv}"
APP=/Applications/Voxly.app
IDENTITY="Dictador Dev"

cd "$ROOT"
echo "→ Compilando con PyInstaller…"
"$VENV/bin/pyinstaller" Voxly.spec --noconfirm | tail -1

echo "→ Desplegando a /Applications…"
osascript -e 'quit app "Voxly"' 2>/dev/null || true
pkill -x Voxly 2>/dev/null || true
# el whisper-server hijo sobrevive al pkill del padre; si queda vivo, la app
# nueva reutiliza el puerto y sigue sirviendo el MODELO VIEJO ya cargado
pkill -f whisper-server 2>/dev/null || true
sleep 1
rm -rf "$APP"
ditto dist/Voxly.app "$APP"
xattr -cr "$APP"

if security find-identity -v -p codesigning 2>/dev/null | grep -q "$IDENTITY"; then
  echo "→ Firmando con '$IDENTITY' (firma estable)…"
  codesign --force --deep -s "$IDENTITY" "$APP"
else
  echo "→ Firmando ad-hoc (¡los permisos TCC se invalidarán! usa make-cert.sh)…"
  codesign --force --deep -s - "$APP"
fi

codesign --verify --deep --strict "$APP"
echo "→ OK: $(codesign -d --verbose=2 "$APP" 2>&1 | grep '^Identifier=')"
echo "→ Lanza con: open $APP"
