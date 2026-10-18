import { dollars, bookingRows } from "../app/purchase.js";
import { formatDate, allocationSummary, distinguishing, TIME_ZONE } from "../app/selectors.js";
import { incidentFacts, incidentBand, confirmDetails, resultFigures, resultOutcome, orderRows, alertDetails } from "./surfaces.js";
import { EMPTY_SESSION } from "../app/metrics.js";

const SVG = "http://www.w3.org/2000/svg";
const WHEN = new Intl.DateTimeFormat("en-US", { timeZone: TIME_ZONE, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const STEP_NAMES = {
  get_shipment: "Shipment", get_order: "Order", get_inventory: "Stock", find_alternative_carriers: "Carrier quotes",
  investigate_incident: "Plans calculated", get_execution_status: "Execution status", list_incidents: "Inbox",
};

export function el(tag, className, text, doc = globalThis.document) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attributes, text, doc = globalThis.document) {
  const node = doc.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes || {})) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

export function labelNodes(label, labels, doc = globalThis.document) {
  return distinguishing(label, labels).flatMap(([text, marked], index) => {
    const space = index ? " " : "";
    return marked ? [space, el("span", "diff", text, doc)] : [`${space}${text}`];
  }).filter(Boolean);
}

function when(iso) {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? "—" : WHEN.format(new Date(time));
}

function rowList(rows, doc = globalThis.document) {
  const list = el("dl", "rows", undefined, doc);
  for (const [term, value, kind] of rows) {
    const chip = kind && kind !== "line";
    const line = kind === "line" ? "line" : "";
    const cell = el("dd", line, chip ? undefined : value, doc);
    if (chip) cell.append(el("span", `outcome ${kind}`, value, doc));
    list.append(el("dt", line, term, doc), cell);
  }
  return list;
}

function columns(main, side, doc = globalThis.document) {
  const split = el("div", "label-split", undefined, doc);
  const left = el("div", "label-main", undefined, doc);
  const right = el("div", "label-side", undefined, doc);
  left.append(...main.filter(Boolean));
  right.append(...side.filter(Boolean));
  split.append(left, right);
  return split;
}

function button(text, className, onClick, doc = globalThis.document) {
  const node = el("button", className, text, doc);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

export function renderHome(section, { heading, session, inbox = [], journey }, doc = globalThis.document) {
  section.querySelector(".home-head")?.remove();
  const head = el("div", "home-head", undefined, doc);
  const title = el("h2", "", heading, doc);
  title.id = "home-title";
  head.append(title);
  if (inbox.length && journey) head.append(nightFigure(inbox, doc), nightLanes(section, inbox, journey, doc));
  section.prepend(head);
  renderSession(section, session, doc);
}

function nightFigure(inbox, doc) {
  const risk = inbox.filter((item) => item.status !== "verified").reduce((sum, item) => sum + (item.critical_units_at_risk || 0), 0);
  const figure = el("p", `night-figure${risk ? " late" : ""}`, undefined, doc);
  const words = el("span", "", "critical units", doc);
  words.append(el("br", "", undefined, doc), "at risk");
  figure.append(el("strong", "", String(risk), doc), " ", words);
  return figure;
}

function glow(id, doc) {
  const defs = svg("defs", {}, undefined, doc);
  const filter = svg("filter", { id, x: "-10%", y: "-60%", width: "120%", height: "220%" }, undefined, doc);
  filter.append(svg("feGaussianBlur", { stdDeviation: 2.6 }, undefined, doc));
  defs.append(filter);
  return defs;
}

function settle(holder, figure, key) {
  figure.classList.toggle("settled", holder.dataset.drawn === key);
  holder.dataset.drawn = key;
}

function nightLanes(section, inbox, journey, doc) {
  const night = journey.queueTrails(inbox);
  const figure = el("figure", "night", undefined, doc);
  settle(section, figure, night.lanes.map((lane) => `${lane.id}:${lane.done}`).join(","));
  const said = night.lanes.map((lane) => (lane.done ? `${lane.id} executed` : `${lane.id} delayed ${lane.delay} h`)).join(", ");
  const map = svg("svg", { class: "night-lanes", viewBox: `0 0 ${night.width} ${night.height}`, role: "img", "aria-label": `Open incidents on one time scale: ${said}` }, undefined, doc);
  const trails = svg("g", { class: "trails" }, undefined, doc);
  const labels = svg("g", { class: "lane-labels" }, undefined, doc);
  for (const lane of night.lanes) {
    const kind = lane.done ? " done" : lane.late ? " late" : "";
    if (!lane.done) trails.append(svg("path", { d: lane.lead, class: "trail-glow", filter: "url(#lane-glow)" }, undefined, doc));
    trails.append(svg("path", { d: lane.lead, class: `lane-lead${kind}${lane.risk ? " risk" : ""}` }, undefined, doc));
    if (lane.late) trails.append(svg("path", { d: lane.tail, class: `lane-tail${lane.risk ? " risk" : ""}` }, undefined, doc));
    trails.append(svg("line", { x1: lane.promise, x2: lane.promise, y1: lane.y - 6, y2: lane.y + 6, class: "lane-promise" }, undefined, doc),
      svg("circle", { cx: lane.end, cy: lane.y, r: 3.5, class: `lane-end${kind}` }, undefined, doc));
    labels.append(svg("text", { x: journey.NIGHT.start, y: lane.y - 8, class: "lane-id" }, lane.id, doc),
      svg("text", { x: lane.end + 8, y: lane.y + 4, class: `lane-delay${kind}` }, lane.done ? "done" : lane.late ? `+${lane.delay} h` : "on time", doc));
  }
  trails.append(svg("circle", { cx: night.hub.x, cy: night.hub.y, r: 4, class: "lane-hub" }, undefined, doc));
  map.append(glow("lane-glow", doc), trails, labels);
  const key = el("figcaption", "lane-key", undefined, doc);
  key.setAttribute("aria-hidden", "true");
  key.append(el("span", "key-promise", undefined, doc), "promise", el("span", "key-delay", undefined, doc), "delay");
  figure.append(map, key);
  return figure;
}

export function renderSession(section, session, doc = globalThis.document) {
  section.querySelector(".session-strip")?.remove();
  if (!session) return;
  const strip = el("ul", `session-strip${session.length ? "" : " empty"}`, undefined, doc);
  strip.setAttribute("aria-label", "This session's outcomes, from the recorded events");
  if (!session.length) strip.append(el("li", "", EMPTY_SESSION, doc));
  for (const [value, label] of session) {
    const item = el("li", "", undefined, doc);
    item.append(el("strong", "", value, doc), el("span", "", label, doc));
    strip.append(item);
  }
  section.append(strip);
}

function drawPlace(layer, place, doc) {
  const below = place.role === "origin" || place.role === "source";
  layer.append(
    svg("circle", { cx: place.x, cy: place.y, r: place.role === "destination" ? 5.5 : 4.5, class: `place place-${place.role}` }, undefined, doc),
    svg("text", { x: place.x, y: place.y + (below ? 22 : -13), "text-anchor": "middle", class: "place-label" }, place.name, doc),
  );
}

export function drawMap(map, caption, snapshot, plan, { route, journey }, doc = globalThis.document) {
  map.replaceChildren(svg("title", { id: "device-map-title" }, "Plan route diagram", doc));
  caption.replaceChildren();
  if (plan) {
    const line = el("p", "plan-line", undefined, doc);
    const labels = snapshot.plans.filter((item) => item.source_version === plan.source_version).map((item) => item.label);
    line.append(...labelNodes(plan.label, labels, doc), ` · $${plan.incremental_cost_usd}`);
    caption.append(line);
  }
  const shipment = snapshot?.state?.shipment;
  if (!shipment) return;
  const view = journey.wideLayout(shipment, route.legsFor(snapshot.state, plan));
  const trails = svg("g", { class: "trails" }, undefined, doc);
  const labels = svg("g", { class: "trail-labels" }, undefined, doc);
  if (!view.legs.some((leg) => leg.type === "delayed")) trails.append(svg("path", { d: view.booked.d, class: view.legs.length ? "trail ghost" : "trail late" }, undefined, doc));
  for (const leg of view.legs) {
    if (!leg.late) trails.append(svg("path", { d: leg.d, class: "trail-glow", filter: "url(#trail-glow)" }, undefined, doc));
    trails.append(svg("path", { d: leg.d, class: `trail leg-${leg.type}${leg.late ? " late" : ""}` }, undefined, doc));
    const text = `${leg.label} · ${leg.units}`;
    const spot = journey.labelSpot(leg, text.length * 8.4);
    labels.append(svg("text", { x: spot.x, y: spot.y, "text-anchor": spot.anchor, class: `trail-label${leg.late ? " late" : ""}` }, text, doc));
  }
  const places = svg("g", { class: "places" }, undefined, doc);
  for (const place of view.places) drawPlace(places, { ...place, name: route.shortName(place.name, 14) }, doc);
  map.append(glow("trail-glow", doc), trails, places, labels);
  if (!view.legs.length) {
    caption.append(el("span", "muted", "Investigate to see a plan's legs.", doc));
    return;
  }
  const list = el("ul", "legend visually-hidden", undefined, doc);
  for (const leg of view.legs) {
    const where = leg.loop ? `at ${leg.to.name}` : `${leg.from.name} → ${leg.to.name}`;
    list.append(el("li", "", `${leg.label}: ${leg.units} units ${where}, ${when(leg.arrival_eta)}${leg.late ? " · late" : ""}`, doc));
  }
  caption.append(list);
}

function track(position, doc) {
  const line = el("span", "track", undefined, doc);
  line.setAttribute("aria-hidden", "true");
  const reach = position.end === null ? position.promise : Math.min(position.end, position.promise);
  const lit = el("span", "lit", undefined, doc);
  lit.style.width = `${reach}%`;
  line.append(lit);
  if (position.late) {
    const over = el("span", "over", undefined, doc);
    over.style.left = `${position.promise}%`;
    over.style.width = `${position.end - position.promise}%`;
    line.append(over);
  }
  const tick = el("span", "tick", undefined, doc);
  tick.style.left = `${position.promise}%`;
  line.append(tick);
  if (position.end !== null) {
    const dot = el("span", "dot", undefined, doc);
    dot.style.left = `${position.end}%`;
    line.append(dot);
  }
  return line;
}

export function drawBars(list, plan, { route, journey }, shipment, doc = globalThis.document, orders = []) {
  list.replaceChildren();
  const bars = route.promiseBars(plan);
  const rows = bars.length ? bars : orders.map((order) => ({ ...order, pending: true }));
  const tracks = journey.promiseTracks(shipment, rows);
  const booked = el("li", "promise shipment late", undefined, doc);
  const hours = Math.round((Date.parse(shipment.delayed_eta) - Date.parse(shipment.original_eta)) / 3600000);
  booked.append(el("span", "who", "Booked shipment", doc), track(tracks.shipment, doc), el("span", "verdict", `+${hours} h · now ${when(shipment.delayed_eta)}`, doc));
  list.append(booked);
  rows.forEach((row, index) => {
    const item = el("li", `promise${row.pending ? " pending" : row.on_time ? " on-time" : " late"}`, undefined, doc);
    const who = el("span", "who", `${row.customer} · ${row.quantity} units`, doc);
    if (row.priority === "critical") who.append(" ", el("span", "critical-tag", "critical order", doc));
    const verdict = row.pending ? `Promised ${when(row.due_eta)} · no plan yet`
      : row.on_time ? `On time · promised ${when(row.due_eta)}`
      : `+${row.delay_hours} h · ${row.late_units} units late · promised ${when(row.due_eta)}`;
    item.append(who, track(tracks.rows[index], doc), el("span", "verdict", verdict, doc));
    list.append(item);
  });
}

export function renderIncident(section, { snapshot, plan, summary, route, journey }, doc = globalThis.document) {
  const facts = incidentFacts(snapshot);
  const head = el("div", "incident-head", undefined, doc);
  const title = el("h2", "", undefined, doc);
  title.append(el("span", "incident-id", facts.id, doc));
  head.append(title, el("p", "incident-route", [summary?.kind_label, facts.route, `${facts.units} units`].filter(Boolean).join(" · "), doc));
  const band = incidentBand(snapshot, summary);
  if (band) head.prepend(el("p", `band ${band[0]}`, band[1], doc));
  const figure = el("figure", "device-map", undefined, doc);
  settle(section, figure, `${facts.id}:${plan?.id || ""}`);
  const map = svg("svg", { id: "device-map", viewBox: `0 0 ${journey.WIDE.width} ${journey.WIDE.height}`, role: "img", "aria-labelledby": "device-map-title" }, undefined, doc);
  const caption = el("figcaption", "", undefined, doc);
  caption.id = "device-map-caption";
  figure.append(map, caption);
  drawMap(map, caption, snapshot, plan, { route, journey }, doc);
  const promise = el("div", "device-promise", undefined, doc);
  const bars = el("ol", "promise-list", undefined, doc);
  bars.id = "device-bars";
  bars.setAttribute("aria-label", "The booked shipment and each order's promise against the projection, on one time scale");
  promise.append(bars);
  drawBars(bars, plan, { route, journey }, snapshot.state.shipment, doc, snapshot.state.orders);
  if (facts.stock) promise.append(el("p", "stock-line", `Local stock · ${facts.stock.available} units at ${facts.stock.name}`, doc));
  const grid = el("div", "incident-grid", undefined, doc);
  grid.append(figure, promise);
  section.replaceChildren(head, grid);
}

export function renderPlanList(container, { plans, selectedId, recommendedId, preferredId, locked, onSelect }, doc = globalThis.document) {
  container.replaceChildren();
  container.setAttribute("role", "list");
  const labels = plans.map((plan) => plan.label);
  for (const plan of plans) {
    const item = el("div", `plan${plan.id === selectedId ? " selected" : ""}${plan.id === recommendedId ? " recommended" : ""}`, undefined, doc);
    item.setAttribute("role", "listitem");
    const description = el("div", "", undefined, doc);
    const title = el("strong", "", undefined, doc);
    title.append(...labelNodes(plan.label, labels, doc));
    if (plan.id === recommendedId) title.append(el("span", "badge", "Agent pick", doc));
    if (plan.id === preferredId) title.append(el("span", "badge preference", "Your preference", doc));
    if (plan.projected_customer_delay_hours === 0) title.append(el("span", "badge", "Zero delay", doc));
    description.append(title, el("small", "", allocationSummary(plan), doc));
    const figures = el("div", "plan-figures", undefined, doc);
    figures.append(el("strong", "", `$${plan.incremental_cost_usd}`, doc), el("small", "", `${plan.projected_customer_delay_hours} h delay · ${formatDate(plan.projected_completion_eta)}`, doc));
    item.append(description, figures);
    if (!locked) item.append(button(plan.id === selectedId ? "Selected" : "Select", "plan-select", () => onSelect(plan), doc));
    container.append(item);
  }
}

export function renderConfirm(section, payload, { onYes, onNo, labels = [] }, doc = globalThis.document) {
  const details = confirmDetails(payload);
  const card = el("div", `confirm-card ${details.kind}`, undefined, doc);
  if (details.warning) card.append(el("p", "band late", details.warning, doc));
  const lead = el("p", "lead", undefined, doc);
  lead.append(...labelNodes(details.lead, labels, doc));
  const figure = el("p", "confirm-figure", undefined, doc);
  figure.append(el("strong", "", details.figure[0], doc), " ", el("span", "", details.figure[1], doc));
  card.append(columns([el("h2", "", details.title, doc), lead, figure], [rowList(details.rows, doc), el("p", "note", details.note, doc)], doc));
  const actions = el("div", "confirm-actions", undefined, doc);
  const yes = button(details.yes, "primary", onYes, doc);
  yes.id = "confirm-yes";
  const no = button(details.no, "secondary", onNo, doc);
  no.id = "confirm-no";
  actions.append(yes, no);
  card.append(actions);
  section.replaceChildren(card);
}

export function renderReceipt(section, { booking, onOpen, onExecute = null }, doc = globalThis.document) {
  const card = el("div", "receipt-card", undefined, doc);
  card.append(el("p", "band ok", "Receipt · simulated payment", doc), columns([
    el("h2", "", `Booked ${booking.number}`, doc), el("p", "receipt-total", dollars(booking.total_usd), doc), el("p", "lead", booking.plan_label, doc),
    el("p", "note", `${String(booking.payment?.method || "").replace(/\s*\(simulated\)$/i, "")} · charged once · delivery is projected, not confirmed`, doc),
  ], [rowList(bookingRows(booking), doc)], doc));
  const actions = el("div", "receipt-actions", undefined, doc);
  if (onExecute) {
    const execute = button("Execute approved plan", "primary", onExecute, doc);
    execute.id = "receipt-execute";
    actions.append(execute);
  }
  actions.append(button("Open printable receipt", "secondary", onOpen, doc));
  card.append(actions);
  section.replaceChildren(card);
}

function planLine(className, prefix, plan, labels, doc) {
  const line = el("p", className, `${prefix} “`, doc);
  line.append(...labelNodes(plan.label, labels, doc), `”${plan.figures ? ` · ${plan.figures}` : ""}`);
  return line;
}

export function renderAlert(section, alert, doc = globalThis.document) {
  const details = alertDetails(alert);
  const labels = [details.was?.label, details.plan?.label].filter(Boolean);
  const card = el("div", "alert-card", undefined, doc);
  card.append(el("p", `band ${details.invalidated ? "late" : "warn"}`, details.invalidated ? "Proactive alert · approval invalidated" : "Proactive alert · nothing approved", doc),
    columns([el("h2", "", details.title, doc), el("p", "lead", details.text, doc)], [
      details.was ? planLine("was-plan", details.invalidated ? "Was approved:" : "Was", details.was, labels, doc) : null,
      details.plan ? planLine(`new-plan${details.plan.late ? " late" : ""}`, "Now", details.plan, labels, doc) : null,
    ], doc));
  section.replaceChildren(card);
}

export function renderResult(section, { snapshot, execution, plan, booking, times = [] }, doc = globalThis.document) {
  const card = el("div", "result-card", undefined, doc);
  const heading = el("h2", "", plan ? plan.label : execution.plan_id, doc);
  const lead = el("p", "lead", undefined, doc);
  lead.append(el("span", "incident-id", snapshot.state.incident_id, doc), ` · ${snapshot.state.title}`);
  let figure = null;
  if (plan) {
    const outcome = resultOutcome(plan);
    figure = el("p", "result-figure", undefined, doc);
    figure.append(el("strong", "", outcome.value, doc), " ", el("span", "", outcome.label, doc), " ", el("small", "", outcome.note, doc));
  }
  const figures = el("div", "figures", undefined, doc);
  for (const item of resultFigures(snapshot, execution)) {
    const box = el("div", "figure", undefined, doc);
    box.append(el("strong", "", item.value, doc), el("span", "", item.label, doc));
    if (item.note) box.append(el("small", "", item.note, doc));
    figures.append(box);
  }
  card.append(el("p", "band ok", "Executed · operationally verified", doc), columns([
    heading, lead, figure,
    times.length ? el("p", "times", times.map(([label, value]) => `${label} ${value}`).join(" · "), doc) : null,
    booking ? el("p", "note", `Booked ${booking.number} · ${dollars(booking.total_usd)} charged once.`, doc) : null,
    el("p", "note", "Delivery is projected from synthetic quotes, not physically confirmed.", doc),
  ], [plan ? rowList(orderRows(plan), doc) : null, figures], doc));
  section.replaceChildren(card);
}

export function stepLabel(step) {
  const input = step.input || {};
  const output = step.output || {};
  let detail = input.shipment_id || input.order_id || (input.warehouse_id ? `${input.warehouse_id} warehouse` : "");
  if (step.tool === "investigate_incident" && Array.isArray(output.plans)) detail = `${output.plans.length} plans`;
  if (step.tool === "list_incidents" && Array.isArray(output.incidents)) detail = `${output.incidents.length} incidents`;
  if (step.tool === "find_alternative_carriers" && output && !step.is_error) detail = `${Object.keys(output).length} quotes`;
  return `${STEP_NAMES[step.tool] || step.tool}${detail ? ` · ${detail}` : ""}${step.is_error ? " · error" : ""}`;
}

export function renderAgentLine(node, text, run, doc = globalThis.document) {
  node.replaceChildren();
  node.hidden = !text;
  if (!text) return;
  const dots = el("span", "agent-dots", undefined, doc);
  dots.setAttribute("aria-hidden", "true");
  for (const step of run.tool_trace) dots.append(el("span", step.is_error ? "error" : "", undefined, doc));
  if (run.evaluations?.length) dots.append(el("span", run.grounded ? "check" : "check failed", undefined, doc));
  node.append(dots, el("span", "", text, doc));
}

function traceDetails(run, { open = false, fresh = false } = {}, doc = globalThis.document) {
  const steps = run?.tool_trace || [];
  if (!steps.length) return null;
  const details = el("details", `turn-trace${fresh ? " fresh" : ""}`, undefined, doc);
  details.open = open;
  const list = el("ol", "device-steps", undefined, doc);
  list.setAttribute("aria-label", "Steps the agent took, from the recorded tool trace");
  if (run.skill?.name) list.append(el("li", "skill", `Agent Skill · ${run.skill.name}`, doc));
  steps.forEach((step, index) => {
    const item = el("li", step.is_error ? "error" : "", stepLabel(step), doc);
    item.style.setProperty("--step", String(index));
    list.append(item);
  });
  details.append(el("summary", "", `From the recorded tool trace · ${steps.length} MCP call${steps.length === 1 ? "" : "s"}`, doc), list);
  return details;
}

export function renderTranscript(list, turns, renderMarkdown, { fresh = null } = {}, doc = globalThis.document) {
  list.replaceChildren();
  const latest = turns.findLastIndex((entry) => entry.trace?.tool_trace?.length);
  turns.forEach((entry, index) => {
    const item = el("li", `turn ${entry.role}`, undefined, doc);
    item.append(el("span", "turn-role", entry.role === "user" ? "You" : "LogiOps", doc));
    if (entry.role === "assistant") item.append(renderMarkdown(entry.text));
    else item.append(el("p", "", entry.text, doc));
    if (entry.check) item.append(el("span", `check-badge${entry.check.passed ? "" : " failed"}`, entry.check.text, doc));
    if (entry.meta) item.append(el("small", "", entry.meta, doc));
    const trace = traceDetails(entry.trace, { open: index === latest, fresh: Boolean(fresh) && entry.trace === fresh }, doc);
    if (trace) item.append(trace);
    list.append(item);
  });
  list.scrollTop = list.scrollHeight;
}
