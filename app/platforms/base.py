"""Base class and shared types for platform adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.utils.http import request_with_retry
from app.utils.text import truncate

_STATUS_MESSAGES = {
    400: "Bad request",
    401: "Authentication failed",
    403: "Permission denied",
    404: "Not found",
    409: "Conflict",
    413: "Content too large",
    422: "Rejected by platform",
    429: "Rate limited",
}


@dataclass(frozen=True)
class PublishOutcome:
    posted_url: str
    created_at: datetime | None = None  # timezone-aware; None means "use server clock"
    public_by_design: bool = True


class PlatformError(Exception):
    """A platform rejected the post or returned something unusable."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def secret_value(secret: SecretStr | None) -> str:
    return secret.get_secret_value() if secret else ""


class BasePlatform(ABC):
    name: ClassVar[str]
    docs_url: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def is_configured(self) -> bool:
        """True when every credential this adapter needs is present."""

    @abstractmethod
    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        """Publish `message` and return where it lives. Raise PlatformError on failure."""

    def secrets(self) -> list[str]:
        """Secret values to scrub from error messages and logs."""
        return []

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        idempotent: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        response = await request_with_retry(
            client,
            method,
            url,
            retries=self.settings.max_retries,
            idempotent=idempotent,
            max_wait=self.settings.max_retry_wait,
            **kwargs,
        )
        if response.status_code >= 400:
            raise PlatformError(self.describe_error(response), response.status_code)
        return response

    @staticmethod
    def json_body(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise PlatformError(
                f"Unexpected non-JSON response (HTTP {response.status_code})",
                response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise PlatformError("Unexpected response shape", response.status_code)
        return data

    @staticmethod
    def describe_error(response: httpx.Response) -> str:
        """Turn an error response into a short, readable message."""
        status = response.status_code
        label = _STATUS_MESSAGES.get(status, "Server error" if status >= 500 else "Request failed")
        detail = ""
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key in ("description", "message", "error_description", "error", "errors", "detail"):
                value = data.get(key)
                if value:
                    detail = value if isinstance(value, str) else str(value)
                    break
        elif response.text and len(response.text) < 200:
            detail = response.text.strip()
        message = f"{label} (HTTP {status})"
        return truncate(f"{message}: {detail}" if detail else message)
