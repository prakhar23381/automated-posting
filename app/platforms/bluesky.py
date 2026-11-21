"""Bluesky (AT Protocol): create an app.bsky.feed.post record with a link facet.

Docs:
- https://docs.bsky.app/docs/api/com-atproto-server-create-session
- https://docs.bsky.app/docs/api/com-atproto-repo-create-record
- https://docs.bsky.app/docs/advanced-guides/post-richtext (facets use UTF-8 byte offsets)
"""

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome, secret_value

SESSION_TTL_SECONDS = 30 * 60  # access JWTs last ~2 h; refresh well before that


def build_link_facets(text: str, link: str) -> list[dict[str, Any]]:
    """Return a link facet for `link` inside `text`, using UTF-8 byte offsets."""
    index = text.find(link)
    if index < 0:
        return []
    byte_start = len(text[:index].encode("utf-8"))
    byte_end = byte_start + len(link.encode("utf-8"))
    return [
        {
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
        }
    ]


class BlueskyPlatform(BasePlatform):
    name = "Bluesky"
    docs_url = "https://docs.bsky.app/docs/api/com-atproto-repo-create-record"

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._session: tuple[str, str, str, float] | None = None  # jwt, did, handle, expires

    def is_configured(self) -> bool:
        return bool(self.settings.bluesky_handle and self.settings.bluesky_app_password)

    def secrets(self) -> list[str]:
        secrets = [secret_value(self.settings.bluesky_app_password)]
        if self._session:
            secrets.append(self._session[0])
        return secrets

    def _service(self) -> str:
        return self.settings.bluesky_service.rstrip("/")

    async def _get_session(self, client: httpx.AsyncClient) -> tuple[str, str, str]:
        if self._session and self._session[3] > time.monotonic():
            jwt, did, handle, _ = self._session
            return jwt, did, handle
        response = await self._request(
            client,
            "POST",
            f"{self._service()}/xrpc/com.atproto.server.createSession",
            json={
                "identifier": (self.settings.bluesky_handle or "").strip().lstrip("@"),
                "password": secret_value(self.settings.bluesky_app_password),
            },
        )
        data = self.json_body(response)
        jwt, did, handle = data["accessJwt"], data["did"], data["handle"]
        self._session = (jwt, did, handle, time.monotonic() + SESSION_TTL_SECONDS)
        return jwt, did, handle

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishOutcome:
        jwt, did, handle = await self._get_session(client)
        created_at = datetime.now(UTC)
        record: dict[str, Any] = {
            "$type": "app.bsky.feed.post",
            "text": message,
            "createdAt": created_at.isoformat().replace("+00:00", "Z"),
            "langs": ["en"],
        }
        facets = build_link_facets(message, link)
        if facets:
            record["facets"] = facets

        try:
            response = await self._request(
                client,
                "POST",
                f"{self._service()}/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {jwt}"},
                json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            )
        except PlatformError as exc:
            if exc.status_code in (400, 401):
                self._session = None  # expired or revoked token; next call logs in again
            raise

        uri = self.json_body(response).get("uri", "")
        rkey = uri.rsplit("/", 1)[-1]
        if not rkey:
            raise PlatformError("Bluesky response did not include a record URI")
        return PublishOutcome(f"https://bsky.app/profile/{handle}/post/{rkey}", created_at, True)
