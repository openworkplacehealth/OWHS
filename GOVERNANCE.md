# Governance

*The Open Workplace Health Standard (OWHS) · v0.1 · updated 1 September 2026*

## Status

> **Status: early open specification.**
> OWHS was created by Zak Fenton and is currently stewarded by Alltoogether. Its specification, schemas and supporting materials are published under permissive licences and are open to inspect, use, challenge and improve. If OWHS earns independent use and recurring contribution, its governance will move to a multi-stakeholder structure so that no single commercial organisation controls its future.

## Current stewardship

OWHS is currently stewarded by **All Toogether Ltd** (trading as Alltoogether), a UK employee-benefits broker registered in Manchester (company number 14775309), which wrote the first draft of the specification and funds its maintenance.

We are explicit about this rather than hiding it: a standard has to start somewhere, and this one started inside a company that needed it and found it did not exist. Alltoogether's commercial products are separate from, and not required by, this standard. Nothing in the specification presumes any Alltoogether product, and the core specification is vendor-neutral by rule (product-specific machinery lives in named profiles, of which Alltoogether's is simply the first).

## The conflict of interest

Alltoogether develops commercial products that may implement OWHS. The standard does not require use of any Alltoogether product, and the project publishes its contribution, decision and change processes openly.

A standard stewarded by a company with products in the same field carries a real conflict, and no wording removes it. What manages it is process, in public: every change goes through a visible history; every material decision is logged with reasons; the instrument registry marks the instruments Alltoogether's own products use, so a reader checking for favourable treatment can do so at a glance; and when evidence points against something the steward's products use, the change follows the same public process as any other.

## How governance evolves

Governance here is progressive and gated on evidence, not on ceremony. Today, this project operates as a founder-stewarded open specification with the governance work done in the open: a public decision log, a public changelog, an open RFC and issue process, and this conflict-of-interest statement.

The indicative triggers for moving to a multi-stakeholder structure: two or more independent organisations mapping to or implementing OWHS; a small number of recurring external contributors; at least one independent technical, privacy or domain reviewer involved in high-impact change control; or a material decision the current steward cannot credibly make alone. Until those exist, forming a governance body would mean a committee without a community, so there is none yet. When they exist, governance moves so that no single commercial organisation, including the founding one, controls the project's future.

**The asset commitment.** If and when governance formalises, the specification's intellectual property, the project domains, the GitHub organisation and any registered trade marks in the standard's name move with it. Until then, All Toogether Ltd holds these assets and will not use them in any way inconsistent with this document. This commitment is versioned with the repository: weakening it in a future revision would be visible in the public history, and we invite anyone to hold us to that.

## Taking part

No membership, no fee, no endorsement required. The asks are deliberately small:

1. **Find the flaw**: read one defined artefact and tell us where it is wrong.
2. **Find the missing field**: suggest a definition, privacy, schema, codelist or evidence improvement.
3. **Test-map one export**: try your existing data against the standard and report where the mapping breaks. A failed mapping report is worth as much to us as a successful one.

Anyone may open an issue or respond to an RFC. Substantive contributions are reviewed in the next published maintenance cycle; the project makes no response-time promises except one: corrections of factual errors take priority over all other work. Contributors are asked to declare any financial or professional interest in instruments or products they reference, and those declarations are public.

The contributor path, if you want one: reader, reviewer, contributor, working group, and potentially a formal governance role when the structure above exists. The community earns the committee, not the reverse.

## Continuity

The licences are permissive and irrevocable. The entire corpus, specification, schemas, codelists, registry and history, can be taken and continued by anyone at any time. If stewardship fails, through neglect or bad judgement, the remedy is a fork, and that possibility is deliberate: it is the standing check on the steward. If the project enters a quiet period, it will say so: a declared maintenance-only mode in which automated evidence sweeps continue, corrections are handled, and new work pauses.

## Licences

- Specification text and documentation: **CC-BY 4.0**
- JSON Schemas, code lists, examples, validator and tooling: **Apache 2.0**

Anyone may implement the standard, in commercial or non-commercial products, without permission, payment or notification. Attribution follows the licence terms.

## Change process

- Anyone may open an issue or propose a change; no membership is required.
- Substantive changes are made by public RFC: a written proposal, an open comment window, and a recorded decision with reasons.
- Every accepted and rejected decision is recorded in the public **decision log**.
- The specification is versioned semantically. v0.x signals a specification under active revision; v1.0 will not be declared before external adopters exist and the standard has survived contact with implementers.

## Relationship to government and official definitions

This standard is designed to be **overwritten gracefully**. Where official UK definitions exist (ONS sickness-absence semantics, HSE Management Standards, the statutory fit note, SSP), the specification adopts them and cites them. Where national definitions are still forming, in particular the Workplace Health Intelligence Unit's measures for sickness absence, return-to-work outcomes and disability participation, the specification reserves namespaces and will adopt the official definitions when published, deprecating its own provisional ones. If a national standard emerges that makes part of this specification redundant, the project's position is to align with it, not to compete with it.

## Conduct

Participation in issues, RFCs and any project forum is expected to be professional and respectful. The standard concerns data about people's health; discussions are expected to reflect the care that subject deserves. The stewards may moderate accordingly.

---

*Contact: hello@openworkplacehealth.org · This document is part of the specification repository and carries its licence (CC-BY 4.0).*
