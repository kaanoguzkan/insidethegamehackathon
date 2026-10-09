"""Guards for the public Brain API: who may spend what.

The Brain is reachable from the internet and every ``/api/beats`` request can cost model tokens, and an expensive
one (the five-agent workflow, no cache) can hold a worker for a minute. Three small guards, all in memory, so they act per
replica:

* a per-client sliding-window rate limit on the expensive routes (:class:`RateLimitMiddleware`);
* a cap on requests being served at once, so a burst is turned away quickly instead of queueing behind slow model calls;
* an admin key for the options that are only for operators (``mode: full``, ``useCache: false``, long deadlines).
  With ``MATCHMIND_ADMIN_KEY`` unset (local development, tests) nothing is restricted.
"""

from __future__ import annotations

import hmac
import json
import os
import time
from collections import defaultdict, deque

ADMIN_HEADER = "x-admin-key"
PUBLIC_MAX_DEADLINE_MS = 10_000


def client_ip(headers: dict[str, str], peer: str | None) -> str:
    """The client's address. Behind the Azure ingress the TCP peer is the proxy, and the proxy appends the real client
    to ``X-Forwarded-For``: take the LAST entry, because anything before it was written by the client and can be forged."""
    xff = headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    return parts[-1] if parts else (peer or "unknown")


class SlidingWindow:
    """At most ``limit`` events per ``window_s`` for each key. Old keys are dropped so memory stays bounded."""

    def __init__(self, limit: int, window_s: float, max_keys: int = 10_000, clock=time.monotonic) -> None:  # noqa: ANN001
        self.limit, self.window_s, self.max_keys, self._clock = limit, window_s, max_keys, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> tuple[bool, float]:
        """(allowed, seconds until the next slot is free). Counts the event only when it is allowed."""
        now = self._clock()
        q = self._hits[key]
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False, max(self.window_s - (now - q[0]), 0.0)
        q.append(now)
        if len(self._hits) > self.max_keys:
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_s][: self.max_keys // 2]:
                del self._hits[k]
        return True, 0.0


class RateLimitMiddleware:
    """Pure ASGI middleware: ``rules`` are (path prefix, method or None, limit, window seconds). A request over the limit
    gets HTTP 429 with ``Retry-After``. Preflight (OPTIONS) is never counted."""

    def __init__(self, app, rules: list[tuple[str, str | None, int, float]]) -> None:  # noqa: ANN001
        self.app = app
        self.rules = [(prefix, method, SlidingWindow(limit, window)) for prefix, method, limit, window in rules]

    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN201
        if scope["type"] == "http" and scope["method"] != "OPTIONS":
            for prefix, method, window in self.rules:
                if scope["path"].startswith(prefix) and method in (None, scope["method"]):
                    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                    peer = (scope.get("client") or (None,))[0]
                    ok, retry = window.allow(f"{prefix}|{client_ip(headers, peer)}")
                    if not ok:
                        body = json.dumps({"detail": "too many requests", "retryAfterS": round(retry, 1)}).encode()
                        await send({"type": "http.response.start", "status": 429, "headers": [
                            (b"content-type", b"application/json"), (b"retry-after", str(int(retry) + 1).encode()), (b"content-length", str(len(body)).encode())]})
                        await send({"type": "http.response.body", "body": body})
                        return
                    break
        await self.app(scope, receive, send)


def is_admin(header_value: str | None) -> bool:
    """True when no admin key is configured (development) or the caller sent the right one."""
    key = os.environ.get("MATCHMIND_ADMIN_KEY")
    return not key or hmac.compare_digest(header_value or "", key)
