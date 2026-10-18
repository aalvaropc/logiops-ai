---
name: LogiOps AI
description: Clinical labelling for logistics exceptions. Every decision reads like a medication label, so no one confuses two look-alike plans.
colors:
  ground: "#ECEEF1"
  outer: "#D6DAE0"
  surface: "#FFFFFF"
  sunken: "#F4F5F7"
  ink: "#111418"
  ink-2: "#454C55"
  ink-3: "#5B636D"
  rule: "#111418"
  hairline: "#C9CED5"
  shell: "#0B4F9C"
  shell-deep: "#093F7D"
  shell-ink: "#FFFFFF"
  shell-tint: "#E4ECF7"
  ok: "#1D7A3C"
  ok-tint: "#E2F1E6"
  late: "#B8102A"
  late-tint: "#FBE6E9"
  warn: "#F2A900"
  warn-ink: "#664400"
  warn-tint: "#FFF3D1"
  bezel: "#1A1D21"
  signal-ok: "#7FD49A"
  signal-late: "#FF9AA8"
  scrim: "rgba(17, 20, 24, .5)"
  focus: "#111418"
typography:
  display:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(32px, 3.4vw, 44px)"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  figure:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(28px, 2.6vw, 34px)"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  stat:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.15
    fontFeature: "tnum"
  title:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(22px, 2.4vw, 30px)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  spoken:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(18px, 1.6vw, 22px)"
    fontWeight: 700
    lineHeight: 1.3
  lead:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(17px, 1.5vw, 20px)"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  tag:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 800
    lineHeight: 1.3
    letterSpacing: "0.05em"
  console-heading:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.2
  console-metric:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  console-body:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  console-meta:
    fontFamily: "Atkinson Hyperlegible Next, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  label: "0px"
  control: "6px"
  round: "50%"
spacing:
  gutter: "16px"
  gutter-wide: "24px"
  card: "16px"
  panel: "24px"
  stack: "12px"
components:
  button-primary:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.shell-deep}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "48px"
  button-secondary-hover:
    backgroundColor: "{colors.sunken}"
  button-send:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "48px"
  button-mic:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    rounded: "{rounded.round}"
    size: "48px"
  orb-toggle:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.round}"
    size: "44px"
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.meta}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  chip-hover:
    backgroundColor: "{colors.shell-tint}"
  chip-action:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.shell}"
    typography: "{typography.meta}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  chip-action-hover:
    backgroundColor: "{colors.shell-tint}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "48px"
  label-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.label}"
    padding: "16px"
  state-band-ok:
    backgroundColor: "{colors.ok}"
    textColor: "{colors.shell-ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "8px 16px"
  state-band-late:
    backgroundColor: "{colors.late}"
    textColor: "{colors.shell-ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "8px 16px"
  state-band-warn:
    backgroundColor: "{colors.warn}"
    textColor: "{colors.ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "8px 16px"
  outcome-chip-ok:
    backgroundColor: "{colors.ok}"
    textColor: "{colors.shell-ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "3px 7px"
  outcome-chip-late:
    backgroundColor: "{colors.late}"
    textColor: "{colors.shell-ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "3px 7px"
  tag-start-here:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "3px 7px"
  tag-executed:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ok}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
    padding: "3px 7px"
  lifecycle-step-done:
    backgroundColor: "{colors.ok-tint}"
    textColor: "{colors.ok}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
  lifecycle-step-now:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    typography: "{typography.tag}"
    rounded: "{rounded.label}"
  shell-bar:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    height: "52px"
  connection-dot-ok:
    backgroundColor: "{colors.signal-ok}"
    rounded: "{rounded.round}"
    size: "9px"
  connection-dot-late:
    backgroundColor: "{colors.signal-late}"
    rounded: "{rounded.round}"
    size: "9px"
  sheet-scrim:
    backgroundColor: "{colors.scrim}"
  sheet-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.label}"
    padding: "16px"
---

# Design System: LogiOps AI

## Overview

**Creative North Star: "The Medication Label"**

Every decision surface is printed like a pharmacy label: white label stock on a cool grey ground, near-black ink, square corners, 2 px ink rules, and flat full-width colour bands that state a condition and nothing else. The design exists so that an operator glancing at a phone, an Echo Show-sized screen or a desk console cannot mistake one plan for its look-alike, cannot miss which order is late, and always knows where the incident stands in its lifecycle.

The system is flat and dense but never cramped. Hierarchy comes from weight, a fixed size ladder and a single dominant figure per card, never from depth or decoration. A label-blue shell band frames the device and carries the brand and connection state; blue otherwise marks action and selection. Green, red and amber are reserved for state. Typography is Atkinson Hyperlegible Next throughout, chosen for character disambiguation, with tabular figures in a right-aligned column wherever numbers are compared.

The world explicitly rejects the dark operations dashboard with a neon accent, and the white SaaS dashboard with blue pills. It replaces the earlier dark theme entirely; the only dark values left are the MCP App card's dark alternate, which follows the host's theme.

**Key Characteristics:**
- White label stock (#FFFFFF) on a cool grey ground, near-black ink, 2 px ink rules.
- Flat, full-width state bands: green on time, red late or critical, amber attention.
- Square-cornered labels; only interactive controls take a 6 px radius.
- No shadows, gradients or glow on the screen.
- One typeface, one size ladder, tabular right-aligned figures.
- The look-alike guard: the words that set a plan's name apart are emphasised wherever plans are named together.

## Colors

A cool, clinical neutral palette with one label-blue shell and three state colours that never decorate.

### Primary
- **Label Blue** (shell): the device's shell bar, primary buttons (including "Execute approved plan"), the mic, the outline and text of action chips, the orb's core while replies are read aloud, selected plans, the start-here tag and agent-pick badge, the look-alike underline, links and the theme colour. It means "the product" or "act here", never a state.
- **Deep Label Blue** (shell-deep): hover for primary buttons only, on the device, the console and the MCP App card's pick button.
- **Blue Wash** (shell-tint): hover on incident cards and chips, the user's conversation turns, the current-plan line, the console boundary note.

### Secondary (state)
- **Dispensed Green** (ok) with **Green Wash** (ok-tint): on time, executed, verified, done lifecycle steps, the outlined Executed tag, success messages, the alert's "Now" line when the new pick is on time.
- **Alert Red** (late) with **Red Wash** (late-tint): late, critical units at risk, approval invalidated, errors, the active mic, the alert's "Now" line when the new pick is late.
- **Caution Amber** (warn), **Amber Ink** (warn-ink) and **Amber Wash** (warn-tint): attention. Solid amber always carries ink text (the alerts bell, the critical tag, the warn band, the connecting dot); amber washes always carry amber ink (the delayed-ETA fact, preference notes, the MCP App fallback note).
- **Signal Green** (signal-ok) and **Signal Rose** (signal-late): the connected and failed states of the 9px connection dot on the shell bar, light enough to read on Label Blue. They exist only on the shell; everywhere on label stock the full-strength green and red carry state.

### Neutral
- **Ink** (ink): text, rules, the current lifecycle step, the send button, focus rings.
- **Graphite** (ink-2) and **Slate** (ink-3): secondary and tertiary text, labels inside facts, muted metadata; Graphite carries the alert's "Was" line and Slate the orb's core while read-aloud is off.
- **Hairline** (hairline): 1 px internal dividers between rows and facts, transcript turns, trace steps, the idle orb ring.
- **Label Stock** (surface): every card, panel, control, the talk dock and the conversation sheet.
- **Sunken** (sunken): secondary button hover, promise-bar track, code and table headers.
- **Cool Ground** (ground): the page and device background.
- **Desk Grey** (outer): the backdrop behind the Echo Show bezel on wide fine-pointer screens.
- **Bezel** (bezel): the hardware frame of the simulated device, desktop only.
- **Ink Scrim** (scrim): the half-ink veil behind the conversation sheet, inside the device.

### Named Rules
**The Band Means State Rule.** Green, red and amber are state and nothing else. A full-width band at the top of a card names the card's condition in uppercase tag type; if nothing is wrong or done, there is no band.

**The Self-Contained Card Rule.** The MCP App card renders in a sandboxed iframe and cannot load host files, so it carries its own copy of this palette (same hex values), its own copy of the size ladder as local variables, and its own Atkinson Hyperlegible Next, which the server inlines as a data: font that the sandbox policy allows; a dark alternate follows the host theme. Host-provided `--color-*`, `--font-*` and `--border-*` variables may override it; nothing else may.

**Known exception: route mode colours.** The route diagram draws legs as a data series in mode colours outside the state palette: air #6A4BB5 (dotted), express #2F6FD6, delayed #A86F00 (dashed), clearance #8F6200, with local in ok and ground in shell. They are hard-coded in the device stylesheet and are marked for a future review; do not extend them to other components.

## Typography

**Display Font:** Atkinson Hyperlegible Next (with ui-sans-serif, system-ui fallback), self-hosted variable woff2, weights 200 to 800, preloaded. The MCP App card embeds the same file as a data: font.
**Body Font:** the same family.

**Character:** A single hyperlegible grotesque, chosen because it separates look-alike glyphs (0/O, 1/l/I). Weight does the hierarchy work: 800 for figures, tags and buttons, 700 for titles, stats and the spoken line, 400 for running text. Font synthesis is off.

### Hierarchy
- **Display** (800, clamp(32px, 3.4vw, 44px), 1.1, -0.02em): the console page heading only.
- **Figure** (800, clamp(28px, 2.6vw, 34px), 1.05, tabular): the one dominant number on a confirmation, receipt or result card. The MCP App card's pick cost uses the same role, with tabular slashed-zero numerals.
- **Title** (700, clamp(22px, 2.4vw, 30px), 1.15, -0.01em): the card heading on the device, the home heading ("4 open incidents") and the plans heading.
- **Stat** (700, 20px, tabular): secondary numbers that sit below the one Figure: incident ids in queue cards (800), fact values, the session strip, plan figures, the result card's four execution numbers, and the conversation sheet heading.
- **Spoken** (700, clamp(18px, 1.6vw, 22px), 1.3): the assistant's spoken line in the dock, clamped to two lines with a More button; tapping the line expands it in place up to 38vh, and the next reply collapses it.
- **Lead** (600, clamp(17px, 1.5vw, 20px), 1.4): the sentence under a card title, queue-card text from 768px, the result figure's label.
- **Body** (400, 16px, 1.5): incident text, rows, plan names, transcript, the home greeting.
- **Meta** (400, 15px): secondary lines, fact labels, legends, chips, trace summaries.
- **Tag** (800, 12px, 0.05 to 0.08em, uppercase): state bands, outcome chips, incident tags, badges, the "simulated" stamp, speaker names. The lifecycle strip uses the tag size in sentence case.

Between 768px and the Echo Show, body steps down to 15px and meta to 14px for denser desk reading; on the Echo Show (1024px and a fine pointer) they return to 16px and 15px, and phones keep them there too. The MCP App card mirrors the ladder locally: 15px body and 14px meta by default, 16px and 15px in its compact mode.

The console uses the same family and weights at its own fixed desk sizes, recorded as the console roles: 24px panel headings, 21px metrics, 15px body, 14px meta, and the shared 12px tag. They are the console's ladder, not nudges of the device ladder.

### Named Rules
**The Ladder Rule.** Device sizes come from the eight ladder tokens (tag, meta, body, lead, stat, title, figure, spoken). A new size needs a new role, not a nudge.

**The Tabular Column Rule.** Every compared figure (costs, ETAs, units, counts, receipt lines) uses tabular numerals and sits right-aligned in its own column; on the 768px facts row it switches to left-aligned columns.

## Layout

Mobile first. On a phone the device fills the viewport as a column: a 52px shell bar (safe-area aware), a four-step lifecycle strip with a 10px top margin, a scrolling card surface, and a fixed talk dock with a 2px ink top rule holding the heard line, the two-line spoken line, one horizontally scrolling row of chips, and the 44px orb toggle, 48px mic, field and send. Side gutters are 16px plus safe-area insets. One card shows at a time. Under 480px an alerts bell shortens to "N alert(s)" and, while a bell shows, the connection keeps only its dot. Under 400px the lifecycle cells size to their content instead of splitting the width equally, and Send becomes a 48px arrow icon.

Home is a stacked queue: a Title heading ("4 open incidents") and a one-line greeting, then an ordered list of incident cards, one column on phones 10px apart and two columns from 768px 12px apart, then the session strip of outcome stats (two columns on phones, wrapping 130px tiles from 768px).

From 768px the gutter becomes 24px, facts sit in a three-column row, the incident sets its promise bars beside a route-map label column of up to 380px, the plan row becomes name, figures, select, and the result card's four stats go to four columns. From 900px wide, whatever the pointer, the confirmation, receipt, alert and result cards drop their width cap and become two-column labels: the decision column (heading, lead, figure, notes) on the left and the evidence column (rows, plan lines, stats) on the right, 32px apart; below 900px the two columns stack. From 1024px with a fine pointer the device becomes a 16:10 Echo Show at up to 1180px wide inside a 10px bezel with 28px corners, centred on Desk Grey with a stage note underneath that carries the console link and the "Dark plans card" developer toggle. Short landscape screens hide the lifecycle and heard line and clamp the spoken line to one.

The console is a 1500px shell with 32px padding (16px under 650px): a four-column inbox (two under 1050px, one under 650px), a summary strip, and a 1.65 : 0.85 workbench that stacks under 1050px.

Spacing is a loose 2px-step rhythm around 8, 12, 14 and 16px inside cards and 18 to 24px between panels. Touch targets are 44px minimum, 48px for the dock's primary controls.

## Elevation & Depth

The screen is flat. Depth is conveyed by tone (label stock on cool ground), 2px ink rules around every label, and the shell band; nothing floats. The only overlay is the conversation sheet, which lives inside the device (within the bezel on desktop) over the Ink Scrim and is flat itself; while it is open the rest of the device and the stage note are inert.

### Shadow Vocabulary
- **Hardware bezel** (`box-shadow: 0 24px 48px rgba(17, 20, 24, .28)`): the Echo Show frame on wide fine-pointer screens only. It belongs to the device hardware, not to the interface.
- **Selection ring** (`box-shadow: inset 0 0 0 2px var(--shell)`): thickens a selected plan's or pressed console incident card's border to 4px of blue. It is a border, not elevation.

### Named Rules
**The Flat Screen Rule.** Nothing inside the device screen, the console or the MCP App card casts a shadow, carries a gradient or glows. The bezel is the hardware exception.

## Shapes

Two corner families and one circle. Labels (cards, panels, bands, facts, lifecycle, transcript turns, trace steps, the sheet, tags, chips that report outcomes) are square (0). Controls a finger presses (buttons, input fields, suggestion and action chips, the alerts bell, the account button, file buttons) take a gentle 6px. Circles are reserved for the mic, the orb and the connection dot. Structural edges are 2px ink; internal dividers between rows are 1px hairline; outlined tags and the "simulated" stamp use 1.5px; action chips use a 2px Label Blue outline. Empty states and the console's developer panel use a 2px dashed hairline.

## Components

### Buttons
Firm, square-shouldered, heavy-weight text.
- **Shape:** gently rounded (6px), 2px border, 48px tall on the device (44px on the console and inside the MCP App card unless compact).
- **Primary:** Label Blue fill, white 800-weight text, 18px side padding. One per card: the "yes", or "Execute approved plan" in the plans header and on a receipt when the plan is approved but has not run.
- **Hover / Focus:** primary deepens to Deep Label Blue; secondary and plan Select take the Sunken fill. Focus is a 3px ink outline at 2px offset (white on the shell bar, inset on the scrolling surface). Disabled drops to 45% opacity.
- **Secondary:** label stock with a 2px ink border; used for No, Keep it, Close, Select, More, "Open printable receipt", "See N more plans" and console actions.
- **Send:** solid ink with white text, sitting at the end of the dock; under 400px a 48px stroked SVG arrow replaces the word and the accessible name stays "Send".
- **Mic:** 48px Label Blue circle with a stroked SVG microphone; turns Alert Red while listening.
- **Quiet:** text-only Graphite, underline on hover, for secondary console actions.
- **Stage toggle:** the "Dark plans card" developer switch in the desktop stage note, 32px, 1.5px slate outline, filled ink when pressed.

### Chips
- **Question chips:** label stock, 1.5px ink border, 6px radius, 44px tall, Meta type at 600; one scrolling row in the dock, wrapping on the console. Hover shifts the border to Label Blue over Blue Wash.
- **Action chips:** the chips that act rather than ask (approve the recommended plan, approve the new pick, book and pay, execute approved plan) take a 2px Label Blue outline and Label Blue 800 text, so a tap that changes state never looks like a question. While a plan is approved and not executed, "Execute approved plan" leads the chips on the plans card and on a receipt booked before execution, alongside the primary button.
- **Outcome chips:** square, solid green or red, white uppercase tag type; one per order row ("on time", "+8 h late").
- **Incident tags:** square uppercase tags, at most two per card: start here (blue), critical units at risk (red), critical order (amber with ink), and the investigated or approved state as words in a 1.5px slate outline. An executed incident shows only the Executed tag, a 1.5px green outline with green text, which outranks start here.
- **Badges:** agent pick and zero delay in blue; "your preference" in Amber Wash with Amber Ink.

### Cards / Containers
- **Corner Style:** square (0).
- **Background:** Label Stock on Cool Ground.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 2px ink.
- **Internal Padding:** 14 to 16px on the device (18px for queue cards from 768px), 24px for console panels (18px under 650px).
- **Two-column labels:** from 900px wide the confirmation, receipt, alert and result cards split into a decision column and an evidence column under one band; below 900px they stack in that order.
- **Confirmation card:** heading, the plan name as the lead, one Figure, then the rows and a slate note, with the primary yes and a secondary no. Approval ("Yes, approve" / "No"), payment and withdrawal ("Withdraw this approval?", "Yes, withdraw" / "Keep it") share it; a red band appears only when the plan leaves a critical order late.
- **Queue cards:** whole-card buttons with the incident id at Stat size, up to two tags, the incident text and a meta line; hover takes Blue Wash.

### Inputs / Fields
- **Style:** label stock, 2px ink border, 6px radius, 48px tall in the dock (44px on the console), 16px text on phones to avoid zoom.
- **Focus:** 3px ink outline at 2px offset; no glow.
- **Checkboxes and radios:** native, 18 to 20px, accent Label Blue.

### Navigation
- **Shell bar:** Label Blue, white text, 52px (44px in short landscape). The wordmark is 800 weight with an outlined uppercase "simulated" stamp. Right side: the amber alerts bell ("N alert(s) · incident", shortened to "N alert(s)" under 480px), the account button (outlined white, filled white when signed in), the connection state with a 9px dot (amber connecting, Signal Green connected, Signal Rose failed), and a tabular clock from 768px.
- **Console top bar:** 68px, separated by a 2px ink rule, a square blue monogram mark and Label Blue text links.

### State Band (signature)
A strip at the top of a card, padded 8px 16px, uppercase tag type with 0.06em tracking. On confirmation, receipt, alert and result cards it bleeds to the card edges; on the incident it sits as its own strip above the heading. Green for a receipt or a verified execution; red for critical units at risk, a late plan or an invalidated approval; amber with ink for a proactive alert where nothing is approved yet. On the incident the band follows the decision: amber "Approved · N critical units projected on time once executed" while an on-time plan waits to run, green "Executed · …" once it has run on time, red whenever the decided plan leaves units late or nothing is decided and critical units are at risk.

### Lifecycle Strip (signature)
Detected, Investigated, Approved, Executed in four cells inside a 2px ink frame with 2px ink dividers, in 800-weight tag-size type. Done steps are Green Wash with green text, the current step is solid ink with white text, future steps are slate. It sits at the same place and scale on every incident.

### Look-Alike Guard (signature)
Wherever plan names appear together (plan list, current-plan line, confirmation lead, alert plan lines, MCP App card), each name is compared word by word with its nearest neighbour. When two names share at least two words and at least half of the name without being identical, the words that differ are set in 800 weight with a 3px Label Blue underline offset 4px. Otherwise the name stands plain. The result heading names the executed plan alone and always stands plain.

### Facts and Promise Bars
Incident facts are a stacked list (three columns from 768px) with label, a Stat-size tabular value and note; the delayed ETA fact is Amber Wash with Amber Ink. Each late order's promise is a 12px Sunken track with a 1px ink zero line, filled red in proportion to its delay, under the customer line and above a red verdict. On-time orders hide the empty track and keep only the green verdict. Before investigation each affected order is listed with its customer, units and critical-order tag over a Graphite "Promised … · no plan yet" verdict in regular weight, with no track. The amber critical-order tag never wraps.

### Result, Receipt and Alert Cards
The result card opens with the green "Executed · operationally verified" band, the plan name as the Title, and the incident as the lead. It then carries one Figure ("12 critical units on time", with the label at Lead size and a slate "projected"), followed by order rows that end in outcome chips. The four execution numbers (units accounted for, extra cost, notifications simulated, customer delay) follow as Stat-size secondary figures over hairline rules. The receipt shows the paid total as its Figure, then rows that start with the "Carriers and services" subtotal and indent its paid lines beneath it in slate Meta type without a rule, then fees, and a total row in 800 weight over a 2px ink rule. The alert card opens with an amber band (red once an approval is invalidated), a "Heads up on" Title and a one-line lead built from the change; its evidence column carries a Graphite "Was …" line above an 800-weight "Now …" line on Green Wash with green text when the new pick is on time, or on Red Wash with red text when it is late.

### Conversation Sheet
A dialog inside the device: bottom-anchored with a 2px ink top rule on phones, a centred 2px-ink-framed panel up to 860px wide from 768px. Its heading is Stat size with a secondary Close beside it; the read-aloud checkbox sits on its own row beneath. Turns cap at min(92%, 72ch). Each assistant reply carries its own tool trace as a disclosure under it: a hairline rule, a 700 Meta summary, and square hairline step tiles (green for a skill, red for an error) that rise in on a 120ms stagger.

### MCP App Card
The plan picker as an MCP App, self-contained (see The Self-Contained Card Rule). The pick leads with a green or red state band, the name at Lead size with up to two tags (agent or default pick outlined in blue, approved or executed outlined in green, your preference in Amber Wash), the cost as the Figure, order outcomes as chips, and a primary "Select for approval" button until a plan is approved. The remaining plans follow with the pick's nearest look-alike first; in compact mode only that one shows, with a "See N more plans" button for the rest. All figures use tabular slashed-zero numerals.

### Talk Dock and Orb
The dock is label stock under a 2px ink rule. The orb is a 44px circular button, the "Read replies aloud" toggle (pressed state exposed): a 3px hairline ring around a Label Blue core when on and a Slate core when off; it is disabled, showing the off core, where no voice exists. It still reports listening, thinking and speaking: the ring turns blue, the core pulses while listening or speaking and the ring spins while thinking, on cubic-bezier(.16, 1, .3, 1). All motion stops under reduced motion.

### Forced Colours
Under forced colours the current lifecycle step takes Highlight with HighlightText, done steps are underlined, the promise fill becomes CanvasText, state bands, outcome chips and incident tags gain a 1px CanvasText border, action chips thicken to a 3px border, Send and the mic gain a 1px ButtonText outline, and the route map's places, labels and legs draw in CanvasText, so no state rides on colour alone.

## Do's and Don'ts

### Do:
- **Do** frame every label in a 2px ink rule on white stock with square corners.
- **Do** use a full-width state band only when the card has a real state: ok, late or warn.
- **Do** emphasise the distinguishing words with the look-alike guard wherever two or more plan names can be seen together.
- **Do** set every compared number in tabular figures in a right-aligned column.
- **Do** keep one dominant figure per card at the Figure size; supporting numbers take the Stat size.
- **Do** pair solid amber with ink text and amber washes with Amber Ink.
- **Do** give chips that change state the 2px Label Blue outline; questions keep the 1.5px ink border.
- **Do** mirror palette and ladder changes into the MCP App card's own light values, its dark alternate and its local size variables.

### Don't:
- **Don't** cast shadows, add gradients or glow on any screen surface; the bezel shadow is hardware only.
- **Don't** use green, red or amber for decoration, branding or emphasis that is not a state.
- **Don't** use Signal Green or Signal Rose anywhere but the shell bar.
- **Don't** round a label; only pressable controls take the 6px radius, and only the mic, orb and status dot are circles.
- **Don't** add an uppercase line above a heading unless it is a state band carrying a real state.
- **Don't** introduce a size off the ladder or a second typeface.
- **Don't** reach for the dark operations-dashboard look with a neon accent, or the white SaaS dashboard with blue pills.
- **Don't** extend the route mode colours beyond the route diagram.
