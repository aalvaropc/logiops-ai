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
  It requires a verified pre-deploy SQLite backup and stops if the backup fails.
- `install_recovery.py` — renders the SQLite backup, deploy hook and reset-pause
  setup into a Systems Manager parameters file for an existing instance.
  `docs/release-recovery.md` has the steps.
- `verify_remote.py` — resets the demo and checks the inbox. Against the HTTPS
  demo endpoint, it runs the complete synthetic Bedrock, approval and execution
  flow on SHIP-421. It then checks the Agent Skill, a booking with its receipt, a
  proactive alert, Polly and the memory. It spends one live investigation.
- `check_oauth.py` — walks a deployment's OAuth discovery the way an MCP client
  does, with no credentials:
  - the 401 challenge;
  - the RFC 9728 and RFC 8414 metadata;
  - a PKCE authorization request that opens the sign-in page.
- `create_demo_user.py` — creates or resets the judges' demo user in the Cognito
  user pool; the password goes only to `.secrets/demo-user`.
- `audit_dependencies.py` — audits the production requirements with pip-audit
  (`security/README.md`).
- `verify_vendor.py` — checks the vendored `mcp-apps-web-host` files against
  their recorded hashes; `--upstream` also compares them with the library's
  commit on GitHub.
- `sqlite_backup.py` — the verified SQLite backup and restore check used on the
  instance (`docs/release-recovery.md`).
- `screenshots.py` — captures the README screenshots (`docs/img/`) from a replay
  server it starts itself, headless; needs the `browser` extra and Chromium.
- `rehearse.sh [port]` — frees the port (by port, never by process name),
  starts the demo in replay mode (zero tokens) and prints the phrases for a
  rehearsal or a recording take.
- `rehearse_api.py` — the whole flow headless against a replay server,
  with PASS or FAIL per step:
  - the four incidents and their isolation;
  - the briefing and a $250 spend cap;
  - the refused stale approval;
  - the $466.10 booking.
- `clean_room.sh <ref>` — clones a ref into a temporary directory and runs
  the install, the tests, the Docker build, `check_mcp.py` and
  `rehearse_api.py` from scratch.
