"""Main application entry point for the MoneyPrinterTurbo Telegram Bot."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from telegram_bot.handlers import (
    batch_command,
    callback_query_handler,
    cancel_command,
    create_command,
    help_command,
    history_command,
    schedule_command,
    settings_command,
    start_command,
    status_command,
    text_message_handler,
)
from telegram_bot.job_manager import JobManager
from telegram_bot.moneyprinter_client import MoneyPrinterClient
from telegram_bot.settings import BotSettings, mask_secret, settings
from telegram_bot.storage import Storage


async def deduplication_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pre-processing handler to reject duplicate Telegram updates."""
    if not update or not update.update_id:
        return

    storage: Storage = context.bot_data.get("storage")
    if not storage:
        return

    if storage.is_update_processed(update.update_id):
        logger.debug(f"Discarding duplicate update {update.update_id}")
        return

    storage.mark_update_processed(update.update_id)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler that logs exceptions without revealing secrets."""
    error = context.error
    err_str = str(error)

    # Sanitize any accidental secret leakage in logs
    current_settings: BotSettings = context.bot_data.get("settings", settings)
    if current_settings.telegram_bot_token:
        err_str = err_str.replace(current_settings.telegram_bot_token, mask_secret(current_settings.telegram_bot_token))
    if current_settings.moneyprinter_api_key:
        err_str = err_str.replace(current_settings.moneyprinter_api_key, "***")

    logger.error(f"Telegram Bot error: {err_str}")


async def scheduled_generator_loop(app: Application) -> None:
    """Background task that creates videos on a schedule when enabled."""
    bot_settings: BotSettings = app.bot_data["settings"]
    job_manager: JobManager = app.bot_data["job_manager"]

    if not bot_settings.schedule_enabled:
        return

    logger.info(
        f"Scheduled video automation is ENABLED. Interval: {bot_settings.schedule_interval_hours}h, "
        f"Target Chat: {bot_settings.schedule_chat_id}"
    )

    interval_sec = max(60.0, bot_settings.schedule_interval_hours * 3600.0)
    topic_index = 0

    while True:
        try:
            await asyncio.sleep(interval_sec)

            if not bot_settings.schedule_chat_id:
                logger.warning("SCHEDULE_CHAT_ID is not configured. Skipping scheduled run.")
                continue

            if not bot_settings.schedule_topics:
                logger.warning("No SCHEDULE_TOPICS configured. Skipping scheduled run.")
                continue

            topic = bot_settings.schedule_topics[topic_index % len(bot_settings.schedule_topics)]
            topic_index += 1

            logger.info(f"Triggering scheduled video for topic: '{topic}'")
            job_manager.submit_job(
                user_id=bot_settings.schedule_chat_id,
                chat_id=bot_settings.schedule_chat_id,
                topic=topic,
                language=bot_settings.default_language,
                aspect_ratio=bot_settings.default_aspect_ratio,
                duration_paragraphs=bot_settings.default_paragraphs,
                clip_duration=bot_settings.default_clip_duration,
            )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error(f"Error in scheduled generator: {exc}")
            await asyncio.sleep(60.0)


def build_application(bot_settings: BotSettings = settings) -> Application:
    """Construct and configure the python-telegram-bot Application."""
    bot_settings.validate_for_start()

    storage = Storage(bot_settings.storage_dir / "bot.db")
    client = MoneyPrinterClient(bot_settings)
    job_manager = JobManager(settings=bot_settings, storage=storage, client=client)

    app = ApplicationBuilder().token(bot_settings.telegram_bot_token).build()

    # Pass dependencies via bot_data
    app.bot_data["settings"] = bot_settings
    app.bot_data["storage"] = storage
    app.bot_data["client"] = client
    app.bot_data["job_manager"] = job_manager

    # Wire up bot reference in job manager once initialized
    job_manager.set_bot(app.bot)

    # Handlers
    app.add_handler(TypeHandler(Update, deduplication_handler), group=-1)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create", create_command))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("schedule", schedule_command))

    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    app.add_error_handler(error_handler)

    # Post-init hook to start JobManager and Scheduler
    async def post_init(application: Application) -> None:
        await job_manager.start()
        if bot_settings.schedule_enabled:
            asyncio.create_task(scheduled_generator_loop(application))

    async def post_shutdown(application: Application) -> None:
        await job_manager.stop()

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    return app


def run_bot() -> None:
    """Run the Telegram bot polling loop."""
    logger.info("Initializing MoneyPrinterTurbo Telegram Bot...")
    logger.info(f"Connecting to MoneyPrinterTurbo at: {settings.moneyprinter_base_url}")
    logger.info(f"Bot Token: {mask_secret(settings.telegram_bot_token)}")
    if settings.allowed_user_ids == "*":
        logger.warning("TELEGRAM_ALLOWED_USER_IDS is set to '*' (Unrestricted). Anyone can generate videos.")
    else:
        logger.info(f"Authorized User IDs count: {len(settings.allowed_user_ids)}")

    # Check MoneyPrinterTurbo engine connectivity
    try:
        import httpx
        res = httpx.get(f"{settings.moneyprinter_base_url}/ping", timeout=3.0)
        if res.status_code == 200:
            logger.success("MoneyPrinterTurbo engine is online and responsive.")
        else:
            logger.warning(
                f"MoneyPrinterTurbo responded with status {res.status_code}. "
                "Ensure 'python main.py' is running."
            )
    except Exception as exc:
        logger.warning(
            f"Notice: MoneyPrinterTurbo engine at {settings.moneyprinter_base_url} is not responding yet. "
            "Please ensure you run 'python main.py' to start the engine service."
        )

    app = build_application(settings)
    logger.info("Starting bot long-polling...")
    app.run_polling(drop_pending_updates=True)


def main() -> None:
    try:
        run_bot()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot process stopped.")
    except Exception as exc:
        logger.critical(f"Fatal bot crash: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
