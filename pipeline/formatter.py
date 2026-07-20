from __future__ import annotations

from datetime import date


def _has_real_words(text: str) -> bool:
    """Return True if text contains at least one token that is not a hashtag,
    emoji, number, or punctuation-only string."""
    for token in text.split():
        if not token.startswith("#") and any(c.isalpha() for c in token):
            return True
    return False


def format_note(meta: dict, transcription: dict | None = None) -> str:
    is_document = meta.get("platform") == "document"

    raw_title = meta.get("title") or ""
    if _has_real_words(raw_title):
        title = raw_title
    else:
        creator = meta.get("creator") or ""
        platform = meta.get("platform") or "unknown"
        title = f"{platform} video by {creator}" if creator else f"{platform} video"

    meta_lines = [
        f"- **Source:** {meta.get('url', '')}",
        f"- **Platform:** {meta.get('platform', '')}",
    ]
    if meta.get("creator"):
        meta_lines.append(f"- **Creator:** {meta['creator']}")
    if not is_document:
        m, s = divmod(int(meta.get("duration") or 0), 60)
        meta_lines.append(f"- **Duration:** {m}:{s:02d}")
    meta_lines += [
        f"- **Captured:** {date.today().isoformat()}",
        "- **Status:** unprocessed",
    ]

    parts = [
        f"# {title}",
        "",
        *meta_lines,
        "",
    ]

    if is_document:
        parts += [
            "## Content",
            "",
            meta.get("content", ""),
        ]
    else:
        caption = meta.get("caption") or "_No caption._"
        transcript = (transcription or {}).get("transcript", "")
        parts += [
            "## Transcript",
            "",
            transcript,
            "",
            "## Caption",
            "",
            caption,
        ]

    return "\n".join(parts) + "\n"


def format_photo_note(image_name: str, ocr_text: str, caption: str = "") -> str:
    """Note for a photo sent straight to the bot: embeds the image + its OCR text.

    Unlike documents (saved as-is), photos are cheap to OCR, so their text is
    captured here and becomes sortable/searchable like a transcript.
    """
    ocr_text = (ocr_text or "").strip()
    # Title: prefer Nour's caption, else the first OCR line with real words
    # (skips decorative/noise lines), else a generic label.
    title = "Photo"
    cap_first = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    if cap_first:
        title = cap_first[:80]
    else:
        for line in ocr_text.splitlines():
            if line.strip() and _has_real_words(line):
                title = line.strip()[:80]
                break

    parts = [
        f"# {title}",
        "",
        "- **Source:** Telegram photo",
        f"- **Captured:** {date.today().isoformat()}",
        "- **Status:** unprocessed",
        "",
        f"![[assets/{image_name}]]",
        "",
    ]
    if caption.strip():
        parts += ["## Caption", "", caption.strip(), ""]
    parts += ["## Text (OCR)", "", ocr_text or "_No text detected._"]
    return "\n".join(parts) + "\n"


def format_carousel_note(meta: dict, slides: list[dict]) -> str:
    raw_title = meta.get("title") or ""
    if _has_real_words(raw_title):
        title = raw_title
    else:
        creator = meta.get("creator") or ""
        platform = meta.get("platform") or "unknown"
        title = f"{platform} post by {creator}" if creator else f"{platform} post"

    meta_lines = [
        f"- **Source:** {meta.get('url', '')}",
        f"- **Platform:** {meta.get('platform', '')}",
    ]
    if meta.get("creator"):
        meta_lines.append(f"- **Creator:** {meta['creator']}")
    meta_lines += [
        f"- **Slides:** {meta.get('slide_count', len(slides))}",
        f"- **Captured:** {date.today().isoformat()}",
        "- **Status:** unprocessed",
    ]

    caption = meta.get("caption") or "_No caption._"

    parts = [f"# {title}", "", *meta_lines, "", "## Caption", "", caption, "", "## Slides", ""]
    for s in slides:
        text = (s.get("text") or "").strip()
        parts += [f"### Slide {s['slide']}", "", text or "_No text on this slide._", ""]

    return "\n".join(parts).rstrip() + "\n"
