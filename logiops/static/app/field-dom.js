const SVG = "http://www.w3.org/2000/svg";

function shape(doc, tag, attributes = {}, text) {
  const node = doc.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function item(doc, className, text) {
  const node = doc.createElement("li");
  node.className = className;
  node.textContent = text;
  return node;
}

export function drawField(figure, plans, pickId, { shapes, view = shapes.WIDE, id = "field", chosen = "selected" }, doc = globalThis.document) {
  figure.replaceChildren();
  figure.hidden = plans.length < 2;
  if (figure.hidden) return;
  const field = shapes.decisionField(plans, pickId, view);
  const { left, right, top, bottom, ticks } = field.axes;
  const pick = plans.find((plan) => plan.id === pickId);
  const said = pick
    ? `${plans.length} plans by delay and cost. The ${chosen} plan costs $${pick.incremental_cost_usd} with ${pick.projected_customer_delay_hours} h of delay.`
    : `${plans.length} plans by delay and cost.`;
  const map = shape(doc, "svg", { viewBox: `0 0 ${field.view.width} ${field.view.height}`, role: "img", "aria-label": said });
  const defs = shape(doc, "defs");
  const glow = shape(doc, "filter", { id: `${id}-glow`, x: "-100%", y: "-100%", width: "300%", height: "300%" });
  glow.append(shape(doc, "feGaussianBlur", { stdDeviation: 5 }));
  defs.append(glow);
  map.append(defs, shape(doc, "path", { d: `M${left} ${top - 8} V${bottom} H${right}`, class: "field-axis" }));
  ticks.forEach((tick, index) => {
    const last = index === ticks.length - 1;
    const anchor = last && ticks.length > 1 ? "end" : tick.x - left < 20 ? "start" : "middle";
    map.append(shape(doc, "line", { x1: tick.x, x2: tick.x, y1: bottom, y2: bottom + 5, class: "field-tick" }),
      shape(doc, "text", { x: tick.x, y: bottom + 20, "text-anchor": anchor, class: "field-axis-label" }, `${tick.delay} h${last ? " delay" : ""}`));
  });
  for (const point of field.points) {
    const anchor = point.x > right - 24 ? "end" : point.x < left + 24 ? "start" : "middle";
    if (point.pick) {
      map.append(shape(doc, "circle", { cx: point.x, cy: point.y, r: 11, class: "field-glow", filter: `url(#${id}-glow)` }),
        shape(doc, "circle", { cx: point.x, cy: point.y, r: 12, class: "field-ring" }));
    }
    map.append(shape(doc, "circle", { cx: point.x, cy: point.y, r: point.pick ? 6 : 5, class: `field-dot ${point.pick ? "chosen" : point.standing}` }));
    if (point.labelled) {
      map.append(shape(doc, "text", { x: point.x, y: point.y - (point.pick ? 18 : 11), "text-anchor": anchor, class: `field-label${point.pick ? " chosen" : ""}` },
        `$${point.cost}`));
    }
  }
  const key = doc.createElement("ul");
  key.className = "field-key";
  key.setAttribute("aria-hidden", "true");
  key.append(item(doc, "on-time", "on time"), item(doc, "late", "some late"), item(doc, "critical-late", "critical late"));
  figure.append(map, key);
}
