"""Telegraph (telegra.ph): publish a page.

Docs: https://telegra.ph/api#createPage
The access token comes from a one-off `createAccount` call (see README), not per request.
"""

from typing import Any

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value
from app.utils.text import derive_title

API_URL = "https://api.telegra.ph/createPage"


def build_content(message: str, link: str) -> list[dict[str, Any]]:
    """Telegraph Node array: one paragraph with the link as an <a> element."""
    before, _, after = message.partition(link)
    children: list[Any] = []
    if before:
        children.append(before)
    children.append({"tag": "a", "attrs": {"href": link}, "children": [link]})
    if after:
        children.append(after)
    return [{"tag": "p", "children": children}]


class TelegraphPlatform(BasePlatform):
    name = "Telegraph"
    docs_url = "https://telegra.ph/api#createPage"

    def is_configured(self) -> bool:
        return bool(self.settings.telegraph_access_token)

    def secrets(self) -> list[str]:
        return [secret_value(self.settings.telegraph_access_token)]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        payload: dict[str, Any] = {
            "access_token": secret_value(self.settings.telegraph_access_token),
            "title": derive_title(message, link),
            "content": build_content(message, link),
            "return_content": False,
        }
        if self.settings.telegraph_author_name:
            payload["author_name"] = self.settings.telegraph_author_name
        if self.settings.telegraph_author_url:
            payload["author_url"] = self.settings.telegraph_author_url

        response = await self._request(client, "POST", API_URL, json=payload)
        data = self.json_body(response)
        # Telegraph reports errors with HTTP 200 and {"ok": false, "error": "..."}.
        if not data.get("ok"):
            raise PlatformError(f"Telegraph error: {data.get('error', 'unknown')}")
        url = data.get("result", {}).get("url")
        if not url:
            raise PlatformError("Telegraph response did not include a page URL")
        return PublishOutcome(url, None, True)
