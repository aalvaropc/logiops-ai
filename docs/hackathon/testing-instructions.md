# Testing instructions for judges

Hosting is optional for this track (see `decisions.md` D-AMZ-1) — a judge can
run the MCP server locally.

1. Install Python 3.12+ and `uv`. Run `uv sync --extra dev`. The AWS CLI is
   needed only for the live Bedrock path.
2. For an AWS-free demo, start `LOGIOPS_AGENT_MODE=replay uv run uvicorn
   logiops.api:app --host 127.0.0.1 --port 8000`. For the Bedrock path, run
   `aws login` and omit `LOGIOPS_AGENT_MODE`.
3. Run `uv run python scripts/check_mcp.py http://127.0.0.1:8000/mcp`.
   This performs MCP `initialize`, `tools/list`, and
   `tools/call(get_shipment)` and prints the negotiated protocol version.
4. Open `http://127.0.0.1:8000/demo`. Reset the synthetic incident, run the
   agent investigation, compare three projected plans, select one, approve it
   as the operator, and execute it. The timeline records the resulting events.
5. To verify idempotence directly, repeat `POST /incidents/SHIP-421/execute`
   with the approved `plan_id` and `source_version`. The response is identical
   and allocations and notifications are not duplicated.

If testing a remote HTTPS deployment, set `LOGIOPS_ACCESS_TOKEN` in your
shell before step 3 and use its HTTPS `/mcp` URL. Credentials and the final
browser URL will be provided with the submission if a hosted demo is used.
