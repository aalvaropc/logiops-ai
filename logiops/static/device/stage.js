import { el, stepLabel } from "./render.js";

const CADENCE_MS = 120;
const HOLD_MS = 1500;
const LEAVE_MS = 360;

export function createStage({ root, surface, document: doc = globalThis.document, reducedMotion = () => false }) {
  const line = root.querySelector(".agent-ask");
  const stations = root.querySelector(".agent-stations");
  const meta = root.querySelector(".agent-meta");
  let timers = [];

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
    reset();
    root.style.top = `${surface.offsetTop}px`;
    root.style.height = `${surface.offsetHeight}px`;
    line.replaceChildren(subject ? `${lead} ` : lead);
    if (subject) line.append(el("strong", "", subject, doc));
    stations.replaceChildren();
    meta.textContent = "0 s";
    root.classList.remove("leaving");
    root.dataset.phase = "asking";
    root.hidden = false;
  }

  function tick(seconds) {
    if (root.dataset.phase === "asking") meta.textContent = `${seconds} s`;
  }

  function clear() {
    reset();
    root.hidden = true;
    root.classList.remove("leaving");
    root.dataset.phase = "";
  }

  function leave() {
    root.classList.add("leaving");
    later(clear, reducedMotion() ? 0 : LEAVE_MS);
  }

  function replay(run, check, caption) {
    if (root.hidden) return;
    reset();
    const steps = run.tool_trace || [];
    if (!steps.length) {
      clear();
      return;
    }
    stations.replaceChildren(...steps.map((step, index) => station(stepLabel(step), step.is_error ? "error" : "", index)));
    if (check) stations.append(station(check.text, check.passed ? "check" : "check failed", steps.length));
    meta.textContent = caption;
    meta.style.setProperty("--step", String(stations.children.length));
    root.dataset.phase = "replay";
    later(leave, (reducedMotion() ? 0 : stations.children.length * CADENCE_MS) + HOLD_MS);
  }

  function settle() {
    later(() => {
      if (root.dataset.phase === "asking") clear();
    }, 0);
  }

  return { ask, tick, replay, settle, clear };
}
