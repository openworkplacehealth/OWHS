# Instrument registry grading rubric, version 1.2

*Open Workplace Health Standard, instrument registry. Rubric v1.2, 2 September 2026, in force for registry dataset v0.5.0 onward. Licence CC BY 4.0.*

**Version 1.2, 2 September 2026, before first publication.** Changes from 1.1, all made after an independent check of dataset v0.4.0 found that the 1.1 re-rate had been applied unevenly:

1. The indirectness flag has three values, not two: `direct`, `general` and `indirect` (section 6). Version 1.1 had read adult general-population samples as direct on some cells and as indirect on others.
2. The reason after the flag names only the sample types that the cell's own findings describe; the dataset stores the quoted descriptors beside the flag and the site build refuses a cell whose reason is not in its text.
3. A cell that is Absent or Not-applicable carries an `absence_type` instead of an indirectness flag, because a population flag on nothing is not a fact.
4. The High grade has a stated precondition: the findings give a sample size and a coefficient for at least two of the studies the grade rests on, recorded on the cell as `high_basis`. Cells that could not meet it from their cited sources were regraded Moderate.
5. Which properties are population-sensitive is written down (section 6), and the consequence of the flag for the grade follows from that list instead of from a per-cell judgement.
6. The six grade moves made under 1.1 (correction C-0004) were reversed, because they were made on the strength of a flag change rather than of evidence. Grades now move only when a stated rule or new evidence moves them.
7. `mixed` evidence form requires the findings to say which claim rests on which form. `Not-applicable` is reserved for category errors of instrument type; a construct with no reference standard is recorded as Absent with `absence_type: category-error`.
8. `confidence_note` is retired as a field. The reason for a grade is the flag, the status, the evidence form and the numbers in the findings.

The re-rate is logged as correction C-0005 in the dataset. Every cell whose grade, status, evidence form, evidence state, indirectness or rubric version changed carries the 1.1 values in `previous`.

Every graded cell in the registry names the rubric version it was graded under (`rubric_version`). A grade may only change under a published rubric version, through the public corrections process, and never by automation. This document is the reference a reader, a reviewer or a second rater needs to reproduce a cell or to argue with it.

**Honesty note on provenance.** The grades in dataset v0.3.0 were assigned in July 2026 (passes one and two) by one rater working to the rules in the research prompts and schema v0.2, before this document existed. Version 1.0 codified that practice as it was applied. Version 1.1 changed the indirectness rule and re-rated the cells that rule touched. Version 1.2 corrects the 1.1 re-rate after an independent check, before first publication, so that a reader never meets a flag whose reason is not in the cell or a High grade whose numbers are not on the page. Where the practice was looser than the text below, the text says so. The point of publishing it is to make the next grader's work reproducible and to give reviewers something concrete to tear apart.

## 1. What a cell contains

A cell is one measurement property of one instrument. It carries:

| Field | Meaning |
|---|---|
| `grade` | Confidence that the published evidence supports the property for the registry's audience (section 3). |
| `status` | What kind of literature produced the grade (section 4). Orthogonal to the grade. |
| `evidence_form` | What the evidence was earned on: `canonical`, `derivative`, `parent` or `mixed` (section 5). |
| `indirectness` | `direct`, `general` or `indirect` relative to working adults, followed by the population fact the flag rests on (section 6). Present on graded cells only. |
| `indirectness_basis` | The sample descriptors, quoted from the cell's findings, that the flag rests on. Empty only when the flag rests on the record's `fielded_population` (section 6). |
| `high_basis` | On High cells only: the machine-checked record of the precondition in section 3. A list of at least two entries, each `{citation, doi, n, statistic}`, where the citation label occurs in the findings and `n` and `statistic` each carry a number. Removed when the grade moves below High. |
| `absence_type` | On Absent and Not-applicable cells only: `population-general`, `none-in-working-adults` or `category-error` (section 6). |
| `evidence_state` | `assessed`, `assessed_absent`, `not_assessed` or `not_applicable` (section 7). |
| `findings` | The prose synthesis, every claim cited, with the coefficients, intervals and sample sizes the grade rests on. For test-retest, a structured list of coefficients instead of prose. |
| `inherited_from` | On an item record's cell that points to its parent set: the parent's `instrument_id`. The cell carries the parent's grade, status, flag and state. |
| `rubric_version` | The version of this document the grade was assigned under. |
| `as_of` | The date the cell's literature was last searched. |
| `grade_last_confirmed` | The date a human rater last confirmed the grade (not the date a sweep added a citation). |
| `review_due` | True when a citation was added to the cell after `grade_last_confirmed`. Cleared only by a rater. |
| `previous` | Where a later rubric version changed the cell: the earlier `rubric_version`, `grade`, `status`, `evidence_form`, `evidence_state` and `indirectness`. |

The nine graded properties are: structural validity; convergent and discriminant validity; criterion validity against a reference standard; criterion validity against organisational outcomes; internal consistency; test-retest reliability; measurement invariance; responsiveness and minimal important change; populations, languages and norms. Criterion validity is two properties by schema rule and is never merged. Evidence against a diagnostic or health reference standard sits only in the first criterion cell; associations with work outcomes sit only in the second, even where a single study reports both.

## 2. Audience and the question each grade answers

Grades are for one audience: anyone deciding whether to field the instrument with working adults. The question each cell answers is therefore not "is there a literature" but "how much confidence does the published evidence give that this property holds for working adults". A large clinical literature earns nothing by volume; it earns what survives the population rule in section 6.

## 3. The grade scale

The scale is COSMIN-informed, in the sense that the judgement follows the GRADE-style logic COSMIN adopted for reviews of measurement instruments (Prinsen et al. 2018, doi:10.1007/s11136-018-1798-3): start from the quality of the best available studies, then downgrade for risk of bias, inconsistency, imprecision and indirectness. It is not a COSMIN systematic review and does not apply the COSMIN Risk of Bias checklist item by item.

| Grade | Meaning in practice |
|---|---|
| **High** | Multiple adequately sized studies (typically several with n in the hundreds or more, or one very large study plus replication) of sound design report consistent results; on a population-sensitive property (section 6) at least part of that evidence is direct or general. **Precondition:** the findings state the sample size and the coefficient or accuracy statistic for at least two of the studies the grade rests on, each with its citation. A cell that does not meet the precondition is not High, whatever the literature. The studies that meet it are listed in `high_basis`; a `mixed` cell whose findings do not name the second form is capped at Moderate (section 5). |
| **Moderate** | The evidence is good but has one substantive limitation: it is consistent but wholly indirect on a population-sensitive property; or direct but from one or two studies; or plentiful but with a credible published disagreement that the rater judges resolved in the instrument's favour; or it would be High but the cited sources do not give the numbers the High precondition requires. Further research could plausibly change the grade. |
| **Low** | One or two studies, small or narrow samples, notable methodological limits, or results that point the same way but weakly. The property is plausibly supported and no more. |
| **Very low** | Evidence exists but is so sparse, indirect, methodologically weak or contradictory that it barely constrains the answer. Often the rater has located one study of the wrong population, or evidence for the construct rather than the instrument. |
| **Absent** | The property was searched for and no published evidence was located, or the construct has no target for the property (section 6, `absence_type`). This is a finding about the literature, recorded with `evidence_state: assessed_absent`. It is not a grade of the instrument and it is not a blank. |
| **Not-applicable** | The property is a category error for the instrument's type: internal consistency or factor structure of a single item, a scale-level property for an item set with no summary score, a latent factor structure for an instrument scored as derived indices. `evidence_state: not_applicable`. A construct that has no reference standard is not a type error and is recorded as Absent, `absence_type: category-error`. |

Two rules cut across the scale. First, contested literatures are recorded as contested (section 4), never averaged into a middle grade. Second, the rater grades the fielded instrument, not its family: evidence for a parent or derivative form is admitted only when tagged as such (section 5) and is discounted by at least one step where the wording, item count or response scale differs.

Where a property genuinely differs by subgroup (for example measurement invariance that is scalar across age but untested across occupation), a cell may carry `subgrades`; the headline grade is then the more conservative of the two.

A grade never moves because a flag moved. It moves when a rule in this document names the consequence (the High rules above, the parent and derivative cap in section 5) or when new evidence is graded under the corrections process.

## 4. Status tokens

The status says what sort of literature produced the grade. It is independent of the grade so that Moderate-and-contested and Moderate-and-thin never share a word.

| Status | Meaning |
|---|---|
| `well-established` | A mature, replicated evidence base across several research groups. |
| `contested` | Credible published disagreement about the property (a rival factor structure, a failed replication, a methodological critique in print). Displayed prominently on record pages, never buried. |
| `thin` | Few studies, small samples or narrow settings, whatever they conclude. |
| `untested` | The specific claim for this instrument has not been directly examined; any evidence is by analogy. Every Absent and Not-applicable cell is `untested`. |

## 5. Evidence-form provenance

| Form | Meaning |
|---|---|
| `canonical` | The fielded instrument as versioned by its steward. |
| `derivative` | A named reworded, shortened or rescaled form (the Personal Wellbeing Score for the ONS-4; UWES-9 relative to UWES-17 when the 9 is the fielded form). |
| `parent` | A longer parent form from which the fielded instrument is drawn, or, on an item record, the item set the cell points to. |
| `mixed` | The synthesis draws on more than one of the above, and the findings say, claim by claim, which form each rests on. A cell that cannot say is not `mixed`; it is graded on the form it can attribute. |

Borrowed evidence is never silently read as evidence for the fielded instrument. A cell whose only evidence is derivative or parent cannot be graded above Moderate. An Absent cell carries the form the search was made for, which is `canonical` unless the findings say otherwise.

## 6. Population: the indirectness flag and its consequence

**The flag.** Every graded cell carries one of three values, decided from the sample types that the cell's own findings describe and nothing else:

| Flag | Meaning |
|---|---|
| `direct` | At least one sample the findings describe is working adults: employees, staff, an occupational group, an occupational cohort, a workforce survey. A sample of patients who happen to be employed does not count unless the analysis was on workers. |
| `general` | No working-adult sample, but at least one adult general-population sample: a national survey, a community sample, a household or population survey, general-population norms. Working adults are the majority of such samples but are not separated. |
| `indirect` | Every sample the findings describe is clinical, student, adolescent, older-adult or otherwise non-working, or the findings describe no sample at all. |

The reason after the flag lists the sample descriptors, working-adult samples first, and nothing else: `direct; nurses and civil servants; also students and general-population samples`. Country, language, sample size, study design and any argument about the grade are not part of the reason. The descriptors are stored verbatim in `indirectness_basis` and the site build checks that each occurs in the cell's findings. **Country and language are never a reason for indirectness.** Where the evidence was earned is a fact recorded in the findings and under populations, languages and norms; whether scores mean the same thing across countries and languages is graded under measurement invariance.

**When the findings describe no sample.** Some cells cite studies without saying who was studied. Where the record's `fielded_population` is `working-adults` (an instrument that asks about the respondent's job and is fielded only on working populations: a job-stress or engagement or work-ability measure, a workforce survey) and the cited studies are studies of that instrument, the flag is `direct` with the reason `the instrument is fielded only on working populations; the cited studies describe no further sample` and `indirectness_basis` empty. Where the record's `fielded_population` is `general-population`, the same rule gives `general`. Where it is `mixed` (a clinical-origin instrument used across populations), or where the cell's evidence is parent or derivative form, the flag is `indirect; no sample population is described in the retrieved findings`. This is a stated fallback, visible on the cell, not a guess about the literature.

**The consequence.** Properties divide into two lists, and the flag's effect on the grade follows from the list:

| Population-insensitive (the flag does not hold the grade below High) | Population-sensitive (High requires `direct` or `general`) |
|---|---|
| internal consistency | convergent and discriminant validity |
| structural validity | criterion validity against organisational outcomes |
| measurement invariance | responsiveness and minimal important change |
| test-retest reliability | populations, languages and norms |
| criterion validity against a diagnostic reference standard | |

The first group concerns the internal behaviour of the items or their agreement with a diagnostic standard, which the evidence shows travels across adult populations; the second concerns what scores relate to and how they move, which depends on who is answering. On a population-sensitive property an `indirect` cell is graded Moderate at most. On a population-insensitive property the flag is a fact for the reader and moves nothing. No other discount is applied for the flag.

**Absent and Not-applicable cells** carry `absence_type` in place of the flag:

| `absence_type` | Meaning |
|---|---|
| `population-general` | Nothing located in any population. |
| `none-in-working-adults` | Evidence exists in other populations but none in working adults and the cell is nevertheless graded Absent. Under this rubric such evidence is graded `indirect` instead, so the value is defined for completeness and no cell in v0.5.0 carries it. |
| `category-error` | The property has no target for this instrument: a type error (Not-applicable) or a construct with no reference standard (Absent). |

A record-level `deployment_context_caveat` states once anything that cuts across every property, such as a clinical-origin instrument deployed in a workplace, and is inherited by every cell.

**Populations, languages and norms.** The ninth property grades the breadth and quality of the population evidence: how many working populations, languages and settings the instrument has been examined in, and whether reference norms exist and are openly checkable. It carries `status` and `evidence_form` like every other cell. Norms are recorded by country as a fact. The absence of norms for any particular country is never a downgrade.

## 7. Evidence states

The state records what the registry did, not what the literature says.

| State | Meaning |
|---|---|
| `assessed` | Searched for and graded on located evidence. |
| `assessed_absent` | Searched for; nothing located, or nothing to locate for the construct. A finding, published with the search basis (the dataset's `assessment_basis`) and its `absence_type`. |
| `not_assessed` | Not yet searched for. Says nothing about the literature. New instruments enter the watchlist with every cell in this state until a rater grades them. |
| `not_applicable` | Category error for the instrument's type. |

In dataset v0.5.0 every cell is `assessed`, `assessed_absent` or `not_applicable`. The registry treats a page that lets `assessed_absent` and `not_assessed` blur as a defect, because it misleads exactly the reader it exists to protect.

## 8. How a cell is derived

1. **Search.** Structured literature pass, AI-assisted: web and database search (publisher pages, Crossref, Europe PMC, PubMed) on the instrument's canonical name and common abbreviations, combined with the property's standard terms (for example "measurement invariance", "differential item functioning", "test-retest", "ICC"), plus the citation trail of the anchoring systematic review where one exists. Searches are non-systematic: no PRISMA flow, no dual screening, no formal search log per cell. The venues and the reusable search strings are published on the automation page of the site so that coverage can be checked and improved by anyone. The `as_of` date is the search date.
2. **Screen.** Include peer-reviewed studies and steward technical reports that report the property for the instrument or a tagged form. Exclude conference abstracts without data, preprints unless nothing else exists (then said in the findings), and any source the rater could not read in full.
3. **Extract.** Record the coefficient, sample size, population, setting and instrument form for each study relied on. Test-retest is extracted as structured findings (coefficient, coefficient type, interval, n, population, form), never as prose, so bundled ICCs and internal-consistency contamination cannot pass as retest evidence. A graded test-retest cell has at least one structured entry; a summary sentence may sit beside the list but never replaces it.
4. **Grade.** Start from the best available study quality; downgrade for inconsistency and imprecision (small or few samples); apply the population rule (section 6); check the High precondition (section 3) and write `high_basis`; assign status (section 4) and evidence form (section 5). Record the sample descriptors the flag rests on.
5. **Cite.** Every claim in `findings` carries a citation with a resolvable DOI where one exists. A number without a citation is not a finding and is removed. DOIs are checked for resolution and retraction status at grading.
6. **Licence, separately.** Licence status is never taken from the literature. It is verified against the steward's current distribution terms on a stated date, classified for the registry's audience (the dataset's `licence_classes`), and the source page is archived. The registry records the class, never the price.

## 9. What may move a grade, and the freeze

A grade may move only through the public corrections process, under a published rubric version, by a human rater, with the reason and the evidence logged in the dataset's corrections entries and the changelog. Automation (the monthly evidence sweep) may add a citation to a cell and set `review_due`; it never changes `grade`, `status`, `evidence_form` or `indirectness`.

**Freeze.** Grades and statuses are single-rater and are frozen from first publication until independent raters join. The registry has one rater, employed by the steward, and no independent check on that rater's judgement. Until two named psychometric raters who are not employees of the steward have joined and the inter-rater procedure below is in force, sweeps add citations and flag review, corrections of fact (wrong DOI, wrong sample size, wrong licence date) are made, and nothing else moves. The freeze is recorded in the dataset (`rater_disclosure`) and on every registry page. The 1.1 and 1.2 re-rates were made before first publication and are logged as corrections C-0004 and C-0005.

**Inter-rater procedure (not yet in force).** Two raters grade a cell independently against this rubric; agreement is recorded; disagreement of more than one step is resolved by discussion with the resolution logged; disagreement of one step defaults to the lower grade. The procedure and the agreement statistics will be published when the first cell is graded under it.

## 10. The role of AI

AI systems assist the human rater with literature retrieval, screening, extraction and drafting of the prose synthesis, and they run the monthly automated sweeps. They do not assign grades and they do not apply changes to the dataset: every grade in the registry was assigned or confirmed by the rater, and every sweep result reaches the dataset only through a pull request that a human merges.

The 1.2 re-rate is disclosed in full. The three-value flag on each of the 180 graded cells was derived by an AI pass that read only the cell's own findings under a written protocol (the flag values in section 6, the reason limited to sample descriptors quoted from the cell), then checked by machine (every quoted descriptor occurs in the cell) and read by the rater, who overrode the pass only through the `fielded_population` fallback stated in section 6. The numbers added to High cells were extracted by an AI pass from the abstracts of the studies those cells already cite, never from memory, and every number carries the citation it came from; where an abstract contradicted the findings the contradiction was corrected and is listed in C-0005. The grade consequences were applied by the rules in sections 3 and 6, not cell by cell. The registry publishes what the automation is permitted to do and where it has failed (the automation page on the site).

## 11. Reproducing or challenging a cell

To reproduce: take the instrument's canonical name, the property's search terms in section 8, the `as_of` date, and run the search; compare the studies you find with the citations in `findings`; apply sections 3 to 6. To challenge: open a correction (the corrections page on the site) quoting the cell, the rubric section you think was misapplied, and the evidence. Corrections of factual error take priority over all other registry work.

Instrument stewards, developers and copyright holders have a right of reply to their record (the dataset's `right_of_reply` policy): a written response is published beside the record, dated and unedited, with the registry's reply.

## 12. Known limits of version 1.2

- Single rater, employed by the steward; no inter-rater data. The freeze exists because of this.
- Searches were non-systematic and not logged per cell; `as_of` is the pass date, not a per-cell search date. The 1.2 re-rate ran no fresh search: flags were read from the cells and numbers from the abstracts of studies already cited, so `as_of` is unchanged everywhere and `grade_last_confirmed` is the re-rate date.
- The rubric was written after the grades it describes. The thresholds in section 3 are a codification of applied practice and have not been tested prospectively.
- The population rule in section 6 makes the consequence of the flag mechanical; whether a property belongs on the sensitive or the insensitive list is a judgement stated once, open to challenge like any other rule.
- Where the findings describe no sample, the flag rests on the record's `fielded_population` and says so; the cell's citations have not been re-read for their samples.
- The High precondition was met from abstracts, which state fewer numbers than full texts. A cell that dropped to Moderate for want of numbers may return to High when its full texts are read under the corrections process.
- `populations_languages_norms` is graded on breadth and quality of population evidence, which fits the scale less naturally than the psychometric properties; treat its grade as a rough summary and read the findings.
- Licence classes are for one audience (employer or vendor use) and may not match a steward's own categories.

Changes to this document are versioned. A rubric change that would move any existing grade is applied only through the corrections process, with the old and new rubric versions both recorded on the cell.

---

*Maintained under the Open Workplace Health Standard. Rubric text CC BY 4.0. Contact: hello@openworkplacehealth.org*
