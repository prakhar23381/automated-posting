import pytest
from pydantic import ValidationError

from app.schemas import PostRequest
from app.utils.text import derive_title
from app.utils.validators import extract_cta_link, find_link_candidates


def error_type(message) -> str:
    with pytest.raises(ValidationError) as exc_info:
        PostRequest(message=message)
    return exc_info.value.errors()[0]["type"]


def test_brief_example_is_valid() -> None:
    body = PostRequest(
        message="Check out our latest business platform and grow your online visibility. "
        "https://example.com"
    )
    assert body.cta_link == "https://example.com"


def test_exactly_200_characters_is_valid() -> None:
    link = " https://example.com"
    message = "a" * (200 - len(link)) + link
    assert len(message) == 200
    assert PostRequest(message=message).message == message


def test_201_characters_is_rejected() -> None:
    message = "a" * (201 - len(" https://example.com")) + " https://example.com"
    assert error_type(message) == "message_too_long"


def test_length_is_counted_after_trimming() -> None:
    core = "a" * 180 + " https://example.com"
    body = PostRequest(message=f"   {core}      \n")
    assert body.message == core


def test_emoji_counts_as_one_character_each() -> None:
    message = "🚀" * 180 + " https://example.com"
    assert len(message) == 200
    PostRequest(message=message)


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_empty_or_whitespace_is_rejected(message: str) -> None:
    assert error_type(message) == "message_empty"


@pytest.mark.parametrize("message", [123, None, ["https://example.com"], {"a": 1}])
def test_non_string_is_rejected(message) -> None:
    assert error_type(message) == "string_type"


def test_no_link_is_rejected() -> None:
    assert error_type("Hello there, no link here") == "link_count"


def test_two_links_are_rejected() -> None:
    assert error_type("Try https://a.com or https://b.com") == "link_count"


def test_extra_platforms_field_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        PostRequest(message="Hi https://example.com", platforms=["Telegram"])
    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Visit www.example.com", "url_missing_scheme"),
        ("Download ftp://example.com/file", "url_invalid_scheme"),
        ("Local http://localhost:8000", "url_missing_tld"),
        ("No TLD https://example", "url_missing_tld"),
        ("Private http://192.168.1.10/admin", "url_host_not_public"),
        ("Loopback http://127.0.0.1", "url_host_not_public"),
        ("Numeric TLD https://example.123", "url_missing_tld"),
        ("Bad host https://-example.com", "url_invalid_host"),
        ("Creds https://user:pass@example.com", "url_has_credentials"),
        ("Port https://example.com:99999", "url_invalid_port"),
        ("Empty host https:///path", "url_missing_host"),
    ],
)
def test_invalid_links_are_rejected(message: str, expected: str) -> None:
    assert error_type(message) == expected


@pytest.mark.parametrize(
    ("message", "link"),
    [
        ("Read more: https://example.com.", "https://example.com"),
        ("See (https://example.com/path?q=1)!", "https://example.com/path?q=1"),
        ("https://example.com is where to go", "https://example.com"),
        ("Go to http://sub.example.co.uk/a#b", "http://sub.example.co.uk/a#b"),
        ("Public IP http://8.8.8.8/x", "http://8.8.8.8/x"),
        ("IDN https://münchen.de/info", "https://münchen.de/info"),
        ("Upper HTTPS://Example.COM/Path", "HTTPS://Example.COM/Path"),
        ("Port https://example.com:8443/x", "https://example.com:8443/x"),
    ],
)
def test_valid_links_are_extracted(message: str, link: str) -> None:
    assert extract_cta_link(message) == link
    assert PostRequest(message=message).cta_link == link


def test_link_candidates_include_bare_www_and_other_schemes() -> None:
    found = find_link_candidates("a www.x.com b ftp://y.com c https://z.com.")
    assert found == ["www.x.com", "ftp://y.com", "https://z.com"]


@pytest.mark.parametrize(
    ("message", "link", "title"),
    [
        (
            "Check out our latest business platform and grow your online visibility. "
            "https://example.com",
            "https://example.com",
            "Check out our latest business platform and grow your online…",
        ),
        ("Big launch today! https://x.com Join us.", "https://x.com", "Big launch today"),
        ("https://x.com", "https://x.com", "New update"),
    ],
)
def test_derive_title(message: str, link: str, title: str) -> None:
    assert derive_title(message, link) == title
