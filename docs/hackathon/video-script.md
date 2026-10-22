# Demo video

Published: <https://youtu.be/h30PVrBO8d0> (2:44, English narration and captions).

A pitch, not a tutorial: the problem, the product working live, why it is safe, and that it runs on
a real MCP server. The first seconds say plainly that the Alexa+ experience is simulated and name
the track's technology. The line to land is said once, at the end: **"The agent proposes. You
approve. Code enforces it."**

How it was made, on 2026-10-22:

- **The footage is one live take of the deployed demo** in bedrock mode (two agent runs on Amazon
  Bedrock), recorded headless with Playwright at 1344x756 and twice the pixel density. Nothing in a
  live agent run is cut or sped up, so the stations show their real timings. The demo was reset
  before and after the take. SHIP-421 was approved off camera beforehand, so the stock change has
  an approval to invalidate.
- **The terminal shows the real output of the commands on screen**, run as a guest against the
  deployed `/mcp`. The Claude shot is a screenshot of Claude with LogiOps AI added as a custom
  connector (21 Oct).
- **Animated parts:** the opening, the architecture and the close are pixel art drawn in code in
  the product's six colours.
- **Sound and fonts:**
  - narration by Amazon Polly (generative voice Matthew; the device's own voice is Ruth);
  - music and effects synthesized in code;
  - fonts Overpass, Silkscreen and Press Start 2P, all under the SIL Open Font License.

  There is no third-party music, footage or logo.

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:10 | Animation: a truck stops on a map of an invented region, "SHIP-433 · 12 critical units at risk", and Transport, Orders and Inventory as three windows that do not connect. | "Four late shipments this morning. One puts a hospital order at risk, and the answer is split across three systems." |
| 0:10–0:24 | The device at home, 12 critical units at risk, and its "Alexa+ simulated" label. Caption: "Simulated Alexa+ experience · self-hosted MCP server · Streamable HTTP · MCP 2025-11-25". | "LogiOps AI is an operations desk you talk to: a simulated Alexa+ experience, since the Alexa+ developer tools are partner-only, over a real self-hosted MCP server, with the agent on Amazon Bedrock." |
| 0:24–0:50 | "What's happening with SHIP-433, and which plan should we choose?" Each MCP call lights a station as it returns, then "Checked against the data"; the plans card, an MCP App, with the $390 pick. | "I ask about SHIP-433. Each station is a real tool call as it returns: shipment, orders, carrier quotes, plans. Code calculates the plans, the model compares them, and the answer is checked against the data before I see it. The pick keeps the hospital on time for $390." |
| 0:50–1:18 | "Remember my spend cap is $250.", then "Recheck": the same plans, and the $240 plan picked with "Your preference". | "I tell it my spend cap once, and it keeps it across sessions. Recheck: the same plans, a different pick. A preference never approves anything. $240, and it says what that costs: the store order waits a day." |
| 1:18–1:34 | "approve the recommended plan", the confirmation with $240 in large type, Yes; "execute it": 30 units accounted for, 12 critical units on time. | "Only I approve. It reads the plan back, and my yes is bound to this exact plan and this version of the data. Execute: 30 units accounted for, and the time to decision measured, not claimed." |
| 1:34–1:53 | The console sets SHIP-421's stock to 11. On the device, the bell, then "Heads up on SHIP-421": the approved $120 plan, now $80 and 3 h late. "execute it" is refused. | "Then the world changes. Stock moves under a plan I already approved. The approval no longer applies, the agent raises an alert with a new pick, and execute is refused until I decide again." |
| 1:53–2:14 | MCP Inspector CLI lists the 12 tools; a guest call to `execute_approved_plan` is refused, and curl shows the `401` with its OAuth challenge. Then Claude renders the plans card as an MCP App. | "And it's a real MCP server: Streamable HTTP, spec 2025-11-25, OAuth 2.1 with Amazon Cognito. A standard client lists 12 tools, a guest gets a 401 on execute, and Claude, added as a connector, renders the same plans card as an MCP App." |
| 2:14–2:32 | Animation: the device, the MCP server, plans in code, the agent, AgentCore Memory and Polly, and the approval lock before Execute. | "Under the hood: Strands Agents with Claude on Amazon Bedrock, AgentCore Memory and Amazon Polly. It's open source under MIT, with my MCP Apps host library on npm and a free replay mode, so anyone can run it." |
| 2:32–2:44 | The close: "LogiOps AI" and the line. | "LogiOps AI. The agent proposes. You approve. Code enforces it." |
