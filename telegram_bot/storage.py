"""Persistent SQLite storage for jobs, user settings, and update deduplication."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """Thread-safe SQLite storage for the Telegram Bot."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Improve concurrency and reliability
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        batch_id TEXT,
                        topic TEXT NOT NULL,
                        params_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        mpt_task_id TEXT,
                        progress INTEGER NOT NULL DEFAULT 0,
                        current_stage TEXT,
                        output_video_path TEXT,
                        error_message TEXT,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs (user_id, status);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, created_at);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs (batch_id);"
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_settings (
                        user_id INTEGER PRIMARY KEY,
                        language TEXT,
                        aspect_ratio TEXT,
                        duration_paragraphs INTEGER,
                        clip_duration INTEGER,
                        voice_name TEXT,
                        updated_at TEXT NOT NULL
                    );
                    """
                )

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS processed_updates (
                        update_id INTEGER PRIMARY KEY,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.commit()

    # -------------------------------------------------------------------------
    # Jobs
    # -------------------------------------------------------------------------

    def create_job(
        self,
        job_id: str,
        user_id: int,
        chat_id: int,
        topic: str,
        params: Dict[str, Any],
        batch_id: Optional[str] = None,
        status: str = "queued",
    ) -> Dict[str, Any]:
        """Create a new job record."""
        now = _utcnow_iso()
        params_str = json.dumps(params, ensure_ascii=False)
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        job_id, user_id, chat_id, batch_id, topic, params_json,
                        status, progress, retry_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?);
                    """,
                    (job_id, user_id, chat_id, batch_id, topic, params_str, status, now, now),
                )
                conn.commit()
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a job by its unique ID."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT * FROM jobs WHERE job_id = ?;", (job_id,))
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                try:
                    data["params"] = json.loads(data["params_json"])
                except Exception:
                    data["params"] = {}
                return data

    def update_job(self, job_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update fields of an existing job."""
        if not kwargs:
            return self.get_job(job_id)

        kwargs["updated_at"] = _utcnow_iso()
        if kwargs.get("status") in {"completed", "failed", "cancelled"} and "completed_at" not in kwargs:
            kwargs["completed_at"] = _utcnow_iso()

        if "params" in kwargs and "params_json" not in kwargs:
            kwargs["params_json"] = json.dumps(kwargs.pop("params"), ensure_ascii=False)

        columns = []
        values = []
        for key, value in kwargs.items():
            columns.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)

        sql = f"UPDATE jobs SET {', '.join(columns)} WHERE job_id = ?;"
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(sql, tuple(values))
                conn.commit()

        return self.get_job(job_id)

    def get_user_jobs(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List recent jobs for a specific user, sorted from newest to oldest."""
        with self._lock:
            with self._get_connection() as conn:
                if status:
                    cursor = conn.execute(
                        """
                        SELECT * FROM jobs
                        WHERE user_id = ? AND status = ?
                        ORDER BY created_at DESC
                        LIMIT ?;
                        """,
                        (user_id, status, limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT * FROM jobs
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?;
                        """,
                        (user_id, limit),
                    )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["params"] = json.loads(item["params_json"])
                    except Exception:
                        item["params"] = {}
                    results.append(item)
                return results

    def get_active_jobs_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Retrieve active (queued, submitting, processing) jobs for a user."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE user_id = ? AND status IN ('queued', 'submitting', 'processing')
                    ORDER BY created_at ASC;
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["params"] = json.loads(item["params_json"])
                    except Exception:
                        item["params"] = {}
                    results.append(item)
                return results

    def get_next_queued_job(self) -> Optional[Dict[str, Any]]:
        """Fetch the oldest queued job in FIFO order."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1;
                    """
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = dict(row)
                try:
                    data["params"] = json.loads(data["params_json"])
                except Exception:
                    data["params"] = {}
                return data

    def count_active_jobs(self) -> int:
        """Count jobs currently submitting or processing on MoneyPrinterTurbo."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM jobs WHERE status IN ('submitting', 'processing');"
                )
                row = cursor.fetchone()
                return int(row["cnt"]) if row else 0

    def get_unfinished_jobs(self) -> List[Dict[str, Any]]:
        """Retrieve all unfinished jobs for crash recovery on bot startup."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status IN ('queued', 'submitting', 'processing')
                    ORDER BY created_at ASC;
                    """
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["params"] = json.loads(item["params_json"])
                    except Exception:
                        item["params"] = {}
                    results.append(item)
                return results

    # -------------------------------------------------------------------------
    # User Settings
    # -------------------------------------------------------------------------

    def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        """Get custom settings for a user. Returns defaults if unset."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM user_settings WHERE user_id = ?;", (user_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return {}
                return dict(row)

    def set_user_settings(
        self,
        user_id: int,
        language: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        duration_paragraphs: Optional[int] = None,
        clip_duration: Optional[int] = None,
        voice_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save or update custom settings for a user."""
        current = self.get_user_settings(user_id)
        now = _utcnow_iso()
        new_lang = language if language is not None else current.get("language")
        new_aspect = aspect_ratio if aspect_ratio is not None else current.get("aspect_ratio")
        new_dur = (
            duration_paragraphs
            if duration_paragraphs is not None
            else current.get("duration_paragraphs")
        )
        new_clip = (
            clip_duration if clip_duration is not None else current.get("clip_duration")
        )
        new_voice = voice_name if voice_name is not None else current.get("voice_name")

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO user_settings (
                        user_id, language, aspect_ratio, duration_paragraphs,
                        clip_duration, voice_name, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        language = excluded.language,
                        aspect_ratio = excluded.aspect_ratio,
                        duration_paragraphs = excluded.duration_paragraphs,
                        clip_duration = excluded.clip_duration,
                        voice_name = excluded.voice_name,
                        updated_at = excluded.updated_at;
                    """,
                    (user_id, new_lang, new_aspect, new_dur, new_clip, new_voice, now),
                )
                conn.commit()

        return self.get_user_settings(user_id)

    # -------------------------------------------------------------------------
    # Deduplication
    # -------------------------------------------------------------------------

    def is_update_processed(self, update_id: int) -> bool:
        """Check if a Telegram update has already been processed."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM processed_updates WHERE update_id = ?;", (update_id,)
                )
                return cursor.fetchone() is not None

    def mark_update_processed(self, update_id: int) -> None:
        """Mark a Telegram update as processed."""
        now = _utcnow_iso()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO processed_updates (update_id, created_at) VALUES (?, ?);",
                    (update_id, now),
                )
                conn.commit()

    def prune_old_updates(self, keep_count: int = 10000) -> None:
        """Prune old processed update IDs to keep table size bounded."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    DELETE FROM processed_updates
                    WHERE update_id NOT IN (
                        SELECT update_id FROM processed_updates
                        ORDER BY update_id DESC
                        LIMIT ?
                    );
                    """,
                    (keep_count,),
                )
                conn.commit()
