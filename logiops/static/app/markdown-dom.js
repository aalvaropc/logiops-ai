export function inlineNodes(parts, doc = globalThis.document) {
  return parts.map((part) => {
    if (part.t === "text") return doc.createTextNode(part.v);
    const node = doc.createElement(part.t === "strong" ? "strong" : part.t === "em" ? "em" : "code");
    node.textContent = part.v;
    return node;
  });
}

export function renderMarkdown(source, { document: doc = globalThis.document, markdown = globalThis.window?.LogiOpsMarkdown } = {}) {
  const box = doc.createElement("div");
  box.className = "markdown";
  const blocks = markdown.parseBlocks(source);
  const top = Math.min(...blocks.filter((block) => block.type === "h").map((block) => block.level));
  let previous = 2;
  for (const block of blocks) {
    let node;
    if (block.type === "hr") node = doc.createElement("hr");
    else if (block.type === "h") {
      const level = Math.min(6, previous + 1, 3 + block.level - top);
      previous = level;
      node = doc.createElement(`h${level}`);
      node.append(...inlineNodes(block.inline, doc));
    } else if (block.type === "quote") {
      node = doc.createElement("blockquote");
      node.append(...inlineNodes(block.inline, doc));
    } else if (block.type === "ul" || block.type === "ol") {
      node = doc.createElement(block.type);
      for (const item of block.items) {
        const li = doc.createElement("li");
        li.append(...inlineNodes(item, doc));
        node.append(li);
      }
    } else if (block.type === "table") {
      node = doc.createElement("div");
      node.className = "table-scroll";
      node.tabIndex = 0;
      node.setAttribute("role", "region");
      node.setAttribute("aria-label", "Table from the agent's answer");
      const table = doc.createElement("table");
      node.append(table);
      const head = table.createTHead().insertRow();
      for (const cell of block.head) {
        const empty = cell.every((part) => !part.v.trim());
        const th = doc.createElement(empty ? "td" : "th");
        if (!empty) th.scope = "col";
        th.append(...inlineNodes(cell, doc));
        head.append(th);
      }
      const body = table.createTBody();
      for (const row of block.rows) {
        const tr = body.insertRow();
        for (const cell of row) tr.insertCell().append(...inlineNodes(cell, doc));
      }
    } else {
      node = doc.createElement("p");
      node.append(...inlineNodes(block.inline, doc));
    }
    box.append(node);
  }
  return box;
}
