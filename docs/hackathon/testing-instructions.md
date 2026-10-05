# Testing instructions for judges

Hosting is optional for this track (see `decisions.md` D-AMZ-1) — a judge can
run the MCP server locally.

1. Install Python 3.12+, `uv`, and the AWS CLI. Run `uv sync --extra dev`.
2. For an AWS-free demo, start `LOGIOPS_AGENT_MODE=replay uv run uvicorn
   logiops.api:app --host 127.0.0.1 --port 8000`. For the Bedrock path, run
   `aws login` and omit `LOGIOPS_AGENT_MODE`.
3. Run `uv run python scripts/check_mcp.py http://127.0.0.1:8000/mcp`.
   This performs MCP `initialize`, `tools/list`, and
   `tools/call(get_shipment)` and prints the negotiated protocol version.
4. Run `POST /demo/reset`, then
   `POST /incidents/SHIP-421/agent/investigate` with JSON `{}`. The response
   includes the answer, three calculated plans, and MCP tool trace.
5. Approve one exact `plan_id` and `source_version` using
   `POST /incidents/SHIP-421/approvals` with `approved_by`; then call
   `POST /incidents/SHIP-421/execute`. A second execution returns the same
   result without duplicating allocations or notifications.

If testing a remote HTTPS deployment, set `LOGIOPS_ACCESS_TOKEN` in your
shell before step 3 and use its HTTPS `/mcp` URL. Credentials and the final
front-end URL will be provided with the submission if a hosted demo is used.
