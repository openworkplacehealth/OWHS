# Evidence maintenance: the deterministic parts

What runs here, what it writes, and what it may never do. The registry's grades are frozen; nothing in this
folder changes a grade, a status or a licence class. These tools find and watch. People judge.

| Tool | Schedule | Writes | May never |
|---|---|---|---|
| `tools/harvest.py` | monthly, `.github/workflows/harvest.yml`, first of the month | `candidates/YYYY-MM.json` as a run artefact; one issue labelled `evidence-sweep` | touch the dataset |
| `tools/watch_licences.py` | weekly, `.github/workflows/licence-watch.yml`, Mondays | `licence-changes.json` as a run artefact; an issue when a page's visible text changed | change a licence class or status |
| `tools/watch_retractions.py` | monthly, `.github/workflows/retraction-watch.yml`, the second | `retraction-signals.json` as a run artefact; an issue when a cited work carries an update notice or retraction flag | remove evidence or move a grade |
| tripwire | monthly, `.github/workflows/tripwire.yml`, the third | an issue if `tools/cycle.py verify` cannot correlate a successful harvest run, a complete full-inventory artefact for this month's planned cycle and the workflow's own issue naming both | anything else |
| `tools/cycle.py` | called by both workflows | nothing on its own; `advance` writes `watermarks.json` locally for the screening pull request | run a harvest, open an issue |

## The harvester

`tools/harvest.py` queries Europe PMC, OpenAlex and Crossref directly. Europe PMC serves the names and abbreviation routes; OpenAlex serves the citation route, and the other two as well when an `OPENALEX_API_KEY` secret is set. Keyless OpenAlex use has a daily credit budget (1,000 credits, 10 per search when this was written) that a full run of every route exceeds, and a run that hits it fails those channels fast and reports itself partial rather than waiting hours. The key, if used, is read from the environment and never written to a log or an artefact. Its configuration is
`queries/instruments-v1.json`: one entry per parent record with long names, abbreviations and the context
each abbreviation requires, citation seeds (development and anchor papers, with their OpenAlex identifiers,
each verified to resolve on the date recorded), an exclusion list that starts empty by design, and a note where
the defining source is a technical report rather than a paper. Three routes run per record and every hit keeps
its route: exact long names in title or abstract; an abbreviation with its context and a property term; works
citing each seed. A separate untargeted channel collects validation papers in working populations that name no
tracked instrument; those go to the admission process, never into the registry.

Every hit from the names and citation routes is retained as a candidate. One whose title or abstract carries a
psychometric property term is `screening_priority: normal`; one without is `low`, because the abstract may be
missing or the evidence described in other words. The abbreviation route requires a property term, as its rule
states. Nothing is dropped except a title carrying one of the instrument's configured exclusion terms, and that
drop is counted per channel. Candidates are de-duplicated by DOI, PMID and OpenAlex identifier; two records with
the same normalised title are merged only when one lacks a DOI, no identifier conflicts and the years agree, the
merge is recorded and the DOI becomes the canonical id; anything weaker is kept as two records linked as possible
duplicates. Every candidate DOI is verified against Crossref and any update notice against it is recorded.
Abstracts are read for matching and not stored. The untargeted channel keeps every hit and tags those that also
mention a tracked instrument (whole-phrase match; an abbreviation only beside its context terms) rather than
dropping them, since a paper can introduce one instrument while comparing it with another.

Each run writes one envelope (schema 1.1): schema version, run id, the registry commit, the query file version and
hash, the cycle (id and kind, below), the requested publication window, whether the run covered the full
inventory, start and finish times, a status (`complete` when every planned channel completed all its pages;
`partial` or `failed` otherwise; an empty channel set is a configuration failure), the expected channel set
derived from the query file and the expected channels that did not complete (so a channel that never ran is
counted, not forgotten), one record per channel with its exact query, page count, reported and collected hits and
outcome, the candidates, the new-instrument candidates, the low-priority counts, any warnings, and a watermark
proposal when the run was complete over the full inventory. A run whose
status is not `complete` exits non-zero after writing its artefact, so the workflow shows the cycle as
incomplete. A server-requested wait of up to two minutes is honoured inside the run; a longer one defers the
channel with the reason recorded. The candidate list is sorted, so two runs over one window diff cleanly.
Saved source responses and pinned code and configuration support reproducible replay; live index results can
change between requests. No language model is involved at any point. `--self-test` checks the pure functions
and the query file's shape offline; replay fixtures against saved responses are designed and not yet built.

### Cycles, windows and watermarks

`tools/cycle.py` is the one definition both workflows use. A planned cycle is named by the month the run happens
in: the run on 1 October is cycle `2026-10`, and the tripwire on 3 October looks for cycle `2026-10`. Three date
bases are searched, and every channel records which one it used. The publication window: from the watermark
(the end of the last complete full-inventory run) minus `overlap_days` (14), or the first day of the previous
month when no watermark exists, to today. The ingestion catch-up: Europe PMC's first-index date over the 90 days
before the window end, so a work published earlier but indexed late is still seen (on a single instrument in
September 2026 this basis returned records the publication window did not); OpenAlex's update-date filter needs a
premium key and is listed in every plan as unavailable rather than claimed to have run. The quarterly rerun: in
January, April, July and October the names and citation channels also run with no date filter, over the full
history. A channel that never ran is missing and stays in the denominator; expected channels are identified at
query granularity (instrument, route, provider, date basis, exact query or seed), so a missing alias or seed is
visible even when its sibling completed. Which providers and routes are required, and which are declared
unavailable, is fixed by the provider profile inside the hashed query file; a key present in the environment
authenticates requests and never changes the plan. The verifier reconstructs that plan from the query file at the
artefact's own recorded dates and judges the artefact against it channel by channel, policy included: an artefact
cannot narrow its own expected set or exempt a required channel by declaring it unavailable. A manual run with an explicit window is a manual cycle named
`manual-FROM-TO`; it never satisfies a planned cycle. A manual run with no window is a re-run of the current
planned cycle. `watermarks.json` advances only after a complete full-inventory run and only through the
screening pull request a person merges: the harvest writes a proposal into its artefact and the issue, and
`python tools/cycle.py advance --artefact FILE` copies it in after checking the proposal against the envelope
it sits in (status complete, full inventory, planned cycle, every expected channel complete, matching query hash,
cycle, run id, window end and channel count, valid dates). Nothing advances automatically, so a failed or
partial month leaves the window where it was and the next run covers it again. `python tools/cycle.py --self-test`
runs the offline contract suite: month rollover, manual old window, watermark-derived window, changed query file,
and every verification refusal below.

```
python tools/harvest.py --from 2026-08-01 --to 2026-08-31 --cycle-id manual-2026-08-01-2026-08-31 --cycle-kind manual --out evidence/candidates/manual-2026-08-01-2026-08-31.json
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
visible text (a PDF is hashed as bytes), and compares the hash with `licence-hashes.json`. Each run reports its
status (`complete`, `partial`, `failed`) with attempted, fetched and failed counts; an unreachable page is
unchecked, not unchanged, and a partial or failed run opens an issue even when nothing changed. A failed run
leaves the previous baseline untouched. A change is a reason to read the page against the registry record and
the archived copy the record links; it says nothing about what changed. Baselines are updated by committing
`licence-hashes.json` through a pull request, never by the workflow.

## The tripwire

An early version of the monthly sweep failed silently for a month. The tripwire exists so that cannot recur
unnoticed. On the third of each month it runs `python tools/cycle.py verify --cycle <this month>`, which is
read-only: it lists the `evidence-harvest` runs of the month, downloads the cycle's artefact from each successful
one, and accepts the cycle only when one artefact names this cycle as planned, reports status complete over the
full inventory with every expected channel complete (the denominator is the query file's channel set), was built
from the current query file, and an issue authored by the workflow carries a marker naming that exact GitHub run
and that artefact's SHA-256. A partial run, a manual catch-up, an unrelated successful run, a hand-written issue,
or an issue describing a run that failed does not satisfy it; the refusal reasons go into the one `maintenance`
issue it opens for the cycle. It runs two days after the harvest; that is its response time. All index-consuming
workflows share one concurrency group, so two never run at once against the open indexes.

## The retraction watcher

`tools/watch_retractions.py` checks every distinct DOI in the current dataset's citation arrays against three
sources, each recorded separately so one source's failure never hides another's answer: Crossref update
notices pointing at the work (the `updates` filter, paged; reaching the page cap before the index is exhausted is
recorded as incomplete coverage for that DOI and source, whether or not a notice was found, and makes the run
partial with a non-zero exit), the
work's own `update-to` with its type and target (it is itself a notice), and OpenAlex's retraction flag.
Correction, expression of concern, retraction, withdrawal and reinstatement are different events and are kept
by type. Cells are mapped to citations by the dataset's typed references (precondition evidence and retest
entries), never by prose. A signal opens one issue naming every record and cell that cites the work; so does a
partial or failed run. Absence of a signal is not proof that a work stands; a DOI outside Crossref's coverage is
reported as such, not as clean. `--self-test` stubs the paged source offline and checks the page-cap case with and
without a signal, a deferred source and an all-sources failure.

## The retrieval evaluation (designed; not yet run)

`tools/measure_recall.py` measures held-out known-item retrieval against a judged bibliography: which judged-relevant holdout works the frozen discovery queries returned without being given their identifiers. Coverage (which indexes contain a work, looked up by identifier) is a separate quantity reported beside it. Every input is first validated against its closed typed contract in `evidence/evaluation-contracts/` (manifest, split, coverage, query lock, the harvester's candidates file, and an execution record), with formats asserted; then the evaluator checks the semantics before any arithmetic: canonical identities, links naming real instruments and properties, judged links with a rationale, a read source and a judgement time not before the source was accessed, calendar validity per declared date precision, split components with unique ids and membership whose union with the categorised exclusions partitions the manifest exactly (a work in neither is refused, never dropped), every exclusion substantiated by its category (seed from the pinned query file, calibration for the whole family component of a disclosed calibration work, exposed from the lock, or an explicitly unresolved allocation that makes the result provisional), study families not crossing the split, unknown overlap placed only with a disposition naming its component, the works it was grouped with and a rationale, the declared deterministic split algorithm reproduced, exposure propagated to a whole component, and the candidates file (the harvester's own artefact, route tags `route:source:instrument`) bound to the lock by query hash, window, immutable harvester commit and predeclared evaluation id. An unseen-holdout claim additionally requires an independently captured execution record (for a GitHub run, the record `tools/check_automations.py` verifies against the immutable head) agreeing on head, run id and start time, with the locked tool hashes among the dependencies that ran and the run starting after the lock time; without it the evaluation is a retrospective replay and the report says so. Seeds are derived from the pinned query file; enabled sources from its provider profile. Unresolved relevance, boundary dates or allocations make the figure provisional and are never dropped from a denominator; a zero denominator is null and not evaluated, never 100 per cent. Every miss is listed. Invalid input exits nonzero with named diagnostics. The judged manifest is private until the evaluation has run and a neutral report has been reviewed; `evidence/evaluation-tests/` holds synthetic fixtures, regenerated by `--write-fixtures` and checked byte for byte by the self-test. No recall figure exists yet.

## The screening proposal gate

`tools/check_proposal_allowlist.py BEFORE.json AFTER.json` compares a screening proposal with the dataset it started from, whole object to whole object, and admits only appended citation entries (existing entries byte-identical, in place, in order; new keys only; canonical DOIs or a declared source), `review_due` set from false to true on a record that gained a citation, and appended search entries where the schema carries them. Every other change, including an edit disguised as an append, a reordered list, a changed nested field, a date refresh, a version bump or a corrections entry, stops the proposal. There is no exception for an automated author. It runs before the registry gate and the generated-output check.
