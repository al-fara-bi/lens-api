"""Shared response contracts (health, metrics, error envelope)."""

from datetime import datetime

from pydantic import BaseModel, Field


class ServiceCheck(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(description="ok when every dependency responds, degraded otherwise")
    version: str
    environment: str
    timestamp: datetime
    checks: list[ServiceCheck]


class MetricsResponse(BaseModel):
    """Aggregated from the database rather than a counter file.

    A separate counter would be a second source of truth that drifts from the
    rows it is supposed to describe.
    """

    total_submissions: int
    submissions_last_24h: int
    by_sentiment: dict[str, int]
    by_category: dict[str, int]
    ai_success_rate: float = Field(description="Share of submissions analysed without fallback")
    by_ai_provider: dict[str, int]
    generated_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    """Documents the shape every failure uses, for the OpenAPI schema."""

    error: ErrorDetail
    request_id: str | None = None
