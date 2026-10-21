export function bellText(alerts, incidentId) {
  const elsewhere = alerts.filter((alert) => alert.incident_id !== incidentId);
  const count = elsewhere.length;
  if (!count) return null;
  const first = elsewhere[0].incident_id;
  return { count, incidentId: first, text: `${count} alert${count === 1 ? "" : "s"} · ${first}`, label: `${count} proactive alert${count === 1 ? "" : "s"}; open ${first}` };
}

export function createAlerts({ request, list = () => request("/alerts"), incidentId, isBusy = () => false, isHidden = () => false, onAlerts = () => {}, onAnnounce }) {
  let alerts = [];

  async function announce(alert) {
    try {
      await request(`/alerts/${encodeURIComponent(alert.id)}/dismiss`, "POST");
    } catch (_) {
      return false;
    }
    alerts = alerts.filter((item) => item.id !== alert.id);
    onAlerts(alerts);
    await onAnnounce(alert);
    return true;
  }

  async function check() {
    if (isBusy() || isHidden()) return alerts;
    try {
      alerts = (await list()).alerts;
    } catch (_) {
      return alerts;
    }
    onAlerts(alerts);
    const here = alerts.find((alert) => alert.incident_id === incidentId());
    if (here && !isBusy()) await announce(here);
    return alerts;
  }

  function elsewhere() {
    return alerts.find((item) => item.incident_id !== incidentId()) || null;
  }

  return { check, announce, elsewhere, current: () => alerts };
}
