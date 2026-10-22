# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary user: the person on a logistics exceptions desk.** The persona is
illustrative, not a customer: the exceptions desk of a mid-size regional
distributor that ships electronics and medical supplies from its hubs to
hospitals and stores in several cities. On a bad morning several shipments
slip at once. Today that person opens three systems per incident,
phones carriers, and decides in a spreadsheet. Their job is to:

- decide which exception needs them first;
- choose a fix that trades cost, arrival time and order priority;
- get it approved, carried out and checked, and book and pay the carriers.

They work in two places:

- **Away from the desk, by voice:** an Alexa+ device with a screen they glance at.
- **At the desk:** an operator console that shows the same incident in full.

**Evaluating audience: hackathon judges.** They meet the product through a
video under three minutes, the README, the live demo and a local run. They
must understand it and try it in minutes. They do not need an AWS account: the
replay mode and Docker run the whole demo at no cost. They serve as a
checkpoint for clarity, not as the user the experience is designed for.

## Product Purpose

LogiOps AI turns a morning of phone calls and spreadsheets into a short
conversation, without letting an AI move inventory on its own.

1. The person asks which late shipment needs them first.
2. The agent reads orders, inventory and carrier quotes through MCP tools, and
   code calculates every feasible plan.
3. The agent recommends one plan by cost, arrival time and order priority, and
   reads it back.
4. The person approves with one "yes".
5. The system carries the plan out once, checks that every unit is accounted
   for, and can book and pay the carriers after reading the price back.

Success means:

- a recommendation grounded in the incident's data within seconds;
- one human decision;
- an execution that is verified, not assumed;
- outcomes measured from the recorded events (time to decision, time to
  execution, critical units on time, extra cost), not claimed.

## Positioning

- **The agent recommends; it never approves, and code enforces that.**
  - No approval tool exists.
  - An approval names the exact plan and the version of the data.
  - A change in the data invalidates it and raises an alert.
  - Execution is idempotent.
- **The numbers come from code, the words from the model, and a data check
  sits between them.**
  - Deterministic code calculates the plans.
  - The model compares them and explains its pick.
  - Every answer, the spoken line included, is checked against the incident's
    data before it is shown. A failed check goes back to the model once; an
    answer that still fails is shown flagged, never hidden.
- **The same MCP tools serve a person's assistant and an autonomous agent.**
  The server speaks MCP over Streamable HTTP, with OAuth 2.1, MCP Apps and an
  Agent Skill, the protocols Alexa+ add-ons are built on. What I expect is left to
  connect the real Alexa+ is in `docs/hackathon/alexa-plus-readiness.md`; it could not
  be verified, because the Alexa+ developer tools are partner-only.

## Operating Context

- **`/demo`: a simulated Alexa+ device.**
  - It is an Echo Show-style screen, and full screen on a phone.
  - It shows one surface at a time, drawn as light trails on a night road:
    home with the open incidents as lanes, incident with the plan's map and
    time scale, the agent at work, plans with the MCP App inside, confirmation
    with Yes / No, receipt, alert and result.
  - Under the surfaces sits a conversation dock: what was heard, the short
    spoken reply, a voice light bar, suggestion chips, the microphone and a
    text field.
  - "More" opens the full answer with the tool trace.
  - The Alexa+ developer tools are partner-only, so the page stands in for the
    wake word, speech recognition, voice, screen and account. Everything under
    it goes through the same REST and MCP endpoints a real integration would
    use.
- **`/console`: the desk-side operator console.**
  - It is a three-column desk. The incident queue is on the left. The incident
    is in the middle: route map, promise bars, plans table, Approve and Execute,
    booking and audit trail. An Agent rail with each MCP call and the
    conversation is on the right, and the session's metrics sit in the top bar.
  - A Developer drawer holds the token, the stock change, the reset and the
    scenario pack import.
- **Voice and screen split the work.**
  - The spoken reply is one or two sentences, with no ids or tables and with
    absolute times.
  - The screen keeps the full detail.
- **Commands act only from a closed grammar.** "Approve the recommended plan",
  "yes", "execute it", "book it" and "withdraw the approval" act. Questions, negations and commands
  buried in a longer sentence go to the agent and never act.
- **The live demo runs on AWS within limits.**
  - It shares a daily budget of model calls. When the budget is spent, replies
    come from the scripted replay, and the page says so.
  - The replay mode runs the same MCP calls with zero tokens.

## Capabilities and Constraints

- **Incidents.**
  - Four built-in synthetic incidents: a delay, a carrier outage with a
    critical and a standard order, a customs hold, and two orders competing
    for stock.
  - Any scenario pack registered over HTTP, from the console, or at start.
- **Agent jobs.** Investigate, answer follow-ups from the investigation already
  done, and brief the queue with read-only tools. The agent runs on Strands
  Agents over Amazon Bedrock Converse, with prompt caching.
- **Operator preferences.** A rule, a spend cap and a note steer which plan is
  picked, through fixed rules. A preference never approves.
- **Bookings.** A booking is quoted with the carrier cost, a service fee and
  tax, read back, charged once under an idempotency key, and returned with a
  receipt. Payments and customer notifications are simulated, and the product
  says so.
- **Other capabilities.**
  - Proactive alerts when data under an investigated plan changes.
  - Memory across sessions for signed-in people (AgentCore Memory).
  - The spoken voice (Amazon Polly).
  - Sign-in with OAuth 2.1 (Amazon Cognito).
  - Outcome metrics per incident and per session.
- **Country-agnostic.**
  - Place names in the built-in incidents are examples.
  - The tax on a booking is a setting (`LOGIOPS_TAX_RATE`,
    `LOGIOPS_TAX_NAME`).
  - The demo's timestamps use one fixed offset (UTC-05:00).
  - No copy, prompt or screen ties the product to one country.
- **Frontend constraints.**
  - Plain HTML, CSS and ES modules, with no framework and no build step.
  - Shared `app/*` modules serve both pages.
  - No `innerHTML` and no `localStorage`; the operator token lives in
    `sessionStorage` for the tab only.
  - The MCP App view loads through a sandbox proxy on a second origin, with
    no network access.
- **Terminology.** Use these terms consistently: incident, plan, pick ("Agent
  pick"), approval, execution, booking, receipt, alert, briefing ("Start
  here"), "Checked against the data".
- **Language.** The UI is in English.

## Brand Commitments

- **Name.** The name is **LogiOps AI**, confirmed.
- **Voice.** Plain and operational:
  - say the decision and its numbers first;
  - give absolute times;
  - quote the operator's own notes word for word;
  - never claim that something was approved, executed or delivered when it
    was not.
- **Honest labels.**
  - Whatever is simulated is labeled as such: the Alexa+ device, payments,
    notifications and the synthetic incidents.
  - The Alexa+ experience is never presented as a real Alexa integration.

## Evidence on Hand

- **Measured on the deployed demo (2026-10-19, live Bedrock through Strands
  Agents), for SHIP-433.** The figures are in the README:
  - a grounded recommendation in 12.2 s, with 5 MCP calls in one live agent run;
  - the tool calls streamed to the device from 2.6 s to 5.7 s, the answer at
    12.5 s;
  - 13.1 s from the first investigation to the verified execution, in a scripted
    walkthrough with no human pause;
  - 12 critical units on time and 18 standard units 8 h late, for $390 extra;
  - a $466.10 booking charged once.
- **Earlier runs.** 13.6 s to the recommendation on 2026-10-12; 13.0 s on
  2026-10-17, with axe at 0 on desktop and phone.
- **Live figures.** `GET /metrics` reports the decision and execution times,
  the outcomes, the model calls and tokens, and the session total booked from
  recorded events. Booking numbers and amounts per incident require operator
  access through the incident, booking or receipt endpoints.
- **Screens.** Screenshots generated in replay are in `docs/img/`:
  `device-home.png`, `device-agent.png`, `device-plans.png`,
  `device-journey.png`, `device-confirm.png`, `device-result.png`,
  `device-phone.png` and `console.png`.
- **Scenario and decisions.**
  - The synthetic scenario is described in `docs/demo-scenario.md`.
  - Decisions with their evidence are in `docs/hackathon/decisions.md`.
- **Absences: never fabricate these.**
  - No real customers, pilots, testimonials or quotes.
  - No industry benchmarks or market figures.
  - No pricing or business model.
  - No logo or brand mark.
  - The persona is illustrative.

## Product Principles

1. **The person decides.** The agent reads, calculates, compares and
   recommends. Approval, payment and anything irreversible wait for an explicit
   human "yes", bound to what was shown.
2. **Code makes the numbers; the model explains them.** Figures on screen and
   in speech come from data and deterministic calculation, and are checked
   before they are shown.
3. **Say it short, show it whole.** The voice gives the decision in a sentence.
   The screen and "More" carry the evidence: plans, trace and data check.
4. **Nothing acts by accident.**
   - Commands come from a closed grammar.
   - Prices and plans are read back before anything acts.
   - Execution and charges happen once.
   - Stale data stops an action rather than letting it proceed.
5. **Measured, not claimed.** Outcomes come from recorded events, and anything
   simulated says so.

## Accessibility & Inclusion

- **CI gate.** axe-core reports zero violations on the device and the console at
  1440 and 390 px; CI fails otherwise.
- **Voice and text are equal paths.**
  - Every command works typed, spoken or tapped.
  - The microphone needs Chrome or Edge, so the text field is always present.
- **Built-in behaviour.**
  - Visible focus.
  - The queue works from the keyboard: each incident is a button.
  - `prefers-reduced-motion` is honoured.
  - Spoken replies are announced through `aria-live`.
