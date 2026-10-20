# Recording checklist

The narration and timings are in `video-script.md`. This list covers the setup.

## Before recording

- [ ] Rehearse in replay: `scripts/rehearse.sh`, `uv run python scripts/rehearse_api.py` and `LOGIOPS_BROWSER=1 uv run pytest -q tests/browser` (zero cost), then the script by hand, including "Remember my spend cap is $250." and "Recheck".
- [ ] New browser profile or a clean window: close work tabs, extensions and anything with personal data.
- [ ] Chrome or Edge (the microphone and speech need it). Allow the microphone for the device page.
- [ ] Three tabs: the device (`/demo`), the operator console (`/console`) and MCP Inspector (`npx @modelcontextprotocol/inspector`) connected to the deployed `/mcp` with the token pasted in its Authentication panel, the tool list already open. Locally, the two pages on `127.0.0.1` so the MCP App card shows (the deployed demo has its own sandbox origin).
- [ ] Resolution 1920×1080, browser zoom 100%, notifications off, clock and e-mail not visible. The device fits the screen; the console is the second tab.
- [ ] No access token, e-mail address, account id or key visible on screen at any point. The token goes into the console's Developer drawer before recording starts, or sign in with the demo user beforehand.
- [ ] "Reset all incidents and preferences" (console, Developer drawer) just before each take, and `DELETE /memory` or "forget me" so the welcome-back line is the one you expect.
- [ ] SHIP-421 investigated and approved before the take (the stock change at 1:36 needs an approved plan to invalidate), then back to home, where the take starts, with no preference saved.

## The real take (costs a few cents)

- [ ] The deployed demo (token or sign-in loaded, never shown), or locally: `aws login --region us-east-1`, then start the server without `LOGIOPS_AGENT_MODE`.
- [ ] "More" shows **bedrock mode** and a non-zero token count. This cannot be rehearsed in replay.
- [ ] Voice input is shown at least once ("Listening…"); if it fails, type the phrase: the flow is the same.
- [ ] On the device: the agent stage lighting each tool call live with its seconds and "Live from the MCP tool calls", the spoken line in large type, the plans card with the MCP App, its decision field and "Agent pick", the incident's map with the agent's pick, the confirmation card, the result card with "Decided in …", the alert card, and in "More" the Agent Skill and the tool-trace steps with "Checked against the data".
- [ ] Approval → execution → "30 units accounted for" on SHIP-433.
- [ ] A stock change from the console raises the alert on the device (bell → card).
- [ ] "Remember my spend cap is $250.", then "Recheck", moves the pick to the $240 plan with "Your preference", and the approval reads $240 back.
- [ ] In Inspector: the 12 tools, one `get_shipment` call, and the guest `401` on `execute_approved_plan` with the Cognito sign-in (client id and scope from `GET /auth/config` entered beforehand).
- [ ] "Read replies aloud" on for at least one reply: only the short spoken line is read.

## After recording

- [ ] Under 3:00. Public on YouTube or Vimeo. English narration or captions.
- [ ] Watch it once with the sound off to check nothing sensitive appears.
- [ ] `POST /demo/reset` on the deployment.
