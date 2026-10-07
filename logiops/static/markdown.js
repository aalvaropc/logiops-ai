"use strict";
// A small, safe Markdown subset for the model's replies: headings, rules, quotes, lists,
// tables, **bold**, *italic* and `code`. It only parses; demo.js builds DOM nodes from the
// result with textContent, so nothing the model writes is ever treated as HTML.
(function (root) {
  const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/;

  function parseInline(text) {
    return text.split(INLINE).filter(Boolean).map((part) => {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return { t: "strong", v: part.slice(2, -2) };
      if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return { t: "code", v: part.slice(1, -1) };
      if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return { t: "em", v: part.slice(1, -1) };
      return { t: "text", v: part };
    });
  }

  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const isSeparator = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

  function parseBlocks(source) {
    const lines = String(source).replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      let match;
      if (!line.trim()) { i += 1; continue; }
      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { blocks.push({ type: "hr" }); i += 1; continue; }
      if ((match = line.match(/^(#{1,6})\s+(.*)$/))) {
        blocks.push({ type: "h", level: Math.min(match[1].length + 1, 6), inline: parseInline(match[2]) });
        i += 1; continue;
      }
      if (/^\s*>/.test(line)) {
        const quoted = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { quoted.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
        blocks.push({ type: "quote", inline: parseInline(quoted.join(" ")) });
        continue;
      }
      if (line.trim().startsWith("|") && i + 1 < lines.length && isSeparator(lines[i + 1])) {
        const head = cells(line).map(parseInline);
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim().startsWith("|")) { rows.push(cells(lines[i]).map(parseInline)); i += 1; }
        blocks.push({ type: "table", head, rows });
        continue;
      }
      if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const marker = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        const items = [];
        while (i < lines.length && marker.test(lines[i])) { items.push(parseInline(lines[i].replace(marker, ""))); i += 1; }
        blocks.push({ type: ordered ? "ol" : "ul", items });
        continue;
      }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*>|\s*[-*+]\s|\s*\d+[.)]\s|\s*\|)/.test(lines[i])
             && !/^\s*([-*_])\1{2,}\s*$/.test(lines[i])) {
        paragraph.push(lines[i]); i += 1;
      }
      if (!paragraph.length) { paragraph.push(line); i += 1; }
      blocks.push({ type: "p", inline: parseInline(paragraph.join("\n")) });
    }
    return blocks;
  }

  // What a screen reader or the speech synthesis should say: the words without the markup.
  function plainText(source) {
    const flat = (inline) => inline.map((part) => part.v).join("");
    return parseBlocks(source).map((block) => {
      if (block.type === "hr") return "";
      if (block.type === "ul" || block.type === "ol") return block.items.map(flat).join(". ");
      if (block.type === "table") return block.rows.map((row) => row.map(flat).join(", ")).join(". ");
      return flat(block.inline);
    }).filter(Boolean).join(". ").replace(/\s+/g, " ").trim();
  }

  const api = { parseBlocks, parseInline, plainText };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LogiOpsMarkdown = api;
})(typeof window !== "undefined" ? window : globalThis);
