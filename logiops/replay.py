"""Explicit, zero-cost local replay for demos and UI development."""

from __future__ import annotations

from typing import Any


class ReplayConverse:
    async def converse(
        self, messages: list[dict[str, Any]], system: str, tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
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
        plans = next(
            item["toolResult"]["content"][0]["json"]["plans"]
            for item in results if item["toolResult"]["toolUseId"] == "investigate_incident"
        )
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
