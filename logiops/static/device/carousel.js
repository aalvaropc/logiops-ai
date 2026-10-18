import { formatDate } from "../app/selectors.js";
import { cardTags } from "./surfaces.js";

const SVG = "http://www.w3.org/2000/svg";

export function createCarousel({ root, document: doc = globalThis.document, onOpen, label = "Incident inbox", reducedMotion = () => false }) {
  root.classList.add("carousel");
  root.setAttribute("aria-roledescription", "carousel");
  root.setAttribute("aria-label", label);
  const arrow = (direction) => {
    const button = doc.createElement("button");
    button.type = "button";
    button.className = `carousel-arrow ${direction}`;
    button.setAttribute("aria-label", direction === "prev" ? "Previous incidents" : "Next incidents");
    const icon = doc.createElementNS(SVG, "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    const path = doc.createElementNS(SVG, "path");
    path.setAttribute("d", direction === "prev" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7");
    icon.append(path);
    button.append(icon);
    button.addEventListener("click", () => scroll(direction === "prev" ? -1 : 1));
    return button;
  };
  const track = doc.createElement("ul");
  track.className = "carousel-track";
  track.setAttribute("aria-label", "Incidents, most urgent first");
  root.replaceChildren(arrow("prev"), track, arrow("next"));

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
