import { CAPABILITIES_TEXT, CAPABILITIES_SPOKEN, FRESH_INVESTIGATION } from "./capabilities.js";

export function approvalReadback(plan) {
  const delay = plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} hours of delay` : "no delay";
  const late = (plan.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  const warning = late.length ? `, and it leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late` : "";
  return `Approve “${plan.label}” for $${plan.incremental_cost_usd} extra, ${delay}${warning}?`;
}

export function withdrawReadback(plan, incidentId) {
  return `Withdraw the approval of “${plan.label}”? An approval is recorded with its data, so withdrawing resets ${incidentId} to its original data: `
    + "the plans and the approval are cleared, and you investigate it again. Say “yes” to withdraw it, or “no” to keep it.";
}

export function startOverLines(snapshot, approval) {
  const execution = snapshot?.executions[0];
  const decided = snapshot?.plans.find((plan) => plan.id === (execution?.plan_id || approval?.plan_id));
  if (execution && decided) {
    const booking = (snapshot.bookings || []).find((item) => item.plan_id === decided.id);
    const paid = booking ? `, and booking ${booking.number} stays paid (simulated)` : "";
    return [`Okay, starting over. I cleared our conversation; “${decided.label}” stays executed${paid}.`, "Okay, starting over. The executed plan stays as it is."];
  }
  if (decided) return [`Okay, starting over. I cleared our conversation; your approval of “${decided.label}” still stands.`, "Okay, starting over. Your approval still stands."];
  return ["Okay, starting over. Nothing was changed or approved.", "Okay, starting over. Nothing was changed."];
}

export function createCommands({
  store, intent, request, purchase, selectors, badges, preferences, say, act, device = () => {}, stopSpeaking = () => {},
  selectIncident, hideMcpApp = () => {}, showMcpApp = async () => {}, showMcpAppNote = () => {}, onInbox = () => {},
  approvePlan, executeApproved, savePreferences, linkAccount = async () => {}, signOut = () => {}, onRun = () => {}, onSurface = () => {},
  investigate = (path, body) => request(path, "POST", body),
}) {
  const state = store.state;
  const incidentPath = (suffix = "") => `/incidents/${encodeURIComponent(state.incidentId)}${suffix}`;

  function runNotes(run) {
    device("trace", run);
    onRun(run);
    badges.noteFallback(run);
    badges.noteCheck(run);
  }

  async function handle(raw) {
    const text = String(raw ?? "").trim();
    if (!text || state.busy) return;
    stopSpeaking();
    const mentioned = intent.mentionedIncident(text, state.inbox.map((item) => item.incident_id));
    if (mentioned && mentioned !== state.incidentId) {
      await selectIncident(mentioned).catch(() => {});
      if (state.incidentId !== mentioned) return;
    }
    state.forgetting = intent.isForgetMe(text);
    say("user", text);
    const lower = text.toLowerCase();
    if (intent.isStartOver(text)) {
      purchase.forget();
      store.set({ pendingApproval: null, awaitingExecute: false, selectedPlanId: null, conversation: state.conversation.slice(-1) });
      state.selections[state.incidentId] = null;
      hideMcpApp();
      const [line, spoken] = startOverLines(state.snapshot, selectors.visibleApproval(state.snapshot));
      say("assistant", `${line} Ask about your queue, or about an incident.`, undefined, spoken);
      onSurface("home");
      return;
    }
    if (intent.isCapabilities(text)) {
      say("assistant", CAPABILITIES_TEXT, "help", CAPABILITIES_SPOKEN);
      return;
    }
    if (intent.isNoise(text)) {
      say("assistant", `I didn't catch that. Ask “any delays today?”, or ask what's happening with ${state.incidentId}.`, "not understood",
        "I didn't catch that. Try asking “any delays today?”");
      return;
    }
    const pending = state.pendingApproval;
    state.pendingApproval = null;
    const pendingWithdraw = state.pendingWithdraw?.incidentId === state.incidentId ? state.pendingWithdraw : null;
    state.pendingWithdraw = null;
    const pendingPurchase = purchase.take();
    const preference = intent.parsePreference(text);
    if (preference) {
      state.awaitingExecute = false;
      try {
        if (preference.forget) {
          await act(() => request("/operator/preferences", "DELETE"), "");
          say("assistant", "Done. I forgot your saved preferences; plans are picked by the default ranking again.");
        } else {
          await act(() => savePreferences(preference.update), "");
          say("assistant", `Saved for every incident: ${preferences.describe(state.snapshot.operator_preferences)}. ${preferences.effect(state.snapshot, state.incidentId)} `
            + "Preferences never approve anything; you still approve the plan.");
        }
      } catch (error) {
        say("assistant", `I couldn't save that: ${error.message || error}`);
      }
      return;
    }
    if (intent.isBriefing(text) && !mentioned) {
      state.awaitingExecute = false;
      try {
        let run;
        await act(async () => { run = await request("/agent/briefing", "POST", { question: text }); }, "");
        state.briefingPick = run.start_with;
        onInbox();
        say("assistant", run.answer, `briefing · ${badges.traceSummary(run)}`, run.spoken, badges.checkBadge(run));
        runNotes(run);
        onSurface("home", { pick: run.start_with });
      } catch (error) {
        say("assistant", `I couldn't do that: ${error.message || error}`);
      }
      return;
    }
    let command = intent.parseCommand(text);
    const investigated = () => selectors.visiblePlans(state.snapshot).length > 0;
    if (command === "open" || command === "show_incident") {
      const id = command === "open" ? mentioned : state.incidentId;
      if (id) {
        const item = state.inbox.find((entry) => entry.incident_id === id);
        const next = state.snapshot?.executions.length ? "Say “show the result” to see what ran."
          : selectors.visibleApproval(state.snapshot) ? "Say “execute it” when you're ready."
          : investigated() ? "Say “show the plans” or “approve the recommended plan”." : "Ask me what's happening, or say “investigate”.";
        say("assistant", `${command === "open" ? "Opened" : "Here's"} ${id}: ${item?.title || "incident"}. ${next}`);
        onSurface("incident");
        return;
      }
      command = null;
    }
    if (command === "show_home") {
      const open = state.inbox.filter((item) => item.status !== "verified").length;
      say("assistant", open ? `Here's your queue: ${open} open incident${open === 1 ? "" : "s"}.` : "Here's your queue. Every incident is resolved.");
      onSurface("home");
      return;
    }
    if (command === "show_result") {
      if (state.snapshot?.executions.length) {
        say("assistant", `Here's the result for ${state.incidentId}.`);
        onSurface("result");
      } else {
        say("assistant", `Nothing has been executed for ${state.incidentId} yet, so there's no result to show.`);
      }
      return;
    }
    if (command === "show_plans") {
      const count = selectors.visiblePlans(state.snapshot).length;
      if (count) {
        say("assistant", `Here are the ${count} plans for ${state.incidentId}. Only you approve.`);
        onSurface("plans");
      } else {
        say("assistant", "There are no plans for the current data yet. Ask me what's happening first.");
      }
      return;
    }
    const awaitingExecute = state.awaitingExecute;
    state.awaitingExecute = false;
    try {
      if (command === "reset") {
        const id = state.incidentId;
        purchase.forget();
        await act(() => request("/demo/reset", "POST", { incident_id: id }), "");
        state.selectedPlanId = null;
        state.conversation = [];
        hideMcpApp();
        say("assistant", `Done. ${id} is back to its original state.`);
        onSurface("incident");
      } else if (command === "book") {
        await purchase.start(lower);
      } else if (command === "confirm" && pendingPurchase) {
        await purchase.confirm(pendingPurchase);
      } else if (command === "withdraw") {
        const id = state.incidentId;
        const approval = selectors.visibleApproval(state.snapshot);
        const plan = approval && state.snapshot.plans.find((item) => item.id === approval.plan_id);
        if (state.snapshot?.executions.length) {
          say("assistant", `${id} was already executed, so its approval stays on the record. Say “show the result” to see what ran.`);
        } else if (!plan) {
          say("assistant", `Nothing is approved for ${id}, so there's nothing to withdraw.`);
        } else if ((state.snapshot.bookings || []).some((booking) => booking.plan_id === plan.id)) {
          say("assistant", `“${plan.label}” is already booked and paid, so its approval stays.`);
        } else {
          state.pendingWithdraw = { incidentId: id, planId: plan.id, label: plan.label };
          say("assistant", withdrawReadback(plan, id), undefined, `Withdraw the approval of ${plan.label}? That resets ${id}, and you investigate it again. Say yes or no.`);
          onSurface("confirm", { kind: "withdraw", plan });
        }
      } else if (command === "confirm" && pendingWithdraw) {
        const id = pendingWithdraw.incidentId;
        if (selectors.visibleApproval(state.snapshot)?.plan_id !== pendingWithdraw.planId) {
          say("assistant", "The approval changed after I read it back, so nothing was reset.");
          onSurface("dismiss");
          return;
        }
        purchase.forget();
        await act(() => request("/demo/reset", "POST", { incident_id: id }), "");
        state.selectedPlanId = null;
        hideMcpApp();
        say("assistant", `Done. The approval of “${pendingWithdraw.label}” is withdrawn and ${id} is back to its original data. Ask me what's happening with ${id} to calculate the plans again.`);
        onSurface("incident");
      } else if (command === "decline") {
        if (pendingPurchase || purchase.stored()) {
          purchase.forget();
          say("assistant", "Okay, nothing was booked or charged.");
        } else {
          say("assistant", pending ? "Okay, nothing was approved."
            : pendingWithdraw ? `Okay, the approval of “${pendingWithdraw.label}” stays.` : "Okay. Ask me anything else about the queue or this incident.");
        }
        onSurface("dismiss");
      } else if (command === "forget_me") {
        if (state.auth.enabled && !state.session) {
          say("assistant", "I don't remember guests, so there's nothing to forget.");
        } else {
          let result;
          await act(async () => { result = await request("/memory", "DELETE"); }, "");
          state.memoryIncident = null;
          say("assistant", `Done. I forgot our earlier conversations (${result.forgotten} item${result.forgotten === 1 ? "" : "s"}). `
            + "Your saved preferences stay until you say “forget my preferences”.", "memory cleared");
        }
        state.forgetting = false;
      } else if (command === "pick_up") {
        const target = state.memoryIncident;
        if (!target) {
          say("assistant", "I don't have an earlier conversation to pick up. Ask about your queue, or about an incident.");
        } else {
          if (target !== state.incidentId) {
            await selectIncident(target);
            state.conversation.push({ role: "user", text });
          }
          say("assistant", `Back on ${target}. Ask what's happening, or say “approve the recommended plan”.`);
        }
      } else if (command === "link") {
        if (state.session) say("assistant", `You're already signed in as ${state.session.username}.`);
        else await linkAccount();
      } else if (command === "unlink") {
        if (!state.session) {
          say("assistant", "You're not signed in.");
        } else {
          signOut();
          say("assistant", "Signed out on this page. You're a guest again: you can read and ask, but not act.");
        }
      } else if (command === "resume") {
        await purchase.resume(selectIncident);
      } else if (command === "approve") {
        if (state.snapshot?.executions.length) {
          say("assistant", `${state.incidentId} was already executed. Say “show the result” to see what ran.`);
          return;
        }
        if (!selectors.visiblePlans(state.snapshot).length) {
          say("assistant", "There are no plans for the current data yet. Ask me to investigate first.");
          return;
        }
        const plan = selectors.planFromUtterance(lower);
        const standing = selectors.visibleApproval(state.snapshot);
        if (standing) {
          const approvedLabel = state.snapshot.plans.find((item) => item.id === standing.plan_id)?.label || standing.plan_id;
          say("assistant", plan?.id === standing.plan_id ? `“${approvedLabel}” is already approved. Say “execute it” when you're ready.`
            : `“${approvedLabel}” is already approved for this data, so I can't approve another plan. Say “withdraw the approval” first if you want to choose again.`,
          undefined, plan?.id === standing.plan_id ? "Already approved. Say execute it when you're ready." : "Another plan is already approved. Say “withdraw the approval” to choose again.");
          return;
        }
        if (!plan) {
          const options = selectors.visiblePlans(state.snapshot).map((item) => `“${item.label}” ($${item.incremental_cost_usd})`).join(", ");
          say("assistant", `That plan isn't available for the current data. The options are ${options}.`);
          return;
        }
        state.pendingApproval = { planId: plan.id, sourceVersion: plan.source_version };
        say("assistant", `${approvalReadback(plan)} Say “yes” to approve it, or ask me anything else.`);
        onSurface("confirm", { kind: "approval", plan });
      } else if (command === "confirm" && pending) {
        const plan = selectors.visiblePlans(state.snapshot)
          .find((item) => item.id === pending.planId && item.source_version === pending.sourceVersion);
        if (!plan) {
          say("assistant", "The data changed after I read that plan back, so nothing was approved. Ask me again.");
          return;
        }
        try {
          await act(() => approvePlan(plan), "");
        } catch (error) {
          if (error.status === 409) onSurface("dismiss");
          else state.pendingApproval = pending;
          throw error;
        }
        say("assistant", `Approved “${plan.label}” on the current data. Nothing has run yet: say “execute it” when you're ready.`);
        state.awaitingExecute = true;
        onSurface("plans");
      } else if (command === "execute" || (command === "confirm" && awaitingExecute && selectors.visibleApproval(state.snapshot))) {
        const approval = selectors.visibleApproval(state.snapshot);
        const approved = approval && state.snapshot.plans.find((plan) => plan.id === approval.plan_id);
        const named = selectors.namedPlanKinds(lower);
        if (approved && named && !named.includes(approved.kind)) {
          const wanted = named.map((kind) => selectors.visiblePlans(state.snapshot).find((plan) => plan.kind === kind)).find(Boolean);
          say("assistant", `The approved plan is “${approved.label}”, so nothing was executed. ${wanted ? `Approve “${wanted.label}” first if you want it instead.` : "The plan you named isn't available for the current data."}`);
          return;
        }
        if (state.snapshot?.executions.length) {
          say("assistant", `${state.incidentId} was already executed. ${badges.executionSummary(state.snapshot, state.snapshot.executions[0])} Reset this incident to run the flow again.`);
          return;
        }
        if (!approval) {
          const next = investigated() ? "Say “approve the recommended plan” first, and I'll read it back." : `Ask me what's happening with ${state.incidentId} first, then approve a plan.`;
          say("assistant", `Nothing is approved for ${state.incidentId} yet, so nothing ran. ${next}`, undefined,
            investigated() ? "Nothing ran. Approve a plan first." : "Nothing ran. Ask me what's happening first.");
          return;
        }
        await act(executeApproved, "");
        const execution = state.snapshot.executions[0];
        say("assistant", `The plan was executed. ${badges.executionSummary(state.snapshot, execution)} Delivery is projected, not physically confirmed.`);
        onSurface("result");
      } else if (command === "confirm") {
        say("assistant", "Nothing is waiting for a “yes” right now. Say “approve the recommended plan” or “book it”, and I'll read it back first.");
      } else {
        const current = selectors.latestAgentEvent(state.snapshot);
        const stale = !current || current.data.source_version !== selectors.visibleVersion(state.snapshot);
        const executed = Boolean(state.snapshot?.executions.length);
        if (executed && stale) {
          say("assistant", "This incident was already executed without an investigation to refer to. Reset this incident to start over.");
          return;
        }
        const fresh = !executed && (stale || FRESH_INVESTIGATION.test(lower));
        const history = state.conversation.slice(0, -1).slice(-6).map(({ role, text: turn }) => ({ role, text: turn.slice(0, 1000) }));
        let run;
        await act(async () => {
          run = fresh
            ? await investigate(incidentPath("/agent/investigate"), { question: text })
            : await request(incidentPath("/agent/ask"), "POST", { question: text, history });
        }, "");
        say("assistant", run.answer, `${fresh ? "investigation" : "follow-up"} · ${badges.traceSummary(run)}`, run.spoken, badges.checkBadge(run));
        runNotes(run);
        if (fresh) {
          onSurface("plans");
          showMcpApp(run).catch((error) => {
            showMcpAppNote(`The interactive card could not be loaded (${error?.message || error}). The plans are listed below.`);
          });
        }
      }
    } catch (error) {
      say("assistant", `I couldn't do that: ${error.message || error}`);
    }
  }

  return { handle };
}
