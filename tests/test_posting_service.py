import asyncio
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.platforms.base import BasePlatform, PlatformError, PublishOutcome
from app.services.posting_service import NOT_CONFIGURED, PostingService
from app.services.public_check import PublicAccessChecker
from app.utils.http import request_with_retry
from tests.conftest import make_settings

MESSAGE = "Launch day! https://example.com"
LINK = "https://example.com"


class FakePlatform(BasePlatform):
    docs_url = "https://example.com/docs"

    def __init__(self, name, settings, *, behaviour="ok", configured=True, public=True):
        super().__init__(settings)
        self.name = name
        self.behaviour = behaviour
        self.configured = configured
        self.public = public
        self.calls = 0

    def is_configured(self) -> bool:
        return self.configured

    def secrets(self) -> list[str]:
        return ["sup3r-secret-token"]

    async def publish(self, client, message, link) -> PublishOutcome:
        self.calls += 1
        if self.behaviour == "ok":
            return PublishOutcome(
                f"https://{self.name.lower()}.example/post/1",
                datetime(2026, 11, 21, 10, 30, 0, tzinfo=UTC),
                self.public,
            )
        if self.behaviour == "platform_error":
            raise PlatformError("Authentication failed (HTTP 401): bad token", 401)
        if self.behaviour == "hang":
            await asyncio.sleep(10)
        if self.behaviour == "network":
            raise httpx.ConnectError("connection refused")
        if self.behaviour == "leaky":
            raise RuntimeError("boom with sup3r-secret-token inside")
        raise AssertionError("unknown behaviour")


def make_service(platforms, settings, client, *, public_enabled=False) -> PostingService:
    checker = PublicAccessChecker(client, timeout=1.0, enabled=public_enabled)
    return PostingService(platforms, client, checker, settings)


async def test_all_platforms_succeed(client) -> None:
    settings = make_settings()
    platforms = [FakePlatform(n, settings) for n in ("A", "B", "C")]
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)

    assert response.success is True
    assert response.summary.model_dump() == {"total": 3, "succeeded": 3, "failed": 0}
    first = response.results[0]
    assert first.status == "success"
    assert first.posted_url == "https://a.example/post/1"
    assert (first.date, first.time, first.error) == ("2026-11-21", "10:30:00", None)
    assert first.public_access is True


async def test_one_failure_does_not_stop_the_others(client) -> None:
    settings = make_settings()
    platforms = [
        FakePlatform("A", settings),
        FakePlatform("B", settings, behaviour="platform_error"),
        FakePlatform("C", settings, behaviour="network"),
        FakePlatform("D", settings),
    ]
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)

    assert response.success is True
    assert [r.status for r in response.results] == ["success", "failed", "failed", "success"]
    failed = response.results[1]
    assert failed.error == "Authentication failed (HTTP 401): bad token"
    assert (failed.posted_url, failed.public_access, failed.date, failed.time) == (
        None,
        False,
        None,
        None,
    )
    assert response.results[2].error.startswith("Network error (ConnectError)")


async def test_all_failing_returns_success_false(client) -> None:
    settings = make_settings()
    platforms = [FakePlatform(n, settings, behaviour="platform_error") for n in ("A", "B")]
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)
    assert response.success is False
    assert response.summary.failed == 2


async def test_hanging_platform_times_out_without_blocking_others(client) -> None:
    settings = make_settings(platform_timeout=0.2)
    platforms = [FakePlatform("Slow", settings, behaviour="hang"), FakePlatform("Fast", settings)]
    started = asyncio.get_running_loop().time()
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 1.0
    assert response.results[0].status == "failed"
    assert response.results[0].error.startswith("Timed out after 0.2s")
    assert response.results[1].status == "success"


async def test_platforms_run_concurrently(client) -> None:
    settings = make_settings(platform_timeout=0.3)
    platforms = [FakePlatform(str(i), settings, behaviour="hang") for i in range(5)]
    started = asyncio.get_running_loop().time()
    await make_service(platforms, settings, client).post(MESSAGE, LINK)
    assert asyncio.get_running_loop().time() - started < 1.0  # not 5 x 0.3s


async def test_unexpected_exception_is_isolated_and_secrets_redacted(client) -> None:
    settings = make_settings()
    platforms = [FakePlatform("Leaky", settings, behaviour="leaky"), FakePlatform("B", settings)]
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)
    error = response.results[0].error
    assert "sup3r-secret-token" not in error
    assert "***" in error
    assert response.results[1].status == "success"


async def test_unconfigured_platforms_are_reported(client) -> None:
    settings = make_settings()
    platforms = [FakePlatform("A", settings), FakePlatform("B", settings, configured=False)]
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)
    assert response.results[1].error == NOT_CONFIGURED
    assert platforms[1].calls == 0


async def test_unconfigured_platforms_can_be_hidden(client) -> None:
    settings = make_settings(report_unconfigured=False)
    platforms = [FakePlatform("A", settings), FakePlatform("B", settings, configured=False)]
    response = await make_service(platforms, settings, client).post(MESSAGE, LINK)
    assert [r.platform for r in response.results] == ["A"]


# --- Public access check -------------------------------------------------


@respx.mock
async def test_public_check_true_when_page_loads(client) -> None:
    respx.get("https://a.example/post/1").respond(200, text="<html>post</html>")
    settings = make_settings()
    response = await make_service(
        [FakePlatform("A", settings)], settings, client, public_enabled=True
    ).post(MESSAGE, LINK)
    assert response.results[0].public_access is True


@respx.mock
async def test_public_check_false_when_page_requires_login(client) -> None:
    respx.get("https://a.example/post/1").respond(403)
    settings = make_settings()
    response = await make_service(
        [FakePlatform("A", settings)], settings, client, public_enabled=True
    ).post(MESSAGE, LINK)
    assert response.results[0].public_access is False
    assert response.results[0].status == "success"  # the check never changes status


@respx.mock
async def test_public_check_respects_design_flag(client) -> None:
    route = respx.get("https://a.example/post/1").respond(200)
    settings = make_settings()
    response = await make_service(
        [FakePlatform("A", settings, public=False)], settings, client, public_enabled=True
    ).post(MESSAGE, LINK)
    assert response.results[0].public_access is False
    assert not route.called


@respx.mock
async def test_public_check_falls_back_on_network_error(client) -> None:
    respx.get("https://a.example/post/1").mock(side_effect=httpx.ConnectError("down"))
    checker = PublicAccessChecker(client, timeout=1.0)
    assert await checker.check("https://a.example/post/1", public_by_design=True) is True


@respx.mock
async def test_public_check_retries_once_on_404(client, monkeypatch) -> None:
    monkeypatch.setattr("app.services.public_check.NOT_FOUND_RETRY_DELAY", 0)
    route = respx.get("https://a.example/post/1")
    route.side_effect = [httpx.Response(404), httpx.Response(200)]
    checker = PublicAccessChecker(client, timeout=1.0)
    assert await checker.check("https://a.example/post/1", public_by_design=True) is True
    assert route.call_count == 2


# --- Retry policy ---------------------------------------------------------


@respx.mock
async def test_retry_on_429_then_success(client) -> None:
    route = respx.post("https://api.example/post")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(201)]
    response = await request_with_retry(client, "POST", "https://api.example/post", max_wait=0)
    assert response.status_code == 201
    assert route.call_count == 2


@respx.mock
async def test_no_retry_on_500_for_non_idempotent_post(client) -> None:
    route = respx.post("https://api.example/post").respond(500)
    response = await request_with_retry(client, "POST", "https://api.example/post", max_wait=0)
    assert response.status_code == 500
    assert route.call_count == 1


@respx.mock
async def test_retry_on_500_when_idempotent(client) -> None:
    route = respx.post("https://api.example/post")
    route.side_effect = [httpx.Response(500), httpx.Response(200)]
    response = await request_with_retry(
        client, "POST", "https://api.example/post", idempotent=True, max_wait=0
    )
    assert response.status_code == 200


@respx.mock
async def test_retry_on_connect_error(client) -> None:
    route = respx.post("https://api.example/post")
    route.side_effect = [httpx.ConnectError("refused"), httpx.Response(201)]
    response = await request_with_retry(client, "POST", "https://api.example/post", max_wait=0)
    assert response.status_code == 201


@respx.mock
async def test_no_retry_on_read_timeout_to_avoid_double_post(client) -> None:
    route = respx.post("https://api.example/post").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ReadTimeout):
        await request_with_retry(client, "POST", "https://api.example/post", max_wait=0)
    assert route.call_count == 1


@respx.mock
async def test_retries_are_bounded(client) -> None:
    route = respx.post("https://api.example/post").respond(503)
    response = await request_with_retry(
        client, "POST", "https://api.example/post", retries=2, max_wait=0
    )
    assert response.status_code == 503
    assert route.call_count == 3
