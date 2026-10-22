"""Small deployment guard for the demo HTTP API and MCP transport."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agent import INTERNAL_HEADER
from .identity import OPERATOR, Actor
from .mcp_transport import NO_STORE, McpRequestGuard
from .oauth import GUEST, InvalidToken, OAuthSettings, base_url, challenge, needed_scope, scope_name, verify_async


SANDBOX_PATH = "/mcp-app/sandbox.html"
PUBLIC_PATHS = ("/healthz", "/docs", "/openapi.json", "/redoc", "/demo", "/console", "/metrics", "/auth/config", SANDBOX_PATH)
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

    def on_sandbox(request: Request) -> bool:
        return bool(sandbox_host) and request.headers.get("host", "").split(":")[0].lower() == sandbox_host

    async def identify(request: Request) -> tuple[Actor, set[str] | None] | JSONResponse:
        known = getattr(request.state, "identity", None)
        if known is not None:
            return known
        supplied = request.headers.get("authorization", "")
        scopes: set[str] | None = None
        if access_token and supplied[:7].lower() == "bearer " and _constant_time_equal(supplied[7:].strip(), access_token):
            actor = OPERATOR
        elif oauth and supplied[:7].lower() == "bearer ":
            try:
                actor, scopes = await verify_async(oauth, supplied[7:].strip())
            except InvalidToken as exc:
                base = base_url(request, public_host)
                return JSONResponse(status_code=401, content={"detail": str(exc)},
                                    headers={**NO_STORE, "WWW-Authenticate": challenge(base, error="invalid_token", description=str(exc))})
        elif oauth:
            actor = GUEST
        elif access_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer token required"},
                headers={**NO_STORE, "WWW-Authenticate": "Bearer"},
            )
        else:
            actor = OPERATOR
        request.state.identity = (actor, scopes)
        return actor, scopes

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if on_sandbox(request) and path != SANDBOX_PATH:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        key = client_key(request, trust_cloudfront=trust_cloudfront)
        request.state.viewer = key
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
        identity = await identify(request)
        if isinstance(identity, JSONResponse):
            return identity
        actor, scopes = identity
        if actor.kind != "operator":
            need = await needed_scope(request)
            if need:
                base = base_url(request, public_host)
                if actor.kind == "guest":
                    return JSONResponse(status_code=401, content={"detail": "Sign in to do this; guests can only read."},
                                        headers={**NO_STORE, "WWW-Authenticate": challenge(base, need)})
                if scope_name(base, need) not in (scopes or set()):
                    return JSONResponse(status_code=403, content={"detail": "Your sign-in does not allow this action."},
                                        headers={**NO_STORE, "WWW-Authenticate": challenge(base, need, error="insufficient_scope")})
        request.state.actor = actor
        request.state.permissions = frozenset(
            name for name in ("incidents.operate", "bookings.write")
            if scope_name(base_url(request, public_host), name) in (scopes or set())
        )
        internal = _constant_time_equal(request.headers.get(INTERNAL_HEADER, ""), internal_key)
        if (path.startswith("/memory") or (path.startswith("/mcp") and path not in ("/mcp", "/mcp/"))) and not internal and not mcp_limiter.allow(key):
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

    def allow_mcp(request: Request) -> bool:
        return _constant_time_equal(request.headers.get(INTERNAL_HEADER, ""), internal_key) or mcp_limiter.allow(
            client_key(request, trust_cloudfront=trust_cloudfront))

    async def admit_mcp(request: Request) -> JSONResponse | None:
        if on_sandbox(request):
            return JSONResponse(status_code=404, content={"detail": "Not found"}, headers=NO_STORE)
        identity = await identify(request)
        return identity if isinstance(identity, JSONResponse) else None

    app.add_middleware(McpRequestGuard, admit=admit_mcp, allow=allow_mcp, retry_after=int(mcp_limiter.window))
