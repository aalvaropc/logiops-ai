# Decisions log

One row per gate or decision relevant to this submission. Newest at the
bottom.

| ID | Decision | Date | Evidence |
|---|---|---|---|
| D-AWS-1 | Region `us-east-1`, model `global.anthropic.claude-sonnet-4-6` for the runtime. | 2026-10-02 | Bedrock Converse API call, `stopReason: tool_use`, 637 tokens. |
| D-AWS-2 | Claude Sonnet 5.5 is not available on this account (`AccessDeniedException`). Not pursued further; fallback would be Amazon Nova. | 2026-10-02 | Error in the Bedrock Playground. |
| D1 | Repo starts **private**. Add the 6 reviewers from the Official Rules before submitting if it stays private at submission time. | 2026-10-03 | Owner decision. |
| D2 | Alexa+ "Option B" developer tools (Category SDK, MCP Toolkit, CLI, Web Simulator) are partner-only, not available to hackathon participants. Confirmed approach: a real self-hosted MCP server (Streamable HTTP) + our own front end that demos the experience. | 2026-10-03 | Hackathon FAQ: "there is currently no way for hackathon participants to apply for or gain access... build a self-hosted MCP server (or Agent Skill)... and demo it via your own web-based simulator or front end." |
| D-AMZ-1 | This track does **not** require live hosting during judging. A public, locally runnable repo + README + video is enough; judges build and test it themselves. A live deployment is recommended (for the video, and in case a judge wants to try it live) but optional. | 2026-10-03 | FAQ: "A locally runnable public repo plus your demo video is enough — judges can download, build, and test it themselves, so hosting isn't required." Rules, Testing section: "Projects do not need to be publicly available." |
| D-MCP-1 | Use official Python MCP SDK `1.28.1`, stateless Streamable HTTP at `/mcp`. Local official SDK client negotiated protocol `2025-11-25` and called `get_shipment`. Public HTTPS validation remains open for G3. | 2026-10-05 | `tests/test_mcp.py`, `scripts/check_mcp.py`. |

## Still open

- Where exactly Product Feedback / Friction Logs are submitted (form field vs
  repo file vs link). Verify once the submission form is opened.
- Whether the repo URL can point to a tag/release instead of the default
  branch.
- Whether `testing@devpost.com` has a GitHub username to invite, relevant
  only if this repo stays private at submission time.
- Whether the AWS promotional credits, once approved, actually cover Bedrock
  usage for Claude (vs. only AWS-native services).
