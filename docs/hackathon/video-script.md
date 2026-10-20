# Video script (under 3 minutes, English)

Recorded against the deployed demo in bedrock mode (a few cents); the device in one
tab, the operator console in a second tab for one step, and MCP Inspector in a
third. Timings are targets; cut words before cutting steps. Nothing on screen may
show a token, an e-mail address or an account id.

Three acts, one per judging criterion: the idea (a decision, not a chat), the
safety (the data changes and the system notices), and the fit (a real MCP server
any client can drive). The line to land is said once, at the end: **"The agent
proposes. You approve. Code enforces it."**

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:12 | The device home: "12 critical units at risk" in red, the four incidents as light lanes trailing their delay. | "Four late shipments this morning. One of them carries a hospital order. LogiOps AI is an operations desk you talk to: an Alexa+-style device over a self-hosted MCP server, with the agent on Amazon Bedrock." |
| 0:12–0:28 | Say "Any delays today?" The lanes stay, SHIP-433 gets "Start here", Polly reads the short line. | "I ask for the day. The agent reads the inbox over MCP and says where to start: the carrier outage with the critical order. A briefing only reads; it cannot change anything." |
| 0:28–0:55 | Tap SHIP-433: the booked route dashed red, "12 critical units at risk". Say "What's happening with SHIP-433, and which plan should we choose?" The agent stage lights each MCP call as it returns, then "Checked against the data". The plans appear with the decision field; the pick is the lit dot. | "Each station is a tool call as it happens: shipment, orders, carrier quotes, plans. The plans are calculated by code; the model compares them and explains. And before anything is shown, the answer is checked against the incident's data. The pick keeps the hospital on time for $390." |
| 0:55–1:15 | Type "Remember my spend cap is $250." Ask "Which plan now?" The pick moves to the $240 plan with "Your preference"; the spoken line names what it trades away. | "This is where state matters. I tell it my spend cap once, and it keeps it across sessions. The same calculated plans, a different pick: $240, and the agent says what that costs the store. A preference never approves anything." |
| 1:15–1:35 | Say "approve the recommended plan". The confirmation: "$240" large, each order's trail to its promise, Yes / No. Press Yes. Say "execute it". The result: the route redrawn, "12 critical units on time", "Decided in 11 s". | "Only I approve. It reads the plan back, and my yes is bound to this exact plan and this version of the data. Execute: thirty units accounted for, verified, and the time to decision measured from the events, not claimed." |
| 1:35–2:05 | Console tab, Developer drawer: on SHIP-421 (investigated and approved before the take), set stock to 11, Apply. Back on the device: the bell, the "Heads up" alert with the previous plan dashed and the new one lit. Say "execute it": refused. | "Act two: the world changes. Stock moves under an approved plan. The approval no longer applies, the agent raises an alert with the new pick, and execute is refused until a person decides again. That is the whole point: the agent proposes, code enforces." |
| 2:05–2:30 | MCP Inspector tab, already connected to the deployed server over HTTPS. Show the tool list (12 tools), call `get_shipment` for SHIP-433, then call `execute_approved_plan` as a guest: 401 with the OAuth challenge, and the Cognito sign-in. | "Act three: this is a real MCP server. Here it is in MCP Inspector, a standard client, over the same URL: Streamable HTTP, OAuth 2.1 with Amazon Cognito, and the write tools refuse a guest. Connecting the real Alexa+ is a registration step, not a rewrite." |
| 2:30–2:45 | Press "More" on the device: the Agent Skill and the tool trace of each reply. Cut to the README's first screen with the gallery. | "Open source, MIT, with the MCP Apps host bridge as its own library. Four hundred tests, replay mode so judges can run it for free, and every step in the audit trail." |
| 2:45–2:55 | End card: the repo URL and the line. | "LogiOps AI. The agent proposes. You approve. Code enforces it." |

## Cuts, in order, if the take runs long

1. The "More" sheet (0:10).
2. The guest 401 in Inspector (0:08): keep the tool list and one call.
3. The briefing (0:16): open SHIP-433 directly.

## Before the take

- Reset all incidents and preferences; then investigate and approve SHIP-421 (the
  alert needs an approved plan to invalidate), and open SHIP-433 last.
- Chrome or Edge for the microphone; if speech fails, type the line: the flow is the
  same. Turn on "Read replies aloud" so Polly is heard.
- MCP Inspector (`npx @modelcontextprotocol/inspector`) connected to
  `https://…/mcp` with the bearer token pasted in its Authentication panel, never
  shown; open the tool list before recording. The guest step is a second
  connection without the token; "Sign in" there opens Cognito with the demo
  user (type the password off camera, or cut to the signed-in state).
- Narration at about 150 words per minute; the text above is about 380 words.
