# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- **Python 3.12.3**, venv at `.venv/`
- **ffmpeg 8.1.1** installed via winget — must be on PATH (requires a fresh shell after install). Needed by `faster-whisper` for audio demuxing.
- Activate venv: `.\.venv\Scripts\Activate.ps1` (PowerShell); use `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once if blocked.
- `TELEGRAM_BOT_TOKEN` must be set in `.env` before running `bot.py`.

## Common commands

```powershell
# Install / sync deps
.\.venv\Scripts\pip.exe install -r requirements.txt

# Run full pipeline for one URL (CLI)
python capture.py "<url>"

# Start the Telegram bot (blocking, Ctrl+C to stop)
python bot.py

# Test individual stages standalone
python pipeline\downloader.py "<url>"
python pipeline\transcriber.py "temp\<video_id>.mp4"

# Sanity-check all imports
python -c "import yt_dlp, faster_whisper, dotenv, telegram; print('ok')"
```

## Architecture

A **linear media-processing pipeline** triggered by a URL. All stages are complete and wired together.

```
URL
 └─► pipeline/downloader.py    download(url)              → {video_path, title, creator, duration, caption, url, platform}
 └─► pipeline/transcriber.py   transcribe(video_path)     → {transcript, language, segments}
 └─► pipeline/formatter.py     format_note(meta, trans)   → markdown string
 └─► config.RAW_FOLDER/<slug>-<id>.md                     (final output, Wiki/raw/)
```

**Entry points:**
- `capture.py` — CLI orchestrator. `capture(url) -> str` runs the full pipeline and returns the `.md` path. Also raises `CaptureError(stage, original)` on failure so callers know which stage failed.
- `bot.py` — Telegram bot. Wraps `capture()` with async polling, one-at-a-time execution (asyncio.Lock), and ⏳/✅/❌ status messages.

## Key conventions

**`config.py`** — single source of truth for constants: `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE`, and `RAW_FOLDER` (set to the absolute path of your Wiki `raw/` folder).

**`pipeline/downloader.py`**
- Downloads to `temp/` (project root, gitignored) using `%(id)s.%(ext)s` as filename — avoids unicode issues.
- Platform detected via URL hostname substring match; unknown domains → `"unknown"`.
- All metadata fields default gracefully (`""` / `0`) — never `None`.
- `requested_downloads[0]["filepath"]` is the authoritative post-merge path; `prepare_filename()` is the fallback.
- Format selector caps at 720p mp4; `merge_output_format: "mp4"` handles DASH streams (requires ffmpeg).

**`pipeline/transcriber.py`**
- Loads `WhisperModel` inside the function and explicitly `del`s it after the generator is consumed — keeps peak RAM bounded (~1GB headroom on this machine).
- Generator must be fully materialized into a list **before** `del model`; consuming it after causes a CTranslate2 fault.
- Adds project root to `sys.path` so `import config` works when run standalone.

**`pipeline/formatter.py`**
- Pure function — no I/O. Omits the `Creator` line entirely when `meta["creator"]` is empty. Duration formatted as `m:ss`. Caption defaults to `_No caption._`.

**`capture.py`**
- Filename: `_slugify(title)-{video_id}.md`. Slugify strips Windows-illegal chars, collapses whitespace+symbols to single dashes, lowercases, truncates to 80 chars.
- `try/finally` guarantees `temp/<id>.mp4` is deleted whether the pipeline succeeds or fails.
- Raises `CaptureError(stage, original)` (defined in this file) on any pipeline failure.

**`bot.py`**
- `capture_lock = asyncio.Lock()` enforces sequential processing — never two captures concurrently.
- `loop.run_in_executor(None, capture, url)` runs the blocking pipeline in a thread so the bot event loop stays responsive.
- Queued links show "⏳ Queued…" immediately, then flip to "⏳ Processing…" once the lock is acquired.
- Status messages are edited in-place (⏳ → ✅/❌) rather than sending new messages.

**Model preference:** plan on Opus 4.7, code on Sonnet 4.6.
