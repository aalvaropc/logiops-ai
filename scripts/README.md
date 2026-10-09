# Smoke test scripts

- `test_bedrock.sh` — one Converse API call with tool use against Amazon
  Bedrock. Requires `aws login` to have been done already.
- `check_mcp.py` — connects to a local or remote `/mcp` URL using the official
  MCP client, lists tools, and calls `get_shipment` and `list_incidents`. Set
  `LOGIOPS_ACCESS_TOKEN` when testing an authenticated deployment.
- `create_access_token.py` — creates a random token in SSM SecureString and a
  gitignored local file after AWS authentication is restored.
- `deploy_ec2.py` — packages the pinned app and browser demo, uploads the
  archive to S3, and deploys it to EC2 through Systems Manager.
  `--package-only` validates the archive without AWS access.
- `verify_remote.py` — resets the demo, checks the inbox, and runs the
  complete synthetic Bedrock, approval, and execution flow on SHIP-421 against
  the HTTPS demo endpoint.
- `rehearse.sh [port]` — frees the port (by port, never by process name),
  starts the demo in replay mode (zero tokens) and prints the phrases for a
  rehearsal or a recording take.
- `rehearse_api.py` — the whole flow headless against a replay server,
  with PASS or FAIL per step: the four incidents, isolation, the briefing and
  a $250 spend cap.
- `clean_room.sh <ref>` — clones a ref into a temporary directory and runs
  the install, the tests, the Docker build, `check_mcp.py` and
  `rehearse_api.py` from scratch.
