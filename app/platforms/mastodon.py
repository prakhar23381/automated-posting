"""Mastodon: publish a public status.

Docs: https://docs.joinmastodon.org/methods/statuses/#create
"""

import uuid
from datetime import datetime

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value


class MastodonPlatform(BasePlatform):
    name = "Mastodon"
    docs_url = "https://docs.joinmastodon.org/methods/statuses/#create"

    def is_configured(self) -> bool:
        return bool(self.settings.mastodon_access_token and self.settings.mastodon_base_url)

    def secrets(self) -> list[str]:
        return [secret_value(self.settings.mastodon_access_token)]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        base_url = self.settings.mastodon_base_url.rstrip("/")
        response = await self._request(
            client,
            "POST",
            f"{base_url}/api/v1/statuses",
            # The same key on every retry lets Mastodon drop duplicates, so retries are safe.
            idempotent=True,
            headers={
                "Authorization": f"Bearer {secret_value(self.settings.mastodon_access_token)}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
            data={"status": message, "visibility": "public"},
        )
        data = self.json_body(response)
        url = data.get("url")
        if not url:
            raise PlatformError("Mastodon response did not include a status URL")
        created_at = (
            datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if data.get("created_at")
            else None
        )
        return PublishOutcome(url, created_at, data.get("visibility", "public") == "public")
