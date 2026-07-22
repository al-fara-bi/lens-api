"""Async SQLAlchemy engine and session wiring.

SQLite is deliberate rather than a limitation — see README. Types are kept
dialect-portable (``Uuid``, timezone-aware ``DateTime``) so moving to
PostgreSQL is a change of ``DATABASE_URL`` plus a fresh migration.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    # SQLite refuses a connection used across threads unless told otherwise;
    # aiosqlite runs statements on a worker thread.
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        # WAL lets reads proceed while a write is in flight — without it a
        # concurrent read during INSERT raises "database is locked".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keeps attributes readable after commit
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rolled back on failure."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def verify_schema() -> None:
    """Fail fast with a useful message if migrations have not been applied.

    Without this the first request dies on "no such table: submissions" from
    somewhere deep in the ORM, which is a confusing way to learn you forgot
    ``alembic upgrade head``.
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='submissions'")
            if settings.database_url.startswith("sqlite")
            else text("SELECT to_regclass('submissions')")
        )
        if result.scalar() is None:
            raise RuntimeError(
                "Database schema is missing. Run 'alembic upgrade head' before starting the app."
            )
    logger.info("Database schema verified at %s", settings.database_url)


async def create_all_tables() -> None:
    """Build the schema directly from the models — tests only.

    Production schema is owned by Alembic; this exists so the test suite does not
    need a migration run per session.
    """
    from app.models import submission  # noqa: F401  — registers the mapper

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
