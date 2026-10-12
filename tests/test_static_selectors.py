"""The page's plan selectors agree with the Python ranking on every incident's real plans."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from logiops.scenario import INCIDENT_IDS, best_plan, build_plans, rank_key, seed_state

STATIC = Path(__file__).resolve().parents[1] / "logiops" / "static"


def selectors(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    program = (f"const intent = require({str(STATIC / 'intent.js')!r});"
               f"import({json.dumps((STATIC / 'app' / 'selectors.js').as_uri())}).then((m) => console.log(JSON.stringify({script})));")
    out = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_the_default_pick_and_the_cheapest_plan_match_python(incident_id):
    state = seed_state(incident_id)
    plans = build_plans(state, 1)
    snapshot = {"source_version": 1, "plans": plans, "approvals": [], "executions": [], "events": [], "state": state}
    picked, cheapest = selectors(
        f"[m.recommendedPlan({json.dumps(snapshot)}, intent).id, m.planFromUtterance('approve the cheapest plan', {json.dumps(snapshot)}, intent).id]")
    assert picked == best_plan(plans)["id"]
    assert cheapest == min(plans, key=lambda plan: (plan["incremental_cost_usd"], rank_key(plan)))["id"]
