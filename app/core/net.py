"""Client IP resolution behind a reverse proxy.

The app never faces the internet directly: in production it sits behind Caddy,
which sits behind Cloudflare. `request.client.host` therefore holds the proxy's
address, not the caller's — using it would collapse every visitor into a single
rate-limit bucket.

Trusting these headers is only safe because the EC2 security group exposes
80/443 to the proxy alone; a client that could reach the app directly could
forge `X-Forwarded-For` and bypass the rate limiter.
"""

from fastapi import Request

UNKNOWN_IP = "unknown"


def get_client_ip(request: Request) -> str:
    # Set by Cloudflare and not forgeable by the caller when proxying is on.
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    # Left-most entry is the original client; the rest are proxy hops.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first

    if request.client and request.client.host:
        return request.client.host

    return UNKNOWN_IP
