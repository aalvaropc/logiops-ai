"""The Strands runtime reproduces the tool loop: events, guards, turns, trace, usage, revision and errors."""

import asyncio
from types import SimpleNamespace

import pytest

from logiops.agent import _with_deadline
from logiops.bedrock import BedrockError, BedrockUnavailable
from logiops.strands_runtime import ConverseModel, converse_events, run_agent, system_parts

TOOLS = [
    SimpleNamespace(name="get_shipment", description="Shipment facts", inputSchema={"type": "object", "properties": {"shipment_id": {"type": "string"}}}),
    SimpleNamespace(name="investigate_incident", description=None, inputSchema={"type": "object"}),
]
ALLOWED = {"get_shipment", "investigate_incident"}
SKILL = {"name": "logiops-exception-desk", "uri": "skill://x", "sha256": "0" * 64}


def tool_use(name, arguments, use_id="u1", text=None):
    content = ([{"text": text}] if text else []) + [{"toolUse": {"toolUseId": use_id, "name": name, "input": arguments}}]
    return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use", "usage": {"inputTokens": 100, "outputTokens": 10}}


def end_turn(text, stop="end_turn", usage=None):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": stop,
            "usage": usage if usage is not None else {"inputTokens": 50, "outputTokens": 20}}


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def converse(self, messages, system, tools, skill=None):
        self.calls.append({"messages": [dict(m) for m in messages], "system": system, "tools": tools, "skill": skill})
        if not self.responses:
            raise AssertionError("the model was called more times than scripted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSession:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.fail:
            raise self.fail
        if name == "investigate_incident":
            return SimpleNamespace(structuredContent={"plans": [{"id": "SHIP-421:1:split-express:v1", "label": "Split"}], "source_version": 1}, isError=False, content=[])
        if name == "get_shipment":
            return SimpleNamespace(structuredContent=None, isError=False, content=[SimpleNamespace(type="text", text="Lima to Arequipa")])
        return SimpleNamespace(structuredContent={"error": name}, isError=True, content=[])


def run(client, session=None, **overrides):
    options = dict(client=client, session=session or FakeSession(), tools=TOOLS, allowed=ALLOWED, shipments={"SHIP-421"},
                   skill="# Skill", skill_info=SKILL, system="Investigate.", first_message="Shipment: SHIP-421. What happened?",
                   required_tool="investigate_incident", max_turns=4)
    options.update(overrides)
    return asyncio.run(run_agent(**options))


def test_a_converse_response_becomes_the_stream_strands_consumes():
    events = list(converse_events(tool_use("get_shipment", {"shipment_id": "SHIP-421"}, text="Looking.")))
    assert events[0] == {"messageStart": {"role": "assistant"}}
    assert events[1] == {"contentBlockDelta": {"delta": {"text": "Looking."}}} and events[2] == {"contentBlockStop": {}}
    assert events[3] == {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "u1", "name": "get_shipment"}}}}
    assert events[4] == {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"shipment_id": "SHIP-421"}'}}}}
    assert events[-2] == {"messageStop": {"stopReason": "tool_use"}}
    assert events[-1] == {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 10}, "metrics": {"latencyMs": 0}}}
    assert system_parts([{"text": "skill"}, {"text": "prompt"}, {"cachePoint": {"type": "default"}}], None) == ("skill", "prompt")
    assert system_parts([{"text": "prompt"}], None) == (None, "prompt") and system_parts(None, "fallback") == (None, "fallback")
    with pytest.raises(BedrockError, match="no assistant message"):
        list(converse_events({"output": {}, "stopReason": "end_turn"}))


def test_the_loop_calls_the_tools_and_returns_the_answer_the_trace_and_the_usage():
    client = ScriptedClient([
        tool_use("get_shipment", {"shipment_id": "ship-421"}, text="Reading."),
        tool_use("investigate_incident", {"shipment_id": "SHIP-421"}, use_id="u2"),
        end_turn("Delay on the highway.\nSpoken: The split plan arrives on time.\nRecommended plan: SHIP-421:1:split-express:v1",
                 usage={"inputTokens": 500, "outputTokens": 80, "cacheReadInputTokens": 400}),
    ])
    session = FakeSession()
    result = run(client, session)
    assert session.calls == [("get_shipment", {"shipment_id": "ship-421"}), ("investigate_incident", {"shipment_id": "SHIP-421"})]
    assert [step["tool"] for step in result["tool_trace"]] == ["get_shipment", "investigate_incident"]
    assert result["tool_trace"][0]["output"] == {"text": "Lima to Arequipa"} and result["tool_trace"][1]["is_error"] is False
    assert result["answer"] == "Delay on the highway.\n\nRecommended plan: SHIP-421:1:split-express:v1"
    assert result["spoken"] == "The split plan arrives on time."
    assert result["usage"] == {"inputTokens": 700, "outputTokens": 100, "cacheReadInputTokens": 400}
    assert result["skill"] == SKILL and "truncated" not in result and "evaluations" not in result
    first = client.calls[0]
    assert first["skill"] == "# Skill" and first["system"] == "Investigate."
    assert [spec["toolSpec"]["name"] for spec in first["tools"]] == ["get_shipment", "investigate_incident"]
    assert first["tools"][1]["toolSpec"]["description"] == "investigate_incident"
    assert first["messages"][0]["content"] == [{"text": "Shipment: SHIP-421. What happened?"}]
    third = client.calls[2]["messages"]
    assert third[1]["role"] == "assistant" and third[2]["content"][0]["toolResult"]["content"] == [{"json": {"text": "Lima to Arequipa"}}]
    assert third[2]["content"][0]["toolResult"]["status"] == "success"


def test_a_truncated_answer_is_kept_and_a_truncated_tool_call_is_an_error():
    client = ScriptedClient([tool_use("investigate_incident", {"shipment_id": "SHIP-421"}), end_turn("Partial answer", stop="max_tokens")])
    result = run(client)
    assert result["truncated"] is True and result["answer"] == "Partial answer" and result["spoken"] == "Partial answer"
    cut = {"output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "u9", "name": "get_shipment", "input": {}}}]}}, "stopReason": "max_tokens", "usage": {}}
    session = FakeSession()
    with pytest.raises(BedrockError, match="truncated in the middle of a tool call"):
        run(ScriptedClient([cut]), session)
    assert session.calls == []


@pytest.mark.parametrize("response, message", [
    (tool_use("find_alternative_carriers", {"shipment_id": "SHIP-421"}), "disallowed tool: find_alternative_carriers"),
    (tool_use("get_shipment", ["SHIP-421"]), "tool input must be an object"),
    (tool_use("get_shipment", {"shipment_id": "SHIP-999"}), "requested a different shipment"),
    ({"output": {"message": {"role": "assistant", "content": [{"text": "hm"}]}}, "stopReason": "tool_use", "usage": {}}, "tool use without a tool call"),
    ({"output": {"message": {"role": "user", "content": []}}, "stopReason": "end_turn"}, "no assistant message"),
    (end_turn("x", stop="content_filtered"), "stopped unexpectedly: content_filtered"),
])
def test_each_guard_stops_the_run_before_any_tool_executes(response, message):
    session = FakeSession()
    with pytest.raises(BedrockError, match=message):
        run(ScriptedClient([response]), session)
    assert session.calls == []


def test_the_turn_limit_and_the_required_tool_and_an_empty_answer():
    endless = ScriptedClient([tool_use("get_shipment", {"shipment_id": "SHIP-421"}, use_id=f"u{i}") for i in range(10)])
    with pytest.raises(BedrockError, match="exceeded 2 Converse turns"):
        run(endless, max_turns=2)
    assert len(endless.calls) == 2
    with pytest.raises(BedrockError, match="ended before calculating the incident plans"):
        run(ScriptedClient([end_turn("No tools used.")]))
    with pytest.raises(BedrockError, match="ended before calling list_incidents"):
        run(ScriptedClient([end_turn("No tools used.")]), required_tool="list_incidents")
    with pytest.raises(BedrockError, match="empty explanation"):
        run(ScriptedClient([tool_use("investigate_incident", {}), end_turn("   ")]))


def test_a_transport_error_inside_a_tool_and_a_model_error_are_raised_as_they_are():
    class Transport(RuntimeError):
        pass

    with pytest.raises(Transport, match="socket closed"):
        run(ScriptedClient([tool_use("get_shipment", {"shipment_id": "SHIP-421"})]), FakeSession(fail=Transport("socket closed")))
    with pytest.raises(BedrockError, match="throttled"):
        run(ScriptedClient([BedrockError("throttled")]))


def test_a_failed_check_is_revised_once_with_the_remaining_turns():
    client = ScriptedClient([
        tool_use("investigate_incident", {"shipment_id": "SHIP-421"}),
        end_turn("Wrong figures.\nSpoken: wrong.\nRecommended plan: nope"),
        end_turn("Right figures.\nSpoken: right.\nRecommended plan: SHIP-421:1:split-express:v1"),
    ])
    seen = []

    def evaluate(answer, trace):
        seen.append((answer, len(trace)))
        return {"passed": "Right" in answer, "issues": [] if "Right" in answer else ["the plan id is not real"]}

    result = run(client, evaluate=evaluate, closing="End with the same two lines.")
    assert [attempt["attempt"] for attempt in result["evaluations"]] == [1, 2] and result["grounded"] is True
    assert result["answer"] == "Right figures.\n\nRecommended plan: SHIP-421:1:split-express:v1" and result["spoken"] == "right."
    revision = client.calls[2]["messages"][-1]
    assert revision["role"] == "user" and "failed an automatic check" in revision["content"][0]["text"]
    assert "the plan id is not real" in revision["content"][0]["text"] and "End with the same two lines." in revision["content"][0]["text"]
    assert len(client.calls[2]["messages"]) == 5 and seen == [("Wrong figures.\nSpoken: wrong.\nRecommended plan: nope", 1), ("Right figures.\nSpoken: right.\nRecommended plan: SHIP-421:1:split-express:v1", 1)]
    assert result["usage"]["inputTokens"] == 200


def test_no_revision_when_the_clock_or_the_turns_are_out():
    late = ScriptedClient([tool_use("investigate_incident", {}), end_turn("Wrong.\nSpoken: w.")])
    failing = lambda answer, trace: {"passed": False, "issues": ["x"]}
    result = run(late, evaluate=failing, revise_until=0.0)
    assert result["grounded"] is False and len(result["evaluations"]) == 1 and len(late.calls) == 2
    short = ScriptedClient([tool_use("investigate_incident", {}), end_turn("Wrong.\nSpoken: w.")])
    result = run(short, evaluate=failing, max_turns=2)
    assert result["grounded"] is False and len(short.calls) == 2


def test_the_deadline_wraps_the_run():
    class Slow:
        async def converse(self, messages, system, tools, skill=None):
            await asyncio.sleep(5)
            return end_turn("late")

    async def go():
        return await _with_deadline(run_agent(
            client=Slow(), session=FakeSession(), tools=TOOLS, allowed=ALLOWED, shipments={"SHIP-421"}, skill="s", skill_info=SKILL,
            system="p", first_message="m", required_tool=None, max_turns=2), 0.2)

    with pytest.raises(BedrockUnavailable, match="did not finish within 0.2 seconds"):
        asyncio.run(go())


def test_the_model_adapter_records_every_turn():
    model = ConverseModel(ScriptedClient([end_turn("hi", usage={"inputTokens": 1, "outputTokens": 2, "cacheWriteInputTokens": 7})]))

    async def go():
        return [event async for event in model.stream([{"role": "user", "content": [{"text": "x"}]}], [TOOLS[0].__dict__], None,
                                                      system_prompt_content=[{"text": "skill"}, {"text": "prompt"}])]

    events = asyncio.run(go())
    assert events[0] == {"messageStart": {"role": "assistant"}} and model.usage() == {"inputTokens": 1, "outputTokens": 2, "cacheWriteInputTokens": 7}
    assert model.calls[0]["skill"] == "skill" and model.calls[0]["system"] == "prompt" and model.calls[0]["tools"][0]["toolSpec"]["name"] == "get_shipment"
