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

bold()  { printf '\033[1m%s\033[0m\n' "$1"; }
info()  { printf '  %s\n' "$1"; }
fail()  { printf '\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

# ---------- preflight ----------

bold "==> Preflight"

git rev-parse --git-dir >/dev/null 2>&1 || fail "not a git repository"

# A dirty tree means the deployed code does not match any commit, so the version
# label would be a lie. Allowed, but only deliberately.
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    printf '\033[33m  Working tree has uncommitted changes.\033[0m\n'
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
    export APP_VERSION='$VERSION'
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

info "$HEALTH_URL"
printf '%s\n' "$RESPONSE" | python3 -m json.tool 2>/dev/null | sed 's/^/    /' \
    || printf '    %s\n' "$RESPONSE"

DEPLOYED="$(printf '%s' "$RESPONSE" | python3 -c 'import sys,json; print(json.load(sys.stdin)["version"])' 2>/dev/null || echo '?')"
if [[ "$DEPLOYED" == "$VERSION" ]]; then
    printf '\033[32m\n✓ Deployed %s\033[0m\n' "$VERSION"
else
    printf '\033[33m\n! Reported version is %s, expected %s — the old container may still be running\033[0m\n' \
        "$DEPLOYED" "$VERSION"
fi
