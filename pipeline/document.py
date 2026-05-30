from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from markitdown import MarkItDown


def parse_document(url: str) -> dict:
    md = MarkItDown()
    result = md.convert(url)

    content = result.markdown
    title = result.title or url

    return {
        "title": title,
        "creator": "",
        "url": url,
        "platform": "document",
        "content": content.strip(),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python pipeline/document.py <url>", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    result = parse_document(sys.argv[1])
    print(f"Title: {result['title']}")
    print()
    print(result["content"])
