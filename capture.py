from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

import config
from pipeline.downloader import download, download_images, is_video_post, _detect_platform
from pipeline.transcriber import transcribe
from pipeline.formatter import format_note, format_carousel_note
from pipeline.document import parse_document
from pipeline.ocr import ocr_images

_IG_POST_RE = re.compile(r"/(?:p|reel|reels|tv)/([^/?#]+)")

SOCIAL_VIDEO_PLATFORMS = {"youtube", "tiktok"}
SOCIAL_IMAGE_PLATFORMS = {"instagram", "facebook"}


class CaptureError(Exception):
    def __init__(self, stage: str, original: BaseException):
        super().__init__(f"{stage}: {original}")
        self.stage = stage
        self.original = original


def _slugify(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    illegal = set('<>:"/\\|?*')
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
        except Exception as e:
            print(f"[capture] transcription stage failed: {e}", file=sys.stderr)
            raise CaptureError("transcription", e) from e

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
            slides = ocr_images(meta["image_paths"])
        except Exception as e:
            print(f"[capture] ocr stage failed (non-fatal): {e}", file=sys.stderr)
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
