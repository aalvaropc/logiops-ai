export const CAPABILITIES_TEXT = "I'm LogiOps, your operations desk for late or held shipments. I can:\n"
  + "- brief your queue: say “any delays today?”;\n"
  + "- investigate an incident and compare its plans: “what's happening with SHIP-433?”;\n"
  + "- answer follow-ups from that investigation: “why not the cheaper one?”;\n"
  + "- remember preferences for every incident: “remember my spend cap is $250”;\n"
  + "- approve a plan after reading it back, then execute it: “approve the recommended plan”, “yes”, “execute it”;\n"
  + "- change your mind before it runs: “withdraw the approval” resets the incident so you can choose again;\n"
  + "- book and pay a plan's carriers after reading back the price with tax, with a receipt: “book it”, “yes”;\n"
  + "- go back to a card: “show the incident”, “show the plans”, or to your queue: “back to the queue”;\n"
  + "- start over at any time: “start over”.\n"
  + "Every answer is checked against the incident's data, and only you can approve.";

export const CAPABILITIES_SPOKEN = "I can brief your queue, investigate an incident and compare plans, remember your preferences, approve and execute a plan, and book and pay its carriers after reading the price back to you. Try: any delays today?";

export const FRESH_INVESTIGATION = /\b(investigate|re-?check|refresh|start again|what(?:'s| is) happening)\b/;
