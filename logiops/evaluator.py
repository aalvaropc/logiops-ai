"""Deterministic checks that a model's answer is grounded in the workflow's own data.

The model writes the explanation; these checks decide whether it can be shown
as-is. They never call a model, so a failed check is always reproducible.
"""

from __future__ import annotations

import re
from typing import Any


NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6}
DOLLARS = re.compile(rf"(?:US\$|USD\s?|\$)\s?({NUMBER})(?:\s?(k|thousand|mn|m|million)\b)?", re.I)
DOLLAR_WORDS = re.compile(rf"\b({NUMBER})\s?(?:USD|dollars?)\b", re.I)
HOURS = re.compile(
    rf"\b({NUMBER})(?:\s?(?:-|–|—|to)\s?({NUMBER}))?\s?(?:-\s?)?(?:h\b|hours?\b|hrs?\b)", re.I
)
URL = re.compile(r"https?://\S+")
RECOMMEND = re.compile(r"\b(recommend\w*|choose|select|go with|suggest\w*)\b", re.I)
FALSE_CLAIMS = re.compile(
    r"\b(?:has|have|was|were|is|are)\s+(?:been\s+)?(?:already\s+)?"
    r"(approved|executed|delivered|physically delivered)\b",
    re.I,
)
NEGATION_BEFORE = re.compile(r"\b(not|never|no|until|before|once|after|unless|only)\b[^.]{0,40}$", re.I)


def _value(number: str, multiplier: str = "") -> float:
    return float(number.replace(",", "")) * MULTIPLIERS.get(multiplier.lower(), 1)


def _dollars(text: str) -> set[float]:
    return {_value(number, unit) for number, unit in DOLLARS.findall(text)} | {
        _value(number) for number in DOLLAR_WORDS.findall(text)
    }


def _hours(text: str) -> set[float]:
    found: set[float] = set()
    for first, second in HOURS.findall(text):
        found.add(_value(first))
        if second:
            found.add(_value(second))
    return found


def _claims(text: str) -> list[str]:
    """Affirmative claims of approval, execution or delivery, ignoring negated ones."""
    found = []
    for match in FALSE_CLAIMS.finditer(text):
        if not NEGATION_BEFORE.search(text[max(0, match.start() - 60):match.start()]):
            found.append(match.group(0))
    return found


def recommended_plan_id(answer: str, plans: list[dict[str, Any]]) -> str | None:
    """The plan the answer recommends: the only cited id, or the id in a recommending line."""
    cited = [plan["id"] for plan in plans if plan["id"] in answer]
    if len(cited) == 1:
        return cited[0]
    for line in answer.splitlines():
        if RECOMMEND.search(line):
            in_line = [plan["id"] for plan in plans if plan["id"] in line]
            if len(in_line) == 1:
                return in_line[0]
    return None


def _split_attributed(
    answer: str, plans: list[dict[str, Any]], sources: list[dict[str, str]]
) -> tuple[str, list[tuple[str, dict[str, str]]]]:
    """Separate lines that cite a web source (and no plan) from the rest of the answer.

    The unit is a line, not a sentence: real snippets contain ". " and models write
    "... 6 hours. Source: <url>". A line that is only a citation is joined to the line
    before it.
    """
    lines: list[str] = []
    for line in answer.splitlines():
        if lines and URL.search(line) and len(URL.sub("", line).split()) <= 2:
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    plain: list[str] = []
    attributed: list[tuple[str, dict[str, str]]] = []
    for line in lines:
        source = next((item for item in sources if item["url"] in line), None)
        if source and not any(plan["id"] in line for plan in plans):
            attributed.append((line, source))
        else:
            plain.append(line)
    return "\n".join(plain), attributed


def check_recommendation(answer: str, plans: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    """Grounding check for an investigation answer.

    `context` carries the other facts the answer may legitimately quote
    (carrier quotes and the original delay), so those numbers are not flagged.
    Its optional `sources` are web results ({url, text}): a line that cites one
    of their URLs may also quote figures from that result's text.
    """
    issues: list[str] = []
    sources = context.get("sources") or []
    plain, attributed = _split_attributed(answer, plans, sources)
    web_hint = " A figure taken from a web result must be on the same line as its URL." if sources else ""
    recommended = recommended_plan_id(answer, plans)
    if recommended is None:
        issues.append(
            "Recommend exactly one plan and cite its exact plan id from investigate_incident "
            f"(one of: {', '.join(plan['id'] for plan in plans)})."
        )
    allowed_dollars = {float(plan["incremental_cost_usd"]) for plan in plans} | {
        float(value) for value in context.get("dollars", [])
    }
    unknown_dollars = sorted(_dollars(plain) - allowed_dollars)
    if unknown_dollars:
        issues.append(
            "These dollar amounts do not match any plan or carrier quote: "
            + ", ".join(f"${value:g}" for value in unknown_dollars) + "." + web_hint
        )
    allowed_hours = {float(plan["projected_customer_delay_hours"]) for plan in plans} | {
        float(order["delay_hours"]) for plan in plans for order in plan.get("orders", [])
    } | {float(value) for value in context.get("hours", [])}
    unknown_hours = sorted(_hours(plain) - allowed_hours)
    if unknown_hours:
        issues.append(
            "These hour values do not match any plan's delay or the shipment delay: "
            + ", ".join(f"{value:g} h" for value in unknown_hours) + "." + web_hint
        )
    for line, source in attributed:
        unsupported = sorted(
            [f"${value:g}" for value in _dollars(line) - _dollars(source["text"]) - allowed_dollars]
            + [f"{value:g} h" for value in _hours(line) - _hours(source["text"]) - allowed_hours]
        )
        if unsupported:
            issues.append(f"These figures are not in the cited web result ({source['url']}): {', '.join(unsupported)}.")
    claims = _claims(answer)
    if claims:
        issues.append(
            "Do not claim that a plan was approved, executed or delivered; a person approves it later: "
            + "; ".join(claims) + "."
        )
    return {"passed": not issues, "issues": issues, "recommended_plan_id": recommended}


def check_verification(report: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Grounding check for a post-execution verification report."""
    issues: list[str] = []
    state = snapshot["state"]
    execution = snapshot["executions"][0] if snapshot["executions"] else None
    accounted = (execution or {}).get("accounted_units")
    if accounted is None:
        accounted = state["shipment"]["units_on_delayed_route"] + sum(item["units"] for item in state["fulfillments"])
    facts = {
        "executed_plan_id": execution["plan_id"] if execution else None,
        "units_accounted": accounted,
        "notifications": len(state["notifications"]),
        "status": state["status"],
    }
    if execution is None:
        issues.append("There is no execution to verify.")
    if not re.search(rf"(?<![\d.]){accounted}(?![\d])", report):
        issues.append(f"State how many units are accounted for ({accounted}).")
    if execution and execution["plan_id"] not in report:
        issues.append(f"Cite the executed plan id ({execution['plan_id']}).")
    if re.search(r"\b(?:was|were|has been|have been)\s+(?:physically\s+)?delivered\b", report, re.I) and not re.search(
        r"\bnot\b[^.]{0,30}\bdelivered\b", report, re.I
    ):
        issues.append("Delivery is only projected; do not claim the units were delivered.")
    if not re.search(r"\b(projected|not (?:physically )?(?:confirmed|delivered))\b", report, re.I):
        issues.append("Say that delivery is projected, not physically confirmed.")
    return {"passed": not issues, "issues": issues, "facts": facts}
