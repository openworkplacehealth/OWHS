# Supplied-entity graph validation, v0.2

`tools/check_entity_graph.py` checks a producer-side bundle of v0.2 records for organisation-scoped integrity: that the records
declared to belong together do belong together. It is an optional check on a supplied set of records. It is not a release envelope,
not a roster, not a privacy assessment and not a conformance certificate.

## The envelope

`schemas/bundles/EntityGraph-v0.2.json` is a closed object with every field required:

| Field | Meaning |
|---|---|
| `schema_version` | the constant `"0.2"` |
| `comparisonAsOfDate` | the producer-declared calendar date at which the comparisons named by the supplied reports are intended to apply; not the system clock, a publication date or the date of the observations; historic comparisons carry their historic intended date, and comparisons intended at different dates need separate bundles |
| `organisations` | groups, each one `organisation` (an Organisation) plus all thirteen entity arrays: `units`, `workers`, `absences`, `rtwOutcomes`, `ohEpisodes`, `adjustments`, `entitlements`, `utilisations`, `disabilityParticipations`, `contexts`, `observations`, `administrations`, `reports` |
| `benchmarks` | BenchmarkRelease records, global to the bundle |
| `crosswalks` | Crosswalk records, global to the bundle |

Empty arrays are valid; missing arrays are not. Every record validates against its exact v0.2 entity schema, resolved from the local
schema inventory only (no URL in an instance is fetched), with formats asserted, and then against the named within-record rules C1 to
C18. An omitted optional reference means no relationship was declared; a present empty string is a reference that must resolve and
cannot.

Identity within a bundle is (organisation, entity type, primary id): `orgId` for the organisation, `unitId`, `pseudonymId`, `episodeId`,
`outcomeId`, `ohEpisodeId`, `adjustmentId`, `entitlementId`, `utilisationId`, `reportId` (DisabilityParticipation), `contextId`,
`observationId`, `administrationId`, `reportId` (AggregateReport); benchmark releases are identified by the pair (`benchmarkId`,
`releaseVersion`). Equal strings in different organisations or different entity types are different records: the same pseudonym in two
organisations does not establish a shared person. Crosswalk has no primary id and nothing references it; exact duplicate rows are
repeated declarations, not independent evidence, and no uniqueness is imposed on (`constructCode`, `crosswalkVersion`).

## Order of checks

1. Strict JSON: duplicate object keys at any depth, `NaN`, `Infinity` and overflowing numeric literals are refused before any
   dictionary is built. Strings containing those words are ordinary strings.
2. Structure: the envelope and every record against its schema. A structural failure stops here; the graph and measurement stages are
   listed as not evaluated and the result is invalid. Malformed JSON, wrong roots, wrong array or record types are diagnosed, never a
   traceback.
3. Within-record rules C1 to C18 (the same functions as `tools/validate.py`) and any supplied profiles.
4. G01 and G02 (identity and scope). When they fail, no ambiguous index entry is selected and nothing downstream is attempted: G03 to G10
   and the measurement checks are listed as not evaluated because identities are invalid, and every relation record says resolution was
   not attempted. Only when identities hold do G03 to G10 run.
5. The measurement-bundle checks of `tools/check_measurement.py`, unchanged, on each organisation's projection (`contexts`,
   `observations`, `administrations`, `reports`); they run only when G01 to G10 pass, because their joins rest on the identities and
   references those rules establish.

Before any of this, the complete configuration is preflighted with the single-record validator's contract: the envelope schema, the
sixteen entity schemas and the profile-envelope schema are read as strict JSON, must meta-validate, may use only formats this installation
asserts, and may carry only references that resolve locally (or, for the envelope, to a schema in the checked inventory), unused branches
included; nothing is fetched. Every supplied profile is read and preflighted the same way (its references must resolve inside its own
document, embedded resources included) before any record is judged, and before the empty-inventory result: an empty bundle with a
malformed or missing profile is a tool error, and an empty bundle with a valid profile is `not_evaluated` with that profile recorded as
unused. The shared validator and the measurement checker are loaded through explicit error boundaries: a missing, unloadable or
substituted dependency, a measurement check that raises or exits, or a measurement result that is not (list of strings, list of strings,
dict) is a tool error, never an empty result standing for a pass.

| Rule | Check |
|---|---|
| G01 | every record carrying `orgId` equals its enclosing Organisation's `orgId`; the three older episodes (absence, return to work, OH) inherit the group scope for this checker only, and no field is injected into a source record |
| G02 | unique group `orgId`, unique scoped entity keys, unique benchmark (`benchmarkId`, `releaseVersion`); duplicates are errors even when byte-identical, with no first-wins or last-wins |
| G03 | every present declared intra-organisation reference resolves to exactly one supplied target in the enclosing group; a match in another group fails |
| G04 | ReturnToWorkOutcome and its AbsenceEpisode, OHEpisode and its optional linked AbsenceEpisode, ReasonableAdjustment and its optional source OHEpisode share one `pseudonymId`; both records' worker references must also resolve |
| G05 | OrgUnit parent links form an acyclic graph within each organisation, walked iteratively (C18 already catches the direct self-loop) |
| G06 | `rtwDate`, when present, is on or after the linked AbsenceEpisode's `startDate`; it is not required to follow `endDate` (phased return and a continuing episode are not rejected), and no date is inferred from the outcome label |
| G07 | every report `benchmarkRef` resolves by the exact (`benchmarkId`, `releaseVersion`) pair; another version is never substituted |
| G08 | the referenced release's `measure.metricCode` equals the report's `metricCode`; equal strings are declared identity only |
| G09 | a referenced release with `leaveOneOut` true names the referencing organisation as `excludedOrgId`; an unreferenced release's excluded organisation need not be supplied |
| G10 | `comparisonAsOfDate` lies within the referenced release's `validFrom` and `validTo`, inclusive; unreferenced old releases may be carried as inventory |

G03 reference map: OrgUnit.parentUnitId and WorkerPseudonym.unitId and AggregateReport.unitId to OrgUnit.unitId; the pseudonymId of
AbsenceEpisode, ReturnToWorkOutcome, OHEpisode, ReasonableAdjustment, WellbeingObservation and InstrumentAdministration to
WorkerPseudonym.pseudonymId; BenefitUtilisation.entitlementId to BenefitEntitlement.entitlementId; the contextId of WellbeingObservation,
InstrumentAdministration and AggregateReport to MeasurementContext.contextId; ReturnToWorkOutcome.absenceEpisodeId and
OHEpisode.linkedAbsenceEpisodeId to AbsenceEpisode.episodeId; ReasonableAdjustment.sourceOhEpisodeId to OHEpisode.ohEpisodeId.

## Profiles

Each `--profile` envelope is validated against `profiles/profile-envelope.schema.json` first; its id, version and SHA-256 are recorded;
it is dispatched only to records whose exact schema `$id` it names in `core_schema_ids`, and applied with the same validator classes
as the single-record tool, so a profile can neither override the core nor the C rules. Two different envelopes for one profile and
version, and a missing or malformed profile file, are tool errors. A valid profile matching no supplied record is reported as unused,
not as applied or passed. An extension namespace with no supplied profile covering that record's entity is listed as unchecked.

## The result

Structured JSON on stdout, and written atomically to `--out` when given (a failed run, a tool error included, replaces any earlier
report with its current result, invocation errors included once an unambiguous `--out` was given; no stale success survives; a
destination that cannot be written is itself reported as a tool error on stdout and stderr, saying the earlier report was not replaced;
an `--out` without a value, or given more than once, invents no destination and writes nothing). Fields: `report_schema_version` (1.0), the input's SHA-256, the checker's
and every schema's SHA-256 (`schema_sha256`), the shared validator's, the measurement checker's and the profile-envelope schema's SHA-256
(`dependency_sha256`), `comparisonAsOfDate`, `state`, `entity_counts` by type and `organisation_groups`, `resolved_links` as one record
per relation (`declared` occurrences of the scoped reference, `resolved`, `unresolved`, and a `state`: `evaluated`, `no_declared_edge`
when no record carries the reference after the stage examined it, or `not_evaluated` with the reason when resolution was not attempted;
these count references, not people or independent evidence), `checks_performed` and `checks_not_evaluated` (only stages that actually
ran are listed as performed; after an identity failure the performed list ends at G01-G02; when G03 to G10 ran and failed, the
measurement checks are listed as not evaluated with the true reason: references unresolved, graph constraints failed, or both), `errors` (rule or schema keyword, JSON
pointer, diagnostic, and for G08 to G10 `related` pointers to the report's `benchmarkRef` and the release record), `review_items` (every
resolved comparison is `comparison_not_established`; measurement interpretation items from the retained checks),
`external_references_not_checked` (item and instrument identities, crosswalk semantics, extension namespaces without a profile),
`profiles` (applied with id, version, hash and counts; unused), `measurement_gate` (which gate ran and its hash) and `not_established`.

Pointers are RFC 6901 JSON pointers: the empty string is the root, every token is prefixed with `/` and escaped (`~` as `~0`, `/` as `~1`),
and each locates the offending existing value or, when a required property is absent, its nearest existing parent. G01 points at the
record's `orgId`; G02 at the duplicated key (or the duplicate release record); G03, G04 and G06 at the reference or date field; G05 at the
organisation's `units`; G07 at the report's `benchmarkRef`; G08 at `/organisations/<g>/reports/<r>/metricCode`; G09 at
`/benchmarks/<b>/excludedOrgId`; G10 at `/comparisonAsOfDate`; S07 at the organisation group, with the retained checks' own text inside
the message. The checker refuses to emit a pointer that does not resolve in the parsed instance (a tool error naming the defect).

States and exit codes: `checked_with_limits` (0), `not_evaluated` for an entirely empty inventory (0, no certificate and nothing
exercised), `invalid` (1) and `tool_error` (2: a missing, malformed or substituted schema, profile or dependency, an unasserted format or an
unresolved reference anywhere in the configuration, a failed or malformed gate result, an unwritable report destination). No record content is echoed as an output dataset; a local report and its hashes can still be sensitive, and no workflow
uploads real bundles or reports as public artefacts. The public self-test uses only the synthetic fixtures in `examples/bundles/v0.2/`.

The success statement, verbatim:

> The supplied records passed the listed structure, within-record and relationship checks. Unchecked external references and
> interpretation limits are listed in the report. This result does not certify a complete workforce dataset, anonymity, lawful processing,
> safe disclosure, clinical validity, benchmark comparability or Level 2 or Level 3 conformance.

## What is not established

A matching metric code is declared identity, not comparability: `BenchmarkRelease.measure.scoringDescriptorRef` is a single string and
`AggregateReport` does not carry the instrument and version pair, so method identity with a MeasurementContext is not proved and is not
inferred from provenance strings. Population, sampling, time transfer, method, unit and score equivalence, the truth of a declared
leave-one-out exclusion, quantile construction, source authenticity and privacy assessment are listed as not established in every
report. The supplied WorkerPseudonym count is not headcount, eligibleN, n or benchmark composition: the bundle is the set of references the
checks need, not a workforce census, and a period count may legitimately exceed a small demonstrative roster. No cross-period unit
membership, tenure history, hours conversion, recurrence, treatment effectiveness, disability denominator or lawful benefit entitlement
is derived from these joins, and no diagnosis or OH report content is needed or accepted to satisfy them.
