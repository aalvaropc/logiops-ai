# Recording checklist

The narration and timings are in the video script. This list covers the setup.

## Before recording

- [ ] Rehearse in replay: `scripts/rehearse.sh` and `uv run python scripts/rehearse_api.py` (zero cost).
- [ ] New browser profile or a clean window: close work tabs, extensions and anything with personal data.
- [ ] Chrome or Edge (the microphone and speech need it). Allow the microphone for the demo page.
- [ ] Locally, the page opened on `127.0.0.1` or `localhost` so the MCP App card shows (the deployed demo has its own sandbox origin).
- [ ] Resolution 1920×1080, browser zoom 100%, notifications off, clock and e-mail not visible.
- [ ] No access token, e-mail address, account id or key visible on screen at any point.
- [ ] `POST /demo/reset` (the "Reset all incidents and preferences" button) just before each take, so no saved preference changes the picks.

## The real take (costs a few cents)

- [ ] Either the deployed demo (token loaded from the file, never shown), or locally: `aws login --region us-east-1`, then start the server without `LOGIOPS_AGENT_MODE`.
- [ ] The reply's meta line shows **bedrock mode** and a non-zero token count. This cannot be rehearsed in replay.
- [ ] Voice input is shown at least once ("Listening…"); if it fails, type the phrase: the flow is the same.
- [ ] Approval → execution → "20 units accounted for". Then reset the incident, investigate and approve again, and a stock change refuses the stale approval (an executed incident's stock control is off).
- [ ] Open a second incident from the inbox (SHIP-433 or SHIP-460): two orders, one critical; the pick protects the critical order and the plan cards show each order's delay.
- [ ] The MCP App card and one follow-up answer are visible.
- [ ] "Any delays today?" briefing, then "remember my spend cap is $250" and SHIP-433 again: the pick moves to the $240 plan and the agent says why.
- [ ] "Read replies aloud" on for one reply: only the short spoken line is read.

## After recording

- [ ] Under 3:00. Public on YouTube or Vimeo. English narration or captions.
- [ ] Watch it once with the sound off to check nothing sensitive appears.
