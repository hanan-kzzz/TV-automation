"""Command and callback query handlers for the Telegram Bot."""

from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from telegram_bot.keyboards import (
    aspect_ratio_keyboard,
    confirmation_keyboard,
    duration_keyboard,
    language_keyboard,
    main_menu_keyboard,
    pacing_keyboard,
    settings_keyboard,
)
from telegram_bot.settings import BotSettings
from telegram_bot.storage import Storage

# Session state dictionary for in-progress creation wizards
# user_id -> wizard state
user_wizards: Dict[int, Dict[str, Any]] = {}


def _get_user_id(update: Update) -> Optional[int]:
    if update.effective_user:
        return update.effective_user.id
    return None


async def _check_authorized(update: Update, settings: BotSettings) -> bool:
    """Verify that the sender is authorized to use the bot."""
    user_id = _get_user_id(update)
    if not settings.is_user_authorized(user_id):
        user_str = str(user_id) if user_id else "unknown"
        logger.warning(f"Unauthorized access attempt from user_id: {user_str}")
        msg = (
            "⛔ **Access Denied**\n\n"
            f"Your Telegram User ID is: `{user_str}`\n\n"
            "This bot is restricted to authorized users. To use it, add your User ID "
            "to `TELEGRAM_ALLOWED_USER_IDS` in your `.env` configuration file on the server."
        )
        if update.callback_query:
            await update.callback_query.answer("Unauthorized", show_alert=True)
            if update.effective_message:
                await update.effective_message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        elif update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return False
    return True


# -----------------------------------------------------------------------------
# Command Handlers
# -----------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command. Show welcome message and interactive menu."""
    settings: BotSettings = context.bot_data["settings"]
    if not await _check_authorized(update, settings):
        return

    name = update.effective_user.first_name if update.effective_user else "Creator"
    welcome_text = (
        f"👋 **Welcome, {name}!**\n\n"
        "I am your **AI Video Automation Bot**, powered by **MoneyPrinterTurbo**.\n"
        "Send me a topic and I will generate complete short videos with AI scriptwriting, "
        "narration, HD footage, and subtitles.\n\n"
        "Choose an action below to get started:"
    )

    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command. Explain commands and video generation features."""
    settings: BotSettings = context.bot_data["settings"]
    if not await _check_authorized(update, settings):
        return

    help_text = (
        "📖 **MoneyPrinterTurbo Bot Guide**\n\n"
        "**Available Commands:**\n"
        "• `/create [topic]` — Start interactive video creation\n"
        "• `/batch` — Submit multiple topics for sequential generation\n"
        "• `/status` — View your active video jobs and progress\n"
        "• `/cancel` — Cancel an active or queued job\n"
        "• `/history` — View your recent completed videos\n"
        "• `/settings` — Customize default language, aspect ratio, and pacing\n"
        "• `/schedule` — Check or toggle automated video creation\n"
        "• `/help` — Display this guide\n\n"
        "**Supported Languages & Voices:**\n"
        "• 🇺🇸 **English** (Standard en-US EdgeTTS)\n"
        "• 🇮🇳 **Malayalam** (Official `ml-IN-SobhanaNeural`)\n"
        "• 🗣️ **Manglish** (Malayalam spoken style written in English script)\n"
        "• 🇨🇳 **Chinese** (zh-CN EdgeTTS)\n"
        "• 🌐 **Auto-Detect** (Engine auto-identifies language)\n\n"
        "**Video Formats:**\n"
        "• `9:16` Vertical (1080×1920) for Shorts, Reels & TikTok\n"
        "• `16:9` Landscape (1920×1080) for YouTube\n"
        "• `1:1` Square (1080×1080) for Instagram posts\n\n"
        "⚡ *All jobs are processed asynchronously in the queue.*"
    )

    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /create [optional topic]. Begin video generation workflow."""
    settings: BotSettings = context.bot_data["settings"]
    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    # Check if user provided the topic in the command arguments
    topic_args = " ".join(context.args).strip() if context.args else ""
    if topic_args:
        user_wizards[user_id] = {"topic": topic_args, "step": "language"}
        text = (
            f"🎬 **Topic**: '{topic_args}'\n\n"
            "Step 2: Choose your **narration language**:"
        )
        await update.message.reply_text(
            text, reply_markup=language_keyboard(), parse_mode=ParseMode.MARKDOWN
        )
        return

    user_wizards[user_id] = {"step": "topic"}
    text = (
        "🎬 **Create Video Wizard** (Step 1/5)\n\n"
        "Please reply with your **video topic** or **keywords**.\n"
        "*(e.g., 'The Future of Renewable Energy' or '10 Mind-Blowing Space Facts')*"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /batch command. Prompt for a list of topics."""
    settings: BotSettings = context.bot_data["settings"]
    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    user_wizards[user_id] = {"step": "batch_input"}
    text = (
        "📋 **Sequential Batch Creation**\n\n"
        "Send me a list of video topics, **one topic per line**.\n\n"
        "Example:\n"
        "`How Quantum Computers Work`\n"
        "`The Mysteries of the Mariana Trench`\n"
        "`Top 5 Ancient Wonders`\n\n"
        "Each video will be queued and generated sequentially using your default settings."
    )
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command. Show active and queued jobs for this user."""
    settings: BotSettings = context.bot_data["settings"]
    storage: Storage = context.bot_data["storage"]
    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    active_jobs = storage.get_active_jobs_for_user(user_id)
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if not target:
        return

    if not active_jobs:
        await target.reply_text(
            "📊 **No Active Jobs**\n\nYou currently have no videos queued or generating.",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = ["📊 **Your Active Jobs:**\n"]
    for idx, job in enumerate(active_jobs, 1):
        job_id = job["job_id"][:8]
        topic = job["topic"]
        status = job["status"].capitalize()
        progress = job.get("progress", 0)
        stage = job.get("current_stage") or "Pending"
        lines.append(
            f"**{idx}. {topic}**\n"
            f"   • Status: `{status}` ({progress}%)\n"
            f"   • Stage: {stage}\n"
            f"   • Job ID: `{job_id}`\n"
        )

    lines.append("\nUse `/cancel` if you wish to cancel an active job.")
    await target.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command. Cancel active wizard or running job."""
    settings: BotSettings = context.bot_data["settings"]
    storage: Storage = context.bot_data["storage"]
    job_manager = context.bot_data["job_manager"]
    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    # If in wizard, cancel wizard
    if user_id in user_wizards:
        del user_wizards[user_id]
        if update.message:
            await update.message.reply_text("❌ Creation wizard cancelled.")
        return

    active_jobs = storage.get_active_jobs_for_user(user_id)
    if not active_jobs:
        if update.message:
            await update.message.reply_text("You have no active or queued jobs to cancel.")
        return

    # Cancel the most recent active job
    target_job = active_jobs[0]
    success, msg = await job_manager.cancel_job(target_job["job_id"])
    reply = f"🛑 Job `{target_job['job_id'][:8]}` ('{target_job['topic']}'): {msg}"
    if update.message:
        await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history command. Show completed video jobs for this user."""
    settings: BotSettings = context.bot_data["settings"]
    storage: Storage = context.bot_data["storage"]
    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    history = storage.get_user_jobs(user_id, status="completed", limit=8)
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if not target:
        return

    if not history:
        await target.reply_text(
            "📜 **No History Yet**\n\nYou haven't generated any completed videos yet. Try `/create`!",
            reply_markup=main_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = ["📜 **Your Recent Completed Videos:**\n"]
    for idx, job in enumerate(history, 1):
        topic = job["topic"]
        completed_at = (job.get("completed_at") or "")[:16].replace("T", " ")
        params = job.get("params", {})
        lang = params.get("language", "en")
        aspect = params.get("aspect_ratio", "9:16")
        lines.append(
            f"**{idx}. {topic}**\n"
            f"   • Completed: {completed_at} UTC\n"
            f"   • Settings: `{lang}` | `{aspect}`\n"
        )

    await target.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command. View and adjust preferences."""
    settings: BotSettings = context.bot_data["settings"]
    storage: Storage = context.bot_data["storage"]
    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    user_cfg = storage.get_user_settings(user_id)
    text = (
        "⚙️ **Your Video Generation Preferences**\n\n"
        f"• **Language**: `{user_cfg.get('language') or settings.default_language}`\n"
        f"• **Format / Aspect**: `{user_cfg.get('aspect_ratio') or settings.default_aspect_ratio}`\n"
        f"• **Duration**: `{user_cfg.get('duration_paragraphs') or settings.default_paragraphs} paragraph(s)`\n"
        f"• **Footage Pacing**: `{user_cfg.get('clip_duration') or settings.default_clip_duration}s per cut`\n\n"
        "Click a setting below to customize your default:"
    )

    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(
            text,
            reply_markup=settings_keyboard(user_cfg),
            parse_mode=ParseMode.MARKDOWN,
        )


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /schedule command. Check or toggle automated scheduled creation."""
    settings: BotSettings = context.bot_data["settings"]
    if not await _check_authorized(update, settings):
        return

    status_str = "🟢 **Enabled**" if settings.schedule_enabled else "🔴 **Disabled**"
    interval = settings.schedule_interval_hours
    topics_count = len(settings.schedule_topics)

    text = (
        "⏰ **Automated Scheduled Generation**\n\n"
        f"• **Status**: {status_str}\n"
        f"• **Interval**: Every `{interval} hours`\n"
        f"• **Configured Topics**: `{topics_count}` backlog topic(s)\n"
        f"• **Target Chat ID**: `{settings.schedule_chat_id or 'Not configured'}`\n\n"
        "Scheduled automation is controlled via server environment variables "
        "(`SCHEDULE_ENABLED=true` in `.env`) to guarantee persistent execution."
    )
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# -----------------------------------------------------------------------------
# Text Message Handler (Wizard Step Input)
# -----------------------------------------------------------------------------

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user text responses during interactive wizards."""
    settings: BotSettings = context.bot_data["settings"]
    storage: Storage = context.bot_data["storage"]
    job_manager = context.bot_data["job_manager"]

    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id or user_id not in user_wizards:
        return

    wizard = user_wizards[user_id]
    step = wizard.get("step")
    text = (update.message.text or "").strip() if update.message else ""

    if not text:
        return

    if step == "topic":
        wizard["topic"] = text
        wizard["step"] = "language"
        await update.message.reply_text(
            f"🎬 **Topic**: '{text}'\n\n"
            "Step 2/5: Choose the **narration language**:",
            reply_markup=language_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif step == "batch_input":
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            await update.message.reply_text("Please provide at least one topic.")
            return

        user_cfg = storage.get_user_settings(user_id)
        lang = user_cfg.get("language") or settings.default_language
        aspect = user_cfg.get("aspect_ratio") or settings.default_aspect_ratio
        dur = user_cfg.get("duration_paragraphs") or settings.default_paragraphs
        clip = user_cfg.get("clip_duration") or settings.default_clip_duration

        chat_id = update.effective_chat.id
        del user_wizards[user_id]

        jobs = job_manager.submit_batch(
            user_id=user_id,
            chat_id=chat_id,
            topics=lines,
            language=lang,
            aspect_ratio=aspect,
            duration_paragraphs=dur,
            clip_duration=clip,
        )

        await update.message.reply_text(
            f"✅ **Queued {len(jobs)} video jobs in batch!**\n\n"
            f"Language: `{lang}` | Aspect: `{aspect}` | Pacing: `{clip}s`\n"
            "Each video will be generated sequentially and delivered here.",
            parse_mode=ParseMode.MARKDOWN,
        )


# -----------------------------------------------------------------------------
# Callback Query Handler
# -----------------------------------------------------------------------------

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all inline button callbacks."""
    query = update.callback_query
    if not query:
        return

    settings: BotSettings = context.bot_data["settings"]
    storage: Storage = context.bot_data["storage"]
    job_manager = context.bot_data["job_manager"]

    if not await _check_authorized(update, settings):
        return

    user_id = _get_user_id(update)
    if not user_id:
        return

    data = query.data or ""
    await query.answer()

    # --- Menu navigation ---
    if data == "menu:create":
        await create_command(update, context)
        return
    elif data == "menu:batch":
        await batch_command(update, context)
        return
    elif data == "menu:status":
        await status_command(update, context)
        return
    elif data == "menu:history":
        await history_command(update, context)
        return
    elif data == "menu:settings":
        await settings_command(update, context)
        return
    elif data == "menu:help":
        await help_command(update, context)
        return
    elif data == "menu:back":
        if query.message:
            await query.message.reply_text("Main Menu:", reply_markup=main_menu_keyboard())
        return

    # --- Wizard Cancellation ---
    if data == "cancel:wizard":
        user_wizards.pop(user_id, None)
        if query.message:
            await query.message.edit_text("❌ Video creation cancelled.")
        return

    # --- Wizard: Language Selection ---
    if data.startswith("set_lang:"):
        selected_lang = data.split(":", 1)[1]
        wizard = user_wizards.get(user_id, {})
        wizard["language"] = selected_lang
        wizard["step"] = "aspect"
        user_wizards[user_id] = wizard

        lang_labels = {
            "en": "English 🇺🇸",
            "ml": "Malayalam 🇮🇳",
            "manglish": "Manglish 🗣️",
            "zh": "Chinese 🇨🇳",
            "auto": "Auto Detect 🌐",
        }
        lbl = lang_labels.get(selected_lang, selected_lang)

        if query.message:
            await query.message.edit_text(
                f"🎬 **Topic**: '{wizard.get('topic', 'Untitled')}'\n"
                f"🌐 **Language**: {lbl}\n\n"
                "Step 3/5: Select **Video Format (Aspect Ratio)**:",
                reply_markup=aspect_ratio_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # --- Wizard: Aspect Ratio Selection ---
    if data.startswith("set_aspect:"):
        selected_aspect = data.split(":", 1)[1]
        wizard = user_wizards.get(user_id, {})
        wizard["aspect_ratio"] = selected_aspect
        wizard["step"] = "duration"
        user_wizards[user_id] = wizard

        if query.message:
            await query.message.edit_text(
                f"🎬 **Topic**: '{wizard.get('topic')}'\n"
                f"📐 **Format**: `{selected_aspect}`\n\n"
                "Step 4/5: Select **Narration Length**:",
                reply_markup=duration_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # --- Wizard: Duration Selection ---
    if data.startswith("set_dur:"):
        paragraphs = int(data.split(":", 1)[1])
        wizard = user_wizards.get(user_id, {})
        wizard["duration_paragraphs"] = paragraphs
        wizard["step"] = "pacing"
        user_wizards[user_id] = wizard

        if query.message:
            await query.message.edit_text(
                f"🎬 **Topic**: '{wizard.get('topic')}'\n"
                f"⏱️ **Length**: {paragraphs} paragraph(s)\n\n"
                "Step 5/5: Select **Footage Pacing** (clip change frequency):",
                reply_markup=pacing_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # --- Wizard: Pacing & Summary Confirmation ---
    if data.startswith("set_clip:"):
        clip_sec = int(data.split(":", 1)[1])
        wizard = user_wizards.get(user_id, {})
        wizard["clip_duration"] = clip_sec
        wizard["step"] = "confirmation"
        user_wizards[user_id] = wizard

        topic = wizard.get("topic", "Untitled")
        lang = wizard.get("language", "en")
        aspect = wizard.get("aspect_ratio", "9:16")
        dur = wizard.get("duration_paragraphs", 1)

        summary_text = (
            "📋 **Confirm Video Settings**\n\n"
            f"• 📌 **Topic**: {topic}\n"
            f"• 🌐 **Language**: `{lang}`\n"
            f"• 📐 **Format**: `{aspect}`\n"
            f"• ⏱️ **Length**: `{dur} paragraph(s)`\n"
            f"• ⚡ **Pacing**: `{clip_sec}s per cut`\n\n"
            "Ready to begin rendering?"
        )
        if query.message:
            await query.message.edit_text(
                summary_text,
                reply_markup=confirmation_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    # --- Wizard: Start Generation ---
    if data == "confirm:start":
        wizard = user_wizards.pop(user_id, None)
        if not wizard:
            if query.message:
                await query.message.reply_text("Wizard session expired. Please run `/create` again.")
            return

        chat_id = update.effective_chat.id
        job = job_manager.submit_job(
            user_id=user_id,
            chat_id=chat_id,
            topic=wizard["topic"],
            language=wizard.get("language", "en"),
            aspect_ratio=wizard.get("aspect_ratio", "9:16"),
            duration_paragraphs=wizard.get("duration_paragraphs", 1),
            clip_duration=wizard.get("clip_duration", 5),
        )

        if query.message:
            await query.message.edit_text(
                f"🚀 **Video Job Enqueued!**\n\n"
                f"📌 **Topic**: {wizard['topic']}\n"
                f"🆔 `Job ID`: `{job['job_id']}`\n\n"
                "Your video has been added to the queue and will begin rendering shortly."
            )
        return

    # --- Job Cancel from button ---
    if data.startswith("cancel_job:"):
        target_job_id = data.split(":", 1)[1]
        success, msg = await job_manager.cancel_job(target_job_id)
        if query.message:
            await query.message.reply_text(f"🛑 {msg}")
        return

    # --- Retry Job ---
    if data.startswith("retry_job:"):
        target_job_id = data.split(":", 1)[1]
        orig_job = storage.get_job(target_job_id)
        if not orig_job:
            await query.answer("Original job not found.", show_alert=True)
            return

        params = orig_job.get("params", {})
        chat_id = update.effective_chat.id
        new_job = job_manager.submit_job(
            user_id=user_id,
            chat_id=chat_id,
            topic=orig_job["topic"],
            language=params.get("language", "en"),
            aspect_ratio=params.get("aspect_ratio", "9:16"),
            duration_paragraphs=params.get("duration_paragraphs", 1),
            clip_duration=params.get("clip_duration", 5),
        )
        if query.message:
            await query.message.reply_text(
                f"🔄 **Retrying Job**: '{orig_job['topic']}'\nNew Job ID: `{new_job['job_id'][:8]}...`"
            )
        return

    # --- Dismiss Notification ---
    if data == "dismiss":
        if query.message:
            try:
                await query.message.delete()
            except Exception:
                pass
        return

    # --- Settings changes ---
    if data.startswith("cfg_change:"):
        setting_key = data.split(":", 1)[1]
        user_cfg = storage.get_user_settings(user_id)

        if setting_key == "lang":
            # Cycle through supported languages
            cycle = ["en", "ml", "manglish", "zh", "auto"]
            curr = user_cfg.get("language") or "en"
            nxt = cycle[(cycle.index(curr) + 1) % len(cycle)] if curr in cycle else "en"
            storage.set_user_settings(user_id, language=nxt)

        elif setting_key == "aspect":
            cycle = ["9:16", "16:9", "1:1"]
            curr = user_cfg.get("aspect_ratio") or "9:16"
            nxt = cycle[(cycle.index(curr) + 1) % len(cycle)] if curr in cycle else "9:16"
            storage.set_user_settings(user_id, aspect_ratio=nxt)

        elif setting_key == "dur":
            cycle = [1, 2, 3, 4]
            curr = user_cfg.get("duration_paragraphs") or 1
            nxt = cycle[(cycle.index(curr) + 1) % len(cycle)] if curr in cycle else 1
            storage.set_user_settings(user_id, duration_paragraphs=nxt)

        elif setting_key == "clip":
            cycle = [3, 5, 8]
            curr = user_cfg.get("clip_duration") or 5
            nxt = cycle[(cycle.index(curr) + 1) % len(cycle)] if curr in cycle else 5
            storage.set_user_settings(user_id, clip_duration=nxt)

        # Refresh settings message
        updated_cfg = storage.get_user_settings(user_id)
        if query.message:
            text = (
                "⚙️ **Your Video Generation Preferences (Updated)**\n\n"
                f"• **Language**: `{updated_cfg.get('language') or settings.default_language}`\n"
                f"• **Format / Aspect**: `{updated_cfg.get('aspect_ratio') or settings.default_aspect_ratio}`\n"
                f"• **Duration**: `{updated_cfg.get('duration_paragraphs') or settings.default_paragraphs} paragraph(s)`\n"
                f"• **Footage Pacing**: `{updated_cfg.get('clip_duration') or settings.default_clip_duration}s per cut`\n\n"
                "Click a setting below to customize your default:"
            )
            await query.message.edit_text(
                text,
                reply_markup=settings_keyboard(updated_cfg),
                parse_mode=ParseMode.MARKDOWN,
            )
        return
