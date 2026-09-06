# Instrument registry grading rubric, version 1.0

*Open Workplace Health Standard, instrument registry. Rubric v1.0, published 2 September 2026, in force for registry dataset v0.3.0 onward. Licence CC BY 4.0.*

Every graded cell in the registry names the rubric version it was graded under (`rubric_version`). A grade may only change under a published rubric version, through the public corrections process, and never by automation. This document is the reference a reader, a reviewer or a second rater needs to reproduce a cell or to argue with it.

**Honesty note on provenance.** The grades in dataset v0.3.0 were assigned in July 2026 (passes one and two) by one rater working to the rules in the research prompts and schema v0.2, before this document existed. Version 1.0 codifies that practice as it was applied; it does not introduce new thresholds, and no grade was revisited to fit it. Where the practice was looser than the text below, the text says so. The point of publishing it now is to make the next grader's work reproducible and to give reviewers something concrete to tear apart.

## 1. What a cell contains

A cell is one measurement property of one instrument. It carries:

| Field | Meaning |
|---|---|
| `grade` | Confidence that the published evidence supports the property for the registry's audience (section 3). |
| `status` | What kind of literature produced the grade (section 4). Orthogonal to the grade. |
| `evidence_form` | What the evidence was earned on: `canonical`, `derivative`, `parent` or `mixed` (section 5). |
| `indirectness` | `direct` or `indirect` relative to UK working adults; the grade is already downgraded for it (section 6). |
| `evidence_state` | `assessed`, `assessed_absent`, `not_assessed` or `not_applicable` (section 7). |
| `findings` | The prose synthesis, every claim cited. For test-retest, a structured list of coefficients instead of prose. |
| `confidence_note` | Why the grade sits where it does: what would move it up, what holds it down. |
| `rubric_version` | The version of this document the grade was assigned under. |
| `as_of` | The date the cell's literature was last searched. |
| `grade_last_confirmed` | The date a human rater last confirmed the grade (not the date a sweep added a citation). |
| `review_due` | True when a citation was added to the cell after `grade_last_confirmed`. Cleared only by a rater. |

The nine graded properties are: structural validity; convergent and discriminant validity; criterion validity against a reference standard; criterion validity against organisational outcomes; internal consistency; test-retest reliability; measurement invariance; responsiveness and minimal important change; populations, languages and norms. Criterion validity is two properties by schema rule and is never merged.

## 2. Audience and the question each grade answers

Grades are for one audience: an employer, or a vendor acting for one, deciding whether to field the instrument with UK working adults. The question each cell answers is therefore not "is there a literature" but "how much confidence does the published evidence give that this property holds for that audience". A large clinical literature earns nothing by volume; it earns what survives the indirectness discount in section 6.

## 3. The grade scale

The scale is COSMIN-informed, in the sense that the judgement follows the GRADE-style logic COSMIN adopted for reviews of measurement instruments (Prinsen et al. 2018, doi:10.1007/s11136-018-1798-3): start from the quality of the best available studies, then downgrade for risk of bias, inconsistency, imprecision and indirectness. It is not a COSMIN systematic review and does not apply the COSMIN Risk of Bias checklist item by item.

| Grade | Meaning in practice |
|---|---|
| **High** | Multiple adequately sized studies (typically several with n in the hundreds or more, or one very large study plus replication) of sound design report consistent results, and at least part of that evidence is direct for the audience or the property is one where population matters little. Further research is unlikely to change the conclusion. |
| **Moderate** | The evidence is good but has one substantive limitation: it is consistent but wholly indirect; or direct but from one or two studies; or plentiful but with a credible published disagreement that the rater judges resolved in the instrument's favour. Further research could plausibly change the grade. |
| **Low** | One or two studies, small or narrow samples, notable methodological limits, or results that point the same way but weakly. The property is plausibly supported and no more. |
| **Very low** | Evidence exists but is so sparse, indirect, methodologically weak or contradictory that it barely constrains the answer. Often the rater has located one study of the wrong population, or evidence for the construct rather than the instrument. |
| **Absent** | The property was searched for and no published evidence was located. This is a finding about the literature, recorded with `evidence_state: assessed_absent`. It is not a grade of the instrument and it is not a blank. |
| **Not-applicable** | The property is a category error for the instrument's type (internal consistency of a single item; a scale-level factor structure for an item set with no summary score). `evidence_state: not_applicable`. |

Two rules cut across the scale. First, contested literatures are recorded as contested (section 4), never averaged into a middle grade. Second, the rater grades the fielded instrument, not its family: evidence for a parent or derivative form is admitted only when tagged as such (section 5) and is discounted by at least one step where the wording, item count or response scale differs.

Where a property genuinely differs by subgroup (for example measurement invariance that is scalar across age but untested across occupation), a cell may carry `subgrades`; the headline grade is then the more conservative of the two.

## 4. Status tokens

The status says what sort of literature produced the grade. It is independent of the grade so that Moderate-and-contested and Moderate-and-thin never share a word.

| Status | Meaning |
|---|---|
| `well-established` | A mature, replicated evidence base across several research groups. |
| `contested` | Credible published disagreement about the property (a rival factor structure, a failed replication, a methodological critique in print). Displayed prominently on record pages, never buried. |
| `thin` | Few studies, small samples or narrow settings, whatever they conclude. |
| `untested` | The specific claim for this instrument has not been directly examined; any evidence is by analogy. |

## 5. Evidence-form provenance

| Form | Meaning |
|---|---|
| `canonical` | The fielded instrument as versioned by its steward. |
| `derivative` | A named reworded, shortened or rescaled form (the Personal Wellbeing Score for the ONS-4; UWES-9 relative to UWES-17 when the 9 is the fielded form). |
| `parent` | A longer parent form from which the fielded instrument is drawn. |
| `mixed` | The synthesis draws on more than one of the above; the findings say which claim rests on which. |

Borrowed evidence is never silently read as evidence for the fielded instrument. A cell whose only evidence is derivative or parent cannot be graded above Moderate.

## 6. Indirectness

Every grade carries `direct` (UK working adults, or a working-age general population close enough that the rater does not expect the property to differ) or `indirect` (evidence earned in clinical, student, non-UK or otherwise different populations or settings). An indirect cell has already been downgraded for it, usually by one step, occasionally two where the setting is far from a workplace (inpatient samples, children). A record-level `deployment_context_caveat` states once anything that cuts across every property, such as a clinical-origin instrument deployed in a workplace, and is inherited by every cell.

## 7. Evidence states

The state records what the registry did, not what the literature says.

| State | Meaning |
|---|---|
| `assessed` | Searched for and graded on located evidence. |
| `assessed_absent` | Searched for; nothing located. A finding, published with the search basis (the dataset's `assessment_basis`). |
| `not_assessed` | Not yet searched for. Says nothing about the literature. New instruments enter the watchlist with every cell in this state until a rater grades them. |
| `not_applicable` | Category error for the instrument's type. |

In dataset v0.3.0 every cell is `assessed`, `assessed_absent` or `not_applicable`. The registry treats a page that lets `assessed_absent` and `not_assessed` blur as a defect, because it misleads exactly the reader it exists to protect.

## 8. How a cell is derived

1. **Search.** Structured literature pass, AI-assisted: web and database search (publisher pages, Crossref, Europe PMC, PubMed) on the instrument's canonical name and common abbreviations, combined with the property's standard terms (for example "measurement invariance", "differential item functioning", "test-retest", "ICC"), plus the citation trail of the anchoring systematic review where one exists. Searches are non-systematic: no PRISMA flow, no dual screening, no formal search log per cell. The `as_of` date is the search date.
2. **Screen.** Include peer-reviewed studies and steward technical reports that report the property for the instrument or a tagged form. Exclude conference abstracts without data, preprints unless nothing else exists (then said in the findings), and any source the rater could not read in full.
3. **Extract.** Record the coefficient, sample size, population, setting and instrument form for each study relied on. Test-retest is extracted as structured findings (coefficient, coefficient type, interval, n, population, form), never as prose, so bundled ICCs and internal-consistency contamination cannot pass as retest evidence.
4. **Grade.** Start from the best available study quality; downgrade for inconsistency, imprecision (small or few samples) and indirectness (section 6); assign status (section 4) and evidence form (section 5). Write the `confidence_note` stating what holds the grade down and what would move it.
5. **Cite.** Every claim in `findings` carries a citation with a resolvable DOI where one exists. DOIs are checked for resolution and retraction status at grading.
6. **Licence, separately.** Licence status is never taken from the literature. It is verified against the steward's current distribution terms on a stated date, classified for the registry's audience (the dataset's `licence_classes`), and the source page is archived. The registry records the class, never the price.

## 9. What may move a grade, and the freeze

A grade may move only through the public corrections process, under a published rubric version, by a human rater, with the reason and the evidence logged in the dataset's corrections entries and the changelog. Automation (the monthly evidence sweep) may add a citation to a cell and set `review_due`; it never changes `grade`, `status`, `evidence_form` or `indirectness`.

**Freeze.** From 1 September 2026 all grades and statuses are frozen: the registry has one rater, employed by the steward, and no independent check on that rater's judgement. Until two named psychometric raters who are not employees of the steward have joined and the inter-rater procedure below is in force, sweeps add citations and flag review, corrections of fact (wrong DOI, wrong sample size, wrong licence date) are made, and nothing else moves. The freeze is recorded in the dataset (`rater_disclosure`) and on every registry page.

**Inter-rater procedure (not yet in force).** Two raters grade a cell independently against this rubric; agreement is recorded; disagreement of more than one step is resolved by discussion with the resolution logged; disagreement of one step defaults to the lower grade. The procedure and the agreement statistics will be published when the first cell is graded under it.

## 10. The role of AI

AI systems assist the human rater with literature retrieval, screening, extraction and drafting of the prose synthesis, and they run the monthly automated sweeps. They do not assign grades, statuses, evidence forms or indirectness flags, and they do not apply changes to the dataset: every grade in the registry was assigned by the rater, and every sweep result reaches the dataset only through a pull request that a human merges. The registry publishes what the automation is permitted to do and where it has failed (the automation page on the site).

## 11. Reproducing or challenging a cell

To reproduce: take the instrument's canonical name, the property's search terms in section 8, the `as_of` date, and run the search; compare the studies you find with the citations in `findings`; apply sections 3 to 6. To challenge: open a correction (the corrections page on the site) quoting the cell, the rubric section you think was misapplied, and the evidence. Corrections of factual error take priority over all other registry work.

Instrument stewards, developers and copyright holders have a right of reply to their record (the dataset's `right_of_reply` policy): a written response is published beside the record, dated and unedited, with the registry's reply.

## 12. Known limits of version 1.0

- Single rater, employed by the steward; no inter-rater data. The freeze exists because of this.
- Searches were non-systematic and not logged per cell; `as_of` is the pass date, not a per-cell search date.
- The rubric was written after the grades it describes. The thresholds in section 3 are a codification of applied practice and have not been tested prospectively.
- The indirectness discount is a judgement (one step, occasionally two), not a formula.
- `populations_languages_norms` is graded on breadth and quality of population evidence, which fits the scale less naturally than the psychometric properties; treat its grade as a rough summary and read the findings.
- Licence classes are for one audience (employer or vendor use) and may not match a steward's own categories.

Changes to this document are versioned. A rubric change that would move any existing grade is applied only through the corrections process, with the old and new rubric versions both recorded on the cell.

---

*Maintained under the Open Workplace Health Standard. Rubric text CC BY 4.0. Contact: hello@openworkplacehealth.org*
