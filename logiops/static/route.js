(function (root) {
  const SHIPMENT_SOURCE = "delayed-shipment";
  const LEG_LABELS = {
    delayed: "Delayed shipment", local: "Local stock", ground: "Ground carrier",
    air: "Air freight", express: "Express", clearance: "Expedited clearance",
  };

  function legType(source) {
    if (source === SHIPMENT_SOURCE) return "delayed";
    if (/-stock$/.test(source)) return "local";
    if (/air/.test(source)) return "air";
    if (/clearance/.test(source)) return "clearance";
    if (/express/.test(source)) return "express";
    if (/reroute|ground/.test(source)) return "ground";
    return "unknown";
  }

  function placeName(name) {
    const text = String(name || "").trim();
    return text && text === text.toLowerCase() ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }

  function shortName(name, limit = 14) {
    const text = String(name || "");
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }

  function legsFor(state, plan) {
    if (!state || !plan) return [];
    const shipment = state.shipment;
    const dueBy = Object.fromEntries((state.orders || []).map((order) => [order.id, order.due_eta]));
    const legs = new Map();
    for (const item of plan.allocations || []) {
      const type = legType(item.source);
      const from = { name: placeName(type === "local" ? item.source.replace(/-stock$/, "") : shipment.origin) };
      const late = Date.parse(item.arrival_eta) > Date.parse(dueBy[item.order_id]);
      const leg = legs.get(item.source) || {
        source: item.source, type, label: LEG_LABELS[type] || item.source,
        from, to: { name: placeName(shipment.destination) }, units: 0, arrival_eta: item.arrival_eta, late: false, orders: [],
      };
      leg.units += item.units;
      leg.late = leg.late || late;
      if (Date.parse(item.arrival_eta) > Date.parse(leg.arrival_eta)) leg.arrival_eta = item.arrival_eta;
      if (!leg.orders.includes(item.order_id)) leg.orders.push(item.order_id);
      legs.set(item.source, leg);
    }
    return [...legs.values()];
  }

  function promiseBars(plan, scaleHours = 48) {
    const orders = (plan && plan.orders) || [];
    const longest = Math.max(scaleHours, ...orders.map((order) => order.delay_hours || 0));
    return orders.map((order) => ({
      order_id: order.order_id, customer: order.customer, priority: order.priority, quantity: order.quantity,
      due_eta: order.due_eta, arrival_eta: order.arrival_eta, delay_hours: order.delay_hours || 0,
      late_units: order.late_units || 0, on_time: !order.delay_hours,
      ratio: Math.min(1, (order.delay_hours || 0) / longest),
    }));
  }

  const VOICE_LABELS = { ready: "Ready", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…" };
  const VOICE_STEPS = {
    "listen-start": () => "listening",
    "listen-end": (current) => (current === "listening" ? "ready" : current),
    request: () => "thinking",
    reply: (_current, speaking) => (speaking ? "speaking" : "ready"),
    "speech-end": () => "ready",
    error: () => "ready",
  };

  function voiceState(current, event, speaking = false) {
    const step = VOICE_STEPS[event];
    const next = step ? step(current in VOICE_LABELS ? current : "ready", speaking) : current;
    return { state: next, label: VOICE_LABELS[next] || VOICE_LABELS.ready };
  }

  const api = { LEG_LABELS, VOICE_LABELS, legType, placeName, shortName, legsFor, promiseBars, voiceState };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsRoute = api;
})(typeof window === "undefined" ? globalThis : window);
