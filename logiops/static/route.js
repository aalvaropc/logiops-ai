(function (root) {
  const VIEW = { width: 240, height: 210 };
  const ROW = { top: 54, bottom: VIEW.height - 54 };

  function round(value) {
    return Math.round(value * 10) / 10;
  }

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

  function layout(shipment, legs) {
    const key = (name) => String(name).toLowerCase();
    const destinationName = placeName(shipment.destination);
    const originName = placeName(shipment.origin);
    const names = [];
    for (const name of [originName, ...legs.map((leg) => leg.from.name)]) {
      if (name && key(name) !== key(destinationName) && !names.some((known) => key(known) === key(name))) names.push(name);
    }
    const step = names.length > 1 ? (VIEW.width - 88) / (names.length - 1) : 0;
    const places = names.map((name, index) => ({
      name, role: key(name) === key(originName) ? "origin" : "source",
      x: round(names.length > 1 ? 44 + index * step : VIEW.width / 2), y: ROW.top,
    }));
    const destination = { name: destinationName, role: "destination", x: VIEW.width / 2, y: ROW.bottom };
    const find = (name) => places.find((place) => key(place.name) === key(name)) || destination;
    return {
      places, destination,
      legs: legs.map((leg) => ({ ...leg, from: find(leg.from.name), to: destination, loop: key(leg.from.name) === key(destinationName) })),
    };
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

  function arc(from, to, lift = 0.25) {
    if (!from || !to) return "";
    const midX = (from.x + to.x) / 2;
    const midY = (from.y + to.y) / 2;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    return `M${from.x} ${from.y} Q${Math.round((midX - dy * lift) * 10) / 10} ${Math.round((midY + dx * lift) * 10) / 10} ${to.x} ${to.y}`;
  }

  const api = { VIEW, LEG_LABELS, VOICE_LABELS, legType, placeName, shortName, legsFor, layout, promiseBars, voiceState, arc };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsRoute = api;
})(typeof window === "undefined" ? globalThis : window);
