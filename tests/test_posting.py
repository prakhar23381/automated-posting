"""End-to-end tests of the HTTP API (TestClient), with platform HTTP calls mocked."""

import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

BRIEF_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)
RESULT_KEYS = {"platform", "status", "posted_url", "public_access", "date", "time", "error"}


@pytest.fixture
def api() -> TestClient:
    settings = make_settings(
        telegram_bot_token="123:ABC",
        telegram_channel="@news",
        github_token="ghp_x",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_posting_returns_brief_shape_with_mixed_results(api: TestClient, respx_mock) -> None:
    respx_mock.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(
        200,
        json={
            "ok": True,
            "result": {"message_id": 9, "date": 1795257000, "chat": {"username": "news"}},
        },
    )
    respx_mock.post("https://api.github.com/gists").respond(
        401, json={"message": "Bad credentials"}
    )

    response = api.post("/posting", json={"message": BRIEF_MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert all(set(r) == RESULT_KEYS for r in body["results"])
    by_name = {r["platform"]: r for r in body["results"]}
    assert by_name["Telegram"]["status"] == "success"
    assert by_name["Telegram"]["posted_url"] == "https://t.me/news/9"
    assert by_name["GitHub Gist"]["error"] == "Authentication failed (HTTP 401): Bad credentials"
    assert by_name["Mastodon"]["error"] == "Credentials not configured"
    assert body["summary"] == {"total": 8, "succeeded": 1, "failed": 7}
    assert response.headers["X-Request-ID"]


def test_all_platforms_failing_is_still_200(api: TestClient, respx_mock) -> None:
    telegram = respx_mock.post("https://api.telegram.org/bot123:ABC/sendMessage").respond(500)
    gist = respx_mock.post("https://api.github.com/gists").respond(500)
    response = api.post("/posting", json={"message": BRIEF_MESSAGE})
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert telegram.called and gist.called


@pytest.mark.parametrize(
    ("payload", "error_type", "field"),
    [
        ({"message": "no link at all"}, "link_count", "message"),
        ({"message": "x" * 190 + " https://example.com"}, "message_too_long", "message"),
        ({"message": BRIEF_MESSAGE, "platforms": ["Telegram"]}, "extra_forbidden", "platforms"),
        ({}, "missing", "message"),
        ({"message": 42}, "string_type", "message"),
    ],
)
def test_validation_errors_use_the_error_envelope(api, payload, error_type, field) -> None:
    response = api.post("/posting", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["type"] == error_type
    assert body["error"]["details"][0]["field"] == field


def test_malformed_json(api: TestClient) -> None:
    response = api.post(
        "/posting", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0] == {
        "field": None,
        "message": "Request body is not valid JSON",
        "type": "json_invalid",
    }


def test_unknown_route_uses_error_envelope(api: TestClient) -> None:
    response = api.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_health(api: TestClient) -> None:
    assert api.get("/health").json() == {"status": "ok"}


def test_platforms_lists_configuration(api: TestClient) -> None:
    platforms = {p["platform"]: p["configured"] for p in api.get("/platforms").json()}
    assert platforms["Telegram"] is True
    assert platforms["Mastodon"] is False
    assert len(platforms) == 8


def test_openapi_has_request_example(api: TestClient) -> None:
    schema = api.get("/openapi.json").json()
    examples = schema["components"]["schemas"]["PostRequest"]["examples"]
    assert examples[0]["message"] == BRIEF_MESSAGE


@respx.mock
def test_optional_link_reachability_check() -> None:
    respx.head("https://example.com").respond(404)
    app = create_app(make_settings(verify_link_reachable=True))
    with TestClient(app) as test_client:
        response = test_client.post("/posting", json={"message": BRIEF_MESSAGE})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["type"] == "link_unreachable"
