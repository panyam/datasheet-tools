---
name: datasheet-transcribe
description: Source a board part's real datasheet and hand-transcribe the specific parameter values into a param PartSpec (method:"hand", cited), so a mock/placeholder review seed becomes a genuine pass/fail. Interim human-in-the-loop stopgap for the not-yet-ready automated extractor (WS13 derive/). Use when asked to "extract real datasheet values", "replace the mock params with real ones", "source datasheets for <board>'s parts", "make the datasheet review items genuine", or to fill a projects/<customer>/params seed. Triggers: "datasheet transcribe", "extract datasheet values", "source datasheets", "real PartSpec", "replace mock params".
---

# datasheet-transcribe

Turn a mock/placeholder datasheet seed into a real, cited PartSpec by sourcing the vendor
PDF and hand-reading the specific parameter off the page. This workflow was first proven on a
full-board EVT0 review batch (Track 2, 2026-07-30).

## Corpus path

PDFs and doc-IR live under **`$AGNI_DATASHEET_ROOT`** (not in Agni or this tools repo). Download skill
writes `$AGNI_DATASHEET_ROOT/<vendor>/<PART>/<PART>.pdf`. House-design overlays (`projects/`, netlists)
stay in your designs checkout.

## Read the determinism boundary first (say it to the user, don't hide it)

This procedure is NOT fully deterministic, and that matters for how the output is trusted:

- **Deterministic** (same in, same out): pulling MPNs from the netlist, the TI symlink probe,
  `pdf2doc` -> doc-IR, `make review`.
- **NON-deterministic**: the actual *reading of a value off a PDF page*. That step is an LLM
  reading a datasheet — it can phrase differently or, rarely, misread. This is why every value
  MUST carry `page + exact table title + doc number + revision`, lands as `method: "hand"`
  (never machine-derived), and gets human-verifiable provenance. The citation is the check.
- This is a **stopgap** for the automated extractor (`derive/`, WS13) that consumes the
  deterministic doc-IR instead of re-reading pixels. When that lands, prefer it. Do not present
  hand-transcription as the real extraction pipeline.

## Orientation (read before starting)

- `hw/CLAUDE.md` sections "Datasheet layer (WS10 ...)", "datasheets/ — vendor datasheet PDFs",
  and "Datasheets extraction workbench (WS13-006)".
- `Agni/CONSTRAINTS.md` **C16**: datasheet PDFs, doc-IRs, and extracted PartSpecs are
  customer-boundary data — they live in gitignored `$AGNI_DATASHEET_ROOT/<vendor>/<PART>/` and the
  private `projects/<customer>/params/` repo. Never commit them to Agni. Transcribed facts
  (a number + its citation) are fine; the PDF stays private.

## Procedure

### 1. Exact MPNs from the netlist
The join key is the exact `Manufacturer PN` string, not the generic part name.
```
grep -A2 'Manufacturer PN' projects/<customer>/designs/<design>/<file>.edn \
  | grep -oiE '"[^"]+"' | sort | uniq -c | sort -rn
```
Match the board's parts to their full ordering MPNs (e.g. `TPS74615PQWDRVRQ1`,
`LMR604103SRAKRQ1`). Automotive suffixes (`...Q1`, `-Q1`) matter for sourcing.

### 2. Source the PDF -> `$AGNI_DATASHEET_ROOT/<vendor>/<PART>/<PART>.pdf`
Dir per part; PDF stem == dir name (the `datasheetstatus` walker convention).

- **TI (fastest, direct):** `https://www.ti.com/lit/ds/symlink/<name>.pdf`. Probe with a
  browser UA; a 404 returns a small (~3.3 KB) HTML body, a real hit is a big `%PDF-`.
  Gotchas learned: the base part name often 404s — try the **automotive family** name and
  `-q1` suffix (`tps746-q1`, `tcan1145-q1`, `lmr60410-q1`, `tps1212-q1`). When still 404,
  websearch "`<part>` datasheet ti.com/lit/ds/symlink" to get the family lit name.
- **Direct-serve vendors** (no login): Infineon `infineon.com/assets/...-datasheet-en.pdf`
  works. Try before assuming gated.
- **Gated / bot-blocked** (NXP docstore, Marvell NDA, Microchip `ww1.microchip.com` 403s,
  Littelfuse `assetdocs` 403s, Epson): DON'T fabricate from a search-result summary. Hand the
  user a table: save-path + MPN + product-page URL + which review items it unblocks. Offer to
  drive the Chrome browser tools if their browser is logged in.

Verify each download is a real PDF (`head -c5` == `%PDF-`), not an error page.

### 3. doc-IR (deterministic structural layer)
```
cd hw && make pdf2doc-all      # processes every not-extracted / stale PDF it finds
make datasheets-status          # confirms each is now "fresh"
```
`make setup` builds the docling venv once (~546 MB models); it's usually already built —
verify `.venv/bin/python -c "from docling.document_converter import DocumentConverter"`
before re-running the full setup.

### 4. Read the values (the non-deterministic step — use the strict contract)
Fan out ONE reader subagent per part (parallel). Give each a rigid contract:
- Read the specific PDF with the Read tool's `pages` param (start ~first 12-14 pages for
  cover/revision + Recommended Operating Conditions + Electrical Characteristics + Thermal).
- Return, **verbatim**, per requested parameter: numeric value, unit, exact table/section
  title as printed, page (printed AND PDF index), and the doc number + revision from
  cover/footer. Give min/typ/max if printed and say which to use.
- **"Do not guess. If a value is not found, say so explicitly."** — this is what surfaces
  honest gaps instead of confident wrong numbers.

### 5. Encode the PartSpec (preserve the join, cite everything)
Edit `projects/<customer>/params/<file>.textproto`. **Keep the same `mpn` + `symbol`** the
mock used (the inline review query keys on them — no query change). Swap mock -> real:
- `docs { id: "<lowercase-doc-number>" title: "<part> -- <docnum> (Rev. X, date)" }`
  (hand-authored `SourceDoc.id` convention is the lowercase doc number, e.g. `snos412q`).
- `prov { doc_ref: "<same id>" page: N table_or_figure: "<section> (<value as printed>)"
  method: "hand" confidence: 1.0 }`. Use `0.9` when you reduced a programmable RANGE to one
  value; note the range in a `conditions { ... raw: "..." }`.
- The thin `param(mpn, symbol, ?v)` relation reads the `value { max: }` slot, so a single-value
  query needs the number in `max` (mirror how the mock encoded it).

### 5b. Seeding a symbol ENROLS the part in every design-wide query (read before step 5)

Several review items are design-wide inline datalog over `param(mpn, SYMBOL, ?v)` with a BLANKET
threshold in the query: item 260 `ILIM < 4` A, 261 `TSD < 150` C, 165 `TJMAX < 150` C, 258 `VRWM < 24` V,
91 `PPM > 50`. Writing a symbol into ANY PartSpec adds that part to the check. That is the point, and it
is also the trap, because a blanket threshold is a hand-written requirement rather than the part's budget.

**Ask before seeding: is the threshold a universal engineering floor, or a per-design budget?**
- Universal floor (TSD / TJMAX at 150 C on automotive silicon) → seed it, that is honest coverage.
- Per-design budget (item 260's 4 A "load requirement") → seed ONLY once the budget is declared in
  `intent.yaml`. TPS4H000B's internal limit is 1-1.6 A, so seeding `ILIM` fires item 260 against a part
  with no declared per-channel load. The rule evaluates perfectly and the finding is still not a defect.

Cite the withheld value in the file's header comment so it is available the moment a budget exists.
Precedent: items 18/19 (real IOUT, undeclared rail budget) and 26/259, both recorded in
`projects/<customer>/params/README.md`.

**Supply rows: the two rail rules are NOT symmetric.**
- `RecommendedOperatingLimits` → `rail-nominal-out-of-recommended` acts only on a part with a SINGLE
  recommended supply row. Seed ALL of a multi-supply part's rows (TIC10024: VS 4.5-35 V, VDD 3.0-5.5 V)
  and the rule correctly declines it. Seeding one of two to force a check is the false finding.
- `SupplyAbsMaxLimits` → `supply-exceeds-abs-max` applies EVERY abs-max ceiling across EVERY `POWER_IN`
  pin. On a multi-supply part that tests the logic ceiling against the battery pin. **So do not seed
  ABSOLUTE_MAX supply rows on a multi-supply part at all.**

`device_class`: `NormalizeDeviceClass` falls through to a raw string cast after the alias map and the
canonical set, which is why `efuse` works and why a TYPO also "works", landing a class nothing matches.
Copy the string from an existing seed. And a controller is not an integrated part: an external-FET
high-side controller (TPS12121, VNFD1248F) must NOT carry `efuse`.

### 6. Honest-gap rule (when NOT to transcribe)
If the datasheet genuinely cannot supply the value, LEAVE the mock and document why in
`params/README.md`. Two real cases from that batch:
- **Controller, not integrated part**: TPS12121 is TPS1212-Q1, an external-FET high-side
  switch *controller* — no internal RON, no fixed ITRIP (those belong to the chosen MOSFET /
  external sense resistor). The mock's integrated-switch model doesn't match the silicon.
- **Preview datasheet**: TPS65222-Q1's published PDF is a 12-page preview with no
  electrical-characteristics section, so the timing value isn't public yet.
Never silently credit a pass or fabricate — surface the gap.

### 7. Verify
**Parse-check without design access first.** `agni params <MPN> --params projects/<customer>/params`
loads the whole corpus and prints the part's record, so it catches a textproto that does not parse AND
shows the values as the engine read them back. It needs no design, so it works in a profile barred from
the raw files.
```
cd projects/<customer> && make review DESIGN=<design>
```
`make review` READS THE RAW DESIGN, so in a design-barred profile this step is a Cursor handoff, and the
transcription is seeded-but-unproven until someone runs it.
Confirm the intended items flipped to genuine pass/fail (an item whose error `.md` disappears
under `reports/<design>/errors/` now passes). A parse error in a textproto fails the load.

## Coordination (params/ is often a shared, actively-edited folder)
- The mock scaffold ("Track 1") and this real-value work ("Track 2") both touch
  `projects/<customer>/params/`. Only replace a part's seed after Track 1 has finished
  scaffolding that item; re-`stat` the files before editing to check for concurrent edits.
- Commit ONLY your slice by explicit pathspec (`git commit -- params/`), after checking
  `git branch --show-current` — you may be on the other track's branch. Leave regenerated
  `reports/` alone unless asked.
- The mock's message text (e.g. "PLACEHOLDER mock...") lives in `review.yaml`, not the
  PartSpec. Fixing a now-stale message or an unrealistic threshold is a query change — out of
  Track 2 scope; flag it to whoever owns the checklist.
