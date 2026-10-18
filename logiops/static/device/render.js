import { dollars, bookingRows } from "../app/purchase.js";
import { formatDate, allocationSummary, distinguishing, TIME_ZONE } from "../app/selectors.js";
import { incidentFacts, incidentBand, confirmDetails, resultFigures, alertDetails } from "./surfaces.js";
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

function button(text, className, onClick, doc = globalThis.document) {
  const node = el("button", className, text, doc);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

export function renderHome(section, { greeting, lead, session }, doc = globalThis.document) {
  section.querySelector(".home-head")?.remove();
  section.querySelector(".session-strip")?.remove();
  const head = el("div", "home-head", undefined, doc);
  head.append(el("p", "lead", lead || greeting, doc));
  if (lead) head.append(el("p", "sub", greeting, doc));
  section.prepend(head);
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
  const below = place.role === "destination";
  layer.append(
    svg("circle", { cx: place.x, cy: place.y, r: place.role === "source" ? 4 : 5, class: `place place-${place.role}` }, undefined, doc),
    svg("text", { x: place.x, y: place.y + (below ? 17 : -10), "text-anchor": "middle", class: "place-label" }, place.name, doc),
  );
}

export function drawMap(map, caption, snapshot, plan, route, doc = globalThis.document) {
  map.replaceChildren(svg("title", { id: "device-map-title" }, "Plan route diagram", doc));
  caption.replaceChildren();
  const shipment = snapshot?.state?.shipment;
  if (!shipment) return;
  const view = route.layout(shipment, route.legsFor(snapshot.state, plan));
  const layer = svg("g", { class: "legs" }, undefined, doc);
  const lifts = [0.22, -0.22, 0.42, -0.42];
  let travelling = 0;
  if (!view.legs.length && view.places.length) layer.append(svg("path", { d: route.arc(view.places[0], view.destination, 0.22), class: "leg leg-delayed" }, undefined, doc));
  for (const leg of view.legs) {
    const className = `leg leg-${leg.type}${leg.late ? " late" : ""}`;
    if (leg.loop) {
      layer.append(svg("circle", { cx: leg.to.x, cy: leg.to.y, r: 8, class: className }, undefined, doc));
    } else {
      layer.append(svg("path", { d: route.arc(leg.from, leg.to, lifts[travelling % lifts.length]), class: className }, undefined, doc));
      travelling += 1;
    }
  }
  const places = svg("g", { class: "places" }, undefined, doc);
  for (const place of [...view.places, view.destination]) drawPlace(places, { ...place, name: route.shortName(place.name, view.places.length > 2 ? 10 : 14) }, doc);
  map.append(layer, places);
  if (!view.legs.length) {
    caption.append(el("span", "muted", "Delayed route. Investigate to see a plan's legs.", doc));
    return;
  }
  const list = el("ul", "legend", undefined, doc);
  for (const leg of view.legs) {
    const item = el("li", `leg-${leg.type}${leg.late ? " late" : ""}`, undefined, doc);
    const where = leg.loop ? `at ${leg.to.name}` : `${leg.from.name} → ${leg.to.name}`;
    item.append(el("span", "swatch", undefined, doc), el("span", "", `${leg.label}: ${leg.units} units ${where}, ${when(leg.arrival_eta)}${leg.late ? " · late" : ""}`, doc));
    list.append(item);
  }
  caption.append(list);
}

export function drawBars(list, plan, route, doc = globalThis.document) {
  list.replaceChildren();
  const bars = route.promiseBars(plan);
  if (!bars.length) {
    list.append(el("li", "muted", "No plan yet. Ask what's happening with this incident.", doc));
    return;
  }
  for (const bar of bars) {
    const item = el("li", `promise${bar.on_time ? " on-time" : " late"}`, undefined, doc);
    const who = el("span", "who", `${bar.customer} · ${bar.quantity} units`, doc);
    if (bar.priority === "critical") who.append(" ", el("span", "critical-tag", "critical", doc));
    const track = el("span", "track", undefined, doc);
    track.setAttribute("aria-hidden", "true");
    const fill = el("span", "fill", undefined, doc);
    fill.style.width = `${Math.max(bar.on_time ? 0 : 6, Math.round(bar.ratio * 100))}%`;
    track.append(fill);
    const verdict = bar.on_time
      ? `On time · promised ${when(bar.due_eta)}`
      : `+${bar.delay_hours} h · ${bar.late_units} units late · promised ${when(bar.due_eta)}`;
    item.append(who, track, el("span", "verdict", verdict, doc));
    list.append(item);
  }
}

export function renderIncident(section, { snapshot, plan, summary, route }, doc = globalThis.document) {
  const facts = incidentFacts(snapshot);
  const head = el("div", "incident-head", undefined, doc);
  const title = el("h2", "", undefined, doc);
  title.append(el("span", "incident-id", facts.id, doc));
  head.append(title, el("p", "incident-title", summary?.kind_label ? `${summary.kind_label} · ${facts.title}` : facts.title, doc),
    el("p", "incident-route", `${facts.route} · ${facts.units} units of ${facts.sku} · ${facts.orders === 1 ? "1 order" : `${facts.orders} orders`}`, doc));
  const band = incidentBand(snapshot, summary);
  if (band) head.prepend(el("p", `band ${band[0]}`, band[1], doc));
  if (plan) {
    const line = el("p", "plan-line", undefined, doc);
    const labels = snapshot.plans.filter((item) => item.source_version === plan.source_version).map((item) => item.label);
    line.append(...labelNodes(plan.label, labels, doc), ` · $${plan.incremental_cost_usd}`);
    head.append(line);
  }
  const facts3 = el("div", "facts", undefined, doc);
  const fact = (label, value, note, className = "") => {
    const box = el("div", `fact ${className}`.trim(), undefined, doc);
    box.append(el("span", "", label, doc), el("strong", "", value, doc), el("small", "", note, doc));
    return box;
  };
  facts3.append(fact("Original ETA", facts.originalEta, facts.promiseLabel), fact("Delayed ETA", facts.delayedEta, `+${facts.delayHours} hours`, "warning"),
    fact("Local stock", facts.stock ? `${facts.stock.available} units` : "None", facts.stock ? facts.stock.name : "No local warehouse"));
  const figure = el("figure", "device-map", undefined, doc);
  const map = svg("svg", { id: "device-map", viewBox: `0 0 ${route.VIEW.width} ${route.VIEW.height}`, role: "img", "aria-labelledby": "device-map-title" }, undefined, doc);
  const caption = el("figcaption", "", undefined, doc);
  caption.id = "device-map-caption";
  figure.append(map, caption);
  drawMap(map, caption, snapshot, plan, route, doc);
  const promise = el("div", "device-promise", undefined, doc);
  const bars = el("ol", "promise-list", undefined, doc);
  bars.id = "device-bars";
  bars.setAttribute("aria-label", "Each order's promise against the projection");
  promise.append(bars);
  drawBars(bars, plan, route, doc);
  const grid = el("div", "incident-grid", undefined, doc);
  grid.append(figure, promise);
  section.replaceChildren(head, facts3, grid);
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
  card.append(el("h2", "", details.title, doc), lead);
  const figure = el("p", "confirm-figure", undefined, doc);
  figure.append(el("strong", "", details.figure[0], doc), " ", el("span", "", details.figure[1], doc));
  card.append(figure);
  const rows = el("dl", "rows", undefined, doc);
  for (const [term, value, tone] of details.rows) {
    const cell = el("dd", "", tone ? undefined : value, doc);
    if (tone) cell.append(el("span", `outcome ${tone}`, value, doc));
    rows.append(el("dt", "", term, doc), cell);
  }
  card.append(rows);
  card.append(el("p", "note", details.note, doc));
  const actions = el("div", "confirm-actions", undefined, doc);
  const yes = button(details.yes, "primary", onYes, doc);
  yes.id = "confirm-yes";
  const no = button(details.no, "secondary", onNo, doc);
  no.id = "confirm-no";
  actions.append(yes, no);
  card.append(actions);
  section.replaceChildren(card);
}

export function renderReceipt(section, { booking, onOpen }, doc = globalThis.document) {
  const card = el("div", "receipt-card", undefined, doc);
  card.append(el("p", "band ok", "Receipt · simulated payment", doc), el("h2", "", `Booked ${booking.number}`, doc),
    el("p", "receipt-total", dollars(booking.total_usd), doc), el("p", "lead", booking.plan_label, doc));
  const rows = el("dl", "rows", undefined, doc);
  for (const [term, value] of bookingRows(booking)) rows.append(el("dt", "", term, doc), el("dd", "", value, doc));
  card.append(rows, el("p", "note", `${String(booking.payment?.method || "").replace(/\s*\(simulated\)$/i, "")} · charged once · delivery is projected, not confirmed`, doc));
  card.append(button("Open printable receipt", "secondary", onOpen, doc));
  section.replaceChildren(card);
}

export function renderAlert(section, alert, doc = globalThis.document) {
  const details = alertDetails(alert);
  const card = el("div", "alert-card", undefined, doc);
  card.append(el("p", `band ${details.invalidated ? "late" : "warn"}`, details.invalidated ? "Proactive alert · approval invalidated" : "Proactive alert · nothing approved", doc),
    el("h2", "", details.title, doc), el("p", "lead", details.text, doc));
  if (details.plan) card.append(el("p", "new-plan", details.plan, doc));
  section.replaceChildren(card);
}

export function renderResult(section, { snapshot, execution, plan, booking, times = [] }, doc = globalThis.document) {
  const card = el("div", "result-card", undefined, doc);
  const heading = el("h2", "", undefined, doc);
  const labels = snapshot.plans.filter((item) => item.source_version === plan?.source_version).map((item) => item.label);
  heading.append(...(plan ? labelNodes(plan.label, labels, doc) : [execution.plan_id]));
  card.append(el("p", "band ok", "Executed · operationally verified", doc), heading,
    el("p", "lead", `${snapshot.state.incident_id} · ${snapshot.state.title}`, doc));
  const figures = el("div", "figures", undefined, doc);
  for (const item of resultFigures(snapshot, execution)) {
    const box = el("div", "figure", undefined, doc);
    box.append(el("strong", "", item.value, doc), el("span", "", item.label, doc));
    if (item.note) box.append(el("small", "", item.note, doc));
    figures.append(box);
  }
  card.append(figures);
  if (times.length) card.append(el("p", "times", times.map(([label, value]) => `${label} ${value}`).join(" · "), doc));
  if (booking) card.append(el("p", "note", `Booked ${booking.number} · ${dollars(booking.total_usd)} charged once.`, doc));
  card.append(el("p", "note", "Delivery is projected from synthetic quotes, not physically confirmed.", doc));
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

export function renderTrace(box, run, { check, reducedMotion = false, setTimeout: schedule = globalThis.setTimeout } = {}, doc = globalThis.document) {
  const steps = run?.tool_trace || [];
  box.hidden = !steps.length;
  const title = box.querySelector(".trace-title");
  const badge = box.querySelector(".device-check");
  const list = box.querySelector("ol");
  list.replaceChildren();
  title.textContent = `From the recorded tool trace · ${steps.length} MCP call${steps.length === 1 ? "" : "s"}`;
  badge.textContent = check ? check.text : "";
  badge.className = `device-check${check ? (check.passed ? " passed" : " failed") : ""}`;
  badge.hidden = !check;
  const timers = [];
  if (run?.skill?.name) list.append(el("li", "skill", `Agent Skill · ${run.skill.name}`, doc));
  steps.forEach((step, index) => {
    const item = el("li", step.is_error ? "error" : "", stepLabel(step), doc);
    if (reducedMotion) list.append(item);
    else timers.push(schedule(() => list.append(item), index * 220));
  });
  return timers;
}

export function renderTranscript(list, turns, renderMarkdown, doc = globalThis.document) {
  list.replaceChildren();
  for (const entry of turns) {
    const item = el("li", `turn ${entry.role}`, undefined, doc);
    item.append(el("span", "turn-role", entry.role === "user" ? "You" : "LogiOps", doc));
    if (entry.role === "assistant") item.append(renderMarkdown(entry.text));
    else item.append(el("p", "", entry.text, doc));
    if (entry.check) item.append(el("span", `check-badge${entry.check.passed ? "" : " failed"}`, entry.check.text, doc));
    if (entry.meta) item.append(el("small", "", entry.meta, doc));
    list.append(item);
  }
  list.scrollTop = list.scrollHeight;
}
