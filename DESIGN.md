---
name: LogiOps AI
description: Long Exposure. Late shipments, plans and agent steps drawn as light trails on a night road.
colors:
  ground: "#07090D"
  outer: "#040507"
  surface: "#0D1118"
  sunken: "#151B25"
  ink: "#F4F1E8"
  ink-2: "#C9C4B6"
  ink-3: "#8A97AB"
  rule: "#3A4352"
  hairline: "#232A35"
  shell: "#F4F1E8"
  shell-deep: "#D8D3C6"
  shell-ink: "#07090D"
  shell-tint: "#1A212C"
  late: "#FF453A"
  late-tint: "#2A1214"
  warn: "#FFB224"
  warn-tint: "#2A2110"
  bezel: "#1C2129"
  scrim: "rgba(0, 0, 0, .62)"
typography:
  hero:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(64px, min(19vw, 12vh), 112px)"
    fontWeight: 800
    lineHeight: 0.9
    letterSpacing: "-0.04em"
    fontFeature: "tnum"
  hero-small:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(52px, min(15vw, 10vh), 88px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.04em"
    fontFeature: "tnum"
  display:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(34px, 9vw, 48px)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
    fontFeature: "tnum"
  title:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(26px, 3vw, 36px)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  figure:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(28px, 2.6vw, 34px)"
    fontWeight: 800
    lineHeight: 1
    fontFeature: "tnum"
  spoken:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(18px, 1.6vw, 22px)"
    fontWeight: 700
    lineHeight: 1.3
  lead:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(17px, 1.5vw, 20px)"
    fontWeight: 600
    lineHeight: 1.4
  stat:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 800
    fontFeature: "tnum"
  body:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.4
  meta:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  tag:
    fontFamily: "Overpass, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 800
    letterSpacing: "0.06em"
rounded:
  label: "0"
  soft: "12px"
  panel: "16px"
  sheet: "20px"
  pill: "999px"
spacing:
  gutter: "16px"
  gutter-wide: "24px"
components:
  button-primary:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.shell-deep}"
    textColor: "{colors.shell-ink}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 22px"
    height: "48px"
  button-secondary-hover:
    backgroundColor: "{colors.sunken}"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "44px"
  chip-hover:
    backgroundColor: "{colors.shell-tint}"
  chip-action:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.shell-ink}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "44px"
  input-ask:
    backgroundColor: "{colors.sunken}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "48px"
  plan-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "16px"
  dock:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    padding: "14px 16px 12px"
  sheet:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
---

# Design System: LogiOps AI

## Overview

**Creative North Star: "Long Exposure"**

Every route, plan and agent step is a trail of light across a night road, and the recommended path is the brightest one. The ground is night asphalt with no boxed cards and no glowing chrome; light only ever draws data. Headlight white means recommended, on time, executed and primary; taillight red means late; sodium amber means attention. Each screen carries one enormous figure in tabular numerals, small labels, and little in between.

One system serves three surfaces: the simulated Alexa+ device (`/demo`, phone first, then an Echo Show-like 16:10 screen in a bezel on desktop), the MCP App plans card (dark by default, light when the host asks for it), and the operator console (`/console`, desk density). The device tokens live in `logiops/static/tokens.css`; the device type ladder lives in `logiops/static/device.css`. The card is a sandboxed iframe and repeats the dark values in its own `:root`.

**Key Characteristics:**
- Dark only on the device and console (`color-scheme: dark`); the card alone has a light alternative.
- Colour lives inside the data: trails, dots, figures, state phrases. Chrome stays night grey.
- Late is always told twice: red and dashed.
- One hero figure per screen; hierarchy by scale, not by boxes.
- Data drawings are pure builders (`journey.js`, `field.js`, `route.js`) rendered as SVG with a spoken sentence and an accessible list beside them.

## Colors

A near-black ground, warm headlight white for everything that is good or chosen, one red, one amber, and blue-grey chrome. There is no green and no second accent.

### Primary
- **Headlight White** (`ink`, also `shell`): primary text, the recommended plan, on-time verdicts, executed states, the filled primary button, the pick ring on the decision field, lit trails. The tokens `--ok`, `--focus` and `--signal-ok` alias this same value; use them where the meaning is "on time", "focus" or "connected" so intent stays readable.
- **Worn Headlight** (`shell-deep`): hover state of filled controls only.
- **Asphalt Ink** (`shell-ink`): text on any filled headlight control.

### Secondary
- **Taillight Red** (`late`, alias `--signal-late`): late, at risk, failed checks, the active mic. Data only, and always paired with a dash pattern or dashed underline. Never a fill for chrome.
- **Brake Glow Tint** (`late-tint`): background of the error message line only.

### Tertiary
- **Sodium Amber** (`warn`, alias `--warn-ink`): attention. Critical-order tags, the user's preference badge, the alerts bell, the "connecting" dot, the warm middle of the agent comet and the thinking light bar.
- **Sodium Tint** (`warn-tint`): background of the MCP note and console preference/state lines.

### Neutral
- **Night Asphalt** (`ground`): every screen's background; also the inside of hollow markers so they read as holes in the light.
- **Outer Dark** (`outer`): the page behind the bezel on desktop.
- **Night Blue** (`surface`): the dock, plan rows, sheet, MCP frame, and hover on queue rows. The only lifted plane.
- **Sunken** (`sunken`): input field, chat turns, secondary hover, code.
- **Shell Tint** (`shell-tint`, alias `--ok-tint`): hover of outlined chips, the user's own chat turn.
- **Moonlight** (`ink-2`): secondary text, place labels, promise ticks.
- **Slate Moonlight** (`ink-3`): tertiary text, outlined control borders, done/settled lanes, "some late" dots.
- **Rule** (`rule`): ghost trails, the agent track, axis lines.
- **Hairline** (`hairline`): 1px dividers, unlit track and lifecycle segments, the idle voice bar.
- **Bezel** (`bezel`): the 10px Echo Show frame on desktop only.
- **Scrim** (`scrim`): behind the conversation sheet.

### Named Rules
**The Light Draws Data Rule.** Red, amber and the glow are reserved for marks that encode the incident. Chrome (bars, borders, rules) uses only `ink-3`, `rule` and `hairline`.

**The Two Signals Rule.** Late is red and dashed: trails at `2 6`, lane tails at `3 5`, track overruns and plan lines as repeating 6px dashes, tags with a 2px dashed underline. A reader without colour still sees it.

**The No Green Rule.** On time is headlight white, never green. There is no green token on the device or the console.

## Typography

**Display Font:** Overpass (with ui-sans-serif, system-ui fallback)
**Body Font:** Overpass
**Label Font:** Overpass, uppercase, letter-spaced

**Character:** Highway-sign type. Overpass is self-hosted as a variable latin subset (`logiops/static/fonts/overpass-latin.woff2`, weights 100-900, SIL OFL), preloaded on the device and embedded into the MCP card under its own name. `font-synthesis: none`; every figure uses tabular numerals.

### Hierarchy
- **Hero** (800, `--type-hero`, 0.9): the one enormous figure on home, confirm, result and receipt totals.
- **Hero small** (800, `--type-hero-small`, 0.95): the incident figure, which shares the screen with a map.
- **Display** (700, `--type-display`): the incident ID heading.
- **Title** (700, `--type-title`): card headings and the agent's question on the stage.
- **Figure** (800, `--type-figure`): the card's pick cost and the stage's elapsed seconds while asking.
- **Spoken** (700, `--type-spoken`, 1.3): the assistant's spoken sentence in the dock, clamped to 2 lines (3 below 480px, 1 in short landscape).
- **Lead** (600-700, `--type-lead`): hero captions, plan names, the brand.
- **Stat** (800, `--type-stat`): queue IDs and plan costs.
- **Body / Meta** (`--type-body`, `--type-meta`): text and secondary facts. Both drop to 15/14px between 768 and 1023px and return to 16/15px on fine-pointer desktops. A touch screen of 1024px or more (a real Echo Show, read from arm's length) uses 18/16px, and tags 14px.
- **Tag** (800, `--type-tag`, 0.06em, uppercase): tags, verdicts, lane keys, the lifecycle stop names (700, sentence case).

### Named Rules
**The Ladder Rule.** In `device.css` every size comes from a `--type-*` token. Only SVG map labels (in viewBox units) and the 16px input (to stop zoom) are literal.

**The One Figure Rule.** One hero-sized number per screen. Everything else sits at body scale or below; nothing in between competes.

## Layout

- **Device frame:** a column of night bar (min 52px), lifecycle trail, scrolling surface, dock. Full viewport (`100dvh`) on phones with safe-area insets; on `min-width: 1024px` with a fine pointer it becomes a 16:10 screen up to 1180px wide inside a 10px bezel, centred on `outer`, with a one-line stage note underneath.
- **Gutter:** 16px, 24px from 768px.
- **Two columns from 900px:** home puts the hero and lanes left, the queue right; the incident puts the map and its figure left, the heading and time tracks right; confirm, alert and result split text left and rows right.
- **Budgets:** one figure per screen; at most two bordered or filled boxes visible on a device screen; under about 40 words per screen; confirm and result fit the Echo Show viewport without scrolling (the surface fade mask is switched off on confirm). On phones below 480px the confirm actions stick to the bottom.
- **Console:** 1500px shell, 32px padding (16px below 650px); a workbench of 1.65fr / 0.85fr that stacks below 1050px.
- **Density:** secondary facts sit tight on one line joined by middle dots; rows separate with 1px hairlines rather than gaps or boxes.

## Elevation & Depth

Flat. Depth comes from light, not shadow: a lit trail sits on dark ground, a hollow marker reads as a hole, settled data dims to `ink-3`. The only lifted plane is `surface` (the dock, plan rows, sheet). Two real shadows exist: the desktop bezel's neutral drop (`0 24px 48px rgba(17,20,24,.28)`), and the inset 2px headlight ring on a selected plan row. Blur appears only on data marks (an SVG Gaussian blur under lit trails and the decision pick, and a 5px blur on the agent comet). Forced colours hide every glow.

**The Glow Belongs To Data Rule.** Glow is an SVG filter on a lit mark at reduced opacity (0.35 trails, 0.45 pick). Never a coloured `box-shadow` on a control or container.

## Shapes

Pills for everything you press (999px); soft 12px for message lines and queue-row hover; 16px for plan rows, chat turns and the MCP frame; 20px for the sheet top (all corners at 768px and up). Square (0) for quoted blocks and the "simulated" badge. Data marks are round: 2-4px stroke trails with round caps, dot stations, circular stops. Borders are 1.5px `ink-3` on outlined controls and 1px `hairline` on dividers.

## Components

### Lifecycle trail
Four stops (Detected, Investigated, Approved, Executed) on a 2px line. Done stops are filled headlight dots on a lit segment; the current stop is a larger 14px dot with a half-lit segment and `aria-current="step"`; future stops are hollow `ink-3` rings on hairline. Hidden in short landscape.

### Voice light bar
A 3px bar along the top edge of the dock, driven by `data-voice` on the dock: `ready` is hairline; `listening` breathes headlight white (1.6s); `thinking` runs an amber-white comet across the bar (1.5s); `speaking` pulses its width from the centre (0.45s). The state is also spoken in text by the orb label (`role="status"`).

### Home lanes
All open incidents on one time scale (`queueTrails`): each lane leaves a hub, runs lit to its promise tick, then continues as a red dashed tail to its projected arrival with `+N h`. At-risk lanes are thicker; verified lanes dim to `ink-3` and read "done". A key shows the promise tick and the dash. The queue below is a hairline-divided list, not cards.

### Wide map
`wideLayout` places origin bottom-left and destination top-right in a 360 x 156 view. Each plan leg is a curved trail with its own bend, labelled once in uppercase (`Air freight · 12`) at a computed spot; late legs are red and dashed, on-time legs are white over a soft glow; the booked route remains as a ghost dashed `rule` line. Origin and sources are hollow stops, the destination a filled one. A visually hidden list repeats every leg in words.

### Time tracks
One shared time scale for the shipment and each order (`promiseTracks`). A hairline track, a lit gradient up to arrival or promise, a 2px promise tick, an end dot, and for late orders a red dashed overrun past the tick with a red dot. Each track sits under the customer's name and over a verdict line ("On time · promised ...", "+8 h · 18 units late ...").

### Agent stage
Covers the surface while the agent works. The question in title type, then a vertical rule track where an amber-to-white comet falls (1.5s) until the first tool returns. Stations (Shipment, Orders, Stock, Quotes, Plans, Checked) append as dots on a lit line at a 120ms cadence; errors are red; the final check is a hollow ring (red if it failed). The caption shows elapsed seconds at figure size while asking, then a one-line summary. The stage leaves by wiping up (0.36s). After the reply, the same steps collapse to a dot line under the hero ("agent line") and into an expandable trace in the conversation.

### Decision field
Plans plotted by delay (x) and cost (y) from `decisionField`, with ticks only where plans sit. On-time plans are filled white dots, plans with some late units are `ink-3` dots, plans with a critical order late are hollow red rings. The pick is a larger dot inside a 12px headlight ring over a blurred glow, labelled with its cost at larger weight; twins at the same point are offset. An uppercase key sits beneath (`aria-hidden`; the SVG's sentence carries it). Used in the MCP card and the console (`field-dom.js`).

### Incident and result figures
The incident heading is the ID at display size, a one-line route, and a state phrase. Beside the map: a hero-small figure ("12 critical units on time", red when units are late) with a lead caption and a dim "projected". The result repeats the map with the chosen plan lit white, a hero figure, the timing line in white, and a four-up row of small figures each over a hairline.

### State phrases
State is a short coloured phrase under a heading, not a band: white for executed/ok ("Executed · operationally verified"), red for late or invalidated, amber for attention. No background, no border.

### Tags
Uppercase 12px coloured text with no fill: white for "Agent pick" and on-time verdicts, amber for "Critical order" and "Your preference", red with a 2px dashed underline for late. Look-alike plan names underline the differing words with a 3px headlight underline.

### Buttons
- **Primary:** filled headlight pill, 48px (44px in the console), weight 800, `shell-deep` on hover. One per screen.
- **Secondary:** outlined pill, 1.5px `ink-3`, transparent; `sunken` on hover.
- **Focus:** 3px headlight outline, 2px offset, on every control.
- **Disabled:** 45% opacity.

### Chips
Outlined 44px pills in a horizontally scrolling, snapping row. The first action chip is filled like a primary button; any later action chip is outlined in white. Hover lifts to `shell-tint`.

### Dock and ask field
`surface` panel with the voice bar, the heard line (inline "You said" label), the spoken sentence (tap or "More" to expand), chips, then orb, mic (48px filled circle, red while listening), a pill input on `sunken`, and Send (filled once text is entered; an arrow icon below 400px).

### MCP App card
Dark by default with the device values; when the host reports a light theme it switches to a light palette (white ground, near-black `#111418` for text, `#0B4F9C` for the pick and for on time, as the dark palette uses one light for both, `#B8102A` for late, no green) and adopts host `--color-*` variables. Shows the decision field and the pick side by side when wide, stacked when compact, then the other plans as hairline-divided rows with "See N more".

## Do's and Don'ts

### Do:
- **Do** take every colour from `tokens.css` and every device size from the `--type-*` ladder.
- **Do** draw data as light: lit white for recommended and on time, red dashed for late, amber for attention.
- **Do** give every SVG `role="img"` and a sentence (`aria-label` or a `<title>`), and put an accessible list or text beside it carrying the same facts.
- **Do** keep every interactive target at least 44px tall; keep axe at zero violations at 390 and 1440 widths.
- **Do** reveal trails once per state with a clip-path wipe (1.4s, `cubic-bezier(.16, 1, .3, 1)`); redraws of the same state are marked settled and do not animate.
- **Do** step agent stations and trace rows at a 120ms cadence.
- **Do** honour reduced motion (animations reduced to 0.01ms and one iteration; voice bar, trail reveal and comet removed; the stage shows stations at once) and forced colours (all marks to `CanvasText`, dashes kept, glows hidden, the current lifecycle stop in `Highlight`).
- **Do** keep one filled primary per screen and one hero figure per screen.

### Don't:
- **Don't** add coloured `box-shadow` glows to controls or containers.
- **Don't** put an eyebrow or kicker above a heading; state goes in a phrase under it.
- **Don't** fill tags with colour; tags are coloured text.
- **Don't** use green for on time or success.
- **Don't** write hex values in `device.css`; use tokens.
- **Don't** signal late with colour alone.
- **Don't** box content in cards to separate it; use hairlines and space, and stay within two boxed elements per device screen.
