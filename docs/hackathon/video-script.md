# Video script (under 3 minutes, English)

Recorded against the deployed demo in bedrock mode (a few cents); the device in one
tab, the operator console in another. Timings are targets; cut words before cutting
steps. Nothing on screen may show a token, an e-mail address or an account id.

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:15 | The device home card: the greeting and the inbox carousel. | "LogiOps AI is an operations desk you talk to. These are today's logistics exceptions: a delayed truck, a carrier that stopped departures, a customs hold, two orders competing for stock. Everything you'll see runs on a self-hosted MCP server, Amazon Bedrock and Strands Agents." |
| 0:15–0:30 | Say "Any delays today?" The carousel reorders; SHIP-433 gets "Start here". | "Ask for a briefing. The agent reads the inbox over MCP and tells me where to start: a carrier outage with a critical hospital order." |
| 0:30–0:55 | Tap SHIP-433. The incident card: the map, the ETAs. Say "What's happening with SHIP-433?" The orb thinks with its seconds; the plans card appears with the MCP App; the spoken line is read aloud by Polly. | "I open it and ask. The agent calls five tools — shipment, orders, stock, carrier quotes — and the plans are calculated by code, not by the model. This card is an MCP App served by the server itself. The pick protects the hospital order. And every answer is checked against the data before it's shown." |
| 0:55–1:15 | Say "approve the recommended plan". The confirmation card reads the plan back; press Yes. Then "execute it": the result card with its figures. | "Only I approve. It reads the plan back — price, delay, who's affected — and approves on my yes, bound to this exact data version. Execute: thirty units accounted for, verified, with the decision time measured from the events." |
| 1:15–1:35 | Say "book it". The purchase card with carriers, fee, tax and total; press Yes; the receipt card. | "Now the purchase. It reads the full price back with tax; one yes books and pays, charged once, with a receipt. A different amount or stale data is refused." |
| 1:35–1:55 | Press "More": the transcript with the Agent Skill and the tool trace, "Checked against the data". Switch to the console tab: the same incident, the audit trail, the session metrics strip. | "Behind the card: the Agent Skill the server publishes, the recorded tool trace, and the audit trail. The operator console shows the same incident in full, with the session's measured outcomes." |
| 1:55–2:15 | In the console's Developer drawer, change SHIP-421's stock; back on the device the bell shows an alert; open it: the "Heads up" card. | "Data changes. Stock moved under an investigated plan, and the agent raised a proactive alert with the new pick — nothing approved." |
| 2:15–2:35 | In the Developer drawer, import `scenario_pack.json`; the inbox shows SHIP-470; open it on the device. | "And it's not four fixed incidents: this is a scenario pack. Bring your own — a dock strike at Paita — and it runs through the same agent, tools and cards." |
| 2:35–2:50 | Reload the device in a new window: "Welcome back… we were on SHIP-433". | "Memory across sessions runs on AgentCore Memory, per signed-in user, and 'forget me' deletes it." |
| 2:50–3:00 | The README's first screen. | "Open source, MIT, with the MCP Apps host bridge as its own library. LogiOps AI." |

## Cuts, in order, if the take runs long

1. The memory reload (0:15).
2. The scenario pack import (0:20).
3. The console tab (keep "More").
