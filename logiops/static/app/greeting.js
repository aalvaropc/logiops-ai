export function welcomeText({ inbox = [], incidentId } = {}) {
  const open = inbox.filter((item) => item.status !== "verified");
  if (!inbox.length) {
    return incidentId ? `Hi, I'm LogiOps. Ask me what's happening with ${incidentId}, and I'll investigate it with the MCP tools.`
      : "Hi, I'm LogiOps. Ask “any delays today?” for my briefing.";
  }
  const critical = open.filter((item) => item.priority === "critical").map((item) => item.incident_id);
  const atRisk = open.filter((item) => item.critical_units_at_risk > 0)
    .map((item) => `${item.incident_id} has ${item.critical_units_at_risk} critical units nothing on hand delivers in time`);
  const queue = open.length
    ? `${open.length} open incident${open.length === 1 ? "" : "s"} in the inbox`
      + (critical.length ? `; ${critical.join(" and ")} ${critical.length === 1 ? "has a critical order" : "have critical orders"}` : "")
      + (atRisk.length ? `, and ${atRisk.join(" and ")}` : "")
    : "Every incident in the inbox is resolved";
  return `Hi, I'm LogiOps. ${queue}. Ask “any delays today?” for my briefing, or ask what's happening with ${incidentId}.`;
}

export const HOME_LINE = "Hi, I'm LogiOps. Ask “any delays today?” for my briefing.";

export function homeHeading(inbox = []) {
  const open = inbox.filter((item) => item.status !== "verified").length;
  if (!inbox.length) return "No incidents in the inbox";
  return open ? `${open} open incident${open === 1 ? "" : "s"}` : "Every incident is resolved";
}
