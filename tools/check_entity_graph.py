#!/usr/bin/env python3
"""Organisation-scoped integrity checks on a supplied bundle of v0.2 records: the entity-graph envelope.

    python tools/check_entity_graph.py BUNDLE.json [--profile PROFILE.json ...] [--out REPORT.json]
    python tools/check_entity_graph.py --self-test

A bundle (schemas/bundles/EntityGraph-v0.2.json) is a closed object: schema_version "0.2", a comparisonAsOfDate, and three arrays,
organisations (each one Organisation plus all thirteen entity arrays), benchmarks and crosswalks. Empty arrays are valid; missing ones
are not. In order: strict JSON (duplicate keys at any depth, NaN, Infinity and overflowing literals refused before any dictionary is
built), the envelope and every record against its exact v0.2 schema with formats asserted (no network resolution), the named
within-record rules C1 to C18 and any supplied profiles, and only then, on a structurally valid bundle, identity and scope (G01, G02),
reference resolution inside the enclosing organisation (G03), same-worker consistency across linked records (G04), an acyclic unit
hierarchy walked iteratively (G05), return dates not before the linked absence start (G06), benchmark references resolved by the exact
identifier and version pair (G07), declared metric identity (G08), leave-one-out exclusion naming the referencing organisation (G09) and
the comparison date inside the release's declared validity (G10). The measurement-bundle checks of tools/check_measurement.py run
unchanged on each organisation's measurement projection. Every resolved comparison is a review item: a matching metric code is
declared identity, not comparability.

The result is structured JSON: state checked_with_limits (exit 0), not_evaluated for an empty inventory (exit 0, no certificate),
invalid (exit 1) or tool_error (exit 2); entity counts, group count, resolved links by relation (zero edges is not exercised, not
validated), checks performed and not evaluated, errors with rule, JSON pointer and diagnostic, review items, unchecked external
references, profile coverage, and the limits this checker does not establish. No record content is echoed. A pass certifies none of a
complete dataset, anonymity, lawful processing, safe disclosure, clinical validity, benchmark comparability or Level 2 or Level 3.
"""
import copy, hashlib, json, math, os, subprocess, sys, tempfile
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SCHEMA_DIR = ROOT / "schemas" / "v0.2"
ENVELOPE = ROOT / "schemas" / "bundles" / "EntityGraph-v0.2.json"
PROFILE_ENVELOPE = ROOT / "profiles" / "profile-envelope.schema.json"
EXAMPLES = ROOT / "examples" / "bundles" / "v0.2"
REPORT_SCHEMA_VERSION = "1.0"
ENTITIES = {"units": ("OrgUnit", "unitId"), "workers": ("WorkerPseudonym", "pseudonymId"), "absences": ("AbsenceEpisode", "episodeId"), "rtwOutcomes": ("ReturnToWorkOutcome", "outcomeId"),
            "ohEpisodes": ("OHEpisode", "ohEpisodeId"), "adjustments": ("ReasonableAdjustment", "adjustmentId"), "entitlements": ("BenefitEntitlement", "entitlementId"),
            "utilisations": ("BenefitUtilisation", "utilisationId"), "disabilityParticipations": ("DisabilityParticipation", "reportId"), "contexts": ("MeasurementContext", "contextId"),
            "observations": ("WellbeingObservation", "observationId"), "administrations": ("InstrumentAdministration", "administrationId"), "reports": ("AggregateReport", "reportId")}
ALL_ENTITIES = ["Organisation"] + [n for n, _ in ENTITIES.values()] + ["BenchmarkRelease", "Crosswalk"]
EDGES = [("units", "parentUnitId", "units"), ("workers", "unitId", "units"), ("reports", "unitId", "units"), ("utilisations", "entitlementId", "entitlements")] \
      + [(a, "pseudonymId", "workers") for a in ["absences", "rtwOutcomes", "ohEpisodes", "adjustments", "observations", "administrations"]] \
      + [(a, "contextId", "contexts") for a in ["observations", "administrations", "reports"]]
LINKED = [("rtwOutcomes", "absenceEpisodeId", "absences"), ("ohEpisodes", "linkedAbsenceEpisodeId", "absences"), ("adjustments", "sourceOhEpisodeId", "ohEpisodes")]
NOT_ESTABLISHED = ["complete workforce dataset or roster", "anonymity or re-identification risk", "lawful processing", "safe disclosure or privacy-profile conformance", "clinical validity",
                   "benchmark comparability: population, sampling, time transfer, method, unit and score equivalence", "truth of a declared leave-one-out exclusion", "quantile construction",
                   "source authenticity and truth of counts", "Level 2 or Level 3 conformance"]
SUCCESS = ("The supplied records passed the listed structure, within-record and relationship checks. Unchecked external references and interpretation limits are listed in the report. "
           "This result does not certify a complete workforce dataset, anonymity, lawful processing, safe disclosure, clinical validity, benchmark comparability or Level 2 or Level 3 conformance.")


class ToolError(Exception): pass
class InvalidInput(Exception): pass


def _reject_constant(name): raise ValueError(f"non-finite number {name} is not JSON")
def _finite_float(text):
    v = float(text)
    if not math.isfinite(v): raise ValueError(f"numeric literal {text} overflows")
    return v
def _no_dupes(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)): raise ValueError(f"duplicate object key {next(k for k in keys if keys.count(k) > 1)!r}")
    return dict(pairs)


def loads_strict(text):
    """Standard JSON grammar only, with duplicate keys refused at every depth: raises ValueError, never builds a dictionary from them."""
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float, object_pairs_hook=_no_dupes)


def load_inventory():
    """The local schema inventory: the envelope, the sixteen entity schemas and the profile envelope schema. Anything missing is a tool error."""
    try:
        from jsonschema.validators import Draft202012Validator as V
        from jsonschema import FormatChecker
        from referencing import Registry, Resource
    except ImportError as e: raise ToolError(f"dependency missing: {e}")
    if not ENVELOPE.exists(): raise ToolError(f"envelope schema missing: {ENVELOPE.relative_to(ROOT)}")
    schemas = {}
    for n in ALL_ENTITIES:
        p = SCHEMA_DIR / f"{n}.json"
        if not p.exists(): raise ToolError(f"entity schema missing: {p.relative_to(ROOT)}")
        schemas[n] = json.loads(p.read_text(encoding="utf-8"))
    env = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    for s in list(schemas.values()) + [env]:
        try: V.check_schema(s)
        except Exception as e: raise ToolError(f"schema {s.get('$id')} does not meta-validate: {str(e)[:120]}")
    def refuse(uri): raise ToolError(f"schema reference {uri!r} is not in the local inventory; network retrieval is not performed")
    reg = Registry(retrieve=refuse).with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    penv = json.loads(PROFILE_ENVELOPE.read_text(encoding="utf-8")) if PROFILE_ENVELOPE.exists() else None
    hashes = {f"schemas/v0.2/{n}.json": hashlib.sha256((SCHEMA_DIR / f"{n}.json").read_bytes()).hexdigest() for n in ALL_ENTITIES}
    hashes[str(ENVELOPE.relative_to(ROOT))] = hashlib.sha256(ENVELOPE.read_bytes()).hexdigest()
    return {"V": V, "FormatChecker": FormatChecker, "schemas": schemas, "envelope": env, "registry": reg, "profile_envelope": penv, "hashes": hashes}


def pointer(path): return "/".join(map(str, path))


def structural_errors(inv, bundle):
    """Envelope and every record against its exact schema, formats asserted: (code, pointer, message)."""
    V, FC = inv["V"], inv["FormatChecker"]
    try: errs = sorted(V(inv["envelope"], registry=inv["registry"], format_checker=FC()).iter_errors(bundle), key=lambda e: [str(x) for x in e.path])
    except Exception as e: raise ToolError(f"the envelope schema could not be applied: {str(e)[:160]}")
    return [(f"schema:{e.validator}", pointer(e.path), e.message[:200]) for e in errs]


def records(bundle):
    """(entity, record, pointer) for every record in a structurally valid bundle."""
    items = [("BenchmarkRelease", x, f"benchmarks/{i}") for i, x in enumerate(bundle["benchmarks"])] + [("Crosswalk", x, f"crosswalks/{i}") for i, x in enumerate(bundle["crosswalks"])]
    for gi, g in enumerate(bundle["organisations"]):
        items.append(("Organisation", g["organisation"], f"organisations/{gi}/organisation"))
        for arr, (n, pk) in ENTITIES.items(): items.extend((n, x, f"organisations/{gi}/{arr}/{i}") for i, x in enumerate(g[arr]))
    return items


def rule_errors(items):
    """C1 to C18 from tools/validate.py, the same functions the single-record validator runs."""
    import validate as v
    out = []
    for n, x, loc in items:
        for code, fn in v.CROSS_FIELD_RULES.get(n, []):
            try: msg = fn(x)
            except (TypeError, AttributeError, KeyError, ValueError) as e: raise ToolError(f"rule {code} failed on a structurally valid record at {loc}: {e!r}")
            if msg: out.append((code, loc, msg))
    return out


def profile_results(inv, profiles, items):
    """Supplied profiles: each envelope validated first, dispatched only to records whose exact schema $id it names, run with the real
    validator classes; errors, coverage and unused profiles. A missing, malformed or conflicting envelope is a tool error."""
    V, FC = inv["V"], inv["FormatChecker"]
    if not profiles: return [], {}, []
    if inv["profile_envelope"] is None: raise ToolError("profiles supplied but profiles/profile-envelope.schema.json is missing")
    seen, applied, errors = {}, {}, []
    for path in profiles:
        try: env = loads_strict(Path(path).read_text(encoding="utf-8"))
        except OSError as e: raise ToolError(f"profile {path}: {e}")
        except ValueError as e: raise ToolError(f"profile {path} is not strict JSON: {e}")
        bad = list(V(inv["profile_envelope"], format_checker=FC()).iter_errors(env))
        if bad: raise ToolError(f"profile envelope {path} is malformed: " + "; ".join(e.message[:80] for e in bad[:3]))
        key = (env["profile_id"], env["version"])
        if key in seen and seen[key] != env: raise ToolError(f"two different envelopes supplied for profile {key[0]} {key[1]}")
        seen[key] = env
        try: V.check_schema(env["schema"])
        except Exception as e: raise ToolError(f"profile {key[0]} {key[1]} schema does not meta-validate: {str(e)[:100]}")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        label = f"{key[0]}@{key[1]}"; applied[label] = {"sha256": digest, "core_schema_ids": env["core_schema_ids"], "records_checked": 0}
        val = V(env["schema"], registry=inv["registry"], format_checker=FC())
        for n, x, loc in items:
            if inv["schemas"][n]["$id"] in env["core_schema_ids"]:
                applied[label]["records_checked"] += 1
                for e in sorted(val.iter_errors(x), key=lambda e: [str(p) for p in e.path]):
                    errors.append((f"profile:{label}", f"{loc}/{pointer(e.path)}" if e.path else loc, e.message[:200]))
    unused = [k for k, v in applied.items() if v["records_checked"] == 0]
    return errors, applied, unused


def graph(bundle):
    """G01 to G10 on a structurally valid bundle whose within-record rules passed. Returns (errors, reviews, resolved edges, indexes)."""
    errors, review = [], []
    resolved = {f"{a}.{f}->{to}": 0 for a, f, to in EDGES + LINKED} | {"reports.benchmarkRef->benchmarks": 0}
    orgs, bench, maps = set(), {}, []
    for i, x in enumerate(bundle["benchmarks"]):
        key = (x["benchmarkId"], x["releaseVersion"])
        if key in bench: errors.append(("G02", f"benchmarks/{i}", f"duplicate benchmark release {key[0]!r} version {key[1]!r}"))
        else: bench[key] = x
    for gi, g in enumerate(bundle["organisations"]):
        org = g["organisation"]["orgId"]; loc = f"organisations/{gi}"
        if org in orgs: errors.append(("G02", loc, f"duplicate organisation group {org!r}"))
        orgs.add(org); idx = {k: {} for k in ENTITIES}
        for arr, (n, pk) in ENTITIES.items():
            for i, x in enumerate(g[arr]):
                path = f"{loc}/{arr}/{i}"
                if "orgId" in x and x["orgId"] != org: errors.append(("G01", path, f"{n}.orgId {x['orgId']!r} is not the enclosing organisation {org!r}"))
                if x[pk] in idx[arr]: errors.append(("G02", path, f"duplicate {n} {pk} {x[pk]!r} in organisation {org!r}"))
                else: idx[arr][x[pk]] = x
        maps.append(idx)
    if errors: return errors, review, resolved, maps            # never select an ambiguous owner, even when its content is equal
    for gi, (g, idx) in enumerate(zip(bundle["organisations"], maps)):
        org = g["organisation"]["orgId"]; loc = f"organisations/{gi}"
        def target(arr, x, field, to, i):
            if field not in x: return None
            found = idx[to].get(x[field])
            if found is None: errors.append(("G03", f"{loc}/{arr}/{i}/{field}", f"{field} {x[field]!r} does not resolve to a {ENTITIES[to][0]} in organisation {org!r}"))
            else: resolved[f"{arr}.{field}->{to}"] += 1
            return found
        for arr, field, to in EDGES:
            for i, x in enumerate(g[arr]): target(arr, x, field, to, i)
        for arr, field, to in LINKED:
            for i, x in enumerate(g[arr]):
                y = target(arr, x, field, to, i)
                if y is not None and y["pseudonymId"] != x["pseudonymId"]: errors.append(("G04", f"{loc}/{arr}/{i}/{field}", f"the linked {ENTITIES[to][0]} belongs to another worker"))
                if arr == "rtwOutcomes" and y is not None and "rtwDate" in x and date.fromisoformat(x["rtwDate"]) < date.fromisoformat(y["startDate"]): errors.append(("G06", f"{loc}/{arr}/{i}/rtwDate", f"rtwDate {x['rtwDate']} precedes the absence start {y['startDate']}"))
        done, cycles = set(), set()
        for start in sorted(idx["units"]):                                    # iterative walk over a single-parent forest; no recursion
            seen, trail, cur = {}, [], start
            while cur in idx["units"] and cur not in done:
                if cur in seen: cycles.add(tuple(sorted(trail[seen[cur]:]))); break
                seen[cur] = len(trail); trail.append(cur); cur = idx["units"][cur].get("parentUnitId")
            done.update(trail)
        for cyc in sorted(cycles): errors.append(("G05", loc + "/units", f"unit hierarchy cycle through {list(cyc)}"))
        when = date.fromisoformat(bundle["comparisonAsOfDate"])
        for i, x in enumerate(g["reports"]):
            br = x.get("benchmarkRef")
            if br is None: continue
            path = f"{loc}/reports/{i}/benchmarkRef"; r = bench.get((br["benchmarkId"], br["releaseVersion"]))
            if r is None: errors.append(("G07", path, f"no supplied release {br['benchmarkId']!r} version {br['releaseVersion']!r}; another version is never substituted")); continue
            resolved["reports.benchmarkRef->benchmarks"] += 1
            if r["measure"]["metricCode"] != x["metricCode"]: errors.append(("G08", path + "/metricCode", f"release metric {r['measure']['metricCode']!r} is not the report's {x['metricCode']!r}"))
            if r["leaveOneOut"] and r["excludedOrgId"] != org: errors.append(("G09", path + "/excludedOrgId", f"leave-one-out release excludes {r['excludedOrgId']!r}, not the referencing organisation {org!r}"))
            if not date.fromisoformat(r["validFrom"]) <= when <= date.fromisoformat(r["validTo"]): errors.append(("G10", path + "/comparisonAsOfDate", f"comparisonAsOfDate {when} is outside the release validity {r['validFrom']} to {r['validTo']}"))
            review.append(("comparison_not_established", path, "a matching metric code is declared identity, not comparability: population, sampling, time, method, unit and score equivalence are not established"))
    return errors, review, resolved, maps


def measurement_checks(bundle):
    """The S07 measurement-bundle checks, unchanged, on each organisation's projection. Returns (errors, reviews, external, gate)."""
    import check_measurement as cm
    gate = {"tool": "tools/check_measurement.py", "sha256": hashlib.sha256((ROOT / "tools" / "check_measurement.py").read_bytes()).hexdigest(), "groups_checked": 0}
    errors, review, external = [], [], {}
    for gi, g in enumerate(bundle["organisations"]):
        proj = {"schema_version": "0.2", "contexts": g["contexts"], "observations": g["observations"], "administrations": g["administrations"], "reports": g["reports"]}
        try: problems, rev, ext = cm.check(proj)
        except SystemExit as e: raise ToolError(f"measurement checker failed on organisations/{gi}: {e}")
        if not isinstance(problems, list) or not isinstance(rev, list) or not isinstance(ext, dict): raise ToolError(f"measurement checker returned a malformed result for organisations/{gi}")
        gate["groups_checked"] += 1
        errors += [("S07", f"organisations/{gi}", p) for p in problems]
        review += [("measurement_interpretation", f"organisations/{gi}", r) for r in rev]
        for k, v in ext.items():
            if k in ("pseudonymId", "unitId", "benchmarkRef"): continue           # resolved by this checker (G03, G07) when the graph stage ran
            if v: external.setdefault(k, set()).update(v)
    return errors, review, {k: sorted(v) for k, v in external.items()}, gate


def check(bundle_bytes, profiles=(), inv=None):
    """The whole check on the raw bytes of a bundle. Returns the report dict; raises ToolError for tool problems."""
    inv = inv or load_inventory()
    rep = {"report_schema_version": REPORT_SCHEMA_VERSION, "checker": "tools/check_entity_graph.py", "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "input_sha256": hashlib.sha256(bundle_bytes).hexdigest(), "schema_sha256": inv["hashes"], "comparisonAsOfDate": None, "state": None,
           "entity_counts": {}, "organisation_groups": 0, "resolved_links": {}, "checks_performed": [], "checks_not_evaluated": [], "errors": [], "review_items": [],
           "external_references_not_checked": {}, "profiles": {"applied": {}, "unused": []}, "not_established": NOT_ESTABLISHED, "statement": None}
    def finish(state, errors, review=(), performed=(), not_eval=()):
        rep["state"] = state; rep["errors"] = [{"rule": c, "pointer": p, "message": m} for c, p, m in errors]; rep["review_items"] = [{"kind": c, "pointer": p, "message": m} for c, p, m in review]
        rep["checks_performed"] = list(performed); rep["checks_not_evaluated"] = list(not_eval)
        rep["statement"] = SUCCESS if state == "checked_with_limits" else ("no record was supplied; nothing was exercised and nothing is certified" if state == "not_evaluated" else None)
        return rep
    try: bundle = loads_strict(bundle_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e: return finish("invalid", [("input", "", f"not strict JSON: {e}")], not_eval=["structure", "C1-C18", "profiles", "G01-G10", "S07"])
    struct = structural_errors(inv, bundle)
    if struct: return finish("invalid", struct, performed=["structure"], not_eval=["C1-C18", "profiles", "G01-G10", "S07"])
    rep["comparisonAsOfDate"] = bundle["comparisonAsOfDate"]; rep["organisation_groups"] = len(bundle["organisations"])
    items = records(bundle)
    counts = {n: 0 for n in ALL_ENTITIES}
    for n, _, _ in items: counts[n] += 1
    rep["entity_counts"] = counts; rep["entity_counts_note"] = "Crosswalk rows are declared mappings, not independent evidence; duplicate rows are repeated declarations"
    if not items: return finish("not_evaluated", [], performed=["structure"], not_eval=["C1-C18", "profiles", "G01-G10", "S07"])
    rules = rule_errors(items)
    perrs, applied, unused = profile_results(inv, profiles, items)
    rep["profiles"] = {"applied": applied, "unused": unused}
    # a namespace is checked only where a supplied profile of that id names the record's own schema; anywhere else its semantics are unchecked
    covered = {(lbl.split("@")[0], sid) for lbl, a in applied.items() for sid in a["core_schema_ids"]}
    ext_ns = sorted({k for n, x, _ in items if isinstance(x.get("ext"), dict) for k in x["ext"] if (k, inv["schemas"][n]["$id"]) not in covered})
    if ext_ns: rep["external_references_not_checked"]["extension_namespaces_without_a_supplied_profile"] = ext_ns
    if rules or perrs: return finish("invalid", rules + perrs, performed=["structure", "C1-C18", "profiles"], not_eval=["G01-G10", "S07"])
    gerrs, greview, resolved, _ = graph(bundle)
    rep["resolved_links"] = {k: (v if v else "not exercised: no declared edge") for k, v in resolved.items()}
    rep["external_references_not_checked"]["crosswalk_semantics"] = "ISO 45003 clauses, HSE domains and reserved WHIU strings are checked as syntax only"
    if gerrs:          # identity, scope or reference failures: the measurement joins would rest on ambiguous or unresolved records, so they are not evaluated
        return finish("invalid", gerrs, greview, performed=["structure", "C1-C18", "profiles", "G01-G10"], not_eval=["S07 measurement checks"])
    merrs, mreview, mext, gate = measurement_checks(bundle)
    rep["measurement_gate"] = gate
    for k, v in mext.items(): rep["external_references_not_checked"][k] = v
    errors = merrs; review = greview + mreview
    return finish("invalid" if errors else "checked_with_limits", errors, review, performed=["structure", "C1-C18", "profiles", "G01-G10", "S07 measurement checks"], not_eval=[])


def write_atomic(path, text):
    tmp = Path(str(path) + ".tmp"); tmp.write_text(text, encoding="utf-8"); os.replace(tmp, path)


def main(argv):
    if "--self-test" in argv: return self_test()
    profiles, out, rest = [], None, list(argv)
    while "--profile" in rest:
        k = rest.index("--profile")
        if k + 1 >= len(rest): print(json.dumps({"state": "tool_error", "error": "--profile needs a path"})); return 2
        profiles.append(rest[k + 1]); del rest[k:k + 2]
    if "--out" in rest:
        k = rest.index("--out")
        if k + 1 >= len(rest): print(json.dumps({"state": "tool_error", "error": "--out needs a path"})); return 2
        out = Path(rest[k + 1]); del rest[k:k + 2]
    if len(rest) != 1: print(json.dumps({"state": "tool_error", "error": "usage: check_entity_graph.py BUNDLE.json [--profile P.json ...] [--out REPORT.json]"})); return 2
    try:
        try: data = Path(rest[0]).read_bytes()
        except OSError as e: raise ToolError(f"bundle {rest[0]}: {e}")
        rep = check(data, profiles)
    except ToolError as e:
        rep = {"report_schema_version": REPORT_SCHEMA_VERSION, "state": "tool_error", "error": str(e), "statement": None}
    text = json.dumps(rep, indent=1, ensure_ascii=False) + "\n"
    if out is not None: write_atomic(out, text)
    print(text)
    return {"checked_with_limits": 0, "not_evaluated": 0, "invalid": 1, "tool_error": 2}[rep["state"]]


def self_test():
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else str(detail)[:300]); failures += not ok
    here = Path(__file__).resolve()
    def cli(obj_or_text, *extra, tmpdir):
        p = Path(tmpdir) / f"b{len(list(Path(tmpdir).iterdir()))}.json"
        p.write_text(obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, "-B", str(here), str(p), *extra], capture_output=True, text=True)
        try: rep = json.loads(r.stdout)
        except ValueError: rep = None
        return r.returncode, rep, r.stderr
    codes = lambda rep: sorted(e["rule"] for e in rep["errors"]) if rep else None
    pairs = lambda rep: sorted((e["rule"], e["pointer"]) for e in rep["errors"]) if rep else None
    valid = json.loads((EXAMPLES / "EntityGraph.valid.json").read_text(encoding="utf-8"))
    manifest = json.loads((EXAMPLES / "cases.manifest.json").read_text(encoding="utf-8"))["cases"]
    with tempfile.TemporaryDirectory() as tmp:
        rc, rep, err = cli(valid, tmpdir=tmp)
        t("the committed valid graph: exit 0, checked_with_limits, sixteen shapes present, no error, one comparison review item, both stages ran", rc == 0 and rep["state"] == "checked_with_limits" and all(rep["entity_counts"][n] >= 1 for n in ALL_ENTITIES) and not rep["errors"] and [r["kind"] for r in rep["review_items"]] == ["comparison_not_established"] and "S07 measurement checks" in rep["checks_performed"] and rep["measurement_gate"]["groups_checked"] == 1, (rc, rep and rep["state"], rep and rep["errors"][:2], err[-200:]))
        t("the valid graph's statement is the exact success wording and its limits are listed", rep["statement"] == SUCCESS and len(rep["not_established"]) == len(NOT_ESTABLISHED))
        t("resolved links are counted per relation and a relation without an edge reads not exercised", rep["resolved_links"]["reports.benchmarkRef->benchmarks"] == 1 and rep["resolved_links"]["absences.pseudonymId->workers"] == 1 and any(v == "not exercised: no declared edge" for v in rep["resolved_links"].values()))
        # the 64 prototype cases through the real command line: code multisets and pointers
        n_cases = 0
        for c in manifest:
            bundle = json.loads((EXAMPLES / c["file"]).read_text(encoding="utf-8"))
            rc, rep, err = cli(bundle, tmpdir=tmp); n_cases += 1
            want_codes = sorted(c["expected_codes"]); got_codes = codes(rep)
            ok = rep is not None and got_codes == want_codes and "Traceback" not in err and (rc == 1 if want_codes else rc == 0)
            if ok and c["expected_errors"]: ok = pairs(rep) == sorted((e[0], e[1]) for e in c["expected_errors"])
            if ok and want_codes and any(x.startswith("schema:") or x.startswith("C") for x in want_codes): ok = "G01-G10" in rep["checks_not_evaluated"] and rep["statement"] is None
            t(f"case {c['case']}: codes {want_codes}", ok, (rc, got_codes, pairs(rep) if rep else None, err[-160:]))
        t("all sixty-four prototype cases ran", n_cases == 64, n_cases)
        empty = {"schema_version": "0.2", "comparisonAsOfDate": "2026-09-01", "organisations": [], "benchmarks": [], "crosswalks": []}
        rc, rep, err = cli(empty, tmpdir=tmp); t("an explicitly empty inventory is not_evaluated with exit 0 and no certificate", rc == 0 and rep["state"] == "not_evaluated" and rep["statement"] != SUCCESS and "G01-G10" in rep["checks_not_evaluated"])
        # strict input: duplicate keys at depth, non-finite and overflowing numbers, roots
        rc, rep, err = cli('{"schema_version": "0.2", "comparisonAsOfDate": "2026-09-01", "organisations": [], "benchmarks": [], "crosswalks": [], "crosswalks": []}', tmpdir=tmp)
        t("duplicate root keys are refused before any dictionary is built", rc == 1 and rep["state"] == "invalid" and "duplicate object key" in rep["errors"][0]["message"])
        dup_nested = json.dumps(valid)[:-1]  # append a duplicate key inside the first organisation
        txt = json.dumps(valid).replace('"orgId": "org-demo", "country"', '"orgId": "org-demo", "orgId": "org-demo", "country"', 1)
        rc, rep, err = cli(txt, tmpdir=tmp); t("a duplicate nested organisation id key is refused", rc == 1 and "duplicate object key" in rep["errors"][0]["message"])
        for lit in ("NaN", "Infinity", "1e400"):
            txt = json.dumps(valid).replace('"workingDaysLost": 10', f'"workingDaysLost": {lit}', 1)
            rc, rep, err = cli(txt, tmpdir=tmp); t(f"{lit} in a count is refused as not strict JSON, no traceback", rc == 1 and rep["state"] == "invalid" and "Traceback" not in err, (rc, rep and rep["errors"][:1]))
        b = copy.deepcopy(valid); b["organisations"][0]["utilisations"][0]["n"] = True
        rc, rep, err = cli(b, tmpdir=tmp); t("a boolean used as a count is a schema type error", rc == 1 and codes(rep) == ["schema:type"])
        b = copy.deepcopy(valid); b["organisations"][0]["absences"][0]["startDate"] = "0000-01-01"
        rc, rep, err = cli(b, tmpdir=tmp); t("a year-zero date is a format error", rc == 1 and codes(rep) == ["schema:format"])
        b = copy.deepcopy(valid); b["comparisonAsOfDate"] = "2026-13-40"
        rc, rep, err = cli(b, tmpdir=tmp); t("a malformed comparison date is a format error at the root", rc == 1 and pairs(rep) == [("schema:format", "comparisonAsOfDate")])
        for name in ("organisations", "benchmarks", "crosswalks"):
            b = copy.deepcopy(valid); del b[name]; rc, rep, err = cli(b, tmpdir=tmp); t(f"missing envelope array {name} is refused", rc == 1 and codes(rep) == ["schema:required"])
        b = copy.deepcopy(valid); b["extra"] = 1; rc, rep, err = cli(b, tmpdir=tmp); t("an extra root key cannot smuggle an alternate inventory", rc == 1 and codes(rep) == ["schema:additionalProperties"])
        b = copy.deepcopy(valid); b["organisations"][0]["units"] = {}; rc, rep, err = cli(b, tmpdir=tmp); t("a wrong nested type is a schema error, no traceback", rc == 1 and codes(rep) == ["schema:type"] and "Traceback" not in err)
        # S07 preservation: the measurement checks run unchanged on the projection
        b = copy.deepcopy(valid); del b["organisations"][0]["contexts"][0]["scoringDescriptor"]["normalisation"]
        rc, rep, err = cli(b, tmpdir=tmp); t("S07: a normalised value without a declared normalisation is an S07 error through the graph checker", rc == 1 and "S07" in codes(rep), (rc, codes(rep)))
        b = copy.deepcopy(valid); b["organisations"][0]["observations"][0]["occasionTs"] = "2030-01-01T00:00:00Z"
        rc, rep, err = cli(b, tmpdir=tmp); t("S07: an occasion outside the context window is an S07 error", rc == 1 and "S07" in codes(rep), (rc, codes(rep), rep and rep["errors"][:1]))
        b = copy.deepcopy(valid); b["organisations"][0]["reports"][0]["periodStart"] = b["organisations"][0]["reports"][0]["periodEnd"]
        rc, rep, err = cli(b, tmpdir=tmp); t("S07: a narrower report period is a measurement review item, not an error", rc == 0 and any(r["kind"] == "measurement_interpretation" for r in rep["review_items"]), (rc, rep and rep["review_items"][:2]))
        # profiles through the real validator classes
        prof = ROOT / "profiles" / "owhs-example" / "0.1.0.json"
        rc, rep, err = cli(valid, "--profile", str(prof), tmpdir=tmp); t("a supplied profile applies to every record of its declared entity: the absence without the required namespace fails it through the real validator", rc == 1 and rep["profiles"]["applied"]["owhs-example@0.1.0"]["records_checked"] == 1 and any(e["rule"] == "profile:owhs-example@0.1.0" and e["pointer"].startswith("organisations/0/absences/0") for e in rep["errors"]), (rc, rep and rep["profiles"], rep and rep["errors"][:1]))
        xw = json.loads(prof.read_text(encoding="utf-8")); xw["core_schema_ids"] = ["https://openworkplacehealth.org/schemas/v0.2/Crosswalk.json"]; (Path(tmp) / "xwprof.json").write_text(json.dumps(xw), encoding="utf-8")
        b = copy.deepcopy(valid); b["crosswalks"] = []
        rc, rep, err = cli(b, "--profile", str(Path(tmp) / "xwprof.json"), tmpdir=tmp); t("a valid profile that matches no supplied record is reported unused, not passed", rc == 0 and rep["profiles"]["unused"] == ["owhs-example@0.1.0"] and rep["profiles"]["applied"]["owhs-example@0.1.0"]["records_checked"] == 0, (rc, rep and rep["profiles"]))
        b = copy.deepcopy(valid); b["organisations"][0]["absences"][0]["ext"] = {"owhs-example": {"wave": 3}}
        rc, rep, err = cli(b, "--profile", str(prof), tmpdir=tmp); t("a valid profile applied to its declared entity checks the record and passes", rc == 0 and rep["profiles"]["applied"]["owhs-example@0.1.0"]["records_checked"] == 1 and not rep["profiles"]["unused"], (rc, rep and rep["profiles"], rep and rep["errors"][:1]))
        b = copy.deepcopy(valid); b["organisations"][0]["absences"][0]["ext"] = {"owhs-example": {"wave": "three"}}
        rc, rep, err = cli(b, "--profile", str(prof), tmpdir=tmp); t("an applicable failing profile refuses through the real validator", rc == 1 and any(e["rule"].startswith("profile:owhs-example") for e in rep["errors"]), (rc, rep and rep["errors"][:1]))
        b = copy.deepcopy(valid); b["organisations"][0]["absences"][0]["ext"] = {"owhs-example": {"wave": 3}}
        rc, rep, err = cli(b, tmpdir=tmp); t("an extension namespace with no supplied profile is listed as unchecked", rc == 0 and rep["external_references_not_checked"].get("extension_namespaces_without_a_supplied_profile") == ["owhs-example"])
        rc, rep, err = cli(valid, "--profile", str(Path(tmp) / "absent-profile.json"), tmpdir=tmp); t("a missing profile file is a tool error (exit 2)", rc == 2 and rep["state"] == "tool_error")
        (Path(tmp) / "badprof.json").write_text('{"profile_id": "x"}', encoding="utf-8")
        rc, rep, err = cli(valid, "--profile", str(Path(tmp) / "badprof.json"), tmpdir=tmp); t("a malformed profile envelope is a tool error", rc == 2 and "malformed" in rep["error"])
        b = copy.deepcopy(valid); b["crosswalks"] = []; b["organisations"][0]["absences"][0]["ext"] = {"owhs-example": {"wave": "three"}}
        rc, rep, err = cli(b, "--profile", str(Path(tmp) / "xwprof.json"), tmpdir=tmp); t("a profile targeting another entity does not check the absence carrying its namespace; the namespace is listed as unchecked and the profile as unused", rc == 0 and not rep["errors"] and rep["profiles"]["unused"] == ["owhs-example@0.1.0"] and rep["external_references_not_checked"].get("extension_namespaces_without_a_supplied_profile") == ["owhs-example"], (rc, rep and rep["errors"][:1], rep and rep["external_references_not_checked"]))
        # identity and scope
        b = copy.deepcopy(valid); b["organisations"][0]["disabilityParticipations"][0]["reportId"] = b["organisations"][0]["reports"][0]["reportId"]
        rc, rep, err = cli(b, tmpdir=tmp); t("the same primary string in two different entity types is valid", rc == 0 and not rep["errors"], (rc, codes(rep)))
        b = copy.deepcopy(valid); b["crosswalks"].append(copy.deepcopy(b["crosswalks"][0]))
        rc, rep, err = cli(b, tmpdir=tmp); t("an exact duplicate crosswalk row is valid, counted as a repeated declaration, and invents no id", rc == 0 and rep["entity_counts"]["Crosswalk"] == 2)
        b = copy.deepcopy(valid); b["organisations"][0]["units"][0]["parentUnitId"] = ""
        rc, rep, err = cli(b, tmpdir=tmp); t("an empty present optional reference fails resolution or shape; it is never an unresolved-empty-target pass", rc == 1, (rc, codes(rep)))
        b = copy.deepcopy(valid); b["organisations"][0]["units"] += [{"unitId": "u2", "orgId": "org-demo", "parentUnitId": "u3", "headcountBand": "10-19", "headcountReferenceDate": "2026-09-01"}, {"unitId": "u3", "orgId": "org-demo", "parentUnitId": "u4", "headcountBand": "10-19", "headcountReferenceDate": "2026-09-01"}, {"unitId": "u4", "orgId": "org-demo", "parentUnitId": "u2", "headcountBand": "10-19", "headcountReferenceDate": "2026-09-01"}]
        rc, rep, err = cli(b, tmpdir=tmp); t("a three-unit cycle is G05", rc == 1 and codes(rep) == ["G05"], (rc, codes(rep)))
        b = copy.deepcopy(valid); units = [{"unitId": f"chain-{i}", "orgId": "org-demo", "headcountBand": "10-19", "headcountReferenceDate": "2026-09-01", **({"parentUnitId": f"chain-{i - 1}"} if i else {})} for i in range(1201)]
        b["organisations"][0]["units"] += units; rc, rep, err = cli(b, tmpdir=tmp); t("a 1,201-unit acyclic chain passes without recursion", rc == 0 and rep["resolved_links"]["units.parentUnitId->units"] == 1200, (rc, codes(rep), err[-120:]))
        # tool errors: a missing entity schema
        import shutil
        with tempfile.TemporaryDirectory() as fake:
            shutil.copytree(ROOT / "tools", Path(fake) / "tools"); shutil.copytree(ROOT / "schemas", Path(fake) / "schemas"); shutil.copytree(ROOT / "profiles", Path(fake) / "profiles")
            (Path(fake) / "schemas" / "v0.2" / "Crosswalk.json").unlink()
            bp = Path(fake) / "b.json"; bp.write_text(json.dumps(valid), encoding="utf-8")
            r = subprocess.run([sys.executable, "-B", str(Path(fake) / "tools" / "check_entity_graph.py"), str(bp)], capture_output=True, text=True)
            t("a missing entity schema is a tool error (exit 2), never a pass", r.returncode == 2 and '"tool_error"' in r.stdout and "Traceback" not in r.stderr, (r.returncode, r.stdout[-200:], r.stderr[-200:]))
        # --out is atomic and carries the failed state
        outp = Path(tmp) / "report.json"; outp.write_text('{"state": "checked_with_limits", "stale": true}', encoding="utf-8")
        b = copy.deepcopy(valid); b["organisations"][0]["workers"][0]["orgId"] = "org-other"
        rc, rep, err = cli(b, "--out", str(outp), tmpdir=tmp); written = json.loads(outp.read_text(encoding="utf-8"))
        t("--out replaces a stale success report with the current invalid result", rc == 1 and written["state"] == "invalid" and "stale" not in written)
        rc, rep, err = cli("{not json", tmpdir=tmp); t("unparseable input is invalid with a diagnostic, no traceback", rc == 1 and rep["state"] == "invalid" and "Traceback" not in err)
    print(f"{'all' if not failures else failures} entity-graph checks {'passed' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
