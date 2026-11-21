# The OWHS minimum group size rule (`owhs-mgs`)

**Status:** proposed by [RFC 0003](../0003-uk-measures-profile.md). Open for comment from 23 November 2026 to 8 January 2027, not released. UK English. CC-BY 4.0.

**Cite as:** Open Workplace Health Standard, *Minimum group size rule* (`owhs-mgs@0.1.0`), draft of 15 November 2026.

**Short form.** No figure about fewer than five people. If a group is too small, the figure is withheld or the group is merged with another, and the report says so.

This rule names, and spells out, what the OWHS specification already requires: the privacy profile's P2 and P5, and the floor of ten on the `DisabilityParticipation` record. It does not change the floors. It adds the working detail a producer needs: what the five counts, how to withhold, how to merge, and how to stop a withheld figure being worked out from the ones around it.

---

## 1. Why a written rule

The government's published plans for workplace health data rely on a threshold and do not state one. The September 2026 Keep Britain Working update says of its employer data project that "Small-number results will be suppressed or combined where necessary", and of its employee toolkit that "Employers receive only protected, aggregated insight above a suppression threshold, never individual answers" [S1]. No number appears in that document or in the earlier Keep Britain Working documents opened for this draft [S2][S3][S4].

A threshold that is not written down cannot be checked. A provider can say its reports are "aggregated" and still show that two people in a team of six were referred. This rule gives a number, a method and a name, so that a report can state which rule it follows and a reader can test it.

---

## 2. The rule

**R1. The floor is five people.** A figure may be shown to an employer, or to anyone outside the organisation that produced it, only if it describes at least five distinct people.

**R2. The floor is ten for the most sensitive figures.** Measures of severe distress need at least ten, as the OWHS v0.2 specification already requires, and the v0.2 specification sets ten for the `DisabilityParticipation` record. In the `owhs-uk-measures` profile, `disability-participation` and `disability-retention-12m` need an `n` of at least ten. By the core definition, `n` is the distinct people contributing to the estimate. For `disability-participation` that is the people who answered, not the number of disabled people, whose count is held to zero or at least five by R4. For `disability-retention-12m` it is the people who said yes a year earlier, so there the ten falls on disabled people.

**R3. It counts people.** Not contacts, calls, sessions, claims or survey responses. One person who rings a helpline six times is one person. A producer that cannot count distinct people cannot show the figure.

**R4. It applies to both sides of a share.** For "12 of 17", the 17 is the group and the 12 is the count.
- The group must be at least five.
- The count must be zero, or at least five.
- The remainder (here 5) must be zero, or at least five, because anyone can subtract.

A zero count may be shown, since it says nothing about any one person beyond what the group size already says.

**R5. All of a group is not shown for a sensitive status.** Where the count equals the group ("14 of 14 were referred") the figure tells the reader something about every member. For figures about health, service use or work status it is withheld. This is the one case where R4's "remainder of zero" is not enough.

**R6. Withhold or merge.** A figure that fails R1 to R5 is handled in one of two ways:
- **Withhold** (suppress): the row is still sent, marked `suppressed: true` with a `suppressionReason`, and carries neither the value nor the count. (In a v0.2 `AggregateReport`, `n` is the size of the group the figure describes and the schema requires it on every row; there the value and its interval are what is withheld. In a `ProviderReturn` the count is often the figure itself, so a withheld row carries no `n`. Whether a group size below the floor may be shown at all is listed as an open question in RFC 0003.)
- **Merge** (combine): two or more categories are added together into one row that clears the floor. The row lists the categories that were merged.

Merging is preferred where the merged group still means something, because the reader keeps more information.

**R7. No working it out.** A withheld figure must not be recoverable from what is shown.
- *Within a table.* If a total and all but one of its parts are shown, the missing part is the difference. Withhold a second part or merge until every hidden remainder is at least five.
- *Across overlapping groups.* Do not publish figures for two groups where one sits inside the other and the difference is one to four people (a department of 30 and the same department without its team of three).
- *Across time.* Do not publish the same figure for two periods where the people who joined or left the group between them number one to four and the figure moves with them.

**R8. Refuse, do not hide.** A conformant producer does not send the withheld number in a hidden field, a tooltip, an export or a footnote. The schema makes a withheld row that still carries its value invalid.

**R9. Say what was withheld.** Every report states the floor it applied, and every withheld row gives its reason. Readers can see what is not being said. (OWHS privacy profile P5.)

**R10. A higher floor is always allowed. A lower one never is.** A producer may set its floor at ten or twenty. A profile may raise the floor and may not lower it.

**R11. Some things are never shown at any size.** Signals in the OWHS safeguarding categories are excluded from employer-visible output whatever the group size (privacy profile P4). This rule does not relax that.

**R12. Some things are exempt because they are individual by nature.** The narrow `individual-employer` class in OWHS (a released fitness opinion, a reasonable adjustment, a return-to-work plan the worker is party to) is not an aggregate and is outside this rule. Nothing in a group-level return may rely on that exemption.

---

## 3. How suppression looks in a file

A shown row:

```json
{ "metricCode": "cases-opened", "breakdown": { "list": "construct-domain", "code": "musculoskeletal" },
  "unit": "people", "base": 17, "n": 7, "value": 7, "suppressed": false }
```

A withheld row. The category is named, the number is not:

```json
{ "metricCode": "cases-opened", "breakdown": { "list": "construct-domain", "code": "demands" },
  "unit": "people", "base": 17, "suppressed": true, "suppressionReason": "below-floor" }
```

A merged row:

```json
{ "metricCode": "cases-opened",
  "breakdown": { "list": "access-route", "code": "combined", "combinedCodes": ["hr", "self-referral"] },
  "unit": "people", "base": 17, "n": 8, "value": 8, "suppressed": false }
```

These rows are taken from `examples/ProviderReturn.valid.json` in this folder, which passes the reference validator.

---

## 4. Why five

Stated plainly: five is a convention, not a proof. The OWHS specification already says its floors "adopt commonly used conventions" and do not claim to mirror any single official rule. This draft does not cite another body's threshold. On 15 November 2026 the disclosure control pages that could be opened did not state a number on the page read, and two guidance pages returned errors, so no comparison is offered.

The reasons for five are practical.

1. **Below five, a member of the group can work out the others.** In a group of three, anyone who knows their own answer and one colleague's knows the third. Each added person makes that harder. Five is the point at which a single figure about the group stops pointing at anyone in particular in most ordinary cases.
2. **Small employers must be able to see something.** The Keep Britain Working documents say the approach will be tested with organisations of all sizes [S1]. A floor of twenty would leave most small firms, and most teams in larger ones, with empty reports. People stop trusting a tool that never tells them anything, and then stop answering it.
3. **Five is not the only protection.** It works with the rest of the OWHS privacy profile: no names or other direct identifiers anywhere; demographics in bands; individual questionnaire results never visible to the employer; safeguarding signals excluded at any size; a higher floor of ten for the most sensitive figures; and a producer that refuses to send a figure it should not.
4. **It is simple enough to check.** A rule that needs a statistician to apply will not be applied by a twelve-person company or audited by its staff. A single whole number can be.

**What five does not do.** It does not make data anonymous, and OWHS does not describe group figures that way. In a small workplace people know each other, and a figure about five people can still be linked to a person by someone who knows the context. The rule reduces that risk. It does not remove it. Where a figure is sensitive enough that this matters, use ten, or do not publish.

---

## 5. Conformance

| Check | Where it is enforced today |
|---|---|
| A shown row has a count of zero or at least five, and a group of at least five (R1, R4) | In schema, per row (`schemas/ProviderReturn.json`) |
| A withheld row carries a reason and no value or count (R6, R8, R9) | In schema, per row |
| The report declares its floor, and the floor is at least five (R9, R10) | In schema |
| Counts are of distinct people (R3) | In schema, as a declared `countBasis` |
| No individual records in a group return (R12) | In schema |
| The remainder of a share is zero or at least five (R4) | Level 3 check, specified here, not yet in the reference validator |
| All-of-a-group figures withheld (R5) | Level 3 check, not yet in the reference validator |
| No recovery by subtraction, overlap or time (R7) | Level 3 check across rows and across returns, not yet in the reference validator |
| Floor of ten for the most sensitive figures (R2) | In schema for `AggregateReport` rows declared `severe-distress` (core) and on `n` for `disability-participation` and `disability-retention-12m` (the `owhs-uk-measures` envelope; for `disability-participation` `n` is the people who answered, not the number of disabled people); otherwise a Level 3 check |
| An `AggregateReport` with `n` of four or fewer is withheld (R1) | In schema (core v0.2) |

The reference validator runs Level 1 only. The Level 3 checks above are written so that a fuller validator can implement them; until then they rest on the producer.

---

## 6. Open questions for governance

1. Whether five should rise for particular measures beyond those already at ten.
2. Whether R5 should apply to every figure or only to sensitive ones, and who keeps the list of what is sensitive.
3. How R7 across time should work for very small employers, where almost any change in headcount is one to four people.
4. Whether to align to a national threshold if the Workplace Health Intelligence Unit publishes one. The position in GOVERNANCE.md applies: align, do not compete. If the national floor is higher, R10 already allows it.

---

## Sources

Opened 15 November 2026. Numbered as in `owhs-uk-measures-0.1.0.md`.

- **[S1]** Keep Britain Working: a national growth opportunity, September 2026. GOV.UK, updated 9 October 2026.
- **[S2]** Keep Britain Working: Final report. GOV.UK, updated 31 March 2026.
- **[S3]** Keep Britain Working: the story so far (June 2026). GOV.UK, updated 4 August 2026.
- **[S4]** Keep Britain Working continues drive to stop people falling out of the workforce. DWP press release, 3 July 2026.
