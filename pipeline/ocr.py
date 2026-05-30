from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
import pytesseract

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

if config.TESSERACT_CMD and Path(config.TESSERACT_CMD).exists():
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

OCR_LANG = "ara+eng"
OCR_CONFIG = "--psm 6"


def ocr_images(image_paths: list[str]) -> list[dict]:
    results = []
    for i, path in enumerate(image_paths, start=1):
        try:
            with Image.open(path) as im:
                text = pytesseract.image_to_string(
                    im.convert("L"), lang=OCR_LANG, config=OCR_CONFIG
                ).strip()
        except Exception as e:
            print(f"[ocr_images] slide {i} failed: {e}", file=sys.stderr)
            text = ""
        results.append({"slide": i, "text": text})
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python pipeline/ocr.py <folder_of_images>", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(sys.argv[1])
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    paths = sorted(str(p) for p in folder.iterdir() if p.suffix.lower() in exts)
    for slide in ocr_images(paths):
        print(f"===== Slide {slide['slide']} =====")
        print(slide["text"] or "(no text)")
        print()
