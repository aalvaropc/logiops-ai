export const EVENT_LABELS = {
  scenario_reset: "Synthetic incident reset",
  incident_investigated: "MCP investigation completed",
  agent_investigation_completed: "Agent assessment recorded",
  plan_approved: "Plan approved by operator",
  plan_executed: "Fulfillment plan executed",
  notifications_simulated: "Notifications simulated",
  execution_verified: "All units accounted for",
  inventory_changed: "Local inventory changed",
  schema_migrated: "Data rebuilt for a new version",
};

export const PLAN_KEYWORDS = [
  [["express-transfer"], /\btransfer\b/],
  [["priority-air-ground"], /\b(air|fly|flight)\b.*\bground\b|\bground\b.*\b(air|fly|flight)\b/],
  [["priority-air"], /\b(air|fly|flight)\b/],
  [["split-expedite"], /\b(split|stock)\b.*\bexpedit|\bexpedit\w*\b.*\b(split|stock)\b/],
  [["expedite", "split-expedite"], /\bexpedit\w*\b|\bbroker\b/],
  [["first-come"], /\b(first[- ]come|as placed|school first)\b/],
  [["priority-first"], /\b(hospital first|priority first)\b/],
  [["split-express", "split-expedite", "split-wait"], /\bsplit\b/],
  [["split-express"], /\bexpress\b/],
  [["local-stock"], /\b(local|warehouse)\b/],
  [["reroute"], /\b(reroute|re-route|economy|rebook)\b/],
  [["wait"], /\bwait\b/],
];

const DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "America/Lima" });

export function formatDate(iso) {
  return DATE.format(new Date(iso));
}

export function visibleVersion(snapshot) {
  return snapshot.executions[0]?.source_version ?? snapshot.source_version;
}

export function visibleApproval(snapshot) {
  return snapshot.approvals.find((approval) => approval.source_version === visibleVersion(snapshot));
}

export function visiblePlans(snapshot) {
  return snapshot.plans.filter((plan) => plan.source_version === visibleVersion(snapshot));
}

export function latestAgentEvent(snapshot) {
  return [...snapshot.events].reverse().find((event) =>
    event.name === "agent_investigation_completed" && event.data.source_version === visibleVersion(snapshot));
}

export function rankKey(plan) {
  const critical = (plan.orders || []).filter((order) => order.priority === "critical").map((order) => order.delay_hours);
  return [Math.max(0, ...critical), plan.projected_customer_delay_hours, plan.late_units || 0, plan.incremental_cost_usd];
}

export function byRank(a, b) {
  const left = rankKey(a), right = rankKey(b);
  return left.reduce((found, value, index) => found || value - right[index], 0);
}

export function recommendedPlan(snapshot, intent) {
  const plans = visiblePlans(snapshot);
  if (!plans.length) return null;
  const answer = latestAgentEvent(snapshot)?.data.answer || "";
  const id = intent.recommendedPlanId(answer, plans);
  return plans.find((plan) => plan.id === id)
    || plans.find((plan) => answer.toLowerCase().includes(`recommend ${plan.label.toLowerCase()}`))
    || [...plans].sort(byRank)[0];
}

export function allocationSummary(plan) {
  const units = new Map();
  for (const item of plan.allocations) units.set(item.source, (units.get(item.source) || 0) + item.units);
  return [...units].map(([source, count]) => `${count} via ${source.replaceAll("-", " ")}`).join(" · ");
}

export function localWarehouse(snapshot) {
  return Object.keys(snapshot.state.inventory || {})[0] || null;
}

export function namedPlanKinds(text) {
  const found = PLAN_KEYWORDS.find(([, pattern]) => pattern.test(text));
  return found ? found[0] : null;
}

export function planFromUtterance(text, snapshot, intent) {
  const plans = visiblePlans(snapshot);
  const preferred = snapshot.preference && plans.find((plan) => plan.id === snapshot.preference.preferred_plan_id);
  if (preferred && /\b(?:preferred|my preference)\b/.test(text)) return preferred;
  const selector = intent.planSelector(text);
  if (selector.cheapest) {
    return [...plans].sort((a, b) => a.incremental_cost_usd - b.incremental_cost_usd || byRank(a, b))[0] || null;
  }
  if (selector.cost !== undefined) {
    const priced = plans.filter((plan) => plan.incremental_cost_usd === selector.cost);
    return priced.length === 1 ? priced[0] : null;
  }
  const kinds = namedPlanKinds(text);
  if (kinds) return kinds.map((kind) => plans.find((plan) => plan.kind === kind)).find(Boolean) || null;
  return recommendedPlan(snapshot, intent);
}
