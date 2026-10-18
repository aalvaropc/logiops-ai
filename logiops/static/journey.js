(function (root) {
  const route = typeof module === "object" && module.exports ? require("./route.js") : root.LogiOpsRoute;
  const WIDE = { width: 360, height: 156 };
  const ENDS = { origin: { x: 34, y: 116 }, destination: { x: 326, y: 46 } };
  const NIGHT = { width: 360, lane: 32, top: 24, hub: 10, start: 86, end: 296 };
  const BENDS = [-34, 30, -62, 58];
  const HOUR = 3600000;

  function round(value) {
    return Math.round(value * 10) / 10;
  }

  const key = (name) => String(name || "").trim().toLowerCase();

  function at(points, t) {
    const [a, b, c, d] = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3];
    return { x: a * points[0].x + b * points[1].x + c * points[2].x + d * points[3].x, y: a * points[0].y + b * points[1].y + c * points[2].y + d * points[3].y };
  }

  function curve(from, to, bend = 0) {
    const reach = (to.x - from.x) * 0.4;
    const c1 = { x: round(from.x + reach), y: round(from.y + bend) };
    const c2 = { x: round(to.x - reach), y: round(to.y + bend) };
    const points = [from, c1, c2, to];
    const mid = at(points, 0.5);
    return { d: `M${from.x} ${from.y} C${c1.x} ${c1.y} ${c2.x} ${c2.y} ${to.x} ${to.y}`, points, mid: { x: round(mid.x), y: round(mid.y) } };
  }

  function labelSpot(leg, width) {
    if (!leg.points) return { x: leg.to.x + 16, y: leg.mid.y, anchor: "end" };
    const x = at(leg.points, 0.42).x;
    const samples = Array.from({ length: 41 }, (_, index) => at(leg.points, index / 40)).filter((point) => Math.abs(point.x - x) <= width / 2);
    const ys = samples.map((point) => point.y);
    return { x: round(x), y: round(leg.bend > 0 ? Math.max(...ys) + 19 : Math.min(...ys) - 9), anchor: "middle" };
  }

  function ring(place, radius = 12) {
    return {
      d: `M${place.x - radius} ${place.y} a${radius} ${radius} 0 1 0 ${radius * 2} 0 a${radius} ${radius} 0 1 0 ${-radius * 2} 0`,
      mid: { x: place.x, y: place.y + radius + 16 },
    };
  }

  function wideLayout(shipment, legs = []) {
    const origin = { name: route.placeName(shipment.origin), role: "origin", ...ENDS.origin };
    const destination = { name: route.placeName(shipment.destination), role: "destination", ...ENDS.destination };
    const sources = [];
    let travelling = 0;
    const placed = legs.map((leg) => {
      if (key(leg.from.name) === key(destination.name)) return { ...leg, loop: true, bend: 0, from: destination, to: destination, ...ring(destination) };
      let from = key(leg.from.name) === key(origin.name) ? origin : sources.find((place) => key(place.name) === key(leg.from.name));
      if (!from) {
        from = { name: leg.from.name, role: "source", x: origin.x, y: origin.y - 44 * (sources.length + 1) };
        sources.push(from);
      }
      const bend = BENDS[travelling % BENDS.length];
      travelling += 1;
      return { ...leg, loop: false, bend, from, to: destination, ...curve(from, destination, bend) };
    });
    return { view: WIDE, places: [origin, ...sources, destination], origin, destination, legs: placed, booked: curve(origin, destination, 0) };
  }

  function timeScale(times, from, to, lead = 0.3) {
    const values = times.map((time) => Date.parse(time)).filter(Number.isFinite);
    if (!values.length) return () => from;
    const first = Math.min(...values);
    const span = Math.max(Math.max(...values) - first, 6 * HOUR);
    const start = first - span * lead;
    const width = span * (1 + lead);
    return (time) => round(from + ((Date.parse(time) - start) / width) * (to - from));
  }

  function promiseTracks(shipment, rows = []) {
    const times = [shipment.original_eta, shipment.delayed_eta, ...rows.flatMap((row) => [row.due_eta, row.arrival_eta])].filter(Boolean);
    const at = timeScale(times, 0, 100);
    const track = (due, arrival) => {
      const promise = at(due);
      const end = arrival ? at(arrival) : null;
      return { promise, end, late: end !== null && end > promise };
    };
    return { shipment: track(shipment.original_eta, shipment.delayed_eta), rows: rows.map((row) => track(row.due_eta, row.arrival_eta)) };
  }

  function arrivalOf(item) {
    const due = Date.parse(item.due_eta);
    return Number.isFinite(due) ? new Date(due + (item.delay_hours || 0) * HOUR).toISOString() : null;
  }

  function queueTrails(items = [], view = NIGHT) {
    const lanes = items.map((item) => ({ item, done: item.status === "verified", arrival: arrivalOf(item) }));
    const at = timeScale(lanes.flatMap((lane) => [lane.item.due_eta, lane.arrival]).filter(Boolean), view.start, view.end, 0.35);
    const height = view.top * 2 + view.lane * Math.max(lanes.length - 1, 0);
    const hub = { x: view.hub, y: round(height / 2) };
    return {
      width: view.width, height, hub,
      lanes: lanes.map(({ item, done, arrival }, index) => {
        const y = view.top + index * view.lane;
        const promise = at(item.due_eta);
        const end = done || !arrival ? promise : at(arrival);
        const bend = round((view.start - hub.x) * 0.55);
        return {
          id: item.incident_id, y, promise, end, done, late: !done && end > promise,
          delay: item.delay_hours || 0, risk: done ? 0 : item.critical_units_at_risk || 0,
          lead: `M${hub.x} ${hub.y} C${hub.x + bend} ${hub.y} ${view.start - bend} ${y} ${view.start} ${y} L${promise} ${y}`,
          tail: `M${promise} ${y} L${end} ${y}`,
        };
      }),
    };
  }

  const api = { WIDE, NIGHT, curve, ring, labelSpot, wideLayout, timeScale, promiseTracks, queueTrails };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsJourney = api;
})(typeof window === "undefined" ? globalThis : window);
