export const RULE_NAMES = { balanced: "balanced ranking", cheapest_unless_critical_late: "cheapest unless a critical order is late" };

export function describePreferences(prefs) {
  const parts = [RULE_NAMES[prefs.rule] || prefs.rule];
  parts.push(prefs.max_cost_usd === null || prefs.max_cost_usd === undefined ? "no spend cap" : `spend cap $${prefs.max_cost_usd}`);
  if (prefs.note) parts.push(`note “${prefs.note}”`);
  return parts.join(" · ");
}

export function mergedPreferences(current, update) {
  const base = current || {};
  return { rule: base.rule || "balanced", max_cost_usd: base.max_cost_usd ?? null, note: base.note || "", ...update };
}

export function preferenceLine(preference) {
  if (!preference) return null;
  return {
    lead: `Your preference → “${preference.preferred_plan_label}”. `,
    text: [preference.changes_pick ? preference.reason : "It agrees with the default pick.", ...preference.warnings].join(" "),
  };
}

export function preferenceEffect(snapshot, incidentId) {
  const preference = snapshot?.preference;
  if (!preference) return `I'll apply them to ${incidentId} once its plans are calculated.`;
  if (!preference.changes_pick) return `For ${incidentId}, they agree with the default pick, “${preference.default_plan_label}”.`;
  return `For ${incidentId}, they point to “${preference.preferred_plan_label}” instead of the default pick, `
    + `“${preference.default_plan_label}”. ${preference.reason} ${preference.warnings.join(" ")}`.trim();
}
