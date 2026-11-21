"""Small text helpers shared by adapters and the service."""

import re

from app.utils.validators import TRAILING_PUNCTUATION

DEFAULT_TITLE = "New update"


def derive_title(message: str, link: str, max_length: int = 60) -> str:
    """Build a short title from the message text, without the link.

    Used by platforms that require a title (Telegraph, Dev.to, Hugging Face).
    """
    text = message.replace(link, " ")
    text = re.sub(r"\s+", " ", text).strip().rstrip(TRAILING_PUNCTUATION + " -\u2013\u2014:")
    if not text:
        return DEFAULT_TITLE
    # Prefer the first sentence when it is reasonably short.
    first_sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].rstrip(".!?")
    if 0 < len(first_sentence) <= max_length:
        return first_sentence
    if len(text) <= max_length:
        return text
    # Keep whole words, leaving one character for the ellipsis.
    words, cut = text.split(" "), ""
    for word in words:
        candidate = f"{cut} {word}" if cut else word
        if len(candidate) > max_length - 1:
            break
        cut = candidate
    cut = cut.rstrip(TRAILING_PUNCTUATION + " ")
    return f"{cut or text[: max_length - 1]}…"


def redact(text: str, secrets: list[str]) -> str:
    """Replace every known secret value in `text` with `***`."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
