#!/bin/bash
# Empaqueta Voxly para compartir con otros Macs:
#   dist/Voxly-vX.Y.Z-share.zip  →  Voxly.app + install.sh + README.txt
# El receptor descomprime y ejecuta:  bash install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${DICTADOR_VENV:-$HOME/.dictador/venv}"
VERSION="$(grep CFBundleShortVersionString -A0 "$ROOT/Voxly.spec" | grep -o '[0-9.]*' | head -1)"
SHARE="$ROOT/dist/share"
ZIP="$ROOT/dist/Voxly-v${VERSION}-share.zip"

cd "$ROOT"
if [ ! -d dist/Voxly.app ]; then
  echo "→ No hay build en dist/: compilando…"
  "$VENV/bin/pyinstaller" Voxly.spec --noconfirm | tail -1
fi

echo "→ Montando paquete…"
rm -rf "$SHARE" "$ZIP"
mkdir -p "$SHARE"
ditto dist/Voxly.app "$SHARE/Voxly.app"
xattr -cr "$SHARE/Voxly.app"
cp scripts/install-app.sh "$SHARE/install.sh"
chmod +x "$SHARE/install.sh"

# --- Firma de distribución + notarización (si hay Developer ID) ---
# Con cert "Developer ID Application" + credencial notarytool, el receptor
# instala con doble click sin avisos de Gatekeeper. Sin ellos, el zip sale
# igualmente y el receptor usa install.sh (re-firma ad-hoc local).
DEVID="$(security find-identity -v -p codesigning 2>/dev/null | grep -o '"Developer ID Application: [^"]*"' | head -1 | tr -d '"' || true)"
NOTARY_PROFILE="${NOTARY_PROFILE:-voxly}"
if [ -n "$DEVID" ]; then
  echo "→ Firmando distribución con: $DEVID"
  codesign --force --deep --options runtime --timestamp \
    --entitlements "$ROOT/voxly.entitlements" -s "$DEVID" "$SHARE/Voxly.app"
  codesign --verify --deep --strict "$SHARE/Voxly.app"
  if xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
    echo "→ Notarizando con Apple (puede tardar unos minutos)…"
    NZIP="$(mktemp -d)/Voxly-notarize.zip"
    ditto -c -k --keepParent "$SHARE/Voxly.app" "$NZIP"
    xcrun notarytool submit "$NZIP" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$SHARE/Voxly.app"
    echo "→ Notarizado y grapado: instalación por doble click en cualquier Mac."
  else
    echo "AVISO: firmado con Developer ID pero SIN notarizar (falta credencial notarytool)."
    echo "Créala una vez con:"
    echo "  xcrun notarytool store-credentials $NOTARY_PROFILE \\"
    echo "    --apple-id TU_APPLE_ID --team-id TU_TEAM_ID --password APP_SPECIFIC_PASSWORD"
  fi
else
  echo "AVISO: sin cert 'Developer ID Application' en el llavero — el receptor usará install.sh."
  echo "Créalo en developer.apple.com → Certificates → Developer ID Application (o Xcode → Settings → Accounts)."
fi

cat > "$SHARE/README.txt" <<'EOF'
VOXLY — private, on-device voice dictation for macOS (Apple Silicon)

Speak. Release. Pasted. Everything runs ON YOUR MAC — your voice
never leaves the machine. The speech engine is built in; the model
(~550MB) downloads itself on first launch (watch the 🎙 icon).

Install:
  1. Drag Voxly.app into /Applications and open it.
     (If macOS refuses to open it: run `bash install.sh` instead.)
  2. System Settings → Privacy & Security: add /Applications/Voxly.app
     with the «+» button and enable it in BOTH panes:
        • Accessibility        • Input Monitoring
  3. Accept the microphone prompt the first time you dictate.

Use:
  • Hold RIGHT Cmd, speak, release → transcribed, polished, pasted
  • Ctrl+Shift+M cycles rewrite modes (Organize & reply, AI prompt,
    Summarize, Translate…)
  • Menu → Recent: your last dictations, click to copy again
  • Menu → Settings: Start at login, Sounds

AI polish (optional): Voxly auto-detects whatever you have — Ollama
running locally, or an ANTHROPIC_API_KEY / OPENAI_API_KEY in
~/.dictador/.env. With none of them it pastes the raw transcription
(check the "AI:" row in the menu).
EOF

echo "→ Comprimiendo…"
ditto -c -k --keepParent "$SHARE" "$ZIP"
echo "LISTO: $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "Compártelo por AirDrop/Drive; el receptor: descomprimir → bash install.sh"
