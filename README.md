# Capture Agent

Send a video link to Telegram. Get a structured markdown note in your wiki.

## Background

This project is built as an extension to [Andrej Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — a pattern where an LLM maintains a persistent, compounding knowledge wiki from raw sources. The idea is that you keep feeding raw material into a `raw/` folder and let the LLM process, link, and build on it over time.

Capture Agent solves the friction problem of getting video content into that wiki. Reels, YouTube videos, TikToks — the kind of content that's easy to consume and hard to retain. Instead of manually transcribing or copy-pasting, you send a link and the pipeline handles extraction, transcription, and formatting automatically. The output drops directly into `raw/`, ready for the LLM to ingest.

## What it does

Zero-friction media capture pipeline. You send a YouTube, TikTok, or Instagram link to a Telegram bot — it downloads the video, transcribes the audio with Whisper, formats everything into a clean markdown note, and drops it directly into your wiki's `raw/` folder. No browser extensions, no manual copy-paste, no open tabs to deal with later.

Built for personal knowledge management: the output is a ready-to-link `.md` file with title, creator, platform, duration, caption, and full transcript.

## How it works

```
Telegram message
     │
     ▼
  yt-dlp          download video (YouTube / TikTok / Instagram, ≤720p)
     │
     ▼
faster-whisper    transcribe audio → text + language detection
     │
     ▼
  formatter       assemble structured markdown note
     │
     ▼
  wiki/raw/       <slug>-<id>.md written to disk
```

One URL in. One `.md` file out. The bot processes links sequentially (one at a time) and edits the status message in-place: ⏳ Queued → ⏳ Processing → ✅ Done / ❌ Failed.

## Stack

- **Python 3.12**
- **yt-dlp** — download + metadata extraction
- **faster-whisper** — CTranslate2-backed Whisper inference (small model, CPU, int8)
- **python-telegram-bot** — async bot with polling
- **ffmpeg** — audio demux for DASH streams
- **python-dotenv** — local config

## Setup

```powershell
# 1. Clone and create venv
git clone https://github.com/nourhalawa/capture-agent.git
cd capture-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install ffmpeg (Windows)
winget install ffmpeg
# Then open a fresh shell so ffmpeg is on PATH

# 4. Configure .env
cp .env.example .env   # or create .env manually
```

`.env` needs two values:

```env
TELEGRAM_BOT_TOKEN=your_token_here
RAW_FOLDER=C:\path\to\your\wiki\raw
```

Get a bot token from [@BotFather](https://t.me/BotFather). `RAW_FOLDER` is wherever you want the markdown files to land.

```powershell
# 5. Run
python bot.py
```

## Usage

Send any YouTube, TikTok, or Instagram URL to the bot. That's it.

The bot replies with a status message and edits it as the pipeline progresses. The finished `.md` file appears in `RAW_FOLDER` named `<title-slug>-<video-id>.md`.

To run the pipeline without the bot:

```powershell
python capture.py "https://youtube.com/watch?v=..."
```

## Project status & roadmap

**v1 — complete and working.**

- [x] Download + transcribe + format pipeline
- [x] Telegram bot with queuing and in-place status updates
- [x] Multi-platform support (YouTube, TikTok, Instagram)
- [x] Config via `.env`, secrets out of version control

**Planned:**

- [ ] **v2:** OCR on video frames for slide/text-heavy content


## Author

**Nour Halawa** — AI/ML engineer, Cairo.
[github.com/nourhalawa](https://github.com/nourhalawa)
