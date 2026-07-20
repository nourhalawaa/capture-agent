from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from yt_dlp import YoutubeDL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

TEMP_DIR = PROJECT_ROOT / "temp"
_REEL_RE = re.compile(r"/reels?/", re.I)


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


def _apply_ig_cookies(opts: dict, url: str) -> None:
    if _detect_platform(url) not in ("instagram", "facebook"):
        return
    if config.GALLERY_DL_COOKIES_FILE:
        opts["cookiefile"] = config.GALLERY_DL_COOKIES_FILE
    elif config.GALLERY_DL_COOKIES:
        opts["cookiesfrombrowser"] = ("firefox", config.GALLERY_DL_COOKIES, None, None)


def is_video_post(url: str) -> bool:
    """instagram/facebook only: True = video/reel, False = image/carousel."""
    if _REEL_RE.search(url):
        return True
    base_opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    try:
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        opts = dict(base_opts)
        _apply_ig_cookies(opts, url)
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            print(f"[is_video_post] probe failed, treating as image: {e}", file=sys.stderr)
            return False
    if not info:
        return False
    if info.get("_type") == "playlist":
        return len(list(info.get("entries") or [])) > 0
    return True


def download(url: str) -> dict:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    base_opts = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(TEMP_DIR / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
    }

    # Instagram/Facebook: try anonymously first. yt-dlp's cookie-authenticated
    # code path has been unreliable against Instagram's current API (404s on
    # public posts that succeed with no cookies at all) — cookies are the
    # fallback for content anonymous access can't reach, not the default.
    if _detect_platform(url) in ("instagram", "facebook"):
        try:
            with YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:
            print(f"[download] anonymous attempt failed ({e}); retrying with cookies", file=sys.stderr)
            ydl_opts = dict(base_opts)
            _apply_ig_cookies(ydl_opts, url)
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
    else:
        with YoutubeDL(base_opts) as ydl:
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


def _cookie_args() -> list[str]:
    if config.GALLERY_DL_COOKIES_FILE:
        return ["--cookies", config.GALLERY_DL_COOKIES_FILE]
    if config.GALLERY_DL_COOKIES:
        return ["--cookies-from-browser", f"firefox:{config.GALLERY_DL_COOKIES}"]
    return []


def _gallery_dl_into(run_dir: Path, url: str, cookie_args: list[str]) -> list[tuple]:
    """Run gallery-dl into run_dir and collect (num, image_path, metadata) items."""
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "-D", str(run_dir),
        "--write-metadata",
        *cookie_args,
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"[download_images] gallery-dl exit {proc.returncode}: {proc.stderr.strip()}",
              file=sys.stderr)
    items = []
    for jf in run_dir.glob("*.json"):
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
        img = jf.with_suffix("")
        if img.exists():
            items.append((data.get("num", 0), str(img.resolve()), data))
    return items


def download_images(url: str) -> dict:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Anonymous first, cookies only as fallback — mirrors the video path. Sending
    # cookies on every request is what got the burner account flagged as bot
    # activity, so we avoid them unless anonymous access genuinely can't reach
    # the post (private/login-walled content).
    run_dir = TEMP_DIR / f"carousel_{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    items = _gallery_dl_into(run_dir, url, [])

    if not items:
        cookie_args = _cookie_args()
        if cookie_args:
            print("[download_images] anonymous attempt got no images; retrying with cookies",
                  file=sys.stderr)
            shutil.rmtree(run_dir, ignore_errors=True)  # discard the empty anonymous attempt
            run_dir = TEMP_DIR / f"carousel_{uuid4().hex[:8]}"
            run_dir.mkdir(parents=True, exist_ok=True)
            items = _gallery_dl_into(run_dir, url, cookie_args)

    if not items:
        raise RuntimeError(f"gallery-dl downloaded no images for {url}")

    items.sort(key=lambda t: t[0])
    image_paths = [p for _, p, _ in items]
    post = items[0][2]
    creator = post.get("username", "") or ""
    platform = _detect_platform(url)

    if post.get("count") not in (None, len(image_paths)):
        print(
            f"[download_images] note: post reports {post.get('count')} items, "
            f"{len(image_paths)} images downloaded (carousel may contain a video slide)",
            file=sys.stderr,
        )

    return {
        "image_paths": image_paths,
        "title": f"{platform} post by {creator}" if creator else f"{platform} post",
        "creator": creator,
        "caption": post.get("description", "") or "",
        "url": url,
        "platform": platform,
        "slide_count": len(image_paths),
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from pprint import pprint

    if len(sys.argv) >= 3 and sys.argv[1] == "images":
        pprint(download_images(sys.argv[2]), sort_dicts=False, width=100)
    elif len(sys.argv) >= 2:
        pprint(download(sys.argv[1]), sort_dicts=False, width=100)
    else:
        print("usage: python pipeline/downloader.py <video_url>", file=sys.stderr)
        print("       python pipeline/downloader.py images <post_url>", file=sys.stderr)
        sys.exit(1)
