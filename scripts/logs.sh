#!/usr/bin/env bash
# Tail the deployed application logs.
#
#   ./scripts/logs.sh            # container output, follow
#   ./scripts/logs.sh requests   # the JSON request log
#   ./scripts/logs.sh app        # the application log file
set -euo pipefail

SSH_HOST="${SSH_HOST:-vm-aws-london}"
REMOTE_DIR="${REMOTE_DIR:-api}"

case "${1:-container}" in
    container) ssh -t "$SSH_HOST" "cd ~/$REMOTE_DIR && docker compose logs -f --tail 100" ;;
    requests)  ssh -t "$SSH_HOST" "cd ~/$REMOTE_DIR && docker compose exec app tail -f /app/data/requests.log" ;;
    app)       ssh -t "$SSH_HOST" "cd ~/$REMOTE_DIR && docker compose exec app tail -f /app/data/app.log" ;;
    *)         echo "usage: $0 {container|requests|app}" >&2; exit 1 ;;
esac
