from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from capture import CaptureError, capture

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN or TOKEN.startswith("<"):
    sys.exit("TELEGRAM_BOT_TOKEN not set in .env — add your BotFather token and restart.")

URL_RE = re.compile(r"https?://\S+")

capture_lock = asyncio.Lock()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Send me a video link (YouTube, TikTok, or Instagram) and I'll transcribe it "
        "and save the note to your wiki."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    match = URL_RE.search(text)
    if not match:
        await update.message.reply_text("Send me a video link (YouTube, TikTok, or Instagram).")
        return

    url = match.group(0)

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
            await status.edit_text(f"✅ Done — saved to raw/{filename}")
        except CaptureError as ce:
            await status.edit_text(f"❌ Failed at {ce.stage}\n{ce.original}")
        except Exception as e:
            await status.edit_text(f"❌ Failed (unknown stage)\n{e}")


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
