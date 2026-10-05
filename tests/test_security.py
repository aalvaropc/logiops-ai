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
