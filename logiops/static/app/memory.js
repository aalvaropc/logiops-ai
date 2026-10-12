export const MEMORY_SESSION_KEY = "logiops-memory-session";

export function createMemory({ storage, fetch: doFetch, request, randomText, credentials = () => ({}), incident = () => null } = {}) {
  const fetcher = (...args) => (doFetch ?? globalThis.fetch)(...args);

  function session() {
    let id = storage.get(MEMORY_SESSION_KEY);
    if (!id) {
      id = `s-${randomText(12)}`;
      storage.set(MEMORY_SESSION_KEY, id);
      if (storage.get(MEMORY_SESSION_KEY) !== id) return null;
    }
    return id;
  }

  function allowed() {
    const { auth, session: signedIn } = credentials();
    return !(auth?.enabled && !signedIn);
  }

  function remember(role, text) {
    const id = session();
    if (!id || !allowed()) return false;
    const headers = { "Content-Type": "application/json" };
    const token = credentials().token;
    if (token) headers.Authorization = `Bearer ${token}`;
    fetcher("/memory/turns", {
      method: "POST", headers, cache: "no-store",
      body: JSON.stringify({ session: id, role, text: String(text).slice(0, 4000), incident: incident() }),
    }).catch(() => {});
    return true;
  }

  async function recall() {
    if (!allowed()) return null;
    try {
      return await request(`/memory?session=${encodeURIComponent(session() || "")}`);
    } catch (_) {
      return null;
    }
  }

  return { session, remember, recall };
}
