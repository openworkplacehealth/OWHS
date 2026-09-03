# RFC 0001: Construct-domain code list v0.2

| | |
|---|---|
| Status | Draft; opens for comment with the public release |
| Affects | `codelists/construct-domain.json` (0.1.0 to 0.2.0), the crosswalk, the question-bank topic-group mapping |
| Breaking | No. Additions and two new optional fields; no code is renamed or withdrawn |
| Drafted | 2 September 2026, after external review of the registry's scope |
| Decision | Not yet taken |

## Summary

The construct-domain list at 0.1.0 has eleven codes: the six HSE Management Standards domains verbatim, plus five outcome constructs. It was built to cover the question bank's items as they stood, and three things have since shown it to be short.

1. The privacy profile (P4) excludes safeguarding-category signals from employer-visible outputs at any group size, and `codelists/safeguarding-category.json` names those categories. But no construct-domain code corresponds to any of them, so a producer cannot tag an observation of bullying or harassment exposure with a construct code at all, and the exclusion has nothing in the construct vocabulary to attach to.
2. The question bank groups its items under thirteen topic groups. Five of them (`fairness`, `culture`, `behaviours`, `environment`, `time`) map to no construct-domain code. A group that maps to no code is a second vocabulary by accident.
3. The instrument registry's admission rule requires every proposed instrument to map to a construct-domain code or carry a domain proposal. Several instruments in common UK use, and the first candidates for admission, measure constructs the list cannot name (organisational justice, job insecurity, work-life interference, loneliness at work).

This RFC proposes five new codes, two new fields on every code, and a published mapping from question-bank topic groups to codes. It does not propose codes for psychological safety, leadership quality, digital always-on demands, meaning and purpose, or financial strain; the reasons are in section 5.

## 1. The admission conditions for a code

A construct-domain code is a heavier commitment than a registry record. Schemas pin the code list by version, the crosswalk carries every code to the HSE Management Standards and ISO 45003, and implementers build against it. A code that has to be withdrawn is a breaking change. Five conditions therefore have to hold together, and this RFC proposes them as the standing rule for any future addition:

1. **Defined and distinguishable.** The domain has a published definition and a statement of what it is not. Where a candidate is a facet of a code that already exists, it is recorded as a definition note or a sub-code, not as a new code.
2. **Measured, not theorised.** At least one instrument or question-bank item measures the domain, with located published evidence. There is no code without a measure.
3. **Crosswalk resolved.** The domain has an entry mapping it to the HSE Management Standards and to ISO 45003, or an explicit statement of none with the reason.
4. **Asked for.** A question-bank item, an implementer question, a sweep finding or a public proposal.
5. **Safeguarding classified.** Before publication, the domain carries a safeguarding classification and a default visibility class (section 3).

## 2. Proposed codes

| Code | Label | Definition (short) | Is not | Measured by | HSE MS | ISO 45003 | Asked for by |
|---|---|---|---|---|---|---|---|
| `bullying-harassment` | Bullying and harassment | Exposure to repeated negative acts at work, or disclosure of such exposure | General relationship quality (`relationships`); discrimination on a protected characteristic (a separate safeguarding category, not proposed as a code here) | NAQ-R; question-bank `fairness` items | Relationships | 6.1.3 social factors: bullying, harassment | question bank; safeguarding-category list; registry candidate NAQ-R |
| `organisational-justice` | Organisational justice | Perceived fairness of outcomes, procedures, and interpersonal and informational treatment | Bullying (a conduct exposure, not a fairness judgement); `role` clarity | Colquitt-tradition justice measures; question-bank `fairness` items | Relationships (partial), Role (partial) | 6.1.3 social factors: civility and respect, recognition and reward | question bank; registry candidate |
| `job-insecurity` | Job insecurity | Perceived threat to the continuity or valued features of the job | Organisational `change` as a process; financial wellbeing as an outcome | JCQ job-insecurity subscale; question-bank `change` items | Change | 6.1.2 how work is organised: job security and precarious work | question bank; registry candidate JCQ |
| `work-life-interference` | Work-life interference | Conflict between work demands and life outside work, in either direction | Working-time arrangements as a fact (a data field, not a construct); `demands` as workload | Work-family conflict scales; question-bank `time` items | Demands (partial) | 6.1.3 social factors: work-life balance | question bank; registry candidates |
| `loneliness-isolation` | Loneliness and isolation at work | Perceived lack of connection or belonging at work | `support` as instrumental help; remote-working arrangement as a fact | Workplace loneliness measures; ONS loneliness item in the question bank | Support (partial), Relationships (partial) | 6.1.3 social factors: support; 6.1.2 how work is organised: remote and isolated work | question bank; registry candidate |

ISO 45003 references name the hazard as the standard's 2021 text lists it, under the clause family it sits in; the exact clause numbers are confirmed against the published text before the decision is recorded, and any correction is noted on this RFC.

Each label, definition and "is not" statement is proposed for the code list's `label`, `definition` and `distinguishedFrom` fields. The crosswalk gains one row per code.

## 3. Two new fields on every code

The privacy profile cannot apply P4 to a category the vocabulary cannot name. Every construct-domain code therefore carries:

- **`safeguardingCategory`**: `null`, or a code from `codelists/safeguarding-category.json`. Where non-null, observations under this construct fall inside the P4 exclusion.
- **`defaultVisibilityClass`**: one of `open`, `aggregate-only`, `individual-employer`, `individual-never`, as defined in the privacy profile (P3). A producer may apply a stricter class; it may never apply a looser one.

Proposed values for the existing eleven codes: `safeguardingCategory: null`, `defaultVisibilityClass: aggregate-only`. For the five proposed codes: `bullying-harassment` carries `safeguardingCategory: bullying-harassment` and `defaultVisibilityClass: individual-never`; the other four carry `null` and `aggregate-only`.

A domain in a safeguarding category is published as a code with `individual-never` visibility and no employer-visible aggregate at any group size. A conformant producer refuses to emit, rather than hiding what it has emitted.

The registry and the standard do different jobs here. The registry describes what the published literature says about instruments, including instruments that measure bullying and harassment: that literature is public science and describing it takes nothing from anyone. The standard governs what data may flow to an employer, and it forbids employer-visible outputs in the safeguarding categories. A domain can be gradeable in the registry and unreportable under the standard.

## 4. Question-bank topic groups

The question bank's topic groups are a navigation facet, not a vocabulary. This RFC proposes that the mapping from group to construct-domain codes is published in the question-bank dataset, that the build fails on any group mapping to no code, and the following mapping for the thirteen current groups:

| Group | Codes |
|---|---|
| outcomes | `mental-health` |
| health | `physical-health`, `musculoskeletal`, `sleep-fatigue` |
| behaviours | `physical-health` (health behaviours are measured as facets of physical health; no separate code) |
| demands | `demands` |
| control | `control` |
| support | `support`, `loneliness-isolation` |
| fairness | `organisational-justice`, `bullying-harassment` |
| role | `role` |
| change | `change`, `job-insecurity` |
| time | `work-life-interference`, `demands` |
| environment | `physical-health` (environmental exposures as facets; a physical-environment code is not proposed until an instrument in the registry measures it) |
| financial | `financial-wellbeing` |
| culture | `support`, `control` (organisational policy items are measured as perceived support and control; no separate code) |

Three groups (`behaviours`, `environment`, `culture`) map to codes by facet rather than by identity. If comment finds that unsatisfactory, the alternatives are a code proposal that meets section 1, or renaming the group.

## 5. Candidates not proposed

- **Psychological safety.** Well measured (Edmondson's scale) and much asked for. Deferred because its relationship to `support` and `relationships` is not yet distinguishable enough to survive condition 1 without a definition note that would itself need comment.
- **Leadership quality.** Measured and asked for, but a construct about an identified person other than the respondent. Deferred to RFC 0002, which has to be decided first.
- **Digital always-on demands.** Watched. Measured by newer scales with a thin evidence base; may be a facet of `demands` and `work-life-interference` rather than a code.
- **Meaning and purpose.** Not proposed. A facet of `role` as the question bank already treats it.
- **Financial strain.** Not proposed. Covered by `financial-wellbeing`.

## 6. What this RFC does not decide

Which instruments enter the registry is decided under the registry's own admission rule, not here. Conformance with the HSE Management Standards or ISO 45003 is not claimed for any implementer by any crosswalk row: the crosswalk is descriptive.

## 7. Migration

Schemas that pin `construct-domain@0.1.0` continue to validate. Producers may adopt 0.2.0 when they choose; a producer emitting a 0.2.0 code under a schema pinned to 0.1.0 fails validation, which is the intended behaviour.

## Comments

Open a comment on this RFC's issue once the repository is public; until then, email hello@openworkplacehealth.org. Please declare any financial or professional interest in an instrument, product or organisation your comment touches.
