"""Application settings, loaded from environment variables (and `.env` when present)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `FOO=` in .env means "not configured"
        extra="ignore",
    )

    # --- Behaviour -------------------------------------------------------
    log_level: str = "INFO"
    platform_timeout: float = 20.0  # total budget per platform, retries included
    http_timeout: float = 10.0  # per HTTP request
    max_retries: int = 2
    max_retry_wait: float = 5.0  # cap for backoff and Retry-After
    report_unconfigured: bool = True  # list platforms without credentials as "failed"
    public_check_enabled: bool = True  # anonymous GET on posted_url after posting
    public_check_timeout: float = 8.0
    verify_link_reachable: bool = False  # optional HEAD on the CTA link before posting

    # --- Telegram (Bot API) ---------------------------------------------
    telegram_bot_token: SecretStr | None = None
    telegram_channel: str | None = None  # public channel username, e.g. @my_channel

    # --- Mastodon --------------------------------------------------------
    mastodon_base_url: str = "https://mastodon.social"
    mastodon_access_token: SecretStr | None = None

    # --- Bluesky (AT Protocol) --------------------------------------------
    bluesky_service: str = "https://bsky.social"
    bluesky_handle: str | None = None
    bluesky_app_password: SecretStr | None = None

    # --- GitHub Gist -------------------------------------------------------
    github_token: SecretStr | None = None

    # --- Telegraph -------------------------------------------------------
    telegraph_access_token: SecretStr | None = None
    telegraph_author_name: str | None = None
    telegraph_author_url: str | None = None

    # --- Dev.to (Forem) ---------------------------------------------------
    devto_api_key: SecretStr | None = None
    devto_tags: str = ""  # comma-separated, max 4

    # --- Hugging Face Hub --------------------------------------------------
    hf_token: SecretStr | None = None
    hf_repo_id: str | None = None  # e.g. username/announcements
    hf_repo_type: Literal["model", "dataset", "space"] = "space"

    # --- Discord (webhook) -------------------------------------------------
    discord_webhook_url: SecretStr | None = None
    discord_guild_id: str | None = None
    discord_server_public: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
