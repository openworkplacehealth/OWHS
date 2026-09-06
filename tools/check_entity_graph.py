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


def load_config_json(path, what):
    """A configuration file (schema, envelope, profile): unreadable or not strict JSON is a tool error naming the path."""
    try: return loads_strict(Path(path).read_text(encoding="utf-8"))
    except OSError as e: raise ToolError(f"{what} {path}: {e}")
    except (UnicodeDecodeError, ValueError) as e: raise ToolError(f"{what} {path} is not strict JSON: {e}")


def load_validator():
    """The shared single-record validator (tools/validate.py) through an explicit error boundary; its absence or failure to import is a tool error."""
    vp = ROOT / "tools" / "validate.py"
    if not vp.exists(): raise ToolError("shared validator tools/validate.py is missing; the within-record rules and preflight cannot run")
    try: import validate as v
    except (ImportError, SyntaxError, SystemExit, Exception) as e: raise ToolError(f"shared validator tools/validate.py could not be loaded: {type(e).__name__}: {str(e)[:120]}")
    for name in ("CROSS_FIELD_RULES", "formats_used", "refs_used", "resolve_local"):
        if not hasattr(v, name): raise ToolError(f"shared validator tools/validate.py lacks {name}; a different file stands where the validator is expected")
    return v, hashlib.sha256(vp.read_bytes()).hexdigest()


def preflight_problems(V, v, checker_formats, schema, what, inventory_ids=None):
    """The accepted S06 preflight, without exiting: meta-validity, every format asserted by this installation, and every reference
    (used branches and unused alike) resolving locally, or, for the entity-graph envelope, to a schema in the checked local inventory.
    Nothing is fetched. Returns a list of named problems."""
    from urllib.parse import urldefrag, urljoin
    p = []
    try: V.check_schema(schema)
    except Exception as e: p.append(f"{what} is not a valid draft 2020-12 schema: {str(e)[:120]}")
    unenforceable = sorted(set(v.formats_used(schema)) - set(checker_formats))
    if unenforceable: p.append(f"{what} uses formats this installation cannot assert: {', '.join(unenforceable)}; a pass would overstate what was checked")
    base = schema.get("$id", "") if isinstance(schema, dict) and isinstance(schema.get("$id"), str) else ""
    def in_inventory(ref):
        target, frag = urldefrag(urljoin(base, ref))
        if not inventory_ids or target not in inventory_ids: return False
        if frag == "": return True
        if frag.startswith("/"): return v.pointer_resolves(inventory_ids[target], frag)
        return frag in set(v.anchors(inventory_ids[target]))
    for ref in sorted(set(v.refs_used(schema))):
        if v.resolve_local(schema, ref) or in_inventory(ref): continue
        p.append(f"{what} carries a reference that does not resolve locally (nothing is fetched): {ref}")
    return p


def load_inventory():
    """The complete local configuration, preflighted before any record is judged: the envelope, the sixteen entity schemas and the
    profile-envelope schema, each strict JSON, meta-valid, with only asserted formats and only local or inventory-resolvable references.
    Anything missing, malformed or unresolvable is a tool error naming the path."""
    try:
        from jsonschema.validators import Draft202012Validator as V
        from jsonschema import FormatChecker
        from referencing import Registry, Resource
    except ImportError as e: raise ToolError(f"dependency missing: {e}")
    v, vhash = load_validator()
    checker_formats = set(FormatChecker().checkers)
    if not ENVELOPE.exists(): raise ToolError(f"envelope schema missing: {ENVELOPE.relative_to(ROOT)}")
    if not PROFILE_ENVELOPE.exists(): raise ToolError(f"profile-envelope schema missing: {PROFILE_ENVELOPE.relative_to(ROOT)}")
    schemas, hashes = {}, {}
    for n in ALL_ENTITIES:
        sp = SCHEMA_DIR / f"{n}.json"
        if not sp.exists(): raise ToolError(f"entity schema missing: {sp.relative_to(ROOT)}")
        schemas[n] = load_config_json(sp, "entity schema"); hashes[f"schemas/v0.2/{n}.json"] = hashlib.sha256(sp.read_bytes()).hexdigest()
    env = load_config_json(ENVELOPE, "envelope schema"); hashes[str(ENVELOPE.relative_to(ROOT))] = hashlib.sha256(ENVELOPE.read_bytes()).hexdigest()
    penv = load_config_json(PROFILE_ENVELOPE, "profile-envelope schema")
    ids = {}
    for n, sc in schemas.items():
        if not isinstance(sc, dict) or not isinstance(sc.get("$id"), str): raise ToolError(f"entity schema schemas/v0.2/{n}.json has no string $id")
        ids[sc["$id"]] = sc
    problems = []
    for n, sc in schemas.items(): problems += preflight_problems(V, v, checker_formats, sc, f"entity schema schemas/v0.2/{n}.json")
    problems += preflight_problems(V, v, checker_formats, env, f"envelope schema {ENVELOPE.relative_to(ROOT)}", inventory_ids=ids)
    problems += preflight_problems(V, v, checker_formats, penv, f"profile-envelope schema {PROFILE_ENVELOPE.relative_to(ROOT)}")
    if problems: raise ToolError("configuration preflight failed: " + "; ".join(problems[:4]))
    def refuse(uri): raise ToolError(f"schema reference {uri!r} is not in the local inventory; network retrieval is not performed")
    reg = Registry(retrieve=refuse).with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    mp = ROOT / "tools" / "check_measurement.py"
    deps = {"tools/validate.py": vhash, "tools/check_measurement.py": hashlib.sha256(mp.read_bytes()).hexdigest() if mp.exists() else None,
            str(PROFILE_ENVELOPE.relative_to(ROOT)): hashlib.sha256(PROFILE_ENVELOPE.read_bytes()).hexdigest()}
    if deps["tools/check_measurement.py"] is None: raise ToolError("measurement checker tools/check_measurement.py is missing; the retained S07 checks cannot run")
    return {"V": V, "FormatChecker": FormatChecker, "validate": v, "checker_formats": checker_formats, "schemas": schemas, "envelope": env, "registry": reg, "profile_envelope": penv, "hashes": hashes, "dependency_hashes": deps}


# ---- RFC 6901 pointers: "" is the root; every token is escaped (~ to ~0, / to ~1) and locates an existing value or the nearest existing parent ----
def esc(tok): return str(tok).replace("~", "~0").replace("/", "~1")
def P(*parts): return "".join("/" + esc(t) for t in parts)
def pointer(path): return P(*path)


def resolve_pointer(doc, ptr):
    """The value an RFC 6901 pointer locates in doc, or a sentinel when it locates nothing."""
    node = doc
    if ptr == "": return node
    if not ptr.startswith("/"): return _MISSING
    for tok in ptr[1:].split("/"):
        tok = tok.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and tok in node: node = node[tok]
        elif isinstance(node, list) and tok.isdigit() and int(tok) < len(node): node = node[int(tok)]
        else: return _MISSING
    return node
_MISSING = object()


def structural_errors(inv, bundle):
    """Envelope and every record against its exact schema, formats asserted: (code, pointer, message)."""
    V, FC = inv["V"], inv["FormatChecker"]
    try: errs = sorted(V(inv["envelope"], registry=inv["registry"], format_checker=FC()).iter_errors(bundle), key=lambda e: [str(x) for x in e.path])
    except Exception as e: raise ToolError(f"the envelope schema could not be applied: {str(e)[:160]}")
    return [(f"schema:{e.validator}", pointer(e.path), e.message[:200]) for e in errs]


def records(bundle):
    """(entity, record, pointer) for every record in a structurally valid bundle."""
    items = [("BenchmarkRelease", x, P("benchmarks", i)) for i, x in enumerate(bundle["benchmarks"])] + [("Crosswalk", x, P("crosswalks", i)) for i, x in enumerate(bundle["crosswalks"])]
    for gi, g in enumerate(bundle["organisations"]):
        items.append(("Organisation", g["organisation"], P("organisations", gi, "organisation")))
        for arr, (n, pk) in ENTITIES.items(): items.extend((n, x, P("organisations", gi, arr, i)) for i, x in enumerate(g[arr]))
    return items


def rule_errors(inv, items):
    """C1 to C18 from tools/validate.py, the same functions the single-record validator runs."""
    v = inv["validate"]
    out = []
    for n, x, loc in items:
        for code, fn in v.CROSS_FIELD_RULES.get(n, []):
            try: msg = fn(x)
            except (TypeError, AttributeError, KeyError, ValueError) as e: raise ToolError(f"rule {code} failed on a structurally valid record at {loc}: {e!r}")
            if msg: out.append((code, loc, msg))
    return out


def load_profiles(inv, profiles):
    """Every supplied profile, before any record is judged: strict JSON, valid against the profile envelope, one envelope per id and
    version, and its schema preflighted with the S06 contract (meta-valid, asserted formats, references resolving locally including
    embedded resources, unused branches included). Returns {label: {sha256, core_schema_ids, schema, records_checked: 0}}."""
    V, FC, v = inv["V"], inv["FormatChecker"], inv["validate"]
    seen, applied = {}, {}
    for path in profiles:
        env = load_config_json(path, "profile")
        bad = list(V(inv["profile_envelope"], format_checker=FC()).iter_errors(env))
        if bad: raise ToolError(f"profile envelope {path} is malformed: " + "; ".join(e.message[:80] for e in bad[:3]))
        key = (env["profile_id"], env["version"])
        if key in seen and seen[key] != env: raise ToolError(f"two different envelopes supplied for profile {key[0]} {key[1]}")
        seen[key] = env
        problems = preflight_problems(V, v, inv["checker_formats"], env["schema"], f"profile {key[0]} {key[1]} schema")
        if problems: raise ToolError("profile preflight failed: " + "; ".join(problems[:3]))
        try: val = V(env["schema"], format_checker=FC()); val.check_schema(env["schema"])
        except Exception as e: raise ToolError(f"profile {key[0]} {key[1]} schema cannot be applied: {str(e)[:100]}")
        applied[f"{key[0]}@{key[1]}"] = {"sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "core_schema_ids": env["core_schema_ids"], "records_checked": 0, "_schema": env["schema"]}
    return applied


def profile_results(inv, applied, items):
    """Supplied profiles dispatched only to records whose exact schema $id they name, run with the real validator classes; errors,
    coverage and unused profiles. Pointers are the record's pointer extended by the error's own path."""
    V, FC = inv["V"], inv["FormatChecker"]
    errors = []
    for label, a in applied.items():
        val = V(a["_schema"], format_checker=FC())
        for n, x, loc in items:
            if inv["schemas"][n]["$id"] in a["core_schema_ids"]:
                a["records_checked"] += 1
                for e in sorted(val.iter_errors(x), key=lambda e: [str(p) for p in e.path]):
                    try: loc_e = loc + pointer(e.path)
                    except Exception: loc_e = loc
                    errors.append((f"profile:{label}", loc_e, e.message[:200]))
    unused = [k for k, a in applied.items() if a["records_checked"] == 0]
    public = {k: {kk: vv for kk, vv in a.items() if kk != "_schema"} for k, a in applied.items()}
    return errors, public, unused


RELATIONS = [(a, f, to) for a, f, to in EDGES + LINKED] + [("reports", "benchmarkRef", "benchmarks")]


def declared_edges(bundle):
    """Occurrences of each scoped reference field in the supplied records (declared edges): counts of references, not of people or evidence."""
    out = {f"{a}.{f}->{to}": 0 for a, f, to in RELATIONS}
    for g in bundle["organisations"]:
        for a, f, to in RELATIONS:
            out[f"{a}.{f}->{to}"] += sum(1 for x in g[a] if f in x and x[f] is not None)
    return out


def graph(bundle):
    """G01 to G10 on a structurally valid bundle whose within-record rules passed. Returns (errors, reviews, resolved edges, stage) where
    stage is 'identity' when G01/G02 failed (G03 to G10 were not attempted) or 'complete'."""
    errors, review = [], []
    resolved = {k: 0 for k in declared_edges(bundle)}
    orgs, bench, bench_index, maps = set(), {}, {}, []
    for i, x in enumerate(bundle["benchmarks"]):
        key = (x["benchmarkId"], x["releaseVersion"])
        if key in bench: errors.append(("G02", P("benchmarks", i), f"duplicate benchmark release {key[0]!r} version {key[1]!r}"))
        else: bench[key] = x; bench_index[key] = i
    for gi, g in enumerate(bundle["organisations"]):
        org = g["organisation"]["orgId"]
        if org in orgs: errors.append(("G02", P("organisations", gi, "organisation", "orgId"), f"duplicate organisation group {org!r}"))
        orgs.add(org); idx = {k: {} for k in ENTITIES}
        for arr, (n, pk) in ENTITIES.items():
            for i, x in enumerate(g[arr]):
                if "orgId" in x and x["orgId"] != org: errors.append(("G01", P("organisations", gi, arr, i, "orgId"), f"{n}.orgId {x['orgId']!r} is not the enclosing organisation {org!r}"))
                if x[pk] in idx[arr]: errors.append(("G02", P("organisations", gi, arr, i, pk), f"duplicate {n} {pk} {x[pk]!r} in organisation {org!r}"))
                else: idx[arr][x[pk]] = x
        maps.append(idx)
    if errors: return errors, review, resolved, "identity"            # never select an ambiguous owner, even when its content is equal
    for gi, (g, idx) in enumerate(zip(bundle["organisations"], maps)):
        org = g["organisation"]["orgId"]
        def target(arr, x, field, to, i):
            if field not in x: return None
            found = idx[to].get(x[field])
            if found is None: errors.append(("G03", P("organisations", gi, arr, i, field), f"{field} {x[field]!r} does not resolve to a {ENTITIES[to][0]} in organisation {org!r}"))
            else: resolved[f"{arr}.{field}->{to}"] += 1
            return found
        for arr, field, to in EDGES:
            for i, x in enumerate(g[arr]): target(arr, x, field, to, i)
        for arr, field, to in LINKED:
            for i, x in enumerate(g[arr]):
                y = target(arr, x, field, to, i)
                if y is not None and y["pseudonymId"] != x["pseudonymId"]: errors.append(("G04", P("organisations", gi, arr, i, field), f"the linked {ENTITIES[to][0]} belongs to another worker"))
                if arr == "rtwOutcomes" and y is not None and "rtwDate" in x and date.fromisoformat(x["rtwDate"]) < date.fromisoformat(y["startDate"]): errors.append(("G06", P("organisations", gi, arr, i, "rtwDate"), f"rtwDate {x['rtwDate']} precedes the absence start {y['startDate']}"))
        done, cycles = set(), set()
        for start in sorted(idx["units"]):                                    # iterative walk over a single-parent forest; no recursion
            seen, trail, cur = {}, [], start
            while cur in idx["units"] and cur not in done:
                if cur in seen: cycles.add(tuple(sorted(trail[seen[cur]:]))); break
                seen[cur] = len(trail); trail.append(cur); cur = idx["units"][cur].get("parentUnitId")
            done.update(trail)
        for cyc in sorted(cycles): errors.append(("G05", P("organisations", gi, "units"), f"unit hierarchy cycle through {list(cyc)}"))
        when = date.fromisoformat(bundle["comparisonAsOfDate"])
        for i, x in enumerate(g["reports"]):
            br = x.get("benchmarkRef")
            if br is None: continue
            ref_ptr = P("organisations", gi, "reports", i, "benchmarkRef"); key = (br["benchmarkId"], br["releaseVersion"]); r = bench.get(key)
            if r is None: errors.append(("G07", ref_ptr, f"no supplied release {br['benchmarkId']!r} version {br['releaseVersion']!r}; another version is never substituted")); continue
            resolved["reports.benchmarkRef->benchmarks"] += 1; rel_ptr = P("benchmarks", bench_index[key]); related = [ref_ptr, rel_ptr]
            if r["measure"]["metricCode"] != x["metricCode"]: errors.append(("G08", P("organisations", gi, "reports", i, "metricCode"), f"release metric {r['measure']['metricCode']!r} is not the report's {x['metricCode']!r}", related))
            if r["leaveOneOut"] and r.get("excludedOrgId") != org: errors.append(("G09", rel_ptr + ("/excludedOrgId" if "excludedOrgId" in r else ""), f"leave-one-out release excludes {r.get('excludedOrgId')!r}, not the referencing organisation {org!r}", related))
            if not date.fromisoformat(r["validFrom"]) <= when <= date.fromisoformat(r["validTo"]): errors.append(("G10", P("comparisonAsOfDate"), f"comparisonAsOfDate {when} is outside the release validity {r['validFrom']} to {r['validTo']}", related))
            review.append(("comparison_not_established", ref_ptr, "a matching metric code is declared identity, not comparability: population, sampling, time, method, unit and score equivalence are not established"))
    return errors, review, resolved, "complete"


def measurement_checks(bundle):
    """The S07 measurement-bundle checks, unchanged, on each organisation's projection, through an explicit error boundary: a missing or
    unloadable checker, a raised exception or SystemExit, or a result that is not (list, list, dict) is a tool error, never an empty result."""
    mp = ROOT / "tools" / "check_measurement.py"
    if not mp.exists(): raise ToolError("measurement checker tools/check_measurement.py is missing; the retained S07 checks cannot run")
    try: import check_measurement as cm
    except (ImportError, SyntaxError, SystemExit, Exception) as e: raise ToolError(f"measurement checker tools/check_measurement.py could not be loaded: {type(e).__name__}: {str(e)[:120]}")
    if not callable(getattr(cm, "check", None)): raise ToolError("measurement checker tools/check_measurement.py has no check() function")
    gate = {"tool": "tools/check_measurement.py", "sha256": hashlib.sha256(mp.read_bytes()).hexdigest(), "groups_checked": 0}
    errors, review, external = [], [], {}
    for gi, g in enumerate(bundle["organisations"]):
        proj = {"schema_version": "0.2", "contexts": g["contexts"], "observations": g["observations"], "administrations": g["administrations"], "reports": g["reports"]}
        try: result = cm.check(proj)
        except SystemExit as e: raise ToolError(f"measurement checker exited on organisations/{gi}: {e}")
        except Exception as e: raise ToolError(f"measurement checker raised on organisations/{gi}: {type(e).__name__}: {str(e)[:120]}")
        if not isinstance(result, (tuple, list)) or len(result) != 3: raise ToolError(f"measurement checker returned a malformed result for organisations/{gi}: expected (problems, reviews, external)")
        problems, rev, ext = result
        if not isinstance(problems, list) or not isinstance(rev, list) or not isinstance(ext, dict) or not all(isinstance(x, str) for x in problems + rev): raise ToolError(f"measurement checker returned a malformed result for organisations/{gi}: problems and reviews must be lists of strings and external a dict")
        gate["groups_checked"] += 1
        errors += [("S07", P("organisations", gi), p_) for p_ in problems]
        review += [("measurement_interpretation", P("organisations", gi), r_) for r_ in rev]
        for k, v in ext.items():
            if k in ("pseudonymId", "unitId", "benchmarkRef"): continue           # resolved by this checker (G03, G07) when the graph stage ran
            if v: external.setdefault(k, set()).update(v)
    return errors, review, {k: sorted(v) for k, v in external.items()}, gate


def relation_records(declared, resolved, stage):
    """One record per relation: declared occurrences, resolved, unresolved and the state of the resolution stage."""
    out = {}
    for k, d in declared.items():
        if stage is None: out[k] = {"declared": d, "resolved": None, "unresolved": None, "state": "not_evaluated", "reason": "reference resolution was not reached"}
        elif stage == "identity": out[k] = {"declared": d, "resolved": None, "unresolved": None, "state": "not_evaluated", "reason": "identities invalid (G01/G02); resolution not attempted"}
        elif d == 0: out[k] = {"declared": 0, "resolved": 0, "unresolved": 0, "state": "no_declared_edge", "reason": "no record carries this reference; nothing exercised"}
        else: out[k] = {"declared": d, "resolved": resolved.get(k, 0), "unresolved": d - resolved.get(k, 0), "state": "evaluated", "reason": None}
    return out


def check(bundle_bytes, profiles=(), inv=None):
    """The whole check on the raw bytes of a bundle. Returns the report dict; raises ToolError for tool problems."""
    inv = inv or load_inventory()
    applied = load_profiles(inv, profiles)                       # the complete supplied configuration is validated before any record, and before an empty-inventory return
    rep = {"report_schema_version": REPORT_SCHEMA_VERSION, "checker": "tools/check_entity_graph.py", "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "input_sha256": hashlib.sha256(bundle_bytes).hexdigest(), "schema_sha256": inv["hashes"], "dependency_sha256": inv["dependency_hashes"], "comparisonAsOfDate": None, "state": None,
           "entity_counts": {}, "organisation_groups": 0, "resolved_links": {}, "checks_performed": [], "checks_not_evaluated": [], "errors": [], "review_items": [],
           "external_references_not_checked": {}, "profiles": {"applied": {k: {kk: vv for kk, vv in a.items() if kk != "_schema"} for k, a in applied.items()}, "unused": sorted(applied)}, "not_established": NOT_ESTABLISHED, "statement": None}
    bundle = None
    def finish(state, errors, review=(), performed=(), not_eval=(), declared=None, resolved=None, stage=None):
        rep["state"] = state
        rep["errors"] = [{"rule": e[0], "pointer": e[1], "message": e[2]} | ({"related": e[3]} if len(e) > 3 else {}) for e in errors]
        rep["review_items"] = [{"kind": c, "pointer": p_, "message": m} for c, p_, m in review]
        rep["checks_performed"] = list(performed); rep["checks_not_evaluated"] = list(not_eval)
        if declared is not None: rep["resolved_links"] = relation_records(declared, resolved or {}, stage)
        rep["statement"] = SUCCESS if state == "checked_with_limits" else ("no record was supplied; nothing was exercised and nothing is certified" if state == "not_evaluated" else None)
        if bundle is not None:                                     # every pointer this checker emits must locate a value in the parsed instance
            for e in rep["errors"] + rep["review_items"]:
                for ptr in [e["pointer"]] + e.get("related", []):
                    if resolve_pointer(bundle, ptr) is _MISSING: raise ToolError(f"checker defect: pointer {ptr!r} does not resolve in the supplied instance")
        return rep
    try: bundle = loads_strict(bundle_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e: return finish("invalid", [("input", "", f"not strict JSON: {e}")], not_eval=["structure", "C1-C18", "profiles", "G01-G10", "S07 measurement checks"])
    struct = structural_errors(inv, bundle)
    if struct: return finish("invalid", struct, performed=["structure"], not_eval=["C1-C18", "profiles", "G01-G10", "S07 measurement checks"])
    rep["comparisonAsOfDate"] = bundle["comparisonAsOfDate"]; rep["organisation_groups"] = len(bundle["organisations"])
    items = records(bundle)
    counts = {n: 0 for n in ALL_ENTITIES}
    for n, _, _ in items: counts[n] += 1
    rep["entity_counts"] = counts; rep["entity_counts_note"] = "Crosswalk rows are declared mappings, not independent evidence; duplicate rows are repeated declarations"
    declared = declared_edges(bundle)
    if not items: return finish("not_evaluated", [], performed=["structure", "profile configuration"], not_eval=["C1-C18", "profiles (no record to apply them to)", "G01-G10", "S07 measurement checks"], declared=declared, stage=None)
    rules = rule_errors(inv, items)
    perrs, applied_public, unused = profile_results(inv, applied, items)
    rep["profiles"] = {"applied": applied_public, "unused": unused}
    # a namespace is checked only where a supplied profile of that id names the record's own schema; anywhere else its semantics are unchecked
    covered = {(lbl.split("@")[0], sid) for lbl, a in applied_public.items() for sid in a["core_schema_ids"]}
    ext_ns = sorted({k for n, x, _ in items if isinstance(x.get("ext"), dict) for k in x["ext"] if (k, inv["schemas"][n]["$id"]) not in covered})
    if ext_ns: rep["external_references_not_checked"]["extension_namespaces_without_a_supplied_profile"] = ext_ns
    if rules or perrs: return finish("invalid", rules + perrs, performed=["structure", "C1-C18", "profiles"], not_eval=["G01-G10", "S07 measurement checks"], declared=declared, stage=None)
    gerrs, greview, resolved, stage = graph(bundle)
    rep["external_references_not_checked"]["crosswalk_semantics"] = "ISO 45003 clauses, HSE domains and reserved WHIU strings are checked as syntax only"
    if stage == "identity":     # identities or scope invalid: nothing downstream was attempted, and the report says so
        return finish("invalid", gerrs, greview, performed=["structure", "C1-C18", "profiles", "G01-G02"], not_eval=["G03-G10 (identities invalid)", "S07 measurement checks (identities invalid)"], declared=declared, resolved=resolved, stage="identity")
    if gerrs:          # reference failures: the measurement joins would rest on unresolved records, so they are not evaluated
        return finish("invalid", gerrs, greview, performed=["structure", "C1-C18", "profiles", "G01-G10"], not_eval=["S07 measurement checks (references unresolved)"], declared=declared, resolved=resolved, stage="complete")
    merrs, mreview, mext, gate = measurement_checks(bundle)
    rep["measurement_gate"] = gate
    for k, v in mext.items(): rep["external_references_not_checked"][k] = v
    errors = merrs; review = greview + mreview
    return finish("invalid" if errors else "checked_with_limits", errors, review, performed=["structure", "C1-C18", "profiles", "G01-G10", "S07 measurement checks"], not_eval=[], declared=declared, resolved=resolved, stage="complete")


def write_atomic(path, text):
    tmp = Path(str(path) + ".tmp"); tmp.write_text(text, encoding="utf-8"); os.replace(tmp, path)


def emit(rep, out):
    """Print the report and, when --out is given, replace whatever stood there with it, so no earlier success survives a failed run.
    A destination that cannot be written is itself an explicit tool error on stdout and stderr."""
    text = json.dumps(rep, indent=1, ensure_ascii=False) + "\n"
    if out is not None:
        try: write_atomic(out, text)
        except OSError as e:
            msg = f"report could not be written to {out}: {e}; the destination may still hold an earlier report that is not this run's result"
            rep = {"report_schema_version": REPORT_SCHEMA_VERSION, "state": "tool_error", "error": msg, "result_not_written": rep.get("state"), "statement": None}
            print(json.dumps(rep, indent=1, ensure_ascii=False)); print(f"[tool] {msg}", file=sys.stderr); return 2
    print(text)
    return {"checked_with_limits": 0, "not_evaluated": 0, "invalid": 1, "tool_error": 2}[rep["state"]]


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
        rep = {"report_schema_version": REPORT_SCHEMA_VERSION, "checker": "tools/check_entity_graph.py", "state": "tool_error", "error": str(e), "statement": None}
    except Exception as e:                       # an unexpected failure of the tool is a tool error, never a traceback standing for a verdict
        rep = {"report_schema_version": REPORT_SCHEMA_VERSION, "checker": "tools/check_entity_graph.py", "state": "tool_error", "error": f"unexpected {type(e).__name__}: {str(e)[:200]}", "statement": None}
    return emit(rep, out)


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
        rl = rep["resolved_links"]
        t("relation records: declared, resolved and unresolved counts per relation; an evaluated edge reads evaluated; a relation no record carries reads no_declared_edge, never validated", rl["reports.benchmarkRef->benchmarks"] == {"declared": 1, "resolved": 1, "unresolved": 0, "state": "evaluated", "reason": None} and rl["absences.pseudonymId->workers"]["resolved"] == 1 and rl["units.parentUnitId->units"]["state"] == "no_declared_edge", rl)
        t("provenance carries the shared validator, measurement checker and profile-envelope hashes beside the checker, input and schema hashes", set(rep["dependency_sha256"]) == {"tools/validate.py", "tools/check_measurement.py", "profiles/profile-envelope.schema.json"} and all(len(v) == 64 for v in rep["dependency_sha256"].values()) and rep["measurement_gate"]["sha256"] == rep["dependency_sha256"]["tools/check_measurement.py"], rep["dependency_sha256"])
        t("every emitted pointer is RFC 6901 and resolves in the instance", all((e["pointer"] == "" or e["pointer"].startswith("/")) and resolve_pointer(valid, e["pointer"]) is not _MISSING for e in rep["errors"] + rep["review_items"]))
        # the 64 prototype cases through the real command line: code multisets and pointers
        n_cases = 0
        for c in manifest:
            bundle = json.loads((EXAMPLES / c["file"]).read_text(encoding="utf-8"))
            rc, rep, err = cli(bundle, tmpdir=tmp); n_cases += 1
            want_codes = sorted(c["expected_codes"]); got_codes = codes(rep)
            ok = rep is not None and got_codes == want_codes and "Traceback" not in err and (rc == 1 if want_codes else rc == 0)
            if ok and c["expected_errors"]: ok = pairs(rep) == sorted((e[0], e[1]) for e in c["expected_errors"])
            if ok and want_codes and any(x.startswith("schema:") or x.startswith("C") for x in want_codes): ok = "G01-G10" in rep["checks_not_evaluated"] and rep["statement"] is None
            if ok and rep is not None and rep["state"] != "invalid" or (ok and rep and rep["errors"]):
                parsed = bundle
                ok = all((e["pointer"] == "" or e["pointer"].startswith("/")) and resolve_pointer(parsed, e["pointer"]) is not _MISSING and all(resolve_pointer(parsed, r) is not _MISSING for r in e.get("related", [])) for e in rep["errors"] + rep["review_items"])
            if ok and want_codes and set(want_codes) <= {"G01", "G02"}:      # identity failed: downstream stages are reported as not evaluated, relations as not attempted
                ok = rep["checks_performed"][-1] == "G01-G02" and any(x.startswith("G03-G10") for x in rep["checks_not_evaluated"]) and all(v["state"] == "not_evaluated" and v["resolved"] is None for v in rep["resolved_links"].values())
            t(f"case {c['case']}: codes {want_codes}", ok, (rc, got_codes, pairs(rep) if rep else None, rep and rep["checks_performed"], err[-160:]))
        t("all sixty-four prototype cases ran", n_cases == 64, n_cases)
        by_case = {c["case"]: c for c in manifest}
        for case, code, want_ptr in (("benchmark-metric-different", "G08", "/organisations/0/reports/0/metricCode"), ("leave-one-out-wrong-org", "G09", "/benchmarks/0/excludedOrgId"), ("before-declared-release-validity", "G10", "/comparisonAsOfDate")):
            rc, rep, err = cli(json.loads((EXAMPLES / by_case[case]["file"]).read_text(encoding="utf-8")), tmpdir=tmp); e = next((x for x in rep["errors"] if x["rule"] == code), None)
            t(f"{code} points at {want_ptr} and relates the report's benchmarkRef and the release record", e is not None and e["pointer"] == want_ptr and e.get("related") == ["/organisations/0/reports/0/benchmarkRef", "/benchmarks/0"], e)
        t("pointer tokens escape ~ and / (RFC 6901 section 3) and round-trip through resolution", P("a/b~c", 0) == "/a~1b~0c/0" and resolve_pointer({"a/b~c": [7]}, "/a~1b~0c/0") == 7 and resolve_pointer({"a": 1}, "") == {"a": 1} and resolve_pointer({"a": 1}, "/b") is _MISSING and resolve_pointer({"a": 1}, "a") is _MISSING)
        abs_prof = {"profile_id": "owhs-test", "version": "1.0.0", "core_schema_ids": ["https://openworkplacehealth.org/schemas/v0.2/AbsenceEpisode.json"], "schema": {"properties": {"ext": {"properties": {"owhs-test": {"properties": {"a/b~c": {"type": "integer"}}}}}}}}
        (Path(tmp) / "absprof.json").write_text(json.dumps(abs_prof), encoding="utf-8")
        b = copy.deepcopy(valid); b["organisations"][0]["absences"][0]["ext"] = {"owhs-test": {"a/b~c": "x"}}
        rc, rep, err = cli(b, "--profile", str(Path(tmp) / "absprof.json"), tmpdir=tmp); t("a failing profile extension property whose name contains / and ~ has an escaped pointer that resolves", rc == 1 and any(e["pointer"] == "/organisations/0/absences/0/ext/owhs-test/a~1b~0c" and e["rule"] == "profile:owhs-test@1.0.0" for e in rep["errors"]) and all(resolve_pointer(b, e["pointer"]) is not _MISSING for e in rep["errors"]), (rc, rep and rep.get("error"), rep and rep["errors"][:2]))
        b = copy.deepcopy(valid); b["benchmarks"].append(copy.deepcopy(b["benchmarks"][0]))
        rc, rep, err = cli(b, tmpdir=tmp); t("a duplicate benchmark key (same id and version, identical content) is G02 at the duplicate release record and the downstream stages are not evaluated", rc == 1 and pairs(rep) == [("G02", "/benchmarks/1")] and any(x.startswith("G03-G10") for x in rep["checks_not_evaluated"]) and rep["resolved_links"]["reports.benchmarkRef->benchmarks"]["state"] == "not_evaluated", (rc, pairs(rep), rep and rep["checks_not_evaluated"]))
        b = copy.deepcopy(valid); b["benchmarks"].append({**copy.deepcopy(b["benchmarks"][0]), "releaseVersion": "9.9.9"})
        rc, rep, err = cli(b, tmpdir=tmp); t("a second release of the same benchmark under another version is not a duplicate key", rc == 0 and not rep["errors"], (rc, codes(rep)))
        b = copy.deepcopy(valid); b["organisations"][0]["workers"][0]["orgId"] = "org-other"
        rc, rep, err = cli(b, tmpdir=tmp); t("after an identity failure the relations say resolution was not attempted, not no declared edge", rc == 1 and codes(rep) == ["G01"] and rep["checks_performed"] == ["structure", "C1-C18", "profiles", "G01-G02"] and rep["checks_not_evaluated"] == ["G03-G10 (identities invalid)", "S07 measurement checks (identities invalid)"] and all(v["state"] == "not_evaluated" and "not attempted" in v["reason"] for v in rep["resolved_links"].values()) and rep["resolved_links"]["reports.benchmarkRef->benchmarks"]["declared"] == 1, (rc, rep and rep["checks_not_evaluated"], rep and rep["resolved_links"]["reports.benchmarkRef->benchmarks"]))
        b = copy.deepcopy(valid); b["organisations"][0]["workers"][0]["unitId"] = "u-absent"
        rc, rep, err = cli(b, tmpdir=tmp); t("an unresolved edge is counted as present but unresolved, distinct from an absent edge", rc == 1 and codes(rep) == ["G03"] and rep["resolved_links"]["workers.unitId->units"] == {"declared": 1, "resolved": 0, "unresolved": 1, "state": "evaluated", "reason": None}, rep and rep["resolved_links"]["workers.unitId->units"])
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
        rc, rep, err = cli(b, tmpdir=tmp); t("a malformed comparison date is a format error at the root", rc == 1 and pairs(rep) == [("schema:format", "/comparisonAsOfDate")])
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
        for name, fn, want_rc in (("no-banding", lambda g_: g_["contexts"][0]["scoringDescriptor"].pop("banding"), 1), ("no-threshold", lambda g_: g_["contexts"][0]["scoringDescriptor"].pop("threshold"), 1),
                                  ("partial-no-rule", lambda g_: (g_["administrations"][0].update(completionStatus="partial"), g_["contexts"][0]["scoringDescriptor"].pop("missingResponseRule")), 1),
                                  ("native-outside", lambda g_: g_["observations"][0].update(nativeValue=6), 1), ("offset-equivalent", lambda g_: g_["observations"][0].update(occasionTs="2026-07-01T01:00:00+01:00"), 0),
                                  ("narrow-report", lambda g_: g_["reports"][0].update(periodStart="2026-08-01", periodEnd="2026-08-31"), 0)):
            b = copy.deepcopy(valid); fn(b["organisations"][0]); rc, rep, err = cli(b, tmpdir=tmp)
            t(f"S07 retained through the graph checker: {name} exits {want_rc}" + (" as S07" if want_rc else ""), rc == want_rc and (("S07" in codes(rep)) if want_rc else not rep["errors"]) and "Traceback" not in err, (rc, codes(rep), err[-120:]))
        # profiles through the real validator classes
        prof = ROOT / "profiles" / "owhs-example" / "0.1.0.json"
        rc, rep, err = cli(valid, "--profile", str(prof), tmpdir=tmp); t("a supplied profile applies to every record of its declared entity: the absence without the required namespace fails it through the real validator", rc == 1 and rep["profiles"]["applied"]["owhs-example@0.1.0"]["records_checked"] == 1 and any(e["rule"] == "profile:owhs-example@0.1.0" and e["pointer"].startswith("/organisations/0/absences/0") for e in rep["errors"]), (rc, rep and rep["profiles"], rep and rep["errors"][:1]))
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
        b["organisations"][0]["units"] += units; rc, rep, err = cli(b, tmpdir=tmp); t("a 1,201-unit acyclic chain passes without recursion", rc == 0 and rep["resolved_links"]["units.parentUnitId->units"]["resolved"] == 1200, (rc, codes(rep), err[-120:]))
        # supplied profile configuration is preflighted with the S06 contract before any record, unused branches included
        sid = "https://openworkplacehealth.org/schemas/v0.2/Organisation.json"
        def prof(schema): return {"profile_id": "owhs-test", "version": "1.0.0", "core_schema_ids": [sid], "schema": schema}
        def with_profile(bundle, profile, *extra):
            pf = Path(tmp) / f"p{len(list(Path(tmp).iterdir()))}.json"; pf.write_text(profile if isinstance(profile, str) else json.dumps(profile), encoding="utf-8")
            return cli(bundle, "--profile", str(pf), *extra, tmpdir=tmp)
        rc, rep, err = with_profile(valid, prof({"type": "object"})); t("a valid supplied profile applies to the organisation record and passes", rc == 0 and rep["profiles"]["applied"]["owhs-test@1.0.0"]["records_checked"] == 1 and not rep["profiles"]["unused"], (rc, rep and rep["profiles"]))
        rc, rep, err = with_profile(valid, prof({"properties": {"orgId": {"format": "unimplemented-format"}}})); t("a profile declaring a format this installation cannot assert is a tool error naming the format, exit 2", rc == 2 and rep["state"] == "tool_error" and "unimplemented-format" in rep["error"], (rc, rep))
        rc, rep, err = with_profile(valid, prof({"$ref": "https://example.invalid/never-fetch.json"})); t("a profile whose root is an external reference is a tool error, no fetch, no traceback", rc == 2 and rep["state"] == "tool_error" and "never-fetch" in rep["error"] and "Traceback" not in err, (rc, rep, err[-120:]))
        rc, rep, err = with_profile(valid, prof({"properties": {"notSupplied": {"$ref": "https://example.invalid/never-fetch.json"}}})); t("an external reference on an unused profile branch is still a tool error (unused branches are inspected)", rc == 2 and "never-fetch" in rep["error"], (rc, rep))
        rc, rep, err = with_profile(valid, prof({"properties": {"orgId": {"pattern": "["}}})); t("a profile with a malformed regular expression is a tool error", rc == 2 and rep["state"] == "tool_error", (rc, rep))
        rc, rep, err = with_profile(valid, prof({"$defs": {"loc": {"type": "object"}}, "$ref": "#/$defs/loc"})); t("a profile whose reference resolves inside its own document passes preflight", rc == 0 and rep["profiles"]["applied"]["owhs-test@1.0.0"]["records_checked"] == 1, (rc, rep and rep.get("error"), rep and rep["profiles"]))
        empty = {"schema_version": "0.2", "comparisonAsOfDate": "2026-09-01", "organisations": [], "benchmarks": [], "crosswalks": []}
        rc, rep, err = with_profile(empty, "not json"); t("an empty inventory with a malformed profile is a tool error, not not_evaluated", rc == 2 and rep["state"] == "tool_error" and "not strict JSON" in rep["error"], (rc, rep))
        rc, rep, err = cli(empty, "--profile", str(Path(tmp) / "missing-profile.json"), tmpdir=tmp); t("an empty inventory with a missing profile file is a tool error", rc == 2 and rep["state"] == "tool_error", (rc, rep))
        rc, rep, err = with_profile(empty, prof({"type": "object"})); t("an empty inventory with a valid profile is not_evaluated and records the profile's id, version and hash as unused, never applied to zero rows under a passed label", rc == 0 and rep["state"] == "not_evaluated" and rep["profiles"]["unused"] == ["owhs-test@1.0.0"] and rep["profiles"]["applied"]["owhs-test@1.0.0"]["records_checked"] == 0 and len(rep["profiles"]["applied"]["owhs-test@1.0.0"]["sha256"]) == 64 and rep["statement"] != SUCCESS, (rc, rep and rep["profiles"], rep and rep["statement"]))
        # tool errors on copied scratch trees: configuration and dependency failures are tool_error reports, never tracebacks or passes; --out is replaced
        import shutil
        def fake_tree(mutate, *extra, profile=None):
            with tempfile.TemporaryDirectory() as fake:
                for sub in ("tools", "schemas", "profiles"): shutil.copytree(ROOT / sub, Path(fake) / sub)
                mutate(Path(fake))
                bp = Path(fake) / "b.json"; bp.write_text(json.dumps(valid), encoding="utf-8"); outp = Path(fake) / "report.json"; outp.write_text('{"state": "checked_with_limits", "stale": true}', encoding="utf-8")
                args = [sys.executable, "-B", str(Path(fake) / "tools" / "check_entity_graph.py"), str(bp), "--out", str(outp), *extra]
                if profile is not None: pf = Path(fake) / "prof.json"; pf.write_text(json.dumps(profile), encoding="utf-8"); args += ["--profile", str(pf)]
                r = subprocess.run(args, capture_output=True, text=True)
                try: rep_ = json.loads(r.stdout)
                except ValueError: rep_ = None
                try: written = json.loads(outp.read_text(encoding="utf-8"))
                except ValueError: written = None
                return r.returncode, rep_, r.stderr, written
        def edit(path, fn):
            d = json.loads(path.read_text(encoding="utf-8")); fn(d); path.write_text(json.dumps(d), encoding="utf-8")
        for label, mutate, needle, kw in (("a missing entity schema", lambda f: (f / "schemas" / "v0.2" / "Crosswalk.json").unlink(), "missing", {}),
                                         ("malformed core schema JSON", lambda f: (f / "schemas" / "v0.2" / "Organisation.json").write_text("{", encoding="utf-8"), "not strict JSON", {}),
                                         ("malformed profile-envelope JSON", lambda f: (f / "profiles" / "profile-envelope.schema.json").write_text("{", encoding="utf-8"), "profile-envelope", {"profile": prof({"type": "object"})}),
                                         ("a core schema using an unasserted format", lambda f: edit(f / "schemas" / "v0.2" / "Organisation.json", lambda d: d["properties"]["orgId"].update(format="unimplemented-format")), "unimplemented-format", {}),
                                         ("a core schema carrying an unexercised external reference", lambda f: edit(f / "schemas" / "v0.2" / "Organisation.json", lambda d: d["properties"].update(unused={"$ref": "https://example.invalid/never-fetch.json"})), "never-fetch", {}),
                                         ("a missing shared validator", lambda f: (f / "tools" / "validate.py").unlink(), "validate.py", {}),
                                         ("a missing measurement checker", lambda f: (f / "tools" / "check_measurement.py").unlink(), "check_measurement.py", {}),
                                         ("a measurement checker returning None", lambda f: (f / "tools" / "check_measurement.py").write_text("def check(bundle): return None\n", encoding="utf-8"), "malformed result", {}),
                                         ("a measurement checker raising SystemExit", lambda f: (f / "tools" / "check_measurement.py").write_text("def check(bundle): raise SystemExit(2)\n", encoding="utf-8"), "exited", {}),
                                         ("a measurement checker raising RuntimeError", lambda f: (f / "tools" / "check_measurement.py").write_text('def check(bundle): raise RuntimeError("synthetic failure")\n', encoding="utf-8"), "synthetic failure", {}),
                                         ("a measurement checker returning the wrong arity", lambda f: (f / "tools" / "check_measurement.py").write_text("def check(bundle): return [], []\n", encoding="utf-8"), "malformed result", {}),
                                         ("a measurement checker returning non-string problems", lambda f: (f / "tools" / "check_measurement.py").write_text("def check(bundle): return [1], [], {}\n", encoding="utf-8"), "malformed result", {}),
                                         ("a shared validator that is a different file", lambda f: (f / "tools" / "validate.py").write_text("X = 1\n", encoding="utf-8"), "lacks", {})):
            rc, rep, err, written = fake_tree(mutate, **kw)
            t(f"tool error: {label} is a tool_error report (exit 2, no traceback, no pass) naming the cause, and --out is replaced with it", rc == 2 and rep is not None and rep["state"] == "tool_error" and needle in rep["error"] and "Traceback" not in err and written is not None and written["state"] == "tool_error" and "stale" not in written, (rc, rep, err[-160:], written))
        with tempfile.TemporaryDirectory() as fake:
            bp = Path(fake) / "b.json"; bp.write_text(json.dumps(valid), encoding="utf-8")
            r = subprocess.run([sys.executable, "-B", str(here), str(bp), "--out", str(Path(fake) / "no-such-dir" / "report.json")], capture_output=True, text=True)
            t("an unwritable --out destination is an explicit tool error on stdout and stderr (exit 2) saying the report was not replaced", r.returncode == 2 and '"tool_error"' in r.stdout and "could not be written" in r.stdout and "could not be written" in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stdout[-200:], r.stderr[-200:]))
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
