"""Shared configuration constants."""

import os
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
GALLERY_DL_COOKIES_FILE = os.getenv("GALLERY_DL_COOKIES_FILE", "")

# Tesseract binary — pytesseract can't reliably find it on PATH in non-interactive shells.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
