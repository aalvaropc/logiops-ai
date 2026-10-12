import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");

export const moduleUrl = (name) => pathToFileURL(path.join(root, "logiops", "static", name)).href;

export function memoryStorage() {
  const items = new Map();
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => { items.set(key, String(value)); },
    removeItem: (key) => { items.delete(key); },
  };
}

export function jsonResponse(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300, status,
    headers: { get: (name) => headers[name.toLowerCase()] ?? null },
    json: async () => body,
  };
}

export function fetchScript(routes) {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    calls.push({ url, init });
    const handler = routes[url] ?? routes["*"];
    if (!handler) throw new Error(`unexpected fetch ${url}`);
    return typeof handler === "function" ? handler(init, calls.length) : handler;
  };
  return { fetcher, calls };
}

export function jwt(claims) {
  const part = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${part({ alg: "RS256" })}.${part(claims)}.sig`;
}
