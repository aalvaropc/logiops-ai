# Smoke test scripts

- `test_bedrock.sh` — one Converse API call with tool use against Amazon
  Bedrock. Requires `aws login` to have been done already.
- `check_mcp.py` — connects to a local or remote `/mcp` URL using the official
  MCP client, lists tools, and calls `get_shipment`. Set
  `LOGIOPS_ACCESS_TOKEN` when testing an authenticated deployment.
- `create_access_token.py` — creates a random token in SSM SecureString and a
  gitignored local file after AWS authentication is restored.
- `deploy_ec2.py` — packages the pinned app and browser demo, uploads the
  archive to S3, and deploys it to EC2 through Systems Manager.
  `--package-only` validates the archive without AWS access.
- `verify_remote.py` — runs the complete synthetic Bedrock, approval, and
  execution flow against the HTTPS demo endpoint.
