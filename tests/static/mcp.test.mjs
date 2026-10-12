import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl, jsonResponse, fetchScript } from "./helpers.mjs";

const { createMcpClient, MCP_VERSION } = await import(moduleUrl("app/mcp.js"));

test("the client negotiates once and sends the protocol header on every later call", async () => {
  const { fetcher, calls } = fetchScript({ "/mcp": (init) => {
    const message = JSON.parse(init.body);
    if (message.method === "initialize") return jsonResponse(200, { jsonrpc: "2.0", id: 0, result: { protocolVersion: "2025-11-25" } });
    if (message.method === "notifications/initialized") return { ok: true, status: 202, headers: { get: () => null }, json: async () => null };
    return jsonResponse(200, { jsonrpc: "2.0", id: 1, result: { tools: [{ name: message.method }] } });
  } });
  const client = createMcpClient({ fetch: fetcher, getToken: () => "tok" });
  const first = await client.request("tools/list", {});
  const second = await client.request("resources/read", { uri: "x" });
  assert.deepEqual(first, { tools: [{ name: "tools/list" }] });
  assert.deepEqual(second, { tools: [{ name: "resources/read" }] });
  assert.equal(calls.length, 4);
  assert.equal(MCP_VERSION, "2025-11-25");
  assert.equal(JSON.parse(calls[0].init.body).params.protocolVersion, "2025-11-25");
  assert.equal(calls[0].init.headers["MCP-Protocol-Version"], undefined);
  for (const call of calls.slice(1)) {
    assert.equal(call.init.headers["MCP-Protocol-Version"], "2025-11-25");
    assert.equal(call.init.headers.Authorization, "Bearer tok");
  }
});

test("a failed negotiation is retried next time and JSON-RPC errors become exceptions", async () => {
  let attempts = 0;
  const { fetcher } = fetchScript({ "/mcp": (init) => {
    const message = JSON.parse(init.body);
    if (message.method === "initialize") return ++attempts === 1 ? jsonResponse(503, {}) : jsonResponse(200, { result: { protocolVersion: "2025-11-25" } });
    if (message.method === "notifications/initialized") return { ok: true, status: 202, headers: { get: () => null }, json: async () => null };
    return jsonResponse(200, { error: { code: -32042, message: "A person must approve" } });
  } });
  const client = createMcpClient({ fetch: fetcher });
  await assert.rejects(client.request("tools/list", {}), /MCP HTTP 503/);
  await assert.rejects(client.request("tools/call", {}), /A person must approve/);
  assert.equal(attempts, 2);
});
