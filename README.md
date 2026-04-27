# audio-to-mermaid

A live system-design interview assistant. It listens to mic + system audio, transcribes the conversation, asks Claude to maintain a Mermaid system-design diagram from the rolling transcript, and renders it in a browser viewer with pan/zoom and a side panel of `%%`-annotations (functional/non-functional requirements, API routes, data model, SLOs, trade-offs, etc.).

The Claude system prompt targets a Staff-Engineer-at-Meta quality bar — async patterns, message queues, idempotency, ACID/saga choices, read-write split, security defaults, observability/SLOs, and edge cases.

## How it works

```
mic + system audio (BlackHole)
        ↓ VAD-segmented chunks
faster-whisper (local, base.en)
        ↓ rolling transcript
Claude Sonnet (anthropic SDK)
        ↓ Mermaid source
mermaid.ink (HTTP, pako-encoded)
        ↓ SVG
local HTTP server → Brave viewer tab (pan/zoom, click-to-zoom-on-node, side-panel annotations)
```

Diagram triggers:
- **First diagram** auto-draws once ~400 chars of transcript have accumulated.
- **Subsequent redraws** require `Ctrl+Shift+M`. (Lets you decide when to refresh.)

## Requirements

- macOS (BlackHole is mac-only; the rest is portable)
- Python 3.10+
- [Brave Browser](https://brave.com) — used as the dedicated viewer host
- An [Anthropic API key](https://console.anthropic.com)
- Internet (for the Whisper model download on first run + mermaid.ink rendering)

## Setup

### 1. Install BlackHole for system-audio capture

```bash
brew install blackhole-2ch
# Reboot after install (BlackHole is a kernel extension)
```

### 2. Create a Multi-Output Device so you can hear *and* capture system audio

1. Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup").
2. Click **+** at the bottom-left → **Create Multi-Output Device**.
3. Check **both** your speakers/headphones **and** `BlackHole 2ch`. Drag your speakers to the top of the list so the OS prefers them as the master clock.
4. **System Settings → Sound → Output** → select the Multi-Output Device. (Option-click the volume icon in the menu bar to switch quickly.)

### 3. Clone, venv, install

```bash
git clone https://github.com/emanco/mermaid.git
cd mermaid
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. Configure

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

Optional env knobs (all have sensible defaults):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Claude API key |
| `WHISPER_MODEL` | `base.en` | faster-whisper model. `small.en` is more accurate, slower. |
| `DEBOUNCE_SECONDS` | `8` | Wait this long after the last new transcript line before generating. |
| `MAX_CONTEXT_TOKENS` | `6000` | Rolling transcript window sent to Claude. |
| `MIN_CONTEXT_CHARS_FOR_AUTO_DRAW` | `400` | Threshold for the auto first-draw. |
| `RENDER_BACKEND` | `mermaid_ink` | `mermaid_ink` or `kroki`. |
| `RENDER_URL` | `https://mermaid.ink/svg` | Override for self-hosted renderer. |
| `VIEWER_DIR` | `~/.cache/audio-to-mermaid` | Where the viewer HTML / SVG / annotations live. |
| `VIEWER_PORT` | `8765` | Local HTTP server port for the viewer. |

The mic + BlackHole device names are matched substring-wise in `src/utils/config.py` (`mic_device_name`, `blackhole_device_name`) — edit those if your mic isn't a Jabra.

## Run

Double-click `AudioToMermaid.command`, **or**:

```bash
source .venv/bin/activate
python -m src
```

On startup the app:
1. Prints detected audio devices.
2. Loads the Whisper model.
3. Opens `http://127.0.0.1:8765/viewer.html` in Brave.
4. Starts listening.

Speak ~3 sentences (or until ~400 chars of transcript accumulate) and the first diagram will auto-render in the viewer. After that, press **Ctrl+Shift+M** to redraw.

## Viewer controls

| Action | Shortcut |
|---|---|
| Zoom | scroll |
| Pan | drag |
| Zoom into a node | click the node |
| Fit to content | `F` (or click empty diagram area) |
| Reset to identity | `R` |
| Toggle annotations panel | `H` |
| Force diagram redraw | `Ctrl+Shift+M` |
| Quit (saves transcript + last diagram) | `Ctrl+C` in the terminal |

Saved transcripts and the final diagram land in `transcripts/` (gitignored).

## Tuning diagram quality

- The system prompt is in `src/llm/prompts.py`. It encodes the "Staff Engineer at Meta" quality bar — edit there to nudge style.
- Common LLM Mermaid syntax mistakes are auto-fixed by the regex table in `src/llm/diagram_generator.py` (`_MERMAID_FIXUPS`). If you see a new class of parse error in the viewer's error SVG, add an entry there rather than just adding more prompt text — prompts don't reliably stop regressions on the same pattern.

## Troubleshooting

- **"Waiting for first diagram…" forever** — speak more, or lower `MIN_CONTEXT_CHARS_FOR_AUTO_DRAW`. Auto-draw needs ~400 chars of transcript by default.
- **Render returns 414 / huge URLs** — the `mermaid_ink` backend already uses pako-encoded URLs (`pako:` prefix); if you see this you're probably on an old build. Pull latest.
- **`mermaid.ink` returns 504 / down** — switch backends: `RENDER_BACKEND=kroki` and `RENDER_URL=https://kroki.io`. (Or self-host either: `docker run -p 8000:8000 yuzutech/kroki`.)
- **Viewer shows an old diagram on launch** — shouldn't happen anymore (stale SVG is cleared on startup). If it does, `rm ~/.cache/audio-to-mermaid/diagram.svg`.
- **No system audio captured** — confirm the Multi-Output Device is set as system output and that BlackHole is in it. The app logs detected devices on startup.

## Architecture

```
src/
├── audio/         capture (sounddevice) + VAD segmentation
├── transcription/ faster-whisper engine
├── llm/           context manager + Claude prompt + post-processor
├── render/        Kroki/mermaid.ink HTTP client + local viewer HTTP server
├── shortcuts/     pynput global hotkey (Ctrl+Shift+M)
├── utils/         config, logger, shared state
└── main.py        async event loop wiring it all together
```
