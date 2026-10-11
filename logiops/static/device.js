(function (root) {
  const SVG = "http://www.w3.org/2000/svg";
  const CLOCK = new Intl.DateTimeFormat("en-US", { timeZone: "America/Lima", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const WHEN = new Intl.DateTimeFormat("en-US", { timeZone: "America/Lima", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const byId = (id) => document.getElementById(id);
  const STEP_NAMES = {
    get_shipment: "Shipment", get_order: "Order", get_inventory: "Stock", find_alternative_carriers: "Carrier quotes",
    investigate_incident: "Plans calculated", get_execution_status: "Execution status", list_incidents: "Inbox",
  };
  let voice = "ready";
  let started = 0;
  let ticker = 0;
  let reveal = [];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function svg(tag, attributes, text) {
    const node = document.createElementNS(SVG, tag);
    for (const [name, value] of Object.entries(attributes || {})) node.setAttribute(name, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function when(iso) {
    const time = Date.parse(iso);
    return Number.isNaN(time) ? "—" : WHEN.format(new Date(time));
  }

  function elapsed() {
    const line = byId("device-elapsed");
    if (line && started) line.textContent = `${Math.floor((performance.now() - started) / 1000)} s`;
  }

  function setVoice(event, speaking = false) {
    const next = root.LogiOpsRoute.voiceState(voice, event, speaking);
    const line = byId("device-elapsed");
    if (next.state === "thinking" && voice !== "thinking") {
      started = performance.now();
      if (line) line.textContent = "0 s";
      clearInterval(ticker);
      ticker = setInterval(elapsed, 250);
    } else if (next.state !== "thinking" && voice === "thinking") {
      clearInterval(ticker);
      if (line && started) line.textContent = `answered in ${((performance.now() - started) / 1000).toFixed(1)} s`;
      started = 0;
    }
    voice = next.state;
    const orb = byId("device-orb");
    if (orb) orb.dataset.state = voice;
    const label = byId("device-state");
    if (label && label.textContent !== next.label) label.textContent = next.label;
  }

  function heard(text) {
    const line = byId("device-heard");
    if (line) line.textContent = text;
  }

  function reply(text, spoken, speaking) {
    const line = byId("device-spoken");
    if (line) {
      const plain = spoken || root.LogiOpsMarkdown.plainText(text);
      line.textContent = plain.length > 260 ? `${plain.slice(0, 257).trimEnd()}…` : plain;
    }
    setVoice("reply", speaking);
  }

  function tick() {
    const clock = byId("device-clock");
    if (clock) clock.textContent = `${CLOCK.format(new Date())} · Lima`;
  }

  function drawCity(layer, city, role) {
    const right = city.x < 170;
    layer.append(
      svg("circle", { cx: city.x, cy: city.y, r: role ? 3.2 : 2, class: `city${role ? ` city-${role}` : ""}` }),
      svg("text", { x: city.x + (right ? 6 : -6), y: city.y + 3, "text-anchor": right ? "start" : "end", class: "city-label" }, city.name),
    );
  }

  function drawMap(snapshot, plan) {
    const map = byId("device-map");
    if (!map) return;
    const route = root.LogiOpsRoute;
    map.replaceChildren(
      svg("title", { id: "device-map-title" }, "Plan route on a map of Peru"),
      svg("path", { d: route.linePath(route.OUTLINE), class: "map-land" }),
    );
    const caption = byId("device-map-caption");
    const shipment = snapshot?.state?.shipment;
    if (!shipment) {
      if (caption) caption.textContent = "Connect to load the incident.";
      return;
    }
    const legs = route.legsFor(snapshot.state, plan);
    const layer = svg("g", { class: "legs" });
    const origin = route.cityOf(shipment.origin);
    const destination = route.cityOf(shipment.destination);
    const lifts = [0.22, -0.22, 0.42, -0.42];
    let travelling = 0;
    for (const leg of legs) {
      const className = `leg leg-${leg.type}${leg.late ? " late" : ""}`;
      if (leg.from && leg.to && leg.from.name === leg.to.name) {
        layer.append(svg("circle", { cx: leg.to.x, cy: leg.to.y, r: 8, class: className }));
      } else {
        layer.append(svg("path", { d: route.arc(leg.from, leg.to, lifts[travelling % lifts.length]), class: className }));
        travelling += 1;
      }
    }
    const cities = svg("g", { class: "cities" });
    const shown = new Set();
    for (const [city, role] of [[origin, "origin"], [destination, "destination"], ...legs.map((leg) => [leg.from, "source"])]) {
      if (city && !shown.has(city.name)) {
        shown.add(city.name);
        drawCity(cities, city, role);
      }
    }
    map.append(layer, cities);
    if (!caption) return;
    caption.replaceChildren();
    if (!legs.length) {
      caption.append(el("span", "muted", `${shipment.origin} → ${shipment.destination}. Investigate to see a plan on the map.`));
      return;
    }
    const list = el("ul", "legend");
    for (const leg of legs) {
      const item = el("li", `leg-${leg.type}${leg.late ? " late" : ""}`);
      const where = leg.from && leg.to && leg.from.name !== leg.to.name ? `${leg.from.name} → ${leg.to.name}` : `at ${leg.to ? leg.to.name : shipment.destination}`;
      item.append(el("span", "swatch"), el("span", "", `${leg.label}: ${leg.units} units ${where}, ${when(leg.arrival_eta)}${leg.late ? " · late" : ""}`));
      list.append(item);
    }
    caption.append(list);
  }

  function drawBars(plan) {
    const list = byId("device-bars");
    if (!list) return;
    list.replaceChildren();
    const bars = root.LogiOpsRoute.promiseBars(plan);
    if (!bars.length) {
      list.append(el("li", "muted", "No plan yet. Ask what's happening with this incident."));
      return;
    }
    for (const bar of bars) {
      const item = el("li", `promise${bar.on_time ? " on-time" : " late"}`);
      const who = el("span", "who", `${bar.customer} · ${bar.quantity} units`);
      if (bar.priority === "critical") who.append(" ", el("span", "critical-tag", "critical"));
      const track = el("span", "track");
      track.setAttribute("aria-hidden", "true");
      const fill = el("span", "fill");
      fill.style.width = `${Math.max(bar.on_time ? 0 : 6, Math.round(bar.ratio * 100))}%`;
      track.append(fill);
      const verdict = bar.on_time
        ? `On time · promised ${when(bar.due_eta)}`
        : `+${bar.delay_hours} h · ${bar.late_units} units late · promised ${when(bar.due_eta)}`;
      item.append(who, track, el("span", "verdict", verdict));
      list.append(item);
    }
  }

  function drawChips(snapshot, plan, summary) {
    const chips = byId("device-chips");
    if (!chips) return;
    chips.replaceChildren();
    if (!snapshot?.state) return;
    const add = (className, text) => chips.append(el("span", `device-chip ${className}`, text));
    add("chip-incident", snapshot.state.incident_id);
    add("chip-status", snapshot.state.status);
    if (summary?.critical_units_at_risk > 0) add("chip-risk", `${summary.critical_units_at_risk} critical units at risk`);
    if (plan) add("chip-plan", `${plan.label} · $${plan.incremental_cost_usd}`);
  }

  function stepLabel(step) {
    const input = step.input || {};
    const output = step.output || {};
    let detail = input.shipment_id || input.order_id || (input.warehouse_id ? `${input.warehouse_id} warehouse` : "");
    if (step.tool === "investigate_incident" && Array.isArray(output.plans)) detail = `${output.plans.length} plans`;
    if (step.tool === "list_incidents" && Array.isArray(output.incidents)) detail = `${output.incidents.length} incidents`;
    if (step.tool === "find_alternative_carriers" && output && !step.is_error) detail = `${Object.keys(output).length} quotes`;
    return `${STEP_NAMES[step.tool] || step.tool}${detail ? ` · ${detail}` : ""}${step.is_error ? " · error" : ""}`;
  }

  function checkText(run) {
    if (!run.evaluations?.length) return null;
    if (!run.grounded) return { passed: false, text: "Did not pass the data check" };
    return { passed: true, text: run.evaluations.length > 1 ? "Checked against the data after one revision" : "Checked against the data" };
  }

  function trace(run) {
    const box = byId("device-trace");
    const list = byId("device-steps");
    if (!box || !list) return;
    for (const timer of reveal) clearTimeout(timer);
    reveal = [];
    list.replaceChildren();
    const steps = run?.tool_trace || [];
    box.hidden = !steps.length;
    const title = byId("device-trace-title");
    if (title) title.textContent = `From the recorded tool trace · ${steps.length} MCP call${steps.length === 1 ? "" : "s"}`;
    const badge = byId("device-check");
    const check = run ? checkText(run) : null;
    if (badge) {
      badge.textContent = check ? check.text : "";
      badge.className = `device-check${check ? (check.passed ? " passed" : " failed") : ""}`;
      badge.hidden = !check;
    }
    const still = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (run?.skill?.name) list.append(el("li", "skill", `Agent Skill · ${run.skill.name}`));
    steps.forEach((step, index) => {
      const item = el("li", step.is_error ? "error" : "", stepLabel(step));
      if (still) list.append(item);
      else reveal.push(setTimeout(() => list.append(item), index * 220));
    });
  }

  function show(snapshot, plan, summary) {
    drawChips(snapshot, plan || null, summary);
    drawMap(snapshot, plan || null);
    drawBars(plan || null);
  }

  function mount() {
    tick();
    setInterval(tick, 30000);
    setVoice("error");
    drawMap(null, null);
    drawBars(null);
  }

  root.LogiOpsDevice = { mount, heard, reply, voice: setVoice, show, trace };
})(window);
