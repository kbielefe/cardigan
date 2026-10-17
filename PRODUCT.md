# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The knitter, at a Silver Reed LK150 or a Taitexma TH-160, with the fabric on the bed. They are following a written pattern and need the next carriage passes for the machine in front of them. When the work needs a ribber, the TH-160 is paired with the TR-160.

## Product Purpose

Cardigan turns a written pattern into a sequence of carriage actions for the machine actually in use. Success is a pass the knitter can execute: the needle roles, the levers, and a direction when the pattern determines one.

## Positioning

One written pattern is resolved through the domain in `DOMAIN.md`, then given in the lever names and needle letters of the machine on the table. The same word can name a different action on each bed: D is holding on the LK150 and the upper position on the TH-160; LK150 intarsia swaps to the AG11 while TH-160 intarsia stays on the main carriage; some LK150 fairisle methods take two passes for one knitted row. That resolution is the product.

## Operating Context

The knitter works from a written pattern, a swatch, and one of the two machines. The browser sits beside the machine, including while yarn is on the needles.

Needle-bed pitch and stitch capacity differ. The LK150 has 150 needles at 6.5 mm. The TH-160 has 164 needles at 6.0 mm. Finished width comes from the confirmed swatch. A centimeter measurement written for one machine stays a measurement. A tension-dial number belongs to the dial it was written for.

`DOMAIN.md` is the authority for how pattern language collapses to actions. The saved reading is City Farmhouse garment prose, Clearwater and Eileen Montgomery LK150 fairisle, Creative Tien tuck, and the Taitexma TH-160 and TR-160 manuals.

## Capabilities and Constraints

Cardigan resolves pattern wording into the shared actions in `DOMAIN.md`, then into the setup of the chosen machine.

Confirmed:

- A step is offered on a machine only when that machine has the feature. The LK150 has one bed, the AG11 intarsia carriage, and no ribber. The TH-160 has built-in intarsia, thread lace, weaving, and, with the TR-160, a second bed and racking. A count past 150 does not fit the LK150. A count past 164 does not fit the TH-160.
- Unsettled wording stays unsettled. That includes shaping scheduled on a row number with no moment fixed, a number that may be needle numbers from center 0 or a stitch count, an odd count with no side named, a knitted row that may be one trip or two, carriage ends set differently with no end named for the trip, and the letter D when the pattern names neither a machine nor a role.
- A pass is one carriage trip, or a setup step that is not a trip. A row is whatever that pattern says it is.
- The pattern's own glossary wins for that pattern. Abbreviations are not standard across publishers.
- Cast-on, row counts, and yarn weight use the gauge of a swatch in the same technique: stockinette, tuck, or slip.
- The implementation stack is undecided. There is no application code yet.

Open, carried from the domain record:

- No sweater-prose TH-160 garment is in the sources.
- Fisherman rib is a name Knit It Now uses. It is not a section of the TR-160/230 manual.
- Motif is named on the TH-160, with no pass rules written.
- Brother KH230 and KR230 wording matches some TH-160 paragraphs. Those books are Brother manuals.
- The saved LK150 instruction book is a scan and does not yield selectable text. The LK150 positions and levers in `DOMAIN.md` follow the pattern writing and the Clearwater fairisle walk-through.

## Brand Commitments

The product is called Cardigan. No logo, voice, or visual identity is set.

## Evidence on Hand

Domain authority: `DOMAIN.md`. Source index: `sources/README.md`.

On disk:

- `sources/manuals/Silver Reed LK-150 Knitting Machine.pdf`
- `sources/manuals/taitexma-th-160-instruction.pdf`
- `sources/manuals/taitexma-tr-160-230-instruction.pdf`
- `sources/patterns/eileen-montgomery-lk150-fairisle.pdf`
- `sources/patterns/clearwater-lk150-fairisle-method-1.html` through `method-3`
- `sources/patterns/city-farmhouse-wrap-sweater-scarf.html`
- `sources/patterns/city-farmhouse-simple-stitch-sweater.html`
- `sources/patterns/city-farmhouse-summer-in-the-city.html`
- `sources/patterns/city-farmhouse-summer-breeze.html`
- `sources/patterns/creative-tien-lk150-tuck-blanket.html`
- `sources/references/clearwater-abbreviations.html`
- `sources/references/clearwater-stitch-symbols.html`

Absent from this tree: City Farmhouse Diamond Canvas and Diamond Lady, the household wheelchair blanket, Brother KH230 and KR230 manuals, Clearwater fairisle method 4, and Creative Tien tuck-blanket parts 2 and 3. Future work treats them as absent.

Do not invent testimonials, yarn amounts, gauges, swatches, or pattern text beyond these files.

## Product Principles

- The machine in front of the knitter is the one the pass is for. A feature that bed lacks is not a step.
- The action is shared. The lever names and needle letters belong to the machine.
- Pattern words are evidence. When the wording does not settle a pass, the pass stays open.
- The swatch sets the gauge. The bed sets how many needles exist.
- The files in `sources/` are the reading. Missing manuals and patterns stay missing.
