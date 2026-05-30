# SHELVED — not wired into the active pipeline.
# OCR on video frames produces too much noise for talking-head / dynamic content.
# Intended for a future image-post / carousel flow where frames are static text.
from __future__ import annotations

import difflib
import sys
from pathlib import Path

import cv2
import pytesseract

SAMPLE_INTERVAL_SEC = 1.5
DEDUP_THRESHOLD = 0.9
OCR_LANG = "ara+eng"


def extract_frames_text(video_path: str) -> str:
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps:  # guard NaN / 0
            fps = 30.0
        frame_interval = max(1, round(fps * SAMPLE_INTERVAL_SEC))

        unique: list[str] = []
        last_kept = ""
        frame_index = 0

        while True:
            grabbed = cap.grab()
            if not grabbed:
                break

            if frame_index % frame_interval == 0:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    text = pytesseract.image_to_string(gray, lang=OCR_LANG, config="--psm 6").strip()
                    if text:
                        ratio = difflib.SequenceMatcher(None, last_kept, text).ratio()
                        if ratio < DEDUP_THRESHOLD:
                            unique.append(text)
                            last_kept = text

            frame_index += 1
    finally:
        cap.release()

    return "\n".join(unique).strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python pipeline/ocr.py <video_path>", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    result = extract_frames_text(sys.argv[1])
    if result:
        print(result)
    else:
        print("(no on-screen text found)")
