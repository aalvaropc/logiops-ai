import asyncio
import json

import httpx
import pytest

from logiops.api import create_app
from logiops.mcp_transport import McpRequestGuard
from tests.test_oauth import BASE_URL, MCP_HEADERS, bearer, settings, token

TOKEN = "a" * 40


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


def serve(tmp_path, work, **app_kwargs):
    async def run():
        app = create_app(tmp_path / "guard.sqlite3", **app_kwargs)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=BASE_URL) as client:
                return await work(client)
    return asyncio.run(run())


LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def test_a_flood_of_invalid_tokens_does_not_use_up_the_limit_of_a_valid_one(tmp_path):
    async def work(http):
        flood = [await http.post("/mcp", headers={**MCP_HEADERS, **bearer("garbage")}, json=LIST_TOOLS) for _ in range(5)]
        valid = await http.post("/mcp", headers={**MCP_HEADERS, **bearer(token())}, json=LIST_TOOLS)
        return [item.status_code for item in flood], valid.status_code

    flood, valid = serve(tmp_path, work, oauth=settings(), mcp_limit_per_minute=2)
    assert flood == [401] * 5 and valid == 200


@pytest.mark.parametrize("credentials", [{}, {"Authorization": "Bearer wrong"}])
def test_authentication_comes_before_the_body_check_with_a_static_token(tmp_path, credentials):
    async def work(http):
        malformed = await http.post("/mcp", headers={**MCP_HEADERS, **credentials}, content=b"{")
        authorized = await http.post("/mcp", headers={**MCP_HEADERS, **bearer(TOKEN)}, content=b"{")
        return malformed, authorized

    malformed, authorized = serve(tmp_path, work, access_token=TOKEN)
    assert malformed.status_code == 401 and malformed.headers["www-authenticate"].startswith("Bearer")
    assert authorized.status_code == 400 and authorized.json()["error"]["code"] == -32700


def test_authentication_comes_before_the_body_check_with_oauth(tmp_path):
    async def work(http):
        return await http.post("/mcp", headers={**MCP_HEADERS, **bearer("garbage")}, content=b"{")

    response = serve(tmp_path, work, oauth=settings())
    assert response.status_code == 401 and "invalid_token" in response.headers["www-authenticate"]


@pytest.mark.parametrize("app_kwargs, credentials", [
    ({"access_token": TOKEN}, {}),
    ({"oauth": settings()}, bearer("garbage")),
])
def test_an_unauthenticated_request_is_not_read(tmp_path, app_kwargs, credentials):
    async def work(http):
        async def chunks():
            yield b"x" * 1024
            raise AssertionError("an unauthenticated body must not be read")
        return await http.post("/mcp", headers={**MCP_HEADERS, **credentials}, content=chunks())

    assert serve(tmp_path, work, **app_kwargs).status_code == 401


def test_the_guard_answers_are_not_cached_and_a_limit_says_when_to_retry(tmp_path):
    async def work(http):
        async def chunks():
            yield b"x" * (4 * 1024 * 1024 + 1)
        malformed = await http.post("/mcp", headers=MCP_HEADERS, content=b"{")
        too_large = await http.post("/mcp", headers=MCP_HEADERS, content=chunks())
        limited = await http.post("/mcp", headers=MCP_HEADERS, content=b"{")
        return malformed, too_large, limited

    malformed, too_large, limited = serve(tmp_path, work, oauth=settings(), mcp_limit_per_minute=2)
    assert (malformed.status_code, too_large.status_code) == (400, 413) and limited.status_code == 429
    assert all(item.headers["cache-control"] == "no-store" for item in (malformed, too_large, limited))
    assert 1 <= int(limited.headers["retry-after"]) <= 60


def test_without_any_token_the_demo_still_validates_and_limits(tmp_path):
    async def work(http):
        valid = await http.post("/mcp", headers=MCP_HEADERS, json=LIST_TOOLS)
        malformed = await http.post("/mcp", headers=MCP_HEADERS, content=b"[]")
        limited = await http.post("/mcp", headers=MCP_HEADERS, json=LIST_TOOLS)
        return valid.status_code, malformed.status_code, limited.status_code

    assert serve(tmp_path, work, mcp_limit_per_minute=2) == (200, 400, 429)


def test_a_valid_body_sent_in_fragments_reaches_the_server_whole(tmp_path):
    body = json.dumps(LIST_TOOLS).encode()

    async def work(http):
        async def chunks():
            for start in range(0, len(body), 7):
                yield body[start:start + 7]
        return await http.post("/mcp", headers={**MCP_HEADERS, **bearer(token())}, content=chunks())

    response = serve(tmp_path, work, oauth=settings())
    assert response.status_code == 200 and "get_shipment" in response.text


def test_a_batch_is_an_invalid_request(tmp_path):
    async def work(http):
        return await http.post("/mcp", headers=MCP_HEADERS, content=json.dumps([LIST_TOOLS]).encode())

    response = serve(tmp_path, work, oauth=settings())
    assert response.status_code == 400 and response.json()["error"]["code"] == -32600


def test_a_client_that_disconnects_while_sending_gets_no_response_and_no_work():
    calls, sent = [], []

    async def app(scope, receive, send):
        calls.append(scope)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def admit(_request):
        return None

    guard = McpRequestGuard(app, admit=admit, allow=lambda _request: True)
    asyncio.run(guard({"type": "http", "method": "POST", "path": "/mcp", "headers": [], "query_string": b""}, receive, send))
    assert calls == [] and sent == []


def test_the_sandbox_host_never_reaches_the_mcp_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "demo.example.com")
    monkeypatch.setenv("LOGIOPS_SANDBOX_HOST", "sandbox.example.com")

    async def work(http):
        sandbox = await http.post("/mcp", headers={**MCP_HEADERS, "host": "sandbox.example.com"}, content=b"{")
        main = await http.post("/mcp", headers={**MCP_HEADERS, **bearer(TOKEN), "host": "demo.example.com"}, content=b"{")
        return sandbox, main

    sandbox, main = serve(tmp_path, work, access_token=TOKEN, mcp_limit_per_minute=1)
    assert sandbox.status_code == 404 and main.status_code == 400
