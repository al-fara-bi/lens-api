"""Contract tests for POST /api/contact."""

import pytest
from httpx import AsyncClient


async def test_valid_submission_is_accepted(client: AsyncClient, valid_payload: dict) -> None:
    response = await client.post("/api/contact", json=valid_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True

    data = body["data"]
    assert data["submission_id"]
    assert data["ai_status"] in {"ok", "fallback"}
    # Timestamps must carry an offset, or clients silently read UTC as local time.
    assert data["created_at"].endswith("Z") or "+" in data["created_at"]


async def test_response_carries_request_id_header(
    client: AsyncClient, valid_payload: dict
) -> None:
    response = await client.post("/api/contact", json=valid_payload)
    assert response.headers.get("X-Request-ID")


async def test_submission_survives_unavailable_ai(
    client: AsyncClient, valid_payload: dict
) -> None:
    """No provider is configured in tests, so this exercises the fallback path."""
    response = await client.post("/api/contact", json=valid_payload)

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["ai_status"] == "fallback"
    # Degraded, not failed: the request is still stored.
    assert data["submission_id"]
    assert data["sentiment"] is None
    assert data["category"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "I"),  # shorter than 2 characters
        ("name", "12345"),  # no letters
        ("phone", "abcdefg"),  # not a phone number
        ("phone", "+7 999"),  # too few digits
        ("email", "not-an-email"),
        ("email", "missing@tld"),
        ("comment", "short"),  # under 10 characters
    ],
)
async def test_invalid_field_is_rejected(
    client: AsyncClient, valid_payload: dict, field: str, value: str
) -> None:
    response = await client.post("/api/contact", json={**valid_payload, field: value})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(detail["field"] == field for detail in error["details"])


async def test_missing_field_is_rejected(client: AsyncClient, valid_payload: dict) -> None:
    del valid_payload["email"]
    response = await client.post("/api/contact", json=valid_payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_control_characters_are_stripped(
    client: AsyncClient, valid_payload: dict
) -> None:
    """Zero-width and control characters must not reach storage or the email body."""
    payload = {
        **valid_payload,
        "name": "Ivan​\x07 Petrov",
        "comment": "Legitimate message body\x00 with an embedded null byte.",
    }
    response = await client.post("/api/contact", json=payload)

    assert response.status_code == 201

    metrics = await client.get("/api/metrics")
    assert metrics.json()["total_submissions"] == 1


async def test_whitespace_only_name_is_rejected(
    client: AsyncClient, valid_payload: dict
) -> None:
    response = await client.post("/api/contact", json={**valid_payload, "name": "     "})
    assert response.status_code == 422


async def test_oversized_comment_is_rejected(
    client: AsyncClient, valid_payload: dict
) -> None:
    response = await client.post("/api/contact", json={**valid_payload, "comment": "x" * 5001})
    assert response.status_code == 422
