from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config
import inbox
from capture import CaptureError, capture, capture_photo

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN or TOKEN.startswith("<"):
    sys.exit("TELEGRAM_BOT_TOKEN not set in .env — add your BotFather token and restart.")

try:
    ALLOWED_USER_ID = int(os.environ.get("TELEGRAM_ALLOWED_USER_ID", ""))
except ValueError:
    sys.exit(
        "TELEGRAM_ALLOWED_USER_ID not set in .env — message @userinfobot on Telegram "
        "to get your numeric ID, add it, and restart."
    )

URL_RE = re.compile(r"https?://\S+")

capture_lock = asyncio.Lock()


def _authorized(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == ALLOWED_USER_ID


def _safe_filename(name: str) -> str:
    """Sanitize an attachment filename, preserving the extension."""
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    illegal = set('<>:"/\\|?*#^[]')
    cleaned = "".join(c for c in stem if c not in illegal and ord(c) >= 0x20)
    cleaned = "-".join(cleaned.split()).strip("-.") or "file"
    return f"{cleaned[:80]}{suffix}"


def _save_failure(url: str, context: str, stage: str, error: str) -> str:
    """Persist a failed capture to skipped.md; return a status suffix for the reply.

    Defensive: if even the skipped.md write fails, tell Nour to resend rather than
    pretend it was saved.
    """
    try:
        inbox.log_failed(url, context, stage, error)
        return " — saved to skipped.md for review"
    except Exception:
        return " — ⚠️ couldn't save it either, please resend"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "👋 Send me a video link and I'll transcribe it into raw/. "
        "Plain text becomes a THOUGHT in the inbox; photos and documents are saved to raw/."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    text = update.message.text or ""
    match = URL_RE.search(text)

    if not match:
        if not text.strip():
            return
        try:
            inbox.log_thought(text)
            await update.message.reply_text("🧠 Saved to inbox as a THOUGHT.")
        except Exception as e:
            await update.message.reply_text(f"❌ Couldn't save that thought — please resend.\n{e}")
        return

    url = match.group(0)
    # Everything Nour sent besides the link travels as context on the inbox line.
    note_context = (text[: match.start()] + text[match.end() :]).strip()

    was_queued = capture_lock.locked()
    if was_queued:
        status = await update.message.reply_text("⏳ Queued — processing your previous link first.")
    else:
        status = await update.message.reply_text("⏳ Processing…")

    async with capture_lock:
        if was_queued:
            try:
                await status.edit_text("⏳ Processing…")
            except Exception:
                pass

        try:
            loop = asyncio.get_running_loop()
            result_path = await loop.run_in_executor(None, capture, url)
            filename = Path(result_path).name
            try:
                inbox.log_video(Path(result_path).stem, url, note_context)
                await status.edit_text(f"✅ Done — saved to raw/{filename} and queued in inbox.")
            except Exception as e:
                # The note was written; only the inbox append failed. Record it so the
                # capture isn't orphaned in raw/ with no queue entry.
                _save_failure(url, note_context, "inbox", f"note saved as {filename} but queueing failed: {e}")
                await status.edit_text(
                    f"⚠️ Saved raw/{filename} but couldn't queue it — logged to skipped.md for review."
                )
        except CaptureError as ce:
            saved = _save_failure(url, note_context, ce.stage, str(ce.original))
            await status.edit_text(f"❌ Failed at {ce.stage}{saved}.\n{ce.original}")
        except Exception as e:
            saved = _save_failure(url, note_context, "unknown", str(e))
            await status.edit_text(f"❌ Failed (unknown stage){saved}.\n{e}")


async def handle_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photos and documents → save binary to raw/assets/.

    Photos are additionally OCR'd into a raw note (cheap, and often screenshots
    full of text). Documents/PDFs are saved as-is with a FILE inbox line — parsing
    big/scanned PDFs is slow and failure-prone, so it's left on-demand.
    """
    if not _authorized(update):
        return
    msg = update.message
    caption = msg.caption or ""
    is_photo = bool(msg.photo)

    try:
        if is_photo:
            tg_file = await msg.photo[-1].get_file()  # largest rendition
            suffix = Path(tg_file.file_path or "").suffix.lower() or ".jpg"
            filename = (
                f"photo-{inbox.now().strftime('%Y%m%d-%H%M%S')}-{tg_file.file_unique_id}{suffix}"
            )
        elif msg.document:
            tg_file = await msg.document.get_file()
            filename = _safe_filename(msg.document.file_name or f"file-{tg_file.file_unique_id}")
        else:
            return

        assets_dir = Path(config.RAW_FOLDER) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = assets_dir / filename
        if dest.exists():
            dest = assets_dir / f"{dest.stem}-{tg_file.file_unique_id}{dest.suffix}"

        await tg_file.download_to_drive(custom_path=dest)
    except Exception as e:
        saved = _save_failure("(attachment)", caption, "attachment", str(e))
        await msg.reply_text(f"❌ Failed to save attachment{saved}.\n{e}")
        return

    # The binary is now safely on disk. From here nothing can lose it — OCR is a
    # best-effort enrichment that falls back to a plain FILE line if it fails.
    if is_photo:
        try:
            loop = asyncio.get_running_loop()
            note_path = await loop.run_in_executor(None, capture_photo, str(dest), caption)
            inbox.log_file(Path(note_path).stem, caption)
            await msg.reply_text(
                f"🖼️ Saved raw/assets/{dest.name}, OCR'd to raw/{Path(note_path).name}, queued in inbox."
            )
        except Exception as e:
            inbox.log_file(dest.name, caption)
            await msg.reply_text(
                f"📎 Saved raw/assets/{dest.name} (OCR skipped: {e}) and queued in inbox."
            )
    else:
        inbox.log_file(dest.name, caption)
        await msg.reply_text(f"📎 Saved to raw/assets/{dest.name} and queued in inbox.")


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_attachment))
    print("Bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
