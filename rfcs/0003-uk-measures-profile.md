# RFC 0003: A profile for the workforce health measures named by the UK government

| | |
|---|---|
| Status | Open for comment |
| Comment window | 30 November 2026 to 8 January 2027 |
| Comment thread | [issue #ISSUE_NUMBER_TBC](https://github.com/openworkplacehealth/OWHS/issues/ISSUE_NUMBER_TBC) |
| Affects | A new profile `owhs-uk-measures` 0.1.0 over the v0.2 `AggregateReport`; a new named rule `owhs-mgs` 0.1.0; two proposed new record types, `CommitmentEvent` and `ProviderReturn`; five new code lists |
| Breaking | No. Nothing in the core is changed, renamed or withdrawn. The profile only narrows `AggregateReport`; the record types and code lists are additions |
| Drafted | 15 November 2026, by the steward |
| Decision | Not yet taken. The three proposals (A, B, C) can be decided separately |

## Summary

In its September 2026 update the UK government named five things it wants measured the same way everywhere: work ability, absence, sustained return, retention and disability participation. It said small-number results will be "suppressed or combined", and that providers could compete on performance data "published in a common format". It has not published a definition for any of the five measures, a number for the suppression threshold, or a format for provider data.

This RFC maps the measures named in the UK government's published Keep Britain Working documents, and proposes three things for open review:

- **A. A profile, `owhs-uk-measures` 0.1.0.** A plain definition for each named measure, with numerator, denominator, period, reporting level and the OWHS fields it is computed from, carried as `AggregateReport` metric codes. An executable profile envelope narrows the v0.2 `AggregateReport` to these codes and their rules.
- **B. A named minimum group size rule, `owhs-mgs` 0.1.0.** Five people, ten for severe distress figures and ten on the group behind two of the disability measures, with the method for withholding or merging small numbers and for stopping a withheld figure being worked out from the ones around it.
- **C. Two new record types.** `CommitmentEvent`, which records the dated commitments in the September 2026 update as events, and `ProviderReturn`, a common group-level return from an EAP, occupational health provider or insurer to an employer.

Every definition is labelled PROPOSED with its reasoning. None of this is endorsed by any government department, by BSI or by anyone else. When the Workplace Health Intelligence Unit publishes its own definitions, this profile is deprecated in their favour, as GOVERNANCE.md commits. Nothing here uses the reserved `whiu:` namespace.

All the proposal files are in [`0003-uk-measures-profile/`](0003-uk-measures-profile/):

| File | What it is |
|---|---|
| `owhs-uk-measures-0.1.0.md` | Proposal A: the measure definitions, the commitments as events, and an honesty pass |
| `owhs-uk-measures-0.1.0.json` | Proposal A: the profile envelope, in the form `profiles/profile-envelope.schema.json` requires |
| `owhs-mgs-0.1.0.md` | Proposal B: the minimum group size rule |
| `provider-return-0.1.0.md` | Proposal C: the provider return, its ten figures and a worked example |
| `schemas/CommitmentEvent.json`, `schemas/ProviderReturn.json` | Proposal C: JSON Schemas, Draft 2020-12, in the style of the v0.2 schemas |
| `codelists/` | Five proposed code lists and `_registry.additions.json` with the registry entries they would need |
| `examples/` | Valid and deliberately invalid instances for the profile and both record types |
| `validation_report.json` | The repository's own validator run over every example on this branch |

The files sit under `rfcs/` and not under `profiles/`, `schemas/`, `codelists/` or `examples/` because they are proposals. Nothing is published as part of the standard until a decision is recorded.

## 1. What the published documents say, and what they leave undefined

Source references are to the list at the end. Every quotation is exact.

| Term | Published text | Left undefined | Proposed here |
|---|---|---|---|
| The five measures | The unit's "Common measures" function is to "Define nationally consistent, proportionate approaches to measuring work ability, absence, sustained return, retention and disability participation." [S1] | Any numerator, denominator, period or threshold | Definitions for all five, plus five companions (Proposal A) |
| Absence | "Sickness absence is measured in different ways." [S1] | The definition | `absence-rate`: the percentage of contracted working hours lost to sickness or injury, rolling 12 months, in the form ONS uses [S6]. Companion `absence-days-per-worker` |
| Sustained return | "Sustained return measured at 6 months, not day one." [S1] | What counts as sustained; which absences are in scope; whether people who never return are in the denominator | `sustained-return-26wk`: of absences of 28 calendar days or more that ended in the cohort window, the share who returned and were still with the same employer 26 weeks later, with no new absence of 28 days or more. People who never returned, and unknowns, stay in the denominator |
| Retention | Named in the list of five; "Participation and retention measured annually, using common definitions." [S1] | The definition, and the common definitions referred to | `retention-26wk`: of people whose absence reached 28 calendar days, the share still employed 26 weeks after it began. Companion `health-related-exit-rate` per 1,000 people |
| Disability participation | Employers "struggle to measure" it because of "differences in the definition of disability along with how the question is asked, if at all" [S1] | Any definition of disability; the question | `disability-participation`: the share of people in scope who said they are disabled in a voluntary employer question, reported with `disability-declaration-rate` and `disability-retention-12m`. The question is deliberately not fixed. Organisation level only, floor of ten on the people who answered |
| Work ability | Named first in the list of five; the toolkit that would give a "work ability score" is "an early prototype" [S1] | Instrument, scale, threshold | `work-ability`: shape only. The group mean of a named instrument, with people completing and people invited. No instrument is chosen |
| Small numbers | "Small-number results will be suppressed or combined where necessary." and "Employers receive only protected, aggregated insight above a suppression threshold, never individual answers" [S1] | The number, and the method | `owhs-mgs` 0.1.0 (Proposal B) |
| Provider data | "No provider can compete reliably on outcomes, because comparable outcomes do not exist." and "providers could compete based on performance data, published in a common format." [S1] | Which figures, how often, what format, what floor | `ProviderReturn` (Proposal C) |
| Contact during absence | "Contact on day one of absence where possible, and no later than day 3." [S1] | Calendar or working days | Calendar days; the first day of absence is day one |
| Conversation when an issue is raised | "A conversation within 5 working days of an issue being raised" [S1] | What a working day is; when the count starts | Monday to Friday, excluding public holidays in the worker's UK nation; the day raised is day zero |
| Conversation on joining | "A work and health conversation offered within 8 weeks of joining." [S1] | Counting | 56 calendar days from the employment start date |
| Return-to-work plan | A plan "co-created for any absence and particularly those likely to pass 4 weeks or linked to underlying conditions" [S1] | Any deadline; "likely to pass" is a judgement, not a date | For any absence that reaches 28 calendar days, a plan agreed on or before day 28 |
| Provision engaged | "with provision engaged within ten working days where needed" [S1] | What starts the clock | The date the need was recorded; working days as above |
| Who is counted | Not stated | | Employees on the payroll, counted as people, not full-time equivalents |
| Period and frequency | "measured annually" for participation and retention [S1]; the unit "should report publicly at least annually" [S1] | How often employers or providers send data | A rolling 12 months ending on the last day of a calendar quarter, reported at least once a year. Provider returns quarterly |

The September 2026 update calls its commitments "early examples of where greater specificity might be valuable" and says they will be tested; it does not present them as firm proposals [S1]. BSI has been commissioned to develop "an employer-facing standard focused on a healthy working lifecycle", with a draft for public comment "expected to be available in early 2027" [S5]. BSI's announcement names no measures or data requirements.

## 2. Proposal A: the profile `owhs-uk-measures` 0.1.0

The definitions are in [`owhs-uk-measures-0.1.0.md`](0003-uk-measures-profile/owhs-uk-measures-0.1.0.md). Each measure leaves the employer only as an `AggregateReport`. The ten metric codes are in `codelists/uk-measure.json`: `absence-rate`, `absence-days-per-worker`, `sustained-return-26wk`, `retention-26wk`, `health-related-exit-rate`, `disability-participation`, `disability-declaration-rate`, `disability-retention-12m`, `work-ability` and `commitment-met-rate`.

The envelope [`owhs-uk-measures-0.1.0.json`](0003-uk-measures-profile/owhs-uk-measures-0.1.0.json) targets `https://openworkplacehealth.org/schemas/v0.2/AggregateReport.json` and only narrows it, as section 7 of the v0.2 specification allows:

- `metricCode` must be one of the ten codes;
- the three disability measures are organisation level only, and `disability-participation` and `disability-retention-12m` must be withheld when `n` is nine or fewer. The test is on `n`, which the core schema defines as the "Distinct people contributing to this metric's estimate in this window". For `disability-participation`, profile section 3.4 sets `n` as the people who answered, so the floor of ten protects the people who answered, not the count of disabled people: a report with 200 answering and three disabled passes the envelope. For that measure only `owhs-mgs` R4 (the count is zero or at least five) touches the count of disabled people, and R4 is a Level 3 rule that no tool checks. For `disability-retention-12m`, by the core definition, `n` is the people who said yes a year earlier, so there the floor of ten is a floor on a count of disabled people. `disability-declaration-rate` keeps the core floor of five;
- `work-ability` must have `measureKind` `instrument`;
- every report carries `ext.owhs-uk-measures.suppressionRule` set to `owhs-mgs@0.1.0`;
- a breakdown by absence reason (`ext.owhs-uk-measures.breakdown`) is allowed on the two absence measures only;
- `commitment-met-rate` must name its commitment (`ext.owhs-uk-measures.commitmentCode`), and no other measure may.

To check a report against it:

```
python tools/validate.py schemas/v0.2/AggregateReport.json <report.json> --profile rfcs/0003-uk-measures-profile/owhs-uk-measures-0.1.0.json
```

## 3. Proposal B: the minimum group size rule `owhs-mgs` 0.1.0

The rule is in [`owhs-mgs-0.1.0.md`](0003-uk-measures-profile/owhs-mgs-0.1.0.md), citable as `owhs-mgs@0.1.0`. It does not change the floors already in the specification (five, and ten for severe distress in P2; ten for the `DisabilityParticipation` record). It names them and adds the working detail a producer needs.

In short: no figure about fewer than five people, or ten for severe distress measures; in the profile, ten on the group behind `disability-participation` and `disability-retention-12m`, as section 2 describes. It counts people, not contacts, calls, sessions or claims. It applies to both sides of a share: the group must be at least five, and the count and the remainder must each be zero or at least five. A figure that covers all of a group is withheld for a sensitive status. A failing figure is withheld (the row is sent, marked suppressed, with a reason) or merged with another category. A withheld figure must not be recoverable by subtraction within a table, across nested groups or across time. That rule, R7, is a proposed answer to part of the open issue [#18](https://github.com/openworkplacehealth/OWHS/issues/18), "Aggregation floors alone do not prevent disclosure by differencing": it specifies secondary suppression within a table and rules for nested groups (one inside the other) and for successive periods. It does not settle #18. It gives no rule for groups that partly overlap without one sitting inside the other, which #18 is also about; it does not say whether a producer must track what it has already released to a given recipient, which #18 also asks; how it works across time for very small employers is listed below as not settled; and it is a Level 3 rule that no tool checks. A higher floor is always allowed and a lower one never is. Safeguarding signals stay excluded at any size.

Five is a convention, not a proof, and it does not make data anonymous. No official number was found to compare it with: no number appears in any of the documents opened. Section 4 of the rule gives the reasons for five.

## 4. Proposal C: two new record types

Section 7 of the v0.2 specification says a profile that needs a new top-level field is a core change request, not a profile. A new entity is more than that, so both records are proposed here as core additions.

**`CommitmentEvent`** ([schema](0003-uk-measures-profile/schemas/CommitmentEvent.json), [code list](0003-uk-measures-profile/codelists/uk-commitment.json)). One commitment for one worker: a trigger date, a due date where the published text gives a time limit, a completion date and a status. The principle is to record the dates and compute the status, so a change of counting rule needs nothing collected again. It carries no free text: what was said in a welfare call is exactly what OWHS keeps out of exchanged data, so the schema rejects notes. Privacy class `individual-employer` for the dates and status, `aggregate-only` for anything leaving the employer. It records what the employer did. It does not create a record of whether a worker complied with anything.

**`ProviderReturn`** ([specification](0003-uk-measures-profile/provider-return-0.1.0.md), [schema](0003-uk-measures-profile/schemas/ProviderReturn.json)). One file per provider, per employer, per period, group level only. Ten figures, the same for every kind of provider: people using, utilisation rate, cases opened, median working days to first contact, the share engaged within ten working days, cases closed, absent at referral, returned to work, sustained return at 26 weeks, and outcome unknown. Counts are of distinct people; contacts and sessions are refused. The schema enforces the per-row parts of `owhs-mgs`, refuses case lists and pseudonyms, and requires a withheld row to carry a reason and neither a value nor a count. The worked example is a synthetic quarterly return from an occupational health provider to an employer of 184 eligible people, showing merged rows and withheld rows.

If either record is accepted, its schema would move into the next schema version through the schema generator, its examples into `examples/`, its code lists into the registry, with changelog entries, and with named date-order rules added to the validator: `dueDate` and `completedDate` not before `triggerDate`; `periodEnd` not before `periodStart`; `cohortEnd` not before `cohortStart`. Those rules are proposed and not implemented.

## 5. What was checked on this branch

The repository's own `tools/validate.py` was run, with `OWHS_ASSERT_NO_NETWORK=1`, over every example in the proposal folder. Full output is in `validation_report.json`. It was run again on 21 November 2026, after the branch was brought up to date with main and the profile envelope's description and comment were corrected, under Python 3.11 as in CI. Every verdict, error count and error message was the same; the only change in the output is the envelope's hash, which the report records.

| Check | Result |
|---|---|
| `ProviderReturn.valid.json` | VALID |
| `ProviderReturn.invalid.json` | 7 errors, all intended: a floor of three, counts of contacts, a case list with a pseudonym, an unsuppressed count of three, and a withheld row that still carries its number |
| `CommitmentEvent.valid.json` | VALID |
| `CommitmentEvent.invalid.json` | 8 errors, all intended: free-text notes, a direct identifier as the pseudonym, an unknown commitment code, missing organisation, dates and provenance |
| Profile, three valid reports | VALID with `owhs-uk-measures@0.1.0` checked: an absence rate, an absence rate by reason, and a withheld disability figure for seven people |
| Profile, five invalid reports | Each is valid against the core and refused by the profile: a disability figure for seven people shown, a disability measure at unit level, an unknown metric code, work ability not from an instrument, and a report that names no suppression rule |
| Codes in the worked provider return | Every breakdown code exists in the core list it names |
| Cross-row rule on the worked provider return | Every hidden remainder is zero or at least five; no shown count leaves a remainder of one to four |

No schema, code list, example, profile, specification text or tool is changed: nothing under `profiles/`, `schemas/`, `codelists/`, `examples/` or `spec/`, and no program under `tools/`. Outside this RFC's own files, opening it adds a changelog entry on the site tab and a dated entry in `CHANGELOG.md`, as for RFCs 0001 and 0002, and lists the RFC in `rfcs/README.md` and on the open review page (`docs/open-review.md`). The same change records, in those two places and in the headers of RFCs 0001 and 0002, that their comment windows closed on 17 October 2026 and that no decision is recorded yet. The site files built from those sources are regenerated by their own generators: the changelog page, the open review page, the home page's Latest strip, the Atom feeds, and the sitemap with its ledger, `tools/sitemap-lastmod.json`.

## 6. Gaps in the core this work found

These are follow-ups. None is changed by this RFC. Each was checked again on 21 November 2026 against main, and each is still open.

1. **`benefit-product` has no code for occupational health.** It appears only in `source-type` (`oh-provider`) and `access-route` (`oh`). The proposed `provider-service-type` list fills the gap for now.
2. **No field records that a person left the employer, or when.** `rtw-sustained-status` has sustained, relapsed and unknown. Retention, exit and sustained return measures cannot be computed from OWHS records alone without it.
3. **No field holds contracted hours.** The absence rate denominator has to come from outside OWHS.
4. **`suppression-reason` cannot say a figure was withheld to protect another one, or merged.** A `secondary` code would help.
5. **No dedicated place to record which disability question was asked**, or which instrument produced a group work ability score, on an `AggregateReport`. The profile asks producers to state it in `MeasurementContext.knownLimitations` meanwhile.
6. **`AggregateReport` v0.2 requires `n` on a withheld row**, so the size of a group below the floor is shown (the repository's own example withholds a figure for four people and shows the four). For a survey mean that may be acceptable; for a count it is the figure. `ProviderReturn` withholds both.
7. **`AggregateReport` has no breakdown field.** This profile carries one under `ext`. If other profiles need breakdowns, a core field may be cleaner.
8. **The safeguarding exclusion stops an EAP return from reporting that workplace relationships are a recurring problem.** The specification's honesty pass already lists this as a governance question.
9. **No tool checks the cross-row parts of the minimum group size rule** (remainders, all-of-a-group figures, recovery by subtraction). Level 3 remains unimplemented, as the specification says.

Three problems found when these drafts were first written against the v0.1 schemas are already fixed on main and need no change: every v0.2 core schema accepts `ext`; the v0.2 `AggregateReport` requires `value` only when a figure is shown and forbids it, and its interval, when withheld; and the reference validator asserts formats.

## 7. Alternatives considered

- **Wait for the national definitions.** The measures are named and undefined now, employers are being asked to measure them, and GOVERNANCE.md already commits OWHS to giving way when official definitions arrive. An open draft gives people something to test.
- **Name the profile after the programme.** Rejected in favour of a neutral name. A programme's name could be read as endorsement, which there is none of, and the measures may outlive the programme's name.
- **Carry commitments on `AbsenceEpisode` under `ext`.** Possible for the absence-linked ones, but three of the commitments are not tied to an absence at all.
- **Choose a work ability instrument and a disability question.** Rejected. Either choice is a guess the national definitions could overturn, and the disability question should be settled by the people it concerns and by the bodies that set statistical standards.
- **A floor higher than five.** Allowed by R10 for any producer. A higher default would leave most small employers, and most teams in larger ones, with empty reports.

## 8. What this RFC does not decide

The official definitions; any instrument or disability question; the registry's licence records for any instrument (a matter for the registry's own correction process); whether a return to an employer and a return to the national unit should be the same file; fees, service levels or capacity in a provider return.

## 9. What is not settled

These are the points most likely to be wrong, gathered from the honesty passes in the three proposal files; points 14 and 15 were added in review.

1. Four weeks as the threshold for sustained return and retention.
2. Keeping people who never return, and unknowns, in the sustained return denominator.
3. Calendar days for the day-3 contact. An absence that starts on a Friday is then due contact by Sunday.
4. Which public holidays count, for workers in different UK nations, in the working-day commitments.
5. Quarterly provider returns. Below about 50 eligible people most rows will be withheld; annual or pooled returns may be the only honest option.
6. The same ten figures for an EAP, an occupational health service and an insurer.
7. People, never contacts: some services only count calls.
8. Judging providers on work outcomes they often cannot see.
9. Whether R5 (all of a group) applies to every figure or only sensitive ones, and who keeps the list of what is sensitive.
10. How R7 across time can work for very small employers, where almost any change in headcount is one to four people.
11. Whether a group size below the floor may be shown on a withheld row (gap 6).
12. Whether the broad domain `relationships` may be reported at a higher floor (gap 8).
13. Whether to align to a national threshold if one is published. GOVERNANCE.md says align, do not compete, and R10 already allows a higher one.
14. Whether, for `disability-participation`, the count of disabled people should itself need ten. The envelope's floor of ten tests `n`, which for that measure is the people who answered; the count of disabled people is held only to zero or at least five, by R4, which no tool checks. (For `disability-retention-12m`, `n` is the people who said yes a year earlier, so the ten already falls on disabled people there.)
15. A rule for groups that partly overlap without one sitting inside the other. R7 covers nested groups only, and issue #18 asks about overlapping units generally.

## 10. Review invited

Find the flaw in any one part. You do not need to review the whole of it.

- **Occupational health providers and clinicians:** the provider return, the fitness-opinion rows and the first-contact timing. These are the parts most likely to be wrong in practice.
- **EAPs and insurers:** whether the ten figures fit what you can report, and whether counting people rather than contacts is workable.
- **Disability data specialists and disabled people's organisations:** section 3.4 of the profile, and whether leaving the question open is right.
- **Statisticians and disclosure control specialists:** the minimum group size rule, five as the floor, and the rules against working figures out.
- **HR, payroll and HR software implementers:** the counting rules for the commitments, contracted hours and a leaving date.
- **Employers of any size:** whether a small employer would see anything useful.

Please declare any financial or professional interest in a product, provider, instrument or organisation your comment touches, as GOVERNANCE.md asks.

## 11. Proposed decision-log rows (not decided)

| # | Decision | Proposed resolution | Reasons |
|---|---|---|---|
| D8 | Publish definitions for the measures the UK government has named | Adopt profile `owhs-uk-measures` 0.1.0, every definition labelled proposed, deprecated when national definitions exist | The measures are named and undefined; an open draft gives people something to test |
| D9 | Name and spell out the minimum group size rule | Adopt `owhs-mgs@0.1.0`: five, ten for severe distress figures and on the group behind two disability measures, counted in people, both sides of a share, withhold or merge, no working it out | The specification gives the floors but not the method; published plans refer to a threshold without stating one |
| D10 | A common provider return, and commitments as events | Add `ProviderReturn` and `CommitmentEvent` as core record types | The published text asks for provider performance data "in a common format" and sets dated commitments; neither has a published format |

## Sources

All opened on 15 November 2026. The "updated" dates are as shown on each page that day.

- **[S1]** Keep Britain Working: a national growth opportunity, September 2026. GOV.UK, updated 9 October 2026. https://www.gov.uk/government/publications/keep-britain-working-review-update-a-national-growth-opportunity-september-2026/keep-britain-working-a-national-growth-opportunity-september-2026
- **[S2]** Keep Britain Working: Final report. GOV.UK, independent report, updated 31 March 2026. https://www.gov.uk/government/publications/keep-britain-working-review-final-report/keep-britain-working-final-report
- **[S3]** Keep Britain Working: the story so far (June 2026). GOV.UK, updated 4 August 2026. https://www.gov.uk/government/publications/keep-britain-working-review-update-june-2026/keep-britain-working-the-story-so-far-june-2026
- **[S4]** Keep Britain Working continues drive to stop people falling out of the workforce. Department for Work and Pensions press release, GOV.UK, 3 July 2026. https://www.gov.uk/government/news/keep-britain-working-continues-drive-to-stop-people-falling-out-of-the-workforce
- **[S5]** New BSI standard to be developed to address UK's economic inactivity crisis. BSI press release, 31 March 2026. https://www.bsigroup.com/en-GB/insights-and-media/media-centre/press-releases/2026/march/new-bsi-standard-to-be-developed-to-address-uks-economic-inactivity-crisis
- **[S6]** Sickness absence in the UK labour market: 2025. Office for National Statistics, released 1 May 2026. https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/labourproductivity/articles/sicknessabsenceinthelabourmarket/2025 (already an OWHS anchor)

GOV.UK material is Crown copyright, quoted under the Open Government Licence v3.0.

## Comments

Open a comment on [this RFC's issue](https://github.com/openworkplacehealth/OWHS/issues/ISSUE_NUMBER_TBC), or email hello@openworkplacehealth.org. Comments arriving after the window closes are still read; the window is the period before a decision is recorded. Please declare any financial or professional interest in a product, provider, instrument or organisation your comment touches.
