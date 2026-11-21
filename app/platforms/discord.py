"""Discord: post through a channel webhook.

Docs: https://discord.com/developers/docs/resources/webhook#execute-webhook
`?wait=true` makes Discord return the created message so we can build its URL.
"""

from datetime import datetime

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value


class DiscordPlatform(BasePlatform):
    name = "Discord"
    docs_url = "https://discord.com/developers/docs/resources/webhook#execute-webhook"

    def is_configured(self) -> bool:
        return bool(self.settings.discord_webhook_url and self.settings.discord_guild_id)

    def secrets(self) -> list[str]:
        url = secret_value(self.settings.discord_webhook_url)
        token = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
        return [url, token]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        response = await self._request(
            client,
            "POST",
            secret_value(self.settings.discord_webhook_url),
            params={"wait": "true"},
            json={"content": message, "allowed_mentions": {"parse": []}},
        )
        data = self.json_body(response)
        message_id, channel_id = data.get("id"), data.get("channel_id")
        if not message_id or not channel_id:
            raise PlatformError("Discord response did not include message and channel IDs")
        guild_id = data.get("guild_id") or self.settings.discord_guild_id
        created_at = (
            datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            if data.get("timestamp")
            else None
        )
        return PublishOutcome(
            f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
            created_at,
            self.settings.discord_server_public,
        )
