"""Walk a deployed LogiOps's OAuth discovery the way an MCP client does; no credentials, no changes.

1. An unauthenticated MCP call of a write tool answers 401, naming the resource metadata and the scope.
2. The protected-resource metadata (RFC 9728) names `<base>/mcp` and its authorization server.
3. The authorization-server metadata (RFC 8414) offers PKCE S256, an authorize and a token endpoint.
4. A PKCE authorization URL for the demo client opens the hosted sign-in page.

    uv run python scripts/check_oauth.py https://<cloudfront-domain>
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import sys
from typing import Any
from urllib.parse import urlencode

import httpx

CHALLENGE = re.compile(r'(\w+)="([^"]*)"')
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json",
               "mcp-protocol-version": "2025-11-25"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL  {message}")


async def check(app: httpx.AsyncClient, outside: httpx.AsyncClient, base: str) -> list[str]:
    lines = []
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "execute_approved_plan", "arguments": {"shipment_id": "SHIP-421", "plan_id": "x", "source_version": 1}}}
    denied = await app.post("/mcp", json=call, headers=MCP_HEADERS)
    header = denied.headers.get("www-authenticate", "")
    fields = dict(CHALLENGE.findall(header))
    if denied.status_code != 401 or not header.startswith("Bearer ") or "resource_metadata" not in fields or "scope" not in fields:
        fail(f"a guest's execute_approved_plan should answer 401 with resource_metadata and scope, got {denied.status_code} {header!r}")
    lines.append(f"PASS  guest write tool -> 401, scope {fields['scope']}")
    metadata_url = fields["resource_metadata"]
    if not metadata_url.startswith(f"{base}/.well-known/oauth-protected-resource"):
        fail(f"resource_metadata points elsewhere: {metadata_url}")
    resource = (await app.get(metadata_url.removeprefix(base))).json()
    if resource.get("resource") != f"{base}/mcp" or not resource.get("authorization_servers"):
        fail(f"protected-resource metadata is wrong: {resource}")
    lines.append(f"PASS  RFC 9728: resource {resource['resource']}, server {resource['authorization_servers'][0]}")
    server_url = resource["authorization_servers"][0].rstrip("/")
    server = (await app.get(f"{server_url.removeprefix(base)}/.well-known/oauth-authorization-server")).json()
    if "S256" not in server.get("code_challenge_methods_supported", []) or server.get("issuer") != server_url:
        fail(f"authorization-server metadata lacks S256 or its issuer: {server}")
    if "none" not in server.get("token_endpoint_auth_methods_supported", []):
        fail("the token endpoint does not accept public clients")
    lines.append(f"PASS  RFC 8414: S256, authorize {server['authorization_endpoint']}, token {server['token_endpoint']}")
    config: dict[str, Any] = (await app.get("/auth/config")).json()
    if not config.get("enabled"):
        fail("/auth/config says sign-in is off")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({
        "response_type": "code", "client_id": config["client_id"], "redirect_uri": f"{base}/demo", "scope": config["scope"],
        "state": secrets.token_urlsafe(24), "code_challenge": challenge, "code_challenge_method": "S256",
    })
    page = await outside.get(f"{server['authorization_endpoint']}?{query}", follow_redirects=True)
    if page.status_code >= 400:
        fail(f"the hosted sign-in page answered {page.status_code} for the demo client's PKCE request")
    lines.append(f"PASS  PKCE authorization request opens the sign-in page ({page.status_code})")
    return lines


async def run(base: str) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=20) as app, httpx.AsyncClient(timeout=20) as outside:
        for line in await check(app, outside, base):
            print(line)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise SystemExit("Usage: uv run python scripts/check_oauth.py https://<cloudfront-domain>")
    asyncio.run(run(sys.argv[1].rstrip("/")))
