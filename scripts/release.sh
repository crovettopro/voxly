#!/bin/bash
# Release público de Voooxly: build + firma Developer ID + notarización + DMG.
#
# A diferencia de deploy.sh (desarrollo local, firma autofirmada que solo vale en
# esta máquina), esto produce un DMG que se abre en el Mac de cualquiera.
#
# Requisitos, una sola vez — ver docs/RELEASING.md:
#   1. Certificado "Developer ID Application" instalado en el llavero
#   2. Perfil de notarización guardado:
#        xcrun notarytool store-credentials voooxly \
#          --apple-id <email> --team-id <TEAMID> --password <app-specific-password>
#
# Uso: ./scripts/release.sh
#      ./scripts/release.sh --dry-run   (firma con el cert local y NO notariza:
#                                        valida toda la mecánica sin cuenta Apple)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VOOOXLY_VENV:-$HOME/.voooxly/venv}"
PROFILE="${NOTARY_PROFILE:-voooxly}"
ENTITLEMENTS="$ROOT/voooxly.entitlements"
# El repo vive en ~/Desktop, que es iCloud: reinyecta atributos extendidos
# continuamente y la firma muere con "resource fork ... detritus not allowed".
# Todo el firmado y empaquetado ocurre fuera de iCloud.
WORK="$HOME/.voooxly/release"
APP="$WORK/Voooxly.app"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

cd "$ROOT"

# ---------- comprobaciones previas (fallar aquí es barato; a mitad de notarización no) ----------
if [ "$DRY_RUN" = "1" ]; then
  # Ensayo: cualquier identidad local sirve para comprobar que el bucle de firma,
  # el hdiutil y el DMG funcionan. El resultado NO es distribuible.
  IDENTITY="${RELEASE_IDENTITY:-Voooxly Dev}"
  echo "⚠️  DRY RUN: firma con '$IDENTITY' y sin notarizar. El DMG no es distribuible."
else
  IDENTITY="$(security find-identity -v -p codesigning \
    | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)"/\1/' || true)"
  if [ -z "$IDENTITY" ]; then
    echo "ERROR: no hay certificado 'Developer ID Application' en el llavero."
    echo "       Créalo en developer.apple.com — pasos en docs/RELEASING.md"
    exit 1
  fi

  if ! xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
    echo "ERROR: no existe el perfil de notarización '$PROFILE'."
    echo "       xcrun notarytool store-credentials $PROFILE --apple-id <email> \\"
    echo "         --team-id <TEAMID> --password <app-specific-password>"
    exit 1
  fi
fi

[ -f "$ENTITLEMENTS" ] || { echo "ERROR: falta $ENTITLEMENTS"; exit 1; }

VERSION="$(grep -E '"CFBundleShortVersionString"' Voooxly.spec | head -1 | sed -E 's/.*: *"([^"]+)".*/\1/')"
[ -n "$VERSION" ] || { echo "ERROR: no pude leer la versión de Voooxly.spec"; exit 1; }

echo "→ Identidad : $IDENTITY"
echo "→ Versión   : $VERSION"
echo

# ---------- build ----------
# vendor/whisper no viaja en git (binarios de Homebrew): se regenera al vuelo
if [ -z "$(ls -A "$ROOT/vendor/whisper" 2>/dev/null)" ]; then
  echo "→ vendor/whisper vacío: vendorizando whisper-server desde Homebrew…"
  bash "$ROOT/scripts/bundle-whisper.sh" >/dev/null
fi

echo "→ Compilando con PyInstaller…"
rm -rf "$ROOT/dist/Voooxly.app"
"$VENV/bin/pyinstaller" Voooxly.spec --noconfirm | tail -1

echo "→ Copiando fuera de iCloud ($WORK)…"
rm -rf "$WORK"
mkdir -p "$WORK"
cp -R "$ROOT/dist/Voooxly.app" "$APP"
xattr -cr "$APP"

# ---------- firma ----------
# De DENTRO AFUERA: primero cada Mach-O anidado, el bundle al final. Los
# libggml-* se cargan por dlopen y necesitan firma propia o la notarización
# los rechaza. --timestamp y --options runtime son obligatorios para notarizar.
echo "→ Firmando binarios internos…"
signed=0
while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q "Mach-O"; then
    codesign --force --timestamp --options runtime \
      --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$f" >/dev/null 2>&1 && signed=$((signed+1))
  fi
done < <(find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0)
echo "  $signed binarios internos firmados"

echo "→ Firmando el bundle…"
codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

# ---------- notarización de la app ----------
if [ "$DRY_RUN" = "1" ]; then
  echo "→ (dry run: notarización de la app omitida)"
else
  echo "→ Notarizando la app (puede tardar unos minutos)…"
  ZIP="$WORK/Voooxly-$VERSION.zip"
  rm -f "$ZIP"
  ditto -c -k --keepParent "$APP" "$ZIP"
  xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
  xcrun stapler staple "$APP"
  rm -f "$ZIP"
fi

# ---------- DMG ----------
echo "→ Construyendo el DMG…"
DMG="$WORK/Voooxly-$VERSION.dmg"
STAGE="$WORK/dmg"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Voooxly" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo "→ Firmando el DMG…"
codesign --force --timestamp -s "$IDENTITY" "$DMG"

SIZE="$(du -h "$DMG" | cut -f1)"

if [ "$DRY_RUN" = "1" ]; then
  echo
  echo "✅ DRY RUN completado: $DMG ($SIZE)"
  echo "   La mecánica funciona. Para un DMG distribuible ejecuta sin --dry-run"
  echo "   una vez tengas el certificado Developer ID (docs/RELEASING.md)."
  exit 0
fi

echo "→ Notarizando el DMG…"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"

# ---------- verificación final ----------
# Esto es literalmente lo que ejecuta Gatekeeper en el Mac de quien lo descargue.
echo
echo "→ Verificación final (Gatekeeper):"
spctl -a -vvv -t install "$DMG"

echo
echo "✅ Listo: $DMG ($SIZE)"
echo
echo "   Siguientes pasos:"
echo "   1. Sube el DMG a GitHub Releases con el tag v$VERSION,"
echo "      RENOMBRADO a 'Voooxly.dmg' — sin la versión en el nombre:"
echo ""
echo "        gh release create v$VERSION \"$DMG#Voooxly.dmg\" --title \"Voooxly $VERSION\""
echo ""
echo "      appcast.json apunta a /releases/latest/download/Voooxly.dmg, un"
echo "      nombre FIJO. Subirlo como Voooxly-$VERSION.dmg deja esa URL en 404"
echo "      y rompe la actualización de todos los que ya tienen la app."
echo "   2. Actualiza appcast.json (repo voooxly-web) a la versión $VERSION y despliega"
