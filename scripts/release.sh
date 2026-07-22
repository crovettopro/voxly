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
  # dmgbuild y el DMG funcionan. El resultado NO es distribuible.
  IDENTITY="${RELEASE_IDENTITY:-Voooxly Dev}"
  # El cert lo crea scripts/make-cert.sh. Si no está (p.ej. quedó el del nombre
  # viejo del proyecto), se tira de cualquier otra identidad local ANUNCIÁNDOLO:
  # descubrir esto tras un build entero de PyInstaller cuesta minutos.
  if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$IDENTITY\""; then
    ALT="$(security find-identity -v -p codesigning 2>/dev/null \
      | grep -v "Developer ID Application" | grep -o '"[^"]*"' | head -1 | tr -d '"' || true)"
    if [ -z "$ALT" ]; then
      echo "ERROR: no hay identidad de firma local para el ensayo."
      echo "       Créala con: ./scripts/make-cert.sh"
      exit 1
    fi
    echo "⚠️  No existe el certificado '$IDENTITY' — uso '$ALT' para el ensayo."
    echo "    Para el nombre correcto: ./scripts/make-cert.sh"
    IDENTITY="$ALT"
  fi
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
rm -f "$DMG"
# dmgbuild escribe el .DS_Store con el layout de la ventana y el icono del
# volumen, cosas que `hdiutil create` a pelo no puede poner. Sin Finder de por
# medio: determinista y sin permiso de Automatización. El symlink a
# /Applications lo crea él, así que ya no hace falta carpeta de staging.
[ -x "$VENV/bin/dmgbuild" ] || { echo "ERROR: falta dmgbuild en $VENV"; \
  echo "       uv pip install --python $VENV/bin/python 'dmgbuild>=1.6'"; exit 1; }
"$VENV/bin/dmgbuild" -s "$ROOT/scripts/dmg_settings.py" \
  -D app="$APP" -D icon="$ROOT/assets/Voooxly.icns" \
  "Voooxly" "$DMG" >/dev/null

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
echo "   1. Sube el DMG a GitHub Releases con el tag v$VERSION."
echo "      OJO: el fichero tiene que LLAMARSE 'Voooxly.dmg', sin la versión."
echo ""
echo "        cp \"$DMG\" \"$WORK/Voooxly.dmg\""
echo "        gh release create v$VERSION \"$WORK/Voooxly.dmg\" --title \"Voooxly $VERSION\""
echo ""
echo "      NO sirve la sintaxis 'fichero#Voooxly.dmg' de gh: ese '#' pone una"
echo "      ETIQUETA de display, no renombra el asset (comprobado en 1.1.0 —"
echo "      subió como Voooxly-1.1.0.dmg y la URL daba 404). Hay que copiarlo"
echo "      con el nombre bueno antes de subirlo."
echo ""
echo "      appcast.json apunta a /releases/latest/download/Voooxly.dmg, un"
echo "      nombre FIJO: si el asset se llama de otra forma, esa URL da 404 y"
echo "      rompe la actualización de todos los que ya tienen la app."
echo "   2. Actualiza appcast.json (repo voooxly-web) a la versión $VERSION y despliega"
