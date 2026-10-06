"""Bedrock tool-use loop, with MCP as its only source of operational facts."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .bedrock import BedrockError


BASE_URL = "http://127.0.0.1:8000"
INTERNAL_HEADER = "x-logiops-internal"
# CloudFront closes the origin request after 60 s; finish (or fail clearly) first.
DEFAULT_DEADLINE_SECONDS = 50.0
READ_TOOLS = {
    "get_shipment",
    "get_order",
    "get_inventory",
    "find_alternative_carriers",
    "investigate_incident",
    "get_execution_status",
}
SYSTEM_PROMPT = """You are LogiOps AI, investigating a synthetic logistics incident.
Use the provided tools to get shipment, order, inventory, and carrier facts. Call
investigate_incident to obtain the three calculated plans. Compare their ETA,
customer delay, cost, and allocation. Recommend one plan using those exact facts.
Clearly say delivery is projected, not physically confirmed. Never claim an action
was approved or executed unless a tool reports it. Human approval is required
before execution. Do not invent plan IDs, quantities, prices, or timestamps."""


class ConverseClient(Protocol):
    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]
    ) -> dict[str, Any]: ...


async def _investigate_with_bedrock(
    app: Any, client: ConverseClient, shipment_id: str, question: str, *,
    access_token: str | None = None, internal_key: str | None = None, max_turns: int = 8
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": f"Shipment: {shipment_id}. {question}"}]}
    ]
    trace: list[dict[str, Any]] = []
    usage = {"inputTokens": 0, "outputTokens": 0}
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    if internal_key:
        headers[INTERNAL_HEADER] = internal_key
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL, headers=headers
    ) as http_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                tool_specs = [
                    {
                        "toolSpec": {
                            "name": tool.name,
                            "description": tool.description or tool.name,
                            "inputSchema": {"json": tool.inputSchema},
                        }
                    }
                    for tool in listed.tools if tool.name in READ_TOOLS
                ]
                if {spec["toolSpec"]["name"] for spec in tool_specs} != READ_TOOLS:
                    raise BedrockError("The read-only MCP toolset is incomplete")
                for _ in range(max_turns):
                    response = await client.converse(messages, SYSTEM_PROMPT, tool_specs)
                    turn_usage = response.get("usage", {})
                    for key in usage:
                        usage[key] += turn_usage.get(key, 0)
                    assistant_message = response.get("output", {}).get("message")
                    if not isinstance(assistant_message, dict) or assistant_message.get("role") != "assistant":
                        raise BedrockError("Bedrock returned no assistant message")
                    messages.append(assistant_message)
                    stop_reason = response["stopReason"]
                    has_tool_use = any("toolUse" in block for block in assistant_message.get("content", []))
                    if stop_reason == "max_tokens" and has_tool_use:
                        raise BedrockError("Bedrock response was truncated in the middle of a tool call")
                    if stop_reason in ("end_turn", "max_tokens"):
                        if not any(step["tool"] == "investigate_incident" and not step["is_error"] for step in trace):
                            raise BedrockError("Agent ended before calculating the incident plans")
                        answer = "\n".join(
                            block["text"] for block in assistant_message.get("content", []) if "text" in block
                        ).strip()
                        if not answer:
                            raise BedrockError("Bedrock returned an empty explanation")
                        result = {"answer": answer, "tool_trace": trace, "usage": usage}
                        if stop_reason == "max_tokens":
                            result["truncated"] = True
                        return result
                    if stop_reason != "tool_use":
                        raise BedrockError(f"Bedrock stopped unexpectedly: {stop_reason}")
                    tool_uses = [
                        block["toolUse"] for block in assistant_message.get("content", []) if "toolUse" in block
                    ]
                    if not tool_uses:
                        raise BedrockError("Bedrock requested tool use without a tool call")
                    results = []
                    for use in tool_uses:
                        name = use.get("name")
                        if name not in READ_TOOLS:
                            raise BedrockError(f"Bedrock requested a disallowed tool: {name}")
                        arguments = use.get("input", {})
                        if not isinstance(arguments, dict):
                            raise BedrockError("Bedrock tool input must be an object")
                        requested = arguments.get("shipment_id")
                        if requested is not None and str(requested).strip().casefold() != shipment_id.casefold():
                            raise BedrockError("Bedrock requested a different shipment")
                        result = await session.call_tool(name, arguments)
                        payload = result.structuredContent
                        if payload is None:
                            payload = {"text": "\n".join(part.text for part in result.content if part.type == "text")}
                        trace.append({
                            "tool": name, "input": arguments, "output": payload,
                            "is_error": bool(result.isError),
                        })
                        results.append({
                            "toolResult": {
                                "toolUseId": use["toolUseId"],
                                "content": [{"json": payload}],
                                "status": "error" if result.isError else "success",
                            }
                        })
                    messages.append({"role": "user", "content": results})
    raise BedrockError(f"Agent exceeded {max_turns} Converse turns")


async def investigate_with_bedrock(
    app: Any, client: ConverseClient, shipment_id: str, question: str, *,
    access_token: str | None = None, internal_key: str | None = None, max_turns: int = 8,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(deadline_seconds):
            return await _investigate_with_bedrock(
                app, client, shipment_id, question,
                access_token=access_token, internal_key=internal_key, max_turns=max_turns,
            )
    except TimeoutError as exc:
        raise BedrockError(f"Agent did not finish within {deadline_seconds:g} seconds; try again") from exc
    except BaseExceptionGroup as group:
        # AnyIO wraps exceptions raised inside MCP's task groups. Preserve our
        # controlled API error without leaking a transport traceback to callers.
        def bedrock_error(error: BaseException) -> BedrockError | None:
            if isinstance(error, BedrockError):
                return error
            if isinstance(error, BaseExceptionGroup):
                return next((found for child in error.exceptions if (found := bedrock_error(child))), None)
            return None

        found = bedrock_error(group)
        if found is not None:
            raise found from None
        raise
