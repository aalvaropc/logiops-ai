import { dollars } from "./purchase.js";
import { plural } from "./selectors.js";

export function seconds(value) {
  if (value === null || value === undefined) return null;
  const whole = Math.round(value);
  if (whole < 60) return `${whole} s`;
  if (whole < 3600) return `${Math.floor(whole / 60)} min ${whole % 60} s`;
  return `${Math.floor(whole / 3600)} h ${Math.floor((whole % 3600) / 60)} min`;
}

export const EMPTY_SESSION = "No plan approved yet this session. Outcomes appear here as you decide.";

export function sessionFigures(totals) {
  if (!totals.decided && !totals.executed && !totals.booked_usd) return [];
  return [
    [`${totals.executed} of ${totals.incidents}`, plural(totals.incidents, "incident executed", "incidents executed")],
    [String(totals.decided), plural(totals.decided, "plan approved", "plans approved")],
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
