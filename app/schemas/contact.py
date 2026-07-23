"""Request/response contracts for the contact endpoint.

Validation happens here rather than in the service layer so that malformed input
is rejected before any business logic runs, and so the rules show up in the
generated OpenAPI schema.
"""

import re
import unicodedata
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.submission import AIStatus, Category, Sentiment

PHONE_ALLOWED = re.compile(r"^[+\d\s\-()]+$")
DIGITS = re.compile(r"\d")


def _strip_control_chars(value: str) -> str:
    """Drop non-printable characters, keeping newlines and tabs.

    Guards against header injection when the value is later interpolated into an
    email, and against invisible padding used to slip past length checks.
    """
    return "".join(
        ch for ch in value if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )


class ContactRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "name": "Ivan Petrov",
                "phone": "+7 999 123-45-67",
                "email": "ivan@example.com",
                "comment": "Hi! I'd like to discuss a backend project for our team.",
            }
        },
    )

    name: str = Field(min_length=2, max_length=100, description="Sender's full name")
    phone: str = Field(min_length=7, max_length=32, description="Contact phone number")
    email: EmailStr = Field(description="Valid email address; the reply copy goes here")
    comment: str = Field(min_length=10, max_length=5000, description="Message body")

    @field_validator("name", "comment")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = _strip_control_chars(value).strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("name")
    @classmethod
    def name_has_letters(cls, value: str) -> str:
        if not any(ch.isalpha() for ch in value):
            raise ValueError("must contain letters")
        return value

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value: str) -> str:
        cleaned = _strip_control_chars(value).strip()
        if not PHONE_ALLOWED.match(cleaned):
            raise ValueError("may only contain digits, spaces and + - ( )")
        digit_count = len(DIGITS.findall(cleaned))
        if not 7 <= digit_count <= 15:
            raise ValueError("must contain between 7 and 15 digits")
        return cleaned


class AIAnalysis(BaseModel):
    """What the AI layer returns; also the shape providers must produce."""

    sentiment: Sentiment = Sentiment.NEUTRAL
    category: Category = Category.OTHER
    suggested_reply: str = ""
    provider: str | None = None
    status: AIStatus = AIStatus.FALLBACK
    error: str | None = None


class ContactAcceptedData(BaseModel):
    submission_id: uuid.UUID
    created_at: datetime
    sentiment: Sentiment | None = None
    category: Category | None = None
    ai_status: AIStatus
    email_sent: bool


class ContactResponse(BaseModel):
    success: bool = True
    # Shown to the visitor by the front-end, so it matches the language of the
    # confirmation email rather than the language of the codebase.
    message: str = "Ваше сообщение получено. Я свяжусь с вами в ближайшее время."
    data: ContactAcceptedData
