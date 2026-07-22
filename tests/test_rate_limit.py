"""Rate limiting behaviour. Test config allows 3 requests per 60 seconds."""

from httpx import AsyncClient

LIMIT = 3


async def test_requests_within_limit_are_allowed(
    client: AsyncClient, valid_payload: dict
) -> None:
    for _ in range(LIMIT):
        response = await client.post(
            "/api/contact", json=valid_payload, headers={"X-Forwarded-For": "203.0.113.10"}
        )
        assert response.status_code == 201


async def test_request_over_limit_is_rejected(
    client: AsyncClient, valid_payload: dict
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.20"}
    for _ in range(LIMIT):
        await client.post("/api/contact", json=valid_payload, headers=headers)

    response = await client.post("/api/contact", json=valid_payload, headers=headers)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limit_exceeded"
    # Clients need to know when to come back, not just that they were refused.
    assert int(response.headers["Retry-After"]) > 0


async def test_limit_is_tracked_per_client(client: AsyncClient, valid_payload: dict) -> None:
    """One noisy visitor must not lock everyone else out.

    This is the regression guard for reading the socket address instead of the
    forwarded header: behind a proxy that would put every caller in one bucket.
    """
    noisy = {"X-Forwarded-For": "203.0.113.30"}
    for _ in range(LIMIT + 1):
        await client.post("/api/contact", json=valid_payload, headers=noisy)

    quiet = {"X-Forwarded-For": "203.0.113.31"}
    response = await client.post("/api/contact", json=valid_payload, headers=quiet)

    assert response.status_code == 201


async def test_blocked_request_does_not_extend_the_window(
    client: AsyncClient, valid_payload: dict
) -> None:
    """A rejected attempt must not be recorded.

    If it were, a client hammering the endpoint would keep pushing their own
    reset time further away and never recover.
    """
    headers = {"X-Forwarded-For": "203.0.113.40"}
    for _ in range(LIMIT):
        await client.post("/api/contact", json=valid_payload, headers=headers)

    first = await client.post("/api/contact", json=valid_payload, headers=headers)
    for _ in range(3):
        await client.post("/api/contact", json=valid_payload, headers=headers)
    last = await client.post("/api/contact", json=valid_payload, headers=headers)

    assert first.status_code == last.status_code == 429
    assert int(last.headers["Retry-After"]) <= int(first.headers["Retry-After"])


async def test_read_endpoints_are_not_rate_limited(
    client: AsyncClient, valid_payload: dict
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.50"}
    for _ in range(LIMIT + 2):
        await client.post("/api/contact", json=valid_payload, headers=headers)

    assert (await client.get("/api/health", headers=headers)).status_code == 200
    assert (await client.get("/api/metrics", headers=headers)).status_code == 200


async def test_cloudflare_header_takes_precedence(
    client: AsyncClient, valid_payload: dict
) -> None:
    """CF-Connecting-IP wins over X-Forwarded-For, which the caller can forge."""
    headers = {"CF-Connecting-IP": "203.0.113.60", "X-Forwarded-For": "198.51.100.1"}
    for _ in range(LIMIT):
        await client.post("/api/contact", json=valid_payload, headers=headers)

    blocked = await client.post("/api/contact", json=valid_payload, headers=headers)
    assert blocked.status_code == 429

    # Same X-Forwarded-For, different real client — must not be blocked.
    other = await client.post(
        "/api/contact",
        json=valid_payload,
        headers={"CF-Connecting-IP": "203.0.113.61", "X-Forwarded-For": "198.51.100.1"},
    )
    assert other.status_code == 201
