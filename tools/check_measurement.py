#!/usr/bin/env python3
"""Supplied-bundle join checks for the v0.2 measurement entities.

    python tools/check_measurement.py BUNDLE.json
    python tools/check_measurement.py --self-test

A bundle is a closed object: schema_version "0.2" and four arrays, contexts, observations, administrations and
reports, each item validated against its v0.2 schema and its cross-field rules through tools/validate.py. Then:

  - (entity, orgId, primary id) is unique;
  - every contextId resolves to a context in the same bundle and the same organisation; the same string in
    another organisation is not a match;
  - an observation or administration occasion falls inside its context's observation window (UTC instants);
  - a report's period is covered by its context window's calendar dates after UTC conversion; a narrower
    period is reported as an interpretation review item, since only the declared estimand can explain it;
  - a nativeValue lies inside the context's declared nativeScale when one is declared;
  - normalisedValue needs the context to declare a normalisation; band needs banding; aboveThresholdFlag needs
    threshold; a partial administration carrying scores needs a missingResponseRule;
  - references the bundle cannot carry (pseudonymId, unitId, benchmarkRef, itemId, instrumentId) are listed as
    external references not checked, never treated as resolved.

Exit 0 means every declared check passed within this scope. It is not Level 2 or Level 3 conformance, not an
anonymity assessment, and not a judgement on any measurement's validity.
"""
import copy, json, subprocess, sys, tempfile
from datetime import datetime, timezone, date
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "tools" / "validate.py"
S = ROOT / "schemas" / "v0.2"
ENTITY = {"contexts": ("MeasurementContext", "contextId"), "observations": ("WellbeingObservation", "observationId"),
          "administrations": ("InstrumentAdministration", "administrationId"), "reports": ("AggregateReport", "reportId")}


def instant(v):
    try: return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception: return None


def validate_item(entity, item):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(item, f); p = f.name
    r = subprocess.run([sys.executable, str(V), str(S / f"{entity}.json"), p], capture_output=True, text=True)
    Path(p).unlink()
    if r.returncode == 2: raise SystemExit(f"[tool] {r.stderr.strip()}")
    return r.returncode == 0, [l for l in r.stdout.splitlines() if l.startswith("[")]


def check(bundle):
    problems, review, external = [], [], {"pseudonymId": set(), "unitId": set(), "benchmarkRef": set(), "itemId": set(), "instrumentId": set()}
    if not isinstance(bundle, dict) or set(bundle) - {"schema_version", *ENTITY}:
        return [f"bundle: unknown keys {sorted(set(bundle) - {'schema_version', *ENTITY})}"], review, external
    if bundle.get("schema_version") != "0.2":
        problems.append(f"bundle: schema_version {bundle.get('schema_version')!r}, expected '0.2'")
    seen = set()
    for arr, (entity, pk) in ENTITY.items():
        items = bundle.get(arr, [])
        if not isinstance(items, list):
            problems.append(f"{arr}: not an array"); continue
        for i, item in enumerate(items):
            ok, errs = validate_item(entity, item)
            if not ok:
                problems += [f"{arr}[{i}]: {e}" for e in errs]; continue
            key = (entity, item.get("orgId"), item.get(pk))
            if key in seen: problems.append(f"{arr}[{i}]: duplicate {entity} {item.get(pk)!r} in organisation {item.get('orgId')!r}")
            seen.add(key)
    ctx = {(c["orgId"], c["contextId"]): c for c in bundle.get("contexts", []) if isinstance(c, dict) and "orgId" in c and "contextId" in c}

    def context_for(arr, i, item):
        key = (item.get("orgId"), item.get("contextId"))
        if key in ctx: return ctx[key]
        elsewhere = [o for (o, cid) in ctx if cid == item.get("contextId") and o != item.get("orgId")]
        problems.append(f"{arr}[{i}]: contextId {item.get('contextId')!r} not found in organisation {item.get('orgId')!r}"
                        + (f" (a context with that id exists in organisation {elsewhere[0]!r}; ids do not join across organisations)" if elsewhere else ""))
        return None

    for i, o in enumerate(bundle.get("observations", [])):
        if not isinstance(o, dict): continue
        external["pseudonymId"].add(o.get("pseudonymId")); external["itemId"].add(o.get("itemId"))
        c = context_for("observations", i, o)
        if not c: continue
        sd = c["scoringDescriptor"]; w = sd["observationWindow"]; t = instant(o["occasionTs"])
        if t and not (instant(w["start"]) <= t <= instant(w["end"])):
            problems.append(f"observations[{i}]: occasionTs {o['occasionTs']} outside the context window {w['start']} to {w['end']}")
        ns = sd.get("nativeScale")
        if ns and not (ns["min"] <= o["nativeValue"] <= ns["max"]):
            problems.append(f"observations[{i}]: nativeValue {o['nativeValue']} outside the declared nativeScale {ns['min']} to {ns['max']}")
        if "normalisedValue" in o and "normalisation" not in sd:
            problems.append(f"observations[{i}]: normalisedValue present but the context declares no normalisation")
    for i, a in enumerate(bundle.get("administrations", [])):
        if not isinstance(a, dict): continue
        external["pseudonymId"].add(a.get("pseudonymId")); external["instrumentId"].add(a.get("instrumentId"))
        c = context_for("administrations", i, a)
        if not c: continue
        sd = c["scoringDescriptor"]; w = sd["observationWindow"]; t = instant(a["occasionTs"])
        if t and not (instant(w["start"]) <= t <= instant(w["end"])):
            problems.append(f"administrations[{i}]: occasionTs {a['occasionTs']} outside the context window")
        if "band" in a and "banding" not in sd: problems.append(f"administrations[{i}]: band present but the context declares no banding")
        if "aboveThresholdFlag" in a and "threshold" not in sd: problems.append(f"administrations[{i}]: aboveThresholdFlag present but the context declares no threshold")
        if a.get("completionStatus") == "partial" and ("totalScore" in a or "subscaleScores" in a) and "missingResponseRule" not in sd:
            problems.append(f"administrations[{i}]: partial administration carries scores but the context declares no missingResponseRule")
    for i, r in enumerate(bundle.get("reports", [])):
        if not isinstance(r, dict): continue
        if r.get("unitId"): external["unitId"].add(r["unitId"])
        if r.get("benchmarkRef"): external["benchmarkRef"].add(f"{r['benchmarkRef'].get('benchmarkId')}@{r['benchmarkRef'].get('releaseVersion')}")
        c = context_for("reports", i, r)
        if not c: continue
        w = c["scoringDescriptor"]["observationWindow"]
        ws, we = instant(w["start"]).date(), instant(w["end"]).date()
        ps, pe = date.fromisoformat(r["periodStart"]), date.fromisoformat(r["periodEnd"])
        if ps < ws or pe > we:
            problems.append(f"reports[{i}]: period {ps} to {pe} not covered by the context window {ws} to {we}")
        elif (ps, pe) != (ws, we):
            review.append(f"reports[{i}]: period {ps} to {pe} is narrower than the context window {ws} to {we}; the declared estimand ({c['scoringDescriptor']['estimand']!r}) must explain the distinction")
    return problems, review, {k: sorted(x for x in v if x) for k, v in external.items()}


def report(problems, review, external):
    for p in problems: print("FAIL", p)
    for r in review: print("REVIEW", r)
    for k, v in external.items():
        if v: print(f"EXTERNAL not checked: {k} x{len(v)}")
    print(("bundle checks passed within scope" if not problems else f"{len(problems)} problem(s)") + "; not Level 2 or Level 3 conformance, not an anonymity assessment")


def load(name): return json.loads((ROOT / "examples" / "v0.2" / name).read_text(encoding="utf-8"))


def self_test():
    ctx, obs, adm, rep = load("MeasurementContext.valid.json"), load("WellbeingObservation.valid.json"), load("InstrumentAdministration.valid.json"), load("AggregateReport.valid.json")
    base = {"schema_version": "0.2", "contexts": [ctx], "observations": [obs], "administrations": [adm, load("InstrumentAdministration.subscales-only.valid.json")], "reports": [rep]}
    cases = []
    def case(label, mutate, expect_fail, must=""):
        b = copy.deepcopy(base); mutate(b); cases.append((label, b, expect_fail, must))
    case("minimal valid bundle, all four entities", lambda b: None, False)
    def two_orgs(b):
        c2 = copy.deepcopy(ctx); c2["orgId"] = "org-two"; b["contexts"].append(c2)
        o2 = copy.deepcopy(obs); o2["orgId"] = "org-two"; b["observations"].append(o2)      # same pseudonym and context strings, different organisation: allowed when scoped
    case("same pseudonym and context strings in two organisations, correctly scoped, allowed", two_orgs, False)
    case("missing context fails", lambda b: b["contexts"].clear(), True, "not found")
    def wrong_org(b): b["observations"][0]["orgId"] = "org-two"
    case("context reference to another organisation fails and is explained", wrong_org, True, "do not join across organisations")
    case("duplicate primary key in one organisation fails", lambda b: b["observations"].append(copy.deepcopy(obs)), True, "duplicate")
    def out_of_window(b): b["observations"][0]["occasionTs"] = "2026-12-01T00:00:00Z"
    case("occasion outside the context window fails", out_of_window, True, "outside the context window")
    def scale(b): b["observations"][0]["nativeValue"] = 9
    case("nativeValue outside declared nativeScale fails", scale, True, "nativeScale")
    def no_norm(b): del b["contexts"][0]["scoringDescriptor"]["normalisation"]
    case("normalisedValue without a declared normalisation fails", no_norm, True, "normalisation")
    def no_band(b): del b["contexts"][0]["scoringDescriptor"]["banding"]
    case("band without declared banding fails", no_band, True, "banding")
    def no_thr(b): del b["contexts"][0]["scoringDescriptor"]["threshold"]
    case("aboveThresholdFlag without declared threshold fails", no_thr, True, "threshold")
    def partial_no_rule(b):
        b["administrations"][0]["completionStatus"] = "partial"; del b["contexts"][0]["scoringDescriptor"]["missingResponseRule"]
    case("partial administration with scores and no missing-response rule fails", partial_no_rule, True, "missingResponseRule")
    def partial_ok(b): b["administrations"][0]["completionStatus"] = "partial"
    case("partial administration with a declared rule passes", partial_ok, False)
    def period_outside(b): b["reports"][0]["periodEnd"] = "2026-10-15"
    case("report period beyond the context window fails", period_outside, True, "not covered")
    def period_narrow(b): b["reports"][0]["periodStart"] = "2026-08-01"
    case("narrower report period is a review item, not a failure", period_narrow, False, "REVIEW")
    def bad_item(b): b["reports"][0]["completionRate"] = 0.15
    case("an item failing its own schema or rule fails the bundle", bad_item, True, "[C9]")
    case("unknown bundle key fails", lambda b: b.update({"extra": []}), True, "unknown keys")
    case("wrong schema_version fails", lambda b: b.update({"schema_version": "0.1"}), True, "schema_version")
    case("empty arrays are allowed", lambda b: [b[k].clear() for k in ("observations", "administrations", "reports")], False)

    failures = 0
    for label, bundle, expect_fail, must in cases:
        problems, review, external = check(bundle)
        text = "\n".join(problems + [f"REVIEW {r}" for r in review])
        ok = (bool(problems) == expect_fail) and (must in text if must else True)
        print(("ok  " if ok else "FAIL"), label, "" if ok else f"({problems[:2]} {review[:1]})")
        failures += not ok
    _, _, external = check(base)
    assert external["pseudonymId"] and external["benchmarkRef"] and external["unitId"], "external references must be listed"
    print("ok   external references (pseudonymId, unitId, benchmarkRef, itemId, instrumentId) listed as not checked:", {k: len(v) for k, v in external.items()})
    print(f"{len(cases) - failures}/{len(cases)} cases as expected")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif len(sys.argv) == 2:
        problems, review, external = check(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
        report(problems, review, external); sys.exit(1 if problems else 0)
    else:
        sys.exit("usage: check_measurement.py BUNDLE.json | --self-test")
