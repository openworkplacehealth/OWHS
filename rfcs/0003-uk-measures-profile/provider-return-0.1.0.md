# Proposed record type `ProviderReturn` 0.1.0: what a provider sends an employer each quarter

**Status:** proposed by [RFC 0003](../0003-uk-measures-profile.md) as a new core record type. Draft, not yet opened for comment, not released. Not endorsed by any government department, provider body or insurer. UK English. Spec text CC-BY 4.0; schema, code lists and examples Apache-2.0.

**What this is.** A common shape for the report an employee assistance programme, an occupational health provider or an insurer sends an employer: who used the service, what for in broad groups, how quickly, and what happened to their work, all at group level. One schema, one worked example, one command to check a file.

**Why.** The September 2026 Keep Britain Working update says: "No provider can compete reliably on outcomes, because comparable outcomes do not exist." It describes a future in which "providers could compete based on performance data, published in a common format." [S1] The June 2026 update lists, as a provider responsibility, "Collect and share performance data to create a transparent marketplace." [S3] No common format has been published in any of the documents opened for this draft. This is a first attempt at one, offered for providers and their professional bodies to correct.

**What it is not.** It is not a league table, a quality mark or a clinical record. It does not score providers. It defines how to write the numbers down so that two reports can be read side by side.

---

## 1. What the published text asks of providers

| Published text | Source |
|---|---|
| Providers should "Offer accessible, coordinated and work-focused support, with clear accountability and measurable outcomes." | [S1] |
| Workplace Health Provision has four functions: advice and guidance, case management, early support and treatment, and employer insight. | [S1] |
| Employer insight means "Collecting aggregate information on recurring employee needs and workplace barriers" and the outcomes that follow, to help employers improve how work is designed and supported. | [S1] |
| The unit would "Receive aggregate employee, employer and provider data, with clear safeguards and no unnecessary collection of identifiable information." | [S1] |
| "Provision is also where the most valuable intelligence in the system is generated, because it sees the problem at the point a person seeks help, rather than at the point they go absent." | [S1] |
| Return-to-work support should have "provision engaged within ten working days where needed". | [S1] |

**Not stated in any document opened:** which figures a provider should report, how often, in what format, or the minimum group size. Everything below is therefore **PROPOSED**.

---

## 2. The return

One file per provider, per employer, per period. Schema: `schemas/ProviderReturn.json`.

### 2.1 Envelope

| Field | Type | Req | Code list | Privacy | Notes |
|---|---|---|---|---|---|
| `returnId` | string | yes | | open | |
| `orgId` | string (opaque) | yes | | open | the employer; `Organisation.orgId` |
| `sizeBand` | string | no | codelist:org-size-band@0.1 | open | |
| `provider.providerRef` | string | yes | | open | |
| `provider.serviceType` | string | yes | codelist:provider-service-type@0.1 | open | EAP, occupational-health, GIP, PMI, cash-plan, MSK-service, wellbeing-intervention, other |
| `provider.entitlementId` | string (ref) | no | | open | to `BenefitEntitlement` |
| `periodStart` / `periodEnd` | string (date) | yes | | open | **PROPOSED:** calendar quarters |
| `eligibleHeadcount` | integer, at least 5 | yes | | open | people entitled to use the service in the period |
| `minimumGroupSize` | integer, at least 5 | yes | | open | the floor applied to every row |
| `suppressionRule` | const `owhs-mgs@0.1.0` | yes | | open | the rule the return follows |
| `measurementContext.producingSystem` | string | yes | | open | as `MeasurementContext` |
| `measurementContext.countBasis` | const `distinct-people` | yes | | open | contacts and sessions are not accepted |
| `measurementContext.knownLimitations` | string | no | | open | as `MeasurementContext` |
| `rows` | array | yes | | | see 2.2 |
| `ext` | object | no | | | profile namespaces only, as on every v0.2 record |
| **Forbidden** | | | | | names and other direct identifiers; `pseudonymId`; any list of workers, cases or episodes. The schema rejects them. |

### 2.2 Rows

Each row is one figure.

| Field | Type | Req | Privacy | Notes |
|---|---|---|---|---|
| `metricCode` | string | yes | open | codelist:provider-return-metric@0.1 |
| `breakdown.list` | string | no | open | an OWHS core code list: access-route, construct-domain, oh-referral-reason, absence-reason, fitness-opinion, rtw-adjustment, rtw-outcome |
| `breakdown.code` | string | with list | open | a code from that list, or `combined` |
| `breakdown.combinedCodes` | array of string | when combined | open | the codes that were merged |
| `unit` | string | yes | open | people, percent, working-days |
| `cohortStart` / `cohortEnd` | string (date) | no | open | for outcomes measured on an earlier cohort |
| `base` | integer, at least 5 | no | open (post-floor) | the group the figure is a share of |
| `n` | integer, 0 or at least 5 | unless withheld | open (post-floor) | the distinct people the figure is computed from |
| `value` | number | unless withheld | open (post-floor) | the figure |
| `suppressed` | boolean | yes | open | P5 |
| `suppressionReason` | string | when withheld | open | codelist:suppression-reason@0.1 |

A withheld row carries its reason and carries neither `value` nor `n`. The schema enforces this.

### 2.3 The figures

Ten metrics, the same for every type of provider. A provider reports those that apply to its service and leaves out the rest.

| `metricCode` | Unit | Plain definition | Numerator | Denominator (`base`) | OWHS fields |
|---|---|---|---|---|---|
| `people-using` | people | People who used the service at least once in the period | distinct people | `eligibleHeadcount` | `BenefitUtilisation.n` (distinct people; `usageCount` counts events, not people) |
| `utilisation-rate` | percent | The share of eligible people who used it | `people-using` | `eligibleHeadcount` | as above |
| `cases-opened` | people | New cases opened in the period. One case is one person | distinct people with a new case | `eligibleHeadcount`, or the total when broken down | distinct people with an `OHEpisode.referralDate` in the period (`BenefitUtilisation.claimCount` counts events, not people) |
| `first-contact-working-days-median` | working-days | The middle value of working days from referral or first request to the provider's first contact with the person | | cases opened in the period | `OHEpisode.referralDate` |
| `engaged-within-10wd-rate` | percent | The share of new cases where first contact came within 10 working days | cases with first contact within 10 working days | cases opened in the period | `uk-commitment`: `provision-engaged` |
| `cases-closed` | people | Cases closed in the period | distinct people | | `OHEpisode` |
| `absent-at-referral` | people | New cases where the person was off work when the case opened | distinct people | cases opened | `OHEpisode.linkedAbsenceEpisodeId` |
| `returned-to-work` | people | Of those off work when the case opened, those who returned | people with `outcomeType` full, phased or adjusted | `absent-at-referral` for the cohort | `ReturnToWorkOutcome.outcomeType` |
| `sustained-return-26wk` | people | Of those who returned in the cohort window, those still at work 26 weeks later | people sustained at 26 weeks | people who returned in the cohort window | `ReturnToWorkOutcome.sustainedAt` |
| `outcome-unknown` | people | Closed cases where the provider does not know what happened to the person's work | distinct people | `cases-closed` | |

**Breakdowns.** `cases-opened` may be broken down by route in (`access-route`), by referral reason (`oh-referral-reason`), by broad health reason (`absence-reason`, the ONS groups) or by the area of need (`construct-domain`). `cases-closed` may be broken down by fitness opinion (`fitness-opinion`) and by the types of adjustment recommended (`rtw-adjustment`). `returned-to-work` may be broken down by `rtw-outcome`. Every breakdown row obeys the floor.

**Why `construct-domain` for need.** In the OWHS code list its first six codes are anchored to the Health and Safety Executive's Management Standards domains, which describe features of the job: demands, control, support, relationships, role and change. That is the closest existing open vocabulary to "recurring employee needs and workplace barriers" [S1], and it is the list OWHS already uses for both measurement and services.

**Why `outcome-unknown` is required thinking.** Most providers do not learn whether a person returned to work or stayed. A format that only has room for good outcomes produces good outcomes. Reporting the unknowns makes the gap visible and gives the employer a reason to close it.

**The sustained return cohort.** A provider cannot report a 26-week outcome for someone who returned last month. The row therefore names an earlier cohort with `cohortStart` and `cohortEnd`: in a third-quarter return, people who returned in the first quarter.

### 2.4 What each kind of provider would typically send

| | EAP | Occupational health | Insurer (income protection, medical, cash plan) |
|---|---|---|---|
| `people-using`, `utilisation-rate` | yes | yes | yes |
| `cases-opened` by `access-route` | yes | yes | yes |
| `cases-opened` by `construct-domain` | yes | yes | where known |
| `cases-opened` by `oh-referral-reason` | | yes | |
| `first-contact-working-days-median`, `engaged-within-10wd-rate` | yes | yes | for early intervention and rehabilitation services |
| `cases-closed` by `fitness-opinion`, `rtw-adjustment` | | yes | |
| `absent-at-referral`, `returned-to-work`, `sustained-return-26wk` | where known | yes | for early intervention and rehabilitation services |
| `outcome-unknown` | yes | yes | yes |

This table is a proposal drawn from the OWHS entities, not from any provider's published reporting. It has not been tested with a provider.

### 2.5 What a return never contains

- Anything about one person. No pseudonyms, no case lists, no dates of individual events.
- Clinical content: diagnoses, symptoms, test results, session notes.
- Free text about cases.
- Anything in the OWHS safeguarding categories, at any group size (privacy profile P4). An EAP return under this profile cannot say how many people called about bullying. See open question 2.
- Counts of contacts or sessions presented as if they were people.

---

## 3. Worked example

`examples/ProviderReturn.valid.json` is a synthetic third-quarter 2026 return from an occupational health provider to an employer with 184 eligible people. Every figure is invented. It shows:

- 21 people used the service (11.4%), 17 new cases, 14 closed.
- Referral reasons: two shown, three small ones **merged** into one row of six.
- Route in: managers shown; HR and self-referral **merged**.
- Area of need: musculoskeletal and mental health shown; two small ones **withheld**. The two hidden figures add up to five, so neither can be worked out.
- Median of 4 working days to first contact; 70.6% within 10 working days.
- Fitness opinions: "fit with adjustments" shown; "fit" and "unfit" **withheld**.
- 11 people were off work when referred; 6 had returned.
- Sustained return at 26 weeks for the first-quarter cohort of 9: **withheld**, because the remainder would be fewer than five. The rule sometimes hides a good number. That is the cost of it.
- Outcome unknown: 0.

`examples/ProviderReturn.invalid.json` breaks the rules on purpose: a floor of three, counts of contacts, a list of cases with a pseudonym and a fitness opinion, an unsuppressed count of three, and a "suppressed" row that still carries its number. The validator raises seven errors.

**To check a file:**

```
python tools/validate.py schemas/ProviderReturn.json examples/ProviderReturn.valid.json
```

Run on 15 November 2026 on this branch with the repository's own `tools/validate.py` (formats asserted, `jsonschema` 4.26.0): the valid example returns `VALID`; the invalid example returns seven errors. Full output: `validation_report.json` in this folder.

**What the validator does not check.** It is the Level 1 structural validator. It does not check that codes exist in the code lists (Level 2), or the cross-row parts of the minimum group size rule (Level 3): remainders, all-of-a-group figures and recovery by subtraction. The worked example was checked for those by the separate checks recorded in `validation_report.json`. A provider's file would need the same care until a Level 3 validator exists.

---

## 4. How this fits the OWHS rules

`ProviderReturn` is a new record type, so under the OWHS profile rules it is a **core change request**, not something a profile can add on its own. It is drafted as a standalone schema so that it can be validated and argued over before an RFC. It reuses core field names and meanings (`n`, `value`, `suppressed`, `suppressionReason` from `AggregateReport`; the distinct-people `n` of `BenefitUtilisation`) and core code lists unchanged. It differs from `AggregateReport` in one deliberate way: a withheld row carries no `n`, because in a return the count is usually the figure itself. It adds two lists: `provider-return-metric` and `provider-service-type`. Gaps it exposed in the core are in RFC 0003 section 6.

---

## 5. Honesty pass

**Decisions others would dispute.**
1. *Quarterly.* No published text sets a frequency. Quarterly is this draft's choice. For a small employer most quarterly rows will be withheld. Annual returns, or pooled returns across several small employers, may be the only honest option below about 50 eligible people.
2. *The same ten figures for every provider.* An EAP, an occupational health service and an income protection insurer do different things. A shared core makes comparison possible and flattens real differences.
3. *People, never contacts.* Some services only count calls. Under this profile they cannot report until they can count people.
4. *Work outcomes from providers at all.* A provider often does not know the outcome and depends on the employer to tell it. The `outcome-unknown` row is the honest answer, but some will say providers should not be judged on what they cannot see.
5. *No satisfaction scores, no clinical outcome measures.* Left out of 0.1.0 because each needs a named instrument and its licence terms.

**Open questions.**
1. Whether a return to an employer and a return to the national unit should be the same file. The published text has providers sending aggregate data to the unit [S1]; this draft only defines the employer-facing return.
2. The safeguarding exclusion means an employer never learns from its EAP that workplace relationships are a recurring problem, which is arguably the most useful thing an EAP could tell it. Whether the broad domain `relationships` may be reported at a higher floor is a governance decision, not an implementer's.
3. How pooled arrangements for small firms should report, where no single employer clears the floor.
4. Whether fees, service levels or capacity belong in the format. They are left out here.

**Not established.** Whether any provider body or insurer body is drafting its own format. None was found in the documents opened, which were limited to GOV.UK and BSI. That is not evidence that none exists.

---

## Sources

Opened 15 November 2026. Numbered as in `owhs-uk-measures-0.1.0.md`.

- **[S1]** Keep Britain Working: a national growth opportunity, September 2026. GOV.UK, updated 9 October 2026. https://www.gov.uk/government/publications/keep-britain-working-review-update-a-national-growth-opportunity-september-2026/keep-britain-working-a-national-growth-opportunity-september-2026
- **[S3]** Keep Britain Working: the story so far (June 2026). GOV.UK, updated 4 August 2026. https://www.gov.uk/government/publications/keep-britain-working-review-update-june-2026/keep-britain-working-the-story-so-far-june-2026
