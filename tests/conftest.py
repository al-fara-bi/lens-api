"""Test fixtures.

Environment variables are set *before* importing anything from ``app``: settings
are cached with ``lru_cache`` and the database engine is bound at import time, so
configuring afterwards would have no effect.

Each test gets a fresh lifespan, which means a fresh rate limiter — otherwise
counters would leak between tests and make ordering significant.
"""

import asyncio
import os
import tempfile
from pathlib import Path

_TMP_DIR = tempfile.mkdtemp(prefix="lens-api-tests-")

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "DATA_DIR": _TMP_DIR,
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP_DIR}/test.db",
        # Emptied explicitly: a real key exported in the developer's shell would
        # otherwise be picked up and the suite would make live, billable calls.
        "GEMINI_API_KEY": "",
        "OPENAI_API_KEY": "",
        "SMTP_HOST": "",
        "MAIL_FROM": "",
        "OWNER_EMAIL": "",
        "RATE_LIMIT_MAX_REQUESTS": "3",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "AI_TIMEOUT_SECONDS": "2",
    }
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionFactory, create_all_tables, engine  # noqa: E402
from app.main import app  # noqa: E402


async def _prepare_database() -> None:
    await create_all_tables()
    # Release connections bound to this throwaway loop so later tests open their
    # own; aiosqlite connections are not portable across event loops.
    await engine.dispose()


# Schema is built once, at collection time, rather than per test.
asyncio.run(_prepare_database())


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM submissions"))
        await session.commit()

    # The limiter deliberately persists counters across restarts, so the state
    # file has to be cleared or quotas would carry over from the previous test.
    state_file = Path(_TMP_DIR) / "rate_limit.json"
    state_file.unlink(missing_ok=True)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client


@pytest.fixture
def valid_payload() -> dict:
    return {
        "name": "Ivan Petrov",
        "phone": "+7 999 123-45-67",
        "email": "ivan@example.com",
        "comment": "Hello! I would like to discuss a backend project for our team.",
    }
