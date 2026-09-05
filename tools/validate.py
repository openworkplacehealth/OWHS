#!/usr/bin/env python3
"""OWHS reference validator (Level 1), for the v0.1 and v0.2 schemas.

Usage: python validate.py <schema.json> <instance.json> [--profile <envelope.json> ...]
Exit 0 instance valid, 1 instance invalid, 2 tool or schema error.

With --profile, each supplied profile envelope (profiles/profile-envelope.schema.json) is applied to the whole
instance after the core schema passes its own checks. The core always runs first and cannot be overridden by a
profile. An envelope whose core_schema_ids does not name the supplied core schema's $id is a configuration
error (2). Extension namespaces present on the instance that no supplied profile covers are reported as
"profile semantics not checked": the core validated their generic structure and nothing more. Every $ref must
be local to its document; nothing is fetched from the network.

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
from pathlib import Path
from jsonschema.validators import Draft202012Validator as V

CHECKER = V.FORMAT_CHECKER
ROOT_PROFILES = Path(__file__).resolve().parents[1] / "profiles"
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


def instant(value):
    """A date-time with an asserted zone as a UTC datetime, or None."""
    from datetime import datetime, timezone
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def rule_fn(label, fn):
    fn.__doc__ = label
    return fn


def window_ordered(inst):
    w = ((inst.get("scoringDescriptor") or {}).get("observationWindow") or {}) if isinstance(inst, dict) else {}
    a, b = instant(w.get("start")), instant(w.get("end"))
    if a and b and b < a:
        return f"observationWindow end {w['end']!r} precedes start {w['start']!r} (compared as UTC instants)"
    return None


def native_scale(inst):
    ns = ((inst.get("scoringDescriptor") or {}).get("nativeScale") or {}) if isinstance(inst, dict) else {}
    lo, hi = ns.get("min"), ns.get("max")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and not isinstance(lo, bool) and not isinstance(hi, bool) and not lo < hi:
        return f"nativeScale min {lo!r} is not below max {hi!r}"
    return None


def interval_ordered(inst):
    iv = inst.get("interval") if isinstance(inst, dict) else None
    if isinstance(iv, dict) and all(isinstance(iv.get(k), (int, float)) and not isinstance(iv.get(k), bool) for k in ("low", "high")) and iv["low"] > iv["high"]:
        return f"interval low {iv['low']!r} exceeds high {iv['high']!r}"
    return None


def counts_nested(inst):
    if not isinstance(inst, dict):
        return None
    n, e, h = inst.get("n"), inst.get("eligibleN"), inst.get("headcount")
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (n, e, h))
    if ints and not n <= e <= h:
        return f"n {n} <= eligibleN {e} <= headcount {h} does not hold"
    return None


def observations_at_least_n(inst):
    if not isinstance(inst, dict) or "observationCount" not in inst:
        return None
    n, o = inst.get("n"), inst.get("observationCount")
    if all(isinstance(v, int) and not isinstance(v, bool) for v in (n, o)) and o < n:
        return f"observationCount {o} is below n {n}"
    return None


def completion_rate(inst):
    if not isinstance(inst, dict):
        return None
    n, e, r = inst.get("n"), inst.get("eligibleN"), inst.get("completionRate")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (n, e)):
        return None
    if e == 0:
        return None if r is None else f"completionRate must be null when eligibleN is 0, got {r!r}"
    if r is None:
        return "completionRate is null although eligibleN is above 0"
    if isinstance(r, (int, float)) and abs(r - n / e) > 1e-9:
        return f"completionRate {r!r} is not n/eligibleN = {n / e:.10g}"
    return None


CROSS_FIELD_RULES = {
    "AbsenceEpisode": [("C1", ordering("startDate", "endDate", "endDate not before startDate"))],
    "OHEpisode": [("C2", ordering("referralDate", "assessmentDate", "assessmentDate not before referralDate"))],
    "AggregateReport": [("C3", ordering("periodStart", "periodEnd", "periodEnd not before periodStart")),
                        ("C6", rule_fn("interval low not above high", interval_ordered)),
                        ("C7", rule_fn("n <= eligibleN <= headcount", counts_nested)),
                        ("C8", rule_fn("observationCount not below n", observations_at_least_n)),
                        ("C9", rule_fn("completionRate is n/eligibleN, null only when eligibleN is 0", completion_rate))],
    "MeasurementContext": [("C4", rule_fn("observationWindow ordered as UTC instants", window_ordered)),
                           ("C5", rule_fn("nativeScale min below max", native_scale))],
}

NAMESPACE = re.compile(r"^owhs-[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def refs_used(node):
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            yield node["$ref"]
        for value in node.values():
            yield from refs_used(value)
    elif isinstance(node, list):
        for value in node:
            yield from refs_used(value)


def resolve_local(schema, ref):
    """A local JSON-pointer reference resolves within its own document, or it is a tool error. Nothing is fetched."""
    if not ref.startswith("#"):
        return False
    node = schema
    for part in [p for p in ref[1:].split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False
    return True


def preflight(schema, what):
    """Refuse to run rather than report a pass the installation cannot stand behind."""
    try:
        V.check_schema(schema)
    except Exception as error:
        die(f"{what} is not a valid draft 2020-12 schema: {error}")
    unenforceable = sorted(set(formats_used(schema)) - set(CHECKER.checkers))
    if unenforceable:
        die(f"this installation cannot assert these formats used by {what}: " + ", ".join(unenforceable)
            + ". Install the optional dependencies (pip install 'jsonschema[format]') and re-run. "
              "Reporting a pass without them would overstate what was checked.")
    bad = sorted({r for r in refs_used(schema) if not resolve_local(schema, r)})
    if bad:
        die(f"{what} carries references that do not resolve locally (nothing is fetched): " + ", ".join(bad))


def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        die(error)


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
    args = sys.argv[1:]
    profiles = []
    while "--profile" in args:
        k = args.index("--profile")
        if k + 1 >= len(args):
            die("--profile needs a path")
        profiles.append(args[k + 1]); del args[k:k + 2]
    if len(args) != 2:
        die("usage: validate.py <schema.json> <instance.json> [--profile <envelope.json> ...]")
    schema, inst = load_json(args[0]), load_json(args[1])
    preflight(schema, "schema")

    try:
        errs = sorted(V(schema, format_checker=CHECKER).iter_errors(inst),
                      key=lambda e: [str(part) for part in e.path])
    except Exception as error:
        die(f"the schema could not be applied: {error}")

    stem = schema.get("$id", args[0]).rstrip("/").split("/")[-1]
    stem = stem[:-5] if stem.endswith(".json") else stem
    cross = [(rule_id, message)
             for rule_id, rule in CROSS_FIELD_RULES.get(stem, [])
             for message in [rule(inst)] if message]

    # Profiles: applied to the whole instance after the core; the core's verdict is never overridden.
    profile_lines, covered = [], set()
    if profiles:
        env_schema_path = ROOT_PROFILES / "profile-envelope.schema.json"
        env_schema = load_json(env_schema_path)
        preflight(env_schema, "the profile envelope schema")
        seen = {}
        for path in profiles:
            env = load_json(path)
            env_errs = list(V(env_schema, format_checker=CHECKER).iter_errors(env))
            if env_errs:
                die(f"profile envelope {path} is malformed: " + "; ".join(e.message for e in env_errs[:3]))
            key = (env["profile_id"], env["version"])
            if key in seen and seen[key] != env:
                die(f"two different envelopes supplied for profile {key[0]} {key[1]}")
            seen[key] = env
            if schema.get("$id") not in env["core_schema_ids"]:
                die(f"profile {env['profile_id']} {env['version']} targets {env['core_schema_ids']}, not this core schema {schema.get('$id')!r}")
            preflight(env["schema"], f"profile {env['profile_id']} schema")
            covered.add(env["profile_id"])
            for e in sorted(V(env["schema"], format_checker=CHECKER).iter_errors(inst), key=lambda e: [str(part) for part in e.path]):
                profile_lines.append(f"[profile:{env['profile_id']}@{env['version']}] {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
    unchecked = sorted(k for k in (inst.get("ext") or {}) if isinstance(inst, dict) and isinstance(inst.get("ext"), dict) and k not in covered)

    if not errs and not cross and not profile_lines:
        print("VALID" + (f" (profiles checked: {', '.join(sorted(covered))})" if covered else ""))
        for k in unchecked:
            print(f"[profile] ext/{k}: profile semantics not checked")
        sys.exit(0)
    for e in errs:
        print(f"[{e.validator}] {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
    for rule_id, message in cross:
        print(f"[{rule_id}] <root>: {message}")
    for line in profile_lines:
        print(line)
    for k in unchecked:
        print(f"[profile] ext/{k}: profile semantics not checked")
    sys.exit(1)


if __name__ == "__main__":
    main()
