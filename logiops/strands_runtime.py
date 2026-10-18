"""The agent's tool loop on Strands Agents: a Model over the project's Converse client, one AgentTool per
allowed MCP tool, hooks that keep the loop's guards, and a run that returns the same result as before."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Awaitable, Callable, Iterable, Mapping

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.hooks import AfterModelCallEvent, AfterToolCallEvent, HookProvider, HookRegistry
from strands.models import Model
from strands.tools.executors import SequentialToolExecutor
from strands.types._events import ToolResultEvent
from strands.types.exceptions import EventLoopException, MaxTokensReachedException
from strands.types.tools import AgentTool, ToolSpec, ToolUse

from .bedrock import BedrockError

Evaluate = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
OnStep = Callable[[dict[str, Any]], Awaitable[None]]
USAGE_KEYS = ("inputTokens", "outputTokens")
CACHE_KEYS = ("cacheReadInputTokens", "cacheWriteInputTokens")


def system_parts(content: list[dict[str, Any]] | None, fallback: str | None) -> tuple[str | None, str]:
    """(skill, system prompt) from the system content blocks: two text blocks are the Agent Skill and the
    prompt, one text block is the prompt alone."""
    texts = [block["text"] for block in content or [] if "text" in block]
    if len(texts) >= 2:
        return texts[0], "\n".join(texts[1:])
    return None, texts[0] if texts else (fallback or "")


def assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    message = response.get("output", {}).get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise BedrockError("Bedrock returned no assistant message")
    return message


def converse_events(response: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """A non-streaming Converse response as the stream events Strands consumes."""
    message = assistant_message(response)
    yield {"messageStart": {"role": "assistant"}}
    for block in message.get("content", []):
        if "toolUse" in block:
            use = block["toolUse"]
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": use["toolUseId"], "name": use["name"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(use.get("input", {}))}}}}
        elif "text" in block:
            yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
        yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": response["stopReason"]}}
    if "usage" in response or "metrics" in response:
        yield {"metadata": {"usage": dict(response.get("usage", {})), "metrics": dict(response.get("metrics", {"latencyMs": 0}))}}


def message_text(message: dict[str, Any] | None) -> str:
    return "\n".join(block["text"] for block in (message or {}).get("content", []) if "text" in block).strip()


def has_tool_use(message: dict[str, Any] | None) -> bool:
    return any("toolUse" in block for block in (message or {}).get("content", []))


class ConverseModel(Model):
    """Strands model provider over the ConverseClient protocol: Bedrock Converse without streaming, the daily
    budget wrapper, the replay client and the test fakes all fit. Usage is summed here, turn by turn."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.responses: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any) -> AsyncGenerator[dict[str, Any], None]:
        raise NotImplementedError("LogiOps answers in prose; structured output is not used")
        yield {}

    async def stream(self, messages: Any, tool_specs: list[ToolSpec] | None = None, system_prompt: str | None = None, *,
                     system_prompt_content: list[dict[str, Any]] | None = None, **kwargs: Any) -> AsyncGenerator[dict[str, Any], None]:
        skill, system = system_parts(system_prompt_content, system_prompt)
        tools = [{"toolSpec": dict(spec)} for spec in tool_specs or []]
        self.calls.append({"messages": [dict(message) for message in messages], "system": system, "skill": skill, "tools": tools})
        response = await self.client.converse(list(messages), system, tools, skill=skill)
        self.responses.append(response)
        for event in converse_events(response):
            yield event

    def usage(self) -> dict[str, int]:
        usage = {key: 0 for key in USAGE_KEYS}
        for response in self.responses:
            turn = response.get("usage", {})
            for key in USAGE_KEYS:
                usage[key] += turn.get(key, 0)
            for key in CACHE_KEYS:
                if key in turn:
                    usage[key] = usage.get(key, 0) + turn[key]
        return usage

    def last_response(self) -> dict[str, Any] | None:
        return self.responses[-1] if self.responses else None


class McpTool(AgentTool):
    """One allowed MCP tool, called on the session that lives in this event loop; every call lands in the trace
    and, with `on_step`, is reported as soon as it returns."""

    def __init__(self, tool: Any, session: Any, trace: list[dict[str, Any]], on_step: OnStep | None = None) -> None:
        super().__init__()
        self._spec: ToolSpec = {"name": tool.name, "description": tool.description or tool.name, "inputSchema": {"json": tool.inputSchema}}
        self.session = session
        self.trace = trace
        self.on_step = on_step

    @property
    def tool_name(self) -> str:
        return self._spec["name"]

    @property
    def tool_spec(self) -> ToolSpec:
        return self._spec

    @property
    def tool_type(self) -> str:
        return "mcp"

    async def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any) -> AsyncGenerator[Any, None]:
        arguments = tool_use.get("input", {})
        result = await self.session.call_tool(self.tool_name, arguments)
        payload = result.structuredContent
        if payload is None:
            payload = {"text": "\n".join(part.text for part in result.content if part.type == "text")}
        self.trace.append({"tool": self.tool_name, "input": arguments, "output": payload, "is_error": bool(result.isError)})
        if self.on_step is not None:
            await self.on_step(self.trace[-1])
        yield ToolResultEvent({"toolUseId": tool_use["toolUseId"], "status": "error" if result.isError else "success", "content": [{"json": payload}]})


class RunGuards(HookProvider):
    """The loop's guards as hooks: a model turn that asks for a tool outside the allowlist, with an input
    that is not an object or for another shipment, a tool_use stop without a tool, or a truncated tool
    call ends the run before any tool executes; a transport error inside a tool is raised, not reported."""

    def __init__(self, allowed: Iterable[str], shipments: Iterable[str]) -> None:
        self.allowed = frozenset(allowed)
        self.shipments = frozenset(shipments)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def after_model(self, event: AfterModelCallEvent) -> None:
        if event.exception is not None or event.stop_response is None:
            return
        message = event.stop_response.message
        uses = [block["toolUse"] for block in message.get("content", []) if "toolUse" in block]
        if event.stop_response.stop_reason == "max_tokens" and uses:
            raise BedrockError("Bedrock response was truncated in the middle of a tool call")
        if event.stop_response.stop_reason == "tool_use" and not uses:
            raise BedrockError("Bedrock requested tool use without a tool call")
        for use in uses:
            name = use.get("name")
            if name not in self.allowed:
                raise BedrockError(f"Bedrock requested a disallowed tool: {name}")
            arguments = use.get("input", {})
            if not isinstance(arguments, dict):
                raise BedrockError("Bedrock tool input must be an object")
            requested = arguments.get("shipment_id")
            if requested is not None and str(requested).strip().upper() not in self.shipments:
                raise BedrockError("Bedrock requested a different shipment")

    def after_tool(self, event: AfterToolCallEvent) -> None:
        if event.exception is not None:
            raise event.exception


def unwrap(error: BaseException) -> BaseException:
    while isinstance(error, EventLoopException):
        error = error.original_exception
    return error


def turns_taken(agent: Agent) -> int:
    return sum(len(invocation.cycles) for invocation in agent.event_loop_metrics.agent_invocations)


async def run_agent(
    *, client: Any, session: Any, tools: list[Any], allowed: Iterable[str], shipments: Iterable[str], skill: str, skill_info: dict[str, Any],
    system: str, first_message: str, required_tool: str | None, max_turns: int, evaluate: Evaluate | None = None,
    revise_until: float | None = None, closing: str = "", trace_attributes: Mapping[str, Any] | None = None,
    on_step: OnStep | None = None,
) -> dict[str, Any]:
    """Run the tool loop as a Strands agent and return the result the API expects: answer, spoken line, tool
    trace, usage, skill, and the evaluations when the answer is checked. A failed first check is sent back
    once as a second invocation of the same agent while turns remain and the clock allows."""
    from .agent import revision_request, split_spoken

    trace: list[dict[str, Any]] = []
    model = ConverseModel(client)
    agent = Agent(
        model=model, tools=[McpTool(tool, session, trace, on_step) for tool in tools],
        system_prompt=[{"text": skill}, {"text": system}, {"cachePoint": {"type": "default"}}],
        hooks=[RunGuards(allowed, shipments)], conversation_manager=NullConversationManager(), callback_handler=None,
        retry_strategy=None, tool_executor=SequentialToolExecutor(), record_direct_tool_call=False, trace_attributes=trace_attributes,
    )
    evaluations: list[dict[str, Any]] = []
    prompt = first_message
    while True:
        remaining = max_turns - turns_taken(agent)
        if remaining <= 0:
            raise BedrockError(f"Agent exceeded {max_turns} Converse turns")
        truncated = False
        try:
            result = await agent.invoke_async(prompt, limits={"turns": remaining})
        except MaxTokensReachedException:
            if has_tool_use(assistant_message(model.last_response() or {})):
                raise BedrockError("Bedrock response was truncated in the middle of a tool call") from None
            answer = message_text(agent.messages[-1] if agent.messages else None)
            truncated = True
        except EventLoopException as error:
            raise unwrap(error) from None
        else:
            if result.stop_reason == "limit_turns":
                raise BedrockError(f"Agent exceeded {max_turns} Converse turns")
            if result.stop_reason != "end_turn":
                raise BedrockError(f"Bedrock stopped unexpectedly: {result.stop_reason}")
            answer = message_text(result.message)
        if required_tool and not any(step["tool"] == required_tool and not step["is_error"] for step in trace):
            raise BedrockError(
                "Agent ended before calculating the incident plans" if required_tool == "investigate_incident"
                else f"Agent ended before calling {required_tool}"
            )
        if not answer:
            raise BedrockError("Bedrock returned an empty explanation")
        if evaluate is not None:
            evaluations.append({"attempt": len(evaluations) + 1, **evaluate(answer, trace)})
            if (not evaluations[-1]["passed"] and len(evaluations) == 1 and turns_taken(agent) < max_turns
                    and (revise_until is None or asyncio.get_running_loop().time() < revise_until)):
                prompt = revision_request(evaluations[-1], closing)
                continue
        answer, spoken = split_spoken(answer)
        outcome: dict[str, Any] = {"answer": answer, "spoken": spoken, "tool_trace": trace, "usage": model.usage(), "skill": skill_info}
        if evaluations:
            outcome.update(evaluations=evaluations, grounded=evaluations[-1]["passed"])
        if truncated:
            outcome["truncated"] = True
        return outcome
