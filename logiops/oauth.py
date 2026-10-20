"""OAuth 2.1 for the MCP server and the demo, with Amazon Cognito as the authorization server.

LogiOps is the protected resource `https://<host>/mcp`. It publishes:
- protected-resource metadata (RFC 9728);
- because Cognito's discovery document does not list PKCE methods, its own authorization-server
  metadata (RFC 8414). That document points at Cognito's authorize endpoint and at a token
  endpoint here, which forwards the code and refresh grants of the allowed public clients to
  Cognito.

Access tokens are Cognito JWTs. They are checked for:
- the signature, against the user pool's JWKS;
- the issuer;
- `token_use` "access";
- an allowed `client_id`;
- the expiry;
- the scope that an action needs.

A visitor without a token is a guest who can read. Approving, executing, booking and changing data
answer 401 with a `WWW-Authenticate` header that names the metadata and the scope to ask for.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .identity import Actor

OPERATE = "incidents.operate"
BOOK = "bookings.write"
GUEST = Actor("guest", "guest", "Guest")
ISSUER = re.compile(r"^https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com/[A-Za-z0-9_-]+$")
DOMAIN = re.compile(r"^https://[a-z0-9.-]+$")
MCP_TOOLS = {"execute_approved_plan": OPERATE, "get_booking": OPERATE, "quote_carrier_booking": BOOK, "book_carrier": BOOK}
GUEST_POSTS = re.compile(r"^/(?:mcp/?|agent/briefing|incidents/[^/]+/(?:investigate|agent/investigate(?:/stream)?|agent/ask))$")
BOOKING_PATHS = re.compile(r"^/(?:incidents/[^/]+/bookings/quote|quotes/[^/]+/confirm)$")


class InvalidToken(Exception):
    pass


@dataclass
class OAuthSettings:
    """Cognito settings; `fetch_jwks` and `transport` are injected by tests."""

    issuer: str
    domain: str
    client_ids: tuple[str, ...]
    fetch_jwks: Callable[[], dict[str, Any]] | None = None
    transport: httpx.AsyncBaseTransport | None = None
    _keys: dict[str, Any] = field(default_factory=dict, repr=False)
    _fetched_at: float | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if not ISSUER.fullmatch(self.issuer):
            raise RuntimeError("LOGIOPS_COGNITO_ISSUER must be https://cognito-idp.<region>.amazonaws.com/<pool id>")
        if not DOMAIN.fullmatch(self.domain):
            raise RuntimeError("LOGIOPS_COGNITO_DOMAIN must be the user pool domain, such as https://name.auth.us-east-1.amazoncognito.com")
        if not self.client_ids or not all(re.fullmatch(r"[A-Za-z0-9]{1,128}", item) for item in self.client_ids):
            raise RuntimeError("LOGIOPS_COGNITO_CLIENT_ID must name the app client")

    @classmethod
    def from_env(cls) -> "OAuthSettings | None":
        issuer = os.environ.get("LOGIOPS_COGNITO_ISSUER", "").strip()
        if not issuer:
            return None
        clients = [os.environ.get("LOGIOPS_COGNITO_CLIENT_ID", ""), *os.environ.get("LOGIOPS_COGNITO_EXTRA_CLIENT_IDS", "").split(",")]
        return cls(issuer.rstrip("/"), os.environ.get("LOGIOPS_COGNITO_DOMAIN", "").strip().rstrip("/"),
                   tuple(item.strip() for item in clients if item.strip()))

    def _jwks(self) -> dict[str, Any]:
        if self.fetch_jwks:
            return self.fetch_jwks()
        response = httpx.get(f"{self.issuer}/.well-known/jwks.json", timeout=5)
        response.raise_for_status()
        return response.json()

    def _key(self, kid: str) -> Any:
        with self._lock:
            if kid not in self._keys and (self._fetched_at is None or time.monotonic() - self._fetched_at > 60):
                self._fetched_at = time.monotonic()
                self._keys = {item["kid"]: jwt.PyJWK(item).key for item in self._jwks().get("keys", []) if item.get("kid")}
            key = self._keys.get(kid)
        if key is None:
            raise InvalidToken("The token was not signed by this user pool")
        return key

    def verify(self, token: str) -> tuple[Actor, set[str]]:
        """The signed-in user and the token's scopes, or InvalidToken."""
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(
                token, self._key(str(header.get("kid", ""))), algorithms=["RS256"], issuer=self.issuer, leeway=30,
                options={"require": ["exp", "iat", "sub", "token_use", "client_id"], "verify_aud": False},
            )
        except InvalidToken:
            raise
        except (jwt.PyJWTError, httpx.HTTPError, ValueError, KeyError) as exc:
            raise InvalidToken("The access token is invalid or expired") from exc
        if claims["token_use"] != "access":
            raise InvalidToken("Send the access token, not the ID token")
        if claims["client_id"] not in self.client_ids:
            raise InvalidToken("The token was issued to another client")
        name = str(claims.get("username") or "Signed-in user")
        return Actor("user", str(claims["sub"]), name), set(str(claims.get("scope", "")).split())


def base_url(request: Request, public_host: str | None) -> str:
    return f"https://{public_host}" if public_host else f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"


def scope_name(base: str, scope: str) -> str:
    return f"{base}/mcp/{scope}"


def challenge(base: str, scope: str | None = None, error: str | None = None, description: str | None = None) -> str:
    parts = []
    if error:
        parts.append(f'error="{error}"')
    if description:
        parts.append(f'error_description="{description}"')
    parts.append(f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"')
    if scope:
        parts.append(f'scope="{scope_name(base, scope)}"')
    return "Bearer " + ", ".join(parts)


async def needed_scope(request: Request) -> str | None:
    """The scope a request needs beyond reading, or None for what a guest may do."""
    path, method = request.url.path, request.method
    if path == "/mcp" or path == "/mcp/":
        if method != "POST":
            return None
        try:
            payload = json.loads(await request.body() or b"null")
        except ValueError:
            return None
        messages = payload if isinstance(payload, list) else [payload]
        found = [
            MCP_TOOLS.get(str(message.get("params", {}).get("name")))
            for message in messages
            if isinstance(message, dict) and message.get("method") == "tools/call" and isinstance(message.get("params"), dict)
        ] + [
            OPERATE for message in messages
            if isinstance(message, dict) and message.get("method") == "resources/read"
            and str((message.get("params") or {}).get("uri", "")).startswith("receipt://")
        ]
        return BOOK if BOOK in found else (OPERATE if OPERATE in found else None)
    if path.startswith("/bookings/"):
        return OPERATE
    if method in ("GET", "HEAD", "OPTIONS"):
        return None
    if BOOKING_PATHS.fullmatch(path):
        return BOOK
    if GUEST_POSTS.fullmatch(path):
        return None
    return OPERATE


def install_oauth(app: FastAPI, settings: OAuthSettings, public_host: str | None) -> None:
    """Discovery documents, the demo's sign-in settings, and the token endpoint."""

    def resource_metadata(request: Request) -> dict[str, Any]:
        base = base_url(request, public_host)
        return {
            "resource": f"{base}/mcp", "authorization_servers": [base],
            "scopes_supported": [scope_name(base, OPERATE), scope_name(base, BOOK)],
            "bearer_methods_supported": ["header"], "resource_name": "LogiOps AI",
            "resource_documentation": "https://github.com/aalvaropc/logiops-ai",
        }

    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    async def protected_resource(request: Request) -> dict[str, Any]:
        return resource_metadata(request)

    @app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
    async def protected_resource_mcp(request: Request) -> dict[str, Any]:
        return resource_metadata(request)

    @app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    async def authorization_server(request: Request) -> dict[str, Any]:
        base = base_url(request, public_host)
        return {
            "issuer": base,
            "authorization_endpoint": f"{settings.domain}/oauth2/authorize",
            "token_endpoint": f"{base}/auth/token",
            "revocation_endpoint": f"{settings.domain}/oauth2/revoke",
            "userinfo_endpoint": f"{settings.domain}/oauth2/userInfo",
            "jwks_uri": f"{settings.issuer}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["openid", "email", scope_name(base, OPERATE), scope_name(base, BOOK)],
        }

    @app.get("/auth/config", include_in_schema=False)
    async def auth_config(request: Request) -> dict[str, Any]:
        base = base_url(request, public_host)
        return {
            "enabled": True, "client_id": settings.client_ids[0],
            "authorize_endpoint": f"{settings.domain}/oauth2/authorize", "token_endpoint": "/auth/token",
            "logout_endpoint": f"{settings.domain}/logout",
            "scope": " ".join(["openid", "email", scope_name(base, OPERATE), scope_name(base, BOOK)]),
        }

    @app.post("/auth/token", include_in_schema=False)
    async def token(request: Request) -> JSONResponse:
        """Forward an authorization-code (with its PKCE verifier) or refresh grant of an allowed public client."""
        form = dict(await request.form())
        grant = form.get("grant_type")
        allowed = {"authorization_code": ("code", "redirect_uri", "code_verifier"), "refresh_token": ("refresh_token",)}
        if grant not in allowed or form.get("client_id") not in settings.client_ids:
            return JSONResponse(status_code=400, content={"error": "invalid_request" if grant in allowed else "unsupported_grant_type"})
        if any(not str(form.get(name) or "") for name in allowed[str(grant)]):
            return JSONResponse(status_code=400, content={"error": "invalid_request"})
        body = {key: str(form[key]) for key in ("grant_type", "client_id", *allowed[str(grant)])}
        async with httpx.AsyncClient(transport=settings.transport, timeout=10) as client:
            try:
                upstream = await client.post(f"{settings.domain}/oauth2/token", content=urlencode(body),
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
            except httpx.HTTPError:
                return JSONResponse(status_code=502, content={"error": "temporarily_unavailable"})
        try:
            content = upstream.json()
        except ValueError:
            content = {"error": "server_error"}
        return JSONResponse(status_code=upstream.status_code, content=content, headers={"Cache-Control": "no-store"})


async def verify_async(settings: OAuthSettings, token: str) -> tuple[Actor, set[str]]:
    return await asyncio.to_thread(settings.verify, token)
