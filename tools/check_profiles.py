#!/usr/bin/env python3
"""Self-test of the v0.2 extension mechanism and profile validation, run through tools/validate.py itself.

    python tools/check_profiles.py --self-test

Every case below names the behaviour it establishes. The last group states the documented boundary: a permitted
string containing an identifier-shaped value is core-valid, and nothing here claims P1 conformance for it.
"""
import copy, json, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "tools" / "validate.py"
S = ROOT / "schemas" / "v0.2"
P = ROOT / "profiles" / "owhs-example" / "0.1.0.json"


def run(schema, instance, *profiles):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(instance, f); path = f.name
    args = [sys.executable, str(V), str(schema), path]
    for p in profiles: args += ["--profile", str(p)]
    r = subprocess.run(args, capture_output=True, text=True)
    Path(path).unlink()
    return r.returncode, r.stdout + r.stderr


def load(name): return json.loads((ROOT / "examples" / "v0.2" / name).read_text(encoding="utf-8"))


def main():
    ab, rt, oh = load("AbsenceEpisode.valid.json"), load("ReturnToWorkOutcome.valid.json"), load("OHEpisode.valid.json")
    cases = []   # (label, expected exit, schema, instance, profiles, must_contain)
    for name, inst in (("AbsenceEpisode", ab), ("ReturnToWorkOutcome", rt), ("OHEpisode", oh)):
        sch = S / f"{name}.json"
        cases += [
            (f"{name}: no ext is valid", 0, sch, inst, (), ""),
            (f"{name}: empty ext is valid", 0, sch, {**inst, "ext": {}}, (), ""),
            (f"{name}: unknown namespace valid, semantics reported unchecked", 0, sch, {**inst, "ext": {"owhs-other": {"k": 1}}}, (), "profile semantics not checked"),
            (f"{name}: bare namespace key invalid", 1, sch, {**inst, "ext": {"example": {}}}, (), ""),
            (f"{name}: malformed namespace invalid", 1, sch, {**inst, "ext": {"owhs-Bad_Name": {}}}, (), ""),
            (f"{name}: overlong namespace invalid", 1, sch, {**inst, "ext": {"owhs-" + "a" * 70: {}}}, (), ""),
            (f"{name}: scalar payload invalid", 1, sch, {**inst, "ext": {"owhs-x": "text"}}, (), ""),
            (f"{name}: identifier key first level invalid", 1, sch, {**inst, "ext": {"owhs-x": {"nino": "QQ"}}}, (), ""),
            (f"{name}: identifier key two levels down invalid", 1, sch, {**inst, "ext": {"owhs-x": {"a": {"b": {"dateOfBirth": "1990-01-01"}}}}}, (), ""),
            (f"{name}: identifier key inside array invalid", 1, sch, {**inst, "ext": {"owhs-x": {"list": [{"email": "a@b.example"}]}}}, (), ""),
            (f"{name}: identifier-shaped value in a permitted string is core-valid (documented boundary)", 0, sch, {**inst, "ext": {"owhs-x": {"note": "contact a@b.example"}}}, (), "not checked"),
        ]
    cases += [
        ("OHEpisode: clinical key inside ext invalid", 1, S / "OHEpisode.json", {**oh, "ext": {"owhs-x": {"diagnosis": "x"}}}, (), ""),
        ("OHEpisode: clinical key nested in array invalid", 1, S / "OHEpisode.json", {**oh, "ext": {"owhs-x": {"r": [{"reportText": "x"}]}}}, (), ""),
        ("AbsenceEpisode: clinical key list not applied (clinicalCauseCode inside ext is a key check only, allowed here)", 0, S / "AbsenceEpisode.json", {**ab, "ext": {"owhs-x": {"clinicalCauseCode": "x"}}}, (), ""),
        ("profile passes with wave 3", 0, S / "AbsenceEpisode.json", {**ab, "ext": {"owhs-example": {"wave": 3}}}, (P,), "profiles checked: owhs-example"),
        ("profile fails with wave 0", 1, S / "AbsenceEpisode.json", {**ab, "ext": {"owhs-example": {"wave": 0}}}, (P,), "profile:owhs-example@0.1.0"),
        ("profile fails with wave missing", 1, S / "AbsenceEpisode.json", {**ab, "ext": {"owhs-example": {}}}, (P,), "wave"),
        ("profile fails with an extra payload property", 1, S / "AbsenceEpisode.json", {**ab, "ext": {"owhs-example": {"wave": 1, "extra": 1}}}, (P,), "extra"),
        ("profile explicitly requested but namespace absent fails", 1, S / "AbsenceEpisode.json", {**ab, "ext": {}}, (P,), "owhs-example"),
        ("profile against a different core version is a tool error", 2, S / "OHEpisode.json", oh, (P,), "targets"),
        ("C1 still fails when the profile passes", 1, S / "AbsenceEpisode.json", {**ab, "startDate": "2026-03-10", "endDate": "2026-03-01", "ext": {"owhs-example": {"wave": 2}}}, (P,), "[C1]"),
    ]
    # a profile cannot open the core: one that permits an extra top-level field
    open_profile = json.loads(P.read_text()); open_profile["schema"] = {"type": "object", "properties": {"extraTop": {"type": "string"}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f: json.dump(open_profile, f); open_path = Path(f.name)
    cases.append(("a profile cannot admit an extra top-level field the core forbids", 1, S / "AbsenceEpisode.json", {**ab, "extraTop": "x"}, (open_path,), "additionalProperties"))
    # a profile cannot widen a core enum
    widen = json.loads(P.read_text()); widen["schema"] = {"type": "object", "properties": {"reasonCode": {"enum": ["not-a-reason"]}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f: json.dump(widen, f); widen_path = Path(f.name)
    cases.append(("a profile cannot widen a core enum", 1, S / "AbsenceEpisode.json", {**ab, "reasonCode": "not-a-reason"}, (widen_path,), "enum"))
    # tool errors: network reference, missing local reference, unknown format
    bad_schema = json.loads((S / "AbsenceEpisode.json").read_text()); bad_schema["properties"]["ext"]["additionalProperties"] = {"$ref": "https://example.org/remote.json"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f: json.dump(bad_schema, f); net_path = Path(f.name)
    cases.append(("a network-only reference is a tool error, nothing is fetched", 2, net_path, ab, (), "do not resolve locally"))
    miss = json.loads((S / "AbsenceEpisode.json").read_text()); miss["$defs"]["unused"] = {"$ref": "#/$defs/doesNotExist"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f: json.dump(miss, f); miss_path = Path(f.name)
    cases.append(("a missing local reference in an unused branch is a tool error", 2, miss_path, ab, (), "do not resolve locally"))
    fmt = json.loads((S / "AbsenceEpisode.json").read_text()); fmt["properties"]["episodeId"]["format"] = "no-such-format"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f: json.dump(fmt, f); fmt_path = Path(f.name)
    cases.append(("an unknown format is a tool error", 2, fmt_path, ab, (), "cannot assert"))
    cases.append(("the recursive local extension reference works", 0, S / "AbsenceEpisode.json", {**ab, "ext": {"owhs-x": {"a": [[{"b": [{"c": None}]}]]}}}, (), ""))

    failures = 0
    for label, expected, schema, inst, profiles, must in cases:
        code, out = run(schema, inst, *profiles)
        ok = code == expected and (must in out if must else True)
        print(("ok  " if ok else "FAIL"), label, "" if ok else f"(exit {code}, expected {expected}; output: {out.strip()[:160]})")
        failures += not ok
    for p in (open_path, widen_path, net_path, miss_path, fmt_path): p.unlink(missing_ok=True)
    print(f"{len(cases) - failures}/{len(cases)} cases as expected")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    if "--self-test" not in sys.argv:
        sys.exit("usage: check_profiles.py --self-test")
    main()
