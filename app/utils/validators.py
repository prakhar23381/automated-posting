"""Message and CTA-link validation helpers.

Rules (also documented in the README):
- A "link candidate" is any `scheme://...` token or a bare `www.` token. Counting every
  scheme (not only http/https) means `ftp://x.com` is reported as an invalid link
  instead of "no link found".
- The single candidate must be an http(s) URL with a host that is either a domain with a
  real TLD or a public IP address.
"""

import ipaddress
import re
from urllib.parse import urlsplit

MAX_MESSAGE_LENGTH = 200

LINK_CANDIDATE_RE = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.\-]*://|\bwww\.)\S+")
TRAILING_PUNCTUATION = ".,;:!?)]}>'\"…"
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")


class LinkValidationError(ValueError):
    """Raised with a user-facing message when the CTA link is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def find_link_candidates(message: str) -> list[str]:
    """Return every link-like token, with trailing sentence punctuation removed."""
    return [m.group(0).rstrip(TRAILING_PUNCTUATION) for m in LINK_CANDIDATE_RE.finditer(message)]


def _validate_host(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if not ip.is_global:
            raise LinkValidationError(
                "url_host_not_public", "CTA link must point to a public host, not a private IP"
            )
        return

    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise LinkValidationError(
            "url_invalid_host", f"CTA link has an invalid host: {host}"
        ) from exc

    labels = ascii_host.rstrip(".").split(".")
    if len(labels) < 2:
        raise LinkValidationError(
            "url_missing_tld", f"CTA link host must include a domain and TLD (got '{host}')"
        )
    if not all(_LABEL_RE.match(label) for label in labels):
        raise LinkValidationError("url_invalid_host", f"CTA link has an invalid host: {host}")
    if not _TLD_RE.match(labels[-1]):
        raise LinkValidationError(
            "url_missing_tld", f"CTA link host has an invalid TLD (got '{labels[-1]}')"
        )


def validate_cta_url(url: str) -> str:
    """Validate one CTA link and return it unchanged if valid."""
    if url.lower().startswith("www."):
        raise LinkValidationError(
            "url_missing_scheme", "CTA link must start with http:// or https://"
        )

    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"}:
        raise LinkValidationError(
            "url_invalid_scheme",
            f"CTA link must use http or https (got '{parts.scheme}')",
        )
    if not parts.hostname:
        raise LinkValidationError("url_missing_host", "CTA link must include a host")
    if parts.username or parts.password:
        raise LinkValidationError(
            "url_has_credentials", "CTA link must not contain a username or password"
        )
    try:
        _ = parts.port  # raises ValueError for an out-of-range or non-numeric port
    except ValueError as exc:
        raise LinkValidationError("url_invalid_port", "CTA link has an invalid port") from exc

    _validate_host(parts.hostname)
    return url


def extract_cta_link(message: str) -> str:
    """Return the single valid CTA link in `message`, or raise LinkValidationError."""
    candidates = find_link_candidates(message)
    if len(candidates) != 1:
        raise LinkValidationError(
            "link_count",
            f"Message must contain exactly one CTA link (found {len(candidates)})",
        )
    return validate_cta_url(candidates[0])
