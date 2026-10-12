import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { describePreferences, mergedPreferences, preferenceLine, preferenceEffect } = await import(moduleUrl("app/preferences.js"));

test("preferences are described and merged the way the page saves them", () => {
  assert.equal(describePreferences({ rule: "balanced", max_cost_usd: null, note: "" }), "balanced ranking · no spend cap");
  assert.equal(describePreferences({ rule: "cheapest_unless_critical_late", max_cost_usd: 250, note: "Hospitals first" }),
    "cheapest unless a critical order is late · spend cap $250 · note “Hospitals first”");
  assert.deepEqual(mergedPreferences(null, { max_cost_usd: 250 }), { rule: "balanced", max_cost_usd: 250, note: "" });
  assert.deepEqual(mergedPreferences({ rule: "cheapest_unless_critical_late", max_cost_usd: 100, note: "n" }, { max_cost_usd: null }),
    { rule: "cheapest_unless_critical_late", max_cost_usd: null, note: "n" });
});

test("the preference line and its effect name plans by label", () => {
  const preference = { preferred_plan_label: "Fly the hospital order", default_plan_label: "Rebook on ground", changes_pick: true, reason: "The $250 cap rules out the default.", warnings: ["The store order is 24 h late."] };
  assert.deepEqual(preferenceLine(preference), { lead: "Your preference → “Fly the hospital order”. ", text: "The $250 cap rules out the default. The store order is 24 h late." });
  assert.equal(preferenceLine(null), null);
  assert.equal(preferenceLine({ ...preference, changes_pick: false, warnings: [] }).text, "It agrees with the default pick.");
  assert.equal(preferenceEffect(null, "SHIP-433"), "I'll apply them to SHIP-433 once its plans are calculated.");
  assert.equal(preferenceEffect({ preference: { ...preference, changes_pick: false } }, "SHIP-433"), "For SHIP-433, they agree with the default pick, “Rebook on ground”.");
  assert.equal(preferenceEffect({ preference }, "SHIP-433"),
    "For SHIP-433, they point to “Fly the hospital order” instead of the default pick, “Rebook on ground”. The $250 cap rules out the default. The store order is 24 h late.");
});
