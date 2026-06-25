"""Simple in-memory per-client rate limiter — a cost guard for the LLM endpoints.

Sliding window per client IP: a per-minute burst cap and a per-day total cap.
In-memory (per process) — fine for a single instance; swap for Redis if you
scale to multiple workers/instances.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

PER_MINUTE = 12
PER_DAY = 150

_hits: dict[str, deque] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # Respect the first hop of X-Forwarded-For when behind a proxy/load balancer.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    """FastAPI dependency: raise 429 when a client exceeds the caps."""
    key = _client_key(request)
    now = time.time()
    dq = _hits[key]

    day_ago = now - 86_400
    while dq and dq[0] < day_ago:
        dq.popleft()

    minute_ago = now - 60
    in_last_minute = sum(1 for t in dq if t >= minute_ago)
    if in_last_minute >= PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Too many requests this minute — please slow down and try again shortly.",
        )
    if len(dq) >= PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="Daily request limit reached for this session. Please try again tomorrow.",
        )

    dq.append(now)
