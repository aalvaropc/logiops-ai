# Recording checklist

What was checked for the published video (<https://youtu.be/h30PVrBO8d0>); the shots and the
narration are in `video-script.md`.

## Before the take

- [x] Rehearsed twice against a local replay server: the same flow, zero model calls.
- [x] The day's model budget checked: two agent runs fit.
- [x] The operator token reached the pages only through sessionStorage. It was never typed, shown
  or logged, and the console's token field shows only its placeholder.
- [x] "Reset all incidents and preferences" before the take. SHIP-421 was approved off camera
  through the API, which calculates plans in code without a model call.

## The take

- [x] The deployed demo in bedrock mode. `/metrics` reports `mode: bedrock` for SHIP-433, and no
  fallback notice (replay, guest budget, daily budget, model unavailable) appears on screen.
- [x] On the device:
  - the stations lit live, with "Live from the MCP tool calls";
  - the plans card as an MCP App, with the pick;
  - "Remember my spend cap is $250." and "Recheck", which move the pick to $240;
  - the confirmation and the result, with 30 units accounted for;
  - the alert after the console's stock change;
  - "execute it" refused.
- [x] The demo was reset after the take.

## After the take

- [x] 2:44, under 3:00. English narration and captions. Public on YouTube.
- [x] The first seconds say it is a simulated Alexa+ experience and name the self-hosted MCP
  server, Streamable HTTP and the spec version.
- [x] Loudness -16 LUFS integrated, true peak -1.5 dBTP.
- [x] Every caption and label inside the safe margins.
- [x] One frame every 5 s reviewed: no token, e-mail address, account id or browser chrome on
  screen.
- [x] No third-party music, footage or logo.
- [x] From the deadline (23 Oct, 12:00 PT) until the winners are announced (3 Dec), nothing in the
  video, the repositories or the materials changes.
