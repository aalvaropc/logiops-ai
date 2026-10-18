export function parseSse(buffer) {
  const blocks = buffer.replaceAll("\r\n", "\n").split("\n\n");
  const rest = blocks.pop();
  const events = [];
  for (const block of blocks) {
    let kind = "message";
    const data = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) kind = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (data.length) events.push([kind, JSON.parse(data.join("\n"))]);
  }
  return { events, rest };
}
