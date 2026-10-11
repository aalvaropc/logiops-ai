"""Deterministic checks that a model's answer is grounded in the workflow's own data.

The model writes the explanation; these checks decide whether it can be shown
as-is. They never call a model, so a failed check is always reproducible. A
figure, id or time written in a form the checks do not recognise is ignored,
never flagged.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any


NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6}
DOLLARS = re.compile(rf"(?:US\$|USD\s?|\$)\s?({NUMBER})(?:\s?(k|thousand|mn|m|million)\b)?", re.I)
DOLLAR_WORDS = re.compile(rf"\b({NUMBER})\s?(?:USD|dollars?)\b", re.I)
HOURS = re.compile(
    rf"\b({NUMBER})(?:\s?(?:-|–|—|to)\s?({NUMBER}))?\s?(?:-\s?)?(?:h\b|hours?\b|hrs?\b)", re.I
)
UNITS = re.compile(
    rf"\b({NUMBER})\s+(?:(?:more|extra|remaining|other|additional|critical|standard|late)\s+)?"
    r"(?:units?|laptops?|tablets?|routers?|devices?|items?|pieces?|pcs)\b",
    re.I,
)
IDS = re.compile(r"\b(?:SHIP|ORD)-\d+[A-Z]?\b", re.I)
ISO_TIME = re.compile(r"\b(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
MONTHS = {name: number for number, names in enumerate(
    [("jan",), ("feb",), ("mar",), ("apr",), ("may",), ("jun",), ("jul",), ("aug",), ("sep", "sept"), ("oct",), ("nov",), ("dec",)],
    start=1) for name in names}
MONTH_TIME = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\b\s*(a\.?m\.?|p\.?m\.?)?",
    re.I,
)
LIMA = timezone(timedelta(hours=-5))
URL = re.compile(r"https?://\S+")
RECOMMEND = re.compile(r"\b(recommend\w*|choose|select|go with|suggest\w*)\b", re.I)
RECOMMENDED_LINE = re.compile(r"recommended plan(?: id)?\s*[:：][\s`*_\"']*([A-Za-z0-9][A-Za-z0-9:._-]*)", re.I)
NEGATED = re.compile(r"\b(not|never|no|instead of|rather than|avoid)\b|n't\b", re.I)
FALSE_CLAIMS = re.compile(
    r"\b(?:has|have|was|were|is|are)\s+(?:been\s+)?(?:already\s+)?"
    r"(approved|executed|delivered|physically delivered)\b",
    re.I,
)
ACTIVE_CLAIMS = re.compile(
    r"\b(?:I|we|LogiOps)(?:\s+have|\s+has|'ve)?(?:\s+already|\s+just)?\s+(approved|executed|delivered)\b", re.I
)
NEGATION_BEFORE = re.compile(r"\b(not|never|no|nothing|until|before|once|after|unless|only|if)\b[^.]{0,40}$", re.I)


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


def _units(text: str) -> set[float]:
    return {_value(number) for number in UNITS.findall(text)}


def figures_in(text: str) -> dict[str, list[float]]:
    """The dollar amounts, hour values and unit counts written in a text, read the way the check reads
    an answer; for facts given as text, such as an operator's note."""
    return {"dollars": sorted(_dollars(text)), "hours": sorted(_hours(text)), "units": sorted(_units(text))}


def _with_differences(values: set[float], sums: bool = False) -> set[float]:
    """Known values plus the gaps between them (and their sums), so comparisons can be quoted."""
    derived = {abs(a - b) for a, b in combinations(values, 2)}
    if sums:
        derived |= {a + b for a, b in combinations(values, 2)}
    return values | derived


def _lima(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return (moment if moment.tzinfo else moment.replace(tzinfo=LIMA)).astimezone(LIMA)


def _unknown_times(text: str, known: set[datetime]) -> list[str]:
    """Times written as an ISO timestamp or as "Oct 12, 14:00" / "Oct 12, 2:00 PM" that match no
    known time (read as Lima time unless the timestamp carries its own offset)."""
    found = []
    for match in ISO_TIME.finditer(text):
        day, hour, minute, offset = match.groups()
        suffix = "+00:00" if offset == "Z" else (offset[:3] + ":" + offset[-2:] if offset else "")
        try:
            moment = _lima(f"{day}T{hour}:{minute}:00{suffix}")
        except ValueError:
            continue
        if moment not in known:
            found.append(match.group(0))
    wall_clock = {(moment.month, moment.day, moment.hour, moment.minute) for moment in known}
    for match in MONTH_TIME.finditer(text):
        month, day, hour, minute, meridiem = match.groups()
        if minute is None and not meridiem:
            continue
        hour_value = int(hour)
        if meridiem:
            if not 1 <= hour_value <= 12:
                continue
            hour_value = hour_value % 12 + (12 if meridiem.lower().startswith("p") else 0)
        if (MONTHS[month.lower()], int(day), hour_value, int(minute or 0)) not in wall_clock:
            found.append(match.group(0).strip())
    return found


def _claims(text: str) -> list[str]:
    """Affirmative claims of approval, execution or delivery (passive or active voice), ignoring negated ones."""
    found = []
    for pattern in (FALSE_CLAIMS, ACTIVE_CLAIMS):
        for match in pattern.finditer(text):
            if not NEGATION_BEFORE.search(text[max(0, match.start() - 60):match.start()]):
                found.append(match.group(0))
    return found


def _resolve(reference: str, plans: list[dict[str, Any]]) -> str | None:
    """A plan named on a "Recommended plan:" line: its exact id, its kind, or the end of its id."""
    wanted = reference.strip().rstrip(".,;:").lower()
    base, version = re.fullmatch(r"(.+?)(?::v(\d+))?", wanted).groups()

    def same_version(plan: dict[str, Any]) -> bool:
        return version is None or plan["id"].lower().endswith(f":v{version}")

    for rule in (
        lambda plan: plan["id"].lower() == wanted,
        lambda plan: base == plan.get("kind", "").lower() and same_version(plan),
        lambda plan: base == f"{plan['id'].split(':')[0]}:{plan.get('kind', '')}".lower() and same_version(plan),
        lambda plan: plan["id"].lower().endswith(":" + wanted),
    ):
        matches = [plan["id"] for plan in plans if rule(plan)]
        if len(matches) == 1:
            return matches[0]
    return None


def _negated_before(text: str, start: int) -> bool:
    """A negation earlier in the same line and clause, within 40 characters ("not", "rather than")."""
    window = text[max(0, start - 40):start].split("\n")[-1]
    return bool(NEGATED.search(re.split(r"[.;:,!?|]", window)[-1]))


def _affirmed(line: str, plan_id: str) -> bool:
    """The id appears at least once in the line without a negation just before it."""
    return any(not _negated_before(line, match.start()) for match in re.finditer(re.escape(plan_id), line))


def _recommending(text: str) -> list[re.Match[str]]:
    """Recommending words ("recommend", "choose", ...) with no negation just before them."""
    return [match for match in RECOMMEND.finditer(text) if not _negated_before(text, match.start())]


def recommended_plan_id(answer: str, plans: list[dict[str, Any]], require_line: bool = False) -> str | None:
    """The plan the answer recommends. The last "Recommended plan:" line wins (exact id, kind, or
    the end of the id). Without one, unless `require_line`: the only plan cited without a negation,
    else the only one in a line that recommends (not "not recommended"), else the first one after
    the last recommending word.
    The browser's pick follows the same rules; tests/grounding_cases.json holds the shared cases."""
    lines = RECOMMENDED_LINE.findall(answer)
    if lines:
        return _resolve(lines[-1], plans)
    if require_line:
        return None
    text_lines = re.split(r"\r?\n", answer)
    cited = [plan["id"] for plan in plans if any(_affirmed(line, plan["id"]) for line in text_lines)]
    if len(cited) == 1:
        return cited[0]
    for line in text_lines:
        if _recommending(line):
            in_line = [plan["id"] for plan in plans if _affirmed(line, plan["id"])]
            if len(in_line) == 1:
                return in_line[0]
    words = _recommending(answer)
    if not words:
        return None
    tail = answer[words[-1].end():]
    after = sorted((tail.index(plan["id"]), plan["id"]) for plan in plans if plan["id"] in tail)
    return after[0][1] if after else None


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


def check_recommendation(
    answer: str, plans: list[dict[str, Any]], context: dict[str, Any], require_line: bool = False,
) -> dict[str, Any]:
    """Grounding check for an investigation answer.

    `context` carries the other facts the answer may legitimately quote (see
    scenario.known_figures): carrier quotes and delays, and when present unit
    counts, ids and timestamps, which turn on those checks. Gaps between known
    figures are accepted, so comparisons between plans pass. Its optional
    `sources` are web results ({url, text}): a line that cites one of their URLs
    may also quote figures from that result's text (but not gaps).
    """
    issues: list[str] = []
    sources = context.get("sources") or []
    plain, attributed = _split_attributed(answer, plans, sources)
    web_hint = " A figure taken from a web result must be on the same line as its URL." if sources else ""
    recommended = recommended_plan_id(answer, plans, require_line)
    if recommended is None:
        choices = ", ".join(plan["id"] for plan in plans)
        if RECOMMENDED_LINE.search(answer):
            issues.append(f"The Recommended plan line does not name one of the plans from investigate_incident ({choices}).")
        elif require_line:
            issues.append(f"End with one line: Recommended plan: <exact plan id> (one of: {choices}).")
        else:
            issues.append(f"Recommend exactly one plan and cite its exact plan id from investigate_incident (one of: {choices}).")
    known_dollars = {float(plan["incremental_cost_usd"]) for plan in plans} | {
        float(value) for value in context.get("dollars", [])
    }
    unknown_dollars = sorted(_dollars(plain) - _with_differences(known_dollars))
    if unknown_dollars:
        issues.append(
            "These dollar amounts do not match any plan or carrier quote: "
            + ", ".join(f"${value:g}" for value in unknown_dollars) + "." + web_hint
        )
    known_hours = {float(plan["projected_customer_delay_hours"]) for plan in plans} | {
        float(order["delay_hours"]) for plan in plans for order in plan.get("orders", [])
    } | {float(value) for value in context.get("hours", [])}
    unknown_hours = sorted(_hours(plain) - _with_differences(known_hours))
    if unknown_hours:
        issues.append(
            "These hour values do not match any plan's delay or the shipment delay: "
            + ", ".join(f"{value:g} h" for value in unknown_hours) + "." + web_hint
        )
    if "units" in context:
        allowed_units = _with_differences({float(value) for value in context["units"]} | {
            float(item["units"]) for plan in plans for item in plan.get("allocations", [])
        } | {
            float(order[key]) for plan in plans for order in plan.get("orders", []) for key in ("quantity", "late_units")
        } | {float(plan.get("late_units", 0)) for plan in plans}, sums=True)
        unknown_units = sorted(_units(plain) - allowed_units)
        if unknown_units:
            issues.append(
                "These unit counts do not match the orders, stock, carrier capacity or any plan: "
                + ", ".join(f"{value:g}" for value in unknown_units) + "."
            )
    if "ids" in context:
        known_ids = {value.upper() for value in context["ids"]}
        unknown_ids = sorted({value.upper() for value in IDS.findall(plain)} - known_ids)
        if unknown_ids:
            issues.append(f"These ids are not part of this incident: {', '.join(unknown_ids)}.")
    if "times" in context:
        known_times = {_lima(value) for value in context["times"]} | {
            _lima(value) for plan in plans for value in [plan.get("projected_completion_eta")]
            + [item["arrival_eta"] for item in plan.get("allocations", [])]
            + [order[key] for order in plan.get("orders", []) for key in ("due_eta", "arrival_eta")] if value
        }
        unknown_times = _unknown_times(plain, known_times)
        if unknown_times:
            issues.append(
                "These times do not match the incident's data or any plan (Lima time): " + "; ".join(unknown_times) + "."
            )
    for line, source in attributed:
        unsupported = sorted(
            [f"${value:g}" for value in _dollars(line) - _dollars(source["text"]) - known_dollars]
            + [f"{value:g} h" for value in _hours(line) - _hours(source["text"]) - known_hours]
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
