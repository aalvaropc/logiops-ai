"""Explicit, zero-cost local replay for demos and UI development."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .bedrock import BedrockError
from .scenario import best_plan

PLAN_KEYWORDS = (
    ("express-transfer", re.compile(r"\btransfer\b", re.I)),
    ("priority-air-ground", re.compile(r"\b(air|fly|flight)\b.*\bground\b|\bground\b.*\b(air|fly|flight)\b", re.I)),
    ("priority-air", re.compile(r"\b(air|fly|flight)\b", re.I)),
    ("split-expedite", re.compile(r"\b(split|stock)\b.*\bexpedit|\bexpedit\w*\b.*\b(split|stock)\b", re.I)),
    ("expedite", re.compile(r"\bexpedit\w*\b|\bbroker\b", re.I)),
    ("first-come", re.compile(r"\b(first[- ]come|as placed|school first)\b", re.I)),
    ("priority-first", re.compile(r"\b(hospital first|priority first)\b", re.I)),
    ("split-express", re.compile(r"\b(split|express)\b", re.I)),
    ("local-stock", re.compile(r"\b(local|warehouse)\b", re.I)),
    ("reroute", re.compile(r"\b(reroute|re-route|rerouting|economy|rebook)\b", re.I)),
    ("wait", re.compile(r"\bwait(ing)?\b", re.I)),
)
CHEAPEST = re.compile(r"\b(cheap(er|est)?|lowest cost|least expensive)\b", re.I)
SHIPMENT = re.compile(r"Shipment: (\S+?)\.(\s|$)")


def _tool_use(calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return {
        "stopReason": "tool_use",
        "usage": {"inputTokens": 0, "outputTokens": 0},
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"{name}:{index}", "name": name, "input": arguments}}
            for index, (name, arguments) in enumerate(calls)
        ]}},
    }


def _text(answer: str) -> dict[str, Any]:
    return {
        "stopReason": "end_turn",
        "usage": {"inputTokens": 0, "outputTokens": 0},
        "output": {"message": {"role": "assistant", "content": [{"text": answer}]}},
    }


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%b %d, %H:%M").replace(" 0", " ") + " local time"


def _result(messages: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """The latest result of a tool, also when a revision request came after it."""
    for message in reversed(messages):
        for item in message["content"]:
            result = item.get("toolResult") if isinstance(item, dict) else None
            if result and result["toolUseId"].split(":", 1)[0] == tool:
                return result
    raise BedrockError(f"The replay found no {tool} result")


class ReplayConverse:
    """A scripted model: reads the shipment, then its orders and stock, then plans."""

    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]], skill: str | None = None
    ) -> dict[str, Any]:
        from .agent import BRIEFING_PROMPT, FOLLOWUP_PROMPT

        if system == FOLLOWUP_PROMPT:
            return self._follow_up(messages[0]["content"][0]["text"])
        if system == BRIEFING_PROMPT:
            return self._briefing(messages)
        turn = sum(1 for message in messages if message["role"] == "assistant")
        if turn == 0:
            shipment_id = SHIPMENT.search(messages[0]["content"][0]["text"]).group(1)
            return _tool_use([
                ("get_shipment", {"shipment_id": shipment_id}),
                ("find_alternative_carriers", {"shipment_id": shipment_id}),
            ])
        if turn == 1:
            shipment = _result(messages, "get_shipment")["content"][0]["json"]
            calls = [("get_order", {"order_id": order_id}) for order_id in shipment["order_ids"]]
            if shipment.get("warehouse_id"):
                calls.append(("get_inventory", {"warehouse_id": shipment["warehouse_id"], "sku": shipment["sku"]}))
            calls.append(("investigate_incident", {"shipment_id": shipment["id"]}))
            return _tool_use(calls)
        result = _result(messages, "investigate_incident")
        if result.get("status") == "error":
            raise BedrockError("Agent could not calculate the incident plans: "
                               + json.dumps(result["content"][0].get("json", {}))[:200])
        plans = result["content"][0]["json"]["plans"]
        shipment = next(
            item["toolResult"]["content"][0]["json"]
            for message in messages if message["role"] == "user" and isinstance(message["content"], list)
            for item in message["content"] if "toolResult" in item
            and item["toolResult"]["toolUseId"].split(":", 1)[0] == "get_shipment"
        )
        preference = result["content"][0]["json"].get("operator_preferences")
        selected = next(
            (plan for plan in plans if preference and plan["id"] == preference["preferred_plan_id"]), best_plan(plans)
        )
        summary = "; ".join(
            f"{plan['label']}: {plan['projected_customer_delay_hours']}h projected delay, "
            f"${plan['incremental_cost_usd']} incremental cost, ETA {plan['projected_completion_eta']}"
            for plan in plans
        )
        because = ""
        if preference and preference["changes_pick"]:
            because = f"Your saved preference changes the pick: {preference['reason']} "
        warnings = " ".join(preference["warnings"]) + " " if preference and preference["warnings"] else ""
        answer = (
            f"{shipment['id']}: {shipment['disruption']} Options: {summary}. "
            f"{because}{warnings}Recommend {selected['label']}. "
            "Delivery is projected, not physically confirmed. A human must approve before execution.\n"
            f"Spoken: {shipment['id']} needs a decision. I recommend: {selected['label']}.\n"
            f"Recommended plan: {selected['id']}"
        )
        return _text(answer)

    @staticmethod
    def _follow_up(text: str) -> dict[str, Any]:
        """Answer from the <context> block alone, with no tool calls, like a cheap follow-up turn."""
        question = json.loads(text.rsplit("Follow-up question:", 1)[1])
        context = json.loads(text.split("<context>", 1)[1].split("</context>", 1)[0])
        plans = context["plans"]
        preference = context.get("operator_preferences")
        best = next((p for p in plans if preference and p["id"] == preference["preferred_plan_id"]), best_plan(plans))
        cheapest = min(plans, key=lambda p: (p["incremental_cost_usd"], p["projected_customer_delay_hours"]))
        executed = next((p for p in plans if context.get("execution") and p["id"] == context["execution"]["plan_id"]), None)
        plan = next(
            (p for kind, pattern in PLAN_KEYWORDS if pattern.search(question) for p in plans if p["kind"] == kind),
            cheapest if CHEAPEST.search(question) else executed or best,
        )
        answer = (
            f"{plan['label']}: {plan['projected_customer_delay_hours']} h projected delay, "
            f"${plan['incremental_cost_usd']} extra, projected completion {plan['projected_completion_eta']}. "
            "Delivery is projected, not physically confirmed; a person approves before execution.\n"
            f"Spoken: {plan['label']}: {plan['projected_customer_delay_hours']} hours of delay, "
            f"{plan['incremental_cost_usd']} dollars extra."
        )
        return _text(answer)

    @staticmethod
    def _briefing(messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Read the inbox and keep the server's order: open first, most critical units at risk next."""
        if len(messages) == 1:
            return _tool_use([("list_incidents", {})])
        incidents = _result(messages, "list_incidents")["content"][0]["json"]["incidents"]
        open_ = [item for item in incidents if item["status"] != "verified"]
        resolved = len(incidents) - len(open_)
        if not open_:
            return _text(f"All {resolved} incidents are resolved; nothing needs attention.\n"
                         "Spoken: Every incident is resolved.")
        lines = []
        for index, item in enumerate(open_, 1):
            critical = [order["customer"] for order in item["orders"] if order["priority"] == "critical"]
            who = f"critical order for {', '.join(critical)}" if critical else f"{item['units']} units"
            risk = f", {item['critical_units_at_risk']} critical units at risk" if item["critical_units_at_risk"] else ""
            lines.append(f"{index}. {item['incident_id']} ({item['kind_label']}, {item['route']}): {item['title'].rstrip('.')}; "
                         f"{who}{risk}, due {_local(item['due_eta'])}, +{item['delay_hours']} h.")
        first = open_[0]
        tail = f" {resolved} resolved." if resolved else ""
        why = (f"{first['critical_units_at_risk']} critical units at risk" if first["critical_units_at_risk"]
               else f"due {_local(first['due_eta'])}")
        answer = (
            f"{len(open_)} open incidents, the most critical units at risk first.{tail}\n\n" + "\n".join(lines)
            + f"\n\nStart with: {first['incident_id']}\n"
            f"Spoken: You have {len(open_)} open incidents. Start with {first['incident_id']}: {why}."
        )
        return _text(answer)
