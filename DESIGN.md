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
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.meta}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  chip-hover:
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
  lifecycle-step-done:
    backgroundColor: "{colors.ok-tint}"
    textColor: "{colors.ok}"
    rounded: "{rounded.label}"
  lifecycle-step-now:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.label}"
  shell-bar:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    height: "52px"
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
- **Label Blue** (shell): the device's shell bar, primary buttons, the mic, selected plans and cards, the start-here tag and agent-pick badge, the look-alike underline, links and the theme colour. It means "the product" or "act here", never a state.
- **Deep Label Blue** (shell-deep): hover for primary buttons only.
- **Blue Wash** (shell-tint): hover on incident cards and chips, the user's conversation turns, the current-plan line, the console boundary note.

### Secondary (state)
- **Dispensed Green** (ok) with **Green Wash** (ok-tint): on time, executed, verified, done lifecycle steps, success messages.
- **Alert Red** (late) with **Red Wash** (late-tint): late, critical units at risk, approval invalidated, errors, the active mic.
- **Caution Amber** (warn), **Amber Ink** (warn-ink) and **Amber Wash** (warn-tint): attention. Solid amber always carries ink text (the alerts bell, the critical tag, the warn band); amber washes always carry amber ink (the delayed-ETA fact, preference notes, the MCP App fallback note).

### Neutral
- **Ink** (ink): text, rules, the current lifecycle step, the send button, focus rings.
- **Graphite** (ink-2) and **Slate** (ink-3): secondary and tertiary text, labels inside facts, muted metadata.
- **Hairline** (hairline): 1 px internal dividers between rows and facts, transcript turns, the idle orb ring.
- **Label Stock** (surface): every card, panel, control and the talk dock.
- **Sunken** (sunken): secondary button hover, promise-bar track, code and table headers.
- **Cool Ground** (ground): the page and device background.
- **Desk Grey** (outer): the backdrop behind the Echo Show bezel on wide fine-pointer screens.
- **Bezel** (bezel): the hardware frame of the simulated device, desktop only.

### Named Rules
**The Band Means State Rule.** Green, red and amber are state and nothing else. A full-width band at the top of a card names the card's condition in uppercase tag type; if nothing is wrong or done, there is no band.

**The Self-Contained Card Rule.** The MCP App card renders in a sandboxed iframe and cannot load host files, so it carries its own copy of this palette (same hex values) plus a dark alternate that follows the host theme. Host-provided `--color-*`, `--font-*` and `--border-*` variables may override it; nothing else may.

**Known exception: route mode colours.** The route diagram draws legs as a data series in mode colours outside the state palette: air #6A4BB5 (dotted), express #2F6FD6, delayed #A86F00 (dashed), clearance #8F6200, with local in ok and ground in shell. They are hard-coded in the device stylesheet and are marked for a future review; do not extend them to other components.

## Typography

**Display Font:** Atkinson Hyperlegible Next (with ui-sans-serif, system-ui fallback), self-hosted variable woff2, weights 200 to 800, preloaded.
**Body Font:** the same family.

**Character:** A single hyperlegible grotesque, chosen because it separates look-alike glyphs (0/O, 1/l/I). Weight does the hierarchy work: 800 for figures, tags and buttons, 700 for titles and the spoken line, 400 for running text. Font synthesis is off.

### Hierarchy
- **Display** (800, clamp(32px, 3.4vw, 44px), 1.1, -0.02em): the console page heading only.
- **Figure** (800, clamp(28px, 2.6vw, 34px), 1.05, tabular): the one dominant number on a confirmation, receipt or result card. The MCP App card's pick cost uses the same role at 30px (26px compact).
- **Title** (700, clamp(22px, 2.4vw, 30px), 1.15, -0.01em): the card heading on the device.
- **Spoken** (700, clamp(18px, 1.6vw, 22px), 1.3): the assistant's spoken line in the dock, clamped to two lines with a More button.
- **Lead** (600, clamp(17px, 1.5vw, 20px), 1.4): the sentence under a card title.
- **Body** (400, 16px, 1.5; 15px from 768px): incident text, rows, plan names, transcript.
- **Meta** (400, 15px; 14px from 768px): secondary lines, fact labels, legends, chips.
- **Tag** (800, 12px, 0.05 to 0.08em, uppercase): state bands, outcome chips, incident tags, badges, the "simulated" stamp, speaker names.

The console uses the same family and weights at fixed desk sizes (24px panel headings, 21px metrics, 15px body, 14px meta, 12px tags) because it keeps its own layout.

### Named Rules
**The Ladder Rule.** Device sizes come from the eight ladder tokens. A new size needs a new role, not a nudge.

**The Tabular Column Rule.** Every compared figure (costs, ETAs, units, counts, receipt lines) uses tabular numerals and sits right-aligned in its own column; on the 768px facts row it switches to left-aligned columns.

## Layout

Mobile first. On a phone the device fills the viewport as a column: a 52px shell bar (safe-area aware), a four-step lifecycle strip with a 10px top margin, a scrolling card surface, and a fixed talk dock with a 2px ink top rule holding the heard line, the two-line spoken line, one horizontally scrolling row of chips, and the orb, 48px mic, field and send. Side gutters are 16px plus safe-area insets. One card shows at a time.

From 768px the gutter becomes 24px, meta and body step down a pixel (more room, denser desk reading), facts sit in a three-column row, the incident sets its promise bars beside a route-map label column of up to 380px, the plan row becomes name, figures, select, and result figures go to four columns. From 1024px with a fine pointer the device becomes a 16:10 Echo Show at up to 1180px wide inside a 10px bezel with 28px corners, centred on Desk Grey with a note underneath. Short landscape screens hide the lifecycle and heard line and clamp the spoken line to one.

The inbox is a stacked queue under a one-line heading ("4 open incidents"): one column of incident cards on phones, 10px apart, and two columns from 768px, 12px apart, with the briefing's pick first and executed incidents last. The console is a 1500px shell with 32px padding (16px under 650px): a four-column inbox, a summary strip, and a 1.65 : 0.85 workbench that stacks under 1050px.

Spacing is a loose 2px-step rhythm around 8, 12, 14 and 16px inside cards and 18 to 24px between panels. Touch targets are 44px minimum, 48px for the dock's primary controls.

## Elevation & Depth

The screen is flat. Depth is conveyed by tone (label stock on cool ground), 2px ink rules around every label, and the shell band; nothing floats. The only overlay is the conversation sheet, which rises from the bottom over a 50% ink scrim and is flat itself.

### Shadow Vocabulary
- **Hardware bezel** (`box-shadow: 0 24px 48px rgba(17, 20, 24, .28)`): the Echo Show frame on wide fine-pointer screens only. It belongs to the device hardware, not to the interface.
- **Selection ring** (`box-shadow: inset 0 0 0 2px var(--shell)`): thickens a selected plan's or pressed incident card's border to 4px of blue. It is a border, not elevation.

### Named Rules
**The Flat Screen Rule.** Nothing inside the device screen, the console or the MCP App card casts a shadow, carries a gradient or glows. The bezel is the hardware exception.

## Shapes

Two corner families and one circle. Labels (cards, panels, bands, facts, lifecycle, transcript turns, tags, chips that report outcomes) are square (0). Controls a finger presses (buttons, input fields, suggestion chips, the alerts bell, file buttons) take a gentle 6px. Circles are reserved for the mic, the orb and the connection dot. Structural edges are 2px ink; internal dividers between rows are 1px hairline; outlined tags and the "simulated" stamp use 1.5px. Empty states and the console's developer panel use a 2px dashed hairline.

## Components

### Buttons
Firm, square-shouldered, heavy-weight text.
- **Shape:** gently rounded (6px), 2px border, 48px tall on the device (44px on the console and inside the MCP App card unless compact).
- **Primary:** Label Blue fill, white 800-weight text, 18px side padding. One per card: the "yes".
- **Hover / Focus:** primary deepens to Deep Label Blue; secondary and plan Select take the Sunken fill. Focus is a 3px ink outline at 2px offset (white on the shell bar). Disabled drops to 45% opacity.
- **Secondary:** label stock with a 2px ink border; used for No, Close, Select and console actions.
- **Send:** solid ink with white text, sitting at the end of the dock.
- **Mic:** 48px Label Blue circle with a stroked SVG microphone; turns Alert Red while listening.
- **Quiet:** text-only Graphite, underline on hover, for secondary console actions.

### Chips
- **Suggestion chips:** label stock, 1.5px ink border, 6px radius, 44px tall, Meta type; one scrolling row in the dock, wrapping on the console. Hover shifts the border to Label Blue over Blue Wash.
- **Outcome chips:** square, solid green or red, white uppercase tag type; one per order row ("on time", "+18 h").
- **Incident tags:** square uppercase tags: start here (blue), at risk (red), critical (amber with ink), state (1.5px slate outline).
- **Badges:** agent pick and zero delay in blue; "your preference" in Amber Wash with Amber Ink.

### Cards / Containers
- **Corner Style:** square (0).
- **Background:** Label Stock on Cool Ground.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 2px ink.
- **Internal Padding:** 14 to 16px on the device (18px for inbox cards from 768px), 24px for console panels (18px under 650px).

### Inputs / Fields
- **Style:** label stock, 2px ink border, 6px radius, 48px tall in the dock (44px on the console), 16px text on phones to avoid zoom.
- **Focus:** 3px ink outline at 2px offset; no glow.
- **Checkboxes and radios:** native, 18 to 20px, accent Label Blue.

### Navigation
- **Shell bar:** Label Blue, white text, 52px (44px in short landscape). The wordmark is 800 weight with an outlined uppercase "simulated" stamp. Right side: the amber alerts bell, the account button (outlined white, filled white when signed in), the connection state with a 9px dot, and a tabular clock from 768px.
- **Console top bar:** 68px, separated by a 2px ink rule, a square blue monogram mark and Label Blue text links.

### State Band (signature)
A full-bleed strip at the top of a card, padded 8px 16px, uppercase tag type with 0.06em tracking: green for executed or receipt, red for critical units at risk or invalidated approval, amber with ink for a proactive alert where nothing is approved yet.

### Lifecycle Strip (signature)
Detected, Investigated, Approved, Executed in four equal cells inside a 2px ink frame with 2px ink dividers. Done steps are Green Wash with green text, the current step is solid ink with white text, future steps are slate. It sits at the same place and scale on every incident.

### Look-Alike Guard (signature)
Wherever plan names appear together (plan list, current-plan line, confirmation lead, result heading, MCP App card), each name is compared word by word with its nearest neighbour. When two names share at least two words and at least half of the name without being identical, the words that differ are set in 800 weight with a 3px Label Blue underline offset 4px. Otherwise the name stands plain.

### Facts and Promise Bars
Incident facts are a stacked list (three columns from 768px) with label, tabular value and note; the delayed ETA fact is Amber Wash with Amber Ink. Each order's promise is a 12px Sunken track with a 1px ink zero line, filled red in proportion to its delay, under the customer line and above a green or red verdict.

### Talk Dock and Orb
The dock is label stock under a 2px ink rule. The orb is a 40px circle with a 3px hairline ring and a blue core that pulses while listening or speaking and spins its ring while thinking, on cubic-bezier(.16, 1, .3, 1). All motion stops under reduced motion.

## Do's and Don'ts

### Do:
- **Do** frame every label in a 2px ink rule on white stock with square corners.
- **Do** use a full-width state band only when the card has a real state: ok, late or warn.
- **Do** emphasise the distinguishing words with the look-alike guard wherever two or more plan names can be seen together.
- **Do** set every compared number in tabular figures in a right-aligned column.
- **Do** keep one dominant figure per card at the Figure size.
- **Do** pair solid amber with ink text and amber washes with Amber Ink.
- **Do** mirror palette changes into the MCP App card's own light values and its dark alternate.

### Don't:
- **Don't** cast shadows, add gradients or glow on any screen surface; the bezel shadow is hardware only.
- **Don't** use green, red or amber for decoration, branding or emphasis that is not a state.
- **Don't** round a label; only pressable controls take the 6px radius, and only the mic, orb and status dot are circles.
- **Don't** add an uppercase line above a heading unless it is a state band carrying a real state.
- **Don't** introduce a size off the ladder or a second typeface.
- **Don't** reach for the dark operations-dashboard look with a neon accent, or the white SaaS dashboard with blue pills.
- **Don't** extend the route mode colours beyond the route diagram.
