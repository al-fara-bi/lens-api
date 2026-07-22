#!/usr/bin/env bash
# Runnable examples for every endpoint and error path.
#
#   ./examples/curl-examples.sh                          # against localhost
#   BASE_URL=https://lens-api.farhat.one ./examples/curl-examples.sh
set -u

BASE_URL="${BASE_URL:-http://localhost:8000}"

section() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
call()    { printf '\n$ %s\n' "$2"; eval "$2"; printf '\n'; }

section "Health"
call h "curl -s '$BASE_URL/api/health' | python3 -m json.tool"

section "Valid submission -> 201"
call c "curl -s -w '\nHTTP %{http_code}\n' -X POST '$BASE_URL/api/contact' \
  -H 'Content-Type: application/json' \
  -d '{\"name\":\"Ivan Petrov\",\"phone\":\"+7 999 123-45-67\",\"email\":\"ivan@example.com\",\"comment\":\"Hello! I would like to discuss a backend project for our team.\"}'"

section "Validation failure -> 422 (per-field details)"
call v "curl -s -w '\nHTTP %{http_code}\n' -X POST '$BASE_URL/api/contact' \
  -H 'Content-Type: application/json' \
  -d '{\"name\":\"I\",\"phone\":\"abc\",\"email\":\"not-an-email\",\"comment\":\"short\"}'"

section "Missing field -> 422"
call m "curl -s -w '\nHTTP %{http_code}\n' -X POST '$BASE_URL/api/contact' \
  -H 'Content-Type: application/json' \
  -d '{\"name\":\"Ivan Petrov\",\"phone\":\"+79991234567\"}'"

section "Unknown route -> 404 in the shared error envelope"
call n "curl -s -w '\nHTTP %{http_code}\n' '$BASE_URL/api/does-not-exist'"

section "Rate limit -> 429 with Retry-After"
echo "Sending 7 requests from a single simulated IP (default limit: 5/hour)..."
for i in $(seq 1 7); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/contact" \
    -H 'Content-Type: application/json' \
    -H 'X-Forwarded-For: 203.0.113.99' \
    -d '{"name":"Rate Probe","phone":"+79991234567","email":"probe@example.com","comment":"Rate limit probe message."}')
  echo "  request $i -> HTTP $CODE"
done
echo "Full 429 response:"
curl -s -D - -o /dev/null -X POST "$BASE_URL/api/contact" \
  -H 'Content-Type: application/json' -H 'X-Forwarded-For: 203.0.113.99' \
  -d '{"name":"Rate Probe","phone":"+79991234567","email":"probe@example.com","comment":"Rate limit probe message."}' \
  | grep -iE '^(HTTP|retry-after)'

section "Metrics"
call mt "curl -s '$BASE_URL/api/metrics' | python3 -m json.tool"
