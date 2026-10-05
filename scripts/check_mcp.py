"""Verify a local or remote MCP endpoint with the official Python SDK."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check(url: str) -> None:
    token = os.environ.get("LOGIOPS_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                shipment = await session.call_tool("get_shipment", {"shipment_id": "SHIP-421"})
                if shipment.isError:
                    raise RuntimeError("get_shipment failed")
                print(json.dumps({
                    "protocol_version": initialized.protocolVersion,
                    "tools": [tool.name for tool in listed.tools],
                    "shipment": shipment.structuredContent,
                }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        raise SystemExit("Usage: uv run python scripts/check_mcp.py <https://host/mcp>")
    asyncio.run(check(sys.argv[1]))
