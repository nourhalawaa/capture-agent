"""One-off batch ingest: WhatsApp chat export (.txt) → capture pipeline → hub inbox.

Parses the export, then in chat order:
  - messages with URLs   → capture() each URL → VIDEO inbox line (bot format);
                           text in the same message as the link becomes context
  - plain text messages  → THOUGHT inbox lines (always — never consumed as
                           context for an adjacent link)

Failures append to system/skipped.md and the run continues. Instagram/
Facebook captures are spaced 30–60 s apart. URLs already in inbox.md are
skipped, so re-running after an interruption resumes where it left off.

Progress: one console line per URL; system/ingest-progress.md rewritten
every 10 items (phone-checkable via Obsidian). On finish or interrupt:
system/ingest-report.md + a summary entry appended to wiki/log.md.

Usage (from the repo root, venv active):
    python batch_ingest.py <export.txt> [--sender NAME] [--dry-run]
                           [--limit N] [--no-delay] [--only DOMAIN]

    --sender    whose messages count as "mine" (required only if the
                export has more than one sender)
    --dry-run   print parse stats + the full plan; capture nothing
    --limit N   process only the first N items (test runs)
    --no-delay  skip anti-rate-limit sleeps (testing only)
    --only STR  process only URLs whose domain contains STR
                (e.g. --only facebook); thoughts are skipped too
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import config
import inbox
from capture import CaptureError, capture
from pipeline.downloader import _detect_platform

URL_RE = re.compile(r"https?://\S+")

# Android: "04/07/2026, 3:53 pm - Name: text" — the space before am/pm is
# U+202F (narrow no-break space) in real exports; \s covers it. am/pm may
# be either case or absent (24 h clocks).
HEADER_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}), (?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
    r"(?:\s(?P<ampm>[APap][Mm]))? - (?P<rest>.*)$"
)
# iOS: "[12/05/2026, 14:45:03] Name: text"
IOS_RE = re.compile(r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{2,4}), (?P<time>[\d:]+)\] (?P<rest>.*)$")

# DD/MM tried before MM/DD — WhatsApp exports from this locale are day-first.
DATE_FORMATS = [
    "%d/%m/%Y %I:%M %p", "%d/%m/%y %I:%M %p", "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p",
    "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S",
]

ARTIFACTS = {
    "<media omitted>", "null", "this message was deleted",
    "you deleted this message", "<this message was edited>",
    "missed voice call", "missed video call",
}

IG_DELAY_RANGE = (120, 180)  # instagram — raised from (30,60) after an IG soft-block on 2026-07-13
FB_DELAY_RANGE = (30, 60)    # facebook — no throttling observed at this rate
OTHER_DELAY = 5              # seconds between captures on other platforms
PROGRESS_EVERY = 10         # rewrite ingest-progress.md every N items


@dataclass
class Message:
    sender: str
    text: str
    when: datetime | None


@dataclass
class Skip:
    url: str
    context: str
    stage: str
    error: str
    domain: str


def _clean(text: str) -> str:
    text = text.replace("‎", "").replace("‏", "").replace(" ", " ")
    text = text.replace("<This message was edited>", "")
    return text.strip()


def _domain(url: str) -> str:
    host = (urlsplit(url).hostname or "?").lower()
    return host[4:] if host.startswith("www.") else host


def _fmt_dur(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _parse_when(date_s: str, time_s: str, ampm: str | None) -> datetime | None:
    stamp = f"{date_s} {time_s}" + (f" {ampm.upper()}" if ampm else "")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def parse_export(path: Path) -> list[Message]:
    messages: list[Message] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.replace("‎", "").replace("‏", "").replace(" ", " ")
        m = HEADER_RE.match(line) or IOS_RE.match(line)
        if m:
            rest = m.group("rest")
            if ": " not in rest:
                continue  # system message (encryption notice, group events)
            sender, text = rest.split(": ", 1)
            ampm = m.groupdict().get("ampm")
            messages.append(
                Message(sender.strip(), text, _parse_when(m.group("date"), m.group("time"), ampm))
            )
        elif messages and line.strip():
            messages[-1].text += "\n" + line  # continuation of a multi-line message
    return messages


def build_items(messages: list[Message], sender: str) -> tuple[list[tuple], dict]:
    """Returns (chat-ordered items, parse stats).

    Items: ("VIDEO", url, context) | ("THOUGHT", text)
    """
    mine = [m for m in messages if m.sender == sender]
    items: list[tuple] = []
    stats = {"headers": len(messages), "mine": len(mine), "artifacts": 0,
             "non_url_msgs": 0, "url_msgs": 0, "domains": Counter()}

    for msg in mine:
        text = _clean(msg.text)
        if not text or text.lower() in ARTIFACTS:
            stats["artifacts"] += 1
            continue

        urls = [u.rstrip(".,)]!'\"") for u in URL_RE.findall(text)]
        if not urls:
            stats["non_url_msgs"] += 1
            items.append(("THOUGHT", text))
            continue

        stats["url_msgs"] += 1
        # context = only text in the same message as the link; standalone
        # messages are always their own THOUGHT (adjacency heuristic removed
        # per Nour, 2026-07-12 — it was eating genuine thoughts)
        context = " ".join(_clean(URL_RE.sub("", text)).split())

        for url in urls:
            stats["domains"][_domain(url)] += 1
            items.append(("VIDEO", url, context))
    return items, stats


def log_skipped(skip: Skip) -> None:
    skipped = Path(config.INBOX_FILE).parent / "skipped.md"
    if not skipped.exists():
        skipped.write_text("# Skipped — batch-ingest failures (retry or drop manually)\n\n", encoding="utf-8")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ctx = f' · "{skip.context}"' if skip.context else ""
    err = " ".join(skip.error.split())[:300]
    with skipped.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"- [{ts}] {skip.url}{ctx} · {skip.stage}: {err}\n")


def write_progress(processed: int, total: int, ok: int, failed: int, dupes: int,
                   thoughts: int, eta: str, last_item: str) -> None:
    path = Path(config.INBOX_FILE).parent / "ingest-progress.md"
    path.write_text(
        f"# Batch ingest — live progress\n\n"
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"- items processed: **{processed} / {total}**\n"
        f"- captured ok: {ok}\n"
        f"- failed → skipped.md: {failed}\n"
        f"- duplicates skipped: {dupes}\n"
        f"- thoughts written: {thoughts}\n"
        f"- ETA: {eta}\n"
        f"- last item: {last_item}\n",
        encoding="utf-8",
    )


def write_report(status: str, started: datetime, msg_stats: dict, items_total: int,
                 ok: int, failed: int, dupes: int, thoughts: int,
                 skips: list[Skip], capture_secs: list[float]) -> None:
    duration = datetime.now() - started
    avg = _fmt_dur(sum(capture_secs) / len(capture_secs)) if capture_secs else "n/a"
    by_stage = Counter(s.stage for s in skips)
    by_domain = Counter(s.domain for s in skips)

    lines = [
        "# Batch ingest report — WhatsApp export",
        "",
        f"- status: **{status}** at {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- messages parsed: {msg_stats['headers']} ({msg_stats['url_msgs']} with URLs, "
        f"{msg_stats['non_url_msgs']} plain, {msg_stats['artifacts']} artifacts filtered)",
        f"- items planned: {items_total}",
        f"- captured ok: **{ok}**",
        f"- failed: **{failed}**",
        f"- duplicates skipped: {dupes}",
        f"- thoughts written: {thoughts}",
        f"- duration: {_fmt_dur(duration.total_seconds())}, avg capture time: {avg}",
        "",
        "## Failures by stage",
        "",
    ]
    lines += [f"- {stage}: {n}" for stage, n in by_stage.most_common()] or ["- none"]
    lines += ["", "## Failures by domain", ""]
    lines += [f"- {dom}: {n}" for dom, n in by_domain.most_common()] or ["- none"]
    lines += ["", "## Full skip list", ""]
    if skips:
        for s in skips:
            ctx = f' · "{s.context}"' if s.context else ""
            lines.append(f"- {s.url}{ctx} · {s.stage}: {' '.join(s.error.split())[:200]}")
    else:
        lines.append("- none")
    lines.append("")

    report_path = Path(config.INBOX_FILE).parent / "ingest-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    wiki_log = Path(config.INBOX_FILE).parent.parent / "wiki" / "log.md"
    if wiki_log.exists():
        entry = (
            f"\n## [{datetime.now().strftime('%Y-%m-%d')}] ingest | batch ingest — WhatsApp export ({status})\n\n"
            f"- {msg_stats['headers']} messages parsed → {items_total} items: "
            f"{ok} captured, {failed} failed (see system/ingest-report.md + system/skipped.md), "
            f"{dupes} duplicates skipped, {thoughts} THOUGHT lines\n"
            f"- duration {_fmt_dur(duration.total_seconds())}, avg capture {avg}\n"
            f"- inbox lines appended by batch_ingest.py in bot format; raw notes in raw/\n"
        )
        with wiki_log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(entry)

    print(f"\nReport written to {report_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path)
    ap.add_argument("--sender", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-delay", action="store_true")
    ap.add_argument("--only", default=None, metavar="DOMAIN")
    ap.add_argument("--start-delay", type=int, default=0, metavar="SECS",
                    help="sleep before starting (rate-limit cool-down)")
    ap.add_argument("--skip-known-failures", action="store_true",
                    help="don't retry URLs already logged in system/skipped.md this run")
    args = ap.parse_args()

    if args.start_delay:
        print(f"cool-down: sleeping {args.start_delay}s before starting "
              f"(until ~{datetime.now().strftime('%H:%M')}+{args.start_delay // 60}m)")
        time.sleep(args.start_delay)

    messages = parse_export(args.export)
    if not messages:
        sys.exit("No messages parsed — is this a WhatsApp .txt export? (Android and iOS formats supported)")

    senders = sorted({m.sender for m in messages})
    sender = args.sender or (senders[0] if len(senders) == 1 else None)
    if sender is None:
        sys.exit(f"Multiple senders found: {senders}. Re-run with --sender \"<name>\".")
    if sender not in senders:
        sys.exit(f"Sender {sender!r} not in export. Found: {senders}")

    items, msg_stats = build_items(messages, sender)
    if args.only:
        items = [it for it in items if it[0] == "VIDEO" and args.only.lower() in _domain(it[1])]
    if args.limit:
        items = items[: args.limit]

    urls_total = sum(1 for it in items if it[0] == "VIDEO")
    print(f"Parsed {msg_stats['headers']} message headers from {len(senders)} sender(s) [{sender}]")
    print(f"  URL messages: {msg_stats['url_msgs']} · plain messages: {msg_stats['non_url_msgs']} "
          f"· artifacts filtered: {msg_stats['artifacts']}")
    print("  URLs by domain: " + ", ".join(f"{d} {n}" for d, n in msg_stats["domains"].most_common()))
    print(f"  → {len(items)} items to ingest ({urls_total} URLs, {len(items) - urls_total} thoughts)")

    if args.dry_run:
        for it in items:
            if it[0] == "VIDEO":
                print(f"  VIDEO   {it[1]}" + (f'  ctx: "{it[2]}"' if it[2] else ""))
            else:
                print(f'  THOUGHT "{it[1][:100]}"')
        return

    inbox_text = Path(config.INBOX_FILE).read_text(encoding="utf-8") if Path(config.INBOX_FILE).exists() else ""
    known_failures: set[str] = set()
    if args.skip_known_failures:
        skipped_path = Path(config.INBOX_FILE).parent / "skipped.md"
        if skipped_path.exists():
            for line in skipped_path.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^\-\s\[[^\]]+\]\s(\S+)", line)
                if m:
                    known_failures.add(m.group(1))
            print(f"--skip-known-failures: {len(known_failures)} URLs from skipped.md will be skipped, not retried")
    seen_urls: set[str] = set()
    skips: list[Skip] = []
    capture_secs: list[float] = []
    ok = failed = dupes = thoughts = url_idx = 0
    started = datetime.now()
    status = "completed"

    try:
        for idx, item in enumerate(items, 1):
            if item[0] == "THOUGHT":
                if f'THOUGHT: "{inbox._one_line(item[1])}"' in inbox_text:
                    dupes += 1
                else:
                    inbox.log_thought(item[1])
                    thoughts += 1
                    print(f"[{url_idx}/{urls_total}] 💭 thought queued")
            else:
                _, url, context = item
                url_idx += 1
                if url in known_failures:
                    dupes += 1
                    print(f"[{url_idx}/{urls_total}] ⏭️  known failure, skipping (see skipped.md)")
                elif url in seen_urls or url in inbox_text:
                    dupes += 1
                    print(f"[{url_idx}/{urls_total}] ⏭️  duplicate, skipping")
                else:
                    seen_urls.add(url)
                    if capture_secs and not args.no_delay:
                        platform = _detect_platform(url)
                        if platform == "instagram":
                            wait = random.randint(*IG_DELAY_RANGE)
                        elif platform == "facebook":
                            wait = random.randint(*FB_DELAY_RANGE)
                        else:
                            wait = OTHER_DELAY
                        time.sleep(wait)
                    t0 = time.time()
                    try:
                        result_path = capture(url)
                        took = time.time() - t0
                        capture_secs.append(took)
                        inbox.log_video(Path(result_path).stem, url, context)
                        ok += 1
                        label = Path(result_path).stem[:40]
                        icon = "✅"
                    except Exception as e:
                        took = time.time() - t0
                        capture_secs.append(took)
                        failed += 1
                        stage = e.stage if isinstance(e, CaptureError) else type(e).__name__
                        skip = Skip(url, context, stage, str(e), _domain(url))
                        skips.append(skip)
                        log_skipped(skip)
                        label = f"{_domain(url)} — {stage}"
                        icon = "❌"
                    avg = sum(capture_secs) / len(capture_secs)
                    eta = _fmt_dur((urls_total - url_idx) * (avg + (sum(IG_DELAY_RANGE) / 2 if not args.no_delay else 0)))
                    print(f"[{url_idx}/{urls_total}] {icon} {label} ({_fmt_dur(took)}) "
                          f"| ok {ok} · fail {failed} · dup {dupes} · ETA ~{eta}")

            if idx % PROGRESS_EVERY == 0:
                last = item[1] if item[0] == "VIDEO" else f'THOUGHT "{item[1][:60]}"'
                eta = "n/a"
                if capture_secs:
                    avg = sum(capture_secs) / len(capture_secs)
                    eta = "~" + _fmt_dur((urls_total - url_idx) * (avg + (sum(IG_DELAY_RANGE) / 2 if not args.no_delay else 0)))
                write_progress(idx, len(items), ok, failed, dupes, thoughts, eta, last)
    except KeyboardInterrupt:
        status = "interrupted"
        print("\nInterrupted — safe to re-run, completed items will be skipped.")
    finally:
        write_progress(min(idx, len(items)) if items else 0, len(items), ok, failed, dupes, thoughts, "done", status)
        write_report(status, started, msg_stats, len(items), ok, failed, dupes, thoughts, skips, capture_secs)

    print(f"\nDone ({status}): {ok} captured, {failed} failed, {dupes} duplicates, {thoughts} thoughts.")


if __name__ == "__main__":
    main()
