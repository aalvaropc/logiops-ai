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

export const TIME_ZONE = "America/Lima";
const DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE });

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

export function distinguishing(label, labels) {
  const words = String(label).split(" ");
  let best = null;
  for (const other of labels) {
    if (other === label) continue;
    const theirs = String(other).split(" ");
    const table = Array.from({ length: words.length + 1 }, () => new Array(theirs.length + 1).fill(0));
    for (let i = words.length - 1; i >= 0; i -= 1) {
      for (let j = theirs.length - 1; j >= 0; j -= 1) {
        table[i][j] = words[i] === theirs[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
      }
    }
    if (!best || table[0][0] > best.table[0][0]) best = { table, theirs };
  }
  const common = best ? best.table[0][0] : 0;
  if (common < 2 || common * 2 < words.length || common === words.length) return [[String(label), false]];
  const shared = new Array(words.length).fill(false);
  for (let i = 0, j = 0; i < words.length && j < best.theirs.length;) {
    if (words[i] === best.theirs[j]) {
      shared[i] = true;
      i += 1;
      j += 1;
    } else if (best.table[i + 1][j] >= best.table[i][j + 1]) {
      i += 1;
    } else {
      j += 1;
    }
  }
  const segments = [];
  words.forEach((word, index) => {
    const last = segments[segments.length - 1];
    if (last && last[1] === !shared[index]) last[0] += ` ${word}`;
    else segments.push([word, !shared[index]]);
  });
  return segments;
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
