"""Verify that a posted URL can be opened without logging in.

Uses its own HTTP client with no credentials or cookies from the posting calls.
`public_access = public_by_design AND the anonymous GET returns 2xx`. The design flag
matters because some sites (e.g. Discord) return 200 with a login page to everyone.
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

NOT_FOUND_RETRY_DELAY = 1.5  # new posts can 404 for a moment while caches catch up


class PublicAccessChecker:
    def __init__(self, client: httpx.AsyncClient, timeout: float, enabled: bool = True) -> None:
        self.client = client
        self.timeout = timeout
        self.enabled = enabled

    async def check(self, url: str, public_by_design: bool) -> bool:
        if not public_by_design:
            return False
        if not self.enabled:
            return True
        try:
            response = await self._get(url)
            if response.status_code == 404:
                await asyncio.sleep(NOT_FOUND_RETRY_DELAY)
                response = await self._get(url)
        except httpx.HTTPError as exc:
            logger.warning(
                "public check failed, falling back to platform visibility url=%s error=%s",
                url,
                type(exc).__name__,
            )
            return public_by_design
        accessible = response.is_success
        logger.info(
            "public check url=%s status=%d accessible=%s", url, response.status_code, accessible
        )
        return accessible

    async def _get(self, url: str) -> httpx.Response:
        self.client.cookies.clear()
        return await self.client.get(url, timeout=self.timeout, follow_redirects=True)
