from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

import config
from pipeline.downloader import download, download_images, is_video_post, _detect_platform
from pipeline.transcriber import NoAudioError, transcribe
from pipeline.formatter import format_note, format_carousel_note, format_photo_note
from pipeline.document import parse_document
from pipeline.ocr import ocr_images

_IG_POST_RE = re.compile(r"/(?:p|reel|reels|tv)/([^/?#]+)")

SOCIAL_VIDEO_PLATFORMS = {"youtube", "tiktok"}
SOCIAL_IMAGE_PLATFORMS = {"instagram", "facebook"}

# Carousel slides that are videos, not images — gallery-dl returns both.
VIDEO_SLIDE_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
VIDEO_SLIDE_LIMIT = 5


class CaptureError(Exception):
    def __init__(self, stage: str, original: BaseException):
        super().__init__(f"{stage}: {original}")
        self.stage = stage
        self.original = original


def _slugify(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    # Filesystem-illegal chars, plus Obsidian wikilink-special chars ([[name#heading|alias^block]])
    # that are filesystem-legal but break `[[name]]` parsing if left in a filename.
    illegal = set('<>:"/\\|?*#^[]')
    cleaned = "".join(c for c in text if c not in illegal and ord(c) >= 0x20)
    cleaned = "-".join(cleaned.split())
    cleaned = cleaned.lower()
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:max_len].strip("-.")


def _extract_post_id(url: str) -> str:
    m = _IG_POST_RE.search(url)
    return m.group(1) if m else hashlib.sha1(url.encode()).hexdigest()[:8]


def _make_filename(meta: dict) -> str:
    slug = _slugify(meta.get("title", ""))
    if meta.get("platform") == "document":
        post_id = hashlib.sha1(meta["url"].encode()).hexdigest()[:8]
    elif "image_paths" in meta:
        post_id = _extract_post_id(meta.get("url", ""))
    else:
        post_id = Path(meta["video_path"]).stem
    return f"{slug}-{post_id}.md" if slug else f"{post_id}.md"


def _write_note(meta: dict, markdown: str) -> str:
    raw_dir = Path(config.RAW_FOLDER)
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / _make_filename(meta)
    output_path.write_text(markdown, encoding="utf-8")
    return str(output_path)


def _capture_video(url: str) -> str:
    video_path: Path | None = None
    try:
        try:
            meta = download(url)
        except Exception as e:
            print(f"[capture] download stage failed: {e}", file=sys.stderr)
            raise CaptureError("download", e) from e
        video_path = Path(meta["video_path"])

        try:
            transcription = transcribe(meta["video_path"])
        except NoAudioError:
            transcription = {"transcript": "", "language": "", "segments": [],
                             "error": "this video has no audio track"}
        except Exception as e:
            # Non-fatal on purpose. A failed transcript must not throw away a
            # download that worked — the note still carries title, creator,
            # caption and URL, which is enough to sort from and to rewatch.
            # Discarding the whole capture instead lost two items outright
            # (2026-08-21 `tuple index out of range`, 2026-09-04 `.NA` path).
            print(f"[capture] transcription stage failed (non-fatal): {e}", file=sys.stderr)
            transcription = {"transcript": "", "language": "", "segments": [], "error": str(e)}

        try:
            markdown = format_note(meta, transcription)
        except Exception as e:
            print(f"[capture] formatting stage failed: {e}", file=sys.stderr)
            raise CaptureError("formatting", e) from e

        try:
            return _write_note(meta, markdown)
        except Exception as e:
            print(f"[capture] write stage failed: {e}", file=sys.stderr)
            raise CaptureError("write", e) from e
    finally:
        if video_path is not None and video_path.exists():
            try:
                video_path.unlink()
            except OSError as e:
                print(f"[capture] cleanup warning: could not delete {video_path}: {e}",
                      file=sys.stderr)


def _read_slides(paths: list[str]) -> list[dict]:
    """Read every slide: OCR the images, transcribe the videos.

    Instagram carousels mix the two freely and gallery-dl fetches both, but OCR
    on an `.mp4` just fails — so an all-video carousel rendered as N empty
    slides, losing the whole point of the post while the note looked complete.
    Video slides beyond VIDEO_SLIDE_LIMIT are named but not transcribed, to keep
    a long carousel from monopolising the 8GB server.
    """
    slides: list[dict] = []
    transcribed = 0
    for i, path in enumerate(paths, start=1):
        is_video = Path(path).suffix.lower() in VIDEO_SLIDE_SUFFIXES
        if not is_video:
            slides.append({"slide": i, "kind": "image", "text": ocr_images([path])[0]["text"]})
            continue
        if transcribed >= VIDEO_SLIDE_LIMIT:
            slides.append({"slide": i, "kind": "video", "text": "",
                           "note": f"not transcribed — over the {VIDEO_SLIDE_LIMIT}-video limit"})
            continue
        try:
            text = (transcribe(path).get("transcript") or "").strip()
            transcribed += 1
        except NoAudioError:
            slides.append({"slide": i, "kind": "video", "text": "", "note": "no audio track"})
            continue
        except Exception as e:
            print(f"[capture] slide {i} transcription failed (non-fatal): {e}", file=sys.stderr)
            slides.append({"slide": i, "kind": "video", "text": "", "note": f"transcription failed: {e}"})
            continue
        slides.append({"slide": i, "kind": "video", "text": text})
    return slides


def _capture_carousel(url: str) -> str:
    image_dir: Path | None = None
    try:
        try:
            meta = download_images(url)
        except Exception as e:
            print(f"[capture] download_images stage failed: {e}", file=sys.stderr)
            raise CaptureError("download_images", e) from e
        image_dir = Path(meta["image_paths"][0]).parent

        try:
            slides = _read_slides(meta["image_paths"])
        except Exception as e:
            print(f"[capture] slide-reading stage failed (non-fatal): {e}", file=sys.stderr)
            slides = [{"slide": i + 1, "text": ""} for i in range(meta["slide_count"])]

        try:
            markdown = format_carousel_note(meta, slides)
        except Exception as e:
            print(f"[capture] formatting stage failed: {e}", file=sys.stderr)
            raise CaptureError("formatting", e) from e

        try:
            return _write_note(meta, markdown)
        except Exception as e:
            print(f"[capture] write stage failed: {e}", file=sys.stderr)
            raise CaptureError("write", e) from e
    finally:
        if image_dir is not None and image_dir.exists():
            try:
                shutil.rmtree(image_dir)
            except OSError as e:
                print(f"[capture] cleanup warning: could not delete {image_dir}: {e}",
                      file=sys.stderr)


def _capture_document(url: str) -> str:
    try:
        meta = parse_document(url)
    except Exception as e:
        print(f"[capture] document stage failed: {e}", file=sys.stderr)
        raise CaptureError("document", e) from e

    try:
        markdown = format_note(meta)
    except Exception as e:
        print(f"[capture] formatting stage failed: {e}", file=sys.stderr)
        raise CaptureError("formatting", e) from e

    try:
        return _write_note(meta, markdown)
    except Exception as e:
        print(f"[capture] write stage failed: {e}", file=sys.stderr)
        raise CaptureError("write", e) from e


def capture_photo(image_path: str, caption: str = "") -> str:
    """OCR a photo already saved in raw/assets/ and write a raw note embedding it.

    Returns the raw note's path. Raises on failure so the caller can fall back to
    keeping just the saved image (the file is never lost either way).
    """
    img = Path(image_path)
    slides = ocr_images([str(img)])
    ocr_text = slides[0]["text"] if slides else ""
    markdown = format_photo_note(img.name, ocr_text, caption)
    raw_dir = Path(config.RAW_FOLDER)
    raw_dir.mkdir(parents=True, exist_ok=True)
    note_path = raw_dir / f"{img.stem}.md"  # image stem already starts with "photo-"
    note_path.write_text(markdown, encoding="utf-8")
    return str(note_path)


def capture(url: str) -> str:
    platform = _detect_platform(url)
    if platform in SOCIAL_VIDEO_PLATFORMS:
        return _capture_video(url)
    if platform in SOCIAL_IMAGE_PLATFORMS:
        if is_video_post(url):
            return _capture_video(url)
        return _capture_carousel(url)
    return _capture_document(url)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python capture.py <url>", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(capture(sys.argv[1]))
    except Exception:
        sys.exit(1)
