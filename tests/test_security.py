"""A public MCP deployment cannot bypass authorization or its request limit."""

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from logiops.api import create_app


BASE_URL = "http://127.0.0.1:8000"
TOKEN = "a" * 40


def test_mcp_and_rest_require_token_and_limit_requests(tmp_path):
    async def run():
        app = create_app(tmp_path / "secured.sqlite3", access_token=TOKEN, mcp_limit_per_minute=20)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                assert (await http.get("/incidents/SHIP-421")).status_code == 401
                assert (await http.post("/mcp")).status_code == 401
                assert (await http.get("/healthz")).status_code == 200
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL,
                headers={"Authorization": f"Bearer {TOKEN}"},
            ) as authorized:
                assert (await authorized.get("/incidents/SHIP-421")).status_code == 200
                async with streamable_http_client(
                    f"{BASE_URL}/mcp", http_client=authorized
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
                        assert shipment.structuredContent["id"] == "SHIP-421"
                responses = [await authorized.post("/mcp") for _ in range(20)]
                assert any(response.status_code == 429 for response in responses)

    asyncio.run(run())


def test_agent_endpoint_has_its_own_limit_and_internal_mcp_calls_are_exempt(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(
            tmp_path / "limits.sqlite3", access_token=TOKEN,
            mcp_limit_per_minute=3, agent_limit_per_minute=2,
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL,
                headers={"Authorization": f"Bearer {TOKEN}"},
            ) as http:
                statuses = [
                    (await http.post("/incidents/SHIP-421/agent/investigate", json={})).status_code
                    for _ in range(3)
                ]
                assert statuses == [200, 200, 429]
                forged = [
                    (await http.post("/mcp", headers={"x-logiops-internal": "guess"})).status_code
                    for _ in range(4)
                ]
                assert 429 in forged

    asyncio.run(run())


def test_cloudfront_viewer_address_keys_the_limit_only_when_trusted(tmp_path, monkeypatch):
    async def statuses(trust):
        if trust:
            monkeypatch.setenv("LOGIOPS_TRUST_CLOUDFRONT", "1")
        else:
            monkeypatch.delenv("LOGIOPS_TRUST_CLOUDFRONT", raising=False)
        app = create_app(tmp_path / f"cf-{trust}.sqlite3", access_token=TOKEN, mcp_limit_per_minute=2)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL,
                headers={"Authorization": f"Bearer {TOKEN}"},
            ) as http:
                result = []
                for viewer in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
                    response = await http.post("/mcp", headers={"cloudfront-viewer-address": f"{viewer}:443"})
                    result.append(response.status_code)
                return result

    trusted = asyncio.run(statuses(True))
    untrusted = asyncio.run(statuses(False))
    assert 429 not in trusted
    assert untrusted[-1] == 429


def test_non_ascii_token_is_rejected_and_responses_are_not_cacheable(tmp_path):
    async def run():
        app = create_app(tmp_path / "headers.sqlite3", access_token=TOKEN)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                odd = await http.get("/incidents/SHIP-421", headers={"Authorization": "Bearer ñ".encode()})
                assert odd.status_code == 401
                assert odd.headers["www-authenticate"] == "Bearer"
                ok = await http.get("/incidents/SHIP-421", headers={"Authorization": f"Bearer {TOKEN}"})
                assert ok.status_code == 200
                assert ok.headers["cache-control"] == "no-store"

    asyncio.run(run())
