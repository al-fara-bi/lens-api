"""Health and metrics endpoints."""

from httpx import AsyncClient


async def test_health_reports_dependency_status(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["environment"] == "test"

    checks = {check["name"]: check for check in body["checks"]}
    assert checks["database"]["healthy"] is True
    # No AI key and no SMTP host in tests: both must report themselves as
    # unavailable rather than pretending to be fine.
    assert checks["ai"]["healthy"] is False
    assert checks["smtp"]["healthy"] is False


async def test_health_is_degraded_not_unhealthy_without_optional_services(
    client: AsyncClient,
) -> None:
    """Missing AI/SMTP is a documented degraded mode, not an outage."""
    body = (await client.get("/api/health")).json()
    assert body["status"] == "degraded"


async def test_metrics_are_empty_initially(client: AsyncClient) -> None:
    body = (await client.get("/api/metrics")).json()

    assert body["total_submissions"] == 0
    assert body["ai_success_rate"] == 0.0
    assert body["by_sentiment"] == {}


async def test_metrics_count_submissions(client: AsyncClient, valid_payload: dict) -> None:
    for i in range(2):
        await client.post(
            "/api/contact",
            json={**valid_payload, "email": f"user{i}@example.com"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )

    body = (await client.get("/api/metrics")).json()

    assert body["total_submissions"] == 2
    assert body["submissions_last_24h"] == 2
    # Every submission fell back in tests, so nothing was analysed successfully.
    assert body["ai_success_rate"] == 0.0


async def test_unknown_route_uses_the_shared_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert "error" in response.json()
    assert "code" in response.json()["error"]


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    assert "/api/contact" in schema["paths"]
    assert "/api/health" in schema["paths"]
    assert "/api/metrics" in schema["paths"]
