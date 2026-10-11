"""The grounding check decides whether a model's answer can be shown as-is; it never calls a model."""

import pytest

from logiops.evaluator import check_recommendation, check_verification, recommended_plan_id
from logiops.scenario import build_plans, known_figures, seed_state

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
