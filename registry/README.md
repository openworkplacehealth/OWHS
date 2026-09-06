# Instrument evidence registry: source of truth

This folder holds what the pages under `site/instrument-registry/` are generated from. Edit here, never
the HTML.

| File | What it is |
|---|---|
| `instrument-evidence-base-v0.9.0.json` | The current dataset: 31 records (27 instruments, four ONS item records), 279 property cells, citations, licence positions, corrections log. Every earlier version is kept beside it at a stable name for citation; superseded versions are left as published. |
| `RUBRIC-v1.6.md`, earlier rubrics | The grading rules the current dataset was graded under, and every earlier version, left as published. |
| `ADMISSION-v1.1.md`, `ADMISSION-v1.0.md` | How an instrument enters the registry. |
| `registry_gate.py` | The conformance gate: the structural and rule-precondition checks rubric section 10 enumerates. The build refuses to run if the dataset breaks one. |
| `build_registry_site.py` | The generator. Reads the current dataset, the rubric, the admission policy and `site/question-bank/question-bank.json`; writes every page, the JSON and CSV downloads and the PDF into `site/instrument-registry/`. |

## Build

```
pip install -r requirements.txt
python registry/build_registry_site.py      # gate, then 38 pages plus JSON, CSV and PDF
python tools/stamp_canonical.py             # canonical links, robots posture, footer line, visit counting
```

Generated HTML initially carries a noindex setting; the stamping step applies the one word in `robots-policy.txt`
to every page before deployment, so a rebuild followed by stamping cannot change whether the site is indexed.

## Check

```
python registry/build_registry_site.py --check
```

Rebuilds into a temporary copy of `site/`, stamps it, and fails if any generated file differs from the
committed one, or if a committed file is not produced by the build. The PDF is excluded: its bytes carry the
build date, so PDF reproducibility is not verified. The CI workflow runs this on every push and pull request
and reports a failure when the pages do not match their source.

## What the build refuses

The gate checks the enumerated structural and rule-precondition checks in rubric section 10. It does not assess study quality, extraction accuracy or whether a grade is scientifically justified. The build also fails if any
output page orders instruments on a grade, carries a composite score, contains an em or en dash outside
verbatim citation titles, or contains internal working terms. The steward runs an additional local word
list against product and vendor names before publishing (`OWHS_NEUTRALITY_TERMS`, a file of one
regular expression per line, kept outside this repository).

## Grades are frozen

From first publication until two named psychometric raters who are not employees of the steward have
rated independently, no grade or status changes except through a numbered correction entry in the
dataset's corrections log. The generator and the gate enforce shape, never judgement.

## Not yet in this folder

The migration scripts that produced each dataset version from the one before are being prepared for
publication. Their comments are being reviewed so that the published copies describe the changes
without internal working notes.

## Dataset files are public projections

The dataset files here from v0.3.0 onward are public projections (projection 1.0) of the released scientific versions: each carries a `public_projection` block stating that private stewardship metadata (one record-level field, null in every released version, and the policy object describing it) is omitted and that one historical changelog clause naming it carries a neutral marker; scientific identity, citations, evidence and property blocks are unchanged, and the dataset version numbers are the scientific versions. v0.1 to v0.2.2 never carried the field and are unchanged.
