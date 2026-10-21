export const MCP_VERSION = "2025-11-25";

export function createMcpClient({ fetch: doFetch, getToken, clientInfo = { name: "LogiOps demo host", version: "1.0.0" }, mcpVersion = MCP_VERSION } = {}) {
  const fetcher = (...args) => (doFetch ?? globalThis.fetch)(...args);
  let negotiated = null;

  async function post(message, version) {
    const headers = { "Content-Type": "application/json", Accept: "application/json, text/event-stream" };
    const token = getToken ? getToken() : "";
    if (token) headers.Authorization = `Bearer ${token}`;
    if (version) headers["MCP-Protocol-Version"] = version;
    const response = await fetcher("/mcp", { method: "POST", headers, cache: "no-store", body: JSON.stringify({ jsonrpc: "2.0", ...message }) });
    if (!response.ok) throw Object.assign(new Error(`MCP HTTP ${response.status}`), { status: response.status });
    return response.status === 202 ? null : response.json();
  }

  function protocol() {
    negotiated ??= (async () => {
      const body = await post({ id: 0, method: "initialize", params: { protocolVersion: mcpVersion, capabilities: {}, clientInfo } });
      if (body.error) throw new Error(body.error.message || "MCP error");
      await post({ method: "notifications/initialized" }, body.result.protocolVersion);
      return body.result.protocolVersion;
    })().catch((error) => { negotiated = null; throw error; });
    return negotiated;
  }

  async function request(method, params) {
    const body = await post({ id: 1, method, params }, await protocol());
    if (body.error) throw new Error(body.error.message || "MCP error");
    return body.result;
  }

  async function callTool(name, args = {}) {
    const result = await request("tools/call", { name, arguments: args });
    if (result.isError) throw new Error(result.content?.find((item) => item.type === "text")?.text || `${name} failed`);
    return result.structuredContent;
  }

  return { request, protocol, callTool };
}
