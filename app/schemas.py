"""Request and response models for the public API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.utils.validators import MAX_MESSAGE_LENGTH, LinkValidationError, extract_cta_link

EXAMPLE_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)


class PostRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # platform selection is internal; no `platforms` field allowed
        json_schema_extra={"examples": [{"message": EXAMPLE_MESSAGE}]},
    )

    message: str = Field(
        ...,
        strict=True,
        description=(
            f"Text to publish. At most {MAX_MESSAGE_LENGTH} characters after trimming, "
            "containing exactly one http(s) CTA link."
        ),
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise PydanticCustomError("message_empty", "Message must not be empty")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise PydanticCustomError(
                "message_too_long",
                "Message must not exceed {max} characters (got {actual})",
                {"max": MAX_MESSAGE_LENGTH, "actual": len(value)},
            )
        try:
            extract_cta_link(value)
        except LinkValidationError as exc:
            raise PydanticCustomError(exc.code, exc.message) from exc
        return value

    @property
    def cta_link(self) -> str:
        return extract_cta_link(self.message)


class PlatformResult(BaseModel):
    platform: str
    status: Literal["success", "failed"]
    posted_url: str | None = None
    public_access: bool = False
    date: str | None = Field(None, description="UTC date, YYYY-MM-DD")
    time: str | None = Field(None, description="UTC time, HH:MM:SS")
    error: str | None = None


class PostingSummary(BaseModel):
    total: int
    succeeded: int
    failed: int


class PostingResponse(BaseModel):
    success: bool = Field(..., description="True when at least one platform succeeded")
    results: list[PlatformResult]
    summary: PostingSummary

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "results": [
                        {
                            "platform": "Mastodon",
                            "status": "success",
                            "posted_url": "https://mastodon.social/@user/113512345678901234",
                            "public_access": True,
                            "date": "2026-11-21",
                            "time": "10:30:00",
                            "error": None,
                        },
                        {
                            "platform": "Dev.to",
                            "status": "failed",
                            "posted_url": None,
                            "public_access": False,
                            "date": None,
                            "time": None,
                            "error": "Authentication failed (HTTP 401): unauthorized",
                        },
                    ],
                    "summary": {"total": 2, "succeeded": 1, "failed": 1},
                }
            ]
        }
    )


class PlatformInfo(BaseModel):
    platform: str
    configured: bool
    docs_url: str


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorBody
