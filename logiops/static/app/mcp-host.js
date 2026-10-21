export const MCP_APPS_PROTOCOL = "2026-01-26";
export const MCP_APP_MIME = "text/html;profile=mcp-app";

export function createMcpAppHost({
  window: win = globalThis.window, sandboxOrigin, hostOrigin, proxyPath = "/mcp-app/sandbox.html", slot, mcp,
  uriPrefix = "ui://", mime = MCP_APP_MIME, protocol = MCP_APPS_PROTOCOL, hostInfo = { name: "MCP Apps web host", version: "1.1.0" },
  hostContext = () => ({}), onMessage = () => false, onHide = () => {}, frameTitle = "MCP App", frameId = "mcp-app-frame",
  minHeight = 80, maxHeight = 640, teardownTimeout = 500, readyTimeout = 5000,
  onReady = () => {}, onError = () => {}, rejectMessage = "The host did not accept the message",
} = {}) {
  const doc = win.document;
  const resources = new Map();
  let generation = 0;
  let nextId = 1;
  let current = null;

  async function loadResource(toolName) {
    if (!resources.has(toolName)) {
      const lookup = { declaresNoView: false };
      resources.set(toolName, (async () => {
        let tool;
        let cursor;
        const cursors = new Set();
        do {
          const listed = await mcp.request("tools/list", cursor === undefined ? {} : { cursor });
          tool = listed.tools.find((item) => item.name === toolName);
          cursor = listed.nextCursor;
          if (tool || cursor === undefined || cursor === null || cursor === "") break;
          if (typeof cursor !== "string" || cursors.has(cursor)) throw new Error("Invalid or repeated tools/list cursor");
          cursors.add(cursor);
        } while (true);
        const uri = tool?._meta?.ui?.resourceUri ?? tool?._meta?.["ui/resourceUri"];
        if (typeof uri !== "string" || !uri.startsWith(uriPrefix)) {
          lookup.declaresNoView = Boolean(tool);
          return null;
        }
        const read = await mcp.request("resources/read", { uri });
        const content = read.contents?.[0];
        if (!content || content.mimeType !== mime || typeof content.text !== "string") return null;
        const ui = content._meta?.ui || {};
        return { uri, html: content.text, csp: ui.csp || {}, prefersBorder: ui.prefersBorder !== false, invoking: tool._meta.ui?.invoking || "", invoked: tool._meta.ui?.invoked || "" };
      })().then((resource) => {
        if (!resource && !lookup.declaresNoView) resources.delete(toolName);
        return resource;
      }).catch((error) => { resources.delete(toolName); throw error; }));
    }
    return resources.get(toolName);
  }

  function frame() {
    return current?.frame || null;
  }

  function post(payload) {
    const target = frame();
    if (target?.contentWindow) target.contentWindow.postMessage({ jsonrpc: "2.0", ...payload }, sandboxOrigin);
  }

  function teardown(reason, { invalidate = true, notify = true } = {}) {
    const view = current;
    current = null;
    if (view) win.clearTimeout(view.readyTimer);
    if (invalidate) generation += 1;
    if (notify) onHide(reason);
    if (!view) return Promise.resolve();
    return new Promise((resolve) => {
      let finished = false;
      let timer;
      const id = `teardown-${nextId++}`;
      const finish = () => {
        if (finished) return;
        finished = true;
        win.clearTimeout(timer);
        win.removeEventListener("message", onReply);
        view.frame.remove();
        resolve();
      };
      const onReply = (event) => {
        if (event.source === view.frame.contentWindow && event.origin === sandboxOrigin && event.data?.id === id) finish();
      };
      if (!view.ready) return finish();
      win.addEventListener("message", onReply);
      view.frame.contentWindow.postMessage({ jsonrpc: "2.0", id, method: "ui/resource-teardown", params: { reason } }, sandboxOrigin);
      timer = win.setTimeout(finish, teardownTimeout);
    });
  }

  async function show({ toolName, input, result, stillWanted = () => true }) {
    if (!sandboxOrigin) return null;
    const mine = ++generation;
    const resource = await loadResource(toolName);
    if (!resource || mine !== generation || !stillWanted()) return null;
    await teardown("replaced", { invalidate: false, notify: Boolean(current) });
    if (mine !== generation) return null;
    const element = doc.createElement("iframe");
    element.id = frameId;
    element.title = frameTitle;
    element.setAttribute("sandbox", "allow-scripts allow-same-origin");
    element.setAttribute("referrerpolicy", "no-referrer");
    element.src = `${sandboxOrigin}${proxyPath}?host=${encodeURIComponent(hostOrigin)}`;
    const view = { frame: element, input, result, resource, ready: false, readyTimer: null };
    current = view;
    const fail = (error) => {
      if (current !== view || view.ready) return;
      teardown("initialization failed", { invalidate: false });
      onError(error);
    };
    const arm = () => {
      win.clearTimeout(view.readyTimer);
      if (Number.isFinite(readyTimeout) && readyTimeout > 0) view.readyTimer = win.setTimeout(() => fail(new Error("MCP App initialization timed out")), readyTimeout);
    };
    let loaded = false;
    element.onerror = () => fail(new Error("MCP App sandbox failed to load"));
    element.onload = () => {
      if (loaded || current !== view || view.ready) return;
      loaded = true;
      arm();
    };
    arm();
    slot.replaceChildren(element);
    return resource;
  }

  function notifyContext() {
    if (!current?.ready) return;
    post({ method: "ui/notifications/host-context-changed", params: hostContext() });
  }

  function onWindowMessage(event) {
    const target = frame();
    if (!current || !target || event.source !== target.contentWindow || event.origin !== sandboxOrigin) return;
    const msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0" || typeof msg.method !== "string") return;
    const reply = (payload) => { if (msg.id !== undefined) post({ id: msg.id, ...payload }); };
    if (msg.method === "ui/notifications/sandbox-proxy-ready") {
      post({ method: "ui/notifications/sandbox-resource-ready", params: { html: current.resource.html, csp: current.resource.csp } });
    } else if (msg.method === "ui/notifications/sandbox-view-removed") {
      teardown("view navigated");
    } else if (msg.method === "ui/initialize") {
      reply({ result: { protocolVersion: protocol, hostInfo, hostCapabilities: {}, hostContext: hostContext() } });
    } else if (msg.method === "ui/notifications/initialized") {
      if (current.ready) return;
      current.ready = true;
      win.clearTimeout(current.readyTimer);
      post({ method: "ui/notifications/tool-input", params: { arguments: current.input } });
      post({ method: "ui/notifications/tool-result", params: current.result });
      onReady(current.resource);
    } else if (msg.method === "ui/notifications/size-changed") {
      const height = Number(msg.params?.height);
      if (Number.isFinite(height)) target.style.height = `${Math.min(Math.max(height, minHeight), maxHeight)}px`;
    } else if (msg.method === "ui/message") {
      const view = current;
      Promise.resolve().then(() => onMessage(msg.params)).catch(() => false).then((accepted) => {
        if (current === view) reply(accepted ? { result: {} } : { error: { code: -32000, message: rejectMessage } });
      });
    } else {
      reply({ error: { code: -32601, message: "Method not supported by this host" } });
    }
  }

  win.addEventListener("message", onWindowMessage);

  return {
    loadResource, show, hide: (reason = "hidden") => teardown(reason), notifyContext,
    isShowing: () => Boolean(current), ready: () => Boolean(current?.ready),
    destroy: () => { win.removeEventListener("message", onWindowMessage); return teardown("destroyed"); },
  };
}
