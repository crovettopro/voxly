# Voooxly

**Hold a key, speak, and finished text appears wherever you were typing.**

Voooxly is voice dictation for macOS that transcribes on your Mac — your voice
never goes anywhere. Connect a free AI key and it goes further: it cleans up
the "um"s, the false starts and the half-corrected sentences, and gives you
what you *meant* to write.

No account. No subscription. No telemetry. MIT-licensed.

**[⬇ Download Voooxly for macOS (Apple Silicon)](https://github.com/crovettopro/voooxly/releases/latest)**

<sub>Apple Silicon only · macOS 13+ · ~2 min to set up</sub>

## Get started in 2 minutes

1. **Open the DMG** and drag Voooxly to Applications.
2. **Launch it.** macOS will ask for two permissions — Microphone (to hear
   you) and Accessibility (to type into other apps). Both are required.
3. **Hold the right ⌘ key, speak, let go.** Your words appear where your
   cursor is.

That's it. Whisper runs on your Mac, so this works with no internet, no API
key and no account.

## Using Voooxly

**Nothing here is fixed. Every shortcut below can be changed from Settings →
Shortcuts…**, one window in the menu bar for all four:

| | |
|---|---|
| **Hold right ⌘** | Dictation — dictate |
| **Ctrl+Shift+M** | Cycle mode — switch to the next mode |
| **Shift** (while holding) | Latch dictation — keep recording hands-free, so you can let go |
| **Esc** | Cancel dictation — throw away what's in progress |

**Settings → Shortcuts…** lets you press new keys for any of the four, pick
"hold" or "tap to start/stop" for Dictation, and set its guard delay with a
slider (0–800 ms). The guard delay only matters for keys that double as
modifiers — right ⌘/⌥/⌃ and left ⌘/⌥/⌃ are the ones most people pick, and the
left ones need a short hold rather than a tap, which is exactly what keeps
⌘C, ⌘V and ⌘Tab working normally while that key also dictates.

Talk as long as you need — a single dictation can run up to five minutes.

## Then connect an AI. This is the part that matters.

Everything above already works with no account and no key. But **transcription
is not writing.** You backtrack, you say "um", you start the sentence twice,
you correct yourself halfway through. A transcript gives you all of that,
faithfully. It's you, typed out — mess included.

Connect an AI and Voooxly hands you the text you *meant*:

**What you say into the mic**

> "um so basically I need to tell the team the deploy is uh is delayed,
> delayed until Thursday because the migration, the database migration failed
> twice, so yeah can we push the demo"

**What lands at your cursor**

> Heads up — the deploy is delayed until Thursday: the database migration
> failed twice. Can we push the demo?

Same meaning, same voice, none of the mess — it doesn't formalize you or put
words in your mouth. That's the default **Organize & reply** mode; the same
sentence comes out as bullet points, a Markdown note, an engineering spec or a
translation depending on which mode you're in ([see the table below](#modes)).

**This is the difference between dictating and being done.**

### It's free. Thirty seconds.

Groq gives you an API key for nothing:

1. Go to [console.groq.com/keys](https://console.groq.com/keys) and sign in.
2. Create an API key and copy it.
3. Menu bar icon → **AI engine → Groq — free**, then paste the key.

That's it — the menu now reads **AI engine — Groq** and every dictation from
here on gets cleaned up. Your key goes into the macOS Keychain, never into a
file in this repo or anywhere else.

### What it costs you

Nothing, but "free tier" means limits exist, so Voooxly counts what you
actually spend. **Usage stats…** in the menu shows your running total.

| | |
|---|---|
| A typical dictation | ~500–850 tokens (estimate) |
| Groq's free limits | [see your current limits](https://console.groq.com/settings/limits) |

That range is an estimate, not a measured average — and most of it isn't your
words. About 400 of those tokens are the fixed instruction Voooxly sends with
every request so the AI knows which mode you're in; that cost is identical
whether you dictated one sentence or three. Your transcript and the cleaned-up
text each add roughly as many tokens as you spoke — tens for a quick sentence,
more for a long one. Groq's limits differ per model and change over time, so
the link above is the honest answer rather than a number that goes stale here.
Day-to-day dictation will not get close to them.

### Or bring a different one

The **AI engine** menu has five options, and switching is one click:

| Provider | What it needs |
|---|---|
| **Groq** | a free API key |
| **Claude** | your API key |
| **OpenAI** | your API key |
| **Google Gemini** | your API key |
| **Ollama (local)** | nothing — runs on your Mac |

They all do the job; pick whichever you already have an account with. Voooxly
has no stake in which one you use and never sends anything anywhere except the
provider you chose. When you connect a cloud provider, Voooxly lets you **pick
the exact model** from a short curated list — the recommended default first,
a lighter one if you want speed, a bigger one if you want the best writing.

Two things worth knowing. **Groq is the only free one**, which is why it's
first in the list and why the setup above uses it. And **Ollama is the only
one where no text leaves your Mac at all** — with a local model Voooxly is
end-to-end offline. Install [Ollama](https://ollama.com), pull a model, and
Voooxly asks your own server which models you have and lets you choose.

Other OpenAI-compatible providers (OpenRouter, DeepSeek, Mistral, Together AI,
xAI, …) can be wired up by hand — see
[For developers → Configuration](#configuration).

**Connect nothing and Voooxly still works.** It pastes the raw transcription,
which Whisper already punctuates well. You just do the cleanup yourself.

## What it does

- **On-device STT** with `whisper.cpp` (native binary, Metal on Apple Silicon, no torch).
  Whisper large-v3-turbo: ~99 languages, strongest in English and Spanish.
- **Silence endpointing** (VAD): stop talking and it finishes on its own.
- **Long dictations**: up to five minutes in one go, with the transcription
  timeout scaled to the length of what you actually recorded.
- **Modes**: the same speech comes out as clean prose, a ready-to-send reply,
  a structured AI prompt, Markdown notes, a code spec, a summary or a translation.
- **Bring your own AI (or none)**: Groq, Claude, OpenAI, Gemini or a local
  Ollama model — one click in the menu, key stored in the Keychain. See
  [Then connect an AI](#then-connect-an-ai-this-is-the-part-that-matters).
- **Your dictation key, not ours**: any of the six bottom-row modifiers, and
  hold-to-talk or press-to-toggle. Every other shortcut is remappable too.
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
| **Command** | Say what you want written ("email Ana that the demo moved to Friday") — get the finished draft |
| **Verbatim** | Exactly what you said — no LLM, no rewriting |

Switch modes from the menu bar or with Ctrl+Shift+M. To make every mode follow
your personal style, add free-text rules in `config.yaml > llm.custom_rules`
("Never use semicolons", "Always spell our product name in caps", …). Building
from source? You can
define whole new modes in `src/voooxly/modes.py`.

## Privacy

**Your voice never leaves your Mac.** Audio is recorded, transcribed by
`whisper-server` running locally, and discarded. There is no upload step, and
that is true no matter which AI you connect.

What varies is the *text*:

| Setup | What leaves your Mac |
|---|---|
| No AI connected | Nothing |
| **Ollama** (local model) | Nothing |
| Groq / Claude / OpenAI / Gemini | The transcribed text only — never audio |

No account, no telemetry, no analytics. Your history and stats are plain files
in `~/.voooxly/`, and your API key lives in the macOS Keychain.

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
- **Accessibility** — global hotkey + simulated Cmd+V paste (no osascript involved).
- **Microphone** — recording.
- **Automation** — pausing Spotify/Music while you dictate, resuming it after (one-time prompt per player you use).

If pasting doesn't work, it's almost always Accessibility not granted. Automation only
affects the music auto-pause — without it, dictation still works, your player just
keeps playing over you.

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

Everything lives in `config.yaml`, with `.env` overrides (see `.env.example`).

| Key | Default | What it does |
|---|---|---|
| `audio.max_duration` | `300` | Hard stop for one dictation, in seconds |
| `stt.transcribe_timeout_floor` | `30` | Lower bound for the `/inference` timeout |
| `stt.transcribe_timeout_ceiling` | `180` | Upper bound; the real timeout scales with audio length |
| `hotkeys.toggle` | `[cmd_r]` | Dictation key. Settings → Shortcuts… writes `prefs.json`, which wins over this |
| `hotkeys.cancel` · `latch` · `cycle_mode` | | The other three shortcuts |
| `llm.custom_rules` | — | Free-text style rules appended to every mode |
| `app.language` | `null` | Output language; `null` keeps whatever you spoke |

### Choosing a model

**Voooxly has no favourite model and doesn't ship one.** `llm.ollama.model`
starts empty on purpose: a baked-in default would presume which model you
happen to have, and a cloud-only one would quietly fail for anyone without
that subscription while still reporting "connected". You choose, and you can
change your mind whenever.

**The free route is Groq.** A free API key, no card, and it handles dictation
cleanup perfectly well — it's first in the **AI engine** menu for that reason.
If you don't already pay for an AI, this is the one to take.

Beyond that, you have as many models as your provider offers:

- **Any provider in the menu** — Groq, Claude, OpenAI or Gemini. Paste a key
  and it starts working immediately. To use a different model from that same
  provider, edit `config.yaml`: Claude reads `llm.claude.model`, and everything
  OpenAI-compatible (including Groq and Gemini) reads `llm.openai.model`.
- **Ollama, running locally** — pull whatever model you like and Voooxly asks
  *your* server which ones you have, then lets you pick from that list. No key,
  and nothing leaves your Mac.
- **Ollama's cloud models** — same menu, same list. If you have an Ollama
  subscription, its cloud models show up alongside your local ones and work
  the same way.
- **Anything else that speaks the OpenAI protocol** — OpenRouter, DeepSeek,
  Mistral, Together AI, xAI and the rest have no menu entry, but they only
  need three lines:

```yaml
# config.yaml
llm:
  backend: openai          # the transport, not the vendor
  openai:
    base_url: "https://<provider>/v1"
    model: "<the model you want>"
    api_key_env: "MY_PROVIDER_KEY"
```

More providers and models will land in the menu over time. The list above is
what's wired today — the `openai` transport already reaches almost anything
else in the meantime.

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

Every module in `src/voooxly/`, and what owns what:

| Module | Owns |
|---|---|
| `app.py` | The rumps menu bar app — wiring, menu, threading. The biggest file. |
| `hotkey.py` | Global key listener, hold/toggle modes, the 300 ms guard window |
| `keys.py` | Dictation-key catalogue and validation (pure data, no AppKit) |
| `audio.py` | Recording, VAD silence detection, the duration cap |
| `stt.py` | `whisper-server` lifecycle and `/inference` calls |
| `refine.py` | LLM cleanup: dispatch per backend, fallbacks, token usage |
| `providers.py` | The five AI providers and their endpoints |
| `ai_settings.py` | Which provider/model the user picked (pure data) |
| `keychain.py` | API keys in and out of the macOS Keychain |
| `modes.py` | The eight dictation modes and their system prompts |
| `output.py` · `richtext.py` | Clipboard, ⌘V injection, Markdown → HTML |
| `overlay.py` | The floating HUD |
| `onboarding.py` | First-run window (AppKit, hand-laid out) |
| `history.py` · `stats.py` · `dictionary.py` | Persistence in `~/.voooxly/` |
| `setup_checks.py` · `updates.py` · `media.py` | Permissions, update check, music auto-pause |
| `config.py` | `config.yaml` + `.env` loading, dotted-path lookup |

Tests live in `tests/`, one file per concern. Most are pure logic; the
exception is `test_onboarding.py`, which builds real AppKit views and so needs
a macOS graphical session (it skips itself over SSH without one).

`vendor/whisper/` is **not** in git: it holds whisper.cpp binaries vendored from
Homebrew, and `scripts/bundle-whisper.sh` rebuilds it automatically before any
build that needs it.

### Roadmap

Next up (1.2):

- Edit Mode: select any text, speak an instruction, get it transformed.
- Per-app modes and optional on-screen context for smarter cleanup.
- **Better update checks.** Today the appcast is only read once, during
  `_warmup` at launch — leave Voooxly running for a month and you will never
  hear about a new version. Needs a periodic re-check and a manual
  **Check for updates…** in the menu.

## License

MIT — see [LICENSE](LICENSE). Third-party components bundled in the app are
listed in [THIRD-PARTY.md](THIRD-PARTY.md).
