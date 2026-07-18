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
nohup uv run dictador >> "$LOG" 2>&1 &
echo "Dictador arrancado (PID $!). Log: $LOG"
echo "Permisos: Sistema > Privacidad y seguridad > Accesibilidad + Micrófono."
echo "Stop:  pkill -f 'uv run dictador'  (o Cierra desde el menú 🎙)"