"""Shared configuration constants."""

import os
from dotenv import load_dotenv

load_dotenv()

WHISPER_MODEL = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
# None = auto-detect the spoken language (current behavior).
# Set to an ISO code like "ar" or "en" to force a specific language.
WHISPER_LANGUAGE = None

RAW_FOLDER = os.getenv("RAW_FOLDER", r"C:\Users\DELL\Desktop\Wiki\raw")

# Firefox profile path for gallery-dl (burner account cookies). Machine-specific — set in .env.
GALLERY_DL_COOKIES = os.getenv("GALLERY_DL_COOKIES", "")

# Tesseract binary — pytesseract can't reliably find it on PATH in non-interactive shells.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
