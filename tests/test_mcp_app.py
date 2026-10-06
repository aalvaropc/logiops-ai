"""MCP Apps: investigate_incident declares an interactive view that can never approve."""

import asyncio
import re
import tarfile

import httpx
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
                        with_ui = {tool.name: tool.meta for tool in tools if tool.meta}
                        assert set(with_ui) == {"investigate_incident"}
                        assert with_ui["investigate_incident"]["ui"]["resourceUri"] == UI_URI
                        assert with_ui["investigate_incident"]["ui/resourceUri"] == UI_URI
                        assert not {"approve_plan", "approve"} & {tool.name for tool in tools}

                        contents = (await session.read_resource(AnyUrl(UI_URI))).contents
                        assert contents[0].mimeType == UI_MIME_TYPE == "text/html;profile=mcp-app"
                        html = contents[0].text
                        assert html.lstrip().lower().startswith("<!doctype html")
                        assert "ui/initialize" in html and "2026-01-26" in html
                        assert not re.search(r"<script[^>]+src=", html), "the view must not load remote scripts"
                        assert "fetch(" not in html and "XMLHttpRequest" not in html

                        # The tool result the agent relies on is unchanged.
                        result = await session.call_tool("investigate_incident", {"shipment_id": "SHIP-421"})
                        assert len(result.structuredContent["plans"]) == 3

    asyncio.run(run())


def test_demo_hosts_the_view_in_an_opaque_sandbox(tmp_path):
    async def run():
        app = create_app(tmp_path / "sandbox.sqlite3")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
            page = (await http.get("/demo")).text
            script = (await http.get("/assets/demo.js")).text
        frame = re.search(r'<iframe id="mcp-app-frame"[^>]*>', page).group(0)
        assert 'sandbox="allow-scripts"' in frame and "allow-same-origin" not in frame
        assert "connect-src 'none'" in script and "event.source !== frame.contentWindow" in script
        assert "hostCapabilities: {}" in script  # the view cannot call MCP tools through the host

    asyncio.run(run())


def test_release_archive_includes_the_view():
    archive, _ = package()
    with tarfile.open(archive, "r:gz") as release:
        assert "logiops/static/resolution_options.html" in release.getnames()
