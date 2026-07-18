#!/usr/bin/env bash
# Instalación de Dictador en macOS (Apple Silicon).
# Mantiene el venv y los modelos FUERA de iCloud (~/.dictador) para evitar
# los cuelgues por evicción de iCloud en ~/Desktop.
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
DATA_DIR="$HOME/.dictador"
export UV_PROJECT_ENVIRONMENT="$DATA_DIR/venv"

echo "==> Dictador installer"
echo "    Proyecto : $PROJECT_DIR"
echo "    Datos    : $DATA_DIR (venv + modelos, fuera de iCloud)"

mkdir -p "$DATA_DIR/venv" "$DATA_DIR/models" "$DATA_DIR/logs"

# 1) dependencias de sistema
echo "==> 1) Dependencias de sistema"
if ! brew list portaudio >/dev/null 2>&1; then
  echo "    Instalando portaudio…"; brew install portaudio
else echo "    portaudio OK"; fi
if ! brew list whisper-cpp >/dev/null 2>&1; then
  echo "    Instalando whisper-cpp…"; brew install whisper-cpp
else echo "    whisper-cpp OK"; fi

# 2) entorno Python con uv (venv fuera de iCloud)
echo "==> 2) Entorno Python (uv)"
uv sync

# 3) .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    Creado .env (edítalo si quieres Claude/OpenAI)"
fi

# 4) modelo whisper.cpp (~1.6GB)
MODEL="$DATA_DIR/models/ggml-large-v3-turbo.bin"
if [ ! -f "$MODEL" ]; then
  echo "==> 4) Descargando modelo ggml-large-v3-turbo (~1.6GB)…"
  python3 - <<'PY'
import urllib.request, os
url='https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin'
dst=os.path.expanduser('~/.dictador/models/ggml-large-v3-turbo.bin')
urllib.request.urlretrieve(url, dst)
print('    modelo descargado')
PY
else echo "==> 4) Modelo ya presente"; fi

echo ""
echo "==> Listo. Permisos que macOS te pedirá al arrancar:"
echo "    - Accesibilidad  (hotkey + paste)  → Sistema > Privacidad y seguridad > Accesibilidad"
echo "    - Micrófono      (grabación)        → Sistema > Privacidad y seguridad > Micrófono"
echo "    Arranca con:  ./scripts/launch.sh"
echo "    Verifica:     ./scripts/launch.sh --check"