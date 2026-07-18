#!/usr/bin/env bash
# Arranca Dictador en segundo plano (menu bar). Logs en ~/.dictador/logs.
# El venv vive en ~/.dictador/venv (fuera de iCloud) vía UV_PROJECT_ENVIRONMENT.
cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT="$HOME/.dictador/venv"
LOG="$HOME/.dictador/logs/dictador.log"

case "${1:-}" in
  --check) exec uv run dictador --check ;;
  --devices) exec uv run dictador --devices ;;
  --fg) exec uv run dictador ;;
esac

mkdir -p "$(dirname "$LOG")"

# idempotente: cierra una instancia previa de dictador (el whisper-server se reutiliza solo)
if pgrep -f "dictador/venv/bin/dictador" >/dev/null 2>&1 || pgrep -f "uv run dictador" >/dev/null 2>&1; then
  echo "Cerrando instancia previa de Dictador…"
  pkill -f "dictador/venv/bin/dictador" 2>/dev/null
  pkill -f "uv run dictador" 2>/dev/null
  sleep 2
fi

nohup uv run dictador >> "$LOG" 2>&1 &
echo "Dictador arrancado (PID $!). Log: $LOG"
echo "Permisos: Sistema > Privacidad y seguridad > Accesibilidad + Micrófono."
echo "Stop:  pkill -f 'uv run dictador'  (o Cierra desde el menú 🎙)"