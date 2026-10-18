"""The decision field (static/field.js): every plan by delay and cost, the pick on top, no DOM."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from logiops.mcp_server import UI_FIELD_TOKEN, UI_HTML
from logiops.scenario import INCIDENT_IDS, best_plan, build_plans, seed_state

FIELD = Path(__file__).resolve().parents[1] / "logiops" / "static" / "field.js"


def field(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "-e", f"const m = require({str(FIELD)!r}); console.log(JSON.stringify({script}));"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
@pytest.mark.parametrize("view", ["NARROW", "WIDE"])
def test_every_plan_lands_inside_the_field_with_the_pick_drawn_last(incident_id, view):
    state = seed_state(incident_id)
    plans = build_plans(state, 1)
    pick = best_plan(plans)["id"]
    drawn = field(f"m.decisionField({json.dumps(plans)}, {json.dumps(pick)}, m.{view})")
    width, height = drawn["view"]["width"], drawn["view"]["height"]
    axes = drawn["axes"]
    assert sorted(point["id"] for point in drawn["points"]) == sorted(plan["id"] for plan in plans)
    assert drawn["points"][-1]["id"] == pick and [point["pick"] for point in drawn["points"]].count(True) == 1
    assert all(0 <= point["x"] <= width and 0 <= point["y"] <= height for point in drawn["points"])
    by_id = {plan["id"]: plan for plan in plans}
    for point in drawn["points"]:
        plan = by_id[point["id"]]
        assert point["cost"] == plan["incremental_cost_usd"] and point["delay"] == plan["projected_customer_delay_hours"]
        if point["cost"] == axes["maxCost"]:
            assert point["y"] == axes["top"]
        if point["cost"] == 0:
            assert point["y"] == axes["bottom"]
    places = [(point["x"], point["y"]) for point in drawn["points"]]
    assert len(set(places)) == len(places), "twins must not sit on each other"
    groups = {}
    for point in drawn["points"]:
        groups.setdefault((point["cost"], point["delay"]), []).append(point)
    for group in groups.values():
        assert [point["labelled"] for point in group].count(True) == 1
        assert any(point["pick"] for point in group) <= next(point for point in group if point["labelled"])["pick"]
    ticks = axes["ticks"]
    assert [tick["x"] for tick in ticks] == sorted(tick["x"] for tick in ticks)
    assert all(b["x"] - a["x"] >= 40 for a, b in zip(ticks, ticks[1:]))
    assert ticks[-1]["delay"] == axes["maxDelay"] or axes["maxDelay"] == 1


def test_standing_reads_the_critical_order_first():
    plans = [
        {"orders": [{"priority": "critical", "delay_hours": 4}, {"priority": "standard", "delay_hours": 0}]},
        {"orders": [{"priority": "critical", "delay_hours": 0}, {"priority": "standard", "delay_hours": 8}], "late_units": 18},
        {"orders": [{"priority": "standard", "delay_hours": 0}], "late_units": 0},
    ]
    assert field(f"{json.dumps(plans)}.map(m.standing)") == ["critical-late", "late", "on-time"]
    assert field("m.decisionField([], null).points") == []


def test_the_card_carries_the_field_inline():
    assert UI_FIELD_TOKEN not in UI_HTML and "root.LogiOpsField = api;" in UI_HTML
    script = FIELD.read_text()
    for forbidden in ("document", "location", "fetch(", "innerHTML", "XMLHttpRequest"):
        assert forbidden not in script, forbidden
    assert script.rstrip().endswith('})(typeof window === "undefined" ? globalThis : window);')
