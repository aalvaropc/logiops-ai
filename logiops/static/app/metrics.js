import { dollars } from "./purchase.js";

export function seconds(value) {
  if (value === null || value === undefined) return null;
  const whole = Math.round(value);
  return whole < 60 ? `${whole} s` : `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

export function sessionFigures(totals) {
  if (!totals.decided && !totals.executed && !totals.booked_usd) return [];
  return [
    [`${totals.executed} of ${totals.incidents}`, "incidents executed"],
    [String(totals.decided), "plans approved"],
    [`$${totals.extra_cost_usd}`, "extra cost committed"],
    [dollars(totals.booked_usd), "booked and paid"],
    [String(totals.late_units), "units late after execution"],
    [seconds(totals.median_time_to_decision_s) ?? "—", "median time to decision"],
  ];
}

export function incidentTimes(item) {
  if (!item) return [];
  return [["Decided in", seconds(item.time_to_decision_s)], ["Verified execution in", seconds(item.time_to_execution_s)]]
    .filter(([, value]) => value !== null);
}
