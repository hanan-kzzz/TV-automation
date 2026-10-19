"""Asynchronous Job and Queue Manager for video generation tasks."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from loguru import logger
from telegram import Bot
from telegram.error import TelegramError

from telegram_bot.keyboards import active_job_keyboard, retry_keyboard
from telegram_bot.moneyprinter_client import (
    MoneyPrinterClient,
    MoneyPrinterConnectionError,
    MoneyPrinterError,
    MoneyPrinterQueueFullError,
)
from telegram_bot.settings import BotSettings
from telegram_bot.storage import Storage

# Telegram bot API file upload limit is 50 MiB
TELEGRAM_MAX_FILE_BYTES = 50 * 1024 * 1024


class JobManager:
    """Coordinates queuing, MoneyPrinterTurbo submission, status polling, and delivery."""

    def __init__(
        self,
        settings: BotSettings,
        storage: Storage,
        client: MoneyPrinterClient,
        bot: Optional[Bot] = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.client = client
        self.bot = bot

        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._cancelled_jobs: set[str] = set()
        self._status_messages: Dict[str, Dict[str, Any]] = {}
        self._worker_running = False
        self._worker_task: Optional[asyncio.Task] = None

    def set_bot(self, bot: Bot) -> None:
        """Bind Telegram bot instance for messaging and delivery."""
        self.bot = bot

    async def start(self) -> None:
        """Start the background worker and recover unfinished jobs."""
        if self._worker_running:
            return
        self._worker_running = True
        logger.info("Starting Telegram Bot JobManager worker...")
        await self.recover_unfinished_jobs()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Gracefully stop background worker and active polling tasks."""
        self._worker_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        for task in self._running_tasks.values():
            task.cancel()

    # -------------------------------------------------------------------------
    # Job Submission & Queue
    # -------------------------------------------------------------------------

    def submit_job(
        self,
        user_id: int,
        chat_id: int,
        topic: str,
        language: str = "en",
        aspect_ratio: str = "9:16",
        duration_paragraphs: int = 1,
        clip_duration: int = 5,
        voice_name: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enqueue a new video task."""
        job_id = str(uuid4())
        params = {
            "topic": topic,
            "language": language,
            "aspect_ratio": aspect_ratio,
            "duration_paragraphs": duration_paragraphs,
            "clip_duration": clip_duration,
            "voice_name": voice_name or "",
        }

        job = self.storage.create_job(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            topic=topic,
            params=params,
            batch_id=batch_id,
            status="queued",
        )
        logger.info(f"Job {job_id} enqueued for user {user_id}: '{topic}'")
        return job

    def submit_batch(
        self,
        user_id: int,
        chat_id: int,
        topics: list[str],
        language: str = "en",
        aspect_ratio: str = "9:16",
        duration_paragraphs: int = 1,
        clip_duration: int = 5,
        voice_name: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """Enqueue multiple video tasks sequentially in a batch."""
        batch_id = f"batch_{int(time.time())}_{uuid4().hex[:6]}"
        jobs = []
        for topic in topics:
            cleaned = topic.strip()
            if not cleaned:
                continue
            job = self.submit_job(
                user_id=user_id,
                chat_id=chat_id,
                topic=cleaned,
                language=language,
                aspect_ratio=aspect_ratio,
                duration_paragraphs=duration_paragraphs,
                clip_duration=clip_duration,
                voice_name=voice_name,
                batch_id=batch_id,
            )
            jobs.append(job)
        return jobs

    async def cancel_job(self, job_id: str) -> tuple[bool, str]:
        """Cancel an active or queued job."""
        job = self.storage.get_job(job_id)
        if not job:
            return False, "Job not found."

        current_status = job.get("status")
        if current_status in {"completed", "failed", "cancelled"}:
            return False, f"Job is already {current_status}."

        self._cancelled_jobs.add(job_id)

        # Cancel running task if any
        running_task = self._running_tasks.get(job_id)
        if running_task and not running_task.done():
            running_task.cancel()

        self.storage.update_job(job_id, status="cancelled", error_message="Cancelled by user")

        mpt_task_id = job.get("mpt_task_id")
        if mpt_task_id:
            # Attempt to clean up on the engine if it is not busy
            asyncio.create_task(self.client.delete_task(mpt_task_id))

        msg = (
            "Job cancelled before dispatch."
            if current_status == "queued"
            else "Job detached and cancelled from bot tracking."
        )
        logger.info(f"Job {job_id} cancelled. {msg}")
        return True, msg

    # -------------------------------------------------------------------------
    # Worker Loop
    # -------------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        """Background loop that picks queued jobs and processes them up to concurrency limit."""
        while self._worker_running:
            try:
                job = self.storage.get_next_queued_job()
                if not job:
                    await asyncio.sleep(1.0)
                    continue

                job_id = job["job_id"]
                if job_id in self._cancelled_jobs:
                    self._cancelled_jobs.discard(job_id)
                    continue

                # Acquire concurrency slot
                await self._semaphore.acquire()

                task = asyncio.create_task(self._process_job_wrapper(job))
                self._running_tasks[job_id] = task

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in JobManager worker loop: {exc}")
                await asyncio.sleep(2.0)

    async def _process_job_wrapper(self, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        try:
            await self._process_job(job)
        except asyncio.CancelledError:
            logger.info(f"Job task {job_id} cancelled.")
        except Exception as exc:
            logger.exception(f"Unhandled failure in job {job_id}: {exc}")
            self.storage.update_job(job_id, status="failed", error_message=str(exc))
            await self._notify_failure(job, f"Unexpected error: {exc}")
        finally:
            self._running_tasks.pop(job_id, None)
            self._cancelled_jobs.discard(job_id)
            self._semaphore.release()

    # -------------------------------------------------------------------------
    # Pipeline Execution
    # -------------------------------------------------------------------------

    def _build_mpt_request_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Translate high-level bot preferences into MoneyPrinterTurbo TaskVideoRequest schema."""
        topic = params.get("topic", "")
        lang = (params.get("language") or "en").lower()
        aspect = params.get("aspect_ratio") or "9:16"
        paragraphs = int(params.get("duration_paragraphs", 1))
        clip_duration = int(params.get("clip_duration", 5))
        custom_voice = params.get("voice_name") or ""

        # Map language and voices
        # Edge TTS provides high-quality free voices
        if custom_voice:
            voice_name = custom_voice
            video_language = lang
            script_prompt = ""
        elif lang in {"ml", "malayalam"}:
            video_language = "ml"
            voice_name = "ml-IN-SobhanaNeural"  # Official Malayalam EdgeTTS voice
            script_prompt = ""
        elif lang == "manglish":
            # Malayalam colloquial script written in English alphabet
            video_language = "en"
            voice_name = "en-IN-NeerjaNeural"
            script_prompt = (
                "Write the narration in Manglish (Malayalam language spoken casually, "
                "written strictly using the English alphabet). Keep it punchy and engaging."
            )
        elif lang in {"zh", "chinese"}:
            video_language = "zh"
            voice_name = "zh-CN-XiaoxiaoNeural-Female"
            script_prompt = ""
        elif lang in {"auto", ""}:
            video_language = ""
            voice_name = ""
            script_prompt = ""
        else:
            # Default English
            video_language = "en"
            voice_name = "en-US-JennyNeural"
            script_prompt = ""

        payload = {
            "video_subject": topic,
            "video_aspect": aspect,
            "video_clip_duration": clip_duration,
            "paragraph_number": max(1, min(10, paragraphs)),
            "video_count": 1,
            "subtitle_enabled": True,
            "video_source": "pexels",
            "bgm_type": "random",
            "bgm_volume": 0.2,
        }

        if video_language:
            payload["video_language"] = video_language
        if voice_name:
            payload["voice_name"] = voice_name
        if script_prompt:
            payload["video_script_prompt"] = script_prompt

        return payload

    async def _process_job(self, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        chat_id = job["chat_id"]
        topic = job["topic"]
        params = job.get("params", {})

        if job_id in self._cancelled_jobs:
            self.storage.update_job(job_id, status="cancelled", error_message="Cancelled before dispatch")
            return

        # 1. Update status to submitting
        self.storage.update_job(job_id, status="submitting", current_stage="Submitting to engine")
        await self._send_or_update_status(
            job_id, chat_id, f"🎬 **Job Queued**: '{topic}'\n⏳ Contacting MoneyPrinterTurbo engine..."
        )

        # 2. Build payload and call MoneyPrinterTurbo API
        mpt_payload = self._build_mpt_request_params(params)
        try:
            mpt_task_id = await self.client.create_video(mpt_payload)
        except MoneyPrinterQueueFullError as exc:
            logger.warning(f"Engine queue is full for job {job_id}: {exc}")
            self.storage.update_job(job_id, status="failed", error_message=str(exc))
            await self._notify_failure(job, "MoneyPrinterTurbo task queue is full. Please try again in a few moments.")
            return
        except MoneyPrinterConnectionError as exc:
            logger.error(f"Cannot connect to MoneyPrinterTurbo for job {job_id}: {exc}")
            self.storage.update_job(job_id, status="failed", error_message=str(exc))
            await self._notify_failure(job, "Could not connect to MoneyPrinterTurbo. Please ensure the engine is running.")
            return
        except Exception as exc:
            logger.exception(f"Failed to submit job {job_id} to engine: {exc}")
            self.storage.update_job(job_id, status="failed", error_message=str(exc))
            await self._notify_failure(job, f"Submission error: {exc}")
            return

        # 3. Update storage with engine task_id
        self.storage.update_job(
            job_id,
            mpt_task_id=mpt_task_id,
            status="processing",
            progress=5,
            current_stage="preflight",
        )
        logger.info(f"Job {job_id} accepted by engine with task_id: {mpt_task_id}")

        # 4. Asynchronous polling loop
        start_time = time.time()
        timeout = self.settings.job_timeout_seconds
        last_progress = 5
        last_stage_desc = "Initializing"

        while True:
            if job_id in self._cancelled_jobs:
                logger.info(f"Job {job_id} cancelled during processing.")
                self.storage.update_job(job_id, status="cancelled", error_message="Cancelled by user")
                await self._send_or_update_status(
                    job_id, chat_id, f"🛑 **Job Cancelled**: '{topic}'\nTask was stopped."
                )
                return

            if time.time() - start_time > timeout:
                err_msg = f"Job timed out after {timeout} seconds."
                logger.error(f"Job {job_id} timed out.")
                self.storage.update_job(job_id, status="failed", error_message=err_msg)
                await self._notify_failure(job, err_msg)
                return

            await asyncio.sleep(self.settings.job_poll_interval_seconds)

            try:
                task_data = await self.client.get_task_status(mpt_task_id)
            except Exception as poll_exc:
                logger.warning(f"Polling error for job {job_id} (will retry): {poll_exc}")
                continue

            state = task_data.get("state", 4)
            progress = int(task_data.get("progress", last_progress))
            failed_stage = task_data.get("failed_stage")
            engine_error = task_data.get("error")

            # Map progress percentage and stages honestly
            stage_desc = self._get_stage_description(progress, failed_stage)
            if progress != last_progress or stage_desc != last_stage_desc:
                last_progress = progress
                last_stage_desc = stage_desc
                self.storage.update_job(
                    job_id, progress=progress, current_stage=stage_desc
                )
                await self._send_or_update_status(
                    job_id,
                    chat_id,
                    f"🎬 **Generating Video**: '{topic}'\n"
                    f"⚙️ **Stage**: {stage_desc}\n"
                    f"📊 **Progress**: {progress}%\n"
                    f"🆔 `Job ID`: `{job_id[:8]}...`",
                )

            # Check termination states:
            # -1: Failed
            if state == -1:
                err_detail = engine_error or f"Stage '{failed_stage}' failed"
                logger.warning(f"Job {job_id} failed on engine: {err_detail}")
                self.storage.update_job(
                    job_id,
                    status="failed",
                    error_message=err_detail,
                    current_stage=failed_stage or "failed",
                )
                await self._notify_failure(job, f"Engine error ({failed_stage or 'unknown'}): {err_detail}")
                return

            # 1: Completed
            if state == 1:
                videos = task_data.get("videos") or []
                if not videos:
                    logger.error(f"Job {job_id} reported complete but videos list is empty.")
                    self.storage.update_job(
                        job_id, status="failed", error_message="Engine returned empty video list."
                    )
                    await self._notify_failure(job, "Engine completed but returned no output video.")
                    return

                video_uri = videos[0]
                logger.info(f"Job {job_id} completed on engine. Video URI: {video_uri}")
                await self._handle_completion(job, mpt_task_id, video_uri)
                return

    def _get_stage_description(self, progress: int, failed_stage: Optional[str] = None) -> str:
        """Map percentage to verified MoneyPrinterTurbo pipeline stages."""
        if failed_stage:
            return f"Failed at {failed_stage}"
        if progress < 10:
            return "Validating parameters & preflight"
        elif progress < 20:
            return "Writing video script with AI"
        elif progress < 30:
            return "Extracting visual search terms"
        elif progress < 40:
            return "Synthesizing voice narration"
        elif progress < 50:
            return "Generating & aligning subtitles"
        elif progress < 75:
            return "Fetching HD video materials"
        elif progress < 100:
            return "Rendering & mixing final video"
        else:
            return "Finalizing video"

    # -------------------------------------------------------------------------
    # Delivery & Notifications
    # -------------------------------------------------------------------------

    async def _handle_completion(self, job: Dict[str, Any], mpt_task_id: str, video_uri: str) -> None:
        """Retrieve the output video, verify it, and deliver to the user."""
        job_id = job["job_id"]
        chat_id = job["chat_id"]
        topic = job["topic"]

        await self._send_or_update_status(
            job_id, chat_id, f"🎬 **Finishing**: '{topic}'\n📦 Preparing video delivery..."
        )

        # 1. Check local file on disk first
        local_path = self.client.resolve_local_video_path(mpt_task_id, video_uri)

        # 2. If not found locally, download via API
        if not local_path or not local_path.is_file():
            cache_dir = self.settings.storage_dir / "cache"
            target_path = cache_dir / f"{job_id}.mp4"
            try:
                local_path = await self.client.download_video(video_uri, target_path)
            except Exception as dl_exc:
                logger.error(f"Failed to download video for job {job_id}: {dl_exc}")
                public_url = self.client.get_public_download_url(video_uri)
                self.storage.update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    output_video_path=public_url,
                )
                await self._send_message(
                    chat_id,
                    f"✅ **Video Ready!**\n\n"
                    f"📌 **Topic**: {topic}\n"
                    f"⚠️ Download via bot failed, but you can retrieve it directly:\n"
                    f"🔗 [Direct Download Link]({public_url})",
                )
                return

        # 3. Verify file exists and is accessible
        if not local_path.exists() or local_path.stat().st_size == 0:
            err_msg = "Output video file does not exist or is 0 bytes."
            logger.error(f"Job {job_id} verification failed: {err_msg}")
            self.storage.update_job(job_id, status="failed", error_message=err_msg)
            await self._notify_failure(job, err_msg)
            return

        file_size_bytes = local_path.stat().st_size
        file_size_mb = file_size_bytes / (1024 * 1024)
        logger.info(f"Verified video file for job {job_id}: {local_path} ({file_size_mb:.2f} MB)")

        self.storage.update_job(
            job_id,
            status="completed",
            progress=100,
            output_video_path=str(local_path),
        )

        caption = f"🎬 **{topic}**\n\n✅ Generated with MoneyPrinterTurbo\n📦 Size: {file_size_mb:.1f} MB"

        # 4. Check Telegram upload limit (50 MB)
        if file_size_bytes > TELEGRAM_MAX_FILE_BYTES:
            public_url = self.client.get_public_download_url(video_uri)
            await self._send_message(
                chat_id,
                f"✅ **Video Generated Successfully!**\n\n"
                f"📌 **Topic**: {topic}\n"
                f"📦 **Size**: {file_size_mb:.1f} MB\n\n"
                f"⚠️ *The video exceeds Telegram's 50 MB bot upload limit.*\n"
                f"🔗 **Download your video here:**\n{public_url}",
            )
            return

        # 5. Send as Telegram Video
        if not self.bot:
            logger.warning(f"Bot instance not set, cannot send video directly for {job_id}")
            return

        try:
            with open(local_path, "rb") as video_file:
                await self.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=120.0,
                    write_timeout=120.0,
                )
            logger.success(f"Video for job {job_id} successfully delivered to chat {chat_id}")
        except TelegramError as tg_exc:
            logger.warning(f"send_video failed ({tg_exc}), falling back to send_document...")
            try:
                with open(local_path, "rb") as video_file:
                    await self.bot.send_document(
                        chat_id=chat_id,
                        document=video_file,
                        caption=caption,
                        filename=f"video_{job_id[:8]}.mp4",
                        read_timeout=120.0,
                        write_timeout=120.0,
                    )
                logger.success(f"Video for job {job_id} delivered as document")
            except Exception as doc_exc:
                logger.error(f"Failed to deliver video file via Telegram: {doc_exc}")
                public_url = self.client.get_public_download_url(video_uri)
                await self._send_message(
                    chat_id,
                    f"✅ **Video Generated!**\n\n"
                    f"📌 **Topic**: {topic}\n"
                    f"⚠️ Telegram delivery timed out. You can download the video directly:\n"
                    f"🔗 [Direct Download Link]({public_url})",
                )

    async def _notify_failure(self, job: Dict[str, Any], reason: str) -> None:
        """Inform the user of a failed job and provide a retry button."""
        job_id = job["job_id"]
        chat_id = job["chat_id"]
        topic = job["topic"]

        text = (
            f"❌ **Video Generation Failed**\n\n"
            f"📌 **Topic**: {topic}\n"
            f"⚠️ **Reason**: {reason}\n"
            f"🆔 `Job ID`: `{job_id}`\n\n"
            f"Would you like to retry?"
        )
        if self.bot:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=retry_keyboard(job_id),
                )
            except Exception as exc:
                logger.error(f"Failed to send failure notification: {exc}")

    async def _send_or_update_status(self, job_id: str, chat_id: int, text: str) -> None:
        """Update live status message, throttling edits to respect Telegram rate limits."""
        if not self.bot:
            return

        now = time.time()
        info = self._status_messages.get(job_id)
        if info:
            msg_id = info["message_id"]
            last_edit = info.get("last_edit", 0)
            # Throttle edits to at least 3 seconds apart
            if now - last_edit < 3.0:
                return
            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    reply_markup=active_job_keyboard(job_id),
                )
                info["last_edit"] = now
                return
            except Exception as exc:
                # If message is not modified or edit fails, create new or ignore
                pass

        try:
            sent_msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=active_job_keyboard(job_id),
            )
            self._status_messages[job_id] = {
                "message_id": sent_msg.message_id,
                "last_edit": now,
            }
        except Exception as exc:
            logger.debug(f"Failed to send status message for {job_id}: {exc}")

    async def _send_message(self, chat_id: int, text: str) -> None:
        if self.bot:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                logger.error(f"Failed to send message to {chat_id}: {exc}")

    # -------------------------------------------------------------------------
    # Crash Recovery
    # -------------------------------------------------------------------------

    async def recover_unfinished_jobs(self) -> None:
        """Scan SQLite for jobs interrupted by a restart and re-check their status."""
        unfinished = self.storage.get_unfinished_jobs()
        if not unfinished:
            return

        logger.info(f"Recovering {len(unfinished)} unfinished job(s) from previous session...")
        for job in unfinished:
            job_id = job["job_id"]
            mpt_task_id = job.get("mpt_task_id")
            status = job.get("status")

            if status == "queued":
                logger.info(f"Job {job_id} remains queued and will be picked up by worker.")
                continue

            if not mpt_task_id:
                # Never made it to engine; re-queue
                self.storage.update_job(job_id, status="queued")
                continue

            try:
                task_data = await self.client.get_task_status(mpt_task_id)
                state = task_data.get("state", 4)
                if state == 1:
                    # Completed during restart
                    videos = task_data.get("videos") or []
                    if videos:
                        logger.info(f"Job {job_id} finished during restart. Delivering now...")
                        asyncio.create_task(self._handle_completion(job, mpt_task_id, videos[0]))
                    else:
                        self.storage.update_job(job_id, status="failed", error_message="Empty video output")
                elif state == -1:
                    err = task_data.get("error") or "Failed on engine during restart"
                    self.storage.update_job(job_id, status="failed", error_message=err)
                else:
                    # Still processing on engine; re-attach polling
                    logger.info(f"Job {job_id} is still processing on engine. Resuming monitor...")
                    task = asyncio.create_task(self._process_job_wrapper(job))
                    self._running_tasks[job_id] = task
            except Exception as exc:
                logger.warning(f"Could not recover status for job {job_id}: {exc}")
