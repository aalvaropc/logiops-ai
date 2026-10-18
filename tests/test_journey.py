"""The shipment's journey (static/journey.js): the wide map, one time scale and the queue's lanes, no DOM."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from logiops.scenario import INCIDENT_IDS, build_plans, seed_state

JOURNEY = Path(__file__).resolve().parents[1] / "logiops" / "static" / "journey.js"


def journey(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "-e", f"const m = require({str(JOURNEY)!r}); const r = require({str(JOURNEY.with_name('route.js'))!r}); "
                          f"console.log(JSON.stringify({script}));"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_every_plan_draws_its_legs_inside_the_wide_view(incident_id):
    state = seed_state(incident_id)
    plans = build_plans(state, 1)
    views = journey(f"{json.dumps(plans)}.map((plan) => {{ const view = m.wideLayout({json.dumps(state['shipment'])}, r.legsFor({json.dumps(state)}, plan)); "
                    "return { ...view, spots: view.legs.map((leg) => m.labelSpot(leg, `${leg.label} · ${leg.units}`.length * 8.4)) }; })")
    for view in views:
        width, height = view["view"]["width"], view["view"]["height"]
        assert all(0 <= place["x"] <= width and 0 <= place["y"] <= height for place in view["places"])
        assert view["origin"]["x"] < view["destination"]["x"] and view["destination"]["name"] == state["shipment"]["destination"]
        assert view["booked"]["d"].startswith(f"M{view['origin']['x']} {view['origin']['y']} C")
        travelling = [leg for leg in view["legs"] if not leg["loop"]]
        assert len({leg["bend"] for leg in travelling}) == len(travelling)
        for leg, spot in zip(view["legs"], view["spots"]):
            assert leg["loop"] == (leg["from"]["name"] == view["destination"]["name"]) and leg["d"].startswith("M")
            assert 0 <= spot["x"] <= width + 20 and 0 <= spot["y"] <= height + 20


def test_any_place_name_works_and_extra_sources_stack_above_the_origin():
    shipment = {"origin": "rotterdam", "destination": "Gdansk"}
    legs = [{"from": {"name": "Rotterdam"}}, {"from": {"name": "Hamburg"}}, {"from": {"name": "gdansk"}}]
    view = journey(f"m.wideLayout({json.dumps(shipment)}, {json.dumps(legs)})")
    assert [(place["name"], place["role"]) for place in view["places"]] == [("Rotterdam", "origin"), ("Hamburg", "source"), ("Gdansk", "destination")]
    assert view["places"][1]["y"] < view["places"][0]["y"] and view["places"][1]["x"] < view["destination"]["x"]
    assert [leg["loop"] for leg in view["legs"]] == [False, False, True]
    assert journey(f"m.wideLayout({json.dumps(shipment)}, []).legs") == []


def test_a_pack_incident_draws_its_local_stock_as_a_loop():
    pack = json.loads((Path(__file__).resolve().parent / "fixtures" / "scenario_pack.json").read_text())["incidents"][0]
    state = {"incident_id": pack["id"], "shipment": pack["shipment"], "orders": pack["orders"], "inventory": pack["inventory"], "carriers": pack["carriers"]}
    plan = {"allocations": [
        {"source": "piura-stock", "units": 30, "order_id": "ORD-470", "arrival_eta": "2026-10-13T08:00:00-05:00"},
        {"source": "refrigerated-truck", "units": 20, "order_id": "ORD-470", "arrival_eta": "2026-10-14T08:00:00-05:00"},
    ]}
    view = journey(f"m.wideLayout({json.dumps(state['shipment'])}, r.legsFor({json.dumps(state)}, {json.dumps(plan)}))")
    assert [place["name"] for place in view["places"]] == ["Paita", "Piura"]
    assert [leg["loop"] for leg in view["legs"]] == [True, False]


def test_the_shipment_and_every_order_share_one_time_scale():
    state = seed_state("SHIP-433")
    plan = next(plan for plan in build_plans(state, 1) if plan["id"].endswith("priority-air-ground:v1"))
    tracks = journey(f"m.promiseTracks({json.dumps(state['shipment'])}, r.promiseBars({json.dumps(plan)}))")
    assert tracks["shipment"]["late"] is True and tracks["shipment"]["end"] > tracks["shipment"]["promise"]
    hospital, store = tracks["rows"]
    assert hospital["late"] is False and hospital["end"] <= hospital["promise"]
    assert store["late"] is True and store["promise"] == hospital["promise"] == tracks["shipment"]["promise"]
    assert all(0 <= value <= 100 for track in [tracks["shipment"], *tracks["rows"]] for value in (track["promise"], track["end"]))
    pending = journey(f"m.promiseTracks({json.dumps(state['shipment'])}, {json.dumps(state['orders'])})")
    assert all(row["end"] is None and row["late"] is False for row in pending["rows"])


def test_the_queue_lanes_run_to_each_promise_and_trail_the_delay():
    items = [
        {"incident_id": "A", "status": "detected", "due_eta": "2026-10-20T12:00:00-05:00", "delay_hours": 24, "critical_units_at_risk": 12},
        {"incident_id": "B", "status": "approved", "due_eta": "2026-10-19T14:00:00-05:00", "delay_hours": 72, "critical_units_at_risk": 0},
        {"incident_id": "C", "status": "verified", "due_eta": "2026-10-20T12:00:00-05:00", "delay_hours": 48, "critical_units_at_risk": 12},
    ]
    night = journey(f"m.queueTrails({json.dumps(items)})")
    first, second, done = night["lanes"]
    assert [lane["id"] for lane in night["lanes"]] == ["A", "B", "C"] and first["y"] < second["y"] < done["y"]
    assert night["hub"]["y"] == night["height"] / 2 and night["hub"]["x"] < min(lane["promise"] for lane in night["lanes"])
    assert first["late"] and first["risk"] == 12 and first["end"] > first["promise"]
    assert second["end"] - second["promise"] == pytest.approx(3 * (first["end"] - first["promise"]), abs=0.3)
    assert done["done"] and not done["late"] and done["end"] == done["promise"] and done["risk"] == 0
    assert all(0 <= lane["promise"] <= lane["end"] <= night["width"] for lane in night["lanes"])
    assert journey("m.queueTrails([])")["lanes"] == []


def test_the_module_never_touches_the_page():
    script = JOURNEY.read_text()
    assert "document" not in script and "innerHTML" not in script and "fetch(" not in script
    assert script.rstrip().endswith('})(typeof window === "undefined" ? globalThis : window);')
