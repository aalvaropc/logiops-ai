"""Run the complete synthetic incident over a deployed HTTPS endpoint, then check the
Agent Skill, a carrier booking with its receipt, a proactive alert, Polly and the memory.

It spends one live Bedrock investigation and a short Polly line, and it clears the operator
token's shared memory. The demo data is reset at the end.
"""

from __future__ import annotations

import argparse
import os
import secrets
import time
from pathlib import Path

import httpx


LOCAL_SECRET = Path(__file__).resolve().parents[1] / ".secrets" / "access-token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="https://<distribution>.cloudfront.net")
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        raise SystemExit("A remote HTTPS URL is required")
    token = os.environ.get("LOGIOPS_ACCESS_TOKEN")
    if not token and LOCAL_SECRET.exists():
        token = LOCAL_SECRET.read_text().strip()
    if not token:
        raise SystemExit("Set LOGIOPS_ACCESS_TOKEN or run create_access_token.py")

    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=125,
    ) as client:
        reset = client.post("/demo/reset")
        reset.raise_for_status()
        inbox = client.get("/incidents")
        inbox.raise_for_status()
        if len(inbox.json()["incidents"]) != 4:
            raise RuntimeError("The deployed inbox does not list the four synthetic incidents")
        investigated = client.post("/incidents/SHIP-421/agent/investigate", json={})
        investigated.raise_for_status()
        run = investigated.json()
        if run.get("fallback") == "daily_budget":
            raise RuntimeError("Today's live model budget is used (LOGIOPS_DAILY_MODEL_CALLS), so the deployment "
                               "answered from replay; try after midnight Lima time or raise the limit")
        if run["mode"] != "bedrock" or len(run["plans"]) != 3:
            raise RuntimeError("The live Bedrock agent did not produce three plans")
        if not any(step["tool"] == "investigate_incident" and not step["is_error"] for step in run["tool_trace"]):
            raise RuntimeError("The agent did not call the MCP investigation tool")
        plan = next(item for item in run["plans"] if item["kind"] == "split-express")
        approval = client.post("/incidents/SHIP-421/approvals", json={
            "plan_id": plan["id"], "source_version": plan["source_version"],
            "approved_by": "remote-verification",
        })
        approval.raise_for_status()
        execution_request = {"plan_id": plan["id"], "source_version": plan["source_version"]}
        first = client.post("/incidents/SHIP-421/execute", json=execution_request)
        first.raise_for_status()
        second = client.post("/incidents/SHIP-421/execute", json=execution_request)
        second.raise_for_status()
        if first.json() != second.json():
            raise RuntimeError("Repeated execution was not idempotent")
        snapshot = client.get("/incidents/SHIP-421")
        snapshot.raise_for_status()
        state = snapshot.json()
        if len(state["executions"]) != 1 or state["state"]["status"] != "verified":
            raise RuntimeError("Operational verification failed")
        if not any(event["name"] == "agent_investigation_completed" for event in state["events"]):
            raise RuntimeError("Agent trace was not persisted")
        print(f"Verified Bedrock run: {len(run['plans'])} plans, {len(run['tool_trace'])} MCP calls")
        print(f"Plan: {plan['kind']}; projected ETA: {plan['projected_completion_eta']}")
        print(f"Token usage: {run['usage']}; one execution; audit events: {len(state['events'])}")
        if run.get("skill", {}).get("name") != "logiops-exception-desk":
            raise RuntimeError("The agent did not load the Agent Skill over MCP")
        print(f"Agent Skill loaded; prompt cache read {run['usage'].get('cacheReadInputTokens', 0)} tokens, "
              f"wrote {run['usage'].get('cacheWriteInputTokens', 0)}")

        quote = client.post("/incidents/SHIP-421/bookings/quote", json={})
        quote.raise_for_status()
        price = quote.json()
        if price["total_usd"] != 147.5:
            raise RuntimeError(f"Unexpected booking total {price['total_usd']}")
        key = f"remote-verify-{secrets.token_hex(6)}"
        paid = client.post(f"/quotes/{price['quote_id']}/confirm", json={"confirmed_total_usd": price["total_usd"], "idempotency_key": key})
        paid.raise_for_status()
        again = client.post(f"/quotes/{price['quote_id']}/confirm", json={"confirmed_total_usd": price["total_usd"], "idempotency_key": key})
        number = paid.json()["number"]
        if again.json().get("number") != number:
            raise RuntimeError("Repeating the payment did not return the same booking")
        receipt = client.get(f"/bookings/{number}/receipt")
        if receipt.status_code != 200 or "$147.50" not in receipt.text:
            raise RuntimeError("The receipt did not show the total charged")
        print(f"Booked {number}: $147.50 charged once (simulated); receipt served")

        client.post("/incidents/SHIP-452/investigate").raise_for_status()
        client.post("/demo/inventory", json={"incident_id": "SHIP-452", "available": 3}).raise_for_status()
        alerts = client.get("/alerts").json()["alerts"]
        if not any(alert["incident_id"] == "SHIP-452" for alert in alerts):
            raise RuntimeError("A stock change after an investigation raised no proactive alert")
        print("Proactive alert raised for SHIP-452 after its stock changed")

        voice = client.get("/voice/config").json()
        if voice["engine"] == "polly":
            speech = client.post("/voice/speech", json={"text": "LogiOps remote check."})
            if speech.status_code != 200 or speech.headers.get("content-type") != "audio/mpeg":
                raise RuntimeError(f"Polly did not return audio ({speech.status_code})")
            print(f"Polly voice {voice['voice']}: {len(speech.content)} bytes of MP3")
        else:
            print("Voice: the browser's own (Polly is not configured or is resting)")

        session = f"s-verify-{secrets.token_hex(4)}"
        client.post("/memory/turns", json={"session": session, "role": "user", "text": "remote verification", "incident": "SHIP-421"})
        recalled = {}
        for _ in range(10):
            time.sleep(1)
            recalled = client.get("/memory", params={"session": f"s-other-{secrets.token_hex(4)}"}).json()
            if any(turn["text"] == "remote verification" for turn in recalled.get("turns", [])):
                break
        else:
            raise RuntimeError(f"The memory ({recalled.get('backend')}) did not recall the turn just written")
        forgotten = client.delete("/memory").json()
        print(f"Memory on {recalled['backend']}: recalled the turn, then forgot {forgotten['forgotten']} item(s)")
        client.post("/demo/reset").raise_for_status()


if __name__ == "__main__":
    main()
