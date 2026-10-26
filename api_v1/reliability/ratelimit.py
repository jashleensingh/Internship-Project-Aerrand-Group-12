"""Per-key fixed-window rate limit (60 requests a minute; 20 bookings a minute on top).

Counters live in the Django cache. Locally that is in-memory; with REDIS_URL set it is Redis, shared by every
worker (Aerrand runs 3), so the limit holds across processes. Every response carries X-RateLimit-*; a 429 adds
Retry-After. Counters are only kept for requests that carry a valid key.
"""
import time

from django.conf import settings
from django.core.cache import cache

from api_v1.common.errors import ApiError


def _hit(name, key_id, window):
    ck = f"rl:{name}:{key_id}:{window}"
    cache.add(ck, 0, timeout=120)
    try:
        return cache.incr(ck)
    except ValueError:      # expired between add and incr
        cache.set(ck, 1, timeout=120)
        return 1


def enforce(request, kind="default"):
    """Returns the headers to attach. Raises 429 rate_limited when over the limit."""
    key_id = request.auth.id
    now = int(time.time())
    window = now // 60
    reset = (window + 1) * 60
    limits = [("default", settings.API_RATE_PER_MIN)]
    if kind == "create":
        limits.append(("create", settings.API_CREATE_PER_MIN))
    tightest = None
    for name, limit in limits:
        n = _hit(name, key_id, window)
        remaining = max(0, limit - n)
        info = {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining), "X-RateLimit-Reset": str(reset)}
        if n > limit:
            info["Retry-After"] = str(max(1, reset - now))
            raise ApiError(429, "rate_limited", f"Too many requests. Retry in {info['Retry-After']} seconds.",
                           headers=info)
        if tightest is None or remaining < int(tightest["X-RateLimit-Remaining"]):
            tightest = info
    return tightest
