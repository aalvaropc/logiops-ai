"""Saved operator preferences: persistent, applied by fixed rules, and never an approval."""

import asyncio
import sqlite3

import httpx
import pytest

from logiops.api import create_app
from logiops.preferences import PreferenceStore, normalized, preference_for
from logiops.scenario import INCIDENT_IDS, build_plans, seed_state
from logiops.service import LogiOpsService


BASE_URL = "http://127.0.0.1:8000"


def _kind(plan_id):
    return plan_id.split(":")[2]


def _picks(preferences):
    return {
        incident_id: _kind(preference_for(build_plans(seed_state(incident_id), 1), preferences)["preferred_plan_id"])
        for incident_id in INCIDENT_IDS
    }


def test_a_250_dollar_cap_changes_the_pick_on_three_incidents_of_four():
    picks = _picks({"rule": "balanced", "max_cost_usd": 250})
    assert picks == {
        "SHIP-421": "split-express",  # $120 already fits
        "SHIP-433": "priority-air",  # $390 no longer fits; the hospital is still flown
        "SHIP-452": "split-wait",
        "SHIP-460": "priority-first",
    }
    shipment = preference_for(build_plans(seed_state("SHIP-433"), 1), {"rule": "balanced", "max_cost_usd": 250})
    assert shipment["changes_pick"] and shipment["warnings"] == []
    assert shipment["reason"].startswith("The $250 spend cap rules out “Fly the hospital order; rebook the store order on ground” ($390)")
    assert "saves $150" in shipment["reason"] and "16 h later" in shipment["reason"]


def test_the_cheapest_rule_still_keeps_critical_orders_on_time():
    picks = _picks({"rule": "cheapest_unless_critical_late", "max_cost_usd": None})
    # SHIP-433's $0 and $150 plans leave the hospital late; the cheapest safe plan is the $240 flight.
    assert picks == {"SHIP-421": "wait", "SHIP-433": "priority-air", "SHIP-452": "split-wait", "SHIP-460": "priority-first"}


def test_a_tight_cap_warns_when_a_critical_order_ends_up_late():
    result = preference_for(build_plans(seed_state("SHIP-433"), 1), {"rule": "balanced", "max_cost_usd": 200})
    assert _kind(result["preferred_plan_id"]) == "reroute"
    assert result["warnings"] == [
        "ORD-433A (Cusco regional hospital, critical) is 8 h late. The default pick, "
        "“Fly the hospital order; rebook the store order on ground”, keeps critical orders on time."
    ]


def test_no_plan_within_the_cap_falls_back_to_the_cheapest_and_says_so():
    plans = [plan for plan in build_plans(seed_state("SHIP-421"), 1) if plan["incremental_cost_usd"] > 0]
    result = preference_for(plans, {"rule": "balanced", "max_cost_usd": 10})
    assert _kind(result["preferred_plan_id"]) == "reroute"
    assert result["warnings"] == ["No plan fits the $10 spend cap; this is the cheapest one."]


def test_nothing_to_apply_without_plans_or_preferences():
    plans = build_plans(seed_state("SHIP-421"), 1)
    assert preference_for([], {"rule": "balanced", "max_cost_usd": 1}) is None
    assert preference_for(plans, None) is None
    agree = preference_for(plans, {"rule": "balanced", "max_cost_usd": None, "note": ""})
    assert not agree["changes_pick"] and agree["reason"] == "Your preferences agree with the default pick."


@pytest.mark.parametrize(("rule", "cap", "note"), [
    ("fastest", None, ""), ("balanced", -1, ""), ("balanced", 1.5, ""), ("balanced", True, ""), ("balanced", None, "x" * 201),
])
def test_invalid_preferences_are_refused(rule, cap, note):
    with pytest.raises(ValueError):
        normalized(rule, cap, note)


def test_preferences_survive_a_restart_and_the_incident_migration(tmp_path):
    path = tmp_path / "prefs.sqlite3"
    LogiOpsService(path)
    PreferenceStore(path).put("cheapest_unless_critical_late", 250, "  Hospitals   first ")
    # A later schema version rebuilds the incident tables, and only those.
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    LogiOpsService(path)
    saved = PreferenceStore(path).get()
    assert {key: saved[key] for key in ("rule", "max_cost_usd", "note")} == {
        "rule": "cheapest_unless_critical_late", "max_cost_usd": 250, "note": "Hospitals first",
    }


def test_the_api_saves_applies_and_forgets_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGIOPS_AGENT_MODE", "replay")

    async def run():
        app = create_app(tmp_path / "api.sqlite3")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                assert (await http.get("/operator/preferences")).json()["preferences"] is None
                for bad in ({"rule": "fastest"}, {"max_cost_usd": -5}, {"note": "x" * 201}, {"max_cost_usd": 2.5}):
                    assert (await http.put("/operator/preferences", json=bad)).status_code == 422
                saved = await http.put("/operator/preferences", json={"max_cost_usd": 250, "note": "Hospitals first"})
                assert saved.status_code == 200 and saved.json()["preferences"]["rule"] == "balanced"
                # Before any investigation there is nothing to pick from.
                incident = (await http.get("/incidents/SHIP-433")).json()
                assert incident["operator_preferences"]["max_cost_usd"] == 250 and incident["preference"] is None

                # The agent sees the preference in the MCP result and recommends its plan.
                run = (await http.post("/incidents/SHIP-433/agent/investigate", json={})).json()
                preferred = next(plan for plan in run["plans"] if plan["kind"] == "priority-air")
                assert run["answer"].rstrip().endswith(f"Recommended plan: {preferred['id']}")
                step = next(item for item in run["tool_trace"] if item["tool"] == "investigate_incident")
                assert step["output"]["operator_preferences"]["preferred_plan_id"] == preferred["id"]
                incident = (await http.get("/incidents/SHIP-433")).json()
                assert incident["preference"]["preferred_plan_id"] == preferred["id"]
                # A preference is not an approval.
                assert incident["approvals"] == [] and incident["state"]["status"] == "investigated"

                # Follow-ups answer with the preference in mind.
                ask = (await http.post("/incidents/SHIP-433/agent/ask", json={"question": "Which plan now?"})).json()
                assert preferred["id"] in ask["answer"]

                # Resetting one incident keeps the preferences; resetting everything forgets them.
                await http.post("/demo/reset", json={"incident_id": "SHIP-433"})
                assert (await http.get("/operator/preferences")).json()["preferences"] is not None
                await http.post("/demo/reset")
                assert (await http.get("/operator/preferences")).json()["preferences"] is None
                await http.put("/operator/preferences", json={"rule": "cheapest_unless_critical_late"})
                assert (await http.delete("/operator/preferences")).json()["preferences"] is None

    asyncio.run(run())


def test_preferences_need_the_token_in_public_mode(tmp_path):
    async def run():
        app = create_app(tmp_path / "locked.sqlite3", access_token="a" * 40)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as http:
                assert (await http.get("/operator/preferences")).status_code == 401
                assert (await http.put("/operator/preferences", json={"max_cost_usd": 1})).status_code == 401
                assert (await http.post("/agent/briefing", json={})).status_code == 401

    asyncio.run(run())
