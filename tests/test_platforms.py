"""Each adapter against mocked HTTP: correct request out, correct result back."""

import json

import httpx
import pytest
import respx

from app.platforms.base import PlatformError
from app.platforms.bluesky import BlueskyPlatform, build_link_facets
from app.platforms.devto import DevToPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.huggingface import HuggingFacePlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.registry import build_platforms
from app.platforms.telegram import TelegramPlatform
from app.platforms.telegraph import TelegraphPlatform, build_content
from tests.conftest import make_settings

MESSAGE = "Grow your online visibility today. https://example.com"
LINK = "https://example.com"


def sent_json(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


def test_no_platform_is_configured_without_credentials() -> None:
    assert [p.is_configured() for p in build_platforms(make_settings())] == [False] * 8


# --- Telegram ---------------------------------------------------------------


@respx.mock
async def test_telegram_success(client) -> None:
    settings = make_settings(telegram_bot_token="123:ABC", telegram_channel="my_channel")
    route = respx.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(
        200,
        json={
            "ok": True,
            "result": {
                "message_id": 42,
                "date": 1795257000,
                "chat": {"id": -1001234, "username": "my_channel", "type": "channel"},
            },
        },
    )
    outcome = await TelegramPlatform(settings).publish(client, MESSAGE, LINK)

    assert sent_json(route)["chat_id"] == "@my_channel"
    assert sent_json(route)["text"] == MESSAGE
    assert outcome.posted_url == "https://t.me/my_channel/42"
    assert outcome.public_by_design is True
    assert outcome.created_at.year == 2026


@respx.mock
async def test_telegram_private_channel_is_not_public(client) -> None:
    settings = make_settings(telegram_bot_token="123:ABC", telegram_channel="-1001234")
    respx.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(
        200, json={"ok": True, "result": {"message_id": 7, "chat": {"id": -1001234}}}
    )
    outcome = await TelegramPlatform(settings).publish(client, MESSAGE, LINK)
    assert outcome.posted_url == "https://t.me/c/1234/7"
    assert outcome.public_by_design is False


@respx.mock
async def test_telegram_unauthorized(client) -> None:
    settings = make_settings(telegram_bot_token="123:BAD", telegram_channel="@c")
    respx.post("https://api.telegram.org/bot123:BAD/sendMessage").respond(
        401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
    )
    with pytest.raises(PlatformError) as exc_info:
        await TelegramPlatform(settings).publish(client, MESSAGE, LINK)
    assert exc_info.value.message == "Authentication failed (HTTP 401): Unauthorized"


# --- Mastodon ---------------------------------------------------------------


@respx.mock
async def test_mastodon_success(client) -> None:
    settings = make_settings(mastodon_access_token="tok", mastodon_base_url="https://m.social/")
    route = respx.post("https://m.social/api/v1/statuses").respond(
        200,
        json={
            "id": "1",
            "url": "https://m.social/@me/1",
            "created_at": "2026-11-21T10:30:00.000Z",
            "visibility": "public",
        },
    )
    outcome = await MastodonPlatform(settings).publish(client, MESSAGE, LINK)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["Idempotency-Key"]
    assert b"visibility=public" in request.content
    assert outcome.posted_url == "https://m.social/@me/1"
    assert outcome.created_at.isoformat() == "2026-11-21T10:30:00+00:00"


@respx.mock
async def test_mastodon_retries_500_with_same_idempotency_key(client) -> None:
    settings = make_settings(mastodon_access_token="tok", max_retry_wait=0)
    route = respx.post("https://mastodon.social/api/v1/statuses")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json={"url": "https://mastodon.social/@me/2"}),
    ]
    outcome = await MastodonPlatform(settings).publish(client, MESSAGE, LINK)
    keys = {call.request.headers["Idempotency-Key"] for call in route.calls}
    assert outcome.posted_url == "https://mastodon.social/@me/2"
    assert route.call_count == 2 and len(keys) == 1


@respx.mock
async def test_mastodon_invalid_token(client) -> None:
    settings = make_settings(mastodon_access_token="bad")
    respx.post("https://mastodon.social/api/v1/statuses").respond(
        401, json={"error": "The access token is invalid"}
    )
    with pytest.raises(PlatformError, match=r"Authentication failed.*access token is invalid"):
        await MastodonPlatform(settings).publish(client, MESSAGE, LINK)


# --- Bluesky ---------------------------------------------------------------


def test_bluesky_facets_use_utf8_byte_offsets() -> None:
    text = "Café 🚀 launch https://example.com now"
    facet = build_link_facets(text, "https://example.com")[0]
    start, end = facet["index"]["byteStart"], facet["index"]["byteEnd"]
    assert text.encode()[start:end] == b"https://example.com"
    assert start != text.index("https")  # code-point index would be wrong here


@respx.mock
async def test_bluesky_success_and_session_reuse(client) -> None:
    settings = make_settings(bluesky_handle="me.bsky.social", bluesky_app_password="app-pw")
    session = respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        200, json={"accessJwt": "jwt-1", "did": "did:plc:abc", "handle": "me.bsky.social"}
    )
    create = respx.post("https://bsky.social/xrpc/com.atproto.repo.createRecord").respond(
        200, json={"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz", "cid": "c"}
    )
    platform = BlueskyPlatform(settings)
    outcome = await platform.publish(client, MESSAGE, LINK)
    await platform.publish(client, MESSAGE, LINK)

    body = sent_json(create)
    assert create.calls.last.request.headers["Authorization"] == "Bearer jwt-1"
    assert body["repo"] == "did:plc:abc"
    assert body["record"]["text"] == MESSAGE
    assert body["record"]["facets"][0]["features"][0]["uri"] == LINK
    assert outcome.posted_url == "https://bsky.app/profile/me.bsky.social/post/3kxyz"
    assert session.call_count == 1  # cached between posts


@respx.mock
async def test_bluesky_bad_password(client) -> None:
    settings = make_settings(bluesky_handle="me", bluesky_app_password="nope")
    respx.post("https://bsky.social/xrpc/com.atproto.server.createSession").respond(
        401, json={"error": "AuthenticationRequired", "message": "Invalid identifier or password"}
    )
    with pytest.raises(PlatformError, match="Invalid identifier or password"):
        await BlueskyPlatform(settings).publish(client, MESSAGE, LINK)


# --- GitHub Gist -------------------------------------------------------------


@respx.mock
async def test_gist_success(client) -> None:
    settings = make_settings(github_token="ghp_x")
    route = respx.post("https://api.github.com/gists").respond(
        201,
        json={
            "html_url": "https://gist.github.com/me/abc",
            "public": True,
            "created_at": "2026-11-21T10:30:00Z",
        },
    )
    outcome = await GitHubGistPlatform(settings).publish(client, MESSAGE, LINK)
    body = sent_json(route)
    assert body["public"] is True
    assert body["files"]["post.md"]["content"].strip() == MESSAGE
    assert route.calls.last.request.headers["Authorization"] == "Bearer ghp_x"
    assert outcome.posted_url == "https://gist.github.com/me/abc"


@respx.mock
async def test_gist_bad_credentials(client) -> None:
    settings = make_settings(github_token="bad")
    respx.post("https://api.github.com/gists").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(PlatformError, match="Bad credentials"):
        await GitHubGistPlatform(settings).publish(client, MESSAGE, LINK)


# --- Telegraph -------------------------------------------------------------


def test_telegraph_content_wraps_link_in_anchor() -> None:
    assert build_content("Hi https://x.com there", "https://x.com") == [
        {
            "tag": "p",
            "children": [
                "Hi ",
                {"tag": "a", "attrs": {"href": "https://x.com"}, "children": ["https://x.com"]},
                " there",
            ],
        }
    ]


@respx.mock
async def test_telegraph_success(client) -> None:
    settings = make_settings(telegraph_access_token="tg", telegraph_author_name="Me")
    route = respx.post("https://api.telegra.ph/createPage").respond(
        200, json={"ok": True, "result": {"url": "https://telegra.ph/Grow-11-21", "path": "x"}}
    )
    outcome = await TelegraphPlatform(settings).publish(client, MESSAGE, LINK)
    body = sent_json(route)
    assert body["title"] == "Grow your online visibility today"
    assert body["author_name"] == "Me"
    assert outcome.posted_url == "https://telegra.ph/Grow-11-21"


@respx.mock
async def test_telegraph_error_with_http_200(client) -> None:
    settings = make_settings(telegraph_access_token="bad")
    respx.post("https://api.telegra.ph/createPage").respond(
        200, json={"ok": False, "error": "ACCESS_TOKEN_INVALID"}
    )
    with pytest.raises(PlatformError, match="ACCESS_TOKEN_INVALID"):
        await TelegraphPlatform(settings).publish(client, MESSAGE, LINK)


# --- Dev.to ---------------------------------------------------------------


@respx.mock
async def test_devto_success(client) -> None:
    settings = make_settings(devto_api_key="k", devto_tags="news, Startup,a,b,c")
    route = respx.post("https://dev.to/api/articles").respond(
        201,
        json={"url": "https://dev.to/me/grow-1a2b", "published_at": "2026-11-21T10:30:00Z"},
    )
    outcome = await DevToPlatform(settings).publish(client, MESSAGE, LINK)
    article = sent_json(route)["article"]
    assert route.calls.last.request.headers["api-key"] == "k"
    assert article["published"] is True
    assert article["tags"] == ["news", "startup", "a", "b"]
    assert outcome.posted_url == "https://dev.to/me/grow-1a2b"


@respx.mock
async def test_devto_validation_error(client) -> None:
    settings = make_settings(devto_api_key="k")
    respx.post("https://dev.to/api/articles").respond(
        422, json={"error": "Body markdown has already been posted", "status": 422}
    )
    with pytest.raises(PlatformError, match=r"Rejected by platform \(HTTP 422\)"):
        await DevToPlatform(settings).publish(client, MESSAGE, LINK)


# --- Hugging Face -----------------------------------------------------------


@pytest.mark.parametrize(
    ("repo_type", "expected_url"),
    [
        ("space", "https://huggingface.co/spaces/me/news/discussions/3"),
        ("dataset", "https://huggingface.co/datasets/me/news/discussions/3"),
        ("model", "https://huggingface.co/me/news/discussions/3"),
    ],
)
@respx.mock
async def test_huggingface_success(client, repo_type, expected_url) -> None:
    settings = make_settings(hf_token="hf_x", hf_repo_id="me/news", hf_repo_type=repo_type)
    route = respx.post(f"https://huggingface.co/api/{repo_type}s/me/news/discussions").respond(
        200, json={"num": 3}
    )
    outcome = await HuggingFacePlatform(settings).publish(client, MESSAGE, LINK)
    body = sent_json(route)
    assert body["description"] == MESSAGE
    assert body["pullRequest"] is False
    assert outcome.posted_url == expected_url


@respx.mock
async def test_huggingface_forbidden(client) -> None:
    settings = make_settings(hf_token="hf_read_only", hf_repo_id="me/news")
    respx.post("https://huggingface.co/api/spaces/me/news/discussions").respond(
        403, json={"error": "You don't have the rights to create a discussion"}
    )
    with pytest.raises(PlatformError, match=r"Permission denied \(HTTP 403\)"):
        await HuggingFacePlatform(settings).publish(client, MESSAGE, LINK)


# --- Discord ---------------------------------------------------------------

WEBHOOK = "https://discord.com/api/webhooks/111/secret-webhook-token"


@respx.mock
async def test_discord_success(client) -> None:
    settings = make_settings(discord_webhook_url=WEBHOOK, discord_guild_id="999")
    route = respx.post(WEBHOOK, params={"wait": "true"}).respond(
        200, json={"id": "555", "channel_id": "222", "timestamp": "2026-11-21T10:30:00+00:00"}
    )
    platform = DiscordPlatform(settings)
    outcome = await platform.publish(client, MESSAGE, LINK)
    assert sent_json(route)["allowed_mentions"] == {"parse": []}
    assert outcome.posted_url == "https://discord.com/channels/999/222/555"
    assert outcome.public_by_design is False
    assert "secret-webhook-token" in platform.secrets()


@respx.mock
async def test_discord_unknown_webhook(client) -> None:
    settings = make_settings(discord_webhook_url=WEBHOOK, discord_guild_id="999")
    respx.post(WEBHOOK, params={"wait": "true"}).respond(
        404, json={"message": "Unknown Webhook", "code": 10015}
    )
    with pytest.raises(PlatformError, match="Unknown Webhook"):
        await DiscordPlatform(settings).publish(client, MESSAGE, LINK)


# --- Shared error handling ---------------------------------------------------


@respx.mock
async def test_non_json_error_body_is_still_readable(client) -> None:
    settings = make_settings(github_token="x")
    respx.post("https://api.github.com/gists").respond(502, text="Bad Gateway")
    with pytest.raises(PlatformError) as exc_info:
        await GitHubGistPlatform(settings).publish(client, MESSAGE, LINK)
    assert exc_info.value.message == "Server error (HTTP 502): Bad Gateway"
