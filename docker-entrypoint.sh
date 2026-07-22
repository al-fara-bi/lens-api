#!/usr/bin/env sh
# Fail on the first error so a broken migration stops the container instead of
# starting an app against a half-built schema.
set -e

echo "[entrypoint] applying database migrations..."
alembic upgrade head

echo "[entrypoint] starting API..."
# One worker on purpose. The rate limiter keeps its counters in process memory,
# so additional workers would each enforce the limit separately and multiply the
# effective quota. The workload is I/O-bound (AI call + two SMTP sends), which a
# single async worker handles comfortably.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips='*'
