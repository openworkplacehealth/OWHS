# RFC 0002: Subject-identifying constructs

| | |
|---|---|
| Status | Draft; opens for comment with the public release |
| Affects | Privacy profile (P2, P3); `codelists/construct-domain.json` (a new field); spec section 3.3 open question 9 |
| Breaking | No, if adopted as proposed. It adds a field and a rule; it withdraws nothing |
| Drafted | 2 September 2026, after external review of the registry's scope |
| Decision | Not yet taken; must be decided before any subject-identifying code is admitted under RFC 0001's conditions |

## Summary

Some constructs are about a person other than the respondent. Leadership quality, supervisor support as rated by a team, and manager fairness are the common ones. A team aggregate on any of them is personal data about one identified manager, however many respondents contributed to it.

The privacy profile's aggregation floors (P2: n≥5 for aggregate outputs, n≥10 for finer cuts) protect respondents: below the floor, an output could be traced back to who said it. They do nothing for subjects. An aggregate of twelve responses on "my manager treats people fairly" passes every floor and still says one thing about one named person, to that person's employer.

The standard has not decided whether such constructs enter the vocabulary at all, and if they do, under what visibility class and what rule for the subject. This RFC proposes that decision.

## 1. The problem stated precisely

A construct is **subject-identifying** when the entity it describes is a specific person, or a group small enough to identify a specific person, other than the respondent, and that person can be named from the output's grouping alone (a team's manager is known from the team).

The distinction is not whether the construct mentions a manager. "I get the support I need from my manager" describes the respondent's experience of support and is grouped under `support`; aggregated across an organisation or a large department it identifies no one. The same item aggregated by team, where each team has one manager, identifies that manager. So subject identification is a property of the construct **and** the grouping together, and the rule has to bind at output time, not only at code-definition time.

## 2. Proposal

**2.1 A new field on construct-domain codes.** `subjectIdentifying`: `true` where the construct's object is a person other than the respondent (leadership quality, manager fairness, supervisor behaviour); `false` otherwise. All eleven current codes and all five codes proposed in RFC 0001 are `false`.

**2.2 A grouping rule in the privacy profile (new P6).** For any observation whose construct is `subjectIdentifying: true`, or whose construct is `false` but whose grouping key resolves to a unit with a single identifiable supervisor, an employer-visible aggregate is permitted only where the grouping unit contains at least the P2 floor of respondents **and** at least a stated minimum of distinct subjects (proposed: 3), so that no output describes one identified person. Below that, the producer refuses to emit.

**2.3 A subject's rights are the same as a respondent's.** Where a subject-identifying output is lawfully produced (for example at organisation level), the subject is a data subject under the applicable data-protection law for that output, and the producer's documentation must say so. The standard does not create the right; it records that the right exists.

**2.4 Sequencing.** No construct-domain code with `subjectIdentifying: true` is admitted until this RFC is decided. Leadership quality is therefore deferred from RFC 0001 rather than declined.

## 3. Alternatives considered

- **Exclude subject-identifying constructs from the vocabulary entirely.** Simple, and it removes a real class of measures (leadership quality is among the best-evidenced predictors of team wellbeing in the occupational literature). Rejected as proposed default; open for comment.
- **Treat them as a safeguarding category.** Wrong tool. Safeguarding categories exist to protect the respondent from the employer; here the person needing protection is a third party, and the harm is different in kind.
- **Leave it to producers.** The spec's honesty pass already lists this as a governance question the schema cannot make (section 3.3, item 9). Leaving it to producers would make the standard silent on exactly the case where an implementer needs a rule to point to.

## 4. What this RFC does not decide

Whether any particular leadership or supervisor instrument enters the registry. The registry grades evidence about instruments; it does not decide what may be reported to an employer.

## Comments

Open a comment on this RFC's issue once the repository is public; until then, email hello@openworkplacehealth.org. Please declare any financial or professional interest in an instrument, product or organisation your comment touches.
