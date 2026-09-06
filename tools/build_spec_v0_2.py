#!/usr/bin/env python3
"""Compose spec/OWHS-v0.2-draft.md, the current specification source, from the v0.1 draft (narrative sections carried as the v0.1
archive states them), the sixteen v0.2 schemas (field tables generated from the executable definitions, so a table cannot say what a
schema does not), the code-list registry, and the generated validation report (the error map). The v0.1 document is not edited: it
remains the v0.1 source and archive.

    python tools/build_spec_v0_2.py           # writes spec/OWHS-v0.2-draft.md and its published copy site/spec/OWHS-v0.2-draft.md
    python tools/build_spec_v0_2.py --check   # fails if either committed file differs from a fresh composition
    python tools/build_spec_v0_2.py --self-test  # generator checks: no invented privacy class, inheritance never widens, opaque-reference controls, exact limit statements
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
UNASSIGNED = "not separately assigned; entity restrictions apply"      # a field with no explicit class has no separate disclosure permission; no default class is invented
PRIVACY_NOTE = ("An unassigned field has no separate disclosure permission. The whole record remains subject to its entity boundary and the privacy profile. An `open` metadata field does not make a linked individual record publishable. "
                "A nested field without its own class shows its nearest assigned parent's class, marked as inherited; a nested field under an unassigned parent is itself unassigned.")
PSEUDONYM_BULLET = ("- **Pseudonym shape:** WorkerPseudonym, ReasonableAdjustment and the absence, RTW and OH records require the declared `owhs:pseudo:` hexadecimal shape. The retained WellbeingObservation and InstrumentAdministration schemas accept opaque WorkerPseudonym references under their own identifier pattern. "
                    "The core validator does not resolve those references or establish how any identifier was generated. Where a supplied entity graph is checked, its worker-reference rules provide the additional join.")
P1_BULLET = ("- **Direct-identifier ban (P1):** Core schema validation checks declared property names, the documented recursive named-key restrictions in extensions, and each entity's identifier syntax. It cannot detect identifiers or sensitive meaning hidden in permitted values or aliases; a structural pass does not establish P1 compliance.")
NOT_ESTABLISHED_BULLET = ("- *What the validators do not establish:* the validators enforce their pinned inline values and the declared structural aggregation and suppression conditions. They do not establish that an external terminology is current, that the submitted counts are true, or that an output is safe to disclose. "
                          "Code-list and generator gates verify only their documented version and consistency contracts.")
HONESTY_6 = ("6. **Closed core objects.** Rejecting undeclared properties prevents extra identifier fields in the sixteen v0.2 core schemas, but cannot detect "
             "identifiers inside allowed string values. The `ext` mechanism is implemented in v0.2 (section 7): its namespace syntax, object shape and recursive "
             "named-key restrictions are checked without a profile, and an explicitly supplied profile adds its own constraints. An extension implementation must "
             "preserve the producer's P1 obligation and define its validation boundary explicitly.")
RESERVED_NOTE = "Reserved, no fields in v0.1 or v0.2"
FIGURE_CAPTION = ("*Figure, the OWHS entity map as drawn for v0.1. Version 0.2 adds no entity and removes none; the field-level references are in the section 4 tables. "
                  "White boxes are organisation-level entities; tinted boxes are individual-level records held against the pseudonym; filled boxes are the outputs that leave; "
                  "grey boxes are shared definitions; dashed outlines are reserved names.*")
# statements true of v0.1 that the carried text must not make about v0.2
NEVER_CARRIED = ("not yet implemented by the three schemas", "additionalProperties:false` everywhere", "Worked JSON Schemas", "only three", "Reserved, no fields in v0.1 |")

SECTION7_MECHANISM = ("Every core permits the generic `ext` object. Its namespace syntax, object shape and recursive named-key restrictions are checked without a profile. An explicitly supplied matching profile adds its own constraints and is reported with its version and envelope hash. "
                      "Unchecked extension namespaces are reported as having profile semantics not checked. A core pass does not establish that an omitted profile's semantics hold.")


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
        cols = None
        for line in m.group(3).splitlines():
            if line.startswith("| Field"): cols = [c.strip() for c in line.strip().strip("|").split("|")]        # the table's own header decides the column positions
            if line.startswith("| `") and cols and "Privacy" in cols:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                pi, ai = cols.index("Privacy"), cols.index("Anchor")
                if len(cells) > max(pi, ai):
                    # a combined source row (`a` / `b`) states one class for two named properties; both keep it
                    for field in [f.strip().strip("`") for f in cells[0].split("/")]:
                        if field: meta[(m.group(1), field)] = (cells[pi], cells[ai])
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
    def add(prefix, p, r, s, depth=0, parent_priv=None):
        if p == "ext": return
        code = ""
        m = re.search(r"codelist:([a-z0-9-]+@[0-9.]+)", s.get("$comment", "") or "")
        if m: code = f"codelist:{m.group(1)}"
        elif s.get("type") == "array" and isinstance(s.get("items"), dict):
            mi = re.search(r"codelist:([a-z0-9-]+@[0-9.]+)", s["items"].get("$comment", "") or "")
            if mi: code = f"codelist:{mi.group(1)}"
        explicit = meta.get((name, p)) if depth == 0 else None          # the v0.1 tables classify top-level fields of the seven carried entities; nothing else is an explicit class
        if explicit: priv, anchor = explicit
        else:
            anchor = ANCHOR_NEW.get(p, "")
            if depth and parent_priv and not parent_priv.startswith(("inherited", UNASSIGNED)): priv = f"inherited: {parent_priv} (from `{prefix.rstrip('.').rstrip('[]')}`)"
            elif depth and parent_priv and parent_priv.startswith("inherited"): priv = parent_priv
            else: priv = UNASSIGNED
        own_class = explicit[0] if explicit else priv
        if not anchor: anchor = s.get("description") or s.get("$comment") or ("OWHS v0.2 design choice" if depth == 0 else "")
        anchor = re.sub(r"^codelist:[a-z0-9-]+@[0-9.]+\s*[\u2014\u2013:-]\s*", "", anchor).replace("\u2014", ",").replace("\u2013", " to ")      # the comment's list pin is already its own column; house style has no dashes
        if name == "ReturnToWorkOutcome" and p == "sustainedAt": code = code or "codelist:rtw-sustained-status@0.1.0 (element status; the checkpoint weeks are advisory rtw-checkpoint@0.1.0)"
        if name == "BenefitUtilisation" and p == "n": anchor = ANCHOR_NEW["n"]
        rows.append(f"| `{prefix}{p}` | {type_of(s)} | {'yes' if r else 'no'} | {code} | {priv} | {anchor} |")
        if s.get("type") == "object" and "properties" in s and depth < 2:
            for q, qs in s["properties"].items(): add(f"{prefix}{p}.", q, q in set(s.get("required", [])), qs, depth + 1, own_class)
        if s.get("type") == "array" and isinstance(s.get("items"), dict) and s["items"].get("type") == "object" and "properties" in s["items"] and depth < 2:
            for q, qs in s["items"]["properties"].items(): add(f"{prefix}{p}[].", q, q in set(s["items"].get("required", [])), qs, depth + 1, own_class)
    for p, s in props.items(): add("", p, p in req, s)
    return rows


def field_tables():
    meta = v1_field_meta(); L = ["## 4. Field tables, entity by entity", "",
        "Generated from the sixteen executable v0.2 schemas: a row exists because the schema declares the field, `Req` is the schema's `required`, and a code-list column names the pinned list. Privacy classes are carried from the v0.1 tables for the fields that existed there and are not invented for any other field: a field without an explicit class reads `not separately assigned; entity restrictions apply`, and a nested field shows its nearest assigned parent's class marked as inherited. Anchors are carried from the v0.1 tables or, for fields added or redefined in v0.2, are the schema's description or the stated design choice. Nested objects are shown as `parent.child`; `ext` (the extension object keyed by profile namespace, section 7) is present on every entity and omitted from the rows.", "",
        PRIVACY_NOTE, "",
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
    s2, n2r = re.subn(r"Reserved, no fields in v0\.1 \|", RESERVED_NOTE + " |", s2)
    assert n2r == 2, "the two reserved-name rows were not found"
    s2, n2f = re.subn(r"\*Figure, the OWHS v0\.1 entity map\..*?reserved names\.\*", FIGURE_CAPTION, s2, count=1, flags=re.S)
    assert n2f == 1, "the figure caption was not found"
    s2 = s2.replace("![OWHS v0.1 entity-relationship diagram]", "![OWHS entity-relationship diagram, drawn for v0.1 and unchanged in v0.2]")
    s3 = secs["3. The privacy profile (normative)"]
    # the v0.1 bullet's account of what the schemas enforce is replaced by the v0.2 statement (sixteen executable schemas; closed cores; recursive named-key rule in extensions)
    s3, n_sub = re.subn(r"What is enforced in schema \(§2d\):.*?No schema keyword detects it\.", P1_NEW, s3, count=1, flags=re.S)
    if not n_sub: s3, n_sub = re.subn(r"In the three executable schemas, undeclared properties are rejected on the core objects\..*?The remaining entity field tables are specifications, not executable schemas\.", P1_NEW, s3, count=1, flags=re.S)
    assert n_sub == 1 and P1_NEW in s3, "the P1 enforcement sentences to replace were not found in the v0.1 text"
    s6 = ["## 6. JSON Schemas and validation", "", SECTION6_INTRO, "", "Schemas: [`schemas/v0.2/`](schemas/v0.2/) (sixteen entity types) and [`schemas/catalogue.json`](schemas/catalogue.json); the three v0.1 entry points remain at `schemas/<Entity>.json` with byte-identical archived copies under `schemas/v0.1/`. Examples: [`examples/v0.2/`](examples/v0.2/). Report: [`examples/validation_report.json`](examples/validation_report.json).", "",
          "### Privacy and boundary rules expressed in schema", "", P1_BULLET,
          PSEUDONYM_BULLET, "- **Opaque identifiers:** every new identifier field forbids whitespace explicitly and takes the shared identifier pattern.",
          "- **OH clinical-content boundary and consent gate; RTW semantic integrity:** unchanged from v0.1.", "- **Layer branches:** `BenefitEntitlement` requires the statutory object or the product category according to `layer` and forbids the other; `BenchmarkRelease` requires `excludedOrgId` exactly when `leaveOneOut` is true, applies declared sample floors of 5 (ordinary) and 10 (severe-distress) to `sampleSizes.people`, and admits no `safeguarding` release at all.",
          "- **Paired fields:** `sicCode` with `sicVersion`; `iso45003Clause` with `iso45003Edition`; `instrumentId` with `instrumentVersion`.", ""] + error_map()
    s7 = secs["7. The profile mechanism"]
    s7, n7 = re.subn(r"Core validators use `additionalProperties:false` on the top level but explicitly permit the `ext` object, whose sub-keys are only validated when the matching profile schema is loaded\. A consumer that does not understand `owhs-msk` drops `ext\.owhs-msk` and still has a conformant core record\.",
                     SECTION7_MECHANISM + " A consumer that does not understand `owhs-msk` drops `ext.owhs-msk` and still has a conformant core record.", s7, count=1)
    assert n7 == 1, "the section 7 mechanism paragraph to replace was not found"
    s8 = secs["8. Identifiers and pseudonymisation"]
    s9 = secs["9. Conformance levels"]
    # the within-record table and the P1 and not-yet-checked bullets are composed from current behaviour, not carried from v0.1
    rules_table = "\n".join(["| Rule | Entity | Statement |", "| --- | --- | --- |"] + [f"| {k} | `{v[0]}` | {v[1]} |" for k, v in RULES.items()])
    s9, n9a = re.subn(r"\| Rule \| Entity \| Statement \|\n\| --- \| --- \| --- \|\n(?:\|.*\|\n)+", rules_table + "\n", s9, count=1)
    assert n9a == 1, "the section 9 within-record table was not found"
    s9, n9b = re.subn(r"- The direct-identifier ban \(P1\) passes: .*?pattern\.\n", P1_BULLET.replace("- **Direct-identifier ban (P1):** ", "- Direct-identifier ban (P1): ") + "\n", s9, count=1, flags=re.S)
    assert n9b == 1, "the section 9 P1 bullet was not found"
    s9, n9c = re.subn(r"- \*Not yet checked:\* whether coded values are current, whether aggregates clear the floors\.", NOT_ESTABLISHED_BULLET, s9, count=1)
    assert n9c == 1, "the section 9 not-yet-checked bullet was not found"
    s9 = s9.replace("The reference validator implements Level 1 today (proven in §2d), including the format assertion and the named cross-field rules.", "The reference validator implements Level 1 today, including the format assertion and the named within-record rules C1 to C18 (section 6).")
    s9 = s9.rstrip() + "\n\n" + SECTION9_ADD + "\n\n---\n\n"
    s10 = secs["10. The honesty pass: disputable decisions and open questions"]
    # item 6 of the disputed decisions is version-bound: v0.1 said the ext mechanism was not implemented; v0.2 implements it
    s10, n10 = re.subn(r"^6\. \*\*.*?(?=\n\n7\. \*\*)", HONESTY_6, s10, count=1, flags=re.S | re.M)
    assert n10 == 1, "item 6 of the honesty pass was not found"
    src = secs["Sources (primary)"]
    body = head + "\n".join(contents) + "\n" + s1 + s2 + s3 + "\n".join(field_tables()) + "\n---\n\n" + "\n".join(codelist_table()) + "\n---\n\n" + "\n".join(s6) + "\n---\n\n" + s7 + s8 + s9 + s10 + src
    body = body.replace("\n\n\n\n", "\n\n\n")
    return body.rstrip() + "\n"


def self_test():
    """Generator checks: no privacy class is invented, inheritance never widens, the opaque-reference controls hold, the composed prose states its limits."""
    import copy, subprocess, tempfile
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else str(detail)[:300]); failures += not ok
    meta = v1_field_meta()
    # a synthetic nested field beneath an individual-never parent inherits individual-never and can never read open
    synthetic = {"properties": {"clinicalCauseCode": {"type": "object", "properties": {"leaf": {"type": "string"}, "deeper": {"type": "object", "properties": {"leaf2": {"type": "integer"}}}}}}}
    rows = rows_for("AbsenceEpisode", synthetic, meta)
    cells = {r.split("|")[1].strip().strip("`"): r.split("|")[5].strip() for r in rows}
    t("a nested field under an individual-never parent inherits individual-never, marked as inherited, never open by depth default", cells["clinicalCauseCode"] == "individual-never" and cells["clinicalCauseCode.leaf"].startswith("inherited: individual-never") and cells["clinicalCauseCode.deeper.leaf2"].startswith("inherited: individual-never") and "open" not in cells["clinicalCauseCode.leaf"], cells)
    synthetic2 = {"properties": {"brandNew": {"type": "object", "properties": {"leaf": {"type": "string"}}}, "alsoNew": {"type": "string"}}}
    cells2 = {r.split("|")[1].strip().strip("`"): r.split("|")[5].strip() for r in rows_for("BenchmarkRelease", synthetic2, meta)}
    t("unassigned fields, top-level and nested, read the unassigned statement; never blank, never implicitly open", cells2["brandNew"] == UNASSIGNED and cells2["brandNew.leaf"] == UNASSIGNED and cells2["alsoNew"] == UNASSIGNED and all(c for c in cells2.values()), cells2)
    text = compose(); sec = text[text.index("## 4. Field tables"):text.index("## 5. Code lists")]
    privs = [[c.strip() for c in ln.strip().strip("|").split("|")][4] for ln in sec.splitlines() if ln.startswith("| `")]
    v1_classes = {v[0] for v in meta.values()}                # exactly the class strings the v0.1 tables use (including qualified ones such as "open (post-floor)")
    t("no privacy cell in the composed tables is blank, and every class is a v0.1 class string, inherited from one, or the unassigned statement", all(privs) and all(p_ in v1_classes or p_ == UNASSIGNED or (p_.startswith("inherited: ") and p_.split("inherited: ", 1)[1].split(" (from")[0] in v1_classes) for p_ in privs), sorted({p_ for p_ in privs if not (p_ in v1_classes or p_ == UNASSIGNED or p_.startswith("inherited: "))}))
    explicit = {(e, f): v[0] for (e, f), v in meta.items()}
    got = {}
    ent = None
    for ln in sec.splitlines():
        m = re.match(r"^### (\w+)", ln)
        if m: ent = m.group(1)
        elif ln.startswith("| `"):
            cells_ = [c.strip() for c in ln.strip().strip("|").split("|")]; got[(ent, cells_[0].strip("`"))] = cells_[4]
    t("every explicit v0.1 class is carried unchanged into the v0.2 table", all(got.get(k) == v for k, v in explicit.items() if k in got), [(k, explicit[k], got.get(k)) for k in explicit if k in got and got[k] != explicit[k]][:5])
    t("the combined v0.1 row `periodStart` / `periodEnd` on BenefitUtilisation yields two explicit open classes, both carried", explicit.get(("BenefitUtilisation", "periodStart")) == "open" and explicit.get(("BenefitUtilisation", "periodEnd")) == "open" and got.get(("BenefitUtilisation", "periodStart")) == "open" and got.get(("BenefitUtilisation", "periodEnd")) == "open", (explicit.get(("BenefitUtilisation", "periodStart")), got.get(("BenefitUtilisation", "periodStart")), got.get(("BenefitUtilisation", "periodEnd"))))
    t("no combined-row key survives the importer", not any("/" in f for _, f in meta))
    t("the five-column BenchmarkRelease and Crosswalk tables (no code-list column) import their explicit classes from their own header", explicit.get(("BenchmarkRelease", "validFrom")) == "open" and explicit.get(("BenchmarkRelease", "validTo")) == "open" and explicit.get(("BenchmarkRelease", "benchmarkId")) == "open" and explicit.get(("Crosswalk", "constructCode")) is not None and got.get(("BenchmarkRelease", "validFrom")) == "open" and got.get(("BenchmarkRelease", "leaveOneOut")) == "open", ({k: v for k, v in explicit.items() if k[0] in ("BenchmarkRelease", "Crosswalk")}, got.get(("BenchmarkRelease", "validFrom"))))
    t("every explicit class the v0.1 tables state for a field the v0.2 schema still declares is carried (none lost to a layout difference)", all(got.get(k) == v for k, v in explicit.items() if k in got) and len([k for k in explicit if k in got]) >= 100, len([k for k in explicit if k in got]))
    t("the composed prose carries the exact pseudonym, P1, not-established and profile-mechanism statements and the privacy note", all(x in text for x in (PSEUDONYM_BULLET, P1_BULLET, NOT_ESTABLISHED_BULLET, SECTION7_MECHANISM, PRIVACY_NOTE)) and "whose sub-keys are only validated when the matching profile schema is loaded" not in text and "Not yet checked" not in text)
    t("the honesty pass states that v0.2 implements the ext mechanism, the reserved rows and figure caption name v0.2, and no v0.1-only statement is carried", HONESTY_6 in text and text.count(RESERVED_NOTE) == 2 and FIGURE_CAPTION in text and not any(x in text for x in NEVER_CARRIED), [x for x in NEVER_CARRIED if x in text])
    t("section 9 Level 1 carries the same generated C1 to C18 table as section 6", text.count("| C18 | `OrgUnit` |") == 2 and text.count("| C1 | `AbsenceEpisode` |") == 2)
    # the two opaque-reference controls: the retained observation and administration schemas accept an opaque WorkerPseudonym reference
    with tempfile.TemporaryDirectory() as tmp:
        for ent_, ex in (("WellbeingObservation", "WellbeingObservation.valid.json"), ("InstrumentAdministration", "InstrumentAdministration.valid.json")):
            inst = json.loads((ROOT / "examples" / "v0.2" / ex).read_text(encoding="utf-8")); inst["pseudonymId"] = "employee-123"
            f = Path(tmp) / ex; f.write_text(json.dumps(inst), encoding="utf-8")
            r = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "validate.py"), str(V2 / f"{ent_}.json"), str(f)], capture_output=True, text=True)
            t(f"opaque-reference control: {ent_} with pseudonymId 'employee-123' is VALID through the real validator (the retained schema's own pattern), as the pseudonym bullet states", r.returncode == 0 and "VALID" in r.stdout, (r.returncode, r.stdout[-120:], r.stderr[-120:]))
    pub = publish(text)
    t("the publication copy carries none of the excluded terms and unlinks the directory references", not any(term in pub for term in NEVER_PUBLISHED) and "](schemas/v0.2/)" not in pub and "](examples/v0.2/)" not in pub and "](codelists/)" not in pub)
    links = re.findall(r"\]\(((?!https?://|#|mailto:)[^)\s]+)\)", pub)
    missing = sorted({l for l in links if not (ROOT / "site" / "spec" / l.split("#")[0]).exists()})
    t("every relative link kept in the publication copy resolves to a file under site/spec/", not missing, missing[:8])
    print(f"{'all' if not failures else failures} specification generator checks {'passed' if not failures else 'FAILED'}")
    return 1 if failures else 0


# canonical -> publication copy for site/spec/: the same discipline as the v0.1 renderer (each rule applies exactly once; excluded
# material never survives). Directory links are unlinked because the site serves files, not directory listings.
PUBLISH_RULES = [
    ("The full table is in [`domain_routing_v0.1.csv`](codelists/domain_routing_v0.1.csv); the reasoning", "The full routing table is not included in this release; the reasoning"),
    ("The Mermaid source is [`erd.mmd`](erd.mmd)", "The Mermaid source is [`owhs_erd_v0.1.mmd`](diagrams/owhs_erd_v0.1.mmd)"),
    ("![OWHS entity-relationship diagram, drawn for v0.1 and unchanged in v0.2](../site/owhs-erd-v0.1.svg)", "![OWHS entity-relationship diagram, drawn for v0.1 and unchanged in v0.2](../owhs-erd-v0.1.svg)"),
    ("Files: [codelists/](codelists/).", "Files: every list is in the download bundle (`owhs-v0.2-bundle.zip`) under `codelists/`."),
    ("Schemas: [`schemas/v0.2/`](schemas/v0.2/) (sixteen entity types)", "Schemas: `schemas/v0.2/` (sixteen entity types, in the bundle and under this page's `schemas/` directory)"),
    ("Examples: [`examples/v0.2/`](examples/v0.2/).", "Examples: `examples/v0.2/` (in the bundle and under this page's `examples/` directory)."),
]
NEVER_PUBLISHED = ("domain_routing_v0.1.csv", "domain-coverage-decisions", "steward_product_use")


def publish(canonical_text):
    """The publication copy: refuses if a rule does not apply exactly once or excluded material would survive."""
    t = canonical_text
    for old, new in PUBLISH_RULES:
        if t.count(old) != 1: raise SystemExit(f"publication rule applies {t.count(old)} times, expected once: {old[:60]!r}")
        t = t.replace(old, new)
    for term in NEVER_PUBLISHED:
        if term in t: raise SystemExit(f"publication copy would carry excluded material: {term!r}")
    return t


def main():
    if "--self-test" in sys.argv: sys.exit(self_test())
    text = compose()
    targets = {OUT: text, SITE_OUT: publish(text)}
    if "--check" in sys.argv:
        stale = [str(p.relative_to(ROOT)) for p, t in targets.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale: sys.exit("the v0.2 specification does not match a fresh composition; run tools/build_spec_v0_2.py\n" + "".join(f"  differs: {s}\n" for s in stale))
        print("up to date: spec/OWHS-v0.2-draft.md and its publication copy site/spec/OWHS-v0.2-draft.md match their sources"); return
    for p, t in targets.items(): p.write_text(t, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} and {SITE_OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()
