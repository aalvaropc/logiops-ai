import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { createMcpAppHost, MCP_APPS_PROTOCOL } = await import(moduleUrl("app/mcp-host.js"));
const settled = () => new Promise((resolve) => setImmediate(resolve));
const SANDBOX = "http://localhost:8000";
const HOST = "http://127.0.0.1:8000";

function fakeWindow() {
  const listeners = new Set();
  const timers = [];
  const win = {
    addEventListener: (type, fn) => { if (type === "message") listeners.add(fn); },
    removeEventListener: (type, fn) => { listeners.delete(fn); },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    document: { createElement: (tag) => fakeFrame(tag) },
    dispatch: (event) => { for (const fn of [...listeners]) fn(event); },
    timers,
  };
  return win;
}

function fakeFrame(tag) {
  const sent = [];
  const frame = {
    tag, attributes: {}, style: {}, removed: false, sent,
    setAttribute(name, value) { this.attributes[name] = value; },
    remove() { this.removed = true; },
    contentWindow: { postMessage: (message, origin) => sent.push({ message, origin }) },
  };
  return frame;
}

function fakeSlot() {
  return { children: [], replaceChildren(...nodes) { this.children = nodes; } };
}

function fakeMcp({ uri = "ui://logiops/resolution-options.abc.html", mime = "text/html;profile=mcp-app" } = {}) {
  const calls = [];
  return {
    calls,
    async request(method, params) {
      calls.push({ method, params });
      if (method === "tools/list") return { tools: [{ name: "investigate_incident", _meta: { ui: { resourceUri: uri, invoking: "Calculating…", invoked: "Plans ready" } } }] };
      if (method === "resources/read") return { contents: [{ uri, mimeType: mime, text: "<!doctype html><p>view</p>", _meta: { ui: { prefersBorder: true, csp: { connectDomains: [] } } } }] };
      throw new Error(`unexpected ${method}`);
    },
  };
}

async function shown({ mcp = fakeMcp(), onMessage, hostContext } = {}) {
  const win = fakeWindow();
  const slot = fakeSlot();
  const hidden = [];
  const host = createMcpAppHost({
    window: win, sandboxOrigin: SANDBOX, hostOrigin: HOST, slot, mcp, uriPrefix: "ui://logiops/resolution-options",
    hostInfo: { name: "test host", version: "1" }, hostContext: hostContext ?? (() => ({ theme: "dark" })),
    onMessage: onMessage ?? (() => true), onHide: (reason) => hidden.push(reason), frameTitle: "Resolution options (MCP App)",
  });
  const result = { content: [], structuredContent: { plans: [] }, _meta: { "logiops/recommended_plan_id": "p1" } };
  const resource = await host.show({ toolName: "investigate_incident", input: { shipment_id: "SHIP-421" }, result });
  const frame = slot.children[0];
  const fromView = (data, origin = SANDBOX) => win.dispatch({ source: frame.contentWindow, origin, data });
  return { win, slot, host, hidden, resource, frame, fromView, mcp, result };
}

test("the resource is read once over MCP and the view loads through the sandbox proxy", async () => {
  const { resource, frame, mcp, host } = await shown();
  assert.equal(resource.uri, "ui://logiops/resolution-options.abc.html");
  assert.equal(resource.invoked, "Plans ready");
  assert.deepEqual(mcp.calls.map((call) => call.method), ["tools/list", "resources/read"]);
  assert.equal(frame.tag, "iframe");
  assert.equal(frame.attributes.sandbox, "allow-scripts allow-same-origin");
  assert.equal(frame.attributes.referrerpolicy, "no-referrer");
  assert.equal(frame.src, `${SANDBOX}/mcp-app/sandbox.html?host=${encodeURIComponent(HOST)}`);
  assert.equal(frame.title, "Resolution options (MCP App)");
  assert.equal(await host.loadResource("investigate_incident"), resource, "cached");
  assert.equal(mcp.calls.length, 2);
});

test("a view that is not an MCP App, or a stale request, is not shown", async () => {
  const win = fakeWindow();
  const slot = fakeSlot();
  const host = createMcpAppHost({ window: win, sandboxOrigin: SANDBOX, hostOrigin: HOST, slot, mcp: fakeMcp({ mime: "text/html" }), uriPrefix: "ui://logiops" });
  assert.equal(await host.show({ toolName: "investigate_incident", input: {}, result: {} }), null);
  assert.equal(slot.children.length, 0);
  const other = createMcpAppHost({ window: win, sandboxOrigin: SANDBOX, hostOrigin: HOST, slot, mcp: fakeMcp(), uriPrefix: "ui://logiops" });
  assert.equal(await other.show({ toolName: "investigate_incident", input: {}, result: {}, stillWanted: () => false }), null);
  const none = createMcpAppHost({ window: win, sandboxOrigin: null, hostOrigin: HOST, slot, mcp: fakeMcp() });
  assert.equal(await none.show({ toolName: "investigate_incident", input: {}, result: {} }), null);
});

test("the handshake answers initialize with the host context and then sends the tool input and result", async () => {
  const { frame, fromView, result } = await shown({ hostContext: () => ({ theme: "light", deviceClass: "compact" }) });
  fromView({ jsonrpc: "2.0", method: "ui/notifications/sandbox-proxy-ready" });
  assert.deepEqual(frame.sent[0], { message: { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html: "<!doctype html><p>view</p>", csp: { connectDomains: [] } } }, origin: SANDBOX });
  fromView({ jsonrpc: "2.0", id: 1, method: "ui/initialize", params: { protocolVersion: "2026-01-26" } });
  assert.deepEqual(frame.sent[1].message, { jsonrpc: "2.0", id: 1, result: { protocolVersion: MCP_APPS_PROTOCOL, hostInfo: { name: "test host", version: "1" }, hostCapabilities: {}, hostContext: { theme: "light", deviceClass: "compact" } } });
  fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  assert.deepEqual(frame.sent[2].message, { jsonrpc: "2.0", method: "ui/notifications/tool-input", params: { arguments: { shipment_id: "SHIP-421" } } });
  assert.deepEqual(frame.sent[3].message, { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: result });
});

test("messages from another origin or window are ignored and unknown methods get -32601", async () => {
  const { frame, fromView, win } = await shown();
  fromView({ jsonrpc: "2.0", id: 1, method: "ui/initialize" }, "https://evil.example.com");
  win.dispatch({ source: {}, origin: SANDBOX, data: { jsonrpc: "2.0", id: 2, method: "ui/initialize" } });
  fromView({ jsonrpc: "1.0", id: 3, method: "ui/initialize" });
  assert.equal(frame.sent.length, 0);
  fromView({ jsonrpc: "2.0", id: 4, method: "ui/open-link", params: {} });
  assert.deepEqual(frame.sent[0].message, { jsonrpc: "2.0", id: 4, error: { code: -32601, message: "Method not supported by this host" } });
});

test("size changes are clamped and ui/message goes to the host's handler", async () => {
  const seen = [];
  const { frame, fromView } = await shown({ onMessage: (params) => { seen.push(params); return params.content.text === "Select plan p1"; } });
  fromView({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: 20 } });
  assert.equal(frame.style.height, "80px");
  fromView({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: 9000 } });
  assert.equal(frame.style.height, "640px");
  fromView({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: 300 } });
  assert.equal(frame.style.height, "300px");
  fromView({ jsonrpc: "2.0", id: 7, method: "ui/message", params: { role: "user", content: { type: "text", text: "Select plan p1" } } });
  fromView({ jsonrpc: "2.0", id: 8, method: "ui/message", params: { role: "user", content: { type: "text", text: "Select plan nope" } } });
  await settled();
  assert.deepEqual(frame.sent.map((item) => item.message), [
    { jsonrpc: "2.0", id: 7, result: {} },
    { jsonrpc: "2.0", id: 8, error: { code: -32000, message: "The host did not accept the message" } },
  ]);
  assert.equal(seen.length, 2);
});

test("ui/message may be answered later; a failing handler is a refusal, and an answer for a replaced view is dropped", async () => {
  const waiting = [];
  const asked = (id, text) => ({ jsonrpc: "2.0", id, method: "ui/message", params: { role: "user", content: { type: "text", text } } });
  const { frame, fromView, host, slot } = await shown({
    onMessage: (params) => {
      const { text } = params.content;
      if (text === "later") return new Promise((resolve) => waiting.push(resolve));
      if (text === "boom") throw new Error("handler failed");
      return Promise.resolve(text === "yes");
    },
  });
  fromView(asked(1, "yes"));
  fromView(asked(2, "boom"));
  fromView(asked(3, "no"));
  await settled();
  const refused = { code: -32000, message: "The host did not accept the message" };
  assert.deepEqual(frame.sent.map((item) => item.message).sort((a, b) => a.id - b.id), [
    { jsonrpc: "2.0", id: 1, result: {} },
    { jsonrpc: "2.0", id: 2, error: refused },
    { jsonrpc: "2.0", id: 3, error: refused },
  ]);
  fromView(asked(4, "later"));
  await settled();
  assert.equal(frame.sent.length, 3, "nothing is said before the handler decides");
  waiting.shift()(true);
  await settled();
  assert.deepEqual(frame.sent.at(-1).message, { jsonrpc: "2.0", id: 4, result: {} });
  fromView(asked(5, "later"));
  await host.show({ toolName: "investigate_incident", input: {}, result: {} });
  const next = slot.children[0];
  assert.notEqual(next, frame);
  waiting.shift()(true);
  await settled();
  assert.equal(frame.sent.length, 4);
  assert.equal(next.sent.length, 0, "the new view never gets the old view's answer");
});

test("host context changes reach only an initialized view", async () => {
  const { frame, fromView, host } = await shown({ hostContext: () => ({ theme: "dark" }) });
  host.notifyContext();
  assert.equal(frame.sent.length, 0);
  fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  host.notifyContext();
  assert.deepEqual(frame.sent.at(-1).message, { jsonrpc: "2.0", method: "ui/notifications/host-context-changed", params: { theme: "dark" } });
});

test("teardown asks an initialized view first and removes the frame on its reply or after the timeout", async () => {
  const { frame, fromView, host, hidden, win } = await shown();
  fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  const hiding = host.hide("incident changed");
  const request = frame.sent.at(-1).message;
  assert.equal(request.method, "ui/resource-teardown");
  assert.deepEqual(request.params, { reason: "incident changed" });
  assert.equal(frame.removed, false);
  fromView({ jsonrpc: "2.0", id: request.id, result: {} });
  await hiding;
  assert.equal(frame.removed, true);
  assert.deepEqual(hidden, ["incident changed"]);
  assert.equal(host.isShowing(), false);
  const again = await shown();
  const second = again.host.hide("quick");
  await second;
  assert.equal(again.frame.removed, true, "a view that never initialized is removed at once");
  const third = await shown();
  third.fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  const slow = third.host.hide("timeout");
  third.win.timers.at(-1).fn();
  await slow;
  assert.equal(third.frame.removed, true);
  assert.equal(win.timers.length, 1);
});

test("a view that navigates away is torn down", async () => {
  const { fromView, host, hidden } = await shown();
  fromView({ jsonrpc: "2.0", method: "ui/notifications/sandbox-view-removed" });
  assert.equal(host.isShowing(), false);
  assert.deepEqual(hidden, ["view navigated"]);
});
