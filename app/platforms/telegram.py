"""Telegram Bot API: post to a public channel where the bot is an admin.

Docs: https://core.telegram.org/bots/api#sendmessage
"""

from datetime import UTC, datetime

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value

API_BASE = "https://api.telegram.org"


class TelegramPlatform(BasePlatform):
    name = "Telegram"
    docs_url = "https://core.telegram.org/bots/api#sendmessage"

    def is_configured(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_channel)

    def secrets(self) -> list[str]:
        return [secret_value(self.settings.telegram_bot_token)]

    def _chat_id(self) -> str:
        channel = (self.settings.telegram_channel or "").strip()
        if channel.lstrip("-").isdigit() or channel.startswith("@"):
            return channel
        return f"@{channel}"

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        token = secret_value(self.settings.telegram_bot_token)
        response = await self._request(
            client,
            "POST",
            f"{API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": self._chat_id(),
                "text": message,
                "link_preview_options": {"is_disabled": False, "url": link},
            },
        )
        data = self.json_body(response)
        if not data.get("ok"):
            raise PlatformError(f"Telegram error: {data.get('description', 'unknown')}")

        result = data["result"]
        message_id = result["message_id"]
        chat = result.get("chat", {})
        username = chat.get("username")
        created_at = datetime.fromtimestamp(result["date"], UTC) if "date" in result else None

        if username:
            return PublishOutcome(f"https://t.me/{username}/{message_id}", created_at, True)
        # Private channel: only members can open the t.me/c/ link.
        internal_id = str(chat.get("id", "")).removeprefix("-100")
        return PublishOutcome(f"https://t.me/c/{internal_id}/{message_id}", created_at, False)
