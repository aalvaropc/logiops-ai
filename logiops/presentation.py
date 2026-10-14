"""What a person reads and hears: plans by name, times in local time, no internal identifiers.

The agent's raw answer, with its exact plan ids and closing "Recommended plan:" line, stays in
the audit trail and drives the deterministic pick; only the copy shown and spoken to the
operator is rewritten (Alexa+ add-ons never expose internal ids, codes or JSON to customers).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

LIMA = timezone(timedelta(hours=-5))
PLAN_ID = re.compile(r"`?\bSHIP-\d+:[0-9a-f][0-9a-f-]{7,}:[a-z][a-z-]*:v\d+\b`?", re.I)
RECOMMENDED_LINE = re.compile(r"^[ \t>*_`-]*recommended plan(?: id)?[*_`]*\s*[:：].*(?:\n|$)", re.I | re.M)
ISO_TIME = re.compile(r"\b(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


def local_time(match: re.Match[str]) -> str:
    day, hour, minute, offset = match.groups()
    suffix = "+00:00" if offset == "Z" else (f"{offset[:3]}:{offset[-2:]}" if offset else "-05:00")
    try:
        moment = datetime.fromisoformat(f"{day}T{hour}:{minute}:00{suffix}").astimezone(LIMA)
    except ValueError:
        return match.group(0)
    return f"{moment.strftime('%b')} {moment.day}, {moment.strftime('%H:%M')} local time"


def customer_text(text: str, plans: list[dict[str, Any]]) -> str:
    """The answer as the operator sees and hears it."""
    labels = {plan["id"].lower(): plan["label"] for plan in plans}
    shown = RECOMMENDED_LINE.sub("", text or "")

    def plan_name(match: re.Match[str]) -> str:
        label = labels.get(match.group(0).strip("`").lower())
        return f"“{label}”" if label else "the plan"

    shown = PLAN_ID.sub(plan_name, shown)
    for label in labels.values():
        quoted = f"“{label}”"
        for repeated in (f"{label} ({quoted})", f"{quoted} ({quoted})", f"{quoted} ({label})"):
            shown = shown.replace(repeated, quoted)
    shown = ISO_TIME.sub(local_time, shown)
    shown = re.sub(r"(local time)(?:\s*\(?local time\)?)+", r"\1", shown)
    shown = re.sub(r"[ \t]+\n", "\n", shown)
    return re.sub(r"\n{3,}", "\n\n", shown).strip()


def shown_run(run: dict[str, Any], plans: list[dict[str, Any]]) -> dict[str, Any]:
    """A run as returned to the browser: answer and spoken line rewritten for people."""
    return {**run, "answer": customer_text(run.get("answer", ""), plans), "spoken": customer_text(run.get("spoken", ""), plans)}
