"""Small deployment guard for the demo HTTP API and MCP transport."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def install_security(app: FastAPI, access_token: str | None, *, limit_per_minute: int = 60) -> None:
    requests: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if path in ("/healthz", "/docs", "/openapi.json", "/redoc", "/demo") or path.startswith("/assets/"):
            return await call_next(request)
        if access_token:
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {access_token}"):
                return JSONResponse(status_code=401, content={"detail": "Bearer token required"})
        if path.startswith("/mcp"):
            # In-memory limit is deliberately scoped to a single demo worker.
            peer = request.client.host if request.client else "unknown"
            now = time.monotonic()
            bucket = requests[peer]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= limit_per_minute:
                return JSONResponse(status_code=429, content={"detail": "MCP rate limit exceeded"})
            bucket.append(now)
        return await call_next(request)
