import { el, stepLabel } from "./render.js";

const CADENCE_MS = 120;
const HOLD_MS = 1500;
const LEAVE_MS = 360;

export function createStage({ root, surface, quiet = [], document: doc = globalThis.document, reducedMotion = () => false }) {
  const line = root.querySelector(".agent-ask");
  const stations = root.querySelector(".agent-stations");
  const meta = root.querySelector(".agent-meta");
  let timers = [];
  let live = 0;
  let nextAt = 0;
  let waiting = [];

  const later = (work, ms) => timers.push(setTimeout(work, ms));

  function reset() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function station(text, kind, index) {
    const item = el("li", kind, text, doc);
    item.style.setProperty("--step", String(index));
    return item;
  }

  function ask([lead, subject]) {
    clear();
    root.style.top = `${surface.offsetTop}px`;
    root.style.height = `${surface.offsetHeight}px`;
    line.replaceChildren(subject ? `${lead} ` : lead);
    if (subject) line.append(el("strong", "", subject, doc));
    stations.replaceChildren();
    live = 0;
    nextAt = 0;
    meta.textContent = "0 s";
    root.classList.remove("leaving");
    root.dataset.phase = "asking";
    root.hidden = false;
    for (const node of quiet) node.inert = true;
  }

  function whenGone(work) {
    if (root.hidden) work();
    else waiting.push(work);
  }

  function tick(seconds) {
    if (root.dataset.phase === "asking") meta.textContent = `${seconds} s`;
  }

  function schedule(item, index) {
    const now = performance.now();
    const at = reducedMotion() ? now : Math.max(now, nextAt);
    nextAt = at + CADENCE_MS;
    later(() => {
      if (stations.children.length === index) stations.append(station(stepLabel(item), item.is_error ? "error" : "", 0));
    }, at - now);
  }

  function step(item) {
    if (root.hidden || root.dataset.phase !== "asking") return;
    schedule(item, live);
    live += 1;
  }

  function clear() {
    reset();
    root.hidden = true;
    root.classList.remove("leaving");
    root.dataset.phase = "";
    for (const node of quiet) node.inert = false;
    const queued = waiting;
    waiting = [];
    for (const work of queued) work();
  }

  function leave() {
    root.classList.add("leaving");
    later(clear, reducedMotion() ? 0 : LEAVE_MS);
  }

  function replay(run, check, caption) {
    if (root.hidden) return;
    const steps = run.tool_trace || [];
    if (!steps.length) {
      clear();
      return;
    }
    const streamed = live > 0;
    const hold = reducedMotion() ? 0 : HOLD_MS;
    root.dataset.phase = "replay";
    if (streamed) {
      steps.slice(live).forEach((item, offset) => schedule(item, live + offset));
      const wait = Math.max(0, nextAt - performance.now());
      if (check) later(() => stations.append(station(check.text, check.passed ? "check" : "check failed", 0)), wait);
      meta.textContent = caption(true);
      meta.style.setProperty("--step", "0");
      later(leave, wait + hold);
      return;
    }
    reset();
    stations.replaceChildren(...steps.map((item, index) => station(stepLabel(item), item.is_error ? "error" : "", index)));
    if (check) stations.append(station(check.text, check.passed ? "check" : "check failed", steps.length));
    meta.textContent = caption(false);
    meta.style.setProperty("--step", String(stations.children.length));
    later(leave, (reducedMotion() ? 0 : stations.children.length * CADENCE_MS) + hold);
  }

  function settle() {
    later(() => {
      if (root.dataset.phase === "asking") clear();
    }, 0);
  }

  return { ask, tick, step, replay, settle, clear, whenGone };
}
