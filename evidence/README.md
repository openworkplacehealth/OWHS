# Evidence maintenance: the deterministic parts

What runs here, what it writes, and what it may never do. The registry's grades are frozen; nothing in this
folder changes a grade, a status or a licence class. These tools find and watch. People judge.

| Tool | Schedule | Writes | May never |
|---|---|---|---|
| `tools/harvest.py` | monthly, `.github/workflows/harvest.yml`, first of the month | `candidates/YYYY-MM.json` as a run artefact; one issue labelled `evidence-sweep` | touch the dataset |
| `tools/watch_licences.py` | weekly, `.github/workflows/licence-watch.yml`, Mondays | `licence-changes.json` as a run artefact; an issue when a page's visible text changed | change a licence class or status |
| `tools/watch_retractions.py` | monthly, `.github/workflows/retraction-watch.yml`, the second | `retraction-signals.json` as a run artefact; an issue when a cited work carries an update notice or retraction flag | remove evidence or move a grade |
| tripwire | monthly, `.github/workflows/tripwire.yml`, the third | an issue if no `evidence-sweep` issue exists for the month | anything else |

## The harvester

`tools/harvest.py` queries Europe PMC, OpenAlex and Crossref directly. Europe PMC serves the names and abbreviation routes; OpenAlex serves the citation route, and the other two as well when an `OPENALEX_API_KEY` secret is set. Keyless OpenAlex use has a daily credit budget (1,000 credits, 10 per search when this was written) that a full run of every route exceeds, and a run that hits it fails those channels fast and reports itself partial rather than waiting hours. The key, if used, is read from the environment and never written to a log or an artefact. Its configuration is
`queries/instruments-v1.json`: one entry per parent record with long names, abbreviations and the context
each abbreviation requires, citation seeds (development and anchor papers, with their OpenAlex identifiers,
each verified to resolve on the date recorded), an exclusion list that starts empty by design, and a note where
the defining source is a technical report rather than a paper. Three routes run per record and every hit keeps
its route: exact long names in title or abstract; an abbreviation with its context and a property term; works
citing each seed. A separate untargeted channel collects validation papers in working populations that name no
tracked instrument; those go to the admission process, never into the registry.

A hit becomes a candidate when a psychometric property term appears in its title or abstract. A hit without one
is counted per instrument and route as a use and not stored: it uses the instrument, it is not evidence about
it. That filter is applied to every route; the counts are published in each run so the trade-off is visible.
Candidates are de-duplicated by DOI, PMID and OpenAlex identifier; a merge on identical normalised titles is
recorded on the candidate, and two DOIs sharing a title are left separate with a warning. Every surviving DOI is
verified against Crossref and any update notice against it is recorded. Abstracts are read for matching and not
stored.

Each run writes one envelope: schema version, run id, the registry commit, the query file version and hash, the
requested window, start and finish times, a status (`complete` when every declared channel completed all its
pages; `partial` or `failed` otherwise), one record per channel with its exact query, page count, reported and
collected hits and outcome, the candidates, the new-instrument candidates, the use counts and any warnings. The
candidate list is sorted, so two runs over one window diff cleanly. No language model is involved at any point.
`--self-test` checks the pure functions and the query file's shape offline.

```
python tools/harvest.py --from 2026-08-01 --to 2026-08-31 --out evidence/candidates/2026-08.json
python tools/harvest.py --instrument isi --from 2026-01-01 --to 2026-09-05 --no-verify
python tools/harvest.py --self-test
```

No retrieval-recall figure is published yet. Rediscovering the registry's own citations would be a regression
check on the queries, not a measure of coverage, because those citations were themselves found by searching.
A held-out evaluation (a judged manifest of eligible works split by study family, seeds excluded, the harvester
never shown the gold list) is designed and not built; until it exists, the methods page carries no recall claim.

### First run, 5 September 2026

`candidates/2026-09-dry-run.json` is the harvester's first run over 12 July to 5 September 2026 for all 27
instruments, made by hand before the workflow existed and before the query file took its current shape.
Compared with the September web-search sweep: every paper that sweep reported inside the window and naming a
tracked instrument was found (four of four); the one in-window paper it missed validated a new instrument and
is what the untargeted channel exists for. The remaining DOIs in that sweep's report were published before the
window. The candidates are unscreened; most will not change a record. A hand-made run is an engineering result,
not evidence that the scheduled workflow works; that evidence is the workflow's own run log.

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

## The retraction watcher

`tools/watch_retractions.py` checks every distinct DOI in the current dataset's citation arrays: Crossref
update notices pointing at the work (the `updates` filter, the direction a retraction notice points), the
work's own `update-to` (it is itself a notice), and OpenAlex's retraction flag. Correction, expression of
concern, retraction, withdrawal and reinstatement are different events and are reported by type. A signal
opens one issue naming every record and cell that cites the work. Absence of a signal is not proof that a
work stands; unreachable records are listed as unchecked.
