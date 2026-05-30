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
