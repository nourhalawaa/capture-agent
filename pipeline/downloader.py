from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = PROJECT_ROOT / "temp"


def _detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "tiktok.com" in host:
        return "tiktok"
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host or "fb.watch" in host:
        return "facebook"
    return "unknown"


def download(url: str) -> dict:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(TEMP_DIR / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    video_path = ""
    if info.get("requested_downloads"):
        video_path = info["requested_downloads"][0].get("filepath", "") or ""
    if not video_path:
        video_path = ydl.prepare_filename(info)

    return {
        "video_path": str(Path(video_path).resolve()) if video_path else "",
        "title": info.get("title") or "",
        "creator": info.get("uploader") or info.get("channel") or info.get("creator") or "",
        "duration": int(info.get("duration") or 0),
        "caption": info.get("description") or "",
        "url": url,
        "platform": _detect_platform(url),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python pipeline/downloader.py <url>", file=sys.stderr)
        sys.exit(1)
    from pprint import pprint
    sys.stdout.reconfigure(encoding="utf-8")
    pprint(download(sys.argv[1]), sort_dicts=False, width=100)
