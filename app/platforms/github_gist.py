"""GitHub Gist: create a public gist containing the message as Markdown.

Docs: https://docs.github.com/en/rest/gists/gists#create-a-gist
"""

from datetime import datetime

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value
from app.utils.text import derive_title

API_URL = "https://api.github.com/gists"


class GitHubGistPlatform(BasePlatform):
    name = "GitHub Gist"
    docs_url = "https://docs.github.com/en/rest/gists/gists#create-a-gist"

    def is_configured(self) -> bool:
        return bool(self.settings.github_token)

    def secrets(self) -> list[str]:
        return [secret_value(self.settings.github_token)]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        title = derive_title(message, link)
        response = await self._request(
            client,
            "POST",
            API_URL,
            headers={
                "Authorization": f"Bearer {secret_value(self.settings.github_token)}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": title,
                "public": True,
                "files": {"post.md": {"content": f"{message}\n"}},
            },
        )
        data = self.json_body(response)
        url = data.get("html_url")
        if not url:
            raise PlatformError("GitHub response did not include html_url")
        created_at = (
            datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if data.get("created_at")
            else None
        )
        return PublishOutcome(url, created_at, bool(data.get("public", True)))
