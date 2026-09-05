#!/usr/bin/env python3
"""OWHS reference validator (Level 1), for the v0.1 and v0.2 schemas.

Usage: python validate.py <schema.json> <instance.json> [--profile <envelope.json> ...]
Exit 0 instance valid, 1 instance invalid, 2 tool or schema error.

With --profile, each supplied profile envelope (profiles/profile-envelope.schema.json) is applied to the whole
instance after the core schema passes its own checks. The core always runs first and cannot be overridden by a
profile. An envelope whose core_schema_ids does not name the supplied core schema's $id is a configuration
error (2). Extension namespaces present on the instance that no supplied profile covers are reported as
"profile semantics not checked": the core validated their generic structure and nothing more. Every $ref and
$dynamicRef must resolve inside its own document (a JSON pointer, a named $anchor or $dynamicAnchor, or an
embedded $id resource); a URI is an identifier, not permission to fetch it, and the resolver's retrieval
function refuses every request. Set OWHS_ASSERT_NO_NETWORK=1 to make any socket open a hard failure.

Numbers must be finite. NaN and Infinity are not JSON values and a literal that overflows (1e999) is refused
when the instance is read, and non-finite numbers are refused recursively for instances built in memory.

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
import hashlib, math, os, re, socket, sys, json
from datetime import date
from pathlib import Path
from urllib.parse import urldefrag, urljoin

if os.environ.get("OWHS_ASSERT_NO_NETWORK"):
    class _NoNetwork(socket.socket):
        def __init__(self, *a, **k):
            raise RuntimeError("network access attempted; the validator never opens a socket")
    socket.socket = _NoNetwork

from jsonschema.validators import Draft202012Validator as V
from referencing import Registry
from referencing.exceptions import NoSuchResource


def _refuse_retrieval(uri):
    """The registry's only retrieval function: nothing is fetched, whatever the URI."""
    raise NoSuchResource(ref=uri)


REGISTRY = Registry(retrieve=_refuse_retrieval)
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


def _obj(value):
    return value if isinstance(value, dict) else {}


def window_ordered(inst):
    w = _obj(_obj(_obj(inst).get("scoringDescriptor")).get("observationWindow"))
    a, b = instant(w.get("start")), instant(w.get("end"))
    if a and b and b < a:
        return f"observationWindow end {w['end']!r} precedes start {w['start']!r} (compared as UTC instants)"
    return None


def native_scale(inst):
    ns = _obj(_obj(_obj(inst).get("scoringDescriptor")).get("nativeScale"))
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


def _int(v): return isinstance(v, int) and not isinstance(v, bool)


def ordering_dates(earlier, later, label):
    """C10 to C14: `later` not before `earlier`, compared as calendar dates. Evaluated only when both values are real ISO dates; a
    malformed date is the format check's finding, not a chronology finding."""
    from datetime import date
    def parse(v):
        try: return date.fromisoformat(v) if isinstance(v, str) else None
        except ValueError: return None
    def rule(inst):
        if not isinstance(inst, dict) or later not in inst or earlier not in inst: return None
        a, b = parse(inst[earlier]), parse(inst[later])
        if a is None or b is None: return None
        if b < a: return f"{later} {inst[later]!r} precedes {earlier} {inst[earlier]!r}"
        return None
    rule.__doc__ = label
    return rule


def utilisation_counts(inst):
    """C15: n <= usageCount + claimCount (an absent claimCount contributes no events); n = 0 only when both recorded event counts are 0.
    Compares declarations; it does not deduplicate people, and repeated events may exceed n."""
    if not isinstance(inst, dict): return None
    n, u, c = inst.get("n"), inst.get("usageCount"), inst.get("claimCount", 0)
    if not all(_int(v) and v >= 0 for v in (n, u, c)): return None          # a negative count is the schema's finding, not a rule's
    if n > u + c: return f"n {n} exceeds the recorded events usageCount {u} + claimCount {c}"
    if n == 0 and u + c > 0: return f"n is 0 while {u + c} event(s) are recorded"
    return None


def composition_counts(inst):
    """C16: composition.orgCount <= sampleSizes.people; observations, when supplied, >= people. Contributing units only."""
    c = _obj(_obj(inst).get("composition")); ss = _obj(c.get("sampleSizes"))
    o, n, obs = c.get("orgCount"), ss.get("people"), ss.get("observations")
    if any(_int(v) and v < 0 for v in (o, n, obs)): return None
    if _int(o) and _int(n) and o > n: return f"composition.orgCount {o} exceeds sampleSizes.people {n}"
    if _int(n) and _int(obs) and obs < n: return f"sampleSizes.observations {obs} is below people {n}"
    return None


def percentiles_ordered(inst):
    """C17: probabilities strictly increase in array order and values never decrease; ties in value and a single quantile are fine.
    No quantile algorithm or sampling distribution is verified."""
    vals = _obj(_obj(inst).get("percentiles")).get("values")
    if not isinstance(vals, list) or not all(isinstance(v, dict) for v in vals): return None
    for i, (a, b) in enumerate(zip(vals, vals[1:])):
        pa, pb, va, vb = a.get("probability"), b.get("probability"), a.get("value"), b.get("value")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (pa, pb, va, vb)): return None
        if pb <= pa: return f"percentiles.values[{i + 1}].probability {pb} does not exceed values[{i}].probability {pa}"
        if vb < va: return f"percentiles.values[{i + 1}].value {vb} is below values[{i}].value {va}"
    return None


def not_self_parent(inst):
    """C18: parentUnitId, if supplied, differs from unitId. The direct self-loop only; longer cycles need a supplied graph checker."""
    if not isinstance(inst, dict) or "parentUnitId" not in inst: return None
    if isinstance(inst.get("unitId"), str) and inst.get("parentUnitId") == inst["unitId"]: return f"parentUnitId equals unitId {inst['unitId']!r}"
    return None


CROSS_FIELD_RULES = {
    "ReasonableAdjustment": [("C10", ordering_dates("startDate", "endDate", "endDate not before startDate, when both are present"))],
    "BenefitUtilisation": [("C11", ordering_dates("periodStart", "periodEnd", "periodEnd not before periodStart")),
                           ("C15", rule_fn("n within recorded events; n = 0 only with no events", utilisation_counts))],
    "DisabilityParticipation": [("C12", ordering_dates("periodStart", "periodEnd", "periodEnd not before periodStart"))],
    "BenchmarkRelease": [("C13", ordering_dates("validFrom", "validTo", "validTo not before validFrom")),
                         ("C14", ordering_dates("dataPeriodStart", "dataPeriodEnd", "dataPeriodEnd not before dataPeriodStart")),
                         ("C16", rule_fn("orgCount <= people <= observations", composition_counts)),
                         ("C17", rule_fn("percentile probabilities strictly increasing, values non-decreasing", percentiles_ordered))],
    "OrgUnit": [("C18", rule_fn("parentUnitId is not unitId", not_self_parent))],
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
ANCHOR = re.compile(r"^[A-Za-z_][-A-Za-z0-9._]*$")
NOT_SCHEMA_KEYS = ("enum", "const", "examples", "default")     # values here are data, not schema, so a "$ref" key inside them is not a reference


def refs_used(node):
    """Every $ref and $dynamicRef anywhere in the schema, used branches and unused alike."""
    if isinstance(node, dict):
        for key in ("$ref", "$dynamicRef"):
            if isinstance(node.get(key), str):
                yield node[key]
        for key, value in node.items():
            if key not in NOT_SCHEMA_KEYS:
                yield from refs_used(value)
    elif isinstance(node, list):
        for value in node:
            yield from refs_used(value)


def resources(schema, base=""):
    """uri -> subschema for the root and every embedded $id, each resolved against its enclosing resource."""
    out = {}
    def walk(node, scope):
        if isinstance(node, dict):
            if isinstance(node.get("$id"), str):
                scope = urldefrag(urljoin(scope, node["$id"]))[0]
                out.setdefault(scope, node)
            for key, value in node.items():
                if key not in NOT_SCHEMA_KEYS:
                    walk(value, scope)
        elif isinstance(node, list):
            for value in node:
                walk(value, scope)
    root_id = urldefrag(urljoin(base, schema["$id"]))[0] if isinstance(schema, dict) and isinstance(schema.get("$id"), str) else ""
    out[root_id] = schema
    walk(schema, root_id)
    return root_id, out


def anchors(node):
    """Every named $anchor and $dynamicAnchor in a resource."""
    if isinstance(node, dict):
        for key in ("$anchor", "$dynamicAnchor"):
            if isinstance(node.get(key), str):
                yield node[key]
        for key, value in node.items():
            if key not in NOT_SCHEMA_KEYS:
                yield from anchors(value)
    elif isinstance(node, list):
        for value in node:
            yield from anchors(value)


def pointer_resolves(node, pointer):
    for part in [p for p in pointer.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False
    return True


def resolve_local(schema, ref):
    """True when the reference resolves inside the document: a JSON pointer or a named anchor within the root
    resource or an embedded $id resource. Anything else is refused without being fetched."""
    root_id, res = resources(schema)
    target, fragment = urldefrag(urljoin(root_id, ref)) if not ref.startswith("#") else (root_id, ref[1:])
    if target not in res:
        return False
    node = res[target]
    if fragment == "":
        return True
    if fragment.startswith("/"):
        return pointer_resolves(node, fragment)
    return bool(ANCHOR.match(fragment)) and fragment in set(anchors(node))


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


def _reject_constant(name):
    raise ValueError(f"{name} is not a JSON value")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"numeric literal {text} is not a finite number")
    return value


def loads_strict(text):
    """JSON with the standard's grammar only: NaN, Infinity and -Infinity are refused, and a literal that
    overflows to infinity is refused. Raises ValueError (JSONDecodeError is a subclass)."""
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def non_finite_paths(node, path=""):
    """Paths of every non-finite number in an in-memory instance; a boolean is not a number."""
    if isinstance(node, bool):
        return
    if isinstance(node, float) and not math.isfinite(node):
        yield path or "<root>"
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from non_finite_paths(value, f"{path}/{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from non_finite_paths(value, f"{path}/{index}" if path else str(index))


def load_json(path):
    """A schema or profile file: a reading problem is a tool error."""
    try:
        return loads_strict(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        die(f"{path}: {error}")


def load_instance(path):
    """The instance file: a reading problem is an invalid instance with a diagnostic, exit 1."""
    try:
        return loads_strict(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        die(f"{path}: {error}")
    except ValueError as error:
        print(f"[json] <root>: {error}")
        sys.exit(1)


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
    schema, inst = load_json(args[0]), load_instance(args[1])
    preflight(schema, "schema")

    try:
        errs = sorted(V(schema, format_checker=CHECKER, registry=REGISTRY).iter_errors(inst),
                      key=lambda e: [str(part) for part in e.path])
    except Exception as error:
        die(f"the schema could not be applied: {error}")
    errs = [(e.validator, "/".join(map(str, e.path)) or "<root>", e.message) for e in errs]
    errs += [("number", path, "not a finite number") for path in non_finite_paths(inst)]

    stem = schema.get("$id", args[0]).rstrip("/").split("/")[-1]
    stem = stem[:-5] if stem.endswith(".json") else stem
    cross = []
    for rule_id, rule in CROSS_FIELD_RULES.get(stem, []):
        try:
            message = rule(inst)
        except (TypeError, AttributeError, KeyError, ValueError) as error:
            if not errs:
                die(f"rule {rule_id} failed on a structurally valid instance: {error!r}")
            message = "not evaluated: its operands failed structural validation (see the errors above)"
        if message:
            cross.append((rule_id, message))

    # Profiles: applied to the whole instance after the core; the core's verdict is never overridden.
    profile_lines, covered = [], {}
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
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            covered[env["profile_id"]] = f"{env['profile_id']}@{env['version']} (envelope sha256 {digest})"
            try:
                found = sorted(V(env["schema"], format_checker=CHECKER, registry=REGISTRY).iter_errors(inst), key=lambda e: [str(part) for part in e.path])
            except Exception as error:
                die(f"profile {env['profile_id']} {env['version']} could not be applied: {error}")
            for e in found:
                profile_lines.append(f"[profile:{env['profile_id']}@{env['version']}] {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
    ext = inst.get("ext") if isinstance(inst, dict) else None
    unchecked = sorted(k for k in ext if k not in covered) if isinstance(ext, dict) else []

    if not errs and not cross and not profile_lines:
        print("VALID" + (f" (profiles checked: {'; '.join(covered[k] for k in sorted(covered))})" if covered else ""))
        for k in unchecked:
            print(f"[profile] ext/{k}: profile semantics not checked")
        sys.exit(0)
    for validator, where, message in errs:
        print(f"[{validator}] {where}: {message}")
    for rule_id, message in cross:
        print(f"[{rule_id}] <root>: {message}")
    for line in profile_lines:
        print(line)
    for k in sorted(covered):
        print(f"[profile] {covered[k]} checked")
    for k in unchecked:
        print(f"[profile] ext/{k}: profile semantics not checked")
    sys.exit(1)


if __name__ == "__main__":
    main()
