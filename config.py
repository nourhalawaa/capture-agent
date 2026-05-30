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
