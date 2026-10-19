"""HTTP Client for communicating with the MoneyPrinterTurbo API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

import httpx
from loguru import logger

from telegram_bot.settings import BotSettings, mask_secret


class MoneyPrinterError(Exception):
    """Base exception for MoneyPrinterTurbo client errors."""


class MoneyPrinterConnectionError(MoneyPrinterError):
    """Raised when unable to connect to the MoneyPrinterTurbo server."""


class MoneyPrinterTimeoutError(MoneyPrinterError):
    """Raised when an API request times out."""


class MoneyPrinterAuthError(MoneyPrinterError):
    """Raised on HTTP 401 Unauthorized."""


class MoneyPrinterQueueFullError(MoneyPrinterError):
    """Raised on HTTP 429 when the server task queue is full."""


class MoneyPrinterValidationError(MoneyPrinterError):
    """Raised on HTTP 400 Bad Request with field validation details."""


class MoneyPrinterNotFoundError(MoneyPrinterError):
    """Raised on HTTP 404 Not Found."""


class MoneyPrinterClient:
    """Asynchronous client for interacting with MoneyPrinterTurbo REST API."""

    def __init__(self, settings: BotSettings) -> None:
        self.settings = settings
        self.base_url = settings.moneyprinter_base_url.rstrip("/")
        self.api_key = settings.moneyprinter_api_key
        self.video_output_dir = settings.video_output_dir
        self.max_retries = settings.max_http_retries

    def _get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "x-task-id": request_id or str(uuid4()),
            "User-Agent": "MoneyPrinterTurbo-TelegramBot/1.0",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Perform an HTTP request with retries and mapped error responses."""
        url = f"{self.base_url}{path}"
        headers = self._get_headers()

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=json_data,
                    )

                    if response.status_code == 200:
                        return response.json()

                    if response.status_code == 401:
                        raise MoneyPrinterAuthError(
                            "Invalid or missing API key for MoneyPrinterTurbo. "
                            "Please check MONEYPRINTER_API_KEY."
                        )

                    if response.status_code == 404:
                        raise MoneyPrinterNotFoundError(
                            f"Resource at {path} was not found on MoneyPrinterTurbo."
                        )

                    if response.status_code == 429:
                        raise MoneyPrinterQueueFullError(
                            "MoneyPrinterTurbo task queue is full. Please try again later."
                        )

                    if response.status_code == 400:
                        try:
                            err_data = response.json()
                            msg = err_data.get("message") or str(err_data)
                        except Exception:
                            msg = response.text
                        raise MoneyPrinterValidationError(f"Invalid video parameters: {msg}")

                    # Server-side 5xx errors may be retried
                    if response.status_code >= 500:
                        logger.warning(
                            f"MoneyPrinterTurbo server error {response.status_code} "
                            f"on {method} {path} (attempt {attempt}/{self.max_retries})"
                        )
                        if attempt == self.max_retries:
                            response.raise_for_status()
                        await asyncio.sleep(1.0 * attempt)
                        continue

                    response.raise_for_status()
                    return response.json()

            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_exc = exc
                logger.warning(
                    f"Connection failed to {self.base_url} (attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0 * attempt)
            except httpx.ReadTimeout as exc:
                last_exc = exc
                logger.warning(
                    f"Read timeout from {self.base_url} on {path} (attempt {attempt}/{self.max_retries})"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 * attempt)
            except MoneyPrinterError:
                raise
            except Exception as exc:
                last_exc = exc
                logger.error(f"Unexpected error communicating with MoneyPrinterTurbo: {exc}")
                break

        if isinstance(last_exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            raise MoneyPrinterConnectionError(
                f"Cannot connect to MoneyPrinterTurbo at {self.base_url}. "
                "Ensure the server is running (e.g. 'python main.py')."
            ) from last_exc
        if isinstance(last_exc, httpx.ReadTimeout):
            raise MoneyPrinterTimeoutError(
                f"Request to MoneyPrinterTurbo timed out after {timeout}s."
            ) from last_exc

        raise MoneyPrinterError(f"API request failed: {last_exc}")

    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------

    async def check_health(self) -> bool:
        """Check if MoneyPrinterTurbo API is responsive."""
        try:
            url = f"{self.base_url}/ping"
            headers = self._get_headers()
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url, headers=headers)
                return res.status_code in (200, 404, 401)
        except Exception as exc:
            logger.debug(f"Health check failed for {self.base_url}: {exc}")
            return False

    async def create_video(self, params: Dict[str, Any]) -> str:
        """Submit a short-video generation request.

        Calls POST /api/v1/videos.
        Returns the generated task_id.
        """
        response = await self._request("POST", "/api/v1/videos", json_data=params, timeout=30.0)
        data = response.get("data", {})
        task_id = data.get("task_id")
        if not task_id:
            raise MoneyPrinterError(f"No task_id returned from server: {response}")
        return str(task_id)

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Query task status from GET /api/v1/tasks/{task_id}.

        Returns dict containing:
        - state: 1 (complete), 4 (processing), -1 (failed)
        - progress: int (0..100)
        - videos: list of relative or absolute URIs
        - error: optional error string
        - failed_stage: optional failed stage name
        """
        response = await self._request("GET", f"/api/v1/tasks/{task_id}", timeout=15.0)
        return response.get("data", {})

    async def delete_task(self, task_id: str) -> bool:
        """Delete a completed or failed task from the engine.

        Calls DELETE /api/v1/tasks/{task_id}.
        Returns True if deleted, False if still busy or not found.
        """
        try:
            url = f"{self.base_url}/api/v1/tasks/{task_id}"
            headers = self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.delete(url, headers=headers)
                return res.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to delete task {task_id}: {exc}")
            return False

    def resolve_local_video_path(self, task_id: str, video_uri: str) -> Optional[Path]:
        """Attempt to locate the generated video directly in the local task directory.

        This avoids re-downloading over loopback HTTP if the bot runs on the same machine.
        """
        if not self.video_output_dir or not self.video_output_dir.exists():
            return None

        # Clean uri (e.g. "/tasks/<task_id>/final-1.mp4" or "final-1.mp4")
        filename = Path(video_uri).name
        candidates = [
            self.video_output_dir / task_id / filename,
            self.video_output_dir / task_id / "final-1.mp4",
            self.video_output_dir / filename,
        ]

        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate

        return None

    async def download_video(
        self,
        video_uri: str,
        destination_path: Path,
        timeout: float = 300.0,
    ) -> Path:
        """Download video file from MoneyPrinterTurbo to local destination."""
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Build download URL
        if video_uri.startswith(("http://", "https://")):
            url = video_uri
        else:
            clean_path = video_uri.lstrip("/")
            if not clean_path.startswith("tasks/"):
                clean_path = f"tasks/{clean_path}"
            url = f"{self.base_url}/{clean_path}"

        headers = self._get_headers()
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                with open(destination_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        if not destination_path.exists() or destination_path.stat().st_size == 0:
            raise MoneyPrinterError("Downloaded file is empty or does not exist.")

        return destination_path

    def get_public_download_url(self, video_uri: str) -> str:
        """Generate the external direct download URL for the video."""
        if video_uri.startswith(("http://", "https://")):
            return video_uri
        clean_path = video_uri.lstrip("/")
        return f"{self.base_url}/{clean_path}"
