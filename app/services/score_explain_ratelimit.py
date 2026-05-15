"""In-memory rate limiter for the /v1/scores/explain endpoint.

Only consulted on cache MISS — cached responses (the overwhelming majority,
since a daily cron pre-warms all (vault, dimension) pairs) bypass this
entirely and stay fast.

Two independent windows enforced at request time:
  * Global cache-miss ceiling — protects the Anthropic subscription from a
    single attacker rotating IPs.
  * Per-IP cache-miss ceiling — protects against a slow scraper from one box.

Both windows are 60s sliding. Counts are kept in-memory per uvicorn worker,
which is intentional: with a single worker (the default for this service),
the ceilings hold; with multiple workers each worker would have its own
budget, which would only loosen the limit, never tighten — still bounded.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional


# Tunables. The legitimate steady-state miss rate is ~0 because the pre-warm
# cron fills the cache nightly; the only legitimate misses are: (a) a vault
# was just added today, (b) the cache TTL'd and the cron hasn't run yet,
# (c) the cron was disabled. So these limits can stay tight without hurting
# real users — and they brick scrapers that try to hit every (vault, dim).
GLOBAL_MISS_LIMIT = 30      # ~30 fresh generations/min across all callers
GLOBAL_MISS_WINDOW = 60.0
PER_IP_MISS_LIMIT = 5       # ~5 fresh generations/min from one IP
PER_IP_MISS_WINDOW = 60.0
# Per-IP table TTL — keep memory bounded if the API stays up for weeks.
PER_IP_GC_AFTER_SEC = 600.0

_global_misses: deque[float] = deque()
_per_ip_misses: dict[str, deque[float]] = {}
_last_ip_gc: float = 0.0


def _prune(dq: deque, window: float, now: float) -> None:
    while dq and now - dq[0] > window:
        dq.popleft()


def _gc_per_ip(now: float) -> None:
    """Drop IP buckets that haven't seen a miss in a while. Cheap O(n) sweep
    every ~5min so we don't leak memory on long-lived deployments."""
    global _last_ip_gc
    if now - _last_ip_gc < 300.0:
        return
    _last_ip_gc = now
    dead = [
        ip for ip, dq in _per_ip_misses.items()
        if not dq or now - dq[-1] > PER_IP_GC_AFTER_SEC
    ]
    for ip in dead:
        _per_ip_misses.pop(ip, None)


def check_and_record_miss(ip: str) -> tuple[bool, Optional[str]]:
    """Try to record a cache-miss event for `ip`.

    Returns (allowed, reason_if_denied). `reason` is one of "global" or "ip".
    On allowed=True the miss has been counted against both windows. On
    allowed=False NOTHING is counted (so a denied attempt doesn't itself
    eat into the budget — caller should return 429 immediately).
    """
    now = time.time()
    _prune(_global_misses, GLOBAL_MISS_WINDOW, now)
    if len(_global_misses) >= GLOBAL_MISS_LIMIT:
        return False, "global"

    ip_key = (ip or "unknown").strip() or "unknown"
    ip_dq = _per_ip_misses.setdefault(ip_key, deque())
    _prune(ip_dq, PER_IP_MISS_WINDOW, now)
    if len(ip_dq) >= PER_IP_MISS_LIMIT:
        return False, "ip"

    _global_misses.append(now)
    ip_dq.append(now)
    _gc_per_ip(now)
    return True, None


def client_ip(request) -> str:
    """Best-effort client IP. Reads the first X-Forwarded-For entry when
    present (nginx sets this) and falls back to the direct peer. We never
    trust the full XFF chain — just the leftmost address, which is what
    the upstream proxy saw."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return (request.client.host if request.client else "unknown") or "unknown"
