import { money, plural } from "./selectors.js";

export const CHECK_FAILED_NOTE = "This answer did not pass the automatic check against the incident's data. The plan cards are calculated by code; rely on them.";
export const BUDGET_NOTE = "Today's live model budget is used, so answers come from the scripted replay until midnight (UTC-05:00).";
export const MODEL_NOTE = "The live model is unavailable right now, so this answer comes from the scripted replay.";
export const GUEST_NOTE = "You're a guest, so answers come from the scripted replay. Press Link account to use the live agent on Amazon Bedrock.";
export const GUEST_BUDGET_NOTE = "The live answers open to guests today are used, so answers come from the scripted replay. Press Link account to use the live agent on Amazon Bedrock.";
const FALLBACK_NOTES = { daily_budget: BUDGET_NOTE, model_unavailable: MODEL_NOTE, sign_in: GUEST_NOTE, guest_budget: GUEST_BUDGET_NOTE };
const FALLBACK_SUMMARIES = {
  daily_budget: " · daily live budget used", model_unavailable: " · live model unavailable", sign_in: " · guest on the replay", guest_budget: " · guest share used",
};

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
  return FALLBACK_NOTES[run.fallback] ?? null;
}

export function traceSummary(run) {
  const tokens = (run.usage?.inputTokens || 0) + (run.usage?.outputTokens || 0);
  const fallback = FALLBACK_SUMMARIES[run.fallback] ?? "";
  return `${run.tool_trace.length} ${plural(run.tool_trace.length, "MCP call")} · ${run.mode} mode${fallback} · ${tokens} tokens${run.truncated ? " · truncated" : ""}`;
}

export function executionSummary(snapshot, execution) {
  const accounted = execution.accounted_units
    ?? snapshot.state.shipment.units_on_delayed_route + execution.fulfillments.reduce((sum, item) => sum + item.units, 0);
  return `Verified: ${accounted} units accounted for · ${money(execution.incremental_cost_usd)} extra · ${execution.notifications.length} simulated notifications. Customer delay: ${execution.projected_customer_delay_hours}h (projected).`;
}
