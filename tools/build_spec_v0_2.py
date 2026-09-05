#!/usr/bin/env python3
"""Compose spec/OWHS-v0.2-draft.md, the current specification source, from the v0.1 draft (narrative sections carried as the v0.1
archive states them), the sixteen v0.2 schemas (field tables generated from the executable definitions, so a table cannot say what a
schema does not), the code-list registry, and the generated validation report (the error map). The v0.1 document is not edited: it
remains the v0.1 source and archive.

    python tools/build_spec_v0_2.py           # writes spec/OWHS-v0.2-draft.md and its published copy site/spec/OWHS-v0.2-draft.md
    python tools/build_spec_v0_2.py --check   # fails if either committed file differs from a fresh composition
"""
import json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "spec" / "OWHS-v0.1-draft.md"
OUT = ROOT / "spec" / "OWHS-v0.2-draft.md"
SITE_OUT = ROOT / "site" / "spec" / "OWHS-v0.2-draft.md"
V2 = ROOT / "schemas" / "v0.2"
ORDER = ["Organisation", "OrgUnit", "WorkerPseudonym", "AbsenceEpisode", "ReturnToWorkOutcome", "OHEpisode", "ReasonableAdjustment", "WellbeingObservation", "InstrumentAdministration", "MeasurementContext",
         "BenefitEntitlement", "BenefitUtilisation", "DisabilityParticipation", "AggregateReport", "BenchmarkRelease", "Crosswalk"]
NEW = {"Organisation", "OrgUnit", "WorkerPseudonym", "ReasonableAdjustment", "BenefitEntitlement", "BenefitUtilisation", "DisabilityParticipation", "BenchmarkRelease", "Crosswalk"}
RULES = {"C1": ("AbsenceEpisode", "endDate not before startDate"), "C2": ("OHEpisode", "assessmentDate not before referralDate"), "C3": ("AggregateReport", "periodEnd not before periodStart"),
         "C4": ("MeasurementContext", "observationWindow ordered as UTC instants"), "C5": ("MeasurementContext", "nativeScale min below max"), "C6": ("AggregateReport", "interval low not above high"),
         "C7": ("AggregateReport", "n <= eligibleN <= headcount"), "C8": ("AggregateReport", "observationCount not below n"), "C9": ("AggregateReport", "completionRate is n/eligibleN, null only when eligibleN is 0"),
         "C10": ("ReasonableAdjustment", "if both dates exist, endDate >= startDate"), "C11": ("BenefitUtilisation", "periodEnd >= periodStart"), "C12": ("DisabilityParticipation", "periodEnd >= periodStart"),
         "C13": ("BenchmarkRelease", "validTo >= validFrom"), "C14": ("BenchmarkRelease", "dataPeriodEnd >= dataPeriodStart"),
         "C15": ("BenefitUtilisation", "n <= usageCount + claimCount (an absent claimCount contributes no recorded events); n = 0 requires both recorded event counts to be zero. Repeated events may exceed n. Declarations are compared; people are not deduplicated"),
         "C16": ("BenchmarkRelease", "composition.orgCount <= sampleSizes.people; observations, when supplied, >= people. Contributing organisations and people, not invited but non-contributing units"),
         "C17": ("BenchmarkRelease", "percentile probabilities strictly increase in array order and values never decrease; tied values and a single quantile are valid, duplicate probabilities are not; no quantile algorithm or sampling distribution is verified"),
         "C18": ("OrgUnit", "parentUnitId, if supplied, differs from unitId; the direct self-loop only")}
OPENING = ("Version 0.2 provides executable Draft 2020-12 schemas for sixteen entity types. The validation report records the schema version and the expected and observed errors for each example. "
           "The reference validator checks the declared structure, asserted formats, generic extensions, explicitly supplied profiles and named within-record rules. The measurement-bundle checker adds its "
           "documented supplied-context joins. These checks do not establish full Level 2 or Level 3 conformance, external terminology resolution, lawful processing, safe disclosure or scientific validity. "
           "The separate entity-graph envelope and G01-G10 relationship checks are documented in the supplied-entity graph guide (docs/entity-graph-validation-v0.2.md).")
SECTION6_INTRO = ("Each of the sixteen entity types in the v0.2 catalogue has an executable schema and passing and failing examples. The generated validation report identifies each entity and schema version and records "
                  "its observed errors. C1-C18 are documented within-record checks implemented by the reference validator; they are not all JSON Schema keywords. ConstructDomain remains a code list. RiskAssessment and "
                  "WorkplaceIncident remain reserved without executable schemas. DisabilityParticipation is an executable reserved-minimal shape with the stated disclosure limitations. "
                  "The separate entity-graph envelope and G01-G10 relationship checks are documented in the supplied-entity graph guide (docs/entity-graph-validation-v0.2.md).")
P1_NEW = ("All sixteen v0.2 entity types have executable schemas. Closed core objects reject undeclared property names, while extension objects apply the documented recursive named-key restriction. "
          "These rules cannot detect identifiers or sensitive meaning hidden in permitted values or aliases. Metadata is not automatically non-personal, and a structural pass is not a privacy-profile assessment.")
SECTION9_ADD = ("The measurement-bundle checker retains its documented context checks. The optional entity-graph checker additionally validates the declared organisation-scoped references, identity uniqueness, "
                "unit hierarchy and named benchmark-reference rules in a supplied bundle. Each report lists its exercised checks, unresolved external references and interpretation limits. These checks do not "
                "establish a complete dataset, the truth of submitted provenance or counts, benchmark comparability, safe disclosure or full Level 2 or Level 3 conformance.")
GRAPH_SENTENCE = "The separate entity-graph envelope and G01-G10 relationship checks are documented in the supplied-entity graph guide (docs/entity-graph-validation-v0.2.md)."
CODELIST_LIMITS = ("These schemas retain UK SIC 2007 explicitly as an edition. ONS also publishes SIC 2026; codes from different editions must not be mixed or relabelled without an explicit mapping. Country, SIC, currency, "
                   "ISO clause and reserved WHIU strings are checked only to the stated syntactic extent. They are not resolved against live external registers. The existing headcount bands have no zero/unknown category, "
                   "and the existing tenure labels do not by themselves settle the shared ten-year boundary. No producer should infer an absent category or boundary rule from a structural pass.")
AFTER_TABLE = {
 "BenefitUtilisation": ("BenefitUtilisation is a producer-held aggregate input. Its event counts may exceed the number of people because a person may use a service repeatedly. Values below a reporting floor may be recorded "
                        "internally. This entity does not by itself establish permission to disclose counts, service attendance or claims; employer-visible numerical results must use AggregateReport and satisfy the privacy "
                        "profile. No individual claim record is permitted."),
 "DisabilityParticipation": ("The executable schema validates this reserved-minimal record's structure and reporting dates. It does not contain a respondent denominator or suppression metadata and cannot verify the n>=10 "
                             "disclosure requirement. A valid instance is not an employer-output or benchmark-release approval. Missing, zero and non-disclosure must not be recoded into an existing positive headcount band. "
                             "Publication requires a governed measure definition and a release mechanism that can establish the applicable privacy conditions; neither is supplied by this placeholder."),
 "BenchmarkRelease": ("A benchmark release identifies one metric, scoring rule, population and data period. Its sample sizes, composition, exclusion and quantiles are producer declarations. The validator checks their stated "
                      "structure and internal consistency; it does not reconstruct the data, verify who was excluded, establish representativeness, validate clinical cut-points or prove that a recipient's measure is comparable. "
                      "A leave-one-out release names the excluded organisation. Sharing a metric identifier or a numeric range does not establish measurement equivalence. Disclosure review, including composition and "
                      "repeated-release risks, remains necessary."),
 "ReasonableAdjustment": "Omit `endDate` when no end date is recorded; null is not a date. An omitted end date does not by itself show that the adjustment is in place; `status` is the separate record of that.",
}
# anchors for fields the v0.2 schemas add or redefine; every other anchor is carried from the v0.1 table for the same field
ANCHOR_NEW = {"sizeBandReferenceDate": "OWHS v0.2 design choice: the date the band relates to", "sicVersion": "UK SIC 2007 retained as an edition; ONS also publishes SIC 2026", "headcountReferenceDate": "OWHS v0.2 design choice",
              "periodStart": "OWHS v0.2 design choice: inclusive reporting dates", "periodEnd": "OWHS v0.2 design choice: inclusive reporting dates", "releaseVersion": "OWHS v0.2 design choice", "dataPeriodStart": "OWHS v0.2 design choice",
              "dataPeriodEnd": "OWHS v0.2 design choice", "measure": "OWHS v0.2 design choice: one metric and scoring rule per release", "population": "OWHS v0.2 design choice", "samplingMethod": "OWHS v0.2 design choice",
              "knownLimitations": "OWHS v0.2 design choice", "releaseCategory": "OWHS P2/P4 declared category", "excludedOrgId": "OWHS v0.2 design choice: required iff leaveOneOut", "sourceRef": "OWHS v0.2 design choice",
              "iso45003Edition": "ISO 45003 edition being mapped; ISO text is referenced, not reproduced", "statutory": "closed statutory-term object; dated and sourced; no rate or eligibility is computed",
              "n": "distinct people represented across the recorded service-use and claim events in this period; not the whole eligible workforce and not automatically the denominator for either event category separately; a released metric requires its own distinct-person count and completion metadata in AggregateReport"}
PRIVACY_NEW = {"statutory": "open", "sizeBandReferenceDate": "open", "sicVersion": "open", "headcountReferenceDate": "open", "periodStart": "open", "periodEnd": "open", "releaseVersion": "open", "dataPeriodStart": "open",
               "dataPeriodEnd": "open", "measure": "open", "population": "open", "samplingMethod": "open", "knownLimitations": "open", "releaseCategory": "open", "excludedOrgId": "open", "sourceRef": "open", "iso45003Edition": "open", "orgId": "open"}


def v1_sections():
    """{heading: text} for the v0.1 draft's top-level sections, in order, plus the whole text."""
    text = V1.read_text(encoding="utf-8")
    parts = re.split(r"^(?=## )", text, flags=re.M)
    out = {}
    for p in parts:
        m = re.match(r"## (.+)", p)
        if m: out[m.group(1).strip()] = p
    return out, text


def v1_field_meta():
    """(entity, field) -> (privacy, anchor) from the v0.1 tables."""
    text = V1.read_text(encoding="utf-8"); sec = text[text.index("## 4. Field tables"):text.index("## 5. Code lists")]
    meta = {}
    for m in re.finditer(r"^### (\w+)(.*?)\n(.*?)(?=^### |\Z)", sec, re.M | re.S):
        for line in m.group(3).splitlines():
            if line.startswith("| `"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 6: meta[(m.group(1), cells[0].strip("`"))] = (cells[4], cells[5])
    return meta


def type_of(s):
    if "const" in s: return f"const `{s['const']}`"
    if "enum" in s: return "string (code)"
    t = s.get("type")
    if isinstance(t, list): t = "/".join(t)
    if t == "string" and s.get("format"): return s["format"]
    if t == "string" and "pattern" in s: return "string (pattern)"
    if t == "array": return "array of " + type_of(s["items"]).replace(" (code)", " codes").replace("string (pattern)", "patterned strings")
    return t or "object"


def rows_for(name, schema, meta):
    props, req = schema["properties"], set(schema.get("required", []))
    rows = []
    def add(prefix, p, r, s, depth=0):
        if p == "ext": return
        code = ""
        m = re.search(r"codelist:([a-z0-9-]+@[0-9.]+)", s.get("$comment", "") or "")
        if m: code = f"codelist:{m.group(1)}"
        elif s.get("type") == "array" and isinstance(s.get("items"), dict):
            mi = re.search(r"codelist:([a-z0-9-]+@[0-9.]+)", s["items"].get("$comment", "") or "")
            if mi: code = f"codelist:{mi.group(1)}"
        priv, anchor = meta.get((name, p), (PRIVACY_NEW.get(p, "open" if depth else ""), ANCHOR_NEW.get(p, "")))
        if depth and not priv: priv = "as parent"
        if not anchor: anchor = s.get("description") or s.get("$comment") or ("OWHS v0.2 design choice" if depth == 0 else "")
        anchor = re.sub(r"^codelist:[a-z0-9-]+@[0-9.]+\s*[\u2014\u2013:-]\s*", "", anchor).replace("\u2014", ",").replace("\u2013", " to ")      # the comment's list pin is already its own column; house style has no dashes
        if name == "ReturnToWorkOutcome" and p == "sustainedAt": code = code or "codelist:rtw-sustained-status@0.1.0 (element status; the checkpoint weeks are advisory rtw-checkpoint@0.1.0)"
        if name == "BenefitUtilisation" and p == "n": anchor = ANCHOR_NEW["n"]
        rows.append(f"| `{prefix}{p}` | {type_of(s)} | {'yes' if r else 'no'} | {code} | {priv} | {anchor} |")
        if s.get("type") == "object" and "properties" in s and depth < 2:
            for q, qs in s["properties"].items(): add(f"{prefix}{p}.", q, q in set(s.get("required", [])), qs, depth + 1)
        if s.get("type") == "array" and isinstance(s.get("items"), dict) and s["items"].get("type") == "object" and "properties" in s["items"] and depth < 2:
            for q, qs in s["items"]["properties"].items(): add(f"{prefix}{p}[].", q, q in set(s["items"].get("required", [])), qs, depth + 1)
    for p, s in props.items(): add("", p, p in req, s)
    return rows


def field_tables():
    meta = v1_field_meta(); L = ["## 4. Field tables, entity by entity", "",
        "Generated from the sixteen executable v0.2 schemas: a row exists because the schema declares the field, `Req` is the schema's `required`, and a code-list column names the pinned list. Privacy classes and anchors are carried from the v0.1 tables for fields that existed there; fields added or redefined in v0.2 carry the schema's description or the stated design choice. Nested objects are shown as `parent.child`; `ext` (the extension object keyed by profile namespace, section 7) is present on every entity and omitted from the rows.", "",
        "**Privacy classification (four classes).** `open` = may appear in any output; `aggregate-only` = employer-visible only through an `AggregateReport` clearing the n-floor; `individual-never` = never leaves the producer at individual grain in any output, even to the employer; `individual-employer` = may be held or shown about an identified pseudonym to the employer only where an independent legal basis entitles them. A class is a field-level obligation on the producer; the schema does not enforce it.", ""]
    for n in ORDER:
        s = json.loads((V2 / f"{n}.json").read_text(encoding="utf-8"))
        tag = " (new in v0.2)" if n in NEW else ""
        L += [f"### {n}{tag}", "", s.get("description", ""), "", "| Field | Type | Req | Code list | Privacy | Anchor or description |", "|---|---|---|---|---|---|"] + rows_for(n, s, meta)
        if n in ("BenefitEntitlement",): L += ["", "A `statutory` layer requires the closed `statutory` object and forbids `productCategory`; a `commercial` layer requires `productCategory` and forbids `statutory`. Within `statutory`, `waitingDays`, `rate` and `durationWeeks` are optional: absence of a term is not zero, and a supplied fixed amount is not proof of legal entitlement."]
        if n in ("Organisation",): L += ["", "`sicCode` and `sicVersion` require one another; the only permitted version is `2007`, retained as an edition (section 5)."]
        if n in ("Crosswalk",): L += ["", "At least one of `hseDomain`, `iso45003Clause` and `whiuCode` is required; `iso45003Clause` and `iso45003Edition` require one another. Clause syntax is not clause existence or mapping validity; WHIU syntax is not resolved terminology."]
        if n in ("WorkerPseudonym",): L += ["", "The five forbidden root identifier names (`name`, `nino`, `email`, `dateOfBirth`, `address`) fail the closed root; inside `ext` they fail the recursive named-key rule (section 7). No raw age, birth date, tenure number or person name is carried."]
        if n in AFTER_TABLE: L += ["", AFTER_TABLE[n]]
        L.append("")
    return L


def codelist_table():
    reg = json.loads((ROOT / "codelists" / "_registry.json").read_text(encoding="utf-8"))
    L = ["## 5. Code lists", "", f"Every list is a standalone JSON file with its own `version` (semver), independent of the spec version, registered in [`_registry.json`](codelists/_registry.json). Schemas pin a list as `name@version`. The registry holds {len(reg['lists'])} lists; archived versions live under `codelists/archive/` and are never edited. Files: [codelists/](codelists/).", "",
         "| List | Ver | Values | Anchor |", "|---|---|---|---|"]
    for e in sorted(reg["lists"], key=lambda e: e["name"]): L.append(f"| `{e['name']}` | {e['version']} | {e['values']} | {e['anchor']} |")
    L += ["", CODELIST_LIMITS, ""]
    return L


def error_map():
    rep = json.loads((ROOT / "examples" / "validation_report.json").read_text(encoding="utf-8"))["results_v0_2"]
    L = ["### Error map (generated from the validation report)", "", "Every committed v0.2 example, with the errors the reference validator raised on it. A valid example raises none; an invalid one raises exactly the keywords or named rules listed. A `[profile]` note (an extension namespace whose profile semantics were not checked) is not an error and is not counted. The map is generated from `examples/validation_report.json`, so it cannot drift from the run.", "",
         "| Entity | Example | Expected | Errors raised |", "|---|---|---|---|"]
    for ent in ORDER:
        for label, c in rep.get(ent, {}).items():
            tags = [l[1:l.index("]")] for l in c["errors"] if not l.startswith("[profile]")]      # a [profile] line is a note that an extension's semantics were not checked, not an error
            L.append(f"| `{ent}` | `{label}` | {c['expected']} | {', '.join(f'`{t}`' for t in tags) if tags else 'none'} ({len(tags)}) |")
    L += ["", "### Named within-record rules", "", "| Rule | Entity | Predicate |", "|---|---|---|"] + [f"| {k} | `{v[0]}` | {v[1]} |" for k, v in RULES.items()]
    L += ["", "Rules run only after the entity's structural operands are valid; a malformed date is the format check's finding, and a negative count the schema's. Malformed inputs yield named validation or tool errors, never a traceback. Cross-record joins (organisation hierarchies beyond the direct self-loop, references to other entities, benchmark applicability) are not within-record rules and are outside this validator; the optional entity-graph checker covers them on a supplied bundle (G01-G10, docs/entity-graph-validation-v0.2.md).", ""]
    return L


def compose():
    secs, text = v1_sections()
    head = text[:text.index("## Contents")]
    head = head.replace("OWHS-v0.1", "OWHS-v0.2").replace("v0.1 draft", "v0.2 draft").replace("Version 0.1", "Version 0.2")
    head = re.sub(r"^# .*$", "# Open Workplace Health Standard (OWHS) v0.2, draft specification", head, count=1, flags=re.M)
    head = re.sub(r"\*\*What is machine-checked in this draft\.\*\*.*?(?=\n\n)", "**What is machine-checked in this draft.** " + OPENING, head, count=1, flags=re.S)
    contents = ["## Contents", "", "1. Scope and domain coverage (carried from v0.1)", "2. Entity catalogue", "3. The privacy profile (normative)", "4. Field tables, entity by entity (generated from the schemas)", "5. Code lists", "6. JSON Schemas and validation", "7. The profile mechanism", "8. Identifiers and pseudonymisation", "9. Conformance levels", "10. The honesty pass", "Sources", ""]
    s1 = secs["1. Scope and domain coverage"]
    s2 = secs["2. Entity catalogue"].replace("Sixteen entities in five clusters, plus two reserved names and one code-list-backed shared entity.", "Sixteen entities in five clusters, plus two reserved names and one code-list-backed shared entity; in v0.2 every one of the sixteen has an executable schema (section 6).")
    s3 = secs["3. The privacy profile (normative)"]
    # the v0.1 bullet's account of what the schemas enforce is replaced by the v0.2 statement (sixteen executable schemas; closed cores; recursive named-key rule in extensions)
    s3, n_sub = re.subn(r"What is enforced in schema \(§2d\):.*?No schema keyword detects it\.", P1_NEW, s3, count=1, flags=re.S)
    if not n_sub: s3, n_sub = re.subn(r"In the three executable schemas, undeclared properties are rejected on the core objects\..*?The remaining entity field tables are specifications, not executable schemas\.", P1_NEW, s3, count=1, flags=re.S)
    assert n_sub == 1 and P1_NEW in s3, "the P1 enforcement sentences to replace were not found in the v0.1 text"
    s6 = ["## 6. JSON Schemas and validation", "", SECTION6_INTRO, "", "Schemas: [`schemas/v0.2/`](schemas/v0.2/) (sixteen entity types) and [`schemas/catalogue.json`](schemas/catalogue.json); the three v0.1 entry points remain at `schemas/<Entity>.json` with byte-identical archived copies under `schemas/v0.1/`. Examples: [`examples/v0.2/`](examples/v0.2/). Report: [`examples/validation_report.json`](examples/validation_report.json).", "",
          "### Privacy and boundary rules expressed in schema", "", "- **Direct-identifier ban (P1):** `additionalProperties:false` on every entity and nested object rejects `name`, `nino`, `email`, `dateOfBirth`, `address` and every other undeclared property at the root; inside `ext`, the named identifier keys (and, for `OHEpisode`, its named clinical-content keys) are refused at every depth by the extension object's property-name rule. This is a key-based check: an identifier written into a permitted string value is not detected.",
          "- **Pseudonym shape:** `pseudonymId` must match `^owhs:pseudo:[0-9a-f]{16,64}$` on `WorkerPseudonym`, `ReasonableAdjustment` and the measurement and absence entities that carry it; a raw employee reference is a schema error.", "- **Opaque identifiers:** every new identifier field forbids whitespace explicitly and takes the shared identifier pattern.",
          "- **OH clinical-content boundary and consent gate; RTW semantic integrity:** unchanged from v0.1.", "- **Layer branches:** `BenefitEntitlement` requires the statutory object or the product category according to `layer` and forbids the other; `BenchmarkRelease` requires `excludedOrgId` exactly when `leaveOneOut` is true, applies declared sample floors of 5 (ordinary) and 10 (severe-distress) to `sampleSizes.people`, and admits no `safeguarding` release at all.",
          "- **Paired fields:** `sicCode` with `sicVersion`; `iso45003Clause` with `iso45003Edition`; `instrumentId` with `instrumentVersion`.", ""] + error_map()
    s7 = secs["7. The profile mechanism"]
    s8 = secs["8. Identifiers and pseudonymisation"]
    s9 = secs["9. Conformance levels"].rstrip() + "\n\n" + SECTION9_ADD + "\n\n---\n\n"
    s10 = secs["10. The honesty pass: disputable decisions and open questions"]
    src = secs["Sources (primary)"]
    body = head + "\n".join(contents) + "\n" + s1 + s2 + s3 + "\n".join(field_tables()) + "\n---\n\n" + "\n".join(codelist_table()) + "\n---\n\n" + "\n".join(s6) + "\n---\n\n" + s7 + s8 + s9 + s10 + src
    body = body.replace("\n\n\n\n", "\n\n\n")
    return body.rstrip() + "\n"


def main():
    text = compose()
    targets = {OUT: text, SITE_OUT: text}
    if "--check" in sys.argv:
        stale = [str(p.relative_to(ROOT)) for p, t in targets.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale: sys.exit("the v0.2 specification does not match a fresh composition; run tools/build_spec_v0_2.py\n" + "".join(f"  differs: {s}\n" for s in stale))
        print("up to date: spec/OWHS-v0.2-draft.md and site/spec/OWHS-v0.2-draft.md match their sources"); return
    for p, t in targets.items(): p.write_text(t, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} and {SITE_OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()
