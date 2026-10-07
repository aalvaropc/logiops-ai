// The demo's thin command layer, kept free of the DOM so it can be tested with node.
// A command is the whole utterance: an optional opener, then the verb. Anything else,
// including a question, a negation, or a command buried in a longer sentence, goes to
// the agent as a question and never acts.
(function (root) {
  const QUESTION = /\?\s*$|^(how|what|why|when|which|who|should|can|could|would|will|is|are|do|does|did|if)\b/;
  const OPENER = String.raw`^(?:(?:ok(?:ay)?|alexa|please|now|alright|great|sure|then|and)[,.!]?\s+)*`;
  const NEGATION = /\b(?:no|not|never|stop|cancel|don'?t|doesn'?t|won'?t|shouldn'?t|hold off|wait until|before|unless|instead)\b|n't\b/;
  const COMMANDS = [
    ["reset", new RegExp(`${OPENER}(?:reset|start over)\\b`)],
    ["approve", new RegExp(`${OPENER}approve\\b`)],
    ["execute", new RegExp(`${OPENER}(?:execute|go ahead|do it|run it)\\b`)],
    ["confirm", /^(?:yes|yeah|yep)\b/],
  ];

  function isQuestion(text) {
    return QUESTION.test(String(text).trim().toLowerCase());
  }

  // "reset" | "approve" | "execute" | "confirm" (a bare yes) | null.
  function parseCommand(text) {
    const lower = String(text).trim().toLowerCase();
    if (!lower || QUESTION.test(lower)) return null;
    for (const [name, pattern] of COMMANDS) {
      if (!pattern.test(lower)) continue;
      // "Approve the wait plan" is a command; "approve it, but not before noon" is not.
      const rest = lower.replace(pattern, "");
      // "Yes" itself is fine; "yes, but don't execute" is not.
      return NEGATION.test(rest) ? null : name;
    }
    return null;
  }

  // The plan the agent recommended, as a plan id from `plans`, or null.
  // The prompt asks for a final "Recommended plan: <id>" line; older or freer answers
  // fall back to the first plan id written after the first "recommend". Answers list
  // every plan's id, so the first id in the whole answer is not the recommendation.
  function recommendedPlanId(answer, plans) {
    const text = String(answer || "");
    const ids = plans.map((plan) => plan.id);
    const byLower = new Map(ids.map((id) => [id.toLowerCase(), id]));
    const explicit = [...text.matchAll(/recommended plan(?: id)?\s*[:：]\s*[`*_]*([a-z0-9][a-z0-9:._-]*)/gi)];
    for (const match of explicit.reverse()) {
      const id = byLower.get(match[1].toLowerCase().replace(/[._-]+$/, ""));
      if (id) return id;
    }
    const lower = text.toLowerCase();
    const start = lower.search(/recommend/);
    if (start < 0) return null;
    const tail = lower.slice(start);
    let best = null;
    let position = Infinity;
    for (const [key, id] of byLower) {
      const at = tail.indexOf(key);
      if (at >= 0 && at < position) { position = at; best = id; }
    }
    return best;
  }

  const api = { isQuestion, parseCommand, recommendedPlanId };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsIntent = api;
})(typeof window === "undefined" ? globalThis : window);
