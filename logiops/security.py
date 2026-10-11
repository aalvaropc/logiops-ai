"""Small deployment guard for the demo HTTP API and MCP transport."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agent import INTERNAL_HEADER
from .identity import OPERATOR
from .oauth import GUEST, InvalidToken, OAuthSettings, base_url, challenge, needed_scope, scope_name, verify_async


SANDBOX_PATH = "/mcp-app/sandbox.html"
PUBLIC_PATHS = ("/healthz", "/docs", "/openapi.json", "/redoc", "/demo", "/auth/config", SANDBOX_PATH)
OAUTH_PATHS = ("/auth/config", "/auth/token")


class _SlidingWindow:
    """In-memory limiter, deliberately scoped to the single demo worker."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self.hits[key]
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()
        if not bucket:
            self.hits.pop(key, None)
            bucket = self.hits[key]
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


def _constant_time_equal(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(supplied.encode("utf-8", "surrogateescape"), expected.encode("utf-8"))


def client_key(request: Request, *, trust_cloudfront: bool) -> str:
    """Identify the viewer for rate limiting.

    Behind CloudFront the TCP peer is an edge server shared by many viewers, so
    use the CloudFront-Viewer-Address header instead. It is only trusted when
    the origin is reachable exclusively from CloudFront (security group rule).
    """
    if trust_cloudfront:
        viewer = request.headers.get("cloudfront-viewer-address", "")
        if viewer:
            return viewer.rsplit(":", 1)[0]
    return request.client.host if request.client else "unknown"


def install_security(
    app: FastAPI,
    access_token: str | None,
    *,
    internal_key: str,
    limit_per_minute: int = 60,
    agent_limit_per_minute: int = 10,
    trust_cloudfront: bool = False,
    sandbox_host: str | None = None,
    oauth: OAuthSettings | None = None,
    public_host: str | None = None,
) -> None:
    mcp_limiter = _SlidingWindow(limit_per_minute, 60)
    agent_limiter = _SlidingWindow(agent_limit_per_minute, 60)
    speech_limiter = _SlidingWindow(agent_limit_per_minute * 3, 60)

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if sandbox_host and request.headers.get("host", "").split(":")[0].lower() == sandbox_host and path != SANDBOX_PATH:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        key = client_key(request, trust_cloudfront=trust_cloudfront)
        if oauth and (path in OAUTH_PATHS or path.startswith("/.well-known/")):
            if path == "/auth/token" and not mcp_limiter.allow(key):
                return JSONResponse(status_code=429, content={"error": "slow_down"})
            response = await call_next(request)
            response.headers.setdefault("Cache-Control", "no-store")
            return response
        if path in PUBLIC_PATHS or path.startswith("/assets/"):
            response = await call_next(request)
            response.headers.setdefault("Cache-Control", "no-cache")
            return response
        supplied = request.headers.get("authorization", "")
        scopes: set[str] | None = None
        if access_token and _constant_time_equal(supplied, f"Bearer {access_token}"):
            actor = OPERATOR
        elif oauth and supplied[:7].lower() == "bearer ":
            try:
                actor, scopes = await verify_async(oauth, supplied[7:].strip())
            except InvalidToken as exc:
                base = base_url(request, public_host)
                return JSONResponse(status_code=401, content={"detail": str(exc)},
                                    headers={"WWW-Authenticate": challenge(base, error="invalid_token", description=str(exc))})
        elif oauth:
            actor = GUEST
        elif access_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer token required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            actor = OPERATOR
        if actor.kind != "operator":
            need = await needed_scope(request)
            if need:
                base = base_url(request, public_host)
                if actor.kind == "guest":
                    return JSONResponse(status_code=401, content={"detail": "Sign in to do this; guests can only read."},
                                        headers={"WWW-Authenticate": challenge(base, need)})
                if scope_name(base, need) not in (scopes or set()):
                    return JSONResponse(status_code=403, content={"detail": "Your sign-in does not allow this action."},
                                        headers={"WWW-Authenticate": challenge(base, need, error="insufficient_scope")})
        request.state.actor = actor
        internal = _constant_time_equal(request.headers.get(INTERNAL_HEADER, ""), internal_key)
        if path.startswith("/mcp") and not internal and not mcp_limiter.allow(key):
            return JSONResponse(status_code=429, content={"detail": "MCP rate limit exceeded"})
        if path == "/voice/speech" and not speech_limiter.allow(key):
            return JSONResponse(status_code=429, content={"detail": "Speech rate limit exceeded", "fallback": "browser"})
        if "/agent/" in path and not agent_limiter.allow(key):
            return JSONResponse(
                status_code=429,
                content={"detail": "Agent rate limit exceeded; each run calls a paid model"},
            )
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response
