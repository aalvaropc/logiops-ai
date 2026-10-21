import { test } from "node:test";
import assert from "node:assert/strict";
import { createMcpAppHost, MCP_APPS_PROTOCOL } from "../../logiops/static/app/mcp-host.js";

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
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].cancelled = true; },
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

async function shown({ mcp = fakeMcp(), onMessage, hostContext, onReady, onError, readyTimeout } = {}) {
  const win = fakeWindow();
  const slot = fakeSlot();
  const hidden = [];
  const host = createMcpAppHost({
    window: win, sandboxOrigin: SANDBOX, hostOrigin: HOST, slot, mcp, uriPrefix: "ui://logiops/resolution-options",
    hostInfo: { name: "test host", version: "1" }, hostContext: hostContext ?? (() => ({ theme: "dark" })),
    onMessage: onMessage ?? (() => true), onHide: (reason) => hidden.push(reason), frameTitle: "Resolution options (MCP App)",
    onReady, onError, readyTimeout,
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
  assert.equal(win.timers.filter((timer) => !timer.cancelled).length, 0);
});

test("readiness is reported once after tool input and result are delivered", async () => {
  const ready = [];
  const view = await shown({ onReady: (resource) => ready.push(resource) });
  assert.equal(view.host.ready(), false);
  assert.deepEqual(ready, []);
  assert.equal(view.win.timers[0].ms, 5000);
  view.fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  view.fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  assert.deepEqual(ready, [view.resource]);
  assert.equal(view.frame.sent.length, 2);
  assert.equal(view.host.ready(), true);
  assert.equal(view.win.timers[0].cancelled, true);
});

test("an unresponsive sandbox is removed and reports a timeout", async () => {
  const errors = [];
  const view = await shown({ readyTimeout: 123, onError: (error) => errors.push(error) });
  assert.equal(view.win.timers[0].ms, 123);
  view.win.timers[0].fn();
  assert.equal(errors.length, 1);
  assert.match(errors[0].message, /initializ/i);
  assert.equal(view.host.isShowing(), false);
  assert.equal(view.frame.removed, true);
  view.fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  assert.equal(view.host.ready(), false);
});

test("hiding, replacing and destroying views cancels pending readiness callbacks", async () => {
  const errors = [];
  const view = await shown({ onError: (error) => errors.push(error) });
  const first = view.win.timers[0];
  await view.host.show({ toolName: "investigate_incident", input: {}, result: {} });
  assert.equal(first.cancelled, true);
  first.fn();
  assert.deepEqual(errors, []);
  await view.host.hide();
  assert.equal(view.win.timers[1].cancelled, true);
  await view.host.show({ toolName: "investigate_incident", input: {}, result: {} });
  await view.host.destroy();
  assert.equal(view.win.timers[2].cancelled, true);
  view.win.timers[2].fn();
  assert.deepEqual(errors, []);
});

test("iframe load errors report failure and remove the pending view", async () => {
  const errors = [];
  const view = await shown({ onError: (error) => errors.push(error) });
  view.frame.onerror();
  assert.equal(errors.length, 1);
  assert.equal(view.frame.removed, true);
  assert.equal(view.win.timers[0].cancelled, true);
});

test("tools on later pages are discovered and cursor cycles are rejected", async () => {
  const backing = fakeMcp();
  const cursors = [];
  const mcp = { request: async (method, params) => {
    if (method !== "tools/list") return backing.request(method, params);
    cursors.push(params.cursor);
    return params.cursor ? backing.request(method, params) : { tools: [], nextCursor: "second" };
  } };
  const view = await shown({ mcp });
  assert.ok(view.resource);
  assert.deepEqual(cursors, [undefined, "second"]);
  const looping = { request: async () => ({ tools: [], nextCursor: "again" }) };
  await assert.rejects(shown({ mcp: looping }), /cursor/i);
});

test("a null or empty nextCursor ends the listing", async () => {
  for (const nextCursor of [null, ""]) {
    const requests = [];
    const mcp = { request: async (method, params) => { requests.push(params); return { tools: [], nextCursor }; } };
    const host = createMcpAppHost({ window: fakeWindow(), sandboxOrigin: SANDBOX, hostOrigin: HOST, slot: fakeSlot(), mcp });
    assert.equal(await host.loadResource("investigate_incident"), null);
    assert.equal(requests.length, 1);
  }
  const numeric = { request: async () => ({ tools: [], nextCursor: 7 }) };
  const host = createMcpAppHost({ window: fakeWindow(), sandboxOrigin: SANDBOX, hostOrigin: HOST, slot: fakeSlot(), mcp: numeric });
  await assert.rejects(host.loadResource("investigate_incident"), /cursor/i);
});

test("the readiness budget restarts when the sandbox page has loaded, and only once", async () => {
  const errors = [];
  const view = await shown({ readyTimeout: 200, onError: (error) => errors.push(error) });
  const [mounted] = view.win.timers;
  assert.equal(mounted.ms, 200);
  view.frame.onload();
  assert.equal(mounted.cancelled, true);
  const [, loaded] = view.win.timers;
  assert.equal(loaded.ms, 200);
  view.frame.onload();
  assert.equal(view.win.timers.length, 2, "a second load does not extend the budget");
  loaded.fn();
  assert.equal(errors.length, 1);
  assert.match(errors[0].message, /timed out/);
});

test("a view that initializes after its sandbox loaded slowly is still reported ready", async () => {
  const ready = [];
  const errors = [];
  const view = await shown({ onReady: (resource) => ready.push(resource), onError: (error) => errors.push(error) });
  view.frame.onload();
  view.fromView({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  assert.equal(ready.length, 1);
  assert.equal(view.win.timers[1].cancelled, true);
  view.frame.onload();
  assert.equal(view.win.timers.length, 2, "a load after initialization arms nothing");
  assert.deepEqual(errors, []);
});

test("a readyTimeout of zero or Infinity never arms a timer", async () => {
  for (const readyTimeout of [0, Infinity]) {
    const errors = [];
    const view = await shown({ readyTimeout, onError: (error) => errors.push(error) });
    view.frame.onload();
    assert.equal(view.win.timers.length, 0);
    assert.equal(view.host.isShowing(), true);
    assert.deepEqual(errors, []);
  }
});

test("a timeout of the old view does not cancel a newer show that is still loading", async () => {
  const view = (name) => ({ name, _meta: { ui: { resourceUri: `ui://logiops/resolution-options.${name}.html` } } });
  let gate = null;
  const mcp = { request: async (method, params) => {
    if (method === "tools/list") {
      if (gate) await gate;
      return { tools: [view("first"), view("second")] };
    }
    return { contents: [{ uri: params.uri, mimeType: "text/html;profile=mcp-app", text: `<p>${params.uri}</p>` }] };
  } };
  const win = fakeWindow();
  const slot = fakeSlot();
  const errors = [];
  const host = createMcpAppHost({ window: win, sandboxOrigin: SANDBOX, hostOrigin: HOST, slot, mcp, uriPrefix: "ui://logiops/resolution-options", onError: (error) => errors.push(error) });
  await host.show({ toolName: "first", input: {}, result: {} });
  const [stale] = slot.children;
  let release;
  gate = new Promise((resolve) => { release = resolve; });
  const second = host.show({ toolName: "second", input: {}, result: {} });
  win.timers[0].fn();
  assert.equal(errors.length, 1);
  assert.equal(stale.removed, true);
  release();
  assert.match((await second).uri, /second/);
  assert.notEqual(slot.children[0], stale);
  assert.equal(host.isShowing(), true);
});

test("a tool that declares no view is not listed again, while a missing tool is", async () => {
  let listings = 0;
  const mcp = { request: async (method) => {
    if (method !== "tools/list") throw new Error(`unexpected ${method}`);
    listings += 1;
    return { tools: [{ name: "plain", _meta: {} }] };
  } };
  const host = createMcpAppHost({ window: fakeWindow(), sandboxOrigin: SANDBOX, hostOrigin: HOST, slot: fakeSlot(), mcp });
  assert.equal(await host.loadResource("plain"), null);
  assert.equal(await host.loadResource("plain"), null);
  assert.equal(listings, 1);
  assert.equal(await host.loadResource("absent"), null);
  assert.equal(await host.loadResource("absent"), null);
  assert.equal(listings, 3);
});

test("a missing or temporarily invalid resource is retried on the next request", async () => {
  const backing = fakeMcp();
  let available = false;
  const mcp = { request: async (method, params) => {
    if (method === "tools/list" && !available) return { tools: [] };
    return backing.request(method, params);
  } };
  const view = await shown({ mcp });
  assert.equal(view.resource, null);
  available = true;
  assert.ok(await view.host.loadResource("investigate_incident"));
  let correct = false;
  const invalid = { request: async (method, params) => {
    if (method === "resources/read" && !correct) return { contents: [] };
    return backing.request(method, params);
  } };
  const other = await shown({ mcp: invalid });
  assert.equal(other.resource, null);
  correct = true;
  assert.ok(await other.host.loadResource("investigate_incident"));
});

test("a view that navigates away is torn down", async () => {
  const { fromView, host, hidden } = await shown();
  fromView({ jsonrpc: "2.0", method: "ui/notifications/sandbox-view-removed" });
  assert.equal(host.isShowing(), false);
  assert.deepEqual(hidden, ["view navigated"]);
});
