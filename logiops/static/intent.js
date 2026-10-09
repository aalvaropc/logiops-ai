// The demo's thin command layer, kept free of the DOM so it can be tested with node.
// A command is the whole utterance, from a closed grammar: an optional opener, the verb,
// and words that name a plan (its kind, its price, or who picked it). Anything else,
// including a question, a negation, or a word the grammar does not know ("nothing",
// "tomorrow", "my manager"), goes to the agent as a question and never acts.
(function (root) {
  const QUESTION = /\?\s*$|^(how|what|why|when|which|who|should|can|could|would|will|is|are|do|does|did|if)\b/;
  const OPENER = String.raw`^(?:(?:ok(?:ay)?|alexa|please|now|alright|great|sure|then|and)[,.!]?\s+)*`;
  // Courtesy words a command may end with: "execute it now", "approve it, please".
  const TRAILER = /(?:[,\s]+(?:please|now))+$/;
  const PLAN_WORDS = new Set((
    "the a an my it this that plan option recommended recommendation agent agent's agents pick preferred preference "
    + "cheapest cheaper lowest least cost expensive split express expedite expedited clearance broker reroute re-route "
    + "rebook economy ground air fly flight freight hospital school store first come first-come placed as priority "
    + "local stock warehouse wait transfer order orders both and with on approved dollar dollars usd"
  ).split(" "));
  const AMOUNT = /^\$?(?:\d{1,3}(?:,\d{3})+|\d{1,6})$/;
  const GRAMMAR = [
    ["reset", /^(?:reset|start over)(?: (?:this|the) incident| it| this)?$/],
    ["approve", /^approve(?: (?<rest>.+))?$/],
    ["execute", /^(?:(?:execute|run|do) it|go ahead|execute(?: (?<rest>.+))?)$/],
    ["open", /^(?:open|show|switch to|go to) ship-\d+$/],
    ["confirm", /^(?:yes|yeah|yep|confirm(?:ed)?)(?:[,\s]+(?:please|do it|go ahead|confirm|approve it|execute it))?$/],
  ];

  // "Remember …" saves a preference; it is data for the plan pick and never approves anything.
  const REMEMBER = new RegExp(`${OPENER}(?:remember|from now on)\\b[,:]?\\s*(?:that\\s+)?`);
  const FORGET = new RegExp(`${OPENER}(?:forget|clear|reset|delete|remove)\\s+(?:all\\s+)?(?:my|the)\\s+(?:saved\\s+)?(?:preferences?|prefs)\\b`);
  const NO_CAP = /\b(?:no|remove|drop|forget|clear|without)\s+(?:the\s+|my\s+|a\s+|any\s+)?(?:spend(?:ing)?\s+)?(?:cap|budget|limit)\b/;
  const CAP_WORDS = /\b(?:cap|budget|limit|under|below|at most|no more than|more than|over|exceed\w*|up to|max(?:imum)?|spend\w*)\b/;
  const MONEY = /\$\s?(\d{1,3}(?:,\d{3})+|\d{1,6})\b|\b(\d{1,3}(?:,\d{3})+|\d{1,6})\s?(?:usd|dollars?)\b/;
  const CHEAPEST = /\bcheap(?:est|er)?\b|\blowest cost\b|\bleast expensive\b|\bsave money\b/;
  const BALANCED = /\b(?:balanced|default (?:ranking|pick|rule))\b/;
  // "Any delays today?" asks for the whole queue, not for the open incident.
  const BRIEFING = /\b(?:any (?:delays?|incidents?|problems?|issues?|exceptions?)(?: today)?|brief(?:ing)? me|(?:daily|morning|queue) briefing|what needs (?:my )?attention|what should i (?:look at|work on|handle) first|which incident (?:first|should i)|summari[sz]e (?:the |my )?(?:queue|inbox|incidents))\b/;

  function isQuestion(text) {
    return QUESTION.test(String(text).trim().toLowerCase());
  }

  // Words after the verb must all name a plan; one unknown word makes it a question.
  function namesOnlyPlans(rest) {
    if (!rest) return true;
    return rest.split(/[\s,]+/).filter(Boolean).every((word) => PLAN_WORDS.has(word) || AMOUNT.test(word));
  }

  // "reset" | "approve" | "execute" | "open" | "confirm" (a bare yes) | null.
  function parseCommand(text) {
    const lower = String(text).trim().toLowerCase();
    if (!lower || /\?\s*$/.test(lower)) return null;
    const bare = lower.replace(/[.!]+$/, "").replace(new RegExp(OPENER), "").replace(TRAILER, "").trim();
    for (const [name, pattern] of GRAMMAR) {
      const match = bare.match(pattern);
      if (match && namesOnlyPlans(match.groups?.rest)) return name;
    }
    return null;
  }

  // How an approval names its plan beyond the kind: {cheapest: true}, {cost: 240}, or {}.
  function planSelector(text) {
    const lower = String(text).toLowerCase();
    if (CHEAPEST.test(lower)) return { cheapest: true };
    const money = lower.match(MONEY) || lower.match(/\b(\d{1,3}(?:,\d{3})+|\d{1,6})\b/);
    if (money) return { cost: Number((money[1] ?? money[2]).replaceAll(",", "")) };
    return {};
  }

  // {forget: true}, {update: {rule?, max_cost_usd?, note?}}, or null when it is not a preference.
  function parsePreference(text) {
    const raw = String(text).trim();
    const lower = raw.toLowerCase();
    if (!lower || QUESTION.test(lower)) return null;
    if (FORGET.test(lower)) return { forget: true };
    const opener = lower.match(REMEMBER);
    if (!opener) return null;
    const rest = raw.slice(opener[0].length).trim();
    const words = rest.toLowerCase();
    if (!rest) return null;
    const update = {};
    const money = words.match(MONEY);
    if (NO_CAP.test(words)) update.max_cost_usd = null;
    else if (money && CAP_WORDS.test(words)) update.max_cost_usd = Number((money[1] ?? money[2]).replaceAll(",", ""));
    if (CHEAPEST.test(words)) update.rule = "cheapest_unless_critical_late";
    else if (BALANCED.test(words)) update.rule = "balanced";
    // Anything else is a note for the agent, kept as the operator wrote it.
    if (!Object.keys(update).length) update.note = rest.replace(/[.!]+$/, "").slice(0, 200);
    return { update };
  }

  function isBriefing(text) {
    return BRIEFING.test(String(text).trim().toLowerCase());
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

  // The one incident a sentence names ("what about ship-452?"), or null for none or several.
  function mentionedIncident(text, ids) {
    const named = ids.filter((id) => new RegExp(`(^|[^a-z0-9-])${id.toLowerCase()}($|[^a-z0-9-])`).test(String(text).toLowerCase()));
    return named.length === 1 ? named[0] : null;
  }

  const api = { isQuestion, parseCommand, planSelector, parsePreference, isBriefing, recommendedPlanId, mentionedIncident };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsIntent = api;
})(typeof window === "undefined" ? globalThis : window);
