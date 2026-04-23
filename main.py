import asyncio
import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

import db
from config import TELEGRAM_TOKEN
from handlers import (
    cmd_clear, cmd_delremind, cmd_export, cmd_help, cmd_model,
    cmd_news, cmd_newsoff, cmd_persona, cmd_remind, cmd_reminders,
    cmd_setnews, cmd_start, cmd_status, cmd_summarize, cmd_summaryday,
    cmd_switch, cmd_translate, handle_message, handle_photo, handle_voice,
    schedule_news_job,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    await db.init_db()
    # Restore scheduled news jobs for all subscribers
    subs = await db.get_all_news_subs()
    for sub in subs:
        schedule_news_job(application.job_queue, sub["user_id"], sub["time_str"])
    logger.info(f"Database initialized, restored {len(subs)} news subscriptions")


def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN is not set in .env")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("persona", cmd_persona))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("setnews", cmd_setnews))
    app.add_handler(CommandHandler("newsoff", cmd_newsoff))
    app.add_handler(CommandHandler("translate", cmd_translate))
    app.add_handler(CommandHandler("summarize", cmd_summarize))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("summaryday", cmd_summaryday))
    app.add_handler(CommandHandler("remind", cmd_remind))
    app.add_handler(CommandHandler("reminders", cmd_reminders))
    app.add_handler(CommandHandler("delremind", cmd_delremind))

    # Media & text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Bot starting...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
