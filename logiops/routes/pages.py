"""The two pages, the MCP Apps sandbox proxy, the static assets and the health check."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..security import SANDBOX_PATH
from .context import Context

LOOPBACK_PAIRS = {"127.0.0.1": "localhost", "localhost": "127.0.0.1"}
SANDBOX_META = '<meta name="logiops-sandbox-origin" content="">'
ASSET_TYPES = {".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2"}


def router(ctx: Context, *, auth_enabled: bool) -> APIRouter:
    public_host, sandbox_host = ctx.public_host, ctx.sandbox_host
    routes = APIRouter()

    def origins(request: Request) -> tuple[str | None, str | None]:
        """(page origin, sandbox origin) for this request; (None, None) if there is no safe pair.

        Public mode uses the two configured HTTPS hostnames. Locally, 127.0.0.1 and
        localhost are different origins on the same server, so each one sandboxes the other.
        """
        if public_host:
            return f"https://{public_host}", (f"https://{sandbox_host}" if sandbox_host else None)
        name, _, port = request.headers.get("host", "").partition(":")
        other = LOOPBACK_PAIRS.get(name.lower())
        if other is None or (port and not port.isdigit()):
            return None, None
        scheme = request.url.scheme
        suffix = f":{port}" if port else ""
        return f"{scheme}://{name.lower()}{suffix}", f"{scheme}://{other}{suffix}"

    if not auth_enabled:
        @routes.get("/auth/config", include_in_schema=False)
        async def auth_off() -> dict[str, Any]:
            return {"enabled": False}

    @routes.get("/demo", include_in_schema=False)
    async def demo_page(request: Request) -> HTMLResponse:
        _page, sandbox = origins(request)
        return HTMLResponse(ctx.demo_page_html.replace(SANDBOX_META, SANDBOX_META.replace('content=""', f'content="{html.escape(sandbox or "")}"')))

    @routes.get("/console", include_in_schema=False)
    async def console_page() -> HTMLResponse:
        """The operator console: the same incidents, plans, approvals and audit trail as the device, in full."""
        return HTMLResponse(ctx.console_page_html)

    @routes.get(SANDBOX_PATH, include_in_schema=False)
    async def mcp_app_sandbox(request: Request) -> Response:
        """Sandbox proxy for MCP Apps views; served only on the sandbox origin, never with data."""
        if public_host:
            if not sandbox_host or request.headers.get("host", "").split(":")[0].lower() != sandbox_host:
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            host_origin = f"https://{public_host}"
        else:
            _self, host_origin = origins(request)
            if host_origin is None:
                return JSONResponse(status_code=404, content={"detail": "Not found"})
        policy = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
            f"connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors {host_origin}"
        )
        return HTMLResponse(ctx.sandbox_page, headers={
            "Content-Security-Policy": policy, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
        })

    @routes.get("/assets/{name:path}", include_in_schema=False)
    async def demo_asset(name: str) -> Response:
        """The demo's stylesheets, scripts and images: only the files under static/ with an allowed
        extension, listed in DEMO_ASSETS and read once at start-up."""
        body = ctx.demo_assets.get(name)
        if body is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return Response(body, media_type=ASSET_TYPES[Path(name).suffix])

    @routes.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "telemetry": ctx.telemetry}

    return routes
