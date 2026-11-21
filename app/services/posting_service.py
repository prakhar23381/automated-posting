"""Fan a message out to every platform concurrently and normalise the results."""

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.platforms.base import BasePlatform, PlatformError, PublishOutcome
from app.schemas import PlatformInfo, PlatformResult, PostingResponse, PostingSummary
from app.services.public_check import PublicAccessChecker
from app.utils.text import redact, truncate

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "Credentials not configured"


class PostingService:
    def __init__(
        self,
        platforms: Sequence[BasePlatform],
        client: httpx.AsyncClient,
        public_checker: PublicAccessChecker,
        settings: Settings,
    ) -> None:
        self.platforms = list(platforms)
        self.client = client
        self.public_checker = public_checker
        self.settings = settings

    def describe_platforms(self) -> list[PlatformInfo]:
        return [
            PlatformInfo(platform=p.name, configured=p.is_configured(), docs_url=p.docs_url)
            for p in self.platforms
        ]

    async def post(self, message: str, link: str) -> PostingResponse:
        targets = [
            p for p in self.platforms if self.settings.report_unconfigured or p.is_configured()
        ]
        logger.info(
            "posting started platforms=%d configured=%d",
            len(targets),
            sum(p.is_configured() for p in targets),
        )
        results = await asyncio.gather(*(self._run(p, message, link) for p in targets))
        succeeded = sum(r.status == "success" for r in results)
        response = PostingResponse(
            success=succeeded > 0,
            results=list(results),
            summary=PostingSummary(
                total=len(results), succeeded=succeeded, failed=len(results) - succeeded
            ),
        )
        logger.info(
            "posting finished success=%s succeeded=%d failed=%d",
            response.success,
            succeeded,
            len(results) - succeeded,
        )
        return response

    async def _run(self, platform: BasePlatform, message: str, link: str) -> PlatformResult:
        if not platform.is_configured():
            logger.info("platform=%r skipped reason=not_configured", platform.name)
            return _failed(platform.name, NOT_CONFIGURED)

        started = time.perf_counter()
        try:
            outcome = await asyncio.wait_for(
                platform.publish(self.client, message, link),
                timeout=self.settings.platform_timeout,
            )
        except TimeoutError:
            error = (
                f"Timed out after {self.settings.platform_timeout:g}s "
                "(the post may still have been created)"
            )
        except PlatformError as exc:
            error = exc.message
        except httpx.TimeoutException as exc:
            error = f"Network timeout ({type(exc).__name__})"
        except httpx.HTTPError as exc:
            error = f"Network error ({type(exc).__name__}): {exc}"
        except Exception as exc:  # isolation: one adapter bug must not break the others
            logger.exception("platform=%r unexpected error", platform.name)
            error = f"Unexpected error ({type(exc).__name__}): {exc}"
        else:
            return await self._success(platform, outcome, started)

        error = truncate(redact(error, platform.secrets()))
        logger.warning(
            "platform=%r status=failed duration_ms=%d error=%r",
            platform.name,
            (time.perf_counter() - started) * 1000,
            error,
        )
        return _failed(platform.name, error)

    async def _success(
        self, platform: BasePlatform, outcome: PublishOutcome, started: float
    ) -> PlatformResult:
        public = await self.public_checker.check(outcome.posted_url, outcome.public_by_design)
        stamp = (outcome.created_at or datetime.now(UTC)).astimezone(UTC)
        logger.info(
            "platform=%r status=success duration_ms=%d url=%s public=%s",
            platform.name,
            (time.perf_counter() - started) * 1000,
            outcome.posted_url,
            public,
        )
        return PlatformResult(
            platform=platform.name,
            status="success",
            posted_url=outcome.posted_url,
            public_access=public,
            date=stamp.strftime("%Y-%m-%d"),
            time=stamp.strftime("%H:%M:%S"),
            error=None,
        )


def _failed(name: str, error: str) -> PlatformResult:
    return PlatformResult(
        platform=name,
        status="failed",
        posted_url=None,
        public_access=False,
        date=None,
        time=None,
        error=error,
    )
