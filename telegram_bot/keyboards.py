"""Inline keyboards and UI menus for the Telegram Bot."""

from __future__ import annotations

from typing import Any, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main interactive menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🎬 Create Video", callback_data="menu:create"),
            InlineKeyboardButton("📋 Topic Batch", callback_data="menu:batch"),
        ],
        [
            InlineKeyboardButton("📊 Job Status", callback_data="menu:status"),
            InlineKeyboardButton("📜 Job History", callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton("⚙️ Video Settings", callback_data="menu:settings"),
            InlineKeyboardButton("❓ Help & Commands", callback_data="menu:help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def language_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting video narration language."""
    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 English", callback_data="set_lang:en"),
            InlineKeyboardButton("🇮🇳 Malayalam (മലയാളം)", callback_data="set_lang:ml"),
        ],
        [
            InlineKeyboardButton("🗣️ Manglish (Malayalam in English script)", callback_data="set_lang:manglish"),
        ],
        [
            InlineKeyboardButton("🇨🇳 Chinese (中文)", callback_data="set_lang:zh"),
            InlineKeyboardButton("🌐 Auto Detect", callback_data="set_lang:auto"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel:wizard"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def aspect_ratio_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting video aspect ratio."""
    keyboard = [
        [
            InlineKeyboardButton("📱 9:16 Vertical (Reels / Shorts / TikTok)", callback_data="set_aspect:9:16"),
        ],
        [
            InlineKeyboardButton("🖥️ 16:9 Landscape (YouTube)", callback_data="set_aspect:16:9"),
        ],
        [
            InlineKeyboardButton("⏹️ 1:1 Square (Instagram Feed)", callback_data="set_aspect:1:1"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel:wizard"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def duration_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting narration length (paragraphs)."""
    keyboard = [
        [
            InlineKeyboardButton("⚡ Quick (~15-30s / 1 §)", callback_data="set_dur:1"),
            InlineKeyboardButton("⏱️ Standard (~30-60s / 2 §)", callback_data="set_dur:2"),
        ],
        [
            InlineKeyboardButton("📖 In-Depth (~60-90s / 3 §)", callback_data="set_dur:3"),
            InlineKeyboardButton("🎞️ Extended (~90-120s / 4 §)", callback_data="set_dur:4"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel:wizard"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def pacing_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting footage pacing (seconds per clip)."""
    keyboard = [
        [
            InlineKeyboardButton("🚀 Fast Cuts (3s / clip)", callback_data="set_clip:3"),
            InlineKeyboardButton("🎯 Balanced (5s / clip)", callback_data="set_clip:5"),
            InlineKeyboardButton("🌊 Relaxed (8s / clip)", callback_data="set_clip:8"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel:wizard"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def confirmation_keyboard() -> InlineKeyboardMarkup:
    """Confirmation before launching video generation."""
    keyboard = [
        [
            InlineKeyboardButton("🚀 Start Generation", callback_data="confirm:start"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel:wizard"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def active_job_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Action buttons attached to a live status message."""
    keyboard = [
        [
            InlineKeyboardButton("🛑 Cancel Job", callback_data=f"cancel_job:{job_id}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def retry_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Options shown when a job fails."""
    keyboard = [
        [
            InlineKeyboardButton("🔄 Retry Job", callback_data=f"retry_job:{job_id}"),
            InlineKeyboardButton("❌ Dismiss", callback_data="dismiss"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def settings_keyboard(settings_data: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Settings menu keyboard showing current values."""
    curr_lang = settings_data.get("language") or "en"
    curr_aspect = settings_data.get("aspect_ratio") or "9:16"
    curr_dur = settings_data.get("duration_paragraphs") or 1
    curr_clip = settings_data.get("clip_duration") or 5

    keyboard = [
        [
            InlineKeyboardButton(f"🌐 Language: {curr_lang}", callback_data="cfg_change:lang"),
            InlineKeyboardButton(f"📐 Format: {curr_aspect}", callback_data="cfg_change:aspect"),
        ],
        [
            InlineKeyboardButton(f"⏱️ Length: {curr_dur} para", callback_data="cfg_change:dur"),
            InlineKeyboardButton(f"⚡ Pacing: {curr_clip}s", callback_data="cfg_change:clip"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="menu:back"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
