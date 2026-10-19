"""Configuration and environment settings for Telegram Bot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Set

from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int, min_val: int | None = None) -> int:
    if not value:
        return default
    try:
        parsed = int(value.strip())
        if min_val is not None and parsed < min_val:
            return default
        return parsed
    except (ValueError, TypeError):
        return default


def _parse_float(value: str | None, default: float, min_val: float | None = None) -> float:
    if not value:
        return default
    try:
        parsed = float(value.strip())
        if min_val is not None and parsed < min_val:
            return default
        return parsed
    except (ValueError, TypeError):
        return default


def _parse_allowed_user_ids(value: str | None) -> Set[int] | str:
    """Parse comma-separated Telegram User IDs. Returns '*' for unrestricted access, or a set of ints."""
    if not value:
        return set()
    raw = value.strip()
    if raw == "*":
        return "*"
    ids: Set[int] = set()
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned.isdigit():
            ids.add(int(cleaned))
    return ids


def mask_secret(secret: str | None) -> str:
    """Safely mask secret credentials for logging."""
    if not secret:
        return "<not set>"
    if len(secret) <= 8:
        return "***"
    return f"{secret[:4]}...{secret[-4:]}"


class BotSettings:
    """Encapsulates all bot runtime settings."""

    def __init__(self) -> None:
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_user_ids: Set[int] | str = _parse_allowed_user_ids(
            os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        )
        self.moneyprinter_base_url: str = (
            os.getenv("MONEYPRINTER_BASE_URL", "http://127.0.0.1:8080").strip().rstrip("/")
        )
        self.moneyprinter_api_key: str = os.getenv("MONEYPRINTER_API_KEY", "").strip()

        # Video output directory
        raw_output_dir = os.getenv("VIDEO_OUTPUT_DIR", "storage/tasks").strip()
        out_path = Path(raw_output_dir)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        self.video_output_dir: Path = out_path

        # Concurrency & Worker
        self.max_concurrent_jobs: int = _parse_int(
            os.getenv("MAX_CONCURRENT_JOBS", "1"), default=1, min_val=1
        )
        self.job_poll_interval_seconds: float = _parse_float(
            os.getenv("JOB_POLL_INTERVAL_SECONDS", "3.0"), default=3.0, min_val=0.5
        )
        self.job_timeout_seconds: int = _parse_int(
            os.getenv("JOB_TIMEOUT_SECONDS", "1800"), default=1800, min_val=30
        )
        self.max_http_retries: int = _parse_int(
            os.getenv("MAX_HTTP_RETRIES", "3"), default=3, min_val=1
        )

        # Storage directory
        raw_storage_dir = os.getenv("BOT_STORAGE_DIR", "storage/telegram_bot").strip()
        storage_path = Path(raw_storage_dir)
        if not storage_path.is_absolute():
            storage_path = REPO_ROOT / storage_path
        self.storage_dir: Path = storage_path
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Video Defaults
        self.default_language: str = os.getenv("DEFAULT_LANGUAGE", "en").strip()
        self.default_aspect_ratio: str = os.getenv("DEFAULT_ASPECT_RATIO", "9:16").strip()
        self.default_paragraphs: int = _parse_int(
            os.getenv("DEFAULT_PARAGRAPHS", "1"), default=1, min_val=1
        )
        self.default_clip_duration: int = _parse_int(
            os.getenv("DEFAULT_CLIP_DURATION", "5"), default=5, min_val=1
        )
        self.default_voice_name: str = os.getenv("DEFAULT_VOICE_NAME", "").strip()

        # Automation & Scheduling
        self.schedule_enabled: bool = _parse_bool(os.getenv("SCHEDULE_ENABLED", "false"))
        self.schedule_interval_hours: float = _parse_float(
            os.getenv("SCHEDULE_INTERVAL_HOURS", "24.0"), default=24.0, min_val=0.1
        )
        raw_chat_id = os.getenv("SCHEDULE_CHAT_ID", "").strip()
        self.schedule_chat_id: int | None = (
            int(raw_chat_id) if raw_chat_id.lstrip("-").isdigit() else None
        )
        self.schedule_topics: list[str] = [
            t.strip()
            for t in os.getenv("SCHEDULE_TOPICS", "").split(",")
            if t.strip()
        ]

    def is_user_authorized(self, user_id: int | None) -> bool:
        """Check if a given Telegram user ID is authorized to access the bot."""
        if user_id is None:
            return False
        if self.allowed_user_ids == "*":
            return True
        if isinstance(self.allowed_user_ids, set):
            if not self.allowed_user_ids:
                # Disallow all by default if no user IDs configured
                return False
            return user_id in self.allowed_user_ids
        return False

    def validate_for_start(self) -> None:
        """Validate critical settings before starting the bot."""
        if not self.telegram_bot_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is not set. Please obtain a bot token from "
                "@BotFather and configure it in your .env file or environment variables."
            )
        if not self.moneyprinter_base_url:
            raise ValueError(
                "MONEYPRINTER_BASE_URL is invalid or empty. Expected e.g. http://127.0.0.1:8080"
            )


# Global settings instance
settings = BotSettings()
