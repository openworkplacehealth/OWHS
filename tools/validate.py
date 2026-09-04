#!/usr/bin/env python3
"""OWHS v0.1 reference validator (Level 1).

Usage: python validate.py <schema.json> <instance.json>
Exit 0 instance valid, 1 instance invalid, 2 tool or schema error.

Two things this tool does that a bare jsonschema call does not.

It asserts every `format` the schema uses. In Draft 2020-12 `format` is an
annotation unless a validator is told to assert it, so a validator constructed
without a format checker accepts "banana" as a date. It also refuses to run
when the installation cannot assert a format the schema uses: jsonschema
registers some checkers only when an optional package is present and silently
accepts any value for a format it has not registered, so reporting a pass
would overstate what was checked.

It runs the named cross-field rules. JSON Schema compares an instance against a
schema and never one field of an instance against another, so an ordering rule
between two dates cannot be expressed in it. Those rules are listed in the
specification under Level 1 and implemented here.
"""
import re, sys, json
from datetime import date
from jsonschema.validators import Draft202012Validator as V

CHECKER = V.FORMAT_CHECKER
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def well_formed_dates(inst, *fields):
    """A cross-field date rule is only meaningful once both values are dates."""
    return all(isinstance(inst.get(f), str) and DATE.match(inst[f]) for f in fields)


def ordering(earlier, later, label):
    """Build a rule asserting that `later` does not precede `earlier`."""
    def rule(inst):
        if not isinstance(inst, dict) or later not in inst or earlier not in inst:
            return None
        if not well_formed_dates(inst, earlier, later):
            return None  # the format check reports it; a second error here would misdescribe it
        if inst[later] < inst[earlier]:
            return f"{later} {inst[later]!r} precedes {earlier} {inst[earlier]!r}"
        return None
    rule.__doc__ = label
    return rule


CROSS_FIELD_RULES = {
    "AbsenceEpisode": [("C1", ordering("startDate", "endDate", "endDate not before startDate"))],
    "OHEpisode": [("C2", ordering("referralDate", "assessmentDate", "assessmentDate not before referralDate"))],
}


def formats_used(node):
    """Every `format` keyword value appearing anywhere in the schema."""
    if isinstance(node, dict):
        if isinstance(node.get("format"), str):
            yield node["format"]
        for value in node.values():
            yield from formats_used(value)
    elif isinstance(node, list):
        for value in node:
            yield from formats_used(value)


def die(message):
    print(f"[tool] {message}", file=sys.stderr)
    sys.exit(2)


def main():
    if len(sys.argv) != 3:
        die("usage: validate.py <schema.json> <instance.json>")
    try:
        with open(sys.argv[1], encoding="utf-8") as handle:
            schema = json.load(handle)
        with open(sys.argv[2], encoding="utf-8") as handle:
            inst = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        die(error)

    try:
        V.check_schema(schema)
    except Exception as error:
        die(f"schema is not a valid draft 2020-12 schema: {error}")

    unenforceable = sorted(set(formats_used(schema)) - set(CHECKER.checkers))
    if unenforceable:
        die("this installation cannot assert these formats used by the schema: "
            + ", ".join(unenforceable)
            + ". Install the optional dependencies (pip install 'jsonschema[format]') and re-run. "
              "Reporting a pass without them would overstate what was checked.")

    try:
        errs = sorted(V(schema, format_checker=CHECKER).iter_errors(inst),
                      key=lambda e: [str(part) for part in e.path])
    except Exception as error:
        die(f"the schema could not be applied: {error}")

    stem = schema.get("$id", sys.argv[1]).rstrip("/").split("/")[-1]
    stem = stem[:-5] if stem.endswith(".json") else stem
    cross = [(rule_id, message)
             for rule_id, rule in CROSS_FIELD_RULES.get(stem, [])
             for message in [rule(inst)] if message]

    if not errs and not cross:
        print("VALID")
        sys.exit(0)
    for e in errs:
        print(f"[{e.validator}] {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
    for rule_id, message in cross:
        print(f"[{rule_id}] <root>: {message}")
    sys.exit(1)


if __name__ == "__main__":
    main()
