import { formatDate } from "../app/selectors.js";
import { cardTags } from "./surfaces.js";

export function createQueue({ root, document: doc = globalThis.document, onOpen, labelledBy = null }) {
  const list = doc.createElement("ol");
  list.className = "queue";
  if (labelledBy) list.setAttribute("aria-labelledby", labelledBy);
  root.replaceChildren(list);

  const tag = (className, text) => {
    const node = doc.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  };

  function update(cards) {
    list.replaceChildren();
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
      list.append(item);
    }
  }

  return { update, list };
}
