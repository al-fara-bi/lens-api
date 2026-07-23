#!/usr/bin/env bash
#
# Deploy the current working tree to the server.
#
#   ./scripts/deploy.sh              # app only, no TLS (port 8000, internal)
#   ./scripts/deploy.sh --tls        # app + Caddy, HTTPS on the public domain
#
# Environment overrides:
#   SSH_HOST      ssh alias or user@host          (default: vm-aws-london)
#   REMOTE_DIR    directory on the server         (default: api)
#   DOMAIN        used for the post-deploy check  (default: api.farhat.one)
#
# The server's .env is never touched — secrets live only there.

set -euo pipefail

SSH_HOST="${SSH_HOST:-vm-aws-london}"
REMOTE_DIR="${REMOTE_DIR:-api}"
DOMAIN="${DOMAIN:-lens-api.farhat.one}"

USE_TLS=false
[[ "${1:-}" == "--tls" ]] && USE_TLS=true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Colour only when a human is reading. Piped into a file, a log or CI, the escape
# sequences would be written out literally as `[33m` and clutter the output.
if [[ -t 1 ]]; then
    C_BOLD=$'\033[1m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'; C_OFF=$'\033[0m'
else
    C_BOLD=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_OFF=''
fi

bold()  { printf '%s%s%s\n' "$C_BOLD" "$1" "$C_OFF"; }
info()  { printf '  %s\n' "$1"; }
warn()  { printf '%s  %s%s\n' "$C_YELLOW" "$1" "$C_OFF"; }
fail()  { printf '%sERROR: %s%s\n' "$C_RED" "$1" "$C_OFF" >&2; exit 1; }

# ---------- preflight ----------

bold "==> Preflight"

git rev-parse --git-dir >/dev/null 2>&1 || fail "not a git repository"

# A dirty tree means the deployed code does not match any commit, so the version
# label would be a lie. Allowed, but only deliberately.
#
# `git status --porcelain` rather than `git diff-index`: the latter trusts cached
# stat information and reports files as modified when only their mtime changed —
# a rewrite with identical content is enough to trigger a spurious prompt.
if [[ -n "$(git status --porcelain)" ]]; then
    warn "Working tree has uncommitted changes:"
    git status --short | sed 's/^/    /'
    read -r -p "  Deploy anyway? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || fail "aborted"
fi

VERSION="$(git describe --tags --always --dirty 2>/dev/null || echo 'untagged')"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
info "version : $VERSION"
info "branch  : $BRANCH"
info "target  : $SSH_HOST:~/$REMOTE_DIR"
info "tls     : $USE_TLS"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" 'true' \
    || fail "cannot reach $SSH_HOST over ssh"

ssh -o BatchMode=yes "$SSH_HOST" "test -f ~/$REMOTE_DIR/.env" \
    || fail "~/$REMOTE_DIR/.env is missing on the server — create it from .env.example first"

# ---------- tests ----------

bold "==> Tests"
if [[ -x .venv/bin/pytest ]]; then
    # Shipping a red build to production is never the intent, so this is a gate,
    # not a report.
    .venv/bin/pytest -q || fail "tests failed — not deploying"
else
    info "skipped (no local .venv; run 'pip install -r requirements-dev.txt')"
fi

# ---------- sync ----------

bold "==> Sync"
rsync -az --delete \
    --exclude '.venv/' \
    --exclude 'data/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache/' \
    --exclude '.git/' \
    --exclude '.env' \
    ./ "$SSH_HOST:~/$REMOTE_DIR/"
info "code synced"

# ---------- build & restart ----------

COMPOSE="docker compose"
$USE_TLS && COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

bold "==> Build & restart"
ssh -o BatchMode=yes "$SSH_HOST" "
    set -e
    cd ~/$REMOTE_DIR
    printf 'APP_VERSION=%s\n' '$VERSION' > .env.version
    $COMPOSE build
    $COMPOSE up -d
    # Keep the disk from filling with orphaned layers after repeated deploys.
    docker image prune -f >/dev/null
" 2>&1 | grep -viE '^\s*$' | tail -6

# ---------- verify ----------

bold "==> Verify"
if $USE_TLS; then
    HEALTH_URL="https://$DOMAIN/api/health"
    RESPONSE="$(curl -fsS --retry 20 --retry-delay 2 --retry-all-errors "$HEALTH_URL" 2>/dev/null || true)"
else
    HEALTH_URL="http://localhost:8000/api/health (from inside the server)"
    RESPONSE="$(ssh -o BatchMode=yes "$SSH_HOST" \
        "curl -fsS --retry 20 --retry-delay 2 --retry-connrefused --retry-all-errors http://localhost:8000/api/health 2>/dev/null" || true)"
fi

[[ -n "$RESPONSE" ]] || fail "health check returned nothing — check: ssh $SSH_HOST 'cd ~/$REMOTE_DIR && docker compose logs --tail 50'"

# Rendered as a short table rather than dumped as raw JSON — the point of this
# step is "is anything broken", which is hard to see in 25 lines of braces.
printf '%s\n' "$RESPONSE" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for check in data["checks"]:
    mark = "ok " if check["healthy"] else "OFF"
    detail = check["detail"] or ""
    print(f"  [{mark}] {check[\"name\"]:<9} {detail}")
' 2>/dev/null || printf '    %s\n' "$RESPONSE"

read -r DEPLOYED STATUS <<<"$(
    printf '%s' "$RESPONSE" |
    python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["version"], d["status"])' \
        2>/dev/null || echo '? ?'
)"

echo
if [[ "$DEPLOYED" != "$VERSION" ]]; then
    printf '%s✗  Version mismatch%s\n' "$C_YELLOW" "$C_OFF"
    printf '   running %s, expected %s — the previous container may not have been replaced\n' \
        "$DEPLOYED" "$VERSION"
    exit 1
fi

printf '%s✓  Deployed %s%s\n' "$C_GREEN" "$VERSION" "$C_OFF"
printf '   health   %s\n' "$STATUS"
printf '   api      https://%s/api/health\n' "$DOMAIN"
printf '   docs     https://%s/docs\n' "$DOMAIN"
if [[ "$STATUS" != "ok" ]]; then
    printf '   note     some optional services are unconfigured — see the checks above\n'
fi
