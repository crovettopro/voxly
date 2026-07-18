#!/bin/bash
# Vendoriza whisper-server (de Homebrew) dentro del repo → vendor/whisper/
# para que Voxly.app lo lleve EMBEBIDO y el receptor no necesite Homebrew.
#
# - Copia el binario + clausura de dylibs (libwhisper, libggml*)
# - IMPORTANTE: ggml carga sus backends (libggml-cpu/metal/blas) por dlopen
#   desde su propio directorio → se copian TODOS los libggml-*
# - Reescribe los install names a @loader_path (todo plano en un dir)
# - Re-firma ad-hoc cada Mach-O (la firma final la pone deploy/package)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/vendor/whisper"
BIN="${WHISPER_SERVER:-/opt/homebrew/bin/whisper-server}"
SEARCH_DIRS=(/opt/homebrew/opt/whisper-cpp/lib /opt/homebrew/opt/ggml/lib /opt/homebrew/lib)

[ -x "$BIN" ] || { echo "ERROR: no encuentro whisper-server ($BIN). brew install whisper-cpp"; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"
cp -f "$(realpath "$BIN")" "$OUT/whisper-server"

resolve() {  # dep ref → ruta real en disco
  local ref="$1"
  if [[ "$ref" == @rpath/* ]]; then
    local name="${ref#@rpath/}"
    for d in "${SEARCH_DIRS[@]}"; do
      [ -e "$d/$name" ] && { realpath "$d/$name"; return; }
    done
    return 1
  fi
  [ -e "$ref" ] && realpath "$ref"
}

# clausura BFS de dependencias de homebrew/@rpath
copied=1
while [ "$copied" -eq 1 ]; do
  copied=0
  for f in "$OUT"/*; do
    while IFS= read -r dep; do
      name="$(basename "$dep" )"
      if [ ! -e "$OUT/$name" ]; then
        src="$(resolve "$dep")" || { echo "ERROR: no resuelvo $dep"; exit 1; }
        cp -f "$src" "$OUT/$name"
        copied=1
      fi
    done < <(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -E '^(@rpath/|/opt/homebrew/)' || true)
  done
done

# backends dlopen de ggml (Metal/CPU/BLAS): viven como .so en libexec/ y ggml
# los busca en una ruta COMPILADA que no existe en otros Macs → se copian aquí
# y stt.py exporta GGML_BACKEND_PATH al lanzar el server embebido.
for lib in /opt/homebrew/opt/ggml/libexec/*.so; do
  [ -e "$lib" ] || continue
  name="$(basename "$lib")"
  [ -e "$OUT/$name" ] || cp -f "$(realpath "$lib")" "$OUT/$name"
done

# segunda pasada de clausura: los .so también traen deps
for f in "$OUT"/*.so; do
  [ -e "$f" ] || continue
  while IFS= read -r dep; do
    name="$(basename "$dep")"
    if [ ! -e "$OUT/$name" ]; then
      src="$(resolve "$dep")" || { echo "ERROR: no resuelvo $dep"; exit 1; }
      cp -f "$src" "$OUT/$name"
    fi
  done < <(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -E '^(@rpath/|/opt/homebrew/)' || true)
done

# reescritura de install names → @loader_path (dir plano)
for f in "$OUT"/*; do
  base="$(basename "$f")"
  if [[ "$base" == *.dylib || "$base" == *.so ]]; then
    install_name_tool -id "@loader_path/$base" "$f" 2>/dev/null
  fi
  while IFS= read -r dep; do
    install_name_tool -change "$dep" "@loader_path/$(basename "$dep")" "$f" 2>/dev/null
  done < <(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -E '^(@rpath/|/opt/homebrew/)' || true)
  codesign --force -s - "$f" 2>/dev/null
done

echo "OK: $(ls "$OUT" | wc -l | tr -d ' ') ficheros en vendor/whisper ($(du -sh "$OUT" | cut -f1))"
ls -la "$OUT"