# Evidence maintenance: the deterministic parts

What runs here, what it writes, and what it may never do. The registry's grades are frozen; nothing in this
folder changes a grade, a status or a licence class. These tools find and watch. People judge.

| Tool | Schedule | Writes | May never |
|---|---|---|---|
| `tools/harvest.py` | monthly, `.github/workflows/harvest.yml`, first of the month | `candidates/YYYY-MM.json` as a run artefact; one issue labelled `evidence-sweep`, assigned to the steward when the cycle is not complete | touch the dataset |
| `tools/watch_licences.py` | weekly, `.github/workflows/licence-watch.yml`, Mondays | `licence-report.json` as a run artefact; a comment on the one standing `licence` issue when a page changed, when a page automation can check failed, or once a month to list the pages that need a person | change a licence class or status |
| `tools/watch_retractions.py` | monthly, `.github/workflows/retraction-watch.yml`, the second | `retraction-signals.json` as a run artefact; an issue when a cited work carries an update notice or retraction flag, or the run is incomplete | remove evidence or move a grade |
| tripwire | monthly, `.github/workflows/tripwire.yml`, the third | an issue, assigned to the steward, if `tools/cycle.py verify` cannot correlate a successful harvest run, a complete full-inventory artefact for this month's planned cycle and the workflow's own issue naming both | anything else |
| `tools/cycle.py` | called by both workflows | nothing on its own; `advance` writes `watermarks.json` locally for the screening pull request | run a harvest, open an issue |

## The harvester

`tools/harvest.py` queries Europe PMC, OpenAlex and Crossref directly. Europe PMC serves the names and abbreviation routes; OpenAlex serves the citation route (the provider profile in the query file keeps the other two routes off OpenAlex). Without a key OpenAlex refuses to page past the first page of results: the second page of a cursor-paged query is answered http 401, "API key required for cursor paging". Keyless use also shares one small daily budget with every other keyless caller on the same network address. In the November 2026 run this ended the two citation channels with more than 200 results in the window (PHQ-9 and GAD-7) partial, so the cycle could not be verified. Setting the `OPENALEX_API_KEY` repository secret is the fix; the key authenticates requests and never changes the plan. It is read from the environment and never written to a log or an artefact, and any error text that echoed it is scrubbed. When OpenAlex answers 401, the channel records the server's reason and the run prints, once, a plain line saying what happened and that setting the secret is the fix. Its configuration is
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
channel with the reason recorded. The candidate list is sorted, so two runs over one window diff cleanly. The
artefact also carries `next_action`, the one action a person needs to take when the run is not complete, chosen
from the cause the run recorded (a missing or refused OpenAlex key, the time budget, or a channel failure), and the
issue puts it in its title and first line.

The harvester prints one line per channel as it goes (instrument, route, provider, date basis, outcome, pages,
hits and elapsed time), flushed, so the Actions log shows where a run is and where it stopped. The workflow gives it
a time budget of 240 minutes (`--time-budget-minutes`), inside a step limit of 270 and a job limit of 300 minutes;
GitHub cancels any job at 360. After the budget no new page, channel or Crossref check starts: a channel cut
between pages ends partial with the reason, a channel not reached is recorded as failed with the reason "time
budget reached before this channel started" (it stays in the denominator), a candidate not checked against
Crossref says so, and the run is `partial`. The file is still written, uploaded and reported in the issue. The
windowed channels run first, then the untargeted channel, then the quarterly full-history channels, so a run that
reaches its budget loses the full-history pass before the monthly one. The rule that a cycle verifies only when
every expected channel is complete is unchanged.

The quarterly full-history pass does not fit in one run, and cannot complete under the current plan. The
1 October 2026 run (GitHub run 36862246228) ran for six hours with no output until GitHub cancelled it, and wrote
no candidates file. Counted on 19 November 2026, the 82 full-history channels report 240,818 hits between them,
and 15 of them report more than the 25-page channel budget can collect (2,500 on Europe PMC, 5,000 on OpenAlex),
so those 15 end `partial` ("page budget reached") however long the run takes; every candidate is then checked
against Crossref one request at a time. The next quarterly cycle, 1 January 2027, will therefore stop at its
time budget and report `partial`, with the issue saying that a re-run stops in the same place. How the
full-history pass should run (split across runs, a different page budget, a different verification step) is a
decision for the steward and is not made here.
Saved source responses and pinned code and configuration support reproducible replay; live index results can
change between requests. No language model is involved at any point. `--self-test` checks the pure functions
and the query file's shape offline, and, with the network stubbed, the progress lines, the OpenAlex 401 line, the
time budget and `next_action`; replay fixtures against saved responses are designed and not yet built.

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
partial month leaves the watermark where it was. Once a watermark exists, the next complete run covers the missed
period again. While none exists (none has yet been set), each planned window starts on the first day of the
previous month, so a missed month's publication window is searched again only by a manual run with an explicit
window, the 90-day first-index catch-up and the quarterly full-history pass. `python tools/cycle.py --self-test`
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

`tools/watch_licences.py` fetches every licence page in the reviewed source plan (`licence-watch-sources-v1.json`,
one acquisition per URL), builds a representation that keeps visible text, link targets and rights metadata (a PDF
is hashed as bytes), and compares it with `licence-hashes.json`. A page that could not be fetched is unchecked,
never unchanged. A failed run leaves the previous baseline untouched. A change is a reason to read the page against
the registry record and the archived copy the record links; it says nothing about what changed. Baselines are
updated by committing `licence-hashes.json` through a pull request, never by the workflow.

Some pages refuse automated requests every week. A plan entry may say so with a `fetch` block: status
`blocked-to-automation`, the error codes observed, the date first observed and a note of what was seen. There is no
value that means verified. Six pages carry one, from the weekly run logs of 7 September to 16 November 2026: two
on maps.org.uk (http 403), the Work Ability Index page at www.baua.de (http 403), the Eurofound survey data page
(http 429), the K6 scales page at www.hcp.med.harvard.edu (http 503), and the GHQ-12 FAQ at
support.gl-assessment.co.uk, which was fetched normally until 26 October and has answered http 403 since
2 November. Each is still requested every week. When it fails again with a declared code it is reported as
blocked to automation and listed as needing a person, with the archived copy to compare against; when it answers,
it is compared like any other page; when it fails with any other code (a 404, say), that is a failure. Each run
reports its status (`complete`, `partial`, `failed`) over the pages automation can check, with attempted, fetched
and failed counts beside the number blocked to automation, so `complete` means everything automation can check was
checked, never that the blocked pages were. Those pages are unchecked until a person opens them. The one standing
issue (label `licence`) gets a comment only when a page changed, when a page automation can check failed, or on
the first run of a month, when a short reminder lists the pages that need a person.

## The tripwire

An early version of the monthly sweep failed silently for a month. The tripwire exists so that cannot recur
unnoticed. Its October and November 2026 issues then sat unread for weeks, so the issue it opens is now assigned to
the steward (`ALERT_ASSIGNEE` in `tools/cycle.py`) and mentions that login once, which makes GitHub email a person; its
title names the month and the one action ("re-run evidence-harvest by 30 November 2026"), and its body says until
when the month can be recovered. A planned cycle is named by the month a run starts in, so after the last day of
that month (UTC) no run can complete it. On the next month's run, if the previous month's issue is still open and
that month is still not verified, the tripwire retitles it ("missed, can no longer be recovered") and says so in a
comment. The harvest issue for a cycle that is not complete carries the same assignment and mention. On the
third of each month it runs `python tools/cycle.py verify --cycle <this month>`, which is
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
partial or failed run. Absence of a signal is not proof that a work stands. When Crossref answers 404 for a DOI,
the watcher asks doi.org which agency registered it (`https://doi.org/doiRA/DOI`). A DOI another agency registered
is listed every run, in `outside_crossref` and in the run's summary line, as "not a Crossref DOI, cannot be checked
at Crossref", and does not by itself make the run partial. Two cited DOIs are in this position, both registered
with DataCite: 10.25318/82-003-x202600300002-eng (Statistics Canada) and 10.5255/ukda-sn-9511-1 (UK Data Service).
DataCite has no field equivalent to Crossref's update notices, so no retraction check is made at their own agency:
only their OpenAlex flag is checked, and they are otherwise unchecked by automation. A failed agency lookup, or a
DOI doi.org assigns to Crossref that Crossref answers 404 for, stays unchecked and makes the run partial. `--self-test` stubs the paged source offline and checks the page-cap case with and
without a signal, a deferred source, an all-sources failure, a DOI another agency registered and a failed agency
lookup.

## The retrieval evaluation (designed; not yet run)

`tools/measure_recall.py` measures held-out known-item retrieval against a judged bibliography: which judged-relevant holdout works the frozen discovery queries returned without being given their identifiers. Coverage (which indexes contain a work, looked up by identifier) is a separate quantity reported beside it. Every input is first validated against its closed typed contract in `evidence/evaluation-contracts/` (manifest, split, coverage, query lock, the harvester's candidates file, and an execution record), with formats asserted; then the evaluator checks the semantics before any arithmetic: canonical identities resolved across the whole manifest before matching (a DOI, PMID or OpenAlex id claimed by two rows, a row whose identifier contradicts its own preferred id, or a candidate whose identifiers name two rows or contradict, in any shared namespace, the work it matches, is a conflict refused rather than merged, so an alias never satisfies a second row), every property row counting one unit per distinct work, instrument and property link (a second supporting location or rationale adds nothing), links naming real instruments and properties, judged links with a rationale, a read source, substantive reading provenance (a URL, an access time and a location usable at the reading level: a section, page or table for full text, the abstract named for abstract-only reading, no invented pages) and a judgement time not before the source was accessed and, for an unseen-holdout claim, not after the lock, calendar validity per declared date precision, split components with unique ids and membership whose union with the categorised exclusions partitions the manifest exactly (a work in neither is refused, never dropped), every exclusion substantiated by its category (seed from the pinned query file, calibration for the whole family component of a disclosed calibration work, exposed from the lock, or an explicitly unresolved allocation that makes the result provisional), study families not crossing the split, unknown or possible overlap placed only with a disposition naming its component, the works it was grouped with and a rationale (an empty family list is not resolved independence), the declared deterministic split algorithm reproduced, exposure closed over the complete family graph before partitioning and over the whole component (a sibling of an exposed work is exposed whether or not the exposed work survived into the split, and the closure with its cause is reported), the query configuration's shape and both windows validated before any field is read (a reversed window is invalid even when two documents agree on it), and the candidates file (the harvester's own artefact, route tags `route:source:instrument`) bound to the lock by query hash, window, immutable harvester commit and predeclared evaluation id. The harvester runs its discovery (the `harvest()` call only, after the configuration is loaded and before the envelope is written) under a read boundary covering the standard Python file-open surface (builtins.open, io.open, io.FileIO and _io.FileIO, os.open, Path.read_text and Path.read_bytes); it refuses and records any attempted path and writes the attestation, with its monitored interval and API coverage, into the artefact. The evaluator refuses an artefact whose run attempted any file or declares a non-empty allowlist, and for an unseen-holdout claim requires the candidates file's bytes to be among the artefacts of the execution receipt, so the attestation is bound to the run that produced it rather than authenticating itself. An unseen-holdout claim additionally requires that enforced boundary and an independently captured execution record (for a GitHub run, the record `tools/check_automations.py` verifies against the immutable head) agreeing on head, run id and start time, with the locked tool hashes among the dependencies that ran and the run starting after the lock time; without it the evaluation is a retrospective replay and the report says so. Seeds are derived from the pinned query file; enabled sources from its provider profile. Unresolved relevance, boundary dates or allocations make the figure provisional and are never dropped from a denominator; a zero denominator is null and not evaluated, never 100 per cent. Every miss is listed. A partial or failed discovery run is evaluated as observed retrieval accounting with its status, window and incomplete channel count preserved and its state and claim labelled, never as a completed discovery evaluation. The report carries the hash of every input and states that the execution binding is locally equal, not independently verified, until the automation status record for that run has been consumed. Invalid input exits nonzero with named diagnostics. The judged manifest is private until the evaluation has run and a neutral report has been reviewed; `evidence/evaluation-tests/` holds synthetic fixtures, regenerated by `--write-fixtures` and checked byte for byte by the self-test. No recall figure exists yet.

## The screening proposal gate

`tools/check_proposal_allowlist.py BEFORE.json AFTER.json` compares a screening proposal with the dataset it started from, whole object to whole object, and admits only appended citation entries (existing entries byte-identical, in place, in order; new keys only; canonical DOIs or a declared source), `review_due` set from false to true on a record that gained a citation, and appended search entries where the schema carries them. Every other change, including an edit disguised as an append, a reordered list, a changed nested field, a date refresh, a version bump or a corrections entry, stops the proposal. There is no exception for an automated author. It runs before the registry gate and the generated-output check.
