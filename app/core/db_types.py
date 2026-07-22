"""Portable column types.

SQLite has no native timezone-aware timestamp: it stores whatever it is given
and returns a naive ``datetime``. Serialising that produces an ISO string with
no offset, which a client will read as *local* time — a silent multi-hour error.

``UTCDateTime`` normalises on the way in and re-attaches UTC on the way out, so
the application only ever sees aware datetimes regardless of dialect. On
PostgreSQL the underlying ``TIMESTAMPTZ`` already does this and the decorator
becomes a no-op, which keeps the migration path clean.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # Naive values are assumed UTC rather than rejected, so that
            # `datetime.utcnow()` in third-party code does not blow up a write.
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
