# Changelog

Changes to the specification, the schemas, the reference validator and the published examples.
Corrections say what was wrong. Where a claim in the specification was stronger than the code
behind it, the entry says so plainly rather than describing the fix as an improvement.

Registry grade corrections are not here. They have their own numbered log at
`site/instrument-registry/corrections.html`, and grades remain frozen.

## 4 September 2026

Corrections following an external technical review of the published repository. Every defect below
was reproduced before it was fixed, and the reproduction is in `examples/` where an instance can
carry it.

### Fixed: the reference validator did not check dates

`tools/validate.py` constructed its validator without a format checker. In JSON Schema Draft
2020-12 `format` is an annotation unless a validator is told to assert it, so every `format: date`
in the schemas was decorative: a start date of `banana` and an end date of `2026-13-45` both
validated and the tool printed `VALID`. Level 1 conformance is the only level this repository
claims to implement, and this is the tool that implements it.

The validator now asserts every format. It also refuses to run, with exit code 2, when the
installation cannot assert a format the schema uses. `jsonschema` registers some format checkers
only when an optional package is present and silently accepts any value for a format it has not
registered, so a pass reported without them would overstate what was checked. The schemas use
`format: date` and nothing else today, so this guard is for the first time someone adds a
timestamp field.

New instance: `examples/AbsenceEpisode.dates.invalid.json`.

### Fixed: the endDate rule enforced nothing

`AbsenceEpisode` carried an `allOf` member commented "endDate must not precede startDate". It
re-asserted the type and format of `endDate`, which the property already declared, and enforced no
ordering. An episode ending six years before it started, with 99999 working days lost, validated.

JSON Schema compares an instance against a schema and never one field of an instance against
another, so this rule cannot be written in it. It is now a named cross-field rule, C1, listed in
the Level 1 definition and implemented in the validator. The same rule for occupational health
referral and assessment dates is C2. Within-record date ordering has moved from Level 2 to Level 1,
because it needs nothing beyond the instance; the cross-record rule stays at Level 2.

New instances: `examples/AbsenceEpisode.chronology.invalid.json` and
`examples/AbsenceEpisode.chronology-boundary.valid.json`, which pins the boundary as inclusive.

### Fixed: the direct-identifier block duplicated a check and overstated it

Each schema carried an `allOf` member commented "P1: forbid direct identifiers anywhere",
rejecting `name`, `nino`, `email`, `dateOfBirth` and `address`. Every one of those was already
rejected by `additionalProperties: false`. Removing the member changed no verdict on any example;
it changed the error count on one, because two keywords were reporting the same fact.

The word "anywhere" was untrue. The check is key-based, so an identifier written into the value of
a permitted string field validates cleanly. The privacy profile now states what is enforced
structurally and what is a producer obligation, and does not claim the second is the first.

The three lists had also drifted apart: `AbsenceEpisode` named five identifiers, `OHEpisode` four
and `ReturnToWorkOutcome` three, so one entity named an identifier another did not. That is an
argument for one mechanism rather than three hand-maintained copies of a rule.

### Fixed: a contradiction in the AggregateReport field table

`value` was marked unconditionally required, while Section 9 required a producer below an
aggregation floor to set `suppressed: true` and not emit the value. Both could not be satisfied at
once, so no conformant suppressed report could exist and P5 was unimplementable as published.
`value` is now required when `suppressed` is false and must be absent when it is true. `interval`
must also be absent when a report is suppressed, because an interval discloses the value it
suppressed to within its own width. An erratum sits with the table.

This corrects the specification. It does not change what a producer below a floor was always
required to do.

### Fixed: the validator's exit codes conflated two different failures

Malformed JSON, an invalid schema and a missing argument all exited 1 with a traceback, which is
what the tool also does when an instance simply does not conform. Anything reading the exit code
could not tell "this record is not conformant" from "your schema is broken". Tool and schema errors
now exit 2 and print a `[tool]` line to standard error; 0 and 1 mean what the usage line says.

### Fixed: the specification linked its own validation report at the wrong path

The repository copy of the draft linked `validator/validation_report.json` twice. The file is at
`examples/validation_report.json`. The published copy was already correct, which is how a manual
sync between two copies of one document tends to fail.

### Added: the validation report is generated rather than maintained

`tools/build_validation_report.py` regenerates `examples/validation_report.json` by running every
example instance through the validator, and fails if any instance disagrees with the verdict its
filename claims. The report is the evidence for the Level 1 claim, so it should not be written by
hand.

### Changed: what Level 3 says about itself

The conformance section now states that no tool in this repository verifies Level 2 or Level 3,
and names three parts of Level 3 that no payload can carry:

- A recipient can check that a report is internally consistent with the `n` it declares. It cannot
  check that `n` is true.
- If a producer omits the cells that fell below a floor, a recipient sees a shorter list and
  nothing else. "Refuse, don't hide" only has an observable meaning if a Level 3 producer emits a
  suppressed report for every cell it would otherwise have reported.
- No payload records where a value was sent, so the visibility classes are verified by review of a
  producer's implementation and not by any validator.

That paragraph is worse reading than the one it replaces. It is the only version this repository
can defend.

### Error counts that moved

`AbsenceEpisode.invalid` fell from five errors to four, because a duplicate identifier assertion
was removed. Nothing was stopped being checked. No verdict changed on any published example.
