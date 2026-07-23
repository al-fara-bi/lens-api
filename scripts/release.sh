#!/usr/bin/env bash
#
# Cut a release: merge dev into main, tag it, push both.
#
#   ./scripts/release.sh patch     # 1.0.0 -> 1.0.1  (bug fixes)
#   ./scripts/release.sh minor     # 1.0.1 -> 1.1.0  (new functionality)
#   ./scripts/release.sh major     # 1.1.0 -> 2.0.0  (breaking changes)
#   ./scripts/release.sh v1.4.2    # explicit version
#
# Work happens on dev. main only ever moves through this script, so every commit
# on main corresponds to a tag, and `git describe` on the server is meaningful.

set -euo pipefail

DEV_BRANCH="${DEV_BRANCH:-dev}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Colour only when a human is reading — see the note in deploy.sh.
if [[ -t 1 ]]; then
    C_BOLD=$'\033[1m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_OFF=$'\033[0m'
else
    C_BOLD=''; C_RED=''; C_GREEN=''; C_OFF=''
fi

bold() { printf '%s%s%s\n' "$C_BOLD" "$1" "$C_OFF"; }
info() { printf '  %s\n' "$1"; }
fail() { printf '%sERROR: %s%s\n' "$C_RED" "$1" "$C_OFF" >&2; exit 1; }

BUMP="${1:-}"
[[ -n "$BUMP" ]] || fail "usage: $0 {patch|minor|major|vX.Y.Z}"

# ---------- preflight ----------

bold "==> Preflight"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$CURRENT_BRANCH" == "$DEV_BRANCH" ]] \
    || fail "releases are cut from '$DEV_BRANCH', but you are on '$CURRENT_BRANCH'"

# Same reason as in deploy.sh: git diff-index trusts cached stat data and flags
# files whose mtime changed but whose content did not.
[[ -z "$(git status --porcelain)" ]] \
    || fail "working tree is dirty — commit or stash first"

# ---------- version ----------

LAST_TAG="$(git tag --list 'v*' --sort=-v:refname | head -1)"
[[ -n "$LAST_TAG" ]] || LAST_TAG="v0.0.0"

if [[ "$BUMP" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    NEW_TAG="$BUMP"
else
    IFS=. read -r major minor patch <<< "${LAST_TAG#v}"
    case "$BUMP" in
        major) NEW_TAG="v$((major + 1)).0.0" ;;
        minor) NEW_TAG="v${major}.$((minor + 1)).0" ;;
        patch) NEW_TAG="v${major}.${minor}.$((patch + 1))" ;;
        *)     fail "unknown bump '$BUMP' — use patch, minor, major or vX.Y.Z" ;;
    esac
fi

git rev-parse "$NEW_TAG" >/dev/null 2>&1 && fail "tag $NEW_TAG already exists"

info "previous : $LAST_TAG"
info "new      : $NEW_TAG"

# ---------- tests ----------

bold "==> Tests"
if [[ -x .venv/bin/pytest ]]; then
    .venv/bin/pytest -q || fail "tests failed — not releasing"
else
    info "skipped (no local .venv)"
fi

# ---------- what is being released ----------

bold "==> Changes since $LAST_TAG"
if git rev-parse "$LAST_TAG" >/dev/null 2>&1; then
    git log --oneline "$LAST_TAG..HEAD" | sed 's/^/    /'
else
    git log --oneline | sed 's/^/    /'
fi

read -r -p "  Release $NEW_TAG? [y/N] " reply
[[ "$reply" =~ ^[Yy]$ ]] || fail "aborted"

# ---------- merge & tag ----------

bold "==> Merging $DEV_BRANCH into $MAIN_BRANCH"
git checkout "$MAIN_BRANCH"
# --no-ff keeps each release visible as a single merge commit on main instead of
# flattening it into dev's history.
git merge --no-ff "$DEV_BRANCH" -m "release: $NEW_TAG"
git tag -a "$NEW_TAG" -m "Release $NEW_TAG"

if git remote get-url origin >/dev/null 2>&1; then
    bold "==> Pushing"
    git push origin "$MAIN_BRANCH"
    git push origin "$NEW_TAG"
else
    info "no 'origin' remote — nothing pushed"
fi

git checkout "$DEV_BRANCH"

echo
printf '%s✓  Released %s%s\n' "$C_GREEN" "$NEW_TAG" "$C_OFF"
printf '   deploy   ./scripts/deploy.sh --tls\n'
