"""Bridge between the browser checker page (site/check/) and the repository's own command-line tools.

The page writes the visitor's file into this interpreter's in-memory file system and calls owhs_check(). The verdict
always comes from the repository's tools, unchanged and run through their command-line entry points:

    record   tools/validate.py main() with argv [validate.py, schemas/v0.2/<Entity>.json, <file>]
    bundle   tools/check_entity_graph.py main([<file>])

Their printed output and exit code are returned exactly as the command line would show them. explain() then adds
plain-English detail for the page (the schema location and description of each finding). It never changes the
verdict, the list of findings or their wording, and it is skipped if it cannot be matched one to one.

Pyodide cannot start a process. tools/check_measurement.py, which tools/check_entity_graph.py runs for its S07
checks, starts tools/validate.py as a separate process for each measurement record. That one call shape is served
in this interpreter by the same validate.main() with the same arguments; any other process start raises.
"""
import contextlib, io, json, os, subprocess, sys

os.environ["OWHS_ASSERT_NO_NETWORK"] = "1"       # validate.py then refuses to open any socket
ROOT = "/owhs"
TOOLS = ROOT + "/tools"
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
sys.dont_write_bytecode = True


def _run(fn, argv):
    """Call a command-line entry point as the shell would: argv set, stdout and stderr captured, the exit code taken
    from SystemExit or the return value."""
    out, err, old = io.StringIO(), io.StringIO(), sys.argv
    sys.argv = list(argv)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                result = fn()
                code = result if isinstance(result, int) else 0
            except SystemExit as e:
                if e.code is None: code = 0
                elif isinstance(e.code, int): code = e.code
                else: print(e.code, file=sys.stderr); code = 1
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


_real_run = subprocess.run


def _in_process_run(args, *a, **k):
    """Only the validator call tools/check_measurement.py makes: [python, tools/validate.py, schema, instance]."""
    args = [str(x) for x in args]
    if len(args) == 4 and args[1] == TOOLS + "/validate.py":
        import validate
        code, out, err = _run(validate.main, args[1:])
        return subprocess.CompletedProcess(args, code, out, err)
    raise OSError("this checker cannot start a process: " + " ".join(args[:2]))


subprocess.run = _in_process_run


def _describe_if(cond):
    """A short reading of a simple if-condition: properties with const, enum or a bound, and required fields."""
    if not isinstance(cond, dict): return None
    parts = []
    for name, sub in (cond.get("properties") or {}).items():
        if not isinstance(sub, dict): continue
        if "const" in sub: parts.append(f"{name} is {json.dumps(sub['const'])}")
        if "enum" in sub: parts.append(f"{name} is one of {', '.join(json.dumps(v) for v in sub['enum'])}")
        for key, words in (("maximum", "at most"), ("minimum", "at least"), ("exclusiveMaximum", "below"), ("exclusiveMinimum", "above")):
            if key in sub: parts.append(f"{name} is {words} {json.dumps(sub[key])}")
    for name in cond.get("required") or []:
        if not any(p.startswith(name + " ") for p in parts): parts.append(f"{name} is present")
    return " and ".join(parts) or None


def _forbidden(sub):
    """Field names a not-subschema forbids, when it is a required list or an anyOf of required lists."""
    if not isinstance(sub, dict): return []
    if list(sub) == ["required"]: return list(sub["required"])
    if list(sub) == ["anyOf"] and all(isinstance(x, dict) and list(x) == ["required"] for x in sub["anyOf"]):
        return [n for x in sub["anyOf"] for n in x["required"]]
    return []


def _detail(schema, e):
    """Plain facts about one jsonschema error: where in the schema it fired and what that part of the schema says."""
    from jsonschema.exceptions import best_match
    sp = list(e.absolute_schema_path)
    node, nodes = schema, [schema]
    for part in sp[:-1]:
        try: node = node[part]; nodes.append(node)
        except (KeyError, IndexError, TypeError): break
    description = None
    for n in reversed(nodes[1:]):                          # the record type's own description is not a reading of one finding
        if isinstance(n, dict) and isinstance(n.get("description"), str):
            description = n["description"]; break
    d = {"keyword": e.validator, "path": [str(p) for p in e.absolute_path], "schema_path": "/".join(str(p) for p in sp), "description": description}
    if e.validator == "not":
        sub = e.validator_value
        forbidden = _forbidden(sub)
        if forbidden: d["forbidden_fields"] = forbidden
        if isinstance(sub, dict) and list(sub) == ["pattern"] and sub["pattern"] == "\\s": d["no_whitespace"] = True
        if isinstance(sub, dict) and list(sub) == ["enum"] and "propertyNames" in sp: d["banned_keys"] = list(sub["enum"])
    branch = max((i for i, p in enumerate(sp) if p in ("then", "else")), default=None)
    if branch is not None and branch < len(nodes) and isinstance(nodes[branch], dict) and "if" in nodes[branch]:
        cond = _describe_if(nodes[branch]["if"])          # nodes[branch] is the object carrying if/then/else
        if cond: d["condition"] = ("when " if sp[branch] == "then" else "unless ") + cond
    if e.validator in ("anyOf", "oneOf") and e.context:
        bm = best_match(e.context)
        d["closest"] = {"keyword": bm.validator, "path": [str(p) for p in bm.absolute_path], "message": bm.message[:300]}
    if e.validator == "enum" and isinstance(e.validator_value, list): d["allowed"] = e.validator_value[:40]
    if e.validator == "format": d["format"] = e.validator_value
    if e.validator == "required":
        d["missing"] = e.message.split("'")[1] if e.message.count("'") >= 2 else None
    return d


def explain(entity, path, findings):
    """Details for the schema findings of a record, in the order validate.py printed them, or [] when they cannot be
    matched one to one with the printed lines."""
    try:
        import validate
        schema = validate.load_json(f"{ROOT}/schemas/v0.2/{entity}.json")
        inst = validate.loads_strict(open(path, encoding="utf-8").read())
        errs = sorted(validate.V(schema, format_checker=validate.CHECKER, registry=validate.REGISTRY).iter_errors(inst),
                      key=lambda e: [str(part) for part in e.path])
        if len(errs) != len(findings) or any(str(e.validator) != f for e, f in zip(errs, findings)): return []
        return [_detail(schema, e) for e in errs]
    except BaseException:
        return []


def owhs_check(kind, path):
    if kind == "bundle":
        import check_entity_graph
        code, out, err = _run(lambda: check_entity_graph.main([path]), [TOOLS + "/check_entity_graph.py", path])
        return json.dumps({"tool": "tools/check_entity_graph.py", "argv": ["tools/check_entity_graph.py", "<your file>"], "exit_code": code, "stdout": out, "stderr": err})
    import validate
    schema = f"{ROOT}/schemas/v0.2/{kind}.json"
    if not os.path.exists(schema):
        return json.dumps({"tool": "tools/validate.py", "exit_code": 2, "stdout": "", "stderr": f"[tool] no v0.2 schema named {kind}"})
    code, out, err = _run(validate.main, [TOOLS + "/validate.py", schema, path])
    lines = [l for l in out.splitlines() if l.startswith("[")]
    schema_findings = [l[1:l.index("]")] for l in lines if not l.startswith(("[profile]", "[json]", "[number]")) and not l[1:2] == "C"]
    details = explain(kind, path, schema_findings) if code == 1 and schema_findings else []
    return json.dumps({"tool": "tools/validate.py", "argv": ["tools/validate.py", f"schemas/v0.2/{kind}.json", "<your file>"], "exit_code": code, "stdout": out, "stderr": err, "details": details})


def owhs_verify(expected_json):
    """Paths whose bytes in the in-memory file system do not have the SHA-256 the build recorded for them."""
    import hashlib
    bad = []
    for path, digest in json.loads(expected_json).items():
        try:
            with open(f"{ROOT}/{path}", "rb") as f: ok = hashlib.sha256(f.read()).hexdigest() == digest
        except OSError: ok = False
        if not ok: bad.append(path)
    return json.dumps(bad)


def owhs_versions():
    import jsonschema, platform
    from importlib.metadata import version
    return json.dumps({"python": platform.python_version(), "jsonschema": version("jsonschema"), "referencing": version("referencing"),
                       "rfc3339-validator": version("rfc3339-validator"), "rfc3987": version("rfc3987")})
