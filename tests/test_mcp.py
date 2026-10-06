"""Interop with the official MCP client over Streamable HTTP."""

import asyncio

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from logiops.api import create_app


BASE_URL = "http://127.0.0.1:8000"


def test_mcp_protocol_and_human_approval_boundary(tmp_path):
    async def run():
        app = create_app(tmp_path / "mcp.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as http_client:
                async with streamable_http_client(
                    f"{BASE_URL}/mcp", http_client=http_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        assert initialized.protocolVersion == "2025-11-25"
                        listed = await session.list_tools()
                        names = {tool.name for tool in listed.tools}
                        assert {"get_shipment", "investigate_incident", "execute_approved_plan"} <= names
                        assert "approve_plan" not in names

                        shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
                        assert shipment.structuredContent["units_on_delayed_route"] == 20
                        investigated = await session.call_tool(
                            "investigate_incident", {"shipment_id": "SHIP-421"}
                        )
                        plans = investigated.structuredContent["plans"]
                        assert len(plans) == 3
                        plan = next(item for item in plans if item["kind"] == "split-express")
                        arguments = {
                            "shipment_id": "SHIP-421",
                            "plan_id": plan["id"],
                            "source_version": plan["source_version"],
                        }
                        blocked = await session.call_tool("execute_approved_plan", arguments)
                        assert blocked.isError is True
                        assert not (await http_client.get("/incidents/SHIP-421")).json()["executions"]

                        approval = await http_client.post(
                            "/incidents/SHIP-421/approvals",
                            json={
                                "plan_id": plan["id"],
                                "source_version": plan["source_version"],
                                "approved_by": "demo-operator",
                            },
                        )
                        assert approval.status_code == 200
                        executed = await session.call_tool("execute_approved_plan", arguments)
                        assert executed.isError is False
                        assert executed.structuredContent["status"] == "verified_operationally"
                        repeated = await session.call_tool("execute_approved_plan", arguments)
                        assert repeated.structuredContent == executed.structuredContent
                        snapshot = (await http_client.get("/incidents/SHIP-421")).json()
                        assert len(snapshot["executions"]) == 1
                        status = (await session.call_tool(
                            "get_execution_status", {"shipment_id": "SHIP-421"}
                        )).structuredContent
                        assert status["status"] == "verified"
                        # Execution bumped the version, so the version-1 approval is no longer current.
                        assert status["source_version"] == 2 and status["approvals"] == []
                        # Event payloads (including old agent traces) stay out of the model context.
                        assert status["events"] and all(set(e) == {"sequence", "name", "recorded_at"} for e in status["events"])

    asyncio.run(run())


def test_mcp_rejects_untrusted_browser_origin(tmp_path):
    async def run():
        app = create_app(tmp_path / "origin.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as client:
                response = await client.post(
                    "/mcp",
                    headers={
                        "Origin": "https://untrusted.example",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2025-11-25",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    },
                )
                assert response.status_code == 403

    asyncio.run(run())


def test_public_mcp_accepts_only_configured_cloudfront_host(tmp_path, monkeypatch):
    host = "d123example.cloudfront.net"
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", host)

    async def run():
        app = create_app(tmp_path / "public.sqlite3", access_token="a" * 40)
        async with app.router.lifespan_context(app):
            headers = {"Authorization": f"Bearer {'a' * 40}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=f"https://{host}", headers=headers
            ) as client:
                async with streamable_http_client(
                    f"https://{host}/mcp", http_client=client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        assert (await session.initialize()).protocolVersion == "2025-11-25"
                        shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
                        assert shipment.structuredContent["id"] == "SHIP-421"
                request = {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "host-test", "version": "1"},
                    },
                }
                bad_host = await client.post(
                    "/mcp", headers={"Host": "attacker.example", "Accept": "application/json, text/event-stream"},
                    json=request,
                )
                assert bad_host.status_code == 421
                bad_origin = await client.post(
                    "/mcp", headers={"Origin": "https://attacker.example", "Accept": "application/json, text/event-stream"},
                    json=request,
                )
                assert bad_origin.status_code == 403
                good_origin = await client.post(
                    "/mcp", headers={"Origin": f"https://{host}", "Accept": "application/json, text/event-stream"},
                    json=request,
                )
                assert good_origin.status_code == 200

    asyncio.run(run())


def test_public_mode_requires_exact_host_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_PUBLIC", "1")
    with pytest.raises(RuntimeError, match="ACCESS_TOKEN"):
        create_app(tmp_path / "missing-token.sqlite3")
    with pytest.raises(RuntimeError, match="PUBLIC_HOST"):
        create_app(tmp_path / "missing-host.sqlite3", access_token="a" * 40)
    monkeypatch.setenv("LOGIOPS_PUBLIC_HOST", "*.cloudfront.net")
    with pytest.raises(RuntimeError, match="exact hostname"):
        create_app(tmp_path / "wildcard.sqlite3", access_token="a" * 40)
