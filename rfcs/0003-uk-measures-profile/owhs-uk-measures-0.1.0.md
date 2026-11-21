# OWHS profile `owhs-uk-measures` 0.1.0: workforce health measures named by the UK government

**Status:** proposed by [RFC 0003](../0003-uk-measures-profile.md). Open for comment from 23 November 2026 to 8 January 2027, not released. Not endorsed by any government department, by BSI or by the Keep Britain Working programme. UK English. Spec text CC-BY 4.0; schemas, code lists and examples Apache-2.0.

**What this is.** In September 2026 the government named five things it wants measured the same way everywhere: work ability, absence, sustained return, retention and disability participation [S1]. It has not yet published a definition for any of them. This profile writes one down for each, in the open, so that employers, providers and the people designing the national definitions have something concrete to test and to disagree with. It maps the measures named in the UK government's published Keep Britain Working documents, and nothing else.

**What this is not.** These are not the official definitions. Where the published text leaves a term undefined, this profile says so and offers a proposal, labelled **PROPOSED**, with its reasoning. When the Workplace Health Intelligence Unit publishes its own definitions, this profile is deprecated in their favour, as GOVERNANCE.md already commits. Nothing here uses the reserved `whiu:` namespace.

**Sources.** Only documents published on GOV.UK, by the Office for National Statistics and by BSI, all opened on 15 November 2026, listed at the end. Quotations are exact. Where a source is silent, this profile says "not stated".

---

## 1. What the government has said, and what it has not

| Topic | Published text | Defined? |
|---|---|---|
| The five measures | The Workplace Health Intelligence Unit's "Common measures" function is to "Define nationally consistent, proportionate approaches to measuring work ability, absence, sustained return, retention and disability participation." [S1] | Named. No numerator, denominator, period or threshold is given for any of the five. |
| Other measures named | "the measures that matter: sustained returns to work, health-related exits, disability participation and the outcomes of support" [S1] | Named, not defined. |
| Earlier lists | "track sickness absence, return-to-work outcomes and disability participation" [S4]; "Reducing absence rates", "Improving return-to-work rates", "Increasing participation of disabled people" [S2] | Named, not defined. The final report says a first phase with employers would test these, "co-creating and standardising measurement" [S2]. |
| Absence | "Sickness absence is measured in different ways." [S1] | Not defined. |
| Sustained return | "Sustained return measured at 6 months, not day one." [S1] | The six-month point is stated. What counts as sustained, and which absences are in scope, is not. |
| Retention | "Participation and retention measured annually, using common definitions." [S1] | Not defined. The common definitions referred to are not published. |
| Disability participation | "differences in the definition of disability along with how the question is asked, if at all, mean that disability participation is something employers struggle to measure." [S1] | Not defined. No definition of disability is given or cited. |
| Work ability | Named in the list above. A "work ability score" appears once, in an illustrative case study of the Work and Health Toolkit, which the document calls "an early prototype" [S1]. | Not defined. No instrument, scale or threshold is given. |
| Who reports | The unit would "Receive aggregate employee, employer and provider data, with clear safeguards and no unnecessary collection of identifiable information." [S1] | Level is stated: aggregate. Format is not. |
| Small numbers | "Small-number results will be suppressed or combined where necessary." (employer data project) and "Employers receive only protected, aggregated insight above a suppression threshold, never individual answers" (toolkit) [S1] | No number is stated anywhere in the documents opened. See the minimum group size rule. |
| Frequency | The unit "should report publicly at least annually" [S1]. Participation and retention "measured annually" [S1]. | How often employers or providers would send data is not stated. |
| The employer standard | BSI "has now been commissioned" to develop "an employer-facing standard focused on a healthy working lifecycle"; a draft for public comment is "expected to be available in early 2027" [S5]. | No measures or data requirements appear in BSI's announcement. |

The government's own data project describes the gap this profile addresses: it "will explore whether existing corporate-level data can be collected consistently and proportionately, how definitions differ, and what a useful confidential benchmark looks like in an employer's hands." [S1]

---

## 2. Rules that apply to every measure

1. **Group level only.** Every measure leaves the employer as an `AggregateReport`. No individual record is part of any return under this profile.
2. **Minimum group size.** Every figure obeys the OWHS minimum group size rule (`owhs-mgs`, in `owhs-mgs-0.1.0.md` in this folder): five, or ten for the two disability measures that rest on a count of disabled people. The v0.2 specification already sets ten for disability participation; the profile envelope (`owhs-uk-measures-0.1.0.json`) enforces it.
3. **Reporting level.** The organisation. A unit within it (`OrgUnit`) only where the unit clears the floor on every figure reported. Disability measures are organisation level only, as in the v0.2 specification; the profile envelope enforces it.
4. **Period.** **PROPOSED:** a rolling 12 months ending on the last day of a calendar quarter, reported once a year at minimum. Reason: the published text says "annually" for the two measures it gives a frequency for, and 12 months removes the seasonal swing in absence. A producer may also report single quarters where the floor allows.
5. **Who is counted.** **PROPOSED:** employees on the employer's payroll, counted as people, not full-time equivalents. Agency workers and contractors are out of scope unless the producer says otherwise in `MeasurementContext.knownLimitations`. The published text does not say who is in scope.
6. **Say what is missing.** Every report carries `n`, `eligibleN`, `headcount`, `completionRate`, `suppressed` and, where withheld, `suppressionReason` (privacy profile P5; the v0.2 `AggregateReport` schema requires them all). Every report also names the rule it follows in `ext.owhs-uk-measures.suppressionRule`, which the profile requires.
7. **Metric codes.** `AggregateReport.metricCode` takes a code from `codelists/uk-measure.json` in this folder. The profile envelope restricts it to that list.

---

## 3. The measures

Each measure gives: a plain definition, numerator, denominator, period, reporting level and the OWHS fields it is computed from.

### 3.1 Absence: `absence-rate`

**Government text.** Named; "measured in different ways"; not defined [S1].

**PROPOSED definition.** The percentage of contracted working hours lost because of sickness or injury.

| | |
|---|---|
| Numerator | Working hours lost to sickness or injury that fall inside the period: the sum of `AbsenceEpisode.workingHoursLost`, counting only the hours inside the period for episodes that cross its edges |
| Denominator | Total contracted working hours in the period for everyone in scope |
| Calculation | numerator / denominator x 100 |
| Period | Rolling 12 months |
| Level | Organisation; unit where the floor allows |
| `n` for the floor | The number of people in the group the rate describes |
| OWHS fields | `AbsenceEpisode.workingHoursLost`, `startDate`, `endDate`; `AggregateReport.value`, `n`, `eligibleN`, `headcount` |

**Reasoning.** OWHS already anchors absence to the Office for National Statistics, which says "the sickness absence rate is defined as the percentage of working hours lost because of sickness or injury" [S6]. Using the same form lets an employer read its own rate beside the national one. One caution: the national figure comes from a household survey, the Labour Force Survey [S6], and an employer's figure comes from its own records. The form is the same; the method is not, so the two will not match exactly.

**Companion: `absence-days-per-worker`.** Working hours lost in the period, divided by 7.5, divided by the average number of people in scope over the period. The 7.5 follows ONS: "The working day is defined as 7 hours and 30 minutes." [S6]

**Optional breakdown.** By `AbsenceEpisode.reasonCode` (the ONS reason categories in `absence-reason@0.2.0`): one `AggregateReport` per category, carrying `ext.owhs-uk-measures.breakdown`, each subject to the floor. The profile allows a breakdown on the two absence measures only.

**Gap in OWHS v0.2.** No OWHS entity holds contracted hours, so the denominator cannot be computed from OWHS records alone. See RFC 0003 section 6, gap 3.

### 3.2 Sustained return: `sustained-return-26wk`

**Government text.** "Sustained return measured at 6 months, not day one." [S1] Not stated: what "sustained" means, which absences count, and whether people who never return are in the denominator.

**PROPOSED definition.** Of the people whose absence of four weeks or more ended in the cohort window, the share who had returned to work and were still at work with the same employer 26 weeks after the day they returned.

| | |
|---|---|
| In scope | Absence episodes lasting 28 calendar days or more |
| Cohort window | The 12 months that ended 26 weeks before the end of the reporting period, so that everyone in the cohort has reached the 26-week point |
| Denominator | In-scope episodes that ended in the cohort window, whether by a return (`outcomeType` full, phased or adjusted) or by not returning (`did-not-return`, `ill-health-exit`) |
| Numerator | Those with a return, and a `sustainedAt` entry of `checkpointWeeks` 26 and `status` sustained |
| "Sustained" | Still employed by the same employer at 26 weeks, and no new absence of 28 calendar days or more started in those 26 weeks |
| Must be reported with it | The count returned; the count sustained; the count with `status` unknown. Unknown stays in the denominator. |
| Level | Organisation |
| OWHS fields | `AbsenceEpisode.startDate`, `endDate`; `ReturnToWorkOutcome.outcomeType`, `rtwDate`, `sustainedAt` |

**Reasoning.**
- *26 weeks.* OWHS already recommends a 26-week checkpoint, and the schema takes any whole number of weeks, so the published six months fits without a schema change.
- *Four weeks or more.* The published commitments single out absences "likely to pass 4 weeks" [S1], and the final report gives the figure that "absent employees had a 96% chance of return after absences of 4 to 6 weeks" [S2]. A measure that includes every two-day absence would sit near 100% for everyone and show nothing.
- *People who never return stay in the denominator.* If they are left out, an employer improves its score when someone leaves. Reporting the parts separately lets a reader compute either version.
- *Unknown is not dropped.* Dropping unknowns rewards not checking.

**Gap in OWHS v0.2.** `sustainedAt.status` has sustained, relapsed and unknown. It cannot say "left the employer". See RFC 0003 section 6, gap 2.

### 3.3 Retention: `retention-26wk` and `health-related-exit-rate`

**Government text.** Retention is in the list of five [S1]. The only descriptions are in illustrative case studies ("She is still there at 6 months, which is when the retention is measured") and in the commitment "Participation and retention measured annually, using common definitions." [S1] The word is used in two senses: staying in work after a health problem, and disabled people staying in work. Neither is defined.

**PROPOSED definition, first sense: `retention-26wk`.** Of the people whose absence reached 28 calendar days in the cohort window, the share still employed by the same employer 26 weeks after the absence began, whether back at work or still absent.

| | |
|---|---|
| Denominator | People with an absence episode that reached its 28th calendar day in the cohort window (cohort window as in 3.2) |
| Numerator | Those still employed by the same employer 26 weeks after `AbsenceEpisode.startDate` |
| Level | Organisation |
| OWHS fields | `AbsenceEpisode.startDate`, `endDate`; `ReturnToWorkOutcome.outcomeType` |

It differs from sustained return on purpose. Sustained return asks whether the return held. Retention asks whether the job was kept.

**PROPOSED companion: `health-related-exit-rate`.** People who left the employer in the period with `ReturnToWorkOutcome.outcomeType` of `ill-health-exit`, or `did-not-return` followed by leaving, per 1,000 people in scope. This puts a number on "health-related exits" [S1]. It undercounts: people who resign for health reasons without a recorded absence are invisible to it, and this profile does not propose asking leavers for a health reason.

**Second sense** (disabled people staying in work) is in 3.4.

**Gap in OWHS v0.2.** No OWHS entity records the date a person left the employer. See RFC 0003 section 6, gap 2.

### 3.4 Disability participation: `disability-participation`, `disability-declaration-rate`, `disability-retention-12m`

**Government text.** Named in the list of five. The document says employers "struggle to measure" it because of "differences in the definition of disability along with how the question is asked, if at all" [S1]. No definition of disability is given or cited in any document opened.

**PROPOSED definition: `disability-participation`.** The share of people in scope who, when asked by their employer in a voluntary question, said they are disabled.

| | |
|---|---|
| Numerator | People in scope on the census date whose most recent answer is yes |
| Denominator | People in scope on the census date |
| Census date | The last day of the period |
| Period | Annual |
| Level | Organisation only |
| Floor | Ten, enforced by the profile envelope. In the `AggregateReport`, `n` is the people who answered, `eligibleN` the people asked and `headcount` the people in scope. The producer-held `DisabilityParticipation` record keeps its banded count |
| OWHS fields | `DisabilityParticipation.disabledHeadcountBand`, `period` (producer-held); `AggregateReport` |

**Must be reported with it: `disability-declaration-rate`.** The share of people in scope who answered the question at all, including "prefer not to say". Without it the main figure cannot be read: 4% from a workforce where everyone was asked means something different from 4% where a fifth were.

**PROPOSED: `disability-retention-12m`.** Of the people whose answer was yes on the census date a year earlier, the share still employed on this census date. Reported beside the same figure for everyone else, so the two can be compared. Organisation level, floor of ten.

**What this profile does not fix, and why.** It does not fix the wording of the question. It requires the producer to state which question was asked, in `MeasurementContext.knownLimitations`, until a `questionRef` field exists. Choosing the question is the heart of the problem the government describes, and it should be settled by the people it concerns and by the bodies that set statistical standards, not by a data format. This draft has not reviewed any harmonised question standard and does not cite one.

**Limits, stated plainly.** The v0.2 specification calls `DisabilityParticipation` reserved-minimal and says publication needs a governed measure definition. This section proposes one; proposing it does not make it governed. This measure counts people who chose to tell their employer. It is a measure of disclosure as much as of participation, and a rising figure can mean more trust, more hiring, or both.

### 3.5 Work ability: `work-ability`

**Government text.** Named first in the list of five. Not defined. No instrument is named. The Work and Health Toolkit, which would produce a "work ability score", is "an early prototype" [S1].

**PROPOSED, shape only.** This profile does not choose an instrument. It fixes how a group result is reported, whichever instrument is used.

| | |
|---|---|
| Value | The group mean of the instrument's score |
| `n` | People who completed the instrument in the period |
| `eligibleN` | People invited |
| `completionRate` | `n` / `eligibleN` |
| `measureKind` | `instrument`, enforced by the profile envelope |
| Must name | The instrument and its version (`InstrumentAdministration.instrumentCitation`, `instrumentVersion`) |
| Level | Organisation; unit where the floor allows |
| Period | The collection window, stated in `MeasurementContext` |
| OWHS fields | `InstrumentAdministration` (individual results are `individual-never`); `AggregateReport`; `MeasurementContext` |

**Reasoning.** Work ability is the only one of the five that cannot be read from records an employer already holds. It has to be asked. Until the toolkit's questions are published, any choice of instrument here would be a guess that the national definition could overturn. Fixing the reporting shape now means a later choice of instrument changes one field.

**A licensing caution.** The OWHS instrument registry holds records for the Work Ability Index and the single-question Work Ability Score. Their licence terms could not be confirmed from the owner's own pages, in July 2026 or on 15 November 2026. No one should build on either until that is settled. Correcting the registry's licence records is a matter for the registry's own correction process, not for this RFC.

---

## 4. The dated commitments, as recordable events

**Government text.** The September 2026 update lists specific commitments that the government says it will test with organisations of all sizes. It describes them as "early examples of where greater specificity might be valuable", not firm proposals. It adds that "The BSI drafting panel will also consider whether the timelines" should be reflected in the standard [S1].

**What this profile adds.** A way to record each commitment as a dated event, so that an employer can show what it did and when, and a group-level rate can be computed. The design principle is: **record the dates, compute the status.** If the counting rule changes, nothing has to be collected again.

**Record.** `CommitmentEvent`, a proposed new record type (schema: `schemas/CommitmentEvent.json` in this folder; code list: `codelists/uk-commitment.json`). One event is one commitment for one worker: a trigger date, a due date where the source gives a time limit, a completion date, and a status. It carries no free text. A note such as what was said in a welfare call is exactly the content OWHS exists to keep out of exchanged data, so the schema rejects it.

| Code | Published wording [S1] | Clock starts | Time limit | Counting rule |
|---|---|---|---|---|
| `joining-conversation` | "A work and health conversation offered within 8 weeks of joining." | Employment start date | 8 weeks | **PROPOSED:** 56 calendar days |
| `issue-conversation` | "A conversation within 5 working days of an issue being raised" | Date the issue was raised | 5 working days | **PROPOSED:** Monday to Friday, excluding public holidays; the day raised is day zero |
| `stay-in-work-plan` | "a stay-in-work plan with named actions, owners and review points" | Date the issue was raised | None published | Dates recorded only |
| `adjustment-agreed` | "Adjustments agreed promptly and put in place as quickly as practicable." | Date requested or recommended | None published | Dates recorded only |
| `adjustment-in-place` | as above | Date agreed | None published | Dates recorded only |
| `absence-contact` | "Contact on day one of absence where possible, and no later than day 3." | `AbsenceEpisode.startDate` | Day 3 | **PROPOSED:** calendar days, first day of absence is day one. The source does not say calendar or working days. |
| `return-plan` | A return-to-work plan "co-created for any absence and particularly those likely to pass 4 weeks or linked to underlying conditions" | `AbsenceEpisode.startDate` | See right | **PROPOSED:** for any absence that reaches 28 calendar days, a plan agreed on or before day 28. The source sets no deadline, and "likely to pass" is a judgement, not a date. |
| `provision-engaged` | "with provision engaged within ten working days where needed" | Date the need was recorded | 10 working days | **PROPOSED:** working days as above. The source does not say what starts the clock. |
| `touchpoints-agreed` | "Regular touchpoints established with agreement of the employee." | `AbsenceEpisode.startDate` | None published | Dates recorded only |
| `sustained-return-check` | "Sustained return measured at 6 months, not day one." | `ReturnToWorkOutcome.rtwDate` | 6 months | **PROPOSED:** 26 weeks, recorded in `ReturnToWorkOutcome.sustainedAt` |

One further published commitment, "Participation and retention measured annually, using common definitions", is met at organisation level by reporting the measures in 3.3 and 3.4. It is not a per-person event.

**Two things deliberately left out.**
1. *The employee's side.* The same document lists, as indicative actions for employees, "Notify employer of absence from day one, and no later than day 3", and states: "None of this is a condition of sick pay, of employment or of access to support." [S1] This profile records what the employer did. It does not create a record of whether a worker complied.
2. *Timings from the case studies.* The document's four working lives include times such as adjustments "agreed within ten working days". The document says these composites "do not relate to specific individuals". They are illustrations, so they are not coded here.

**An earlier, different timing.** The final report says return-to-work plans should be "supported by the WHP from two weeks and no later than six weeks after the commencement of absence." [S2] The September 2026 text uses four weeks. This profile follows the later document and records dates, so either can be computed.

**Group measure: `commitment-met-rate`**, per commitment code.

| | |
|---|---|
| Denominator | Events with a `dueDate` in the period and a status of met, late or not-done |
| Numerator | Those with status met |
| Reported with it | Counts of late, not-done, declined-by-worker and not-applicable. Declined and not-applicable are never counted as missed. |
| Level | Organisation; unit where the floor allows |
| Carried as | `ext.owhs-uk-measures.commitmentCode`, which the profile requires for this measure and refuses on every other |

**Privacy class.** `CommitmentEvent` dates and status are `individual-employer`: they describe the employer's own actions for a worker it already holds an absence or adjustment record for. Anything leaving the employer is `aggregate-only`.

---

## 5. How this profile fits the OWHS rules

The v0.2 specification (section 7) says a profile may add fields under `ext`, narrow core fields and add profile-scoped code lists, and may not add a new top-level field or widen a core list; anything else is a core change by RFC.

- **Inside the profile rules:** the code lists `uk-measure`, `uk-commitment` and `commitment-status`; every measure definition, which uses existing core fields and `AggregateReport`; and the envelope `owhs-uk-measures-0.1.0.json`, which only narrows the v0.2 `AggregateReport`: `metricCode` to the `uk-measure` list, the disability measures to organisation level with a floor of ten, work ability to instrument results, and a required `ext.owhs-uk-measures` object naming the minimum group size rule.
- **Needs a core change:** `CommitmentEvent` is a new record type (RFC 0003, proposal C). Absence-linked events could instead ride on `AbsenceEpisode` under `ext.owhs-uk-measures`, since the v0.2 core accepts `ext`, but three of the commitments are not tied to an absence at all.
- Every gap this draft found in the core is listed in RFC 0003 section 6.

**Conformance.** The profile's own examples and the `CommitmentEvent` examples pass and fail the reference validator at Level 1 as intended (`validation_report.json`). The measure definitions are specification text, not executed code: no tool computes them.

---

## 6. Honesty pass

In the same spirit as the honesty pass in the OWHS specification.

**Decisions others would dispute.**
1. Four weeks as the threshold for sustained return and retention. A lower threshold catches more people and tells you less; a higher one misses the absences where early action matters most.
2. Keeping people who never return in the sustained return denominator. Providers judged on this measure may prefer the narrower version.
3. Counting days as calendar days for `absence-contact`. An absence that starts on a Friday is then due contact by Sunday. Working days would be kinder to employers and harder to compute for shift patterns.
4. Refusing to pick a work ability instrument or a disability question.
5. Not recording the employee's side of the day-3 commitment.

**What the national definitions could overturn.** All of section 3. The most likely points of difference: hours against days for absence; a different definition of sustained; retention defined for everyone with a health condition and not only after an absence; a disability measure that needs individual-level data, which OWHS is built not to supply.

**What this draft could not establish.** Whether the unit will define measures at organisation level only or below it; how often data would be sent; what the "common definitions" referred to in the commitments table are; what the suppression threshold is; whether BSI's draft standard will contain measures.

---

## Sources

All opened 15 November 2026.

- **[S1]** Keep Britain Working: a national growth opportunity, September 2026. GOV.UK, "Updated 9 October 2026". https://www.gov.uk/government/publications/keep-britain-working-review-update-a-national-growth-opportunity-september-2026/keep-britain-working-a-national-growth-opportunity-september-2026
- **[S2]** Keep Britain Working: Final report. GOV.UK, independent report, "Updated 31 March 2026". https://www.gov.uk/government/publications/keep-britain-working-review-final-report/keep-britain-working-final-report
- **[S3]** Keep Britain Working: the story so far (June 2026). GOV.UK, "Updated 4 August 2026". https://www.gov.uk/government/publications/keep-britain-working-review-update-june-2026/keep-britain-working-the-story-so-far-june-2026
- **[S4]** Keep Britain Working continues drive to stop people falling out of the workforce. Department for Work and Pensions press release, 3 July 2026. https://www.gov.uk/government/news/keep-britain-working-continues-drive-to-stop-people-falling-out-of-the-workforce
- **[S5]** New BSI standard to be developed to address UK's economic inactivity crisis. BSI press release, 31 March 2026. https://www.bsigroup.com/en-GB/insights-and-media/media-centre/press-releases/2026/march/new-bsi-standard-to-be-developed-to-address-uks-economic-inactivity-crisis
- **[S6]** Sickness absence in the UK labour market: 2025. Office for National Statistics, released 1 May 2026. https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/labourproductivity/articles/sicknessabsenceinthelabourmarket/2025 (already an OWHS anchor)

GOV.UK material is Crown copyright, quoted under the Open Government Licence v3.0.
