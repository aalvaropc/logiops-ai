(function (root) {
  const NARROW = { width: 360, height: 168, pad: { left: 18, right: 22, top: 30, bottom: 30 } };
  const WIDE = { width: 440, height: 190, pad: { left: 18, right: 26, top: 32, bottom: 32 } };
  const TWIN_OFFSET = 12;
  const TICK_GAP = 40;

  function round(value) {
    return Math.round(value * 10) / 10;
  }

  function standing(plan) {
    const orders = plan.orders || [];
    if (orders.some((order) => order.priority === "critical" && order.delay_hours)) return "critical-late";
    return (plan.late_units || 0) > 0 || orders.some((order) => order.delay_hours) ? "late" : "on-time";
  }

  function decisionField(plans = [], pickId = null, view = NARROW) {
    const { width, height, pad } = view;
    const maxCost = Math.max(1, ...plans.map((plan) => plan.incremental_cost_usd || 0));
    const maxDelay = Math.max(1, ...plans.map((plan) => plan.projected_customer_delay_hours || 0));
    const left = pad.left;
    const right = width - pad.right;
    const top = pad.top;
    const bottom = height - pad.bottom;
    const key = (plan) => `${plan.incremental_cost_usd || 0}:${plan.projected_customer_delay_hours || 0}`;
    const ordered = [...plans].sort((a, b) => Number(b.id === pickId) - Number(a.id === pickId));
    const seen = new Map();
    const points = ordered.map((plan) => {
      const cost = plan.incremental_cost_usd || 0;
      const delay = plan.projected_customer_delay_hours || 0;
      const twin = seen.get(key(plan)) || 0;
      seen.set(key(plan), twin + 1);
      const base = left + (delay / maxDelay) * (right - left);
      const shift = twin * TWIN_OFFSET;
      return {
        id: plan.id, cost, delay, pick: plan.id === pickId, standing: standing(plan), labelled: twin === 0,
        x: round(base + shift > right ? base - shift : base + shift),
        y: round(bottom - (cost / maxCost) * (bottom - top)),
      };
    });
    const ticks = [];
    for (const delay of [...new Set(plans.map((plan) => plan.projected_customer_delay_hours || 0))].sort((a, b) => a - b)) {
      const x = round(left + (delay / maxDelay) * (right - left));
      if (ticks.length && x - ticks[ticks.length - 1].x < TICK_GAP) ticks.pop();
      ticks.push({ delay, x });
    }
    return {
      view: { width, height }, points: [...points.filter((point) => !point.pick), ...points.filter((point) => point.pick)],
      axes: { left, right, top, bottom, maxCost, maxDelay, ticks },
    };
  }

  const api = { NARROW, WIDE, standing, decisionField };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsField = api;
})(typeof window === "undefined" ? globalThis : window);
