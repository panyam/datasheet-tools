# Next steps

Where each line of work left off. Work items live in GitHub issues; this file points at them.
Maintained by /checkpoint: one thread per branch, pruned when the branch merges.

## At a glance

- main — no ticket — next: generate `overrides.public.yaml` from the full corpus and re-run genindex

## main

- **Last touched**: 2026-10-26 (Srirams-MacBook-Pro:~/projects/Agni/datasheet-tools)
- **Why**: rebuild the public corpus (`~/projects/Agni/datasheets`) from `sources.public.yaml` and
  confirm the regenerated `index.yaml` matches `index.public.yaml`.
- **Where it stopped**: all 64 PDFs downloaded, doc-IR extracted, `index.yaml` generated with
  `sources.yaml` copied in. `filter_index_public.py --sources` now also writes
  `overrides.public.yaml`, but that file doesn't exist yet: it has to be generated from the full
  internal corpus, which holds the real `overrides.yaml`.
- **Next action**: on the full corpus run `python3 tools/filter_index_public.py --sources
  --require-url`, commit `overrides.public.yaml`, copy it into the public corpus as
  `overrides.yaml`, re-run genindex, then compare the two indexes field by field.
- **Open questions**: after overrides, the remaining diffs should be the 26 vendor-revised PDFs plus
  TPS2HB16's `variants` (identical PDF, so pdf2doc or genindex extraction changed). Is the
  TPS2HB16 change a regression? Do any transcribed params cite the old revisions (e.g. INA226
  SBOS743B→C, LMR604103 SNAS870B→C, FS2633 Rev 6.1→6.2)?
