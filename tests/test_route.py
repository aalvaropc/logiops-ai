"""The device view's route legs (static/route.js): real plans of every incident, no DOM."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from logiops.scenario import INCIDENT_IDS, PLAYBOOKS, best_plan, build_plans, seed_state

ROUTE = Path(__file__).resolve().parents[1] / "logiops" / "static" / "route.js"


def route(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "-e", f"const m = require({str(ROUTE)!r}); console.log(JSON.stringify({script}));"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_every_plan_becomes_legs_that_carry_every_unit(incident_id):
    state = seed_state(incident_id)
    plans = build_plans(state, 1)
    legs = route(f"{json.dumps(plans)}.map((plan) => m.legsFor({json.dumps(state)}, plan))")
    due = {order["id"]: datetime.fromisoformat(order["due_eta"]) for order in state["orders"]}
    for plan, plan_legs in zip(plans, legs):
        assert sum(leg["units"] for leg in plan_legs) == sum(order["quantity"] for order in state["orders"])
        assert {leg["source"] for leg in plan_legs} == {item["source"] for item in plan["allocations"]}
        for leg in plan_legs:
            assert leg["type"] != "unknown" and leg["from"] and leg["to"]["name"] == state["shipment"]["destination"]
            items = [item for item in plan["allocations"] if item["source"] == leg["source"]]
            assert leg["late"] == any(datetime.fromisoformat(item["arrival_eta"]) > due[item["order_id"]] for item in items)


def test_every_playbook_source_has_a_leg_type():
    sources = sorted({source for options in PLAYBOOKS.values() for option in options
                      for source in (option["sources"] if isinstance(option["sources"], list)
                                     else [item for group in option["sources"].values() for item in group])})
    types = route(f"{json.dumps(sources)}.map(m.legType)")
    assert dict(zip(sources, types)) == {
        "air-freight": "air", "arequipa-stock": "local", "delayed-shipment": "delayed", "economy-reroute": "ground",
        "expedited-clearance": "clearance", "express": "express", "express-transfer": "express",
        "ground-reroute": "ground", "lima-stock": "local", "trujillo-stock": "local",
    }


def test_place_names_are_capitalised_and_shortened():
    assert route('[m.placeName("piura"), m.placeName("Lima"), m.placeName(" "), m.shortName("Puerto de Chancay", 10)]') == ["Piura", "Lima", "", "Puerto de…"]


def test_promise_bars_compare_each_order_with_its_promise():
    state = seed_state("SHIP-433")
    plan = best_plan(build_plans(state, 1))
    bars = route(f"m.promiseBars({json.dumps(plan)})")
    assert [(bar["order_id"], bar["on_time"], bar["delay_hours"]) for bar in bars] == [("ORD-433A", True, 0), ("ORD-433B", False, 8)]
    assert bars[1]["ratio"] == pytest.approx(8 / 48)
    wait = next(item for item in build_plans(state, 1) if item["kind"] == "wait")
    assert all(0 <= bar["ratio"] <= 1 for bar in route(f"m.promiseBars({json.dumps(wait)}, 12)"))


def test_the_voice_orb_states():
    steps = route('[["ready", "listen-start"], ["listening", "listen-end"], ["listening", "request"], '
                  '["thinking", "reply", true], ["thinking", "reply", false], ["speaking", "speech-end"], '
                  '["thinking", "error"], ["ready", "nonsense"], ["bogus", "request"]].map(([s, e, v]) => m.voiceState(s, e, v))')
    assert [step["state"] for step in steps] == [
        "listening", "ready", "thinking", "speaking", "ready", "ready", "ready", "ready", "thinking"]
    assert steps[0]["label"] == "Listening…" and steps[2]["label"] == "Thinking…" and steps[3]["label"] == "Speaking…"


def test_the_module_never_touches_the_page():
    script = ROUTE.read_text()
    assert "document" not in script and "innerHTML" not in script and "fetch(" not in script
    assert script.rstrip().endswith('})(typeof window === "undefined" ? globalThis : window);')


def test_a_pack_incident_becomes_legs_with_every_unit():
    pack = json.loads((Path(__file__).resolve().parent / "fixtures" / "scenario_pack.json").read_text())["incidents"][0]
    state = {"incident_id": pack["id"], "shipment": pack["shipment"], "orders": pack["orders"], "inventory": pack["inventory"], "carriers": pack["carriers"]}
    plan = {"allocations": [
        {"source": "piura-stock", "units": 30, "order_id": "ORD-470", "arrival_eta": "2026-10-13T08:00:00-05:00"},
        {"source": "refrigerated-truck", "units": 20, "order_id": "ORD-470", "arrival_eta": "2026-10-14T08:00:00-05:00"},
    ]}
    legs = route(f"m.legsFor({json.dumps(state)}, {json.dumps(plan)})")
    assert [(leg["type"], leg["units"], leg["from"]["name"], leg["to"]["name"]) for leg in legs] == [
        ("local", 30, "Piura", "Piura"), ("unknown", 20, "Paita", "Piura")]
    assert legs[1]["label"] == "refrigerated-truck"
