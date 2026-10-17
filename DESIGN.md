---
name: Cardigan
description: A pattern leaflet on warm paper, ruled in madder.
colors:
  madder: "#8C2F2F"
  madder-deep: "#6F2424"
  paper: "#F7F4EE"
  ink: "#1C1C1C"
  inset: "#F3E6E4"
  rule: "#D9D0C4"
  quiet: "#5C534A"
  field: "#fff"
  selection: "#E7C9C4"
typography:
  brand:
    fontFamily: "system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1
  headline:
    fontFamily: "system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.04em"
  body:
    fontFamily: "system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.45
  note:
    fontFamily: "system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.4
  action:
    fontFamily: "system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1
  label:
    fontFamily: "system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.2
rounded:
  none: "0"
spacing:
  tight: "8px"
  compact: "12px"
  section: "16px"
  box: "18px"
  gutter: "32px"
components:
  button-primary:
    backgroundColor: "{colors.madder}"
    textColor: "{colors.paper}"
    typography: "{typography.action}"
    rounded: "{rounded.none}"
    padding: "12px 18px"
  button-primary-hover:
    backgroundColor: "{colors.madder-deep}"
    textColor: "{colors.paper}"
    typography: "{typography.action}"
    rounded: "{rounded.none}"
    padding: "12px 18px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.madder}"
    typography: "{typography.action}"
    rounded: "{rounded.none}"
    padding: "12px 18px"
  button-quiet-hover:
    backgroundColor: "{colors.inset}"
    textColor: "{colors.madder}"
    typography: "{typography.action}"
    rounded: "{rounded.none}"
    padding: "12px 18px"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.madder}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 14px"
  tab-selected:
    backgroundColor: "{colors.madder}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 14px"
  tab-hover:
    backgroundColor: "{colors.inset}"
    textColor: "{colors.madder}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 14px"
  field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 12px"
  file:
    backgroundColor: "{colors.field}"
    textColor: "{colors.quiet}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 12px"
  abbreviations:
    backgroundColor: "{colors.inset}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "16px 18px 18px"
  reading:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "0"
  bar:
    backgroundColor: "{colors.madder}"
    textColor: "{colors.paper}"
    typography: "{typography.brand}"
    rounded: "{rounded.none}"
    padding: "0 32px"
    height: "64px"
---

# Design System: Cardigan

## Overview

**Creative North Star: "Pattern leaflet"**

Cardigan's first visual system is a pattern leaflet: warm paper, a madder bar, and one ruled box for the abbreviations. It is read beside the machine, so the sheet is flat, square, and immediate. Nothing lifts, nothing rounds, and nothing moves.

The madder rectangle is the form. The bar is a solid one. The tabs and the actions are thin ones, edged with a 1px madder rule. The abbreviations box is the thick one, a 2px rule on the inset ground, and it is the signature. The reading is not a rectangle of chrome. It sits on the paper in the body size, under the glossary, the way a leaflet sets the instructions after the abbreviations.

This surface ships the platform sans (system-ui, sans-serif), because the leaflet brief asked for the face the browser already has. That stack is a fact of this page. It is not the typeface every future Cardigan surface must use. The page has no logo, no imagery, and no motion.

**Key Characteristics:**

- Warm paper, ink, and a single madder accent
- Square rectangles and 1px or 2px rules, with no shadow
- The abbreviations box as the signature
- A full-height column with a fixed bar and a scrolling reading
- Platform sans on this surface, with no motion and no imagery

## Colors

A warm sheet of paper, near-black ink, and one madder red. Everything else is a variation of that sheet: a white field, a tan rule, a brown quiet, and two rose washes. There is no second accent.

### Primary

- **Madder** (#8C2F2F): The bar, the selected tab, the primary action, the abbreviations border, the focus ring, the caret, and the scrollbar thumb.
- **Madder Deep** (#6F2424): Hover on the primary action only.

### Neutral

- **Paper** (#F7F4EE): The page ground, and the text that sits on madder.
- **Ink** (#1C1C1C): Body text, the reading, and the abbreviation list.
- **Quiet** (#5C534A): Placeholders, the file control, and the source line.
- **Rule** (#D9D0C4): The 1px border on the address field and the file control.
- **Field** (#fff): The fill of those two controls. The reading has no field fill.
- **Inset** (#F3E6E4): The abbreviations box, and the hover wash on an unselected tab or the quiet action.
- **Madder Blush** (#E7C9C4): Text selection. The selected text stays ink.

The page sets a light color scheme. It has no dark palette.

**The Madder Rule.** Madder is the only accent. It paints the bar, the selected tab, the primary action, the abbreviations rule, the focus ring, the caret, and the scrollbar. Body text stays ink.

**The Wash Rule.** Hover on an unselected tab or the quiet action fills with inset. Only the primary action darkens, to madder-deep. Text selection uses the blush wash, with ink left as the text color.

## Typography

**Display Font:** None. This surface does not set a display face.
**Body Font:** Platform sans (system-ui, sans-serif)
**Label/Mono Font:** Platform sans (system-ui, sans-serif). No mono.

**Character:** One sans, set like a leaflet. A short wordmark, one tracked uppercase heading on the abbreviations box, then a comfortable reading size. The platform sans is what this surface ships. It is not the required face of every future Cardigan surface.

### Hierarchy

- **Brand** (650, 22px, line-height 1): The word Cardigan in the bar, in paper, sentence case. 650 is the declared weight, between semibold and bold.
- **Headline** (700, 24px, line-height 1.2, letter-spacing 0.04em, uppercase): The abbreviations heading, and only that heading.
- **Body** (400, 18px, line-height 1.45): The page default, the reading, and the abbreviation list once it is present.
- **Note** (400, 16px, line-height 1.4): The empty abbreviations sentence, and the confirmation that the reading is settled.
- **Action** (600, 16px, line-height 1): The footer actions.
- **Label** (400, 14px, line-height 1.2): Tabs, the address field, and the file control. The source line is this size at line-height 1.4, in quiet.

**The Tracked Heading Rule.** Uppercase and opened letter-spacing belong only to the abbreviations heading. The brand word stays in sentence case.

**The Measure Rule.** The reading and notices stop at 68ch. Copy inside the abbreviations box stops at 62ch.

## Layout

A single column fills the viewport. The page itself does not scroll. The body is a column: a fixed bar, a fixed intake, a scrolling reading, and a fixed footer.

The bar is 64px tall. The intake is a row, tabs then the address or file control, with 16px between them and padding 16px 32px 8px. The source line sits under that, padded 4px 32px 12px. The reading region is padded 8px 32px 16px. The footer is padded 16px 32px 24px, and its actions sit in a wrapping row with 12px between them.

The abbreviations box is at most 740px wide, aligned to the start of the column, with 18px under it. It is not centered on the page. The repeated distances are 8px, 12px, 16px, 18px, and the 32px gutter. They are not an 8px grid.

At 720px and below, the bar, intake, source line, reading, and footer use 16px of horizontal padding. The intake wraps. The tabs stretch to the full width and share it equally. The actions stack, full width.

**The Fixed Bar Rule.** The bar, the intake, and the footer stay fixed. Only the reading region scrolls.

**The Gutter Rule.** The page gutter is 32px, and 16px at the 720px breakpoint. Line length is held by the measure, not by a centered sheet.

## Elevation & Depth

Flat. The stylesheet sets no shadow. Depth is tonal. The page is paper. An address or a file sits on a white field with a tan rule. The abbreviations box is inset, edged in madder. The bar is solid madder. Hover changes a fill. It does not lift.

The focus ring is the only line that leaves the rectangle: 2px solid madder, offset 2px, on focus-visible. A resting focus outline is suppressed. The file control draws that same ring when focus is inside it.

**The Flat Rule.** Nothing casts a shadow, at rest or on hover. A state change is a new fill, or the 2px madder focus ring offset by 2px.

## Shapes

Corners are square (0). The stylesheet sets no radius, and the bar, tabs, fields, actions, and abbreviations box all render as rectangles. The recurring silhouette is the madder-edged rectangle: 1px where a control is a choice, 2px on the abbreviations box. Controls that are not choices use the tan rule. The reading is an unboxed block of text.

**The Square Rule.** Corners are square (0). Do not round the bar, the boxes, the tabs, the fields, or the actions.

## Components

### Buttons

- **Shape:** Square (0), with a 1px madder border.
- **Primary:** Madder fill, paper text, padding 12px 18px, action type. Hover fills madder-deep. Disabled drops to 40% opacity, and hover stays madder.
- **Quiet:** Transparent ground, madder text, the same border, type, and padding. Hover fills inset. Disabled hover stays transparent.
- **Hover / Focus:** The fill changes immediately. There is no transition. Focus-visible is the 2px madder ring, offset 2px.

The counted state uses the same primary button. It does not introduce a third shape.

**The Two Actions Rule.** The primary action is a madder rectangle with paper text. The quiet action is madder text on a transparent ground. Both share the 1px madder edge, the action type, and 12px 18px padding.

### Tabs

A joined row inside one 1px madder rectangle. Each tab is square, transparent, madder text, padding 8px 14px, label type. The selected tab fills madder with paper text. An unselected tab hovers to inset. At 720px the row is full width and the tabs share it equally.

### Inputs / Fields

- **Address:** White field, 1px tan rule, ink text, quiet placeholder at full opacity, padding 8px 12px, label type, madder caret, square.
- **File:** The same edge and padding, quiet text, at least 38px tall. Focus inside the control draws the 2px madder ring.
- **Reading:** No border, no fill, no padding, body type, line-height 1.45, madder caret, measure 68ch. It does not drag-resize. It grows with the text instead of scrolling inside the field. Notices above it use the body size, the same measure, and 12px under them.
- **Abbreviation list:** Borderless, like the reading, at 62ch. It renders at the body size. The empty sentence it replaces is the note size, in ink.

### Bar

A 64px madder band. Padding 0 32px, and 16px at the breakpoint. The wordmark is the brand type, in paper, sentence case, line-height 1. There are no links and no icons. This is not a navigation.

### Abbreviations box

The signature. Inset ground, 2px solid madder border, square, padding 16px 18px 18px, max width 740px, 18px below. The heading is the headline role, with 8px under it. The empty sentence is the note role, at 62ch. When a list exists, it replaces that sentence and is set like the reading.

The source line under the intake is quiet, label size, line-height 1.4. The settled confirmation is the note role, in ink, with 12px under it before the actions.

## Do's and Don'ts

### Do:

- **Do** keep madder as the only accent and paper as the ground.
- **Do** put the abbreviations in the inset box with a 2px madder border.
- **Do** leave the reading on the paper, unboxed, at the body size, within 68ch.
- **Do** use a 2px madder focus ring, offset 2px, and only on focus-visible.
- **Do** stay square (0) and flat, and drop the gutter from 32px to 16px at 720px.

### Don't:

- **Don't** add a shadow, a blur, or a second accent.
- **Don't** round the bar, the abbreviations box, the tabs, the fields, or the actions.
- **Don't** box the reading, or give it the field's white fill and tan rule.
- **Don't** animate state changes. This surface has no transition.
- **Don't** treat the platform sans as the face every future Cardigan surface must use. It is the face this leaflet ships.
