# Voooxly — private, on-device voice dictation for macOS

**Hold a key, speak, let go — polished text appears in whatever app you're using.**
100% local speech-to-text on Apple Silicon: your voice never leaves your Mac.

Voooxly doesn't just transcribe. An LLM **rewrites what you said according to the
active mode** — organize your thoughts, draft a reply, shape an AI prompt, take
Markdown notes — and the result is pasted right where your cursor is.

🌐 **Website & download:** [voooxly.com](https://voooxly.com) ·
📦 **Latest DMG:** [Releases](https://github.com/crovettopro/voooxly/releases)

## Features

- **On-device STT** with `whisper.cpp` (native binary, Metal on Apple Silicon, no torch).
  Whisper large-v3-turbo: ~99 languages, strongest in English and Spanish.
- **Silence endpointing** (VAD): stop talking and it finishes on its own.
- **Modes**: the same speech comes out as clean prose, a ready-to-send reply,
  a structured AI prompt, Markdown notes, a code spec, a summary or a translation.
- **Bring your own AI (or none)**: cleanup runs through Ollama (local), Claude API
  or any OpenAI-compatible endpoint — auto-detected. Without any, Voooxly pastes the
  raw transcription, which Whisper already punctuates well.
- **Global hotkey + menu bar + live HUD**: a status HUD shows `● Listening`
  with your words appearing in real time, `✦ Processing` while it polishes and
  `✓ Pasted` when done; the menu bar turns into a red dot with a timer while
  you record.
- **Rich paste**: Markdown modes put both plain text *and* rendered HTML on the
  clipboard — Mail, Gmail or Notion paste real headings and bullet lists, while
  terminals and editors get the raw Markdown.
- **Stays out of your way**: pauses Spotify/Music while you dictate and resumes
  them after; Esc cancels; hold + Shift latches into hands-free recording.
- **Personal dictionary** (teach it names and jargon, add `wrong -> right`
  replacements), **persistent searchable history** and **usage stats**.
- **Free.** No account, no subscription, no telemetry.

## Using Voooxly

Download the DMG from [voooxly.com](https://voooxly.com), drag
Voooxly to Applications, and a first-run assistant walks you through microphone
and Accessibility permissions, the model download and (optionally) an AI engine.

- **Right ⌘ (hold)** — push-to-talk: speak while holding, release to finish.
- **Right ⌘ + Shift** — latch: recording locks hands-free; tap right ⌘ to finish.
- **Esc** — cancel the dictation in progress; nothing is pasted.
- **Ctrl+Shift+M** — cycle modes; the HUD flashes the mode you landed on
  (`❯ AI prompt · 2/8`) so you're never cycling blind.
- **Ctrl+Shift+V** — paste the last result again.

Key and behavior are configurable (`config.yaml > hotkeys`).

## Modes

| Mode | What you get |
|---|---|
| **Organize & reply** (default) | Cleans fillers and false starts; replies come out message-ready |
| **AI prompt** | A structured, reusable prompt (task, context, requirements, output) — never the answer |
| **Summarize** | Crisp bullets that keep every number, name and decision |
| **Translate EN→ES / ES→EN** | Natural translation that keeps your register and tone |
| **Code / spec** | An engineering spec: behavior, edge cases, backticked identifiers |
| **Markdown notes** | A real Markdown note: `##` title, sections, checkboxes for to-dos |
| **Verbatim** | Exactly what you said — no LLM, no rewriting |

Switch modes from the menu bar or with Ctrl+Shift+M. To make every mode follow
your personal style, add free-text rules in `config.yaml > llm.custom_rules`
("Never use semicolons", "Always spell our product name in caps", …). Building
from source? You can
define whole new modes in `src/voooxly/modes.py`.

## Privacy model

Audio is recorded, transcribed and discarded **on your Mac** — the Whisper model
runs locally via `whisper-server`. If you connect a cloud AI for text cleanup
(Claude/OpenAI/cloud-routed Ollama), only the transcribed **text** is sent, never
audio. With a local Ollama model or no AI at all, nothing leaves your machine.

---

## Building from source

Requires an Apple Silicon Mac, [Homebrew](https://brew.sh) and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/crovettopro/voooxly && cd voooxly
./scripts/install.sh
```

This installs `portaudio` + `whisper-cpp` (Homebrew), creates the venv with `uv`
in `~/.voooxly/venv`, copies `.env` and downloads the Whisper model to
`~/.voooxly/models/`.

> **Why `~/.voooxly`?** venv and models live outside any iCloud-synced folder.
> iCloud evicts large binaries and hangs builds — keep them out of Desktop/Documents.

### macOS permissions (prompted on first run)
- **Accessibility** — global hotkey + simulated Cmd+V paste.
- **Microphone** — recording.
- **Automation** — osascript pasting (first-time dialog).

If pasting doesn't work, it's almost always Accessibility/Automation not granted.

### Running

```bash
./scripts/launch.sh             # start the menu bar app in the background
./scripts/launch.sh --check     # verify backends + STT
./scripts/launch.sh --devices   # list microphones (for audio.device)
./scripts/launch.sh --fg        # run in the foreground (live logs)
```

> `launch.sh` sets `UV_PROJECT_ENVIRONMENT=~/.voooxly/venv`. If you run
> `uv run voooxly` manually, export that variable first.

### Configuration

Everything lives in `config.yaml`, with `.env` overrides (see `.env.example`):

- `VOOOXLY_LLM_BACKEND` = `ollama` | `claude` | `openai` | `none`
- `ANTHROPIC_API_KEY` — cleanup with Claude (best rewriting quality)
- `VOOOXLY_APP_LANGUAGE` — force an output language (default: keep the language you spoke)

Cleanup with a fully local model:

```bash
ollama pull qwen3:8b
# config.yaml → llm.ollama.model: "qwen3:8b"
```

### Architecture

```
hotkey (pynput) ──▶ app (rumps menu bar) ──▶ recorder (sounddevice + webrtcvad)
                                                  │ partials every ~2s ─▶ overlay (AppKit HUD)
                                                  ▼ silence
   whisper-server (subprocess, Metal) ◀── HTTP /inference (wav) ── stt.py
                                                  │
                                                  ▼ raw transcript
                                       refine (ollama/claude/openai) per mode
                                                  │
                                                  ▼
                                    output (pbcopy + Cmd+V into the active app)
```

`whisper-server` starts with the app and **keeps the model in memory**, so every
transcription (partial or final) is a fast HTTP request — no model reload, no torch.

Each block is a swappable module: `stt.py`, `refine.py`, `output.py`, `modes.py`.

### Tests

```bash
UV_PROJECT_ENVIRONMENT=~/.voooxly/venv uv run pytest tests/ -q
```

### Building the app + public release

```bash
bash scripts/make-cert.sh        # stable self-signed cert (once) — keeps TCC grants across rebuilds
bash scripts/deploy.sh           # build + install into /Applications
bash scripts/package.sh          # shareable zip for other Apple Silicon Macs
./scripts/release.sh --dry-run   # signed-DMG rehearsal without an Apple account
./scripts/release.sh             # real release: Developer ID + notarization
```

The public-release prerequisites (Developer ID certificate, notarization
credentials) and the reasoning behind each decision are in
[docs/RELEASING.md](docs/RELEASING.md).

Hard-won build gotchas:

- The PyInstaller spec takes `info_plist=` (not `plist=`, silently ignored) and
  the bundle id goes in `bundle_identifier=`; without `NSMicrophoneUsageDescription`
  macOS delivers **silence** from the mic and Whisper hallucinates "Thank you.".
- Always sign in `/Applications`, never inside an iCloud-synced folder (iCloud
  re-injects xattrs and signing fails with "detritus not allowed").
- The signing identifier must match the plist's CFBundleIdentifier or TCC won't
  associate permissions even with the toggle ON.

### Roadmap

Next up (1.1):

- Edit Mode: select any text, speak an instruction, get it transformed.
- Per-app modes and optional on-screen context for smarter cleanup.

### Project layout

```
src/voooxly/  __main__ · app · audio · stt · refine · output · hotkey · overlay · modes · config
config.yaml · scripts/ · docs/RELEASING.md
```

`vendor/whisper/` is **not** in git: it holds whisper.cpp binaries vendored from
Homebrew, and `scripts/bundle-whisper.sh` rebuilds it automatically before any
build that needs it.

## License

MIT — see [LICENSE](LICENSE). Third-party components bundled in the app are
listed in [THIRD-PARTY.md](THIRD-PARTY.md).
