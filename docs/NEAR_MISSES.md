# Near-miss MPNs: pairs a prefix match will conflate

A part-number prefix match is the obvious way to ask "is this board part already in the corpus",
and it is wrong often enough to matter. Each row below is a pair where one member was in the
corpus and the other was NOT, and where a substring or prefix test reports a hit anyway.

**The rule: a near-miss MPN is a different part until a human says otherwise.** The param join is
exact and case-insensitive with no suffix stripping, so a wrong "already have it" verdict does not
fail loudly. It silently leaves the part unseeded and the review item hollow.

Found 2026-09-07 while sourcing the EVT0 incumbent-report parts.

| Board part | Already in corpus | Why they are different |
|---|---|---|
| `SN74LVC1G14QDCKRQ1` (Schmitt-trigger INVERTER) | `ti/SN74LVC1G08` (2-input AND gate) | Different function, different sheet: SCES865 vs SCES584. Shares the whole `SN74LVC1G` prefix. This is the one the handoff called out. |
| `TPS4H000BQPWPRQ1` (quad high-side switch, 1000 mOhm) | `ti/TPS4H160` (quad high-side switch, 160 mOhm) | Same family shape, different RDS(on) grade and different sheet (SLVSD73 vs SLVSCV8). `TPS4H` is the shared prefix. |
| `TPS2HCS05-Q1` (dual SPI smart high-side switch) | `ti/TPS2HB16` (dual smart high-side switch) | Both `TPS2H*` dual high-side switches. SLVSKW3 vs SLVSDV7, and TPS2HCS05 is still ADVANCE INFORMATION. |
| `TCA9539AQPWRQ1` | none (the report links the non-A `tca9539-q1` sheet) | The board part is the **A** variant; TI ships `tca9539a-q1` as its own document. Sourcing off the report's own link would have filed the wrong sheet. |
| `TMUX1309AQBQBRQ1` | none (the report links `tmux1308a-q1`) | 1308A is 8:1 1-channel, 1309A is 4:1 2-channel. They share the SCDS476 family sheet, so this one is benign, but the link and the part still disagree. |

## What this implies for an automated gap diff

Matching a board MPN against corpus directory names needs to be **exact on the device designation**
after stripping only the package / reel / qualification suffix, never a prefix or substring test.
The two failure directions are not symmetric:

- A false HIT (what the table above produces) silently drops a part from the work queue.
- A false MISS costs one redundant download.

So bias the matcher toward false misses. When a candidate differs from a corpus entry by a trailing
letter (`A`, `B`, `P`, `S`), treat it as a DIFFERENT part and check the vendor's literature number
before merging them: TI in particular gives a variant letter its own `-q1` symlink often enough that
the base name and the variant name resolve to two genuinely different PDFs.
