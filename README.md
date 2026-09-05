# OWHS: the Open Workplace Health Standard

**v0.1 · early open specification · published for public review**

An open data standard for workplace health: sickness absence, return to work, occupational health, wellbeing measurement and benefit provision, defined once, in plain language and machine-readable schemas, private by design, free for anyone to implement. Built first for the UK, and for the millions of businesses everywhere that will never have a data team.

> "Currently, sickness absence is tracked inconsistently, and return-to-work outcomes are rarely measured."
> UK Government, Keep Britain Working programme, announcing the Workplace Health Intelligence Unit, July 2026

OWHS is an independent, open proposal for what standardised workplace-health data should look like at the level of an employer's records: anchored to the definitions the UK already trusts (ONS, HSE Management Standards, the statutory fit note, SSP), implementable by the smallest employer, and versioned so that when official definitions arrive they slot in rather than start over.

## What's here

| Path | Contents |
|---|---|
| `spec/` | The v0.1 specification draft: entity catalogue, per-field tables with privacy classes, profile mechanism, pseudonymisation design, conformance levels, and an honesty pass listing every disputable decision. Plus the ERD and the domain-coverage decision table. |
| `schemas/` | Executable JSON Schemas (Draft 2020-12). Version 0.1: `AbsenceEpisode`, `ReturnToWorkOutcome`, `OHEpisode`, unchanged at their unversioned paths. Version 0.2 (`schemas/v0.2/`, `schemas/catalogue.json`): the same three with an optional `ext` object keyed by profile namespace, plus `WellbeingObservation`, `InstrumentAdministration`, `MeasurementContext` and `AggregateReport`. Every object is closed; named identifier keys are refused inside extensions at any depth. Schemas cannot detect identifiers or clinical content inside permitted string values and do not implement the whole privacy profile. |
| `examples/` | A valid and a deliberately invalid instance per schema, with the validation report showing exactly which conformance errors the invalid ones raise. |
| `codelists/` | 24 independently versioned code lists (ONS absence reasons, fit-note adjustment categories, HSE-anchored construct domains, the provisional safeguarding-category list, and more) plus the registry. |
| `tools/` | The reference validator (Level 1, structural). `python tools/validate.py <schema> <instance>` |
| `site/` | The project site: plain-language pages, the instrument evidence registry (dataset v0.9.0, schema 0.7, grading rubric v1.6), the question bank, search. |
| `GOVERNANCE.md` | Stewardship, the progressive-governance model, licences, the change process. |
| `DECISIONS.md` | The public decision log, running since before release. |

## The privacy profile, in one paragraph

No direct identifiers anywhere, ever (enforced in schema). No employer-visible value below an aggregation floor of five people, ten for severe-distress measures. Individual instrument results are never employer-visible, by definition. Safeguarding-category signals are excluded from employer-visible outputs at any group size. Every aggregate carries its completion rate and suppression metadata, so consumers can see what is not being said. A conformant producer refuses to emit a violating payload rather than merely hiding it.

## Status

> **Status: early open specification.**
> OWHS was created by [Zak Fenton](https://www.linkedin.com/in/zak-fenton-a433624b/) and is currently stewarded by Alltoogether. Its specification, schemas and supporting materials are published under permissive licences and are open to inspect, use, challenge and improve. If OWHS earns independent use and recurring contribution, its governance will move to a multi-stakeholder structure so that no single commercial organisation controls its future.

Alltoogether develops commercial products that may implement OWHS. The standard does not require use of any Alltoogether product, and the project publishes its contribution, decision and change processes openly.

This is a v0.x specification, published to be improved and, where national definitions emerge, to be overwritten gracefully (a `whiu:` namespace is reserved for the Workplace Health Intelligence Unit's future definitions). See the honesty pass in `spec/`: the decisions reasonable people would dispute, the assumptions government could contradict, and the questions that need governance rather than engineering.

## Licences

Specification text and documentation: **CC-BY 4.0**. Schemas, code lists, examples and tooling: **Apache 2.0**. Anyone may implement OWHS in commercial or non-commercial products without permission, payment or notification.

## The instrument registry, and its current limit

The instrument registry is the open synthesis of the published evidence on instruments used to measure workplace health and wellbeing. For every instrument it records what it measures, how well, in which populations and languages, and on what licence terms, drawn from the literature and existing systematic reviews, every claim cited, every grade conservative. It is maintained, machine-readable and free to use, so that nobody choosing, building, licensing or reviewing a workplace measure has to reassemble the field's evidence themselves.

It grades 27 instruments, stage one of the field, across eight psychometric evidence properties in the matrix, with a ninth (populations, languages and norms) on each record, licence class verified against archived steward pages, and single-item measures linked in the data to the multi-item instruments they have been validated against. All grades were assigned by one rater employed by the steward, under the rules published as rubric v1.6 (`site/instrument-registry/RUBRIC-v1.6.md`; indirectness is defined by population type, never by country; a High grade needs two cited studies with a sample size and a statistic of the property graded). Grades and statuses are frozen from first publication until two named psychometric raters who are not steward employees have joined. AI assists retrieval, screening, extraction and drafting; it never assigns a grade, and nothing it produces reaches the dataset except through a pull request a human merges.

## Get involved

Issues and RFCs are open to anyone once this repository is public. The ask is deliberately small: find the flaw, suggest a missing field or definition, or test-map one of your existing exports and report where it breaks. You do not need to endorse the standard or join anything. Substantive contributions are reviewed in the next published maintenance cycle. Every issue template asks for a declaration of any financial or professional interest in what the contribution touches; an interest does not disqualify a contribution, an undeclared one does. The registry's most specific ask is for independent raters: see `site/contribute.html`. See `GOVERNANCE.md` for the progressive-governance model and the evidence-gated path to multi-stakeholder stewardship.

Contact: hello@openworkplacehealth.org · https://openworkplacehealth.org

---

*Stewarded by All Toogether Ltd (Alltoogether), Manchester, UK. See GOVERNANCE.md for why that's stated plainly and how governance evolves.*
