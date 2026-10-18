import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { welcomeText } = await import(moduleUrl("app/greeting.js"));

test("the greeting names the open queue, its critical orders and the units at risk", () => {
  assert.equal(welcomeText({ inbox: [], incidentId: "SHIP-421" }),
    "Hi, I'm LogiOps. Ask me what's happening with SHIP-421, and I'll investigate it with the MCP tools.");
  assert.equal(welcomeText({ inbox: [], incidentId: null }), "Hi, I'm LogiOps. Ask “any delays today?” for my briefing.");
  const inbox = [
    { incident_id: "SHIP-433", status: "detected", priority: "critical", critical_units_at_risk: 12 },
    { incident_id: "SHIP-421", status: "detected", priority: "standard", critical_units_at_risk: 0 },
    { incident_id: "SHIP-452", status: "verified", priority: "critical", critical_units_at_risk: 0 },
  ];
  assert.equal(welcomeText({ inbox, incidentId: "SHIP-421" }),
    "Hi, I'm LogiOps. 2 open incidents in the inbox; SHIP-433 has a critical order, and SHIP-433 has 12 critical units nothing on hand delivers in time. "
    + "Ask “any delays today?” for my briefing, or ask what's happening with SHIP-421.");
  assert.match(welcomeText({ inbox: inbox.map((item) => ({ ...item, status: "verified" })), incidentId: "SHIP-421" }), /Every incident in the inbox is resolved/);
});
