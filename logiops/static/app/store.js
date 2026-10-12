export function createStore(initial = {}) {
  const state = { ...initial };
  const listeners = new Set();

  function get() {
    return state;
  }

  function set(patch) {
    const previous = { ...state };
    const next = typeof patch === "function" ? patch(state) : patch;
    if (!next || typeof next !== "object") return state;
    Object.assign(state, next);
    for (const entry of [...listeners]) {
      const before = entry.selector(previous);
      const after = entry.selector(state);
      if (!Object.is(before, after)) entry.listener(after, before, state);
    }
    return state;
  }

  function subscribe(listener, selector = (value) => value) {
    const entry = { listener, selector };
    listeners.add(entry);
    return () => { listeners.delete(entry); };
  }

  return { state, get, set, subscribe };
}
