import asyncio

import httpx
import pytest

from logiops.api import create_app
from tests.test_oauth import BASE_URL, MCP_HEADERS, settings


@pytest.mark.parametrize("body", [b'{', b'[]', b'null', b'{"jsonrpc":"2.0","id":1,"method":"resources/read","params":"bad"}'])
def test_malformed_requests_are_limited_and_rejected(tmp_path, body):
    async def work():
        app = create_app(tmp_path / "requests.sqlite3", oauth=settings(), mcp_limit_per_minute=1)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=BASE_URL) as client:
                first = await client.post("/mcp", headers=MCP_HEADERS, content=body)
                second = await client.post("/mcp", headers=MCP_HEADERS, content=body)
                assert first.status_code == 400
                assert first.json()["error"]["code"] in (-32700, -32600)
                assert second.status_code == 429
    asyncio.run(work())


def test_oversized_chunked_request_is_rejected_without_reading_the_rest(tmp_path):
    async def work():
        app = create_app(tmp_path / "large.sqlite3", oauth=settings())
        async def chunks():
            yield b'x' * (4 * 1024 * 1024 + 1)
            raise AssertionError("the request limit must stop reading")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
                response = await client.post("/mcp", headers=MCP_HEADERS, content=chunks())
                assert response.status_code == 413
    asyncio.run(work())
