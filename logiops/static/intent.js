(function (root) {
  const QUESTION = /\?\s*$|^(how|what|why|when|which|who|should|can|could|would|will|is|are|do|does|did|if)\b/;
  const OPENER = String.raw`^(?:(?:ok(?:ay)?|alexa|please|now|alright|great|sure|then|and)[,.!]?\s+)*`;
  const TRAILER = /(?:[,\s]+(?:please|now))+$/;
  const PLAN_WORDS = new Set((
    "the a an my it this that plan option recommended recommendation agent agent's agents pick preferred preference "
    + "cheapest cheaper lowest least cost expensive split express expedite expedited clearance broker reroute re-route "
    + "rebook economy ground air fly flight freight hospital school store first come first-come placed as priority "
    + "local stock warehouse wait transfer order orders both and with on approved dollar dollars usd "
    + "carrier carriers service services transport booking for"
  ).split(" "));
  const AMOUNT = /^\$?(?:\d{1,3}(?:,\d{3})+|\d{1,6})$/;
  const KNOWN_WORDS = new Set((
    "a an the is are was were be been am do does did done can could should would will may might must don doesn isn can won "
    + "what why how which when where who whose any anything some every all none its this that these those there here "
    + "i me my we us our you your they them their he she his her to of in on at for from with without about by "
    + "and or but not no yes yeah yep nope ok okay please thanks thank hi hello hey "
    + "if then than so as up out over under after before now today tomorrow yesterday tonight morning next last "
    + "tell show give explain check need needs want happen happens happening happened going get got let make help see "
    + "open approve execute run go ahead reset start book pay resume continue cancel confirm forget remember delete investigate investigating recheck refresh again "
    + "link connect sign log unlink disconnect switch back "
    + "delay delays late eta status incident incidents shipment shipments customer customers cost costs price "
    + "risk critical inventory queue inbox route truck alert alerts receipt result results withdraw revoke undo approval home list"
  ).split(" "));
  const GRAMMAR = [
    ["reset", /^(?:reset(?: (?:this|the) incident| it| this)?|start (?:this|the) incident over)$/],
    ["approve", /^approve(?: (?<rest>.+))?$/],
    ["execute", /^(?:(?:execute|run|do) it|go ahead|execute(?: (?<rest>.+))?)$/],
    ["open", /^(?:open|show|switch to|go to) ship-\d+$/],
    ["show_plans", /^(?:show|open|see|go back to|back to)(?: me)?(?: the| all(?: the)?)? (?:plans|options)$/],
    ["show_incident", /^(?:show|open|see|go back to|back to)(?: me)? (?:the|this) (?:incident|map)$/],
    ["show_result", /^(?:show|open|see|go back to|back to)(?: me)? the results?$/],
    ["show_home", /^(?:(?:go )?home|go back|(?:go )?back to (?:the |my )?(?:queue|inbox|list|home)|(?:show|open|see)(?: me)? (?:the |my )?(?:queue|inbox))$/],
    ["withdraw", /^(?:withdraw|cancel|revoke|undo|take back)(?: (?:the|my|this|that))? approval$/],
    ["book", /^(?:book(?: and pay(?: for)?)?|pay for)(?: (?<rest>.+))?$/],
    ["confirm", /^(?:yes|yeah|yep|confirm(?:ed)?)(?:[,\s]+(?:please|do it|go ahead|confirm|approve it|execute it|book it|pay(?: for it)?|approve and pay))?$/],
    ["decline", /^(?:(?:no|nope)(?:[,\s]+(?:thanks|thank you))?|(?:no[,\s]+)?(?:cancel(?: it)?|never mind|don'?t (?:book|pay for) it|don'?t))$/],
    ["resume", /^(?:resume|continue (?:the|my) (?:booking|purchase)|resume (?:the|my) (?:booking|purchase))$/],
    ["forget_me", /^(?:forget me|forget (?:our|my) (?:conversations?|history|chats?)|delete my (?:memory|history)|forget everything about me)$/],
    ["pick_up", /^(?:pick up (?:there|where we left off)|continue where we left off|resume where we left off|where were we)$/],
    ["link", /^(?:link|connect)(?: (?:my|the))? account$|^(?:sign|log) ?in(?: to (?:my|the) account)?$/],
    ["unlink", /^(?:sign|log) ?out$|^(?:unlink|disconnect)(?: (?:my|the))? account$/],
  ];

  const REMEMBER = new RegExp(`${OPENER}(?:remember|from now on)\\b[,:]?\\s*(?:that\\s+)?`);
  const FORGET = new RegExp(`${OPENER}(?:forget|clear|reset|delete|remove)\\s+(?:all\\s+)?(?:my|the)\\s+(?:saved\\s+)?(?:preferences?|prefs)\\b`);
  const NO_CAP = /\b(?:no|remove|drop|forget|clear|without)\s+(?:the\s+|my\s+|a\s+|any\s+)?(?:spend(?:ing)?\s+)?(?:cap|budget|limit)\b/;
  const CAP_WORDS = /\b(?:cap|budget|limit|under|below|at most|no more than|more than|over|exceed\w*|up to|max(?:imum)?|spend\w*)\b/;
  const MONEY = /\$\s?(\d{1,3}(?:,\d{3})+|\d{1,6})\b|\b(\d{1,3}(?:,\d{3})+|\d{1,6})\s?(?:usd|dollars?)\b/;
  const CHEAPEST = /\bcheap(?:est|er)?\b|\blowest cost\b|\bleast expensive\b|\bsave money\b/;
  const BALANCED = /\b(?:balanced|default (?:ranking|pick|rule))\b/;
  const BRIEFING = /\b(?:any (?:delays?|incidents?|problems?|issues?|exceptions?)(?: today)?|brief(?:ing)? me|(?:daily|morning|queue) briefing|what needs (?:my )?attention|what should i (?:look at|work on|handle) first|which incident (?:first|should i)|summari[sz]e (?:the |my )?(?:queue|inbox|incidents))\b/;
  const CAPABILITIES = new RegExp(`${OPENER}(?:what can (?:you|i) (?:do|say|ask)(?: here)?|what do you do|how does this work|help(?: me)?)[\\s?.!]*$`);
  const START_OVER = new RegExp(`${OPENER}(?:let'?s )?(?:start over|clear (?:the |this )?conversation|new conversation|forget this conversation)[\\s.!]*$`);
  const RECOMMEND = /\b(recommend\w*|choose|select|go with|suggest\w*)\b/gi;
  const RECOMMENDED_LINE = /recommended plan(?: id)?\s*[:：][\s`*_"']*([A-Za-z0-9][A-Za-z0-9:._-]*)/gi;
  const NEGATED = /\b(not|never|no|instead of|rather than|avoid)\b|n't\b/i;

  function isQuestion(text) {
    return QUESTION.test(String(text).trim().toLowerCase());
  }

  function namesOnlyPlans(rest) {
    if (!rest) return true;
    return rest.split(/[\s,]+/).filter(Boolean).every((word) => PLAN_WORDS.has(word) || AMOUNT.test(word));
  }

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

  function planSelector(text) {
    const lower = String(text).toLowerCase();
    if (CHEAPEST.test(lower)) return { cheapest: true };
    const money = lower.match(MONEY) || lower.match(/\b(\d{1,3}(?:,\d{3})+|\d{1,6})\b/);
    if (money) return { cost: Number((money[1] ?? money[2]).replaceAll(",", "")) };
    return {};
  }

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
    if (!Object.keys(update).length) update.note = rest.replace(/[.!]+$/, "").slice(0, 200);
    return { update };
  }

  function isBriefing(text) {
    return BRIEFING.test(String(text).trim().toLowerCase());
  }

  function isCapabilities(text) {
    return CAPABILITIES.test(String(text).trim().toLowerCase());
  }

  function isForgetMe(text) {
    return parseCommand(text) === "forget_me";
  }

  function isStartOver(text) {
    return START_OVER.test(String(text).trim().toLowerCase());
  }

  function isNoise(text) {
    const lower = String(text).toLowerCase();
    if (/\b(?:ship|ord)-\d+/.test(lower)) return false;
    return !(lower.match(/[a-z]+/g) || []).some((word) => KNOWN_WORDS.has(word) || PLAN_WORDS.has(word));
  }

  function resolvePlan(reference, plans) {
    const wanted = reference.trim().replace(/[.,;:]+$/, "").toLowerCase();
    const [, base, version] = wanted.match(/^(.+?)(?::v(\d+))?$/);
    const sameVersion = (plan) => version === undefined || plan.id.toLowerCase().endsWith(`:v${version}`);
    const rules = [
      (plan) => plan.id.toLowerCase() === wanted,
      (plan) => base === String(plan.kind || "").toLowerCase() && sameVersion(plan),
      (plan) => base === `${plan.id.split(":")[0]}:${plan.kind || ""}`.toLowerCase() && sameVersion(plan),
      (plan) => plan.id.toLowerCase().endsWith(`:${wanted}`),
    ];
    for (const rule of rules) {
      const found = plans.filter(rule);
      if (found.length === 1) return found[0].id;
    }
    return null;
  }

  function negatedBefore(text, start) {
    const window = text.slice(Math.max(0, start - 40), start).split("\n").pop();
    return NEGATED.test(window.split(/[.;:,!?|]/).pop());
  }

  function affirmed(line, id) {
    for (let at = line.indexOf(id); at >= 0; at = line.indexOf(id, at + 1)) {
      if (!negatedBefore(line, at)) return true;
    }
    return false;
  }

  function recommending(text) {
    return [...text.matchAll(RECOMMEND)].filter((match) => !negatedBefore(text, match.index));
  }

  function recommendedPlanId(answer, plans, requireLine = false) {
    const text = String(answer || "");
    const explicit = [...text.matchAll(RECOMMENDED_LINE)];
    if (explicit.length) return resolvePlan(explicit[explicit.length - 1][1], plans);
    if (requireLine) return null;
    const lines = text.split(/\r?\n/);
    const cited = plans.filter((plan) => lines.some((line) => affirmed(line, plan.id)));
    if (cited.length === 1) return cited[0].id;
    for (const line of lines) {
      if (!recommending(line).length) continue;
      const inLine = plans.filter((plan) => affirmed(line, plan.id));
      if (inLine.length === 1) return inLine[0].id;
    }
    const words = recommending(text);
    if (!words.length) return null;
    const last = words[words.length - 1];
    const tail = text.slice(last.index + last[0].length);
    const after = plans.filter((plan) => tail.includes(plan.id))
      .sort((a, b) => tail.indexOf(a.id) - tail.indexOf(b.id) || (a.id < b.id ? -1 : 1));
    return after.length ? after[0].id : null;
  }

  function mentionedIncident(text, ids) {
    const named = ids.filter((id) => new RegExp(`(^|[^a-z0-9-])${id.toLowerCase()}($|[^a-z0-9-])`).test(String(text).toLowerCase()));
    return named.length === 1 ? named[0] : null;
  }

  const api = {
    isQuestion, parseCommand, planSelector, parsePreference, isBriefing, isCapabilities, isStartOver, isForgetMe, isNoise,
    recommendedPlanId, mentionedIncident,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LogiOpsIntent = api;
})(typeof window === "undefined" ? globalThis : window);
