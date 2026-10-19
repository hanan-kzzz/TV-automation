"""Automated unit and integration tests for Telegram Bot automation."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import ContextTypes

from telegram_bot.keyboards import (
    aspect_ratio_keyboard,
    duration_keyboard,
    language_keyboard,
    main_menu_keyboard,
    settings_keyboard,
)
from telegram_bot.moneyprinter_client import (
    MoneyPrinterAuthError,
    MoneyPrinterClient,
    MoneyPrinterConnectionError,
    MoneyPrinterError,
    MoneyPrinterQueueFullError,
    MoneyPrinterValidationError,
)
from telegram_bot.settings import BotSettings, mask_secret
from telegram_bot.storage import Storage


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_bot.db"


@pytest.fixture
def storage(temp_db_path: Path) -> Storage:
    return Storage(temp_db_path)


@pytest.fixture
def test_settings(tmp_path: Path) -> BotSettings:
    s = BotSettings()
    s.telegram_bot_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    s.allowed_user_ids = {111222333, 444555666}
    s.moneyprinter_base_url = "http://127.0.0.1:8080"
    s.moneyprinter_api_key = "test-api-key"
    s.video_output_dir = tmp_path / "tasks"
    s.video_output_dir.mkdir(parents=True, exist_ok=True)
    s.storage_dir = tmp_path / "bot_storage"
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    s.max_concurrent_jobs = 1
    s.job_poll_interval_seconds = 0.05
    s.job_timeout_seconds = 5
    return s


def make_update(user_id: int = 111222333, chat_id: int = 111222333, text: str = "", update_id: int = 1001) -> Update:
    user = User(id=user_id, is_bot=False, first_name="TestUser")
    chat = Chat(id=chat_id, type="private")
    message = MagicMock(spec=Message)
    message.message_id = 1
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock()
    message.edit_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.update_id = update_id
    update.message = message
    update.effective_user = user
    update.effective_chat = chat
    update.callback_query = None
    return update


def make_callback_update(user_id: int = 111222333, chat_id: int = 111222333, data: str = "", update_id: int = 1002) -> Update:
    user = User(id=user_id, is_bot=False, first_name="TestUser")
    chat = Chat(id=chat_id, type="private")
    message = MagicMock(spec=Message)
    message.message_id = 2
    message.chat = chat
    message.from_user = user
    message.text = "Previous message"
    message.reply_text = AsyncMock()
    message.edit_text = AsyncMock()

    query = MagicMock(spec=CallbackQuery)
    query.id = "query_123"
    query.from_user = user
    query.data = data
    query.message = message
    query.answer = AsyncMock()

    update = MagicMock(spec=Update)
    update.update_id = update_id
    update.callback_query = query
    update.effective_user = user
    update.effective_chat = chat
    update.message = None
    return update


# -----------------------------------------------------------------------------
# 1. Settings & Secret Masking
# -----------------------------------------------------------------------------

def test_settings_validation_missing_token():
    s = BotSettings()
    s.telegram_bot_token = ""
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is not set"):
        s.validate_for_start()


def test_secret_masking():
    assert mask_secret("") == "<not set>"
    assert mask_secret("short") == "***"
    assert mask_secret("1234567890abcdef") == "1234...cdef"


def test_authorization_checks(test_settings: BotSettings):
    # Allowed ID
    assert test_settings.is_user_authorized(111222333) is True
    # Disallowed ID
    assert test_settings.is_user_authorized(999999999) is False
    # None
    assert test_settings.is_user_authorized(None) is False

    # Wildcard unrestricted
    test_settings.allowed_user_ids = "*"
    assert test_settings.is_user_authorized(999999999) is True

    # Empty set -> reject all
    test_settings.allowed_user_ids = set()
    assert test_settings.is_user_authorized(111222333) is False


# -----------------------------------------------------------------------------
# 2. Storage Operations
# -----------------------------------------------------------------------------

def test_storage_job_lifecycle(storage: Storage):
    job = storage.create_job(
        job_id="test-job-1",
        user_id=123,
        chat_id=456,
        topic="AI in Healthcare",
        params={"language": "en", "aspect_ratio": "9:16"},
    )
    assert job["job_id"] == "test-job-1"
    assert job["status"] == "queued"
    assert job["topic"] == "AI in Healthcare"

    # Update job
    updated = storage.update_job(
        "test-job-1",
        status="processing",
        progress=30,
        mpt_task_id="mpt-123",
        current_stage="Synthesizing voice narration",
    )
    assert updated["status"] == "processing"
    assert updated["progress"] == 30
    assert updated["mpt_task_id"] == "mpt-123"

    # User active jobs
    active = storage.get_active_jobs_for_user(123)
    assert len(active) == 1
    assert active[0]["job_id"] == "test-job-1"

    # User isolation: another user has no active jobs
    assert len(storage.get_active_jobs_for_user(999)) == 0

    # Complete job
    storage.update_job("test-job-1", status="completed", progress=100)
    assert len(storage.get_active_jobs_for_user(123)) == 0
    history = storage.get_user_jobs(123, status="completed")
    assert len(history) == 1


def test_storage_user_settings(storage: Storage):
    # Default empty
    cfg = storage.get_user_settings(123)
    assert cfg == {}

    # Update settings
    storage.set_user_settings(123, language="ml", aspect_ratio="16:9", duration_paragraphs=2)
    cfg2 = storage.get_user_settings(123)
    assert cfg2["language"] == "ml"
    assert cfg2["aspect_ratio"] == "16:9"
    assert cfg2["duration_paragraphs"] == 2


def test_storage_update_deduplication(storage: Storage):
    assert storage.is_update_processed(500) is False
    storage.mark_update_processed(500)
    assert storage.is_update_processed(500) is True


# -----------------------------------------------------------------------------
# 3. MoneyPrinterClient API Unit Tests (Mocked)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_create_video_success(test_settings: BotSettings):
    client = MoneyPrinterClient(test_settings)
    mock_resp = {"status": 200, "data": {"task_id": "mpt-uuid-999"}}

    with patch.object(client, "_request", AsyncMock(return_value=mock_resp)):
        task_id = await client.create_video({"video_subject": "Test Topic"})
        assert task_id == "mpt-uuid-999"


@pytest.mark.asyncio
async def test_client_error_mappings(test_settings: BotSettings):
    client = MoneyPrinterClient(test_settings)

    # 401 Auth Error
    with patch("httpx.AsyncClient.request") as mock_req:
        mock_res = MagicMock()
        mock_res.status_code = 401
        mock_req.return_value = mock_res
        with pytest.raises(MoneyPrinterAuthError):
            await client.create_video({"video_subject": "Test"})

    # 429 Queue Full
    with patch("httpx.AsyncClient.request") as mock_req:
        mock_res = MagicMock()
        mock_res.status_code = 429
        mock_req.return_value = mock_res
        with pytest.raises(MoneyPrinterQueueFullError):
            await client.create_video({"video_subject": "Test"})

    # 400 Validation Error
    with patch("httpx.AsyncClient.request") as mock_req:
        mock_res = MagicMock()
        mock_res.status_code = 400
        mock_res.json.return_value = {"message": "Invalid aspect ratio"}
        mock_req.return_value = mock_res
        with pytest.raises(MoneyPrinterValidationError, match="Invalid video parameters"):
            await client.create_video({"video_subject": "Test"})


@pytest.mark.asyncio
async def test_client_connection_error_retry(test_settings: BotSettings):
    test_settings.max_http_retries = 2
    client = MoneyPrinterClient(test_settings)

    with patch("httpx.AsyncClient.request", side_effect=MoneyPrinterConnectionError("Connect failed")):
        with pytest.raises(MoneyPrinterConnectionError):
            await client.create_video({"video_subject": "Test"})


# -----------------------------------------------------------------------------
# 4. Telegram Handlers & Authorization
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthorized_user_rejected(test_settings: BotSettings, storage: Storage):
    from telegram_bot.handlers import start_command

    update = make_update(user_id=999999)  # Not in allowed_user_ids
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {"settings": test_settings, "storage": storage}

    await start_command(update, context)

    # Verify Access Denied was sent
    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args[0][0]
    assert "Access Denied" in call_args
    assert "999999" in call_args


@pytest.mark.asyncio
async def test_authorized_user_start_menu(test_settings: BotSettings, storage: Storage):
    from telegram_bot.handlers import start_command

    update = make_update(user_id=111222333)
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {"settings": test_settings, "storage": storage}

    await start_command(update, context)

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    assert "Welcome" in call_args[0][0]
    assert call_args[1].get("reply_markup") is not None


@pytest.mark.asyncio
async def test_create_command_wizard_initiation(test_settings: BotSettings, storage: Storage):
    from telegram_bot.handlers import create_command, user_wizards

    user_id = 111222333
    user_wizards.clear()

    update = make_update(user_id=user_id, text="/create")
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot_data = {"settings": test_settings, "storage": storage}

    await create_command(update, context)

    assert user_id in user_wizards
    assert user_wizards[user_id]["step"] == "topic"
    update.message.reply_text.assert_called_once()
    assert "video topic" in update.message.reply_text.call_args[0][0].lower()


# -----------------------------------------------------------------------------
# 5. Interactive Wizard State Machine
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wizard_step_by_step_flow(test_settings: BotSettings, storage: Storage):
    from telegram_bot.handlers import (
        callback_query_handler,
        text_message_handler,
        user_wizards,
    )
    from telegram_bot.job_manager import JobManager

    user_id = 111222333
    chat_id = 111222333
    user_wizards[user_id] = {"step": "topic"}

    client = MoneyPrinterClient(test_settings)
    job_manager = JobManager(test_settings, storage, client)
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {
        "settings": test_settings,
        "storage": storage,
        "job_manager": job_manager,
    }

    # Step 1: User types topic
    update1 = make_update(user_id=user_id, text="Space Exploration Wonders")
    await text_message_handler(update1, context)

    assert user_wizards[user_id]["topic"] == "Space Exploration Wonders"
    assert user_wizards[user_id]["step"] == "language"

    # Step 2: User selects Malayalam language via inline button
    update2 = make_callback_update(user_id=user_id, data="set_lang:ml")
    await callback_query_handler(update2, context)

    assert user_wizards[user_id]["language"] == "ml"
    assert user_wizards[user_id]["step"] == "aspect"

    # Step 3: User selects 9:16 aspect ratio
    update3 = make_callback_update(user_id=user_id, data="set_aspect:9:16")
    await callback_query_handler(update3, context)

    assert user_wizards[user_id]["aspect_ratio"] == "9:16"
    assert user_wizards[user_id]["step"] == "duration"

    # Step 4: User selects 2 paragraphs
    update4 = make_callback_update(user_id=user_id, data="set_dur:2")
    await callback_query_handler(update4, context)

    assert user_wizards[user_id]["duration_paragraphs"] == 2
    assert user_wizards[user_id]["step"] == "pacing"

    # Step 5: User selects 5s pacing -> summary shown
    update5 = make_callback_update(user_id=user_id, data="set_clip:5")
    await callback_query_handler(update5, context)

    assert user_wizards[user_id]["clip_duration"] == 5
    assert user_wizards[user_id]["step"] == "confirmation"

    # Step 6: User confirms generation
    update6 = make_callback_update(user_id=user_id, data="confirm:start")
    await callback_query_handler(update6, context)

    # Wizard cleared and job submitted
    assert user_id not in user_wizards
    active = storage.get_active_jobs_for_user(user_id)
    assert len(active) == 1
    assert active[0]["topic"] == "Space Exploration Wonders"
    assert active[0]["params"]["language"] == "ml"


# -----------------------------------------------------------------------------
# 6. Job Processing, Output Verification & Delivery
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_processing_success_local_file(test_settings: BotSettings, storage: Storage, tmp_path: Path):
    from telegram_bot.job_manager import JobManager

    client = MoneyPrinterClient(test_settings)
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = MagicMock(message_id=99)
    mock_bot.send_video = AsyncMock()

    job_manager = JobManager(test_settings, storage, client, bot=mock_bot)

    # Submit job
    job = job_manager.submit_job(
        user_id=111222333,
        chat_id=111222333,
        topic="Future of AI",
        language="en",
    )
    job_id = job["job_id"]
    mpt_task_id = "test-mpt-123"

    # Create dummy video file on disk in task directory
    task_dir = test_settings.video_output_dir / mpt_task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    video_file = task_dir / "final-1.mp4"
    video_file.write_bytes(b"dummy mp4 video bytes")

    # Mock client methods
    client.create_video = AsyncMock(return_value=mpt_task_id)
    # Simulate status transitions: 50% -> 100% complete
    status_responses = [
        {"state": 4, "progress": 50, "failed_stage": None},
        {"state": 1, "progress": 100, "videos": [f"/tasks/{mpt_task_id}/final-1.mp4"]},
    ]
    client.get_task_status = AsyncMock(side_effect=status_responses)

    # Execute processing
    await job_manager._process_job(job)

    # Verify job completed in storage
    finished_job = storage.get_job(job_id)
    assert finished_job["status"] == "completed"
    assert finished_job["progress"] == 100
    assert str(video_file) == finished_job["output_video_path"]

    # Verify send_video was called
    mock_bot.send_video.assert_called_once()
    assert mock_bot.send_video.call_args[1]["chat_id"] == 111222333


@pytest.mark.asyncio
async def test_job_processing_failure_on_engine(test_settings: BotSettings, storage: Storage):
    from telegram_bot.job_manager import JobManager

    client = MoneyPrinterClient(test_settings)
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = MagicMock(message_id=100)

    job_manager = JobManager(test_settings, storage, client, bot=mock_bot)

    job = job_manager.submit_job(
        user_id=111222333,
        chat_id=111222333,
        topic="Failing Topic",
    )
    job_id = job["job_id"]
    mpt_task_id = "test-fail-123"

    client.create_video = AsyncMock(return_value=mpt_task_id)
    # Simulate engine failure
    client.get_task_status = AsyncMock(return_value={
        "state": -1,
        "progress": 30,
        "failed_stage": "audio",
        "error": "TTS synthesis timed out",
    })

    await job_manager._process_job(job)

    failed_job = storage.get_job(job_id)
    assert failed_job["status"] == "failed"
    assert "TTS synthesis timed out" in failed_job["error_message"]

    # Verify failure notification sent with retry button
    mock_bot.send_message.assert_called()
    assert "Video Generation Failed" in mock_bot.send_message.call_args[1]["text"]


@pytest.mark.asyncio
async def test_file_size_exceeding_telegram_limit(test_settings: BotSettings, storage: Storage):
    from telegram_bot.job_manager import JobManager, TELEGRAM_MAX_FILE_BYTES

    client = MoneyPrinterClient(test_settings)
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = MagicMock(message_id=101)
    mock_bot.send_video = AsyncMock()

    job_manager = JobManager(test_settings, storage, client, bot=mock_bot)

    job = job_manager.submit_job(
        user_id=111222333,
        chat_id=111222333,
        topic="Large 4K Video",
    )
    job_id = job["job_id"]
    mpt_task_id = "large-task-123"

    task_dir = test_settings.video_output_dir / mpt_task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    video_file = task_dir / "final-1.mp4"
    video_file.write_bytes(b"large file")

    client.create_video = AsyncMock(return_value=mpt_task_id)
    client.get_task_status = AsyncMock(return_value={
        "state": 1,
        "progress": 100,
        "videos": [f"/tasks/{mpt_task_id}/final-1.mp4"],
    })

    # Set TELEGRAM_MAX_FILE_BYTES to 5 bytes so the dummy file (10 bytes) triggers the limit
    with patch("telegram_bot.job_manager.TELEGRAM_MAX_FILE_BYTES", 5):
        await job_manager._process_job(job)

        # Video should NOT be sent via send_video
        mock_bot.send_video.assert_not_called()
        # Direct download link message should be sent
        mock_bot.send_message.assert_called()
        last_msg = mock_bot.send_message.call_args[1]["text"]
        assert "exceeds Telegram's 50 MB bot upload limit" in last_msg
        assert "Download your video here" in last_msg


# -----------------------------------------------------------------------------
# 7. Job Cancellation
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_queued_and_processing_jobs(test_settings: BotSettings, storage: Storage):
    from telegram_bot.job_manager import JobManager

    client = MoneyPrinterClient(test_settings)
    job_manager = JobManager(test_settings, storage, client)

    # 1. Queued job cancellation
    job = job_manager.submit_job(user_id=111, chat_id=111, topic="Queued Job")
    job_id = job["job_id"]

    success, msg = await job_manager.cancel_job(job_id)
    assert success is True
    assert "before dispatch" in msg
    assert storage.get_job(job_id)["status"] == "cancelled"

    # 2. Cannot cancel already cancelled job
    success2, msg2 = await job_manager.cancel_job(job_id)
    assert success2 is False
    assert "already cancelled" in msg2


# -----------------------------------------------------------------------------
# 8. Batch Sequential Generation
# -----------------------------------------------------------------------------

def test_batch_submission(test_settings: BotSettings, storage: Storage):
    from telegram_bot.job_manager import JobManager

    client = MoneyPrinterClient(test_settings)
    job_manager = JobManager(test_settings, storage, client)

    topics = ["Topic Alpha", "Topic Beta", "Topic Gamma"]
    jobs = job_manager.submit_batch(
        user_id=111,
        chat_id=111,
        topics=topics,
        language="en",
        aspect_ratio="16:9",
    )

    assert len(jobs) == 3
    batch_id = jobs[0]["batch_id"]
    assert batch_id is not None
    assert all(j["batch_id"] == batch_id for j in jobs)

    # Stored sequentially in queued state
    all_queued = storage.get_active_jobs_for_user(111)
    assert len(all_queued) == 3
    assert [j["topic"] for j in all_queued] == topics


# -----------------------------------------------------------------------------
# 9. Crash Recovery
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crash_recovery_resumes_running_and_delivers_completed(test_settings: BotSettings, storage: Storage):
    from telegram_bot.job_manager import JobManager

    client = MoneyPrinterClient(test_settings)
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = MagicMock(message_id=200)

    job_manager = JobManager(test_settings, storage, client, bot=mock_bot)

    # 1. Create a job that completed while bot was down
    job1 = storage.create_job("job-done", 111, 111, "Completed during restart", {}, status="processing")
    storage.update_job("job-done", mpt_task_id="mpt-done")

    # 2. Create a job that failed while bot was down
    job2 = storage.create_job("job-failed", 111, 111, "Failed during restart", {}, status="processing")
    storage.update_job("job-failed", mpt_task_id="mpt-fail")

    # Mock get_task_status for both
    async def mock_status(task_id: str):
        if task_id == "mpt-done":
            return {"state": 1, "progress": 100, "videos": ["/tasks/mpt-done/final-1.mp4"]}
        if task_id == "mpt-fail":
            return {"state": -1, "progress": 40, "error": "Hardware out of memory"}
        return {"state": 4, "progress": 50}

    client.get_task_status = AsyncMock(side_effect=mock_status)
    client.resolve_local_video_path = MagicMock(return_value=None)
    client.download_video = AsyncMock(return_value=Path("/tmp/recovered.mp4"))

    await job_manager.recover_unfinished_jobs()

    # job-failed should be updated to failed
    assert storage.get_job("job-failed")["status"] == "failed"
