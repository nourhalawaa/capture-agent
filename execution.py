"""Reader/writer/renderer for the hub's execution district (`execution/`).

A separate pipeline from capture, on purpose. Capture optimises for never
losing anything; execution optimises for *actively forgetting* — finished work
leaves, dropped work leaves, or the system clogs. See `execution/README.md` in
the hub for the district's rules.

Files (paths from config, all env-overridable):
  commitments.md  hand-written by Nour. READ ONLY here, always.
  actions.md      hand-written by Nour. The ONLY mutation allowed is deleting
                  one line when it's closed — never a rewrite or an annotation.
  inbox.md        /do appends here. Nour empties it as he promotes.
  done.md         append-only log of closed actions (temporary home — a
                  tracking system is planned; DONE_FILE moves then).
  NOW.md          fully generated, overwritten wholesale on every render.

There is no scheduler: the render is a side effect of every mutation, so NOW.md
is fresh after any phone action. `/now` re-renders on demand to pick up
hand-edits made on the laptop.

No scoring, no ranking, no aging decay, no automatic classification. Ranking is
manual in v1 by design — Nour reads NOW and picks.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple

import config

# Reuse the capture inbox's clock and newline-collapsing so timestamps and
# verbatim handling are identical across both queues.
from inbox import _one_line, now

STALE_DAYS = 14

_COMMENT_INLINE_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_COMMITMENT_RE = re.compile(r"^\s*[-*]\s*@(?P<slug>[\w-]+)\s*(?P<rest>.*)$")
_ACTION_RE = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<body>.*)$")
_SLUG_RE = re.compile(r"@([\w-]+)")
_DUE_RE = re.compile(r"\bdue:\s*(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
_DONE_LINE_RE = re.compile(r"^\s*-\s*\[(\d{4}-\d{2}-\d{2})[^\]]*\]\s*(?P<body>.*)$")
_SEPARATORS = re.compile(r"[·|]")
_STATES = {"active", "paused"}


def _timestamp() -> str:
    return now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


def _read_lines(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8").splitlines()


def _content_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Drop HTML-comment regions, keeping original line indices.

    The seed files carry their format docs — and worked examples — inside
    `<!-- -->` blocks. Parsing those would invent commitments and actions Nour
    never wrote, so comments are skipped. Indices are preserved because
    `close_action` deletes by line number in the real file.
    """
    out: list[tuple[int, str]] = []
    in_comment = False
    for i, raw in enumerate(lines):
        line = _COMMENT_INLINE_RE.sub("", raw)
        if in_comment:
            if "-->" in line:
                line = line.split("-->", 1)[1]
                in_comment = False
            else:
                continue
        if "<!--" in line:
            line = line.split("<!--", 1)[0]
            in_comment = True
        if line.strip():
            out.append((i, line))
    return out


@dataclass
class Commitment:
    slug: str
    label: str
    state: str


@dataclass
class Action:
    body: str  # everything after the checkbox, verbatim as typed
    text: str  # body with @slug and due: stripped, for display
    slug: str | None
    due: date | None
    done: bool
    lineno: int  # 0-based index into actions.md


def parse_commitments(path: str | Path | None = None) -> list[Commitment]:
    """Parse commitments.md. Forgiving: label and state are both optional."""
    commitments: list[Commitment] = []
    seen: set[str] = set()
    for _, line in _content_lines(_read_lines(path or config.COMMITMENTS_FILE)):
        m = _COMMITMENT_RE.match(line)
        if not m:
            continue
        slug = m.group("slug").lower()
        if slug in seen:
            continue
        seen.add(slug)

        parts = [p.strip() for p in _SEPARATORS.split(m.group("rest")) if p.strip()]
        state = "active"
        if parts and parts[-1].lower() in _STATES:
            state = parts.pop().lower()
        commitments.append(Commitment(slug=slug, label=" · ".join(parts) or slug, state=state))
    return commitments


def parse_actions(path: str | Path | None = None) -> list[Action]:
    """Parse actions.md. Tolerates `- [ ]`, `-[ ]`, `* [ ]`, stray whitespace."""
    actions: list[Action] = []
    for lineno, line in _content_lines(_read_lines(path or config.ACTIONS_FILE)):
        m = _ACTION_RE.match(line)
        if not m:
            continue
        body = m.group("body").strip()

        slug_match = _SLUG_RE.search(body)
        due_match = _DUE_RE.search(body)
        due = None
        if due_match:
            try:
                due = date.fromisoformat(due_match.group(1))
            except ValueError:
                due = None  # a typo'd date is not worth refusing the action over

        text = body
        if slug_match:
            text = text.replace(slug_match.group(0), "")
        if due_match:
            text = text.replace(due_match.group(0), "")
        text = " ".join(text.split()).strip(" -–—·")

        actions.append(
            Action(
                body=body,
                text=text or body,
                slug=slug_match.group(1).lower() if slug_match else None,
                due=due,
                done=m.group("mark").lower() == "x",
                lineno=lineno,
            )
        )
    return actions


def _uncommitted_count(path: str | Path | None = None) -> int:
    lines = _read_lines(path or config.EXEC_INBOX_FILE)
    return sum(1 for _, line in _content_lines(lines) if "#uncommitted" in line)


def _last_closed_by_slug(path: str | Path | None = None) -> dict[str, date]:
    """Most recent close date per commitment slug, read from the done log.

    done.md is the only timestamped surface in the district. Hand-typed actions
    carry no creation date and the brief forbids inventing one, so "untouched"
    is derived from here — a reported fact, not a decay term in a score.
    """
    latest: dict[str, date] = {}
    for _, line in _content_lines(_read_lines(path or config.DONE_FILE)):
        m = _DONE_LINE_RE.match(line)
        if not m:
            continue
        try:
            when = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        slug_match = _SLUG_RE.search(m.group("body"))
        if not slug_match:
            continue
        slug = slug_match.group(1).lower()
        if slug not in latest or when > latest[slug]:
            latest[slug] = when
    return latest


def ordered_open_actions() -> list[Action]:
    """The actions NOW displays, in display order — the numbering `/done N` uses.

    Commitments in commitments.md order × actions in actions.md order. Recomputed
    every time from the files, so there's no index state file to drift out of sync.
    Only actions under *active* commitments appear, because that's exactly what
    NOW shows; paused and unassigned actions are closable by text instead.
    """
    actions = [a for a in parse_actions() if not a.done]
    ordered: list[Action] = []
    for c in parse_commitments():
        if c.state != "active":
            continue
        ordered.extend(a for a in actions if a.slug == c.slug)
    return ordered


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def _write_atomic(path: str | Path, text: str) -> None:
    """Replace a file in one step.

    actions.md has two writers — this bot and Nour by hand on laptop/phone — so a
    half-written file must never be observable. Same class of hazard that cost 89
    system/inbox.md lines to a Syncthing conflict on 2026-07-28; atomic replace
    plus an append-only done log makes it recoverable, not impossible.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def _append_dated(path: str | Path, line: str) -> None:
    """Append under a `## YYYY-MM-DD` heading, created by the day's first item.

    Mirrors inbox.py's queue format so both inboxes read the same way.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    heading = f"## {now().strftime('%Y-%m-%d')}"
    has_heading = any(ln.strip() == heading for ln in existing.splitlines())
    with p.open("a", encoding="utf-8", newline="\n") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        if not has_heading:
            f.write(f"\n{heading}\n\n")
        f.write(line + "\n")


def log_todo(text: str) -> str:
    """Append a /do capture to the execution inbox, verbatim. Returns the line."""
    line = f'- [{_timestamp()}] "{_one_line(text)}" · #uncommitted'
    _append_dated(config.EXEC_INBOX_FILE, line)
    return line


class CloseResult(NamedTuple):
    ok: bool
    message: str  # ready to send back to Telegram as-is
    closed: str | None


def close_action(selector: int | str) -> CloseResult:
    """Close one action: delete its line, log it verbatim, re-render NOW.

    `selector` is either a position in the NOW numbering or a text substring.
    An ambiguous or unmatched text selector mutates nothing — it reports the
    candidates instead, because guessing which of Nour's lines to delete is
    worse than doing nothing.
    """
    if isinstance(selector, str) and selector.strip().isdigit():
        selector = int(selector.strip())

    if isinstance(selector, int):
        ordered = ordered_open_actions()
        if not ordered:
            return CloseResult(False, "Nothing open under an active commitment.", None)
        if not 1 <= selector <= len(ordered):
            return CloseResult(
                False, f"There's no #{selector} — NOW has {len(ordered)} open.", None
            )
        target = ordered[selector - 1]
    else:
        needle = selector.strip().lower()
        if not needle:
            return CloseResult(False, "Give me a number from NOW, or some of the text.", None)
        # Text search covers every open action, including paused-commitment and
        # unassigned ones — those have no NOW number, so text is their only route.
        matches = [a for a in parse_actions() if not a.done and needle in a.body.lower()]
        if not matches:
            return CloseResult(False, f'Nothing open matching "{selector}".', None)
        if len(matches) > 1:
            listed = "\n".join(f"· {a.text}" for a in matches[:6])
            more = "" if len(matches) <= 6 else f"\n…and {len(matches) - 6} more"
            return CloseResult(
                False,
                f'"{selector}" matches {len(matches)} — nothing closed. Be more specific:'
                f"\n{listed}{more}",
                None,
            )
        target = matches[0]

    lines = _read_lines(config.ACTIONS_FILE)
    if not 0 <= target.lineno < len(lines):
        return CloseResult(False, "actions.md changed underneath me — try /now, then again.", None)

    remaining = lines[: target.lineno] + lines[target.lineno + 1 :]
    _write_atomic(config.ACTIONS_FILE, "\n".join(remaining).rstrip("\n") + "\n")
    _append_dated(config.DONE_FILE, f"- [{_timestamp()}] {target.body}")
    render_now()
    return CloseResult(True, f"✅ Done — {target.text}", target.body)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def _due_note(due: date | None, today: date) -> str:
    if due is None:
        return ""
    delta = (due - today).days
    if delta < 0:
        return f" — **overdue** {due.isoformat()}"
    if delta == 0:
        return " — **due today**"
    return f" — due {due.isoformat()}"


def _ago(when: date | None, today: date) -> str:
    if when is None:
        return "never"
    days = (today - when).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def render_now() -> str:
    """Regenerate NOW.md from commitments.md + actions.md. Returns the body text.

    NOW shows open actions grouped under active commitments and nothing else.
    Everything hidden is accounted for in OVERVIEW, so nothing can silently
    vanish — hidden is not deleted.
    """
    today = now().date()
    commitments = parse_commitments()
    actions = parse_actions()
    open_actions = [a for a in actions if not a.done]
    last_closed = _last_closed_by_slug()

    known = {c.slug for c in commitments}
    active = [c for c in commitments if c.state == "active"]
    paused = [c for c in commitments if c.state != "active"]
    unassigned = [a for a in open_actions if a.slug is None or a.slug not in known]

    body: list[str] = ["# NOW", ""]
    n = 0
    if not commitments:
        body += [
            "No commitments yet — write 3 to 5 in `commitments.md`, then tag actions",
            "with their `@slug`. Until then this render has nothing to group by.",
            "",
        ]
    elif not active:
        body += ["Every commitment is `paused`. Nothing is asking for attention.", ""]
    else:
        for c in active:
            mine = [a for a in open_actions if a.slug == c.slug]
            body.append(f"## {c.label}  `@{c.slug}`")
            body.append("")
            if not mine:
                body.append("*Nothing open — either it's done, or it needs a next action.*")
            else:
                for a in mine:
                    n += 1
                    body.append(f"{n}. {a.text}{_due_note(a.due, today)}")
            body.append("")

    body += ["---", "", "# OVERVIEW", ""]
    if active:
        body += [
            "| Commitment | Open | Last closed |",
            "|---|---|---|",
        ]
        for c in active:
            count = sum(1 for a in open_actions if a.slug == c.slug)
            body.append(f"| {c.label} | {count} | {_ago(last_closed.get(c.slug), today)} |")
        body.append("")

    notes: list[str] = []
    pending = _uncommitted_count()
    notes.append(
        f"**Execution inbox:** {pending} uncommitted"
        + ("" if pending else " — empty")
    )
    if unassigned:
        notes.append(
            f"**Unassigned:** {len(unassigned)} open action(s) with no known `@commitment` "
            "— hidden from NOW, close with `/done <text>`"
        )
    if paused:
        hidden = sum(1 for a in open_actions if a.slug in {c.slug for c in paused})
        notes.append(
            f"**Paused:** {len(paused)} commitment(s) hiding {hidden} action(s) "
            f"({', '.join('@' + c.slug for c in paused)}) — hidden, not deleted"
        )

    stale = [
        c
        for c in active
        if (last := last_closed.get(c.slug)) is None or (today - last).days >= STALE_DAYS
    ]
    stale_with_work = [c for c in stale if any(a.slug == c.slug for a in open_actions)]
    for c in stale_with_work:
        last = last_closed.get(c.slug)
        when = "nothing closed yet" if last is None else f"nothing closed since {last.isoformat()}"
        notes.append(f"**Untouched:** `@{c.slug}` — {when}")

    body += [f"- {line}" for line in notes]
    body.append("")

    text = "\n".join(body).rstrip() + "\n"
    frontmatter = (
        "---\n"
        "type: execution-render\n"
        "tags: [execution, now]\n"
        "created: 2026-07-30\n"
        f"updated: {_timestamp()}\n"
        "machine_generated: true\n"
        "---\n\n"
        "> Generated from `commitments.md` + `actions.md`. Never hand-edit — the next\n"
        "> `/do`, `/done`, or `/now` overwrites this file wholesale. Edit `actions.md`.\n\n"
    )
    _write_atomic(config.NOW_FILE, frontmatter + text)
    return text


def for_telegram(body: str) -> str:
    """Trim a rendered NOW body down to what reads well on a phone.

    Drops the OVERVIEW table (unreadable in a chat bubble; it's there for
    Obsidian) and the emphasis markers. Sent as plain text on purpose — Telegram's
    MarkdownV2 needs every special character escaped, and a parse failure means
    the message doesn't send at all. Nour's own action text is arbitrary, so
    plain text is the robust choice.
    """
    kept = [
        line
        for line in body.splitlines()
        if not line.startswith("|") and line.strip() not in {"---", "# NOW"}
    ]
    out: list[str] = []
    for line in kept:
        line = line.replace("**", "").replace("`", "").rstrip()
        if not line and (not out or not out[-1]):
            continue  # the dropped table/rule lines leave blank runs behind
        out.append(line)
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- #
# CLI — lets the whole module be exercised without starting a second Telegram
# poller (only one process may poll the token; the server is live).
# --------------------------------------------------------------------------- #


def _cli(argv: list[str]) -> int:
    # Windows consoles default to a legacy codepage (cp1256 here), which can't
    # encode the · / — / ✅ this module emits. Without this, a *successful* close
    # still crashes on the way to printing its confirmation.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(__doc__)
        print("Usage: python execution.py render | add \"<text>\" | done <n|text> | show")
        return 0

    cmd, rest = argv[0], argv[1:]
    if cmd == "render":
        print(render_now())
        print(f"→ wrote {config.NOW_FILE}", file=sys.stderr)
        return 0
    if cmd == "add":
        if not rest:
            print("add needs text", file=sys.stderr)
            return 2
        print(log_todo(" ".join(rest)))
        render_now()
        return 0
    if cmd == "done":
        if not rest:
            print("done needs a number or some text", file=sys.stderr)
            return 2
        result = close_action(" ".join(rest))
        print(result.message)
        return 0 if result.ok else 1
    if cmd == "show":
        p = Path(config.NOW_FILE)
        print(p.read_text(encoding="utf-8") if p.exists() else "(NOW.md not rendered yet)")
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
