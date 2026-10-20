import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { createStage } = await import(moduleUrl("device/stage.js"));

function fakeNode(tag = "div") {
  const classes = new Set();
  const node = {
    tag, className: "", textContent: "", hidden: true, inert: false, dataset: {}, children: [],
    style: { props: {}, setProperty(name, value) { this.props[name] = value; } },
    classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name), contains: (name) => classes.has(name) },
    append(...nodes) { for (const item of nodes) this.children.push(typeof item === "string" ? { textContent: item } : item); },
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); },
  };
  return node;
}

function staged(t, { reduced = false } = {}) {
  let clock = 1000;
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(performance, "now", () => clock);
  const parts = { ".agent-ask": fakeNode("p"), ".agent-stations": fakeNode("ol"), ".agent-meta": fakeNode("p") };
  const root = Object.assign(fakeNode(), { querySelector: (selector) => parts[selector] });
  const quiet = [fakeNode(), fakeNode()];
  const stage = createStage({
    root, surface: { offsetTop: 12, offsetHeight: 300 }, quiet, reducedMotion: () => reduced,
    document: { createElement: (tag) => fakeNode(tag) },
  });
  const advance = (ms) => { clock += ms; t.mock.timers.tick(ms); };
  const labels = () => parts[".agent-stations"].children.map((item) => item.textContent);
  return { stage, root, quiet, advance, labels, line: parts[".agent-ask"], meta: parts[".agent-meta"] };
}

const shipment = { tool: "get_shipment", input: { shipment_id: "SHIP-433" }, output: {} };
const order = { tool: "get_order", input: { order_id: "ORD-433-H" }, output: {} };
const quotes = { tool: "find_alternative_carriers", input: { shipment_id: "SHIP-433" }, output: { air: {}, road: {} } };
const run = { tool_trace: [shipment, order, quotes] };
const check = { text: "Checked against the data", passed: true };
const caption = (live) => (live ? "Live from the MCP tool calls" : "Replayed from a recorded run");

test("asking shows the question over the surface and quiets the controls", (t) => {
  const { stage, root, quiet, line, meta } = staged(t);
  stage.ask(["Asking the agent about", "SHIP-433"]);
  assert.equal(root.hidden, false);
  assert.equal(root.dataset.phase, "asking");
  assert.deepEqual([root.style.top, root.style.height], ["12px", "300px"]);
  assert.deepEqual(line.children.map((item) => [item.tag, item.textContent]), [[undefined, "Asking the agent about "], ["strong", "SHIP-433"]]);
  assert.deepEqual(quiet.map((node) => node.inert), [true, true]);
  stage.tick(4);
  assert.equal(meta.textContent, "4 s");
});

test("live steps arrive one per beat, however fast they come", (t) => {
  const { stage, advance, labels } = staged(t);
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.step(shipment);
  stage.step(order);
  stage.step(quotes);
  advance(0);
  assert.deepEqual(labels(), ["Shipment · SHIP-433"]);
  advance(119);
  assert.equal(labels().length, 1);
  advance(1);
  assert.equal(labels().length, 2);
  advance(120);
  assert.deepEqual(labels(), ["Shipment · SHIP-433", "Order · ORD-433-H", "Carrier quotes · 2 quotes"]);
});

test("a recorded run is laid out at once, held, and then lets the reply out", (t) => {
  const { stage, root, quiet, advance, labels, meta } = staged(t);
  const replies = [];
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.replay(run, check, caption);
  stage.whenGone(() => replies.push(root.hidden));
  assert.equal(root.dataset.phase, "replay");
  assert.equal(labels().at(-1), "Checked against the data");
  assert.equal(meta.textContent, "Replayed from a recorded run");
  assert.equal(meta.style.props["--step"], "4");
  advance(4 * 120 + 1500 - 1);
  assert.equal(root.classList.contains("leaving"), false);
  advance(1);
  assert.equal(root.classList.contains("leaving"), true);
  assert.deepEqual(replies, []);
  advance(360);
  assert.equal(root.hidden, true);
  assert.deepEqual(replies, [true]);
  assert.deepEqual(quiet.map((node) => node.inert), [false, false]);
});

test("a streamed run adds what the stream missed and the check after the last live step", (t) => {
  const { stage, root, advance, labels, meta } = staged(t);
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.step(shipment);
  advance(0);
  stage.replay(run, { text: "One figure did not match", passed: false }, caption);
  assert.equal(meta.textContent, "Live from the MCP tool calls");
  advance(120);
  assert.equal(labels().length, 2);
  advance(120);
  assert.equal(labels().length, 3);
  advance(120);
  assert.deepEqual(labels(), ["Shipment · SHIP-433", "Order · ORD-433-H", "Carrier quotes · 2 quotes", "One figure did not match"]);
  advance(1500 - 1);
  assert.equal(root.classList.contains("leaving"), false);
  advance(1);
  assert.equal(root.classList.contains("leaving"), true);
  advance(360);
  assert.equal(root.hidden, true);
});

test("with reduced motion the stage does not hold the answer", (t) => {
  const { stage, root, advance } = staged(t, { reduced: true });
  const replies = [];
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.replay(run, check, caption);
  stage.whenGone(() => replies.push("reply"));
  advance(0);
  advance(0);
  assert.equal(root.hidden, true);
  assert.deepEqual(replies, ["reply"]);
});

test("a run without tool calls, or a stage already gone, lets the reply out at once", (t) => {
  const { stage, root, advance } = staged(t);
  const replies = [];
  stage.whenGone(() => replies.push("before"));
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.whenGone(() => replies.push("empty"));
  stage.replay({ tool_trace: [] }, check, caption);
  assert.equal(root.hidden, true);
  assert.deepEqual(replies, ["before", "empty"]);
  stage.replay(run, check, caption);
  stage.step(shipment);
  advance(5000);
  assert.equal(root.hidden, true, "a hidden stage ignores late steps and replays");
});

test("a new question during the hold lets the held reply out first", (t) => {
  const { stage, root, advance, labels } = staged(t);
  const replies = [];
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.replay(run, check, caption);
  stage.whenGone(() => replies.push(root.hidden));
  advance(600);
  stage.ask(["Asking the agent about", "SHIP-421"]);
  assert.deepEqual(replies, [true]);
  assert.equal(root.hidden, false);
  assert.equal(root.dataset.phase, "asking");
  assert.deepEqual(labels(), []);
  advance(5000);
  assert.equal(root.hidden, false, "the first question's leave was cancelled");
});

test("settle closes a stage that never got a trace, but not one holding a replay", (t) => {
  const { stage, root, advance } = staged(t);
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.settle();
  advance(0);
  assert.equal(root.hidden, true);
  stage.ask(["Asking the agent about", "SHIP-433"]);
  stage.replay(run, check, caption);
  stage.settle();
  advance(0);
  assert.equal(root.dataset.phase, "replay");
  assert.equal(root.hidden, false);
});
