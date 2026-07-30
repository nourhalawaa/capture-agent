# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- **Python 3.12.3**, venv at `.venv/`
- **ffmpeg 8.1.1** installed via winget — must be on PATH (requires a fresh shell after install). Needed by `faster-whisper` for audio demuxing.
- **Tesseract 5.5.0** installed via UB Mannheim installer at `C:\Program Files\Tesseract-OCR\`. Language packs: `eng`, `ara`. Path set explicitly via `config.TESSERACT_CMD` — do not rely on PATH.
- **gallery-dl 1.32.1** installed in venv. Reads Instagram/Facebook cookies from a Firefox profile (burner account). Firefox must be **closed** during any run that hits IG/FB.
- Activate venv: `.\.venv\Scripts\Activate.ps1` (PowerShell); use `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once if blocked.
- `.env` must be configured before running — see `.env.example`. Required keys: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `RAW_FOLDER`, `GALLERY_DL_COOKIES`. Optional: `INBOX_FILE` (defaults to `<RAW_FOLDER parent>/system/inbox.md`), `SKIPPED_FILE` (defaults to `<…>/system/skipped.md`).

## Deployment (Linux home server, 24/7)

The production target is a headless Linux server via Docker Compose — see **`DEPLOY.md`** for the full runbook. In that mode: `docker-compose.yml` bind-mounts the Syncthing-synced vault root at `/vault` (so `RAW_FOLDER=/vault/raw`, inbox/skipped/wiki all land in the synced vault) and runs as the host uid (`PUID`/`PGID`) so files aren't root-owned; cookies come from a static `secrets/cookies.txt` (`GALLERY_DL_COOKIES_FILE`) instead of a Firefox profile, so there's **no Firefox-closed requirement** on Linux. `restart: unless-stopped` gives 24/7 auto-restart. Only one instance may poll the bot token at a time (Telegram 409 otherwise) — don't run the laptop `run_bot.bat` and the server together.

## Common commands

```powershell
# Install / sync deps
.\.venv\Scripts\pip.exe install -r requirements.txt

# Run full pipeline for one URL (CLI) — auto-routes by content type
python capture.py "<url>"

# Start the Telegram bot (blocking, Ctrl+C to stop)
# WARNING: only one process may poll the token. The server is live — don't run this.
python bot.py

# Execution district, without starting a poller (this is how to test /do /done /now)
python execution.py render
python execution.py add "buy sunglasses"
python execution.py done 3
python execution.py done "landing page"

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

`capture(url)` auto-routes by content type. All stages raise `CaptureError(stage, original)` on failure; OCR is non-fatal (degrades gracefully). The bot never drops a failed capture: `bot.py` catches the error and calls `inbox.log_failed()` to record the URL + stage + error in `system/skipped.md` for manual review.

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

**`config.py`** — single source of truth for all constants. Calls `load_dotenv()` at import time. Keys: `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE`, `WHISPER_LANGUAGE`, `RAW_FOLDER`, `INBOX_FILE`, `SKIPPED_FILE`, `EXECUTION_FOLDER` + the five per-file execution keys (`COMMITMENTS_FILE`, `ACTIONS_FILE`, `EXEC_INBOX_FILE`, `DONE_FILE`, `NOW_FILE` — `DONE_FILE` is separate specifically so the temporary done-log can be relocated in one line), `GALLERY_DL_COOKIES`, `GALLERY_DL_COOKIES_FILE` (preferred on Linux/Docker), `TESSERACT_CMD`. Never hardcode paths or credentials.

**`execution.py`** — the hub's **execution district** (`execution/`), a separate pipeline from capture: capture optimises for never losing anything, execution optimises for *actively forgetting*. Backs the `/do`, `/done`, `/now` bot commands. Reads `commitments.md` (Nour-only, never written here) and `actions.md` (his; the ONLY mutation allowed is deleting one closed line — never a rewrite or an annotation); writes `inbox.md` (`/do` appends), `done.md` (append-only, **temporary home** — `DONE_FILE` moves when the planned tracking system lands), and `NOW.md` (fully generated, overwritten wholesale). Reuses `inbox.py`'s `now()` and `_one_line()` so timestamps and verbatim handling match the capture queue. Key points:
- `_content_lines()` strips HTML-comment regions **while preserving line indices** — the seed files carry worked examples inside `<!-- -->`, and parsing those would invent commitments Nour never wrote. Indices must survive because `close_action` deletes by line number.
- `ordered_open_actions()` is the single source of the `/done N` numbering: commitments-file order × actions-file order, recomputed every call, so there's no index state file to drift. Only actions under `active` commitments are numbered (that's exactly what NOW shows); paused and unassigned ones are closable by text instead.
- `close_action(int | str)` — ambiguous or unmatched text **mutates nothing** and reports candidates; guessing which of Nour's lines to delete is worse than doing nothing. Writes `actions.md` via `_write_atomic()` (temp + `os.replace`).
- `render_now()` — NOW shows open actions under active commitments **and nothing else**; everything hidden (paused, unassigned, unknown slug) is accounted for in OVERVIEW, so nothing silently vanishes. "Untouched" is derived from `done.md` dates, the district's only timestamped surface — a reported fact, never a decay term in a score. There is no scoring, ranking, or automatic classification anywhere in this module, by design.
- `for_telegram()` — drops the OVERVIEW table and emphasis markers. Replies are sent as **plain text**: MarkdownV2 needs every special char escaped and a parse failure means the message doesn't send at all.
- `__main__` CLI (`render` / `add` / `done` / `show`) is how this gets tested locally — **never run `python bot.py` on the laptop while the server is live** (one poller per token, else Telegram 409). The CLI reconfigures stdout to UTF-8 because Windows' legacy codepage can't encode `·`/`—`/`✅` and would crash *after* a successful mutation.

**`inbox.py`** — append-only writer for the hub's `system/inbox.md` queue. `log_video(note_stem, url, context)`, `log_file(file_name, context)`, `log_thought(text)`, and `log_failed(url, context, stage, error)` (appends to `system/skipped.md`, same format `batch_ingest.py` uses, so live-bot and batch failures share one review list). Items append under a `## YYYY-MM-DD` date heading (created with the day's first capture). One line per item: `- [YYYY-MM-DD HH:MM] KIND [[wikilink]] · [source](url) · "context" · #unsorted` (THOUGHT has no wikilink/source; empty segments omitted; internal newlines collapse to ` ⏎ `). VIDEO wikilinks use the note stem without `.md`; FILE wikilinks keep the extension. Never edits or deletes existing lines — sorting later flips `#unsorted` → `#sorted`.

**`pipeline/downloader.py`**
- `download(url)` — yt-dlp video download. Downloads to `temp/` as `%(id)s.%(ext)s`. Caps at 720p mp4. Applies Instagram/Facebook cookies via `_apply_ig_cookies()` (uses `GALLERY_DL_COOKIES` Firefox profile).
- `download_images(url)` — gallery-dl carousel download. **Anonymous-first, cookies only as fallback** (`_gallery_dl_into()` helper; mirrors `download()`): tries with no cookies, and only retries with `_cookie_args()` into a fresh dir if the anonymous attempt yields no images — sending cookies on every request is what got the burner account flagged as bot activity. Creates a unique `temp/carousel_<uuid8>/` per run. Reads per-slide `.json` metadata files; sorts slides by `num` field. Returns `image_paths`, `caption`, `creator`, `slide_count`.
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
- `format_photo_note(image_name, ocr_text, caption)` — for a photo sent straight to the bot. Embeds `![[assets/<image>]]` + `## Text (OCR)`. Title prefers the caption, else the first OCR line with real words, else `Photo`.

**`capture.py`**
- `_make_filename(meta)` — slug + id for all three types: video uses yt-dlp video ID stem, carousel uses post shortcode (extracted from URL), document uses 8-char URL SHA1 hash.
- `_capture_carousel()` — runs download → OCR (non-fatal, degrades to empty slides) → format → write, with `shutil.rmtree(image_dir)` in `finally`.
- All three `_capture_*` helpers use `_write_note()` (shared RAW_FOLDER write) and raise `CaptureError(stage, e)` per stage.
- `capture_photo(image_path, caption)` — OCRs a photo already saved in `raw/assets/` and writes a note (`raw/<image-stem>.md`) embedding the image + its OCR text. Called by `bot.py` for photo attachments; raises on failure so the bot falls back to a plain saved-file line.

**`bot.py`**
- Whitelist: every handler starts with `_authorized(update)` — only `TELEGRAM_ALLOWED_USER_ID` gets a response; everyone else is silently ignored. Bot refuses to start if the ID is unset.
- **Execution commands** `/do`, `/done`, `/now` (see `execution.py`). They cannot intercept links or plain thoughts: `handle_message` is registered with `filters.TEXT & ~filters.COMMAND`, so capture behaviour is unchanged by construction. `_command_text()` reads the text after the command token from `update.message.text` — **not** `context.args`, which splits on whitespace and would silently reflow a verbatim `/do` capture. A separate `execution_lock` (not `capture_lock`) means a `/done` never queues behind a 3-minute transcription.
- Text without a URL → `inbox.log_thought()` (verbatim THOUGHT line). Text with a URL → capture; on success `inbox.log_video()` with the non-URL remainder of the message as context. On any failure → `_save_failure()` → `inbox.log_failed()` (skipped.md) so the link is never lost; the thought and queue writes are also wrapped so a disk hiccup can't silently drop them.
- Attachments are saved to `RAW_FOLDER/assets/` first (largest photo rendition; sanitized document filename; collision-suffixed with `file_unique_id`) — so the binary is never lost — then: **photos** are OCR'd via `capture_photo()` into a raw note (falls back to a plain FILE line if OCR fails); **documents/PDFs** get a plain `inbox.log_file()` line (parsing big/scanned PDFs is slow/failure-prone, left on-demand).
- `capture_lock = asyncio.Lock()` enforces sequential processing.
- `loop.run_in_executor(None, capture, url)` keeps the event loop responsive.
- Status messages edited in-place (⏳ → ✅/❌).

**Model preference:** plan on Opus 4.8, code on Sonnet 4.6.
