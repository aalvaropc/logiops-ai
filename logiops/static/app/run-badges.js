import { plural } from "./selectors.js";

export const CHECK_FAILED_NOTE = "This answer did not pass the automatic check against the incident's data. The plan cards are calculated by code; rely on them.";
export const BUDGET_NOTE = "Today's live model budget is used, so answers come from the scripted replay until midnight (UTC-05:00).";

export function checkBadge(run) {
  if (!run.evaluations?.length) return null;
  if (!run.grounded) {
    const issue = (run.evaluations[run.evaluations.length - 1].issues[0] || "").replace("(Lima time)", "(local time)");
    return { passed: false, text: `Did not pass the data check: ${issue}` };
  }
  return { passed: true, text: run.evaluations.length > 1 ? "Checked against the data after one revision" : "Checked against the data" };
}

export function checkNote(run) {
  return run.evaluations?.length && !run.grounded ? CHECK_FAILED_NOTE : null;
}

export function fallbackNote(run) {
  return run.fallback === "daily_budget" ? BUDGET_NOTE : null;
}

export function traceSummary(run) {
  const tokens = (run.usage?.inputTokens || 0) + (run.usage?.outputTokens || 0);
  const fallback = run.fallback === "daily_budget" ? " · daily live budget used" : "";
  return `${run.tool_trace.length} ${plural(run.tool_trace.length, "MCP call")} · ${run.mode} mode${fallback} · ${tokens} tokens${run.truncated ? " · truncated" : ""}`;
}

export function executionSummary(snapshot, execution) {
  const accounted = execution.accounted_units
    ?? snapshot.state.shipment.units_on_delayed_route + execution.fulfillments.reduce((sum, item) => sum + item.units, 0);
  return `Verified: ${accounted} units accounted for · $${execution.incremental_cost_usd} extra · ${execution.notifications.length} simulated notifications. Customer delay: ${execution.projected_customer_delay_hours}h (projected).`;
}
