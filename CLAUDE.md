# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- **Python 3.12.3**, venv at `.venv/`
- **ffmpeg 8.1.1** installed via winget — must be on PATH (requires a fresh shell after install). Needed by `faster-whisper` for audio demuxing.
- **Tesseract 5.5.0** installed via UB Mannheim installer at `C:\Program Files\Tesseract-OCR\`. Language packs: `eng`, `ara`. Path set explicitly via `config.TESSERACT_CMD` — do not rely on PATH.
- **gallery-dl 1.32.1** installed in venv. Reads Instagram/Facebook cookies from a Firefox profile (burner account). Firefox must be **closed** during any run that hits IG/FB.
- Activate venv: `.\.venv\Scripts\Activate.ps1` (PowerShell); use `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once if blocked.
- `.env` must be configured before running — see `.env.example`. Required keys: `TELEGRAM_BOT_TOKEN`, `RAW_FOLDER`, `GALLERY_DL_COOKIES`.

## Common commands

```powershell
# Install / sync deps
.\.venv\Scripts\pip.exe install -r requirements.txt

# Run full pipeline for one URL (CLI) — auto-routes by content type
python capture.py "<url>"

# Start the Telegram bot (blocking, Ctrl+C to stop)
python bot.py

# Test individual stages standalone
python pipeline\downloader.py "<video_url>"
python pipeline\downloader.py images "<instagram_post_url>"
python pipeline\transcriber.py "temp\<video_id>.mp4"
python pipeline\ocr.py "temp\carousel_<id>\"
python pipeline\document.py "<article_url>"

# Sanity-check all imports
python -c "import yt_dlp, faster_whisper, dotenv, telegram, gallery_dl, markitdown, pytesseract; print('ok')"
```

## Architecture

`capture(url)` auto-routes by content type. All stages raise `CaptureError(stage, original)` on failure; OCR is non-fatal (degrades gracefully).

```
URL
 └─► capture.py  _detect_platform()
       │
       ├─ youtube / tiktok ──────────────────────► _capture_video()
       │                                               │
       ├─ instagram / facebook                    download(url)        yt-dlp + cookies for IG/FB
       │    │                                         │
       │    ├─ is_video_post()=True ──────────►  transcribe(path)     faster-whisper
       │    │                                         │
       │    └─ is_video_post()=False ──────────► format_note()        Transcript + Caption
       │         │                                    │
       │    _capture_carousel()              wiki/raw/<slug>-<id>.md
       │         │
       │    download_images(url)   gallery-dl, Firefox cookies, temp/carousel_<id>/
       │         │
       │    ocr_images(paths)      Tesseract ara+eng --psm 6, one image at a time
       │         │
       │    format_carousel_note() Caption → ## Slides → ### Slide N
       │         │
       │    wiki/raw/<slug>-<shortcode>.md    temp/carousel_<id>/ deleted after write
       │
       └─ everything else ──────────────────────► _capture_document()
                                                      │
                                                 parse_document(url)  MarkItDown
                                                      │
                                                 format_note()        ## Content
                                                      │
                                                 wiki/raw/<slug>-<hash8>.md
```

**Entry points:**
- `capture.py` — CLI orchestrator. `capture(url) -> str` routes and runs the full pipeline, returns the `.md` path.
- `bot.py` — Telegram bot. Wraps `capture()` with async polling, one-at-a-time execution (`asyncio.Lock`), and ⏳/✅/❌ status messages.

## Key conventions

**`config.py`** — single source of truth for all constants. Calls `load_dotenv()` at import time. Keys: `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE`, `WHISPER_LANGUAGE`, `RAW_FOLDER`, `GALLERY_DL_COOKIES`, `TESSERACT_CMD`. Never hardcode paths or credentials.

**`pipeline/downloader.py`**
- `download(url)` — yt-dlp video download. Downloads to `temp/` as `%(id)s.%(ext)s`. Caps at 720p mp4. Applies Instagram/Facebook cookies via `_apply_ig_cookies()` (uses `GALLERY_DL_COOKIES` Firefox profile).
- `download_images(url)` — gallery-dl carousel download. Creates a unique `temp/carousel_<uuid8>/` per run. Reads per-slide `.json` metadata files; sorts slides by `num` field. Returns `image_paths`, `caption`, `creator`, `slide_count`.
- `is_video_post(url)` — reel-vs-carousel detector for IG/FB. `/reel/` in URL → True instantly. Otherwise runs a yt-dlp metadata probe (`download=False`): ≥1 entry → video, 0 entries or raises → carousel (gallery-dl handles it).
- `_detect_platform(url)` — hostname substring match; unknown → `"unknown"`.
- `_apply_ig_cookies(opts, url)` — injects `cookiesfrombrowser` tuple into yt-dlp opts only for IG/FB. YouTube/TikTok unaffected.

**`pipeline/transcriber.py`**
- Loads `WhisperModel` inside the function and explicitly `del`s it after the generator is consumed — keeps peak RAM bounded.
- Generator must be fully materialized into a list **before** `del model`; consuming it after causes a CTranslate2 fault.
- Passes `config.WHISPER_LANGUAGE` to `model.transcribe()` — `None` = auto-detect, ISO code (e.g. `"ar"`) = forced.

**`pipeline/ocr.py`**
- `ocr_images(image_paths)` — Tesseract OCR on an ordered list of image paths. Converts each to grayscale via PIL, runs `ara+eng --psm 6`. Per-slide `try/except` so one bad slide yields empty text without killing the batch. Returns `[{"slide": N, "text": "..."}]` in order.
- Sets `pytesseract.pytesseract.tesseract_cmd` from `config.TESSERACT_CMD` at import time — required because Tesseract is not reliably on PATH in non-interactive shells.
- `__main__`: takes a folder path, OCRs all `.jpg/.jpeg/.png/.webp` files in sorted order.

**`pipeline/document.py`**
- `parse_document(url)` — MarkItDown converts articles, PDFs, and web pages. Uses `result.markdown` and `result.title`. Returns `platform="document"` dict.

**`pipeline/formatter.py`**
- `format_note(meta, transcription=None)` — handles video and document. Documents: no Duration, `## Content`. Videos: Duration + `## Transcript` + `## Caption`.
- `format_carousel_note(meta, slides)` — carousel only. Header with `Slides:` count → `## Caption` → `## Slides` with `### Slide N` subsections. Empty slides render `_No text on this slide._`.

**`capture.py`**
- `_make_filename(meta)` — slug + id for all three types: video uses yt-dlp video ID stem, carousel uses post shortcode (extracted from URL), document uses 8-char URL SHA1 hash.
- `_capture_carousel()` — runs download → OCR (non-fatal, degrades to empty slides) → format → write, with `shutil.rmtree(image_dir)` in `finally`.
- All three `_capture_*` helpers use `_write_note()` (shared RAW_FOLDER write) and raise `CaptureError(stage, e)` per stage.

**`bot.py`**
- `capture_lock = asyncio.Lock()` enforces sequential processing.
- `loop.run_in_executor(None, capture, url)` keeps the event loop responsive.
- Status messages edited in-place (⏳ → ✅/❌).

**Model preference:** plan on Opus 4.8, code on Sonnet 4.6.
