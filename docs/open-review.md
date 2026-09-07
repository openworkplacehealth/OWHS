# Open questions and corrections
<!-- meta: public review · list checked 7 September 2026 -->
<!-- description: Help review OWHS: open questions about the specification, registry evidence needing re-examination, published corrections and ways to contribute. -->

OWHS is open to correction. This page brings together questions where evidence or practical experience would help, concerns about how evidence has been interpreted, and the record of changes already made.

You can contribute a source, a counterexample or an implementation experience. You do not need to review the whole project to make a useful contribution.

[Questions about the standard](#questions) · [Evidence needing review](#evidence) · [Published corrections](#corrections) · [Contribute](#contribute)

The list below was checked on **7 September 2026**. Follow each source for subsequent comments and decisions. An open question is not a confirmed error. This page lists selected public questions; the [methods and limitations](methods.html) and the [specification's open questions](spec/#the-honesty-pass-disputable-decisions-and-open-questions) provide further context.

<h2 id="questions">Questions about the standard</h2>

<h3 id="construct-domains">Which constructs should the vocabulary include?</h3>

**RFC 0001: proposal open for comment.** Comment window: 7 September to 17 October 2026. Decision not yet taken at the date checked.

The proposal concerns the construct-domain code list, its safeguarding and visibility fields, and its mapping to question-bank topic groups. Input is particularly useful on whether proposed constructs are sufficiently distinct, what has been omitted, and where a visibility default belongs.

[Read RFC 0001](https://github.com/openworkplacehealth/OWHS/blob/main/rfcs/0001-construct-domain-v0.2.md) · [Join the existing discussion, #24](https://github.com/openworkplacehealth/OWHS/issues/24)

<h3 id="identifiable-subjects">What if an aggregate describes an identifiable manager?</h3>

**RFC 0002: proposal open for comment.** Comment window: 7 September to 17 October 2026. Decision not yet taken at the date checked.

The proposal asks how to handle outputs that describe a person other than the respondent, including team ratings of a manager. It seeks critique of the proposed protections, practical examples, and relevant data-protection and employment-law analysis. The proposed subject-count rule remains a proposal, not a demonstrated privacy guarantee. This decision must precede admission of subject-identifying codes under RFC 0001.

[Read RFC 0002](https://github.com/openworkplacehealth/OWHS/blob/main/rfcs/0002-subject-identifying-constructs.md) · [Join the existing discussion, #25](https://github.com/openworkplacehealth/OWHS/issues/25)

<h3 id="score-comparability">What should a normalised score communicate?</h3>

**Open discussion, #16.** Affects the representation and interpretation of normalised instrument scores. The thread asks what role the field should have and what evidence a comparison needs. Useful input includes scoring examples, limitations of rescaling and proposed alternatives. Earlier wording in the thread may predate the current specification.

[Read and contribute to #16](https://github.com/openworkplacehealth/OWHS/issues/16)

<h3 id="disclosure-authority">How should authority to disclose an occupational-health opinion be recorded?</h3>

**Open discussion, #17.** Affects the occupational-health episode model. The thread asks how authorisation, the basis for disclosure and the time of release should be represented. Useful input includes synthetic workflow examples and relevant legal or professional sources. Earlier wording in the thread may predate the current specification.

[Read and contribute to #17](https://github.com/openworkplacehealth/OWHS/issues/17)

<h3 id="overlapping-reports">How should overlapping and repeated reports be handled?</h3>

**Open discussion, #18.** Affects aggregate reporting and the privacy profile. The thread asks what additional rules are needed for reports whose groups or reporting periods overlap. Useful input includes synthetic counterexamples, disclosure-control methods and practical implementation constraints. The latest checked comment describes the question as substantively open despite prose changes.

[Read and contribute to #18](https://github.com/openworkplacehealth/OWHS/issues/18)

<h2 id="evidence">Evidence needing review</h2>

<h3 id="isi-reference-standard">ISI: reference-standard evidence</h3>

**Re-adjudication requested, #33.** Affects the ISI record's criterion-validity property for a reference standard in registry v0.9.0.

The public notice questions the basis of the displayed grade. It asks reviewers to separate each study's sample, comparator, threshold and accuracy estimates, inspect the supporting full texts, and assess whether the published rubric's conditions are met. The notice links the original study and relevant pages. It does not announce a replacement grade or a recommendation to use the instrument.

[Read the notice and contribute to #33](https://github.com/openworkplacehealth/OWHS/issues/33) · [Inspect the ISI record](instrument-registry/isi.html)

<h3 id="organisational-evidence">WAS and TIS-6: organisational criterion validity</h3>

**Listed for re-examination in the current methods.** The methods page names these two cells. A review can help establish what the cited studies actually support for the stated organisational outcomes and populations. Please identify the record, property and source passage in any response.

[Read the methods statement](methods.html) · [Submit evidence or a correction](https://github.com/openworkplacehealth/OWHS/issues/new?template=4-registry-correction.yml)

**Independent psychometric review is still needed.** Registry grades and statuses remain frozen under the [published review policy](instrument-registry/how-to-read.html#raters). Researchers interested in independent rating can [contact the registry](mailto:hello@openworkplacehealth.org?subject=Independent%20psychometric%20review), describing their relevant experience and any interests. Reviewing a record does not by itself appoint a rater or lift the freeze.

<h2 id="corrections">Published corrections</h2>

The [registry correction record](instrument-registry/corrections.html) publishes numbered corrections with the previous and replacement values, evidence and notes. It also provides the sections for errata and rights of reply. The [changelog](changelog.html) records changes to the specification, registry and site.

These records have different purposes. A concern awaiting examination is not a published correction. A correction to one field does not establish that the rest of an instrument record has been independently verified.

<h2 id="contribute">Contribute a bounded piece of evidence</h2>

For a scientific concern, provide the instrument record and property, the exact statement being challenged, a primary source with a section or page, and the change or uncertainty you think follows. For an implementation problem, provide a synthetic example, the relevant specification or schema version, and what happened.

- [Submit a registry correction or evidence challenge](https://github.com/openworkplacehealth/OWHS/issues/new?template=4-registry-correction.yml).
- [Report a schema, code-list or definition problem](https://github.com/openworkplacehealth/OWHS/issues/new?template=2-schema-codelist-definition-suggestion.yml).
- [Share an implementation or mapping report](https://github.com/openworkplacehealth/OWHS/issues/new?template=3-implementation-mapping-report.yml).
- [Email a contribution](mailto:hello@openworkplacehealth.org?subject=OWHS%20public%20review) if you do not use GitHub. Include the relevant question or record and whether you consent to being named.

Declare relevant financial or professional interests. GitHub issues and comments are public under your account. Do not include real employee or patient data. If a concern could enable disclosure or exploitation, [email it privately first](mailto:hello@openworkplacehealth.org?subject=Private%20privacy%20or%20safeguarding%20concern).

The [contribution guide](contribute.html) and [governance page](governance.html) explain how contributions and decisions are handled. Factual corrections take priority; no response deadline is promised. A closed discussion is not by itself evidence that the scientific or implementation question has been resolved.
