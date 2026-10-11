"""The grounding check decides whether a model's answer can be shown as-is; it never calls a model."""

import json
import re
from pathlib import Path

import pytest

from logiops.evaluator import check_recommendation, check_verification, figures_in, recommended_plan_id
from logiops.scenario import build_plans, known_figures, seed_state

CASES = json.loads((Path(__file__).resolve().parent / "grounding_cases.json").read_text())


def fill(case):
    """A shared case with real plans: the incident's seed plans, and the answer with their ids."""
    state = seed_state(case["incident"])
    plans = build_plans(state, 1)
    by_kind = {plan["kind"]: plan["id"] for plan in plans}
    answer = re.sub(r"\{id:([a-z-]+)\}", lambda match: by_kind[match.group(1)], case["answer"])
    return state, plans, answer.replace("{run}", state["scenario_run_id"]), by_kind.get(case.get("expected"))


@pytest.mark.parametrize("case", CASES["recommended"], ids=lambda case: case["name"])
def test_the_recommended_plan_follows_the_shared_cases(case):
    _state, plans, answer, expected = fill(case)
    assert recommended_plan_id(answer, plans, case.get("require_line", False)) == expected


@pytest.mark.parametrize("case", CASES["grounding"], ids=lambda case: case["name"])
def test_the_grounding_check_follows_the_shared_cases(case):
    state, plans, answer, _expected = fill(case)
    result = check_recommendation(answer, plans, known_figures(state), case.get("require_line", False))
    assert result["passed"] is case["passed"], result["issues"]
    if "issue" in case:
        assert case["issue"] in " ".join(result["issues"])

PLANS = build_plans(seed_state(), 1)
IDS = {plan["kind"]: plan["id"] for plan in PLANS}
URL = "https://news.example.com/panamericana"
SOURCES = [{"url": URL, "text": "Strike on the Panamericana Sur: trucks held for up to 6 hours"}]
CONTEXT = {"dollars": [80, 120], "hours": [12]}
WEB_CONTEXT = {**CONTEXT, "sources": SOURCES}


def test_a_real_style_answer_with_a_table_and_one_choice_passes():
    answer = (
        "SHIP-421 is delayed by 12 hours (12-hour delay).\n"
        f"| `{IDS['wait']}` | wait | 12 h | $0 |\n"
        f"| `{IDS['reroute']}` | reroute | 3 h | $80 |\n"
        f"| `{IDS['split-express']}` | split-express | 0 h | $120 |\n"
        f"Choose plan `{IDS['split-express']}`. Delivery is projected and has not been executed."
    )
    result = check_recommendation(answer, PLANS, CONTEXT)
    assert result == {"passed": True, "issues": [], "recommended_plan_id": IDS["split-express"]}
    assert recommended_plan_id(answer, PLANS) == IDS["split-express"]


@pytest.mark.parametrize("answer, problem", [
    ("I recommend split + express.", "cite its exact plan id"),
    (f"I recommend {IDS['split-express']} for $99.", "$99"),
    (f"I recommend {IDS['split-express']}, only 1 h late.", "1 h"),
    (f"I recommend {IDS['split-express']}; it has been approved.", "has been approved"),
])
def test_ungrounded_answers_are_rejected_with_the_reason(answer, problem):
    result = check_recommendation(answer, PLANS, CONTEXT)
    assert not result["passed"]
    assert problem in " ".join(result["issues"])


def test_each_order_delay_may_be_quoted():
    plans = build_plans(seed_state("SHIP-433"), 1)
    best = next(plan for plan in plans if plan["kind"] == "priority-air-ground")
    answer = (f"Fly the hospital order and rebook the store order: the hospital is on time and the store "
              f"waits 8 h, for $390 extra. The carrier itself would be 24 h late. I recommend {best['id']}. "
              "Delivery is projected, not physically confirmed.")
    assert check_recommendation(answer, plans, known_figures(seed_state("SHIP-433")))["passed"] is True
    wrong = answer.replace("waits 8 h", "waits 5 h")
    assert check_recommendation(wrong, plans, known_figures(seed_state("SHIP-433")))["passed"] is False


@pytest.mark.parametrize("answer, flagged", [
    ("costs $120,000", "$120000"),
    ("costs US$300", "$300"),
    ("costs USD 250", "$250"),
    ("costs 95 dollars", "$95"),
    ("costs $1.5k", "$1500"),
    ("takes 12–24 hours", "24 h"),
    ("takes 12 to 30 h", "30 h"),
])
def test_amounts_and_ranges_are_read_the_way_people_write_them(answer, flagged):
    result = check_recommendation(f"I recommend {IDS['split-express']}; it {answer}.", PLANS, CONTEXT)
    assert not result["passed"] and flagged in " ".join(result["issues"]), result["issues"]


def test_a_web_figure_is_accepted_only_on_its_urls_line_and_from_its_snippet():
    base = f"I recommend {IDS['split-express']} at $120 with 0 h delay."
    attributed = check_recommendation(f"{base}\nA strike may hold trucks for up to 6 hours ({URL}).", PLANS, WEB_CONTEXT)
    assert attributed["passed"], attributed["issues"]
    detached = check_recommendation(f"{base}\nA strike may hold trucks for up to 6 hours.", PLANS, WEB_CONTEXT)
    assert not detached["passed"] and "same line as its URL" in detached["issues"][0]
    invented = check_recommendation(f"{base}\nA strike may hold trucks for 9 hours and cost $300 ({URL}).", PLANS, WEB_CONTEXT)
    assert not invented["passed"]
    assert invented["issues"] == [f"These figures are not in the cited web result ({URL}): $300, 9 h."]
    mixed = check_recommendation(f"I recommend {IDS['split-express']} for 6 hours ({URL}).", PLANS, WEB_CONTEXT)
    assert not mixed["passed"]


@pytest.mark.parametrize("web_line", [
    "Trucks are held for up to 6 hours. Source: " + URL,
    "Trucks are held for up to 6 hours.\nSource: " + URL,
    f'Web, unverified: "Strike on the Panamericana Sur. Trucks held for up to 6 hours" ({URL})',
    f"The 12-hour delay may grow: trucks are held for up to 6 hours ({URL}).",
])
def test_common_citation_styles_are_attributed(web_line):
    sources = [{"url": URL, "text": "Strike on the Panamericana Sur. Trucks held for up to 6 hours"}]
    answer = f"I recommend {IDS['split-express']} at $120.\n{web_line}"
    result = check_recommendation(answer, PLANS, {**CONTEXT, "sources": sources})
    assert result["passed"], result["issues"]


def test_web_amounts_with_separators_must_match_the_snippet():
    context = {**CONTEXT, "sources": [{"url": URL, "text": "Tolls rose to $1,200 per convoy"}]}
    honest = check_recommendation(f"I recommend {IDS['wait']}.\nTolls rose to $1,200 per convoy ({URL}).", PLANS, context)
    assert honest["passed"], honest["issues"]
    short = check_recommendation(f"I recommend {IDS['wait']}.\nTolls rose to $1.2k per convoy ({URL}).", PLANS, context)
    assert short["passed"], short["issues"]
    wrong = check_recommendation(f"I recommend {IDS['wait']}.\nTolls rose to $1,900 per convoy ({URL}).", PLANS, context)
    assert not wrong["passed"] and "$1900" in wrong["issues"][0]
    assert check_recommendation(f"I recommend {IDS['split-express']}: 3 to 12 hours of delay avoided.", PLANS, CONTEXT)["passed"]


def test_the_verification_check_catches_a_delivery_claim():
    snapshot = {
        "state": {"shipment": {"units_on_delayed_route": 0}, "fulfillments": [{"units": 12}, {"units": 8}],
                  "notifications": [{}, {}], "status": "verified"},
        "executions": [{"plan_id": "P-1"}],
    }
    good = check_verification("Plan P-1: 20 units accounted for. Delivery is projected.", snapshot)
    bad = check_verification("Plan P-1: the 20 laptops were delivered.", snapshot)
    assert good["passed"] and not bad["passed"]
    assert any("delivered" in issue for issue in bad["issues"])


def test_the_verification_check_matches_whole_numbers_and_neutral_wording():
    snapshot = {"state": {"shipment": {"units_on_delayed_route": 0}, "fulfillments": [], "notifications": [],
                          "status": "verified"},
                "executions": [{"plan_id": "P-1", "accounted_units": 20}]}
    assert check_verification("Plan P-1: 120 units on 2026-10-12, projected.", snapshot)["passed"] is False
    assert check_verification("Plan P-1: 20 units accounted for, projected.", snapshot)["passed"] is True
    issues = check_verification("Plan P-1: 20 units were delivered.", snapshot)["issues"]
    assert any("do not claim the units were delivered" in issue for issue in issues)


def test_figures_written_in_a_text_are_read_like_an_answer():
    assert figures_in("Keep it under $1.2k, at most 6 hours late, and ship 12 more laptops.") == {
        "dollars": [1200.0], "hours": [6.0], "units": [12.0]}
    assert figures_in("No numbers here.") == {"dollars": [], "hours": [], "units": []}
