# Voooxly

Private, on-device voice dictation for macOS. Hold a key, speak, and clean
text appears wherever you were typing — no account, no subscription, no
telemetry.

**[⬇ Download Voooxly for macOS (Apple Silicon)](https://github.com/crovettopro/voooxly/releases/latest)**

## Get started in 2 minutes

1. **Open the DMG** and drag Voooxly to Applications.
2. **Launch it.** macOS will ask for two permissions — Microphone (to hear
   you) and Accessibility (to type into other apps). Both are required.
3. **Hold the right ⌘ key, speak, let go.** Your words appear where your
   cursor is.

That's it. Whisper runs on your Mac, so this works with no internet, no API
key and no account.

Want a different key? **Settings → Dictation key** — right ⌘/⌥/⌃, left
⌘/⌥/⌃ (a short delay keeps their combos like ⌘C working), F6/F13–F15, or
**Custom…** for anything else. Prefer pressing once to start and again to
stop instead of holding? **Settings → Dictation style**.

Two more shortcuts worth knowing: **Ctrl+Shift+M** cycles modes without
opening the menu, and **Ctrl+Shift+V** pastes your last result again. Both
are remappable in `config.yaml > hotkeys`.

## Optional: free AI with Groq (30 seconds)

Out of the box Voooxly pastes the raw transcription, which Whisper already
punctuates well. Connect an AI and it also cleans up filler words, fixes
grammar and reshapes your words to the mode you picked.

**Groq is free and takes half a minute:**

1. Go to [console.groq.com/keys](https://console.groq.com/keys) and sign in.
2. Create an API key and copy it.
3. In Voooxly's menu bar icon: **AI engine → Groq — free**, then paste the
   key when it asks.

The key is stored in your macOS Keychain, never in a file.

### What it costs you

Nothing — but "free tier" has limits, so Voooxly counts what you actually
spend. **Usage stats…** in the menu shows your running total.

| | |
|---|---|
| A typical dictation | ~500–850 tokens (estimate) |
| Groq's free limits | [see your current limits](https://console.groq.com/settings/limits) |

That range is an estimate, not a measured average — and most of it isn't
your words. About 400 of those tokens are the fixed system prompt Voooxly
sends with every request so the AI knows which mode you're in; that cost is
the same whether you dictated one sentence or three. The transcript and the
cleaned-up text each add roughly as many tokens as you spoke — tens of tokens
for a short dictation, more for a long one. Groq's free-tier limits differ
per model and change over time, so the link above is the honest answer
rather than a number that would go stale. For normal day-to-day dictation you
will not get close.

Prefer something else? The **AI engine** menu also has Claude, OpenAI and
Google Gemini — or **Ollama (local)** to run fully local with no key at all.
Other OpenAI-compatible providers (OpenRouter, DeepSeek, Mistral, Together
AI, xAI, …) can be wired up by hand — see **For developers → Configuration**.

## What it does

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

## Privacy

Audio is recorded, transcribed and discarded **on your Mac** — the Whisper model
runs locally via `whisper-server`. If you connect a cloud AI for text cleanup
(Claude/OpenAI/cloud-routed Ollama), only the transcribed **text** is sent, never
audio. With a local Ollama model or no AI at all, nothing leaves your machine.

---

## For developers

Everything below is for building Voooxly from source, running it in dev mode,
or understanding how it works internally — none of it is needed just to use
the app.

### Building from source

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

#### macOS permissions (prompted on first run)
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

**Voooxly ships with no AI connected.** It dictates and pastes the raw
transcription out of the box — that already works with nothing installed.
There is no default model baked in (`llm.ollama.model` starts empty in
`config.yaml`): shipping a fixed default would presume which model *you*
happen to have, and a cloud-only default (like Ollama's `:cloud` models)
would quietly fail for anyone without that subscription while reporting
"connected".

Connect your own from the menu bar — open **AI engine** and pick a provider:

- **Ollama (local)** — if you have the Ollama app installed, Voooxly asks
  your own server which models it has and lets you pick one; no key needed.
- **Any other provider** (Claude, OpenAI, Groq, OpenRouter, DeepSeek,
  Mistral, Together AI, xAI, or a custom OpenAI-compatible endpoint) — paste
  your API key and it's stored in the macOS Keychain.

Prefer to do it by hand, or run fully local:

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

### Project layout

```
src/voooxly/  __main__ · app · audio · stt · refine · output · hotkey · overlay · modes · config
config.yaml · scripts/ · docs/RELEASING.md
```

`vendor/whisper/` is **not** in git: it holds whisper.cpp binaries vendored from
Homebrew, and `scripts/bundle-whisper.sh` rebuilds it automatically before any
build that needs it.

### Roadmap

Next up (1.1):

- Edit Mode: select any text, speak an instruction, get it transformed.
- Per-app modes and optional on-screen context for smarter cleanup.

## License

MIT — see [LICENSE](LICENSE). Third-party components bundled in the app are
listed in [THIRD-PARTY.md](THIRD-PARTY.md).
