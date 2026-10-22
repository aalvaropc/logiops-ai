export const PURCHASE_KEY = "logiops-pending-purchase";

export function dollars(value) {
  return `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function spelled(number) {
  return String(number).replace("-", "").split("").join(" ");
}

export function newPurchaseKey(webCrypto = globalThis.crypto) {
  const random = webCrypto?.randomUUID ? webCrypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `buy-${random}`;
}

const taxWords = (label) => String(label).replace(/^Tax\b/, "tax");

export function purchaseReadback(purchase, plan) {
  const quote = purchase.quote;
  const card = String(quote.payment_method).replace(/\s*\(simulated\)$/i, "").toLowerCase();
  const breakdown = `carriers and services ${dollars(quote.base_usd)}, service fee ${dollars(quote.service_fee_usd)}, `
    + `${taxWords(quote.tax_label)} ${dollars(quote.tax_usd)}, total ${dollars(quote.total_usd)}, charged to the ${card} (simulated)`;
  if (!purchase.approve) {
    const text = `To book “${quote.plan_label}”: ${breakdown}. Say “yes” to pay, or “no”.`;
    return { text, spoken: text };
  }
  const delay = plan.projected_customer_delay_hours ? `${plan.projected_customer_delay_hours} hours of delay` : "no delay";
  const late = (plan.orders || []).filter((order) => order.priority === "critical" && order.delay_hours > 0);
  const warning = late.length ? ` It leaves the critical order for ${late.map((order) => order.customer).join(" and ")} late.` : "";
  const text = `To approve “${quote.plan_label}” (${delay}) and book it: ${breakdown}.${warning} `
    + "Say “yes” to approve and pay, or “no”.";
  return { text, spoken: text };
}

export function bookingRows(booking) {
  return [
    ["Carriers and services", dollars(booking.base_usd)],
    ...booking.lines.map((line) => [`${line.service}, ${line.units} units`, "cost_usd" in line ? dollars(line.cost_usd) : "included", "line"]),
    ["Service fee", dollars(booking.service_fee_usd)], [booking.tax_label, dollars(booking.tax_usd)], ["Total", dollars(booking.total_usd)],
  ];
}

export function createPurchase({
  storage, request, api, selectors, crypto: webCrypto, now = () => Date.now(), snapshot, incidentId, say, act, approvePlan,
  onBooking = () => {}, onReadback = () => {},
}) {
  let pending = null;

  function stored() {
    const value = storage.getJson(PURCHASE_KEY);
    return value && value.quote && Date.parse(value.quote.expires_at) > now() ? value : null;
  }

  function keep(purchase) {
    pending = purchase;
    storage.set(PURCHASE_KEY, purchase ? JSON.stringify(purchase) : null);
  }

  function forget() {
    keep(null);
  }

  function take() {
    const current = pending;
    pending = null;
    return current;
  }

  function readback(purchase, plan) {
    return purchaseReadback(purchase, plan);
  }

  async function start(lower) {
    const current = snapshot();
    if (!selectors.visiblePlans(current).length) {
      say("assistant", "There are no plans for the current data yet. Ask me to investigate first.");
      return null;
    }
    const approval = selectors.visibleApproval(current);
    const lockedId = current.executions[0]?.plan_id || approval?.plan_id;
    const locked = lockedId && current.plans.find((plan) => plan.id === lockedId);
    const named = selectors.namedPlanKinds(lower);
    if (locked && named && !named.includes(locked.kind)) {
      say("assistant", `The approved plan is “${locked.label}”, so that's the only one I can book. Nothing was charged.`);
      return null;
    }
    const plan = locked || selectors.planFromUtterance(lower);
    if (!plan) {
      const options = selectors.visiblePlans(current).map((item) => `“${item.label}” ($${item.incremental_cost_usd})`).join(", ");
      say("assistant", `That plan isn't available for the current data. The options are ${options}.`);
      return null;
    }
    const booked = (current.bookings || []).find((item) => item.plan_id === plan.id);
    if (booked) {
      say("assistant", `“${plan.label}” is already booked as ${booked.number}: ${dollars(booked.total_usd)} was charged once. Nothing more to pay.`);
      onBooking(booked);
      return null;
    }
    if (!plan.incremental_cost_usd) {
      say("assistant", `“${plan.label}” uses no paid carrier or service, so there's nothing to book.`);
      return null;
    }
    let quote;
    await act(async () => { quote = await request(`/incidents/${encodeURIComponent(incidentId())}/bookings/quote`, "POST", { plan_id: plan.id }); }, "");
    const purchase = { incidentId: incidentId(), planId: plan.id, sourceVersion: plan.source_version, approve: !quote.approved, quote, key: newPurchaseKey(webCrypto) };
    keep(purchase);
    const read = readback(purchase, plan);
    say("assistant", read.text, "price read-back · nothing charged yet", read.spoken);
    onReadback(purchase, plan);
    return purchase;
  }

  async function confirm(purchase) {
    if (Date.parse(purchase.quote.expires_at) <= now()) {
      forget();
      say("assistant", "That price expired, so nothing was charged. Say “book it” for a new quote.");
      return null;
    }
    const current = snapshot();
    const plan = current.plans.find((item) => item.id === purchase.planId && item.source_version === purchase.sourceVersion);
    const live = plan && (plan.source_version === current.source_version || current.executions.some((item) => item.plan_id === plan.id));
    if (!live) {
      forget();
      say("assistant", "The data changed after I read that price back, so nothing was approved or charged. Ask me again.");
      return null;
    }
    let approvedNow = false;
    if (purchase.approve && !selectors.visibleApproval(current) && !current.executions.length) {
      try {
        await act(() => approvePlan(plan), "");
      } catch (error) {
        const retry = !error.status || error.status >= 500;
        if (retry) keep(purchase);
        else forget();
        say("assistant", `Nothing was approved or charged: ${error.message || error}` + (retry ? " Say “yes” to try again." : ""));
        return null;
      }
      approvedNow = true;
      keep({ ...purchase, approve: false });
    }
    let booking;
    try {
      await act(async () => {
        booking = await request(`/quotes/${encodeURIComponent(purchase.quote.quote_id)}/confirm`, "POST", {
          confirmed_total_usd: purchase.quote.total_usd, idempotency_key: purchase.key,
        });
      }, "");
    } catch (error) {
      const retry = !error.status || error.status >= 500;
      if (retry) keep(approvedNow ? { ...purchase, approve: false } : purchase);
      else forget();
      say("assistant", `${approvedNow ? `Approved “${plan.label}”, but the` : "The"} booking didn't go through: ${error.message || error}`
        + (retry ? " Say “yes” to try again; it never charges twice." : ""));
      return null;
    }
    forget();
    onBooking(booking);
    say("assistant", `${approvedNow ? "Approved. " : ""}${booking.confirmation} Open the receipt for a printable copy.`,
      `booking · ${booking.number}`,
      `${approvedNow ? "Approved, and booked. " : "Booked. "}${dollars(booking.total_usd)} charged. Your confirmation number is ${booking.number}.`);
    return booking;
  }

  async function resume(selectIncident) {
    const parked = stored();
    if (!parked) {
      say("assistant", "There's no booking waiting. Say “book it” to price the approved plan's carriers.");
      return null;
    }
    if (parked.incidentId !== incidentId()) {
      await selectIncident(parked.incidentId);
      if (incidentId() !== parked.incidentId) return null;
    }
    const plan = snapshot().plans.find((item) => item.id === parked.planId);
    if (!plan) {
      forget();
      say("assistant", "That booking no longer matches the incident's data, so nothing was charged. Say “book it” for a new quote.");
      return null;
    }
    keep(parked);
    const read = readback(parked, plan);
    say("assistant", read.text, "price read-back · nothing charged yet", read.spoken);
    onReadback(parked, plan);
    return parked;
  }

  async function openReceipt(number) {
    const headers = api.token() ? { Authorization: `Bearer ${api.token()}` } : {};
    const response = await api.fetch(`/bookings/${encodeURIComponent(number)}/receipt`, { headers, cache: "no-store" });
    if (!response.ok) throw new Error(api.explain(response.status, "The receipt could not be opened."));
    return response.text();
  }

  return { stored, keep, forget, take, pending: () => pending, start, confirm, resume, openReceipt, readback };
}
