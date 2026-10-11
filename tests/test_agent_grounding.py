"""The investigation answer is checked against the data before it is shown, with one revision."""

import asyncio

import httpx

from logiops.agent import REVISION_MIN_SECONDS, investigate_with_bedrock
from logiops.api import create_app
from logiops.scenario import known_figures, seed_state

BASE_URL = "http://test"
TOOLS = {"stopReason": "tool_use", "usage": {"inputTokens": 100, "outputTokens": 10}, "output": {"message": {
    "role": "assistant", "content": [
        {"toolUse": {"toolUseId": "s1", "name": "get_shipment", "input": {"shipment_id": "SHIP-421"}}},
        {"toolUse": {"toolUseId": "p1", "name": "investigate_incident", "input": {"shipment_id": "SHIP-421"}}},
    ]}}}
GOOD = ("Split the order: 12 laptops from Arequipa stock and 8 by express, on time, for $120.\n"
        "Spoken: Split the order, on time, for 120 dollars.\nRecommended plan: split-express")


def answer(text):
    return {"stopReason": "end_turn", "usage": {"inputTokens": 200, "outputTokens": 50},
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}


class Scripted:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def converse(self, messages, system, tools):
        self.calls.append(messages[-1])
        return TOOLS if len(self.calls) == 1 else answer(self.answers.pop(0) if len(self.answers) > 1 else self.answers[0])


def _investigate(tmp_path, model, preferences=None):
    async def run():
        app = create_app(tmp_path / "grounding.sqlite3", model)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                if preferences:
                    assert (await http.put("/operator/preferences", json=preferences)).status_code == 200
                body = (await http.post("/incidents/SHIP-421/agent/investigate", json={})).json()
                recorded = (await http.get("/incidents/SHIP-421")).json()["events"][-1]
        return body, recorded

    return asyncio.run(run())


def test_a_failed_check_gets_one_revision_with_the_reasons(tmp_path):
    model = Scripted(GOOD.replace("$120", "$99"), GOOD)
    body, recorded = _investigate(tmp_path, model)
    assert [evaluation["passed"] for evaluation in body["evaluations"]] == [False, True] and body["grounded"] is True
    assert "$99" in body["evaluations"][0]["issues"][0]
    revision = model.calls[2]["content"][0]["text"]
    assert revision.startswith("Your answer failed an automatic check") and "$99" in revision
    assert body["answer"].endswith("Recommended plan: split-express") and body["spoken"].startswith("Split the order")
    assert recorded["name"] == "agent_investigation_completed" and recorded["data"]["grounded"] is True
    assert body["usage"] == {"inputTokens": 500, "outputTokens": 110}


def test_an_answer_that_stays_ungrounded_is_shown_flagged(tmp_path):
    body, recorded = _investigate(tmp_path, Scripted(GOOD.replace("8 by express", "15 laptops by express")))
    assert body["grounded"] is False and len(body["evaluations"]) == 2
    assert recorded["data"]["grounded"] is False and recorded["data"]["evaluations"] == body["evaluations"]


def test_the_spoken_line_and_the_recommended_line_are_checked(tmp_path):
    spoken = Scripted(GOOD.replace("Spoken: Split the order, on time,", "Spoken: Send 15 laptops by express,"), GOOD)
    body, _recorded = _investigate(tmp_path, spoken)
    assert "15" in body["evaluations"][0]["issues"][0] and body["grounded"] is True
    missing = Scripted(GOOD.replace("\nRecommended plan: split-express", ""), GOOD)
    body, _recorded = _investigate(tmp_path / "missing", missing)
    assert "Recommended plan" in body["evaluations"][0]["issues"][0] and body["grounded"] is True


def test_the_spend_cap_and_the_note_may_be_quoted(tmp_path):
    text = GOOD.replace("on time, for $120.", "on time, for $120, under your $250 cap; you asked to keep delays under 6 h.")
    body, _recorded = _investigate(tmp_path, Scripted(text), {"max_cost_usd": 250, "note": "keep delays under 6 h"})
    assert body["grounded"] is True and len(body["evaluations"]) == 1
    body, _recorded = _investigate(tmp_path / "unsaved", Scripted(text))
    assert body["evaluations"][0]["passed"] is False and "$250" in body["evaluations"][0]["issues"][0]


def test_no_revision_without_time_for_it(tmp_path):
    async def run():
        model = Scripted(GOOD.replace("$120", "$99"), GOOD)
        app = create_app(tmp_path / "late.sqlite3", model)
        async with app.router.lifespan_context(app):
            facts = known_figures(seed_state("SHIP-421"))
            return model, await investigate_with_bedrock(
                app, model, "SHIP-421", "Which plan?", facts=facts, deadline_seconds=REVISION_MIN_SECONDS)

    model, run_result = asyncio.run(run())
    assert len(model.calls) == 2 and run_result["grounded"] is False and len(run_result["evaluations"]) == 1
