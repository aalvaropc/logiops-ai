export function bellText(alerts, incidentId) {
  const elsewhere = alerts.filter((alert) => alert.incident_id !== incidentId);
  const count = elsewhere.length;
  if (!count) return null;
  const first = elsewhere[0].incident_id;
  return { count, incidentId: first, text: `${count} alert${count === 1 ? "" : "s"} · ${first}`, label: `${count} proactive alert${count === 1 ? "" : "s"}; open ${first}` };
}

export const SEEN_KEY = "logiops-alerts-seen";

export function createAlerts({
  request, list = () => request("/alerts"), incidentId, isBusy = () => false, isHidden = () => false, onAlerts = () => {}, onAnnounce,
  acknowledge = true, storage = null,
}) {
  let alerts = [];
  let checking = null;
  const announced = new Set(storage?.getJson(SEEN_KEY) || []);

  async function announce(alert) {
    if (announced.has(alert.id)) return false;
    announced.add(alert.id);
    if (acknowledge) {
      try {
        await request(`/alerts/${encodeURIComponent(alert.id)}/dismiss`, "POST");
      } catch (_) {
        announced.delete(alert.id);
        return false;
      }
    }
    storage?.set(SEEN_KEY, JSON.stringify([...announced].slice(-50)));
    alerts = alerts.filter((item) => item.id !== alert.id);
    onAlerts(alerts);
    await onAnnounce(alert);
    return true;
  }

  async function poll() {
    if (isBusy() || isHidden()) return alerts;
    try {
      alerts = (await list()).alerts.filter((alert) => !announced.has(alert.id));
    } catch (_) {
      return alerts;
    }
    onAlerts(alerts);
    const here = alerts.find((alert) => alert.incident_id === incidentId());
    if (here && !isBusy()) await announce(here);
    return alerts;
  }

  function check() {
    checking ??= poll().finally(() => { checking = null; });
    return checking;
  }

  function elsewhere() {
    return alerts.find((item) => item.incident_id !== incidentId()) || null;
  }

  return { check, announce, elsewhere, current: () => alerts };
}
