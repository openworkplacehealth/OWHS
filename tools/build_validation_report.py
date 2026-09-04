#!/usr/bin/env python3
"""Regenerate examples/validation_report.json from the schemas and example instances.

The report is the evidence for the Level 1 conformance claim, so it is generated
from a run rather than maintained by hand. Every instance in examples/ named
<Entity>.<label>.json or <Entity>.<label>.<verdict>.json is validated against
schemas/<Entity>.json using the same code path as tools/validate.py, including
the format checker and the named cross-field rules.

Usage: python tools/build_validation_report.py [--check]

`--check` compares the generated report against the committed one and writes
nothing, exiting non-zero if they differ. That is what a build gate needs: without
it a gate that runs this script rewrites the file it was meant to be checking, and
a stale report always passes.
"""
import json, pathlib, subprocess, sys, collections

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "tools" / "validate.py"
OUT = ROOT / "examples" / "validation_report.json"
SPEC_VERSION = "0.1.0"


def run(schema, instance):
    proc = subprocess.run([sys.executable, str(VALIDATE), str(schema), str(instance)],
                          capture_output=True, text=True)
    if proc.returncode == 2:
        raise SystemExit(f"validator refused to run on {instance.name}: {proc.stderr.strip()}")
    lines = [line for line in proc.stdout.splitlines() if line.startswith("[")]
    return proc.returncode, lines


def main():
    results = collections.OrderedDict()
    for schema in sorted((ROOT / "schemas").glob("*.json")):
        entity = schema.stem
        instances = sorted((ROOT / "examples").glob(f"{entity}.*.json"))
        cases = collections.OrderedDict()
        for instance in instances:
            label = instance.name[len(entity) + 1:-len(".json")]
            code, lines = run(schema, instance)
            cases[label] = collections.OrderedDict([
                ("expected", "pass" if label.endswith("valid") and not label.endswith("invalid") else "fail"),
                ("exit_code", code),
                ("error_count", len(lines)),
                ("errors", lines),
            ])
        results[entity] = cases
    report = collections.OrderedDict([
        ("specVersion", SPEC_VERSION),
        ("validator", "tools/validate.py, jsonschema Draft202012Validator with FORMAT_CHECKER and the Level 1 cross-field rules"),
        ("generatedBy", "tools/build_validation_report.py"),
        ("results", results),
    ])
    serialised = json.dumps(report, indent=2) + "\n"
    if "--check" in sys.argv[1:]:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != serialised:
            raise SystemExit(f"{OUT.relative_to(ROOT)} is out of date; "
                             "run tools/build_validation_report.py")
        print(f"up to date: {OUT.relative_to(ROOT)}")
    else:
        OUT.write_text(serialised, encoding="utf-8")
        print(f"written: {OUT.relative_to(ROOT)}")
    unexpected = [f"{e}.{l}" for e, cases in results.items() for l, c in cases.items()
                  if (c["expected"] == "pass") != (c["exit_code"] == 0)]
    if unexpected:
        raise SystemExit("verdict does not match the instance name: " + ", ".join(unexpected))
    print("every instance matched its expected verdict")


if __name__ == "__main__":
    main()
