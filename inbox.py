"""Append-only writer for the hub's system/inbox.md queue.

Line formats (see the hub's CLAUDE.md, INBOX FORMAT):
  - [YYYY-MM-DD HH:MM] VIDEO [[<raw-note>]] · [source](<url>) · "<context>" · #unsorted
  - [YYYY-MM-DD HH:MM] FILE [[<raw-file>]] · "<caption>" · #unsorted
  - [YYYY-MM-DD HH:MM] THOUGHT: "<verbatim text>" · #unsorted

Items append under a `## YYYY-MM-DD` date heading, created with the
first capture of each day. Empty context/caption segments are omitted.
Lines are never modified or deleted here — the inbox is append-only
from the bot's side; sorting later flips #unsorted → #sorted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import config


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _one_line(text: str) -> str:
    """Collapse internal newlines so the item stays a single inbox line."""
    return " ⏎ ".join(part.strip() for part in text.splitlines() if part.strip())


def _append(line: str) -> None:
    inbox_path = Path(config.INBOX_FILE)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    existing = inbox_path.read_text(encoding="utf-8") if inbox_path.exists() else ""
    heading = f"## {datetime.now().strftime('%Y-%m-%d')}"
    has_heading = any(ln.strip() == heading for ln in existing.splitlines())
    with inbox_path.open("a", encoding="utf-8", newline="\n") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        if not has_heading:
            f.write(f"\n{heading}\n\n")
        f.write(line + "\n")


def _entry_line(kind: str, note_name: str, url: str, context: str) -> str:
    parts = [f"- [{_timestamp()}] {kind} [[{note_name}]]"]
    if url:
        parts.append(f"[source]({url})")
    ctx = _one_line(context)
    if ctx:
        parts.append(f'"{ctx}"')
    parts.append("#unsorted")
    return " · ".join(parts)


def log_video(note_name: str, url: str, context: str = "") -> None:
    """Queue a successful capture. note_name is the raw note's stem (no .md)."""
    _append(_entry_line("VIDEO", note_name, url, context))


def log_file(file_name: str, context: str = "", url: str = "") -> None:
    """Queue a saved photo/document. file_name keeps its extension for the wikilink."""
    _append(_entry_line("FILE", file_name, url, context))


def log_thought(text: str) -> None:
    """Queue a text-only message, verbatim (newlines collapsed to ⏎)."""
    _append(f'- [{_timestamp()}] THOUGHT: "{_one_line(text)}" · #unsorted')


def log_failed(url: str, context: str = "", stage: str = "capture", error: str = "") -> None:
    """Append a failed capture to system/skipped.md so it's never silently lost.

    Uses the same line format as batch_ingest.py, so live-bot and batch failures
    share one review list that sorting/ingesting surfaces:
      - [YYYY-MM-DD HH:MM] <url> · "<context>" · <stage>: <error>
    """
    skipped_path = Path(config.SKIPPED_FILE)
    skipped_path.parent.mkdir(parents=True, exist_ok=True)
    if not skipped_path.exists():
        skipped_path.write_text(
            "# Skipped — capture failures (retry or triage manually)\n\n", encoding="utf-8"
        )
    ctx = _one_line(context)
    ctx_part = f' · "{ctx}"' if ctx else ""
    err = " ".join((error or "").split())[:300]
    with skipped_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"- [{_timestamp()}] {url}{ctx_part} · {stage}: {err}\n")
