(function (root) {
  const VIEW = { width: 240, height: 300 };
  const BOUNDS = { west: -81.6, east: -68.4, north: 0.2, south: -18.6 };

  function project(lat, lon) {
    const x = 10 + ((lon - BOUNDS.west) / (BOUNDS.east - BOUNDS.west)) * (VIEW.width - 20);
    const y = 10 + ((BOUNDS.north - lat) / (BOUNDS.north - BOUNDS.south)) * (VIEW.height - 20);
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
  }

  const CITIES = Object.fromEntries([
    ["Lima", -12.05, -77.04],
    ["Callao", -12.06, -77.15],
    ["Arequipa", -16.41, -71.54],
    ["Cusco", -13.53, -71.97],
    ["Trujillo", -8.11, -79.03],
  ].map(([name, lat, lon]) => [name, { name, lat, lon, ...project(lat, lon) }]));

  const OUTLINE = [
    [-3.4, -80.3], [-4.3, -81.3], [-5.1, -81.1], [-6.8, -79.9], [-8.1, -79.0], [-9.1, -78.6], [-11.1, -77.6],
    [-12.1, -77.2], [-13.7, -76.2], [-15.4, -75.1], [-16.6, -72.7], [-17.6, -71.3], [-18.3, -70.4],
    [-17.3, -69.5], [-16.2, -68.9], [-14.2, -68.9], [-12.5, -68.7], [-11.0, -69.6], [-10.0, -71.4],
    [-9.4, -72.7], [-7.5, -73.9], [-5.2, -73.1], [-4.2, -70.0], [-2.4, -71.0], [-0.1, -75.2],
    [-1.5, -76.7], [-2.6, -78.2], [-3.4, -80.3],
  ].map(([lat, lon]) => project(lat, lon));

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

  function cityOf(name) {
    const key = String(name || "").toLowerCase();
    return Object.values(CITIES).find((city) => city.name.toLowerCase() === key) || null;
  }

  function legsFor(state, plan) {
    if (!state || !plan) return [];
    const shipment = state.shipment;
    const dueBy = Object.fromEntries((state.orders || []).map((order) => [order.id, order.due_eta]));
    const legs = new Map();
    for (const item of plan.allocations || []) {
      const type = legType(item.source);
      const from = type === "local" ? cityOf(item.source.replace(/-stock$/, "")) : cityOf(shipment.origin);
      const late = Date.parse(item.arrival_eta) > Date.parse(dueBy[item.order_id]);
      const leg = legs.get(item.source) || {
        source: item.source, type, label: LEG_LABELS[type] || item.source,
        from, to: cityOf(shipment.destination), units: 0, arrival_eta: item.arrival_eta, late: false, orders: [],
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

  function linePath(points) {
    return points.map((point, index) => `${index ? "L" : "M"}${point.x} ${point.y}`).join(" ") + " Z";
  }

  function arc(from, to, lift = 0.25) {
    if (!from || !to) return "";
    const midX = (from.x + to.x) / 2;
    const midY = (from.y + to.y) / 2;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    return `M${from.x} ${from.y} Q${Math.round((midX - dy * lift) * 10) / 10} ${Math.round((midY + dx * lift) * 10) / 10} ${to.x} ${to.y}`;
  }

  const api = { VIEW, CITIES, OUTLINE, LEG_LABELS, VOICE_LABELS, project, legType, cityOf, legsFor, promiseBars, voiceState, linePath, arc };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsRoute = api;
})(typeof window === "undefined" ? globalThis : window);
