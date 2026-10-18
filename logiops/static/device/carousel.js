import { formatDate } from "../app/selectors.js";

export function cardTags(card) {
  const tags = [];
  if (card.startHere) tags.push(["start-here", "Start here"]);
  if (card.critical_units_at_risk > 0) tags.push(["at-risk", `${card.critical_units_at_risk} critical units at risk`]);
  else if (card.priority === "critical") tags.push(["critical", "Critical order"]);
  if (card.status !== "detected") tags.push(["state", card.status]);
  return tags.slice(0, 2);
}

export function createCarousel({ root, document: doc = globalThis.document, onOpen, label = "Incident inbox", reducedMotion = () => false }) {
  root.classList.add("carousel");
  root.setAttribute("aria-roledescription", "carousel");
  root.setAttribute("aria-label", label);
  const arrow = (direction, text) => {
    const button = doc.createElement("button");
    button.type = "button";
    button.className = `carousel-arrow ${direction}`;
    button.setAttribute("aria-label", direction === "prev" ? "Previous incidents" : "Next incidents");
    button.textContent = text;
    button.addEventListener("click", () => scroll(direction === "prev" ? -1 : 1));
    return button;
  };
  const track = doc.createElement("ul");
  track.className = "carousel-track";
  track.setAttribute("aria-label", "Incidents, most urgent first");
  root.replaceChildren(arrow("prev", "‹"), track, arrow("next", "›"));

  function scroll(direction) {
    track.scrollBy({ left: direction * Math.max(220, track.clientWidth * 0.8), behavior: reducedMotion() ? "auto" : "smooth" });
  }

  const tag = (className, text) => {
    const node = doc.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  };

  function update(cards) {
    track.replaceChildren();
    for (const card of cards) {
      const item = doc.createElement("li");
      const button = doc.createElement("button");
      button.type = "button";
      button.className = "incident-card";
      button.dataset.incident = card.incident_id;
      const top = tag("incident-top", "");
      top.append(tag("incident-id", card.incident_id), ...cardTags(card).map(([className, text]) => tag(className, text)));
      const due = doc.createElement("small");
      due.textContent = `${card.kind_label} · ${card.route} · ${card.units} units · due ${formatDate(card.due_eta)}`;
      button.append(top, tag("incident-text", card.title), due);
      button.addEventListener("click", () => onOpen(card.incident_id));
      item.append(button);
      track.append(item);
    }
    root.classList.toggle("single", cards.length <= 1);
  }

  track.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const buttons = [...track.querySelectorAll("button")];
    const index = buttons.indexOf(doc.activeElement);
    if (index < 0) return;
    const next = buttons[index + (event.key === "ArrowRight" ? 1 : -1)];
    if (!next) return;
    event.preventDefault();
    next.focus();
    next.scrollIntoView({ block: "nearest", inline: "center", behavior: reducedMotion() ? "auto" : "smooth" });
  });

  return { update, track };
}
