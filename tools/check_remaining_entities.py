#!/usr/bin/env python3
"""Gate for the nine entity types that completed the v0.2 catalogue: Organisation, OrgUnit, WorkerPseudonym, ReasonableAdjustment,
BenefitEntitlement, BenefitUtilisation, DisabilityParticipation, BenchmarkRelease and Crosswalk.

    python tools/check_remaining_entities.py --self-test

What is checked, and how: every one of the nine schemas meta-validates as Draft 2020-12 and equals its reviewed contract (the hash of its
canonical JSON is pinned here, as are the three new code lists, the principal valid and invalid fixtures and the procedural case set);
the seven predecessor schema files are byte-identical to their reviewed bytes; every committed fixture for the nine entities is run
through the real tools/validate.py command line as a subprocess, and its verdict, error keyword multiset and named within-record rules
(C10 to C18) are compared with the expected ones, not merely its exit code; the structural case set (valid, root identifier, unknown and
identifier-carrying extensions, principal invalids, whitespace in identifiers, null dates, boolean counts, syntactic-only externals,
statutory branch requirements, release-category floors, the safeguarding refusal) and further adversarial cases (extra keys at root and
depth, each new required field removed, malformed dates and year zero, scalar and list roots, non-finite and overflowing numbers, invalid
code-list values, ISO edition pairing, empty crosswalk targets, invalid extension namespaces and payloads, forbidden identifiers at depth
and inside arrays) are written to temporary files and run through the same command line. A tool error (exit 2) is reported as a tool
error, never as an invalid instance. Nothing here is an in-memory check dressed as a run: every verdict below comes from a subprocess.
"""
import copy, hashlib, json, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "tools" / "validate.py"
V2 = ROOT / "schemas" / "v0.2"
EX = ROOT / "examples" / "v0.2"
NEW = ["Organisation", "OrgUnit", "WorkerPseudonym", "ReasonableAdjustment", "BenefitEntitlement", "BenefitUtilisation", "DisabilityParticipation", "BenchmarkRelease", "Crosswalk"]
PREDECESSORS = ["AbsenceEpisode", "ReturnToWorkOutcome", "OHEpisode", "WellbeingObservation", "InstrumentAdministration", "MeasurementContext", "AggregateReport"]
# ---- the reviewed contract: canonical-JSON hashes (sorted keys, ensure_ascii false) of the accepted proposal's objects ----
SCHEMA_PINS = {"Organisation": "99708f7faee637530356c65747e6310297da81f726a495009c778cccaaf0cfd3", "OrgUnit": "856baca4b255d62e9f2dc7a9a5a836de13de0e318600406712feead3d92cb0e8", "WorkerPseudonym": "2cc069e759ca2d1463313833b582e38e7091fbe281fff28da29a1fe664d452da", "ReasonableAdjustment": "f55c273a5980ad5dd2ec9be4b6bbb632a8cb573f0960b781419bd403aa5897b8", "BenefitEntitlement": "50ff227f0f715789b6645e6df2a1c13da5705dfe31f87f779225827016c165be", "BenefitUtilisation": "df8e4316a69844a56d33749320be729f5999f4f019ef3e8054acebe65005be85", "DisabilityParticipation": "70e8c74b9a85c3cd0a018bfe48e738ca0ab52fc6eb40e9a143332b9db53c6962", "BenchmarkRelease": "ccf75ee2e9a2623fc05dfe19d77075b9a15df98860f8e3a4d35725b7fb42bc1c", "Crosswalk": "8ef333c31566b3734eedd9d59e335a971a66a1b42c551f54443234e837fd23bc"}
CODELIST_PINS = {"benefit-layer": "87e99fd820dd40b6d9bdfc13498271c5185e75ae50e131a32f1e9849c618ff1f", "hse-management-domain": "b296d12ab84a00332367e51252195e64656c72f1f8670188a049317f3ac24555", "release-category": "ac11c2d0e62452843e71706b492569ec6476e5a5365365860df680b609d93112"}
VALID_PINS = {"Organisation": "8738293d45636b695be382d524cc680f358b285aeb215731bcff45d59eab5c1b", "OrgUnit": "9d298824cd11b7b40845604cd9351ec4e9268dab8cff228a645ce93b0237d9be", "WorkerPseudonym": "668d8d24630015f879df28398a195f2c2d889e403fc4cc1925cc2690c1d85cbd", "ReasonableAdjustment": "12b6afbd1565f9c02dc9e14a11a4c4166e8ee2a61ac124fb2559654e08b0c952", "BenefitEntitlement": "60993a55902f30fd7d619d84aeea9e63e7e87c4e0a2c8ae8dcab1370bb08524c", "BenefitUtilisation": "20cab5c93f9be73d398c2f6fcd32015c3d747f6e7b261dc2dde28805ee4e8c46", "DisabilityParticipation": "b3175eced5a9baeed679117ef74230100536326f5778dc731358ca0a04ee8f43", "BenchmarkRelease": "35a5877470d12bc550be613e9243cb5103983444636ecf93fb4eade430e42e33", "Crosswalk": "5dc6fb53df37662b0c389aef91653d8cb3f3612f314d89b1b792f5859eaec20b"}
INVALID_PINS = {"Organisation": "81f78b0bd235e0a570f6c9ce3f4c85781fe00f5d57f49645f7eea57fb8bb5f84", "OrgUnit": "2c9f14074d8d77c5ff47c9d0ce60504431def3e721db1560401f2989e4afcea5", "WorkerPseudonym": "485b8fac0876a82974abaa1c1d1897fcbbc0a30c0f87d4690c83dfa494d38456", "ReasonableAdjustment": "62b87b638328012b36c977f6b6ffa3179f5554d76bb715bbd60c37ad4d5b7afc", "BenefitEntitlement": "63e44a174b26983a1809d1d32bad96e8a38ec2018f70ddc7d0900b2fd311a16c", "BenefitUtilisation": "22e97536b34d59183b719a4d8b58499bec9723e75886a7e657407fe72ab496ab", "DisabilityParticipation": "9f4164e9eb0483cb0b1382774d128170e2c9a1203962f9b059d380276acdf355", "BenchmarkRelease": "3b751af312929acb356983ec4824af227dc042a83848f13c1536ad71c4a9b9bc", "Crosswalk": "fbe0bab95cbbf40f7dde562eb14ce8b0be1fc14a23ac9a86c4dd9bcf5140cf20"}
AGGREGATE_REPORT_BEHAVIOUR = "430328a8468ea3d66fdf3e0f94edb1a45d5db0d2c9155bed7c33e9123e003244"   # canonical hash of the schema with every description removed; unchanged from the first set
PREDECESSOR_BYTES = {"AbsenceEpisode": "a5d733e05fe9e4ab4ec83d7e0e152afb2b5778e72700552583df51c31cb39c90", "ReturnToWorkOutcome": "22c0ca8d8c2940d88a2bdbfc65d609c3be87fc1a9ff391d085ae8c9e52e2cdd2", "OHEpisode": "4c564fe016392fb6593fd87dddef79697cc932fc5aee44b1baad4cd64aa7cfd8",
                     "WellbeingObservation": "30aa5081aaa4c35b05ba5ab726be5edda9d708c04c6de6ddd73e493bbd59c24d", "InstrumentAdministration": "4eb772c17780fd9960649b63c178a39d0d7602be59d555a53814b1645a477b2f", "MeasurementContext": "626345412ea61ade36ed41b6f38b0b29eaca08cdb6a17cc1f032dbce4759b2ac", "AggregateReport": "803cf3f92ac2bffbb41b1611b691eab6f0e59901c2bd6867a1264f3cfde1d07a"}
# the principal invalid fixtures' expected error keyword multisets
PRINCIPAL_INVALID = {"Organisation": ["maxLength", "pattern"], "OrgUnit": ["enum"], "WorkerPseudonym": ["pattern"], "ReasonableAdjustment": ["enum"], "BenefitEntitlement": ["not"],
                     "BenefitUtilisation": ["minimum"], "DisabilityParticipation": ["enum"], "BenchmarkRelease": ["required"], "Crosswalk": ["enum"]}
# procedural fixtures: file label -> the rules the validator must name (empty for the valid controls)
RULE_OF = {"reversed-c10": ["C10"], "reversed-c11": ["C11"], "reversed-c12": ["C12"], "reversed-c13": ["C13"], "reversed-c14": ["C14"]}
P = "owhs:pseudo:0123456789abcdef0123456789abcdef"


def canon(o): return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def cli(schema_path, instance, tmp, name="inst.json"):
    """Run the real validator as a subprocess on an instance written to a temporary file. Returns (exit code, keyword multiset,
    rule list, raw lines). Exit 2 is a tool error and is returned as such."""
    p = Path(tmp) / name; p.write_text(instance if isinstance(instance, str) else json.dumps(instance, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(VALIDATE), str(schema_path), str(p)], capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("[")]
    tags = [l[1:l.index("]")] for l in lines]
    keywords = sorted(t for t in tags if not (t.startswith("C") and t[1:].isdigit()) and t not in ("profile",))
    rules = sorted(t for t in tags if t.startswith("C") and t[1:].isdigit())
    return r.returncode, keywords, rules, lines, r.stderr


def main():
    if "--self-test" not in sys.argv: sys.exit(__doc__)
    if not VALIDATE.exists(): sys.exit("tools/validate.py is missing; there is no real command line to run and nothing is claimed")
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else detail); failures += not ok
    from jsonschema import Draft202012Validator as V
    schemas = {n: json.loads((V2 / f"{n}.json").read_text(encoding="utf-8")) for n in NEW}
    for n, s in schemas.items():
        try: V.check_schema(s); meta = True
        except Exception as e: meta = False; detail = str(e)[:120]
        t(f"{n}: meta-validates as Draft 2020-12", meta, detail if not meta else "")
        t(f"{n}: equals its reviewed contract (canonical hash)", canon(s) == SCHEMA_PINS[n], canon(s)[:16])
        t(f"{n}: versioned $id, closed root, extension fragment present", s["$id"] == f"https://openworkplacehealth.org/schemas/v0.2/{n}.json" and s["additionalProperties"] is False and "ext" in s["properties"] and "owhsExtensionObject" in s["$defs"])
    for n, h in CODELIST_PINS.items():
        d = json.loads((ROOT / "codelists" / f"{n}.json").read_text(encoding="utf-8"))
        t(f"code list {n}: present, version 0.1.0, equals its reviewed contract", d["version"] == "0.1.0" and canon(d) == h)
    reg = json.loads((ROOT / "codelists" / "_registry.json").read_text(encoding="utf-8"))
    t("registry lists 27 code lists including the three new ones with version maps", len(reg["lists"]) == 27 and all(any(e["name"] == n and e["versions"] == {"0.1.0": f"{n}.json"} for e in reg["lists"]) for n in CODELIST_PINS))
    for n, h in PREDECESSOR_BYTES.items():
        t(f"{n}: predecessor schema bytes unchanged", hashlib.sha256((V2 / f"{n}.json").read_bytes()).hexdigest() == h)
    # AggregateReport's description was reworded (its first sentence no longer says individual-level results leave only this way);
    # with every description removed the schema is byte-for-byte the first-set schema's behaviour
    def stripped(o):
        if isinstance(o, dict): return {k: stripped(v) for k, v in o.items() if k != "description"}
        if isinstance(o, list): return [stripped(v) for v in o]
        return o
    t("AggregateReport: behaviour identical to the first-set predecessor once descriptions are removed", canon(stripped(json.loads((V2 / "AggregateReport.json").read_text(encoding="utf-8")))) == AGGREGATE_REPORT_BEHAVIOUR)
    cat = json.loads((ROOT / "schemas" / "catalogue.json").read_text(encoding="utf-8"))
    t("catalogue: sixteen v0.2 entity types and three archived v0.1 entries (nineteen identities)", len(cat["versions"]["0.2"]["entities"]) == 16 and len(cat["versions"]["0.1"]["entities"]) == 3 and all(n in cat["versions"]["0.2"]["entities"] for n in NEW))
    with tempfile.TemporaryDirectory() as tmp:
        # committed fixtures through the real command line: principal pairs pinned, verdicts and keyword or rule multisets compared
        for n in NEW:
            valid = json.loads((EX / f"{n}.valid.json").read_text(encoding="utf-8")); invalid = json.loads((EX / f"{n}.invalid.json").read_text(encoding="utf-8"))
            t(f"{n}: principal fixtures equal the reviewed instances", canon(valid) == VALID_PINS[n] and canon(invalid) == INVALID_PINS[n])
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", valid, tmp); t(f"{n}.valid: real CLI exit 0, no errors, no rules", rc == 0 and not lines, (rc, lines[:3], err[-120:]))
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", invalid, tmp); t(f"{n}.invalid: real CLI exit 1 with keywords {PRINCIPAL_INVALID[n]}", rc == 1 and kw == PRINCIPAL_INVALID[n] and not rules, (rc, kw, rules))
        proc_files = sorted(p for p in EX.glob("*.json") if p.name.split(".")[0] in NEW and p.name.count(".") == 3)
        n_proc = 0
        for p in proc_files:
            ent, label, verdict = p.name.split(".")[0], p.name.split(".")[1], p.name.split(".")[2]
            inst = json.loads(p.read_text(encoding="utf-8")); rc, kw, rules, lines, err = cli(V2 / f"{ent}.json", inst, tmp)
            if label in RULE_OF: want = RULE_OF[label]
            elif label.startswith("c15"): want = ["C15"] if verdict == "invalid" else []
            elif label.startswith("c16"): want = ["C16"] if verdict == "invalid" else []
            elif label in ("duplicate-probability", "inverted-values"): want = ["C17"]
            elif label == "self-parent": want = ["C18"]
            else: want = []
            ok = (rc == (0 if verdict == "valid" else 1)) and not kw and rules == want
            t(f"{p.name}: real CLI verdict {verdict}, rules {want}", ok, (rc, kw, rules)); n_proc += 1
        t("thirty-six procedural cases are committed as fixtures (nine valid controls are the principal valid files)", n_proc == 27, n_proc)
        # the structural case set, run through the command line
        valid = {n: json.loads((EX / f"{n}.valid.json").read_text(encoding="utf-8")) for n in NEW}
        def mut(n, field, value): d = copy.deepcopy(valid[n]); d[field] = value; return d
        def expect(label, n, inst, keywords, rc_want=None):
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", inst, tmp)
            want_rc = rc_want if rc_want is not None else (0 if not keywords else 1)
            t(f"{n} {label}: keywords {keywords}", rc == want_rc and kw == keywords and not rules, (rc, kw, rules, err[-100:]))
        for n in NEW:
            expect("root identifier key", n, mut(n, "email", "synthetic@example.invalid"), ["additionalProperties"])
            expect("unknown extension namespace accepted structurally", n, mut(n, "ext", {"owhs-example": {"wave": 3}}), [])
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", mut(n, "ext", {"owhs-example": {"nested": [{"email": "synthetic@example.invalid"}]}}), tmp)
            t(f"{n} identifier key inside an extension array is refused", rc == 1 and kw and not rules, (rc, kw))
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", mut(n, "ext", {"bad namespace": {"a": 1}}), tmp); t(f"{n} invalid extension namespace refused (property-name pattern)", rc == 1 and kw == ["pattern"], (rc, kw))
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", mut(n, "ext", {"owhs-example": "not an object"}), tmp); t(f"{n} non-object extension payload refused", rc == 1 and kw, (rc, kw))
            for field in schemas[n]["required"]:
                d = copy.deepcopy(valid[n]); d.pop(field, None)
                rc, kw, rules, lines, err = cli(V2 / f"{n}.json", d, tmp); t(f"{n} without required {field}", rc == 1 and "required" in kw, (rc, kw))
            for label, inst in (("list root", []), ("scalar root", 7)):
                rc, kw, rules, lines, err = cli(V2 / f"{n}.json", inst, tmp); t(f"{n} {label} refused with a type error and no rule", rc == 1 and "type" in kw and not rules, (rc, kw))
            rc, kw, rules, lines, err = cli(V2 / f"{n}.json", '"x"', tmp); t(f"{n} string root refused with a type error and no rule", rc == 1 and "type" in kw and not rules, (rc, kw))
        for n in ["Organisation", "OrgUnit", "WorkerPseudonym", "ReasonableAdjustment", "BenefitEntitlement", "BenefitUtilisation", "DisabilityParticipation"]:
            expect("newline in orgId", n, mut(n, "orgId", "org-demo\n"), ["not"])
        expect("newline in pseudonymId", "WorkerPseudonym", mut("WorkerPseudonym", "pseudonymId", P + "\n"), ["not"])
        expect("null endDate is not a date", "ReasonableAdjustment", mut("ReasonableAdjustment", "endDate", None), ["type"])
        expect("year zero date", "ReasonableAdjustment", mut("ReasonableAdjustment", "startDate", "0000-01-01"), ["format"])
        expect("malformed date", "BenefitUtilisation", mut("BenefitUtilisation", "periodStart", "2026-13-40"), ["format"])
        expect("repeated service use exceeding n", "BenefitUtilisation", mut("BenefitUtilisation", "usageCount", 100), [])
        expect("boolean count", "BenefitUtilisation", mut("BenefitUtilisation", "n", True), ["type"])
        expect("sub-floor internal count", "BenefitUtilisation", mut("BenefitUtilisation", "n", 4), [])
        expect("reserved small disability band", "DisabilityParticipation", mut("DisabilityParticipation", "disabledHeadcountBand", "1-4"), [])
        expect("syntactic unknown country", "Organisation", mut("Organisation", "country", "ZZ"), [])
        d = mut("Organisation", "sicCode", "00000"); d["sicVersion"] = "2007"; expect("syntactic unknown SIC", "Organisation", d, [])
        expect("SIC without its version", "Organisation", mut("Organisation", "sicCode", "01110"), ["dependentRequired"])
        d = mut("Organisation", "sicCode", "01110"); d["sicVersion"] = "2026"; expect("SIC 2026 refused in a 2007 field", "Organisation", d, ["const"])
        expect("unknown HSE domain", "Crosswalk", mut("Crosswalk", "hseDomain", "stress"), ["enum"])
        expect("ISO clause without edition", "Crosswalk", mut("Crosswalk", "iso45003Clause", "6.1.2"), ["dependentRequired"])
        d = copy.deepcopy(valid["Crosswalk"]); del d["hseDomain"]; expect("crosswalk with no target", "Crosswalk", d, ["anyOf"])
        expect("reserved WHIU string accepted syntactically", "DisabilityParticipation", mut("DisabilityParticipation", "whiuMeasureCode", "whiu:placeholder"), [])
        stat = {"entitlementId": "entitlement-statutory", "orgId": "org-demo", "layer": "statutory", "statutory": {"scheme": "synthetic-scheme", "eligibility": "Synthetic eligibility description, not statutory advice.", "sourceRef": "Synthetic example; not a real scheme.", "asOfDate": "2026-09-01"}}
        expect("statutory minimal", "BenefitEntitlement", stat, [])
        sb = copy.deepcopy(stat); del sb["statutory"]["asOfDate"]; expect("statutory undated", "BenefitEntitlement", sb, ["required"])
        sb = copy.deepcopy(stat); sb["productCategory"] = "EAP"; expect("statutory layer with a product category", "BenefitEntitlement", sb, ["not"])
        sb = copy.deepcopy(stat); sb["statutory"]["rate"] = {"amount": -1, "currency": "gbp", "basis": "per week"}; expect("negative rate with a lower-case currency", "BenefitEntitlement", sb, ["minimum", "pattern"])
        for category, floor in (("ordinary", 5), ("severe-distress", 10)):
            for k in (floor - 1, floor):
                d = copy.deepcopy(valid["BenchmarkRelease"]); d["releaseCategory"] = category; d["composition"]["sampleSizes"]["people"] = k
                expect(f"{category} people {k}", "BenchmarkRelease", d, ["minimum"] if k < floor else [])
        rc, kw, rules, lines, err = cli(V2 / "BenchmarkRelease.json", mut("BenchmarkRelease", "releaseCategory", "safeguarding"), tmp); t("safeguarding can never be a published benchmark release", rc == 1 and kw and not rules, (rc, kw))
        d = mut("BenchmarkRelease", "leaveOneOut", False); d["excludedOrgId"] = "org-x"; expect("excludedOrgId without leave-one-out", "BenchmarkRelease", d, ["not"])
        d = copy.deepcopy(valid["BenchmarkRelease"]); d["measure"]["instrumentId"] = "who-5"; expect("instrumentId without instrumentVersion", "BenchmarkRelease", d, ["dependentRequired"])
        d = copy.deepcopy(valid["BenchmarkRelease"]); d["composition"]["extra"] = 1; expect("extra key at depth", "BenchmarkRelease", d, ["additionalProperties"])
        d = copy.deepcopy(valid["BenchmarkRelease"]); d["percentiles"]["values"] = []; expect("empty percentile array", "BenchmarkRelease", d, ["minItems"])
        # non-finite and overflowing numbers reach the validator's number check, never a traceback
        rc, kw, rules, lines, err = cli(V2 / "BenefitUtilisation.json", '{"utilisationId":"u","orgId":"o","entitlementId":"e","periodStart":"2026-08-01","periodEnd":"2026-08-31","usageCount":NaN,"n":1}', tmp)
        t("NaN count is refused by name, no traceback", rc == 1 and kw and "Traceback" not in err, (rc, kw, err[-120:]))
        rc, kw, rules, lines, err = cli(V2 / "BenefitUtilisation.json", '{"utilisationId":"u","orgId":"o","entitlementId":"e","periodStart":"2026-08-01","periodEnd":"2026-08-31","usageCount":1e400,"n":1}', tmp)
        t("an overflowing number is refused by name, no traceback", rc == 1 and kw and "Traceback" not in err, (rc, kw, err[-120:]))
        # tool errors are tool errors
        rc, kw, rules, lines, err = cli(V2 / "Organisation.json", "{not json", tmp); t("unparseable JSON is an invalid instance with a [json] diagnostic (the validator's documented contract), no traceback", rc == 1 and kw == ["json"] and "Traceback" not in err, (rc, kw, err[-120:]))
        r = subprocess.run([sys.executable, "-B", str(VALIDATE), str(Path(tmp) / "absent-schema.json"), str(EX / "Organisation.valid.json")], capture_output=True, text=True)
        t("a missing schema path is a tool error (exit 2)", r.returncode == 2 and "Traceback" not in r.stderr, (r.returncode, r.stderr[-120:]))
        # C18 direct self-parent through the command line
        d = mut("OrgUnit", "parentUnitId", "unit-demo"); rc, kw, rules, lines, err = cli(V2 / "OrgUnit.json", d, tmp); t("OrgUnit parentUnitId equal to unitId names C18", rc == 1 and rules == ["C18"] and not kw, (rc, kw, rules))
        d = mut("OrgUnit", "parentUnitId", "unit-parent"); rc, kw, rules, lines, err = cli(V2 / "OrgUnit.json", d, tmp); t("OrgUnit with a different parent is valid (longer cycles are for a supplied graph checker)", rc == 0 and not lines)
        # a rule is not evaluated on structurally invalid operands, and says so rather than misreporting
        d = mut("BenefitUtilisation", "n", "many"); rc, kw, rules, lines, err = cli(V2 / "BenefitUtilisation.json", d, tmp); t("C15 on a non-integer n reports the type error, not a rule verdict", rc == 1 and kw == ["type"] and not rules, (rc, kw, rules))
    print(f"{'all' if not failures else failures} remaining-entity checks {'passed' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
