# Evidence maintenance: the deterministic parts

What runs here, what it writes, and what it may never do. The registry's grades are frozen; nothing in this
folder changes a grade, a status or a licence class. These tools find and watch. People judge.

| Tool | Schedule | Writes | May never |
|---|---|---|---|
| `tools/harvest.py` | monthly, `.github/workflows/harvest.yml`, first of the month | `candidates/YYYY-MM.json` as a run artefact; one issue labelled `evidence-sweep` | touch the dataset |
| `tools/watch_licences.py` | weekly, `.github/workflows/licence-watch.yml`, Mondays | `licence-changes.json` as a run artefact; an issue when a page's visible text changed | change a licence class or status |
| tripwire | monthly, `.github/workflows/tripwire.yml`, the third | an issue if no `evidence-sweep` issue exists for the month | anything else |

## The harvester

`tools/harvest.py` queries OpenAlex, Europe PMC and Crossref directly. For every instrument in
`registry/harvest-queries.json` it searches titles and abstracts for the instrument's names, collects works
citing its development paper, keeps a work only if a psychometric property term also appears, drops works whose
title carries an exclusion term (and records the drop), de-duplicates by DOI, PMID, OpenAlex id and normalised
title, and verifies every surviving DOI against Crossref, recording any correction or retraction Crossref
lists against it. A separate untargeted query collects validation papers in working populations that name no
tracked instrument; those are candidates for the admission process, never for the registry directly.

The output is sorted, so two runs over the same window diff cleanly. Works that name or cite an instrument
without any psychometric term are counted (`seen_without_property_terms`) and excluded: they use the
instrument, they are not evidence about it. No language model is involved at any point.

```
python tools/harvest.py --from 2026-08-01 --to 2026-08-31 --out evidence/candidates/2026-08.json
python tools/harvest.py --instrument isi --from 2026-01-01 --to 2026-09-05
python tools/harvest.py --recall registry/instrument-evidence-base-v0.9.0.json --out evidence/recall.json
```

`--recall` reports what fraction of the registry's own cited DOIs the queries find over their publication
window. That is a regression check on the queries. It is not an estimate of how much new literature the
harvester misses: the registry's citations were themselves found by searching, so rediscovering them cannot
measure what searching misses. A held-out reference set is needed for that and does not yet exist.

### First run, 5 September 2026

`candidates/2026-09-dry-run.json` is the harvester's first run, over 12 July to 5 September 2026, all 27
instruments, made by hand before the workflow existed. Compared with the September web-search sweep: every
paper that sweep reported inside the window and naming a tracked instrument was found (four of four); the one
in-window paper it missed validated a new instrument and is in `new_instrument_candidates`. The remaining
DOIs in that sweep's report were published before the window. The candidates are unscreened; most will not
change a record.

### Screening

A candidate becomes a proposed citation only after a person, or an assisted session working under the
published rules, reads it and opens a pull request. That step is described on the site's maintenance page and
is not part of this folder.

## The licence watcher

`tools/watch_licences.py` fetches every licence page named in a record's identity block, reduces HTML to
visible text (a PDF is hashed as bytes), and compares the hash with `licence-hashes.json`. A change is a reason
to read the page against the registry record and the archived copy the record links; it says nothing about
what changed. Baselines are updated by committing `licence-hashes.json` through a pull request, never by the
workflow. Pages that refuse automated requests are listed as unreachable in every run rather than silently
skipped.

## The tripwire

An early version of the monthly sweep failed silently for a month. The tripwire exists so that cannot recur
unnoticed: on the third of each month it looks for an issue labelled `evidence-sweep` created that month and
opens a `maintenance` issue if there is none. A missing sweep is an incomplete maintenance cycle, not a month
with no new evidence.
