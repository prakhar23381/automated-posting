"""Dev.to (Forem API v1): publish an article.

Docs: https://developers.forem.com/api/v1#tag/articles/operation/createArticle
"""

from datetime import datetime

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value
from app.utils.text import derive_title

API_URL = "https://dev.to/api/articles"


class DevToPlatform(BasePlatform):
    name = "Dev.to"
    docs_url = "https://developers.forem.com/api/v1#tag/articles/operation/createArticle"

    def is_configured(self) -> bool:
        return bool(self.settings.devto_api_key)

    def secrets(self) -> list[str]:
        return [secret_value(self.settings.devto_api_key)]

    def _tags(self) -> list[str]:
        tags = [t.strip().lower() for t in self.settings.devto_tags.split(",") if t.strip()]
        return tags[:4]  # Forem allows at most 4 tags

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        response = await self._request(
            client,
            "POST",
            API_URL,
            headers={
                "api-key": secret_value(self.settings.devto_api_key),
                "Accept": "application/vnd.forem.api-v1+json",
            },
            json={
                "article": {
                    "title": derive_title(message, link, max_length=100),
                    "body_markdown": message,
                    "published": True,
                    "tags": self._tags(),
                }
            },
        )
        data = self.json_body(response)
        url = data.get("url")
        if not url:
            raise PlatformError("Dev.to response did not include an article URL")
        stamp = (
            data.get("published_timestamp") or data.get("published_at") or data.get("created_at")
        )
        created_at = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        return PublishOutcome(url, created_at, True)
