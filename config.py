"""Shared configuration constants."""

import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# All inbox/log timestamps use this zone explicitly, independent of the host's
# system clock/TZ setting (the server runs UTC; Nour is in Cairo, EET, no DST).
TIMEZONE = os.getenv("TIMEZONE", "Africa/Cairo")

WHISPER_MODEL = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
# None = auto-detect the spoken language (current behavior).
# Set to an ISO code like "ar" or "en" to force a specific language.
WHISPER_LANGUAGE = None

RAW_FOLDER = os.getenv("RAW_FOLDER", r"C:\Users\DELL\Desktop\Wiki\raw")

# Hub inbox queue (system/inbox.md). Defaults to <vault>/system/inbox.md,
# where <vault> is RAW_FOLDER's parent. Override in .env if the layout differs.
INBOX_FILE = os.getenv("INBOX_FILE", str(Path(RAW_FOLDER).parent / "system" / "inbox.md"))

# Capture-failure log (system/skipped.md). Failed captures are appended here so a
# broken/failed link is never lost — it rides into manual review instead. Same file
# batch_ingest.py writes to, so live-bot and batch failures share one review list.
SKIPPED_FILE = os.getenv("SKIPPED_FILE", str(Path(INBOX_FILE).parent / "skipped.md"))

# Firefox profile path for gallery-dl (burner account cookies). Machine-specific — set in .env.
# Used on Windows dev. Ignored when GALLERY_DL_COOKIES_FILE is set.
GALLERY_DL_COOKIES = os.getenv("GALLERY_DL_COOKIES", "")

# Path to a Netscape cookies.txt file — used in Docker/Linux where no Firefox profile exists.
# Preferred over GALLERY_DL_COOKIES when both are set.
_COOKIES_FILE_RAW = os.getenv("GALLERY_DL_COOKIES_FILE", "")


def _writable_cookie_copy(path: str) -> str:
    """Return a writable path to the cookie jar, copying it out if need be.

    yt-dlp rewrites the jar after each request, so the file it's handed must be
    writable. In Docker the secret is bind-mounted read-only — which is correct, a
    secret shouldn't be mutated in place — and that made every cookie-fallback
    capture die with `[Errno 30] Read-only file system: '/secrets/cookies.txt'`.
    It silently cost 3 Instagram reels between 2026-07-23 and 07-26 before anyone
    read skipped.md closely enough to spot it. So: work on a copy.

    The copy is taken once at import, i.e. per container start. Replacing
    cookies.txt on the server therefore needs the usual
    `docker compose up -d --force-recreate` to take effect — same as before.
    """
    if not path:
        return path
    src = Path(path)
    if not src.is_file() or os.access(src, os.W_OK):
        return path
    dest = Path(tempfile.gettempdir()) / "capture-agent-cookies.txt"
    try:
        shutil.copyfile(src, dest)
        os.chmod(dest, 0o600)
        return str(dest)
    except OSError:
        # A read-only jar still beats no cookies at all — let the caller try.
        return path


GALLERY_DL_COOKIES_FILE = _writable_cookie_copy(_COOKIES_FILE_RAW)

# Tesseract binary — pytesseract can't reliably find it on PATH in non-interactive shells.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
