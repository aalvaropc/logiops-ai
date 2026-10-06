"""Explicit, zero-cost local replay for demos and UI development."""

from __future__ import annotations

import json
import re
from typing import Any

from .bedrock import BedrockError

PLAN_KEYWORDS = (
    ("split-express", re.compile(r"\b(split|express)\b", re.I)),
    ("reroute", re.compile(r"\b(reroute|re-route|rerouting|economy)\b", re.I)),
    ("wait", re.compile(r"\bwait(ing)?\b", re.I)),
)
CHEAPEST = re.compile(r"\b(cheap(er|est)?|lowest cost|least expensive)\b", re.I)


class ReplayConverse:
    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        from .agent import FOLLOWUP_PROMPT

        if system == FOLLOWUP_PROMPT:
            return self._follow_up(messages[0]["content"][0]["text"])
        if len(messages) == 1:
            calls = [
                ("get_shipment", {"shipment_id": "SHIP-421"}),
                ("get_order", {"order_id": "ORD-421"}),
                ("get_inventory", {"warehouse_id": "arequipa", "sku": "LAPTOP-01"}),
                ("find_alternative_carriers", {"shipment_id": "SHIP-421"}),
                ("investigate_incident", {"shipment_id": "SHIP-421"}),
            ]
            return {
                "stopReason": "tool_use",
                "usage": {"inputTokens": 0, "outputTokens": 0},
                "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": name, "name": name, "input": arguments}}
                    for name, arguments in calls
                ]}},
            }
        results = messages[-1]["content"]
        result = next(item["toolResult"] for item in results if item["toolResult"]["toolUseId"] == "investigate_incident")
        if result.get("status") == "error":
            # Same outcome as a real model that cannot calculate plans: a clear agent error.
            raise BedrockError("Agent could not calculate the incident plans: "
                               + json.dumps(result["content"][0].get("json", {}))[:200])
        plans = result["content"][0]["json"]["plans"]
        selected = min(plans, key=lambda plan: (
            plan["projected_customer_delay_hours"], plan["incremental_cost_usd"]
        ))
        summary = "; ".join(
            f"{plan['label']}: {plan['projected_customer_delay_hours']}h projected delay, "
            f"${plan['incremental_cost_usd']} incremental cost, ETA {plan['projected_completion_eta']}"
            for plan in plans
        )
        answer = (
            f"SHIP-421 has a delayed route. Options: {summary}. "
            f"Recommend {selected['label']} ({selected['id']}). "
            "Delivery is projected, not physically confirmed. A human must approve before execution."
        )
        return {
            "stopReason": "end_turn",
            "usage": {"inputTokens": 0, "outputTokens": 0},
            "output": {"message": {"role": "assistant", "content": [{"text": answer}]}},
        }

    @staticmethod
    def _follow_up(text: str) -> dict[str, Any]:
        """Answer from the <context> block alone, with no tool calls, like a cheap follow-up turn."""
        question = json.loads(text.rsplit("Follow-up question:", 1)[1])
        context = json.loads(text.split("<context>", 1)[1].split("</context>", 1)[0])
        plans = context["plans"]
        fastest = min(plans, key=lambda p: (p["projected_customer_delay_hours"], p["incremental_cost_usd"]))
        cheapest = min(plans, key=lambda p: (p["incremental_cost_usd"], p["projected_customer_delay_hours"]))
        # Once executed, an open question is about what actually ran.
        executed = next((p for p in plans if context.get("execution") and p["id"] == context["execution"]["plan_id"]), None)
        plan = next(
            (p for kind, pattern in PLAN_KEYWORDS if pattern.search(question) for p in plans if p["kind"] == kind),
            cheapest if CHEAPEST.search(question) else executed or fastest,
        )
        answer = (
            f"{plan['label']} ({plan['id']}): {plan['projected_customer_delay_hours']} h projected delay, "
            f"${plan['incremental_cost_usd']} extra, projected completion {plan['projected_completion_eta']}. "
            "Delivery is projected, not physically confirmed; a person approves before execution."
        )
        return {
            "stopReason": "end_turn",
            "usage": {"inputTokens": 0, "outputTokens": 0},
            "output": {"message": {"role": "assistant", "content": [{"text": answer}]}},
        }
