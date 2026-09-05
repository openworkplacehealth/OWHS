#!/usr/bin/env python3
"""Write the v0.2 schemas: the three v0.1 entities with the extension mechanism, and four measurement entities.

The v0.1 schemas are not touched: the unversioned files under schemas/ remain the v0.1 entry points, and the build
writes byte-identical copies under schemas/v0.1/ as the archived set. Version 0.2 of AbsenceEpisode pins
absence-reason at its current version (0.2.0, eleven codes); the v0.1 schema keeps its six-code enum and its pin at
0.1.0, which the code-list registry resolves to the preserved archive file. Every v0.2 schema is Draft 2020-12, closed at every object, and carries one optional root property `ext`
keyed by profile namespace. Extension payloads are objects whose nested values are structurally checked and whose
named identifier keys (OHEpisode: also its named clinical-content keys) are prohibited at every depth. That is a
key-based check and nothing more: an identifier inside a permitted string is not detected, and the schemas say so.

    python tools/build_schemas_v0_2.py           # writes schemas/v0.2/*.json and schemas/catalogue.json
    python tools/build_schemas_v0_2.py --check   # fails if a committed file differs from a fresh build
"""
import copy, json, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "schemas"
V2 = ROOT / "schemas" / "v0.2"
V1_ARCHIVE = ROOT / "schemas" / "v0.1"
BASE = "https://openworkplacehealth.org/schemas/v0.2/"

IDENTIFIER_KEYS = ["name", "nino", "email", "dateOfBirth", "address"]
OH_CLINICAL_KEYS = ["diagnosis", "clinicalCauseCode", "symptoms", "testResults", "reportText", "history"]
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
EXT_COMMENT = ("Extension namespaces and values are structurally checked. The named identifier keys are prohibited recursively; "
               "OHEpisode also prohibits its named clinical-content keys recursively. This is not detection of identifiers or "
               "clinical meaning hidden in allowed keys or values. All extensions remain subject to P1-P5 and their applicable "
               "profile. A core-only pass does not establish profile or Level 3 conformance.")


def codelist(name):
    d = json.loads((ROOT / "codelists" / f"{name}.json").read_text(encoding="utf-8"))
    return d["version"], [c["code"] for c in d.get("codes", d.get("values", []))]


def ext_property():
    return {"type": "object", "$comment": EXT_COMMENT,
            "propertyNames": {"pattern": "^owhs-[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", "maxLength": 64},
            "additionalProperties": {"$ref": "#/$defs/owhsExtensionObject"}}


def ext_defs(forbidden):
    return {"owhsExtensionObject": {"type": "object", "propertyNames": {"not": {"enum": forbidden}},
                                    "additionalProperties": {"$ref": "#/$defs/owhsExtensionValue"}},
            "owhsExtensionValue": {"anyOf": [{"type": ["string", "number", "boolean", "null"]},
                                             {"type": "array", "items": {"$ref": "#/$defs/owhsExtensionValue"}},
                                             {"$ref": "#/$defs/owhsExtensionObject"}]}}


def with_ext(schema, forbidden):
    s = copy.deepcopy(schema)
    s["properties"]["ext"] = ext_property()
    s.setdefault("$defs", {}).update(ext_defs(forbidden))
    return s


def idf(desc, **kw):
    d = {"type": "string", "pattern": ID_PATTERN, "description": desc}; d.update(kw); return d


def text(desc, maxlen=2000):
    return {"type": "string", "minLength": 1, "maxLength": maxlen, "description": desc}


def num(desc, **kw):
    d = {"type": "number", "description": desc}; d.update(kw); return d


def enum_from(name, desc):
    v, codes = codelist(name)
    return {"type": "string", "enum": codes, "$comment": f"codelist:{name}@{v}", "description": desc}


def closed(props, required, desc=None):
    d = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    if desc: d["description"] = desc
    return d


def provenance(desc):
    return closed({"id": idf("Identifier of the rule or table."), "version": idf("Version of the rule or table."),
                   "sourceRef": text("Where the rule or table is published or held."), "description": text("Optional description.")},
                  ["id", "version", "sourceRef"], desc)


def measurement_schemas():
    cd_v, cd = codelist("construct-domain")
    common = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
    wo = dict(common, **{
        "$id": BASE + "WellbeingObservation.json", "title": "OWHS WellbeingObservation v0.2",
        "description": "One answer to one survey item on one occasion, any vendor. Individual-never at this grain: it leaves an organisation only through an AggregateReport.",
        "type": "object", "additionalProperties": False,
        "required": ["observationId", "orgId", "pseudonymId", "contextId", "itemId", "itemVersion", "constructCode", "nativeValue", "occasionTs", "safeguardingCategory"],
        "properties": {
            "observationId": idf("Primary identifier, unique within the organisation."),
            "orgId": idf("Organisation scope. Metadata remains subject to P1."),
            "pseudonymId": idf("WorkerPseudonym reference. The same string in two organisations is not the same person."),
            "contextId": idf("Same-organisation MeasurementContext reference; one immutable scoring and interpretation descriptor."),
            "itemId": idf("Item identifier. No item wording is carried."),
            "itemVersion": idf("Version of this item and its response options."),
            "constructCode": enum_from("construct-domain", "Construct the item measures."),
            "nativeValue": num("Observed response on the declared native scale."),
            "normalisedValue": num("Arithmetic transformation of nativeValue to 0..100 under the context's declared normalisation. Not equivalence with any other item or score.", minimum=0, maximum=100),
            "occasionTs": {"type": "string", "format": "date-time", "pattern": "(Z|[+-]\\d{2}:\\d{2})$", "description": "Observation occasion, with an asserted time zone."},
            "collectionChannel": enum_from("collection-channel", "How the answer was collected."),
            "safeguardingCategory": {"type": "boolean", "description": "Explicit flag. Absence is not inferred; the field is required."},
            "samplingDesign": closed({"design": enum_from("sampling-design", "Sampling design under which this item was offered."),
                                      "scheduleRef": idf("Schedule reference, required for rotating-subset and adaptive designs.")},
                                     ["design"], "Metadata only."),
        },
        "allOf": [{"if": {"properties": {"samplingDesign": {"properties": {"design": {"enum": ["rotating-subset", "adaptive"]}}, "required": ["design"]}}, "required": ["samplingDesign"]},
                   "then": {"properties": {"samplingDesign": {"required": ["design", "scheduleRef"]}}}}],
    })
    ia = dict(common, **{
        "$id": BASE + "InstrumentAdministration.json", "title": "OWHS InstrumentAdministration v0.2",
        "description": "One completed, partial or abandoned administration of a validated instrument: scores and bands, never item text. Individual-never at this grain. The schema does not grant a licence to administer the instrument.",
        "type": "object", "additionalProperties": False,
        "required": ["administrationId", "orgId", "pseudonymId", "contextId", "instrumentId", "instrumentCitation", "instrumentVersion", "occasionTs", "constructCodes", "completionStatus"],
        "properties": {
            "administrationId": idf("Primary identifier, unique within the organisation."),
            "orgId": idf("Organisation scope."),
            "pseudonymId": idf("WorkerPseudonym reference."),
            "contextId": idf("Same-organisation MeasurementContext reference."),
            "instrumentId": idf("Stable identifier of the exact instrument or form. Not its registry grade."),
            "instrumentCitation": text("Bibliographic citation of the instrument. No questionnaire item text."),
            "instrumentVersion": idf("Form or version, separate from any dataset version."),
            "occasionTs": {"type": "string", "format": "date-time", "pattern": "(Z|[+-]\\d{2}:\\d{2})$", "description": "Administration occasion, with an asserted time zone."},
            "constructCodes": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "enum": cd, "$comment": f"codelist:construct-domain@{cd_v}"},
                               "description": "Constructs the instrument measures; a multidimensional instrument lists several without inventing one total construct."},
            "completionStatus": enum_from("completion-status", "complete, partial or abandoned."),
            "totalScore": num("Total score, where the instrument defines one."),
            "subscaleScores": {"type": "object", "minProperties": 1, "propertyNames": {"pattern": ID_PATTERN, "not": {"enum": IDENTIFIER_KEYS}},
                               "additionalProperties": {"type": "number"}, "description": "Subscale identifier to finite score."},
            "band": idf("Band label under the context's declared banding."),
            "aboveThresholdFlag": {"type": "boolean", "description": "Under the context's declared threshold. Severe-distress measures carry the n>=10 floor at aggregation (P2)."},
        },
        "allOf": [
            {"if": {"properties": {"completionStatus": {"const": "complete"}}}, "then": {"anyOf": [{"required": ["totalScore"]}, {"required": ["subscaleScores"]}]}},
            {"if": {"properties": {"completionStatus": {"const": "abandoned"}}}, "then": {"not": {"anyOf": [{"required": ["totalScore"]}, {"required": ["subscaleScores"]}, {"required": ["band"]}, {"required": ["aboveThresholdFlag"]}]}}},
        ],
    })
    mc = dict(common, **{
        "$id": BASE + "MeasurementContext.json", "title": "OWHS MeasurementContext v0.2",
        "description": "What makes scores comparable: the producing system, the scoring descriptor and its provenance, the data window it describes, and the stated limitations. Immutable: a changed descriptor is a new context.",
        "type": "object", "additionalProperties": False,
        "required": ["contextId", "orgId", "producingSystem", "scoringDescriptor", "knownLimitations"],
        "properties": {
            "contextId": idf("Primary identifier, unique within the organisation."),
            "orgId": idf("Organisation scope."),
            "producingSystem": text("System and version that produced the scores. Identifies, does not disclose architecture."),
            "knownLimitations": text("Stated limitations. 'Not assessed' means exactly that."),
            "recallPeriod": text("The instrument's recall period where its source specifies one, for example 'preceding two weeks'. Distinct from observationWindow."),
            "scoringDescriptor": closed({
                "descriptorId": idf("Identifier of this descriptor."),
                "descriptorVersion": idf("Version of this descriptor."),
                "method": text("Scoring method, in the producer's words."),
                "estimand": text("What the score estimates: a period mean, a modelled current state, a rolling average with its window, and so on."),
                "observationWindow": closed({"start": {"type": "string", "format": "date-time", "pattern": "(Z|[+-]\\d{2}:\\d{2})$"},
                                             "end": {"type": "string", "format": "date-time", "pattern": "(Z|[+-]\\d{2}:\\d{2})$"}},
                                            ["start", "end"], "The data the descriptor represents. Not the instrument's recall period."),
                "sourceRef": text("Where the method is published or held."),
                "scoreUnit": text("Unit of the score."),
                "higherScoreMeaning": {"type": "string", "enum": ["higher-construct", "lower-construct", "not-ordered"]},
                "nativeScale": closed({"min": {"type": "number"}, "max": {"type": "number"}}, ["min", "max"], "Bounds of the native response scale."),
                "normalisation": provenance("Rule that maps nativeValue to 0..100. Required by any observation carrying normalisedValue."),
                "banding": provenance("Banding table. Required by any administration carrying band."),
                "threshold": provenance("Threshold rule. Required by any administration carrying aboveThresholdFlag."),
                "missingResponseRule": provenance("Scoring rule for partial administrations. Required by any partial administration carrying scores."),
            }, ["descriptorId", "descriptorVersion", "method", "estimand", "observationWindow", "sourceRef"],
               "Closed object with open method identifiers: the fields are fixed, the methods they name are the producer's."),
        },
    })
    ar = dict(common, **{
        "$id": BASE + "AggregateReport.json", "title": "OWHS AggregateReport v0.2",
        "description": "The only way individual-level results leave an organisation. Structural consistency of declarations, not a disclosure assessment: the schema cannot know the recipient, and a safeguarding record valid as suppressed must still never enter employer output (P4).",
        "type": "object", "additionalProperties": False,
        "required": ["reportId", "orgId", "level", "periodStart", "periodEnd", "n", "headcount", "eligibleN", "completionRate", "metricCode", "measureKind", "releaseCategory", "suppressed", "contextId"],
        "properties": {
            "reportId": idf("Primary identifier, unique within the organisation."),
            "orgId": idf("Organisation scope."),
            "level": {"type": "string", "enum": ["org", "unit"]},
            "unitId": idf("OrgUnit reference; required at unit level, forbidden at org level."),
            "periodStart": {"type": "string", "format": "date"}, "periodEnd": {"type": "string", "format": "date", "description": "Inclusive period, ordered."},
            "n": {"type": "integer", "minimum": 0, "description": "Distinct people contributing to this metric's estimate in this window."},
            "observationCount": {"type": "integer", "minimum": 0, "description": "Responses underlying the estimate; may exceed n with repeated observations."},
            "headcount": {"type": "integer", "minimum": 0, "description": "In-scope distinct roster for the declared window."},
            "eligibleN": {"type": "integer", "minimum": 0, "description": "Distinct people eligible or offered this metric in the window."},
            "completionRate": {"type": ["number", "null"], "minimum": 0, "maximum": 1, "description": "n divided by eligibleN; null only when eligibleN is 0."},
            "metricCode": idf("Metric identifier. Not presumed equal to a construct code."),
            "measureKind": {"type": "string", "enum": ["observation", "instrument", "other"], "description": "Source grain, not a reliability claim."},
            "releaseCategory": {"type": "string", "enum": ["ordinary", "severe-distress", "safeguarding"], "description": "Producer-declared. Misclassification is not detected by a numerical gate."},
            "value": num("The estimate. Present only when not suppressed."),
            "interval": closed({"low": {"type": "number"}, "high": {"type": "number"}, "level": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
                                "method": text("Interval method."), "sourceRef": text("Where the method is published.")}, ["low", "high", "level", "method"]),
            "suppressed": {"type": "boolean"},
            "suppressionReason": enum_from("suppression-reason", "Required when suppressed; forbidden otherwise."),
            "contextId": idf("Same-organisation MeasurementContext reference."),
            "benchmarkRef": closed({"benchmarkId": idf("BenchmarkRelease identifier."), "releaseVersion": idf("Immutable release version."), "sourceRef": text("Where the release is published.")},
                                   ["benchmarkId", "releaseVersion", "sourceRef"], "Reference to a comparison release. No implied score equivalence. Not resolved by the core validator."),
        },
        "allOf": [
            {"if": {"properties": {"level": {"const": "unit"}}}, "then": {"required": ["unitId"]}, "else": {"not": {"required": ["unitId"]}}},
            {"if": {"properties": {"suppressed": {"const": True}}},
             "then": {"required": ["suppressionReason"], "not": {"anyOf": [{"required": ["value"]}, {"required": ["interval"]}]}},
             "else": {"required": ["value"], "not": {"required": ["suppressionReason"]}}},
            {"if": {"properties": {"n": {"maximum": 4}}}, "then": {"properties": {"suppressed": {"const": True}}}},
            {"if": {"properties": {"releaseCategory": {"const": "severe-distress"}, "n": {"maximum": 9}}, "required": ["releaseCategory"]}, "then": {"properties": {"suppressed": {"const": True}}}},
            {"if": {"properties": {"releaseCategory": {"const": "safeguarding"}}, "required": ["releaseCategory"]}, "then": {"properties": {"suppressed": {"const": True}}}},
            {"if": {"properties": {"eligibleN": {"const": 0}}}, "then": {"properties": {"completionRate": {"type": "null"}, "n": {"const": 0}, "suppressed": {"const": True}}}},
        ],
    })
    return {"WellbeingObservation": wo, "InstrumentAdministration": ia, "MeasurementContext": mc, "AggregateReport": ar}


def build():
    out = {}
    for n in ["AbsenceEpisode", "ReturnToWorkOutcome", "OHEpisode"]:
        s = json.loads((V1 / f"{n}.json").read_text(encoding="utf-8"))
        s["$id"] = BASE + f"{n}.json"
        s["title"] = s.get("title", f"OWHS {n}").replace("v0.1", "v0.2")
        if n == "AbsenceEpisode":
            ar_v, ar_codes = codelist("absence-reason")
            s["description"] = "Reported sickness-absence episode with versioned reason-category mapping. No direct identifiers."
            s["properties"]["reasonCode"] = {"type": "string", "enum": ar_codes,
                                             "$comment": f"codelist:absence-reason@{ar_v}. Reported reason categories following the ONS 2025 workbook plus its separate non-disclosure response; not diagnoses. The crosswalk from the v0.1 six-code list is codelists/mappings/absence-reason-ons-2025-v1.json; a legacy other is not upgraded automatically."}
        out[n] = with_ext(s, IDENTIFIER_KEYS + (OH_CLINICAL_KEYS if n == "OHEpisode" else []))
    for n, s in measurement_schemas().items():
        out[n] = with_ext(s, IDENTIFIER_KEYS)
    catalogue = {"note": "Versioned schema catalogue. The unversioned files under schemas/ are the v0.1 entry points and are unchanged; schemas/v0.1/ holds byte-identical copies as the archived set. A caller names the version it validates against; validation does not choose a version from an unversioned payload.",
                 "versions": {
                     "0.1": {"status": "archived", "entities": {n: {"file": f"schemas/v0.1/{n}.json", "entry_point": f"schemas/{n}.json", "$id": f"https://openworkplacehealth.org/schemas/v0.1/{n}.json"} for n in ["AbsenceEpisode", "ReturnToWorkOutcome", "OHEpisode"]},
                             "codelists": {"absence-reason": "0.1.0 (six codes), resolved through codelists/_registry.json versions to codelists/archive/absence-reason@0.1.0.json"}},
                     "0.2": {"status": "current", "extension": "ext, keyed by profile namespace; see profiles/", "entities": {n: {"file": f"schemas/v0.2/{n}.json", "$id": out[n]["$id"]} for n in out},
                             "codelists": {"absence-reason": f"{codelist('absence-reason')[0]} (eleven codes); crosswalk codelists/mappings/absence-reason-ons-2025-v1.json"}}}}
    return out, catalogue


def main():
    out, catalogue = build()
    files = {V2 / f"{n}.json": json.dumps(s, indent=2, ensure_ascii=False) + "\n" for n, s in out.items()}
    files[V1 / "catalogue.json"] = json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n"
    for n in ["AbsenceEpisode", "ReturnToWorkOutcome", "OHEpisode"]:      # the archived v0.1 set: byte-identical copies of the entry points
        files[V1_ARCHIVE / f"{n}.json"] = (V1 / f"{n}.json").read_text(encoding="utf-8")
    if "--check" in sys.argv:
        stale = [str(p.relative_to(ROOT)) for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale:
            sys.exit("schemas/v0.2 do not match a fresh build; run tools/build_schemas_v0_2.py\n" + "".join(f"  differs: {s}\n" for s in stale))
        print(f"up to date: {len(files)} schema files match their source"); return
    V2.mkdir(parents=True, exist_ok=True); V1_ARCHIVE.mkdir(parents=True, exist_ok=True)
    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    print(f"wrote {len(out)} v0.2 schemas, schemas/catalogue.json and the archived v0.1 copies")


if __name__ == "__main__":
    main()
