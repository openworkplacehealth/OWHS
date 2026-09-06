"""Conformance checks for the instrument registry dataset (rubric 1.5, schema 0.7).

One code path, imported by both the migration (migrate_v0.8.py) and the site
generator (build_registry_site.py, CONFORMANCE gate), so that a build that
contradicts the rubric fails instead of publishing. Every check here names the
rubric or schema rule it enforces; RUBRIC-v1.5.md section 10 carries the map
in the other direction (every rule, and whether this module checks it).
"""
from __future__ import annotations

import re

PROPS = [
    "structural_validity",
    "convergent_discriminant_validity",
    "criterion_validity_reference_standard",
    "criterion_validity_organisational",
    "internal_consistency",
    "test_retest_reliability",
    "measurement_invariance",
    "responsiveness_mic",
    "populations_languages_norms",
]
SV, CV, CR, CO, IC, TR, MI, RM, PL = PROPS
# Rubric section 6: High on these needs direct or general evidence. Criterion
# validity against a reference standard joined the list at 1.3 (the reference
# standard's base rate and the cut-off both move with the sample).
POP_SENSITIVE = {CV, CR, CO, RM, PL}
UNGRADED = {"Absent", "Not-applicable"}
FLAGS = ("direct", "general", "indirect")
ABSENCE_TYPES = ("population-general", "category-error")
POPULATION_TAGS = ("working-adults", "general", "other")
# Schema 0.7: every previous block carries eight fields; precondition_evidence is
# the archive of the High evidence a cell carried before it moved (null otherwise).
PREV_FIELDS = ["rubric_version", "grade", "status", "evidence_form", "evidence_state", "indirectness", "absence_type",
               "precondition_evidence"]

# Section 5: a `mixed` cell's findings name the second form. Generic form words
# (a translation is not a form; "version" alone is not a form) plus the named
# forms each record's literature uses.
FORM_GENERIC = re.compile(
    r"\bparent(?:-form)?\b|predecessor|derivative|short[- ]form|long[- ]form|"
    r"reduced (?:\d+-item )?(?:form|version|instrument)|\d+-item (?:reworking|version|form)|abbreviated",
    re.I,
)
FORM_TERMS = {
    "perma": r"general PERMA-Profiler",
    "mbi": r"MBI-(?:GS|HSS|ES)",
    "cbi": r"CBI-SS|PUMA",
    "olbi": r"short OLBI|15[- ]items?|short-form",
    "k10": r"\bK6\b",
    "copsoq-iii": r"COPSOQ[- ]II\b|predates COPSOQ III",
    "eurofound-ewcs": r"WHO-5",
    "csps-wellbeing": r"ONS-?4",
    "isi": r"six-item|6-item",
    "tis-6": r"TIS-4",
    "wpai": r"WPAI[:-]|disease-specific|rheumatoid arthritis|spondyloarthritis|Crohn|lupus",
}

# Section 3 precondition: `n` carries a digit; `statistic` carries a statistic OF
# THE PROPERTY GRADED with its value. Parenthetical disclaimers ("no values in
# the abstract") are removed before the test so that they cannot supply the
# digit, and instrument names that carry a digit (WHO-5, GAD-7) are removed so
# that they cannot either.
DISCLAIM_PAREN = re.compile(
    r"\((?:[^()]*?(?:no (?:values?|numeric|coefficient|numbers|AUC)|not (?:in|stated in|given in|reported in) (?:the )?abstract|not in abstract)[^()]*)\)",
    re.I,
)
# Names that carry a digit and are not a sample size or a value.
INSTRUMENT_DIGITS = re.compile(r"WHO-5|ONS-?4|K6|K10|GHQ-12|PHQ-9|PHQ-2|GAD-7|COVID-19|SF-36|SF-12|TIS-6|UWES-9|MBI-GS9?|WEMWBS-\d+|CHQ-CF87|PAID-20|PSS-10|MHC-SF|type [12] diabetes")
# The value: reach a digit without crossing a clause boundary. A period is
# allowed only when a digit follows it (a decimal), so "alpha 0.89; CFI" does
# not let the alpha's clause borrow the CFI's number. A comma is a boundary
# too (rubric 1.5), so "alpha reported, 1076 respondents" cannot pass on the
# sample size.
VALUE = r"(?:[^.;,]|\.\d)*?\d"
# Rubric 1.5 section 3: the named statistics of each property. An entry counts
# only when one of the property's own statistics is followed by a value in the
# same clause. The lists match the section 3 text token for token: the
# structural row names the scaling coefficients (Mokken, Loevinger) and the
# AGFI, NFI and NNFI indices; a person separation index counts for internal
# consistency as well as for structure; words that are not statistics
# (agreement, correspondence, predict, convergent, discriminant, divergent,
# responsiveness) are not in any list.
_FIT = r"CFI|TLI|RMSEA|SRMR|WRMR|GFI|AGFI|NFI|NNFI|chi-?squared?|chi2|χ2|loadings?|PSI|person separation|infit|outfit|Mokken|Loevinger|scalability|eigenvalues?|variance|ECV|omega hierarchical"
_IC = r"alphas?|omega|KR-?20|Kuder|composite reliability|Cronbach|McDonald|internal consistency|reliability|Spearman-Brown|split-half|PSI|person separation"
_TR = r"ICC|test-retest|retest|kappa|r|rho|correlat\w*|Pearson|Spearman|Bland|limits of agreement"
_MI = r"CFI|TLI|RMSEA|SRMR|delta|Δ|DIF|configural|metric|scalar|strict|invariance|non-?invariant"
_CV = r"r|rho|correlat\w*|Pearson|Spearman|latent correlation|AVE|HTMT"
# Criterion validity is two lists at 1.5. Against a reference standard only an
# accuracy statistic counts; against organisational outcomes a correlation or a
# regression coefficient counts as well.
_CR = (r"AUC|area under|ROC|sensitivity|specificity|kappa|OR|odds ratios?|HR|hazard ratios?|RR|relative risk|DOR|PPV|NPV|LR|"
       r"likelihood ratios?|SSLR|accuracy|c-statistic|ORC")
_CO = _CR + r"|r|rho|correlat\w*|beta|β|R-?squared|R2"
_RM = (r"effect sizes?|Cohen|d|SRM|standardi[sz]ed response mean|MIC|MCID|MID|minimal(?:ly)? (?:clinically )?important|change|"
       r"ES|Guyatt|AUC|difference")
# Populations, languages and norms is breadth: any psychometric statistic or a
# norm counts, and (rubric 1.5 section 3) at least one of the two counted
# studies carries a norm, cut-off, prevalence or explicitly reported reference
# value. NORM_RE is that second test.
_NORM = r"mean|median|average|SD|percentiles?|norm\w*|cut-?offs?|scored|prevalence|reference values?"
PROPERTY_STATISTIC = {
    SV: _FIT, IC: _IC, TR: _TR, MI: _MI, CV: _CV, CR: _CR, CO: _CO, RM: _RM,
    PL: "|".join([_FIT, _IC, _TR, _MI, _CV, _CO, _RM, _NORM]),
}
STAT_RE = {p: re.compile(r"\b(?:" + toks + r")\b" + VALUE, re.I) for p, toks in PROPERTY_STATISTIC.items()}
NORM_RE = re.compile(r"\b(?:" + _NORM + r")\b" + VALUE, re.I)
VARIANCE_PCT = re.compile(r"\d+(?:\.\d+)?\s?%\s(?:of\s)?(?:the\s)?variance", re.I)

# Section 6: every basis descriptor names who was studied (a population noun),
# carries no sample size or coefficient, no verb, and does not open with a
# preposition, article or number.
POP_NOUN = re.compile(
    r"\b(?:adults?|adolescents?|teenagers?|children|students?|workers?|employees?|staff|nurses?|physicians?|teachers?|"
    r"personnel|professionals?|patients?|participants?|respondents?|survivors?|caregivers?|carers?|cohorts?|samples?|"
    r"populations?|groups?|officers?|principals?|midwives|veterans?|citizens|members|educators?|individuals|people|"
    r"women|men|refugees|controls?|community|households?|survey|surveys|norms|norming|organisations?|company|companies|"
    r"datasets?|data|profession|leavers|cases|workforce|police|faculty|outpatients|servants|learners|practitioners|"
    r"clinicians|residents|optometrists|trials?|boys|girls|young people|older|elderly|sub-?samples?)\b",
    re.I,
)
SIZE = re.compile(r"\bn\s*=|\bN\s*=|\d{1,3},\d{3}|\b\d{3,}\b|\d\.\d")
VERB = re.compile(
    r"\b(?:correlated|gave|reported|found|established|supported|discriminated|distinguished|examined|detected|favoured|"
    r"respond|compared|converged|behaved|is used|inherits|held|showed|explained|analysed|relates|relied|described|"
    r"left|stayed|tested|derived|identified|reached|cover|span|predicted|performed|fitted|emerged|declined|improved|"
    r"comes|came|was|were|is|are|located|confirmed|achieved|yielded|produced|obtained|observed|measured|assessed|"
    r"validated|administered|fielded|recruited|drawn|sampled|surveyed|studied)\b",
    re.I,
)
LEAD = re.compile(r"^(?:(?:in|among|against|across|for|from|with|on|by|the|a|an|and|also|including|plus|during|between)\b|\d)", re.I)
# Section 6, ordering: the reason on a `direct` cell lists working-adult samples
# first. The segment before "; also" must name an occupational population.
OCCUPATIONAL = re.compile(
    r"\b(?:workers?|employees?|staff|personnel|professions?|professionals?|nurses?|nursing|physicians?|doctors?|teachers?|"
    r"academics?|officers?|working|occupational|workforce|workplaces?|companies|company|organisations?|servants|"
    r"practitioners|clinicians|faculty|police|forces|leavers|stayers|midwives|educators?|principals?|managers?|labou?r|"
    r"jobs?|employed|civil|military|firefighters?|paramedics?|trainees|apprentices|farmers|drivers|soldiers|veterans|"
    r"sectors?|industry|industries|municipality|veterinary|trades?|unions?)\b",
    re.I,
)
# Section 6: the only reasons a graded cell may carry with an empty basis.
FALLBACK_REASONS = (
    "the instrument is fielded only on working populations; the cited studies describe no further sample",
    "the instrument is fielded on general populations; the cited studies describe no further sample",
    "no sample population is described in the retrieved findings",
)
FALLBACK_RE = re.compile(r"^the cited [\w -]+ evidence describes no sample$")


def is_fallback(body: str) -> bool:
    body = body.replace("inherited from the parent record: ", "")
    return body in FALLBACK_REASONS or bool(FALLBACK_RE.match(body))


def cell_text(cell: dict) -> str:
    parts: list[str] = []
    f = cell.get("findings")
    if isinstance(f, str):
        parts.append(f)
    elif isinstance(f, list):
        for e in f:
            parts.append(" ".join(str(v) for v in e.values()))
    for k in ("summary", "confidence_note"):
        if cell.get(k):
            parts.append(cell[k])
    for sg in cell.get("subgrades") or []:
        parts.append(" ".join(str(v) for v in sg.values()))
    return " ".join(parts)


def names_second_form(rid: str, text: str) -> bool:
    return bool(FORM_GENERIC.search(text) or (rid in FORM_TERMS and re.search(FORM_TERMS[rid], text)))


def n_ok(n) -> bool:
    return bool(re.search(r"\d", DISCLAIM_PAREN.sub("", INSTRUMENT_DIGITS.sub("", str(n or "")))))


def statistic_ok(s, prop: str) -> bool:
    """Section 3: the entry names a statistic of the property graded and gives its value."""
    s = DISCLAIM_PAREN.sub("", INSTRUMENT_DIGITS.sub("", str(s or "")))
    if STAT_RE[prop].search(s):
        return True
    return prop in (SV, PL) and bool(VARIANCE_PCT.search(s))


def entry_ok(b: dict, prop: str) -> bool:
    return n_ok(b.get("n")) and statistic_ok(b.get("statistic"), prop)


def norm_ok(s) -> bool:
    """Section 3, populations: the entry names a norm, cut-off, prevalence or reference value with its value."""
    s = DISCLAIM_PAREN.sub("", INSTRUMENT_DIGITS.sub("", str(s or "")))
    return bool(NORM_RE.search(s))


def basis_problems(desc: str) -> list[str]:
    out = []
    if not POP_NOUN.search(desc):
        out.append("no population noun")
    if SIZE.search(desc):
        out.append("sample size or coefficient")
    if VERB.search(desc):
        out.append("verb")
    if LEAD.match(desc):
        out.append("opens with a preposition, article or number")
    return out


def reason_problems(reason: str) -> list[str]:
    flag = reason.split(";")[0].strip()
    body = reason.split(";", 1)[1].strip() if ";" in reason else ""
    if is_fallback(body):
        return []
    body = body.replace("inherited from the parent record: ", "")
    out = []
    if re.search(r"\d", INSTRUMENT_DIGITS.sub("", body)):
        out.append("digit in reason")
    if "(" in body or ")" in body:
        out.append("parenthesis in reason")
    if flag == "direct" and not OCCUPATIONAL.search(re.split(r";\s*also\b", body)[0]):
        out.append("direct reason does not list a working-adult sample first")
    return out


def gate(records: dict[str, dict]) -> tuple[list[str], dict]:
    """Return (problems, counts). Empty problems means the dataset conforms."""
    problems: list[str] = []
    counts = {"records": len(records), "cells": 0, "graded": 0, "high": 0, "absent": 0, "not_applicable": 0,
              "direct": 0, "general": 0, "indirect": 0, "basis_entries": 0, "fallback_cells": 0,
              "precondition_entries": 0, "mixed_cells": 0, "population_tagged_entries": 0, "previous_blocks": 0,
              "archived_precondition_entries": 0, "populations_norm_entries": 0}
    seen_findings: dict[str, set] = {}
    for rid, rec in records.items():
        for p in PROPS:
            cell = rec.get(p)
            if not isinstance(cell, dict):
                problems.append(f"{rid}.{p}: missing cell")
                continue
            counts["cells"] += 1
            if "high_basis" in cell:
                problems.append(f"{rid}.{p}: high_basis (renamed precondition_evidence at schema 0.7)")
            for k in ("grade", "status", "evidence_form", "evidence_state", "rubric_version", "as_of", "grade_last_confirmed"):
                if cell.get(k) in (None, ""):
                    problems.append(f"{rid}.{p}: missing {k}")
            # schema 0.7: every previous block carries the eight fields (null where the older version had none)
            prev = cell.get("previous")
            while isinstance(prev, dict):
                counts["previous_blocks"] += 1
                for k in PREV_FIELDS:
                    if k not in prev:
                        problems.append(f"{rid}.{p}: previous block missing {k}")
                if "high_basis" in prev:
                    problems.append(f"{rid}.{p}: previous block carries high_basis")
                pe = prev.get("precondition_evidence")
                if pe is not None:
                    counts["archived_precondition_entries"] += len(pe)
                    if prev.get("grade") != "High":
                        problems.append(f"{rid}.{p}: previous block archives precondition evidence on a grade below High")
                prev = prev.get("previous")
            # data hygiene: no findings text repeated within a record. Pointer cells
            # (inherited_from) and single-item category-error cells share one sentence by design.
            f = cell.get("findings")
            if isinstance(f, str) and not cell.get("inherited_from") and cell.get("absence_type") != "category-error":
                seen_findings.setdefault(rid, set())
                if f in seen_findings[rid]:
                    problems.append(f"{rid}.{p}: findings duplicated within the record")
                seen_findings[rid].add(f)
            text = cell_text(records[cell["inherited_from"]][p]) if cell.get("inherited_from") else cell_text(cell)
            if cell["grade"] in UNGRADED:
                counts["absent" if cell["grade"] == "Absent" else "not_applicable"] += 1
                if cell.get("absence_type") not in ABSENCE_TYPES or "indirectness" in cell or "indirectness_basis" in cell:
                    problems.append(f"{rid}.{p}: ungraded cell flag state")
                if cell["status"] != "untested":
                    problems.append(f"{rid}.{p}: ungraded cell not untested")
                if cell["grade"] == "Not-applicable" and cell.get("evidence_state") != "not_applicable":
                    problems.append(f"{rid}.{p}: Not-applicable without not_applicable state")
                if cell["grade"] == "Not-applicable" and cell.get("absence_type") != "category-error":
                    problems.append(f"{rid}.{p}: Not-applicable without category-error")
                if cell["grade"] == "Absent" and cell.get("evidence_state") != "assessed_absent":
                    problems.append(f"{rid}.{p}: Absent without assessed_absent state")
                if cell.get("precondition_evidence"):
                    problems.append(f"{rid}.{p}: precondition_evidence on an ungraded cell")
                continue
            counts["graded"] += 1
            if cell.get("absence_type"):
                problems.append(f"{rid}.{p}: absence_type on a graded cell")
            reason = cell.get("indirectness") or ""
            flag = reason.split(";")[0].strip()
            if flag not in FLAGS or "indirectness_basis" not in cell:
                problems.append(f"{rid}.{p}: flag {flag!r}")
            else:
                counts[flag] += 1
                for x in reason_problems(reason):
                    problems.append(f"{rid}.{p}: {x}: {reason!r}")
            basis = cell.get("indirectness_basis") or []
            for b in basis:
                counts["basis_entries"] += 1
                if b not in text:
                    problems.append(f"{rid}.{p}: basis {b!r} not in cell text")
                for x in basis_problems(b):
                    problems.append(f"{rid}.{p}: basis {b!r}: {x}")
            if not basis:
                counts["fallback_cells"] += 1
                body = reason.split(";", 1)[1].strip() if ";" in reason else ""
                if not is_fallback(body):
                    problems.append(f"{rid}.{p}: empty basis without the stated fallback reason")
            # section 5: evidence form vs the findings
            form = cell.get("evidence_form")
            if isinstance(cell.get("findings"), list):
                entries = cell["findings"]
                if not entries:
                    problems.append(f"{rid}.{p}: graded test-retest cell with no entries")
                forms = {e.get("evidence_form") for e in entries}
                if form == "mixed" and len(forms) < 2:
                    problems.append(f"{rid}.{p}: mixed test-retest cell whose entries carry one form")
                if form != "mixed" and forms and forms != {form}:
                    problems.append(f"{rid}.{p}: {form} test-retest cell whose entries carry {sorted(forms)}")
            if form == "mixed":
                counts["mixed_cells"] += 1
                if not names_second_form(rid, text):
                    problems.append(f"{rid}.{p}: mixed cell names no second form")
            # section 5: the parent and derivative cap (borrowed evidence never grades above Moderate)
            if form in ("parent", "derivative") and cell["grade"] == "High":
                problems.append(f"{rid}.{p}: High on borrowed evidence only (parent and derivative cap)")
            # section 3: the High precondition, and the section 6 population rule
            if cell["grade"] == "High":
                counts["high"] += 1
                pe = cell.get("precondition_evidence") or []
                counts["precondition_entries"] += len(pe)
                passing = [b for b in pe if entry_ok(b, p)]
                if len(passing) < 2:
                    problems.append(f"{rid}.{p}: High without two cited studies carrying n and a statistic of the property")
                for b in pe:
                    if b.get("citation") not in text:
                        problems.append(f"{rid}.{p}: precondition_evidence citation {b.get('citation')!r} not in findings")
                    if not entry_ok(b, p):
                        problems.append(f"{rid}.{p}: precondition_evidence entry {b.get('citation')!r} without n and a statistic of the property")
                # section 3, populations (rubric 1.5): at least one of the counted studies carries a norm,
                # cut-off, prevalence or explicitly reported reference value
                if p == PL:
                    norm_bearing = [b for b in passing if norm_ok(b.get("statistic"))]
                    counts["populations_norm_entries"] += len(norm_bearing)
                    if not norm_bearing:
                        problems.append(f"{rid}.{p}: High on populations with no counted study carrying a norm, cut-off, prevalence or reference value")
                if p in POP_SENSITIVE:
                    if flag == "indirect":
                        problems.append(f"{rid}.{p}: High on a population-sensitive property with an indirect flag")
                    tagged = [b for b in pe if b.get("population") in POPULATION_TAGS]
                    counts["population_tagged_entries"] += len(tagged)
                    if len(tagged) != len(pe):
                        problems.append(f"{rid}.{p}: precondition_evidence entry without a population tag on a population-sensitive property")
                    if not any(entry_ok(b, p) and b.get("population") in ("working-adults", "general") for b in pe):
                        problems.append(f"{rid}.{p}: High on a population-sensitive property with no working-adult or general coefficient-bearing study")
            elif cell.get("precondition_evidence"):
                problems.append(f"{rid}.{p}: precondition_evidence on a cell below High")
        # schema rules (relations): a screens-for or corresponds-with relation carries the statistic it rests on
        for rel in rec.get("relations", []) or []:
            if rel.get("type") in ("screens-for", "corresponds-with") and not re.search(r"\d", rel.get("evidence", "")):
                problems.append(f"{rid}: relation without a statistic")
            if rel.get("type") == "screens-for" and not re.search(r"sensitivity|specificity|AUC|area under", rel.get("evidence", "")):
                problems.append(f"{rid}: screens-for without an accuracy statistic")
    return problems, counts
