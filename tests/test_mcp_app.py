"""MCP Apps: investigate_incident declares an interactive view that can never approve."""

import asyncio
import re
import tarfile

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import AnyUrl

from logiops.api import create_app
from logiops.mcp_server import UI_MIME_TYPE, UI_URI
from scripts.deploy_ec2 import package

BASE_URL = "http://127.0.0.1:8000"


def test_tool_declares_ui_and_resource_serves_a_self_contained_view(tmp_path):
    async def run():
        app = create_app(tmp_path / "app.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        meta = {tool.name: tool.meta or {} for tool in tools}
                        with_view = {name for name, value in meta.items() if value.get("ui", {}).get("resourceUri")}
                        assert with_view == {"investigate_incident"}
                        assert meta["investigate_incident"]["ui"]["resourceUri"] == UI_URI
                        assert meta["investigate_incident"]["ui/resourceUri"] == UI_URI
                        # Views may call server tools unless visibility says otherwise:
                        # the only state-changing tool is model-only.
                        assert meta["execute_approved_plan"]["ui"]["visibility"] == ["model"]
                        assert not {"approve_plan", "approve"} & set(meta)

                        contents = (await session.read_resource(AnyUrl(UI_URI))).contents
                        assert contents[0].mimeType == UI_MIME_TYPE == "text/html;profile=mcp-app"
                        html = contents[0].text
                        assert html.lstrip().lower().startswith("<!doctype html")
                        assert "ui/initialize" in html and "2026-01-26" in html
                        assert not re.search(r"<script[^>]+src=", html), "the view must not load remote scripts"
                        for network in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "new Image"):
                            assert network not in html, network
                        assert not re.search(r"\blocation\b", html), "the view must not navigate"
                        assert "ui/resource-teardown" in html

                        # The tool result the agent relies on is unchanged.
                        result = await session.call_tool("investigate_incident", {"shipment_id": "SHIP-421"})
                        assert len(result.structuredContent["plans"]) == 3

    asyncio.run(run())


SANDBOX_META = re.compile(r'<meta name="logiops-sandbox-origin" content="([^"]*)">')


def get(app, path, host, **headers):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}") as http:
            return await http.get(path, headers={"host": host, **headers})
    return asyncio.run(run())


def test_local_demo_uses_the_other_loopback_name_as_sandbox_origin(tmp_path):
    app = create_app(tmp_path / "local.sqlite3")
    assert SANDBOX_META.search(get(app, "/demo", "127.0.0.1:8000").text).group(1) == "http://localhost:8000"
    assert SANDBOX_META.search(get(app, "/demo", "localhost:8000").text).group(1) == "http://127.0.0.1:8000"
    # Anything else has no safe second origin, so the host shows no MCP App.
    assert SANDBOX_META.search(get(app, "/demo", "10.0.0.5:8000").text).group(1) == ""
    proxy = get(app, "/mcp-app/sandbox.html", "localhost:8000")
    assert proxy.status_code == 200
    policy = proxy.headers["content-security-policy"]
    assert "frame-ancestors http://127.0.0.1:8000" in policy and "connect-src 'none'" in policy
    assert get(app, "/mcp-app/sandbox.html", "10.0.0.5:8000").status_code == 404


def public_app(tmp_path, monkeypatch, sandbox_host="sandbox.example.com"):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_ACCESS_TOKEN", "p" * 40)
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "demo.example.com")
    if sandbox_host:
        monkeypatch.setenv("LOGIOPS_SANDBOX_HOST", sandbox_host)
    return create_app(tmp_path / "public.sqlite3")


def test_public_sandbox_origin_serves_only_the_proxy(tmp_path, monkeypatch):
    app = public_app(tmp_path, monkeypatch)
    token = {"authorization": "Bearer " + "p" * 40}
    assert SANDBOX_META.search(get(app, "/demo", "demo.example.com").text).group(1) == "https://sandbox.example.com"
    proxy = get(app, "/mcp-app/sandbox.html", "sandbox.example.com")
    assert proxy.status_code == 200
    assert "frame-ancestors https://demo.example.com" in proxy.headers["content-security-policy"]
    assert get(app, "/mcp-app/sandbox.html", "demo.example.com").status_code == 404
    for path in ("/incidents/SHIP-421", "/demo", "/mcp", "/healthz"):
        assert get(app, path, "sandbox.example.com", **token).status_code == 404, path
    assert get(app, "/incidents/SHIP-421", "demo.example.com", **token).status_code == 200


def test_public_mode_without_a_sandbox_host_shows_no_app(tmp_path, monkeypatch):
    app = public_app(tmp_path, monkeypatch, sandbox_host=None)
    assert SANDBOX_META.search(get(app, "/demo", "demo.example.com").text).group(1) == ""
    assert get(app, "/mcp-app/sandbox.html", "demo.example.com").status_code == 404


@pytest.mark.parametrize("value", ["demo.example.com", "https://sandbox.example.com", "sandbox.example.com:8443"])
def test_sandbox_host_must_be_a_different_bare_hostname(tmp_path, monkeypatch, value):
    with pytest.raises(RuntimeError, match="LOGIOPS_SANDBOX_HOST"):
        public_app(tmp_path, monkeypatch, sandbox_host=value)


def test_proxy_and_host_follow_the_sandbox_contract(tmp_path):
    app = create_app(tmp_path / "contract.sqlite3")
    proxy = get(app, "/mcp-app/sandbox.html", "localhost:8000").text
    script = get(app, "/assets/demo.js", "127.0.0.1:8000").text
    # Proxy: announces itself, loads the raw HTML with the CSP placed before any markup,
    # never grants same-origin or top navigation, and keeps sandbox-* messages to itself.
    assert "ui/notifications/sandbox-proxy-ready" in proxy and "ui/notifications/sandbox-resource-ready" in proxy
    assert "`<!doctype html>${meta}${body}`" in proxy
    grantable = re.search(r"const GRANTABLE = new Set\(\[([^\]]*)\]\)", proxy).group(1)
    assert "allow-same-origin" not in grantable and "allow-top-navigation" not in grantable
    assert 'const SANDBOX_PREFIX = "ui/notifications/sandbox-"' in proxy and "isProxyMethod(message)" in proxy
    assert "event.origin === hostOrigin" in proxy and "connect-src ${list(connect, \"'none'\")}" in proxy
    # Host: proxy on another origin with the spec's tokens, origin-checked messages,
    # teardown before removal, no capabilities offered to the view.
    assert 'frame.setAttribute("sandbox", "allow-scripts allow-same-origin")' in script
    assert "event.origin !== SANDBOX_ORIGIN" in script and "srcdoc" not in script
    assert "ui/resource-teardown" in script and "hostCapabilities: {}" in script
    assert "url.origin !== location.origin" in script  # fail closed on a same-origin "sandbox"


def test_release_archive_includes_the_view():
    archive, _ = package()
    with tarfile.open(archive, "r:gz") as release:
        names = release.getnames()
        assert "logiops/static/resolution_options.html" in names
        assert "logiops/static/mcp_app_sandbox.html" in names
