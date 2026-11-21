"""Shared HTTP helpers: client factory and a retry policy that never double-posts.

Retry rules for a request that creates content (non-idempotent):
- Retry when the request provably never reached the server (connect errors/timeouts).
- Retry on 429 and 503: the server explicitly refused the request.
- Do NOT retry on read timeouts or other 5xx responses: the post may already exist.

Idempotent requests (e.g. Mastodon with an Idempotency-Key, plain GETs) also retry
on those ambiguous cases.
"""

import asyncio
import email.utils
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "automated-posting/1.0 (+https://github.com)"

_SAFE_TRANSPORT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_ALWAYS_RETRY_STATUS = {429, 503}


def create_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed is None:
            return None
        return max(0.0, parsed.timestamp() - time.time())


def _backoff(attempt: int, cap: float) -> float:
    return min(cap, 0.5 * (2**attempt))


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 2,
    idempotent: bool = False,
    max_wait: float = 5.0,
    **kwargs: Any,
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            response = await client.request(method, url, **kwargs)
        except _SAFE_TRANSPORT_ERRORS as exc:
            if attempt >= retries:
                raise
            delay = _backoff(attempt, max_wait)
            reason = type(exc).__name__
        except httpx.TransportError as exc:
            if not idempotent or attempt >= retries:
                raise
            delay = _backoff(attempt, max_wait)
            reason = type(exc).__name__
        else:
            retryable = response.status_code in _ALWAYS_RETRY_STATUS or (
                idempotent and response.status_code >= 500
            )
            if not retryable or attempt >= retries:
                return response
            retry_after = _retry_after_seconds(response)
            delay = (
                min(max_wait, retry_after)
                if retry_after is not None
                else _backoff(attempt, max_wait)
            )
            reason = f"HTTP {response.status_code}"

        attempt += 1
        logger.warning(
            "retrying request host=%s reason=%s attempt=%d delay=%.2fs",
            httpx.URL(url).host,
            reason,
            attempt,
            delay,
        )
        await asyncio.sleep(delay)
