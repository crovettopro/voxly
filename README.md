# Dictador — dictado local pro tipo Wispr Flow

Sistema de dictado por voz **100% local** en macOS (Apple Silicon). No solo transcribe:
un LLM **ordena y mejora** lo que dices según el **modo** activo. Se lanza con un hotkey,
dictas, te callas, y el resultado se pega solo en la app activa.

- **STT on-device** con `whisper.cpp` (binario nativo, Metal/CoreML en Apple Silicon, **sin torch**).
- **VAD + endpointing** por silencio (te callas → se cierra solo, como Wispr).
- **Refino LLM** por modo: Ollama (local/cloud) por defecto, o Claude API, o OpenAI-compatible.
- **Hotkey global** + **menu bar** + **overlay HUD** con transcripción en vivo.

> **Nota sobre iCloud:** el código va en `~/Desktop/code-edu/dictado-local`, pero el
> **venv y los modelos se guardan en `~/.dictador/`** (fuera de iCloud) para evitar los
> cuelgues por evicción de iCloud que sufren los binarios grandes en `~/Desktop`.

Ver `RESEARCH.md` para el análisis de cómo funciona Wispr Flow y por qué este stack.

## Instalación

```bash
cd ~/Desktop/code-edu/dictado-local
./scripts/install.sh
```

Esto instala `portaudio` + `whisper-cpp` (Homebrew), crea el venv con `uv` en `~/.dictador/venv`
(fuera de iCloud), copia `.env` y descarga el modelo `ggml-large-v3-turbo` (~1.6GB) a `~/.dictador/models/`.

### Permisos de macOS (te los pedirá al arrancar)
- **Accesibilidad** → para el hotkey global y simular Cmd+V. Sistema > Privacidad y seguridad > Accesibilidad.
- **Micrófono** → para grabar. Sistemas > Privacidad y seguridad > Micrófono.
- **Automatización** → para que osascript pegue. Sale un diálogo la primera vez.

Si el paste no funciona, suele ser Accesibilidad/Automatización sin conceder.

## Uso

```bash
./scripts/launch.sh             # arranca la app de menú en background
./scripts/launch.sh --check     # verifica backends + STT
./scripts/launch.sh --devices   # lista mics (para elegir audio.device)
./scripts/launch.sh --fg        # arranca en primer plano (ver logs en vivo)
```

> `launch.sh` ya pone `UV_PROJECT_ENVIRONMENT=~/.dictador/venv`. Si lanzas a mano con
> `uv run dictador`, exporta esa variable antes.

Aparece 🎙 en la barra de menús.

- **F5** → empezar/parar dictado (configúralo en `config.yaml > hotkeys.toggle`).
- Habla. El overlay muestra la transcripción en vivo.
- Te callas ~1.2s → se cierra solo, refina y pega.
- **Ctrl+Shift+M** → cambia de modo.
- **Ctrl+Shift+V** → vuelve a pegar el último resultado.

## Modos

| Modo | Qué hace |
|---|---|
| **Ordenar ideas** (default) | Limpia muletillas, estructura, sin inventar |
| **Responder a personas** | Lo convierte en email/mensaje bien redactado |
| **Prompt para IA** | Lo convierte en un prompt claro para un LLM |
| **Resumir** | Bullets concisos |
| **Traducir EN→ES / ES→EN** | Traducción manteniendo tono |
| **Código / spec** | Spec/comentario de código |
| **Notas Markdown** | Nota con headings y listas |
| **Literal** | Solo transcribe, sin reescritura |

Cambia de modo desde el menú o con Ctrl+Shift+M. Define los tuyos en `src/dictador/modes.py`.

## Configuración

Todo en `config.yaml`. Overrides por entorno en `.env` (ver `.env.example`):

- `DICTADOR_LLM_BACKEND` = `ollama` | `claude` | `openai`
- `ANTHROPIC_API_KEY` para refino con Claude (mejor reescritura)
- `DICTADOR_STT_MODEL` para cambiar de modelo (p.ej. `mlx-community/whisper-medium` si 8GB va justa)
- `DICTADOR_APP_LANGUAGE` idioma de salida (`es`, `en`, …)

### Refino con Ollama
Por defecto usa `glm-5.2:cloud` enrutado por tu Ollama local. Sirve cualquier modelo:
```bash
ollama pull qwen3:8b         # modelo local puro, sin red
# y en config.yaml: llm.ollama.model: "qwen3:8b"
```

## Arquitectura

```
hotkey (pynput) ──▶ app (rumps menubar) ──▶ recorder (sounddevice + webrtcvad)
                                                  │ partials cada 1.5s ─▶ overlay (AppKit HUD)
                                                  ▼ silencio
   whisper-server (subprocess, Metal) ◀── HTTP /inference (wav) ── stt.py
                                                  │
                                                  ▼ texto crudo
                                       refine (ollama/claude/openai) según modo
                                                  │
                                                  ▼
                                    output (pbcopy + Cmd+V en la app activa)
```

`whisper-server` se lanza al arrancar y **mantiene el modelo en memoria**, así cada
transcripción (partial o final) es una petición HTTP rápida sin recargar modelo y sin torch.

Cada bloque es un módulo swappable: `stt.py`, `refine.py`, `output.py`, `modes.py`.

## Limitaciones / siguientes pasos
- Aprender de correcciones (log de edits + few-shot en el prompt) — lo que hace Wispr.
- ASR condicionado por contexto (leer ventana activa).
- Dictionary / snippets personales.

## Estructura
```
src/dictador/  __main__ · app · audio · stt · refine · output · hotkey · overlay · modes · config
config.yaml · .env.example · scripts/install.sh · RESEARCH.md
```