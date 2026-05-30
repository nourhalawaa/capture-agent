from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import config
from pipeline.downloader import download, _detect_platform
from pipeline.transcriber import transcribe
from pipeline.formatter import format_note
from pipeline.document import parse_document

VIDEO_PLATFORMS = {"youtube", "tiktok", "instagram", "facebook"}


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


def _make_filename(meta: dict) -> str:
    if meta.get("platform") == "document":
        url_hash = hashlib.sha1(meta["url"].encode()).hexdigest()[:8]
        slug = _slugify(meta.get("title", ""))
        if slug:
            return f"{slug}-{url_hash}.md"
        return f"{url_hash}.md"
    video_id = Path(meta["video_path"]).stem
    slug = _slugify(meta.get("title", ""))
    if slug:
        return f"{slug}-{video_id}.md"
    return f"{video_id}.md"


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
                print(f"[capture] cleanup warning: could not delete {video_path}: {e}", file=sys.stderr)


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
    if _detect_platform(url) in VIDEO_PLATFORMS:
        return _capture_video(url)
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
