# Capture Agent

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![faster-whisper](https://img.shields.io/badge/faster--whisper-CTranslate2-brightgreen)
![yt-dlp](https://img.shields.io/badge/yt--dlp-latest-red)
![gallery-dl](https://img.shields.io/badge/gallery--dl-latest-orange)
![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

Send any link to Telegram. Get a structured markdown note in your wiki. No browser tabs, no manual transcription, no copy-paste.

## Background

This project is built as an extension to [Andrej Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — a pattern where an LLM maintains a persistent, compounding knowledge wiki from raw sources. The idea is that you keep feeding raw material into a `raw/` folder and let the LLM process, link, and build on it over time.

Capture Agent solves the friction problem of getting content into that wiki. Videos, carousels, articles, PDFs — the kind of content that's easy to consume and hard to retain. Instead of manually transcribing or copy-pasting, you send a link and the pipeline handles extraction, transcription, and formatting automatically. The output drops directly into `raw/`, ready for the LLM to ingest.

## What it does

Zero-friction media capture pipeline. Send any link to a Telegram bot — it figures out what it is and routes it automatically:

- **YouTube / TikTok** — downloads the video, transcribes audio with Whisper, formats a note with title, creator, duration, transcript, and caption
- **Instagram / Facebook reels** — same video pipeline; tries anonymously first, falls back to burner-account cookies only when needed
- **Instagram / Facebook carousels / image posts** — downloads all slides with gallery-dl (anonymous-first), OCRs each slide with Tesseract (Arabic + English), formats a per-slide note with caption
- **Articles, PDFs, web pages** — converts to markdown via MarkItDown, formats a document note
- **Plain text** — any message without a link becomes a timestamped THOUGHT in the inbox
- **Photos / documents** — saved to `raw/assets/`; photos are additionally OCR'd (ara+eng) into a note, documents/PDFs saved as-is

One URL in. One `.md` file out. The bot processes links sequentially and edits the status message in-place: ⏳ Queued → ⏳ Processing → ✅ Done / ❌ Failed. **A failed capture is never dropped** — the link is appended to `system/skipped.md` for manual review.

### Execution commands

The same bot also drives the hub's `execution/` district — a separate pipeline, because
capture optimises for never losing anything while execution optimises for *actively
forgetting*. Three commands, no scoring and no ranking:

| Command | What it does |
|---|---|
| `/do <text>` | logs it verbatim to `execution/inbox.md`. No prompts, no classification at capture time. |
| `/now` | replies with the open list, grouped under your active commitments |
| `/done <n\|text>` | closes it by NOW number or text match → `execution/done.md` |

`commitments.md` (3–5 season-long things) and `actions.md` are hand-written; `NOW.md` is
generated and overwritten on every command. There's no scheduler — the render is a side
effect of each mutation. Local testing without a Telegram poller: `python execution.py
render | add "<text>" | done <n|text>`.

## How it works

```
Telegram message
     │
     ▼
  capture(url)   ── detect type ──►  YouTube / TikTok
                                          │
                                     yt-dlp download
                                          │
                                    faster-whisper
                                          │
                                      formatter
                                          │
                          ┌──────────────┤
                          │              │
                 Instagram / Facebook    │
                          │              │
                  reel? ──┤              │
                    yes   │   no         │
                          ▼             ▼
                    video pipeline   gallery-dl (all slides)
                                          │
                                    Tesseract OCR
                                    (ara+eng, per slide)
                                          │
                                      formatter
                                          │
                          ┌──────────────┘
                          │
               Article / PDF / website
                          │
                      MarkItDown
                          │
                       formatter
                          │
                          ▼
                    wiki/raw/<slug>-<id>.md
```

## Stack

- **Python 3.12**
- **yt-dlp** — video download + metadata (YouTube, TikTok, Instagram reels, Facebook reels)
- **gallery-dl** — image/carousel download (Instagram, Facebook image posts)
- **faster-whisper** — CTranslate2-backed Whisper inference (small model, CPU, int8)
- **Tesseract OCR** — on-slide text extraction (ara+eng)
- **MarkItDown** — article/PDF/webpage → markdown conversion
- **python-telegram-bot** — async bot with polling
- **ffmpeg** — audio demux for DASH streams
- **python-dotenv** — local config

## Setup

```powershell
# 1. Clone and create venv
git clone https://github.com/nourhalawaa/capture-agent.git
cd capture-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install ffmpeg (Windows)
winget install ffmpeg
# Then open a fresh shell so ffmpeg is on PATH

# 4. Install Tesseract OCR with Arabic language pack
# Download from: https://github.com/UB-Mannheim/tesseract/wiki
# During install: check "Additional language data → Arabic (ara)"
# Default install path: C:\Program Files\Tesseract-OCR\

# 5. Configure .env
cp .env.example .env
```

`.env` required values:

```env
TELEGRAM_BOT_TOKEN=your_token_here
RAW_FOLDER=C:\path\to\your\wiki\raw

# Firefox profile path for gallery-dl (burner Instagram account)
GALLERY_DL_COOKIES=C:\path\to\Firefox\Profiles\xxxxxxxx.Profile 1
```

`GALLERY_DL_COOKIES` is the path to a Firefox profile that is logged into a burner Instagram account. Used for carousel downloads and Instagram reel authentication. See gallery-dl docs for setup.

```powershell
# 6. Run
python bot.py
```

### Run 24/7 on a Linux server (Docker)

For always-on capture, deploy to a home server with Docker Compose — the bot writes into a Syncthing-synced copy of the vault so captures reach every device. Full runbook in **[DEPLOY.md](DEPLOY.md)**; the short version:

```bash
docker compose up -d --build
```

## Usage

Send any YouTube, TikTok, Instagram, or Facebook URL — or any article/PDF link — to the bot. That's it.

The bot replies with a status message and edits it as the pipeline progresses. The finished `.md` file appears in `RAW_FOLDER`.

To run the pipeline without the bot:

```powershell
python capture.py "https://..."
```

## Output formats

**Video note** (YouTube, TikTok, reels):
```markdown
# Title

- Source / Platform / Creator / Duration / Captured / Status

## Transcript
...

## Caption
...
```

**Carousel note** (Instagram/Facebook image posts):
```markdown
# instagram post by creator

- Source / Platform / Creator / Slides / Captured / Status

## Caption
...

## Slides

### Slide 1
[OCR text]

### Slide 2
...
```

**Document note** (articles, PDFs, websites):
```markdown
# Page title

- Source / Platform / Captured / Status

## Content
[MarkItDown markdown]
```

## Project status

**v3 — complete and working.**

- [x] Video pipeline: YouTube, TikTok, Instagram/Facebook reels
- [x] Carousel pipeline: Instagram/Facebook image posts, all slides OCR'd (ara+eng)
- [x] Document pipeline: articles, PDFs, web pages via MarkItDown
- [x] Automatic routing — one `capture(url)` call handles all types
- [x] Telegram bot with queuing and in-place status updates
- [x] Configurable Whisper language (auto-detect or forced ISO code)
- [x] Thoughts (plain text) and photo attachments (saved + OCR'd)
- [x] Failed captures saved to `skipped.md` — never dropped
- [x] Anonymous-first for IG/FB (cookies only as fallback)
- [x] 24/7 Docker deployment for a Linux home server ([DEPLOY.md](DEPLOY.md))

### Known limitations

- Instagram `/p/` posts and some Facebook `/share/` posts can still fail to download (upstream gallery-dl extractor issues) — these are saved to `skipped.md` for manual capture rather than lost.
- Documents/PDFs sent as attachments are saved but not parsed (send them as a link to extract text).

## Author

**Nour Halawa** — AI/ML engineer, Cairo.
[github.com/nourhalawa](https://github.com/nourhalawa)

## License

MIT — see [LICENSE](LICENSE).

---

`python` · `whisper` · `yt-dlp` · `gallery-dl` · `tesseract` · `markitdown` · `telegram-bot` · `knowledge-management` · `transcription` · `ocr` · `personal-wiki` · `ai-pipeline`
