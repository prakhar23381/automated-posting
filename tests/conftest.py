from collections.abc import AsyncIterator

import httpx
import pytest

from app.config import Settings


def make_settings(**overrides) -> Settings:
    """Settings that ignore the developer's real .env and environment credentials."""
    base = {
        "max_retries": 2,
        "max_retry_wait": 0.0,
        "platform_timeout": 2.0,
        "public_check_enabled": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_credential_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real credentials in the shell must never leak into tests."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
