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

    async def converse(self, messages, system, tools, skill=None):
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
    assert body["recommended_plan_id"].endswith(":split-express:v1") and "Recommended plan" not in body["answer"]
    assert body["spoken"].startswith("Split the order") and recorded["data"]["answer"].endswith("Recommended plan: split-express")
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


class Replies:
    """A follow-up or briefing model: answers in order, after one list_incidents call for a briefing."""

    def __init__(self, *answers, briefing=False):
        self.answers, self.briefing, self.calls = list(answers), briefing, []

    async def converse(self, messages, system, tools, skill=None):
        self.calls.append(messages[-1])
        if self.briefing and len(self.calls) == 1:
            return {"stopReason": "tool_use", "usage": {}, "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "l1", "name": "list_incidents", "input": {}}}]}}}
        return answer(self.answers.pop(0) if len(self.answers) > 1 else self.answers[0])


def _follow_up(tmp_path, model, question, execute=False):
    """Investigate SHIP-421 with the replay (and approve and execute its pick), then ask `model` a follow-up."""
    async def run():
        app = create_app(tmp_path / "follow-up.sqlite3", followup_client=model, agent_limit_per_minute=100)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                run = (await http.post("/incidents/SHIP-421/agent/investigate", json={})).json()
                if execute:
                    plan = next(p for p in run["plans"] if p["id"] == run["evaluations"][-1]["recommended_plan_id"])
                    body = {"plan_id": plan["id"], "source_version": plan["source_version"]}
                    await http.post("/incidents/SHIP-421/approvals", json={**body, "approved_by": "operator"})
                    await http.post("/incidents/SHIP-421/execute", json=body)
                return (await http.post("/incidents/SHIP-421/agent/ask", json={"question": question, "history": []})).json()

    return asyncio.run(run())


def test_a_follow_up_is_checked_and_revised(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    model = Replies("Rerouting would cost $95.\nSpoken: About 95 dollars.", "Rerouting costs $80.\nSpoken: 80 dollars.")
    body = _follow_up(tmp_path, model, "How much is the reroute?")
    assert [evaluation["passed"] for evaluation in body["evaluations"]] == [False, True] and body["grounded"] is True
    assert "$95" in model.calls[1]["content"][0]["text"] and body["answer"] == "Rerouting costs $80."


def test_a_follow_up_may_quote_the_question_and_the_record(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")
    hypothetical = Replies("With only 11 units in Arequipa, 9 more units would need express, which carries 8.\nSpoken: Not enough.")
    assert _follow_up(tmp_path, hypothetical, "What if only 11 units were in stock?")["grounded"] is True
    executed = Replies("The split was approved and has been executed; delivery is projected.\nSpoken: It ran.",
                       "I executed the split.\nSpoken: Done.")
    body = _follow_up(tmp_path / "executed", executed, "What happened?", execute=True)
    assert body["grounded"] is True and len(body["evaluations"]) == 1
    claimed = _follow_up(tmp_path / "claimed", Replies("I executed the split.\nSpoken: Done."), "What happened?", execute=True)
    assert claimed["grounded"] is False and "I executed" in claimed["evaluations"][0]["issues"][0]


def test_the_briefing_is_checked_against_every_incident(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_SCENARIO_ANCHOR", "fixed")
    good = ("SHIP-433 first: 12 critical units at risk for ORD-433A, due Oct 13, 12:00 Lima time, +24 h. "
            "SHIP-460 next: 45 units.\n\nStart with: SHIP-433\nSpoken: Start with SHIP-433.")
    model = Replies(good.replace("SHIP-460 next", "SHIP-999 next"), good, briefing=True)

    async def run():
        app = create_app(tmp_path / "briefing.sqlite3", model)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                return (await http.post("/agent/briefing", json={"question": "Any delays today?"})).json()

    body = asyncio.run(run())
    assert [evaluation["passed"] for evaluation in body["evaluations"]] == [False, True] and body["grounded"] is True
    assert "SHIP-999" in body["evaluations"][0]["issues"][0] and body["start_with"] == "SHIP-433"
