import { CAPABILITIES_TEXT, CAPABILITIES_SPOKEN, FRESH_INVESTIGATION } from "./capabilities.js";

export function approvalReadback(plan) {
  const delay = plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} hours of delay` : "no delay";
  const late = (plan.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  const warning = late.length ? `, and it leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late` : "";
  return `Approve “${plan.label}” for $${plan.incremental_cost_usd} extra, ${delay}${warning}?`;
}

export function createCommands({
  store, intent, request, purchase, selectors, badges, preferences, say, act, device = () => {}, stopSpeaking = () => {},
  selectIncident, hideMcpApp = () => {}, showMcpApp = async () => {}, showMcpAppNote = () => {}, onInbox = () => {},
  approvePlan, executeApproved, savePreferences, linkAccount = async () => {}, signOut = () => {}, onRun = () => {},
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
      say("assistant", "Okay, starting over. Nothing was changed or approved. Ask about your queue, or about an incident.",
        undefined, "Okay, starting over. Nothing was changed.");
      return;
    }
    if (intent.isCapabilities(text)) {
      say("assistant", CAPABILITIES_TEXT, "help", CAPABILITIES_SPOKEN);
      return;
    }
    const pending = state.pendingApproval;
    state.pendingApproval = null;
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
      } catch (error) {
        say("assistant", `I couldn't do that: ${error.message || error}`);
      }
      return;
    }
    let command = intent.parseCommand(text);
    if (command === "open") {
      if (mentioned) {
        const item = state.inbox.find((entry) => entry.incident_id === mentioned);
        say("assistant", `Opened ${mentioned}: ${item?.title || "incident"}. Ask me what's happening, or say “investigate”.`);
        return;
      }
      command = null;
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
      } else if (command === "book") {
        await purchase.start(lower);
      } else if (command === "confirm" && pendingPurchase) {
        await purchase.confirm(pendingPurchase);
      } else if (command === "decline") {
        if (pendingPurchase || purchase.stored()) {
          purchase.forget();
          say("assistant", "Okay, nothing was booked or charged.");
        } else {
          say("assistant", pending ? "Okay, nothing was approved." : "Okay. Ask me anything else about the queue or this incident.");
        }
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
        if (!selectors.visiblePlans(state.snapshot).length) {
          say("assistant", "There are no plans for the current data yet. Ask me to investigate first.");
          return;
        }
        const plan = selectors.planFromUtterance(lower);
        if (!plan) {
          const options = selectors.visiblePlans(state.snapshot).map((item) => `“${item.label}” ($${item.incremental_cost_usd})`).join(", ");
          say("assistant", `That plan isn't available for the current data. The options are ${options}.`);
          return;
        }
        state.pendingApproval = { planId: plan.id, sourceVersion: plan.source_version };
        say("assistant", `${approvalReadback(plan)} Say “yes” to approve it, or ask me anything else.`);
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
          state.pendingApproval = pending;
          throw error;
        }
        say("assistant", `Approved “${plan.label}” for version ${plan.source_version}. Say “execute it” when you're ready.`);
        state.awaitingExecute = true;
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
        await act(executeApproved, "");
        const execution = state.snapshot.executions[0];
        say("assistant", `The plan was executed. ${badges.executionSummary(state.snapshot, execution)} Delivery is projected, not physically confirmed.`);
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
            ? await request(incidentPath("/agent/investigate"), "POST", { question: text })
            : await request(incidentPath("/agent/ask"), "POST", { question: text, history });
        }, "");
        say("assistant", run.answer, `${fresh ? "investigation" : "follow-up"} · ${badges.traceSummary(run)}`, run.spoken, badges.checkBadge(run));
        runNotes(run);
        if (fresh) {
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
