#!/usr/bin/env python3
"""The browser checker at site/check/: its page, its data and the copies of the repository's tools it runs, with a check in CI.

    python tools/build_checker.py              # write site/check/index.html, checker-data.json, engine-files.json and vendor/MANIFEST.json
    python tools/build_checker.py --check      # regenerate in memory (the page stamped in a temporary copy of site/), compare; verify every vendored file
    python tools/build_checker.py --fetch      # (maintainers, needs the network) download every pinned vendored file and verify its hash
    python tools/build_checker.py --self-test

The page runs the repository's own tools in the visitor's browser, in Python compiled to WebAssembly (Pyodide), so its
verdicts are the reference validator's. What it runs is generated here and nowhere else:

  engine-files.json   tools/validate.py, tools/check_entity_graph.py and tools/check_measurement.py, the sixteen v0.2
                      schemas, the entity-graph envelope and the profile-envelope schema, byte for byte, keyed by their
                      repository paths, which is where the page writes them in its in-memory file system
  checker-data.json   what the page shows before anything heavy loads: the record types and their fields (for detecting
                      the type of a pasted record), the spec's field-table rows, the statements of C1 to C18 (from the
                      specification) and G01 to G10 (from the entity-graph guide), links to the spec sections, the
                      synthetic samples (copied from examples/), the versions and the hashes of every tool copied
  index.html          tools/check_template.html with the counts, versions and sizes computed from the files
  vendor/MANIFEST.json  every vendored file (Pyodide, the Python wheels, the two fonts) with its upstream URL, version,
                      SHA-256 and licence; --check fails on a changed, missing or unlisted vendored file

Nothing here is fetched at run time from anywhere but the site itself. tools/check_browser_checker.py is the parity test:
it runs every fixture through the reference tools and through this page in headless Chrome and fails on any difference.
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
CHECK = ROOT / "site" / "check"
VENDOR = CHECK / "vendor"
TEMPLATE = ROOT / "tools" / "check_template.html"
CHECKER_VERSION = "1.0.0"
SCHEMA_VERSION = "0.2"
PYODIDE_VERSION = "314.0.7"
PYODIDE_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"

# Every vendored file: (path under vendor/, upstream URL, sha256, licence, licence file under vendor/, loaded when).
# The wheels are the ones Pyodide publishes for this release, except rfc3339-validator and rfc3986-validator, which are
# pure-Python wheels from PyPI: jsonschema asserts the date-time and uri formats only when they are installed, as
# requirements.txt's jsonschema[format-nongpl] installs them for the command-line validator. Nothing vendored is GPL.
PINS = [
    ("pyodide/pyodide.mjs", PYODIDE_URL + "pyodide.mjs", "6f1d60f7bf529beb300f0f47983c921d3982363640ba20af0e38efdddbc66109", "MPL-2.0", "pyodide/LICENSE-Pyodide.txt", "check"),
    ("pyodide/pyodide.asm.mjs", PYODIDE_URL + "pyodide.asm.mjs", "f7cdc8ece80678ceb712f8e65ebe6d3a83203a180c399865f49612a051693635", "MPL-2.0 (with Emscripten runtime, MIT)", "pyodide/LICENSE-Emscripten.txt", "check"),
    ("pyodide/pyodide.asm.wasm", PYODIDE_URL + "pyodide.asm.wasm", "cc36e3cab04fdfc9a63ff13eb52eae2b911bf46c025cc7b281f394bd3de1d5e6", "MPL-2.0 (CPython 3.14, PSF)", "pyodide/LICENSE-CPython.txt", "check"),
    ("pyodide/python_stdlib.zip", PYODIDE_URL + "python_stdlib.zip", "fa1957e5777068fc4f7437f96d860ae2fbe9c19732ba06c84e004ec16dd7dd7a", "PSF-2.0", "pyodide/LICENSE-CPython.txt", "check"),
    ("pyodide/pyodide-lock.json", PYODIDE_URL + "pyodide-lock.json", "5dc2fc119108bc148c7457dc86e7675b5c87e1cafd420b9c34c1eaef7b36c010", "MPL-2.0", "pyodide/LICENSE-Pyodide.txt", "check"),
    ("pyodide/LICENSE-Pyodide.txt", f"https://raw.githubusercontent.com/pyodide/pyodide/{PYODIDE_VERSION}/LICENSE", None, "licence text", None, "never"),
    ("pyodide/LICENSE-CPython.txt", "https://raw.githubusercontent.com/python/cpython/v3.14.2/LICENSE", None, "licence text", None, "never"),
    ("pyodide/LICENSE-Emscripten.txt", "https://raw.githubusercontent.com/emscripten-core/emscripten/5.0.3/LICENSE", None, "licence text", None, "never"),
    ("wheels/six-1.17.0-py2.py3-none-any.whl", PYODIDE_URL + "six-1.17.0-py2.py3-none-any.whl", "228c50f73aa7", "MIT", "inside the wheel", "check"),
    ("wheels/typing_extensions-4.15.0-py3-none-any.whl", PYODIDE_URL + "typing_extensions-4.15.0-py3-none-any.whl", "4fec68770a05", "PSF-2.0", "inside the wheel", "check"),
    ("wheels/attrs-26.1.0-py3-none-any.whl", PYODIDE_URL + "attrs-26.1.0-py3-none-any.whl", "0506ebb8e46c", "MIT", "inside the wheel", "check"),
    ("wheels/rpds_py-0.30.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl", PYODIDE_URL + "rpds_py-0.30.0-cp314-cp314-pyemscripten_2026_0_wasm32.whl", "9997dcfaee44", "MIT", "inside the wheel", "check"),
    ("wheels/referencing-0.37.0-py3-none-any.whl", PYODIDE_URL + "referencing-0.37.0-py3-none-any.whl", "db67659fe2ec", "MIT", "inside the wheel", "check"),
    ("wheels/jsonschema_specifications-2025.9.1-py3-none-any.whl", PYODIDE_URL + "jsonschema_specifications-2025.9.1-py3-none-any.whl", "8e4353ea148a", "MIT", "inside the wheel", "check"),
    ("wheels/jsonschema-4.26.0-py3-none-any.whl", PYODIDE_URL + "jsonschema-4.26.0-py3-none-any.whl", "7ce77bd37ad1", "MIT", "inside the wheel", "check"),
    ("wheels/rfc3339_validator-0.1.4-py2.py3-none-any.whl", "https://files.pythonhosted.org/packages/py2.py3/r/rfc3339-validator/rfc3339_validator-0.1.4-py2.py3-none-any.whl", None, "MIT", "inside the wheel", "check"),
    ("wheels/rfc3986_validator-0.1.1-py2.py3-none-any.whl", "https://files.pythonhosted.org/packages/py2.py3/r/rfc3986-validator/rfc3986_validator-0.1.1-py2.py3-none-any.whl", "2f235c432ef459970b4306369336b9d5dbdda31b510ca1e327636e01f528bfa9", "MIT", "inside the wheel", "check"),
    ("fonts/inter-latin.woff2", "https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1ZL7W0Q5nw.woff2", None, "OFL-1.1", "fonts/LICENSE-Inter-OFL.txt", "page"),
    ("fonts/plexmono-400-latin.woff2", "https://fonts.gstatic.com/s/ibmplexmono/v23/-F63fjptAgt5VM-kVkqdyU8n1i8q131nj-o.woff2", None, "OFL-1.1", "fonts/LICENSE-IBM-Plex-OFL.txt", "page"),
    ("fonts/plexmono-500-latin.woff2", "https://fonts.gstatic.com/s/ibmplexmono/v23/-F6qfjptAgt5VM-kVkqdyU8n3twJwlBFgsAXHNk.woff2", None, "OFL-1.1", "fonts/LICENSE-IBM-Plex-OFL.txt", "page"),
    ("fonts/LICENSE-Inter-OFL.txt", "https://raw.githubusercontent.com/rsms/inter/master/LICENSE.txt", None, "licence text", None, "never"),
    ("fonts/LICENSE-IBM-Plex-OFL.txt", "https://raw.githubusercontent.com/IBM/plex/master/LICENSE.txt", None, "licence text", None, "never"),
]
# The full SHA-256 of every vendored file, recorded when it was vendored. A prefix in PINS above is the hash Pyodide's own
# lock file publishes for that wheel, which the manifest check also confirms against the vendored pyodide-lock.json.
HASHES_FILE = VENDOR / "MANIFEST.json"

ENGINE_FILES = ["tools/validate.py", "tools/check_entity_graph.py", "tools/check_measurement.py",
                "schemas/bundles/EntityGraph-v0.2.json", "profiles/profile-envelope.schema.json"]
ENTITY_ORDER = ["Organisation", "OrgUnit", "WorkerPseudonym", "AbsenceEpisode", "ReturnToWorkOutcome", "OHEpisode", "ReasonableAdjustment",
                "BenefitEntitlement", "BenefitUtilisation", "DisabilityParticipation", "MeasurementContext", "WellbeingObservation",
                "InstrumentAdministration", "AggregateReport", "BenchmarkRelease", "Crosswalk"]
# The synthetic samples offered on the page: (label, file under examples/, kind). Copied from the committed fixtures, never written here.
SAMPLES = [
    ("Absence episode that passes", "v0.2/AbsenceEpisode.valid.json", "AbsenceEpisode", "pass"),
    ("Absence episode with four problems", "v0.2/AbsenceEpisode.invalid.json", "AbsenceEpisode", "fail"),
    ("Aggregate report that passes", "v0.2/AggregateReport.valid.json", "AggregateReport", "pass"),
    ("Aggregate report of four people, not suppressed", "v0.2/AggregateReport.n4-unsuppressed.invalid.json", "AggregateReport", "fail"),
    ("OH episode with a clinical key", "v0.2/OHEpisode.ext-clinical-key.invalid.json", "OHEpisode", "fail"),
    ("Unit that is its own parent", "v0.2/OrgUnit.self-parent.invalid.json", "OrgUnit", "fail"),
    ("Bundle of all sixteen record types that passes", "bundles/v0.2/EntityGraph.valid.json", "bundle", "pass"),
    ("Bundle with a return before its absence began", "bundles/v0.2/cases/return-before-absence-start.json", "bundle", "fail"),
]
SPEC = "/spec/"
LINKS = {"level1": SPEC + "#level-1-schema-valid", "levels": SPEC + "#conformance-levels", "rules": SPEC + "#named-within-record-rules",
         "privacy": SPEC + "#the-privacy-profile-normative", "boundary": SPEC + "#privacy-and-boundary-rules-expressed-in-schema",
         "profiles": SPEC + "#the-profile-mechanism", "graph": "/entity-graph-validation.html", "identifiers": SPEC + "#identifiers-and-pseudonymisation"}


def sha(path_or_bytes):
    b = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    return hashlib.sha256(b).hexdigest()


def clean_cell(text):
    t = text.strip().replace("**", "")
    t = re.sub(r"`([^`]*)`", r"\1", t)
    return t.strip()


def spec_facts(root=ROOT):
    """Field-table rows per entity, the C1 to C18 statements and each entity's section anchor, read from the specification."""
    from build_spec_page import pandoc_slug
    text = (root / "spec" / "OWHS-v0.2-draft.md").read_text(encoding="utf-8")
    fields, anchors, current = {}, {}, None
    for line in text.splitlines():
        h = re.match(r"^### (\w+)(?: \(new in v0\.2\))?\s*$", line)
        if h and h.group(1) in ENTITY_ORDER:
            current = h.group(1); anchors[current] = SPEC + "#" + pandoc_slug(line[4:]); fields[current] = {}; continue
        if line.startswith("## "): current = None
        if current and line.startswith("| `"):
            cells = line.strip().strip("|").split("|")
            if len(cells) >= 6:
                name = clean_cell(cells[0])
                fields[current][name] = {"type": clean_cell(cells[1]), "required": clean_cell(cells[2]) == "yes", "codelist": clean_cell(cells[3]).rstrip("."),
                                         "privacy": clean_cell(cells[4]), "anchor": clean_cell("|".join(cells[5:]))}
    rules = {}
    for m in re.finditer(r"^\| (C\d+) \| `(\w+)` \| (.+?) \|\s*$", text, re.M):
        rules.setdefault(m.group(1), {"entity": m.group(2), "statement": clean_cell(m.group(3)), "source": "specification, section 9, Level 1", "link": LINKS["rules"]})
    doc = (root / "docs" / "entity-graph-validation-v0.2.md").read_text(encoding="utf-8")
    for m in re.finditer(r"^\| (G\d\d) \| (.+?) \|\s*$", doc, re.M):
        rules.setdefault(m.group(1), {"entity": None, "statement": clean_cell(m.group(2)), "source": "supplied-entity graph guide", "link": LINKS["graph"]})
    missing = [e for e in ENTITY_ORDER if e not in fields or not fields[e]]
    if missing: raise SystemExit(f"specification field tables not found for: {', '.join(missing)}")
    want = [f"C{i}" for i in range(1, 19)] + [f"G{i:02d}" for i in range(1, 11)]
    if [r for r in want if r not in rules]: raise SystemExit(f"rule statements not found: {[r for r in want if r not in rules]}")
    return fields, anchors, {k: rules[k] for k in want}


def wheel_versions():
    out = {}
    for p, *_ in PINS:
        m = re.match(r"wheels/([A-Za-z0-9_]+)-([0-9][^-]*)-", p)
        if m: out[m.group(1).replace("_", "-")] = m.group(2)
    return out


def engine_files(root=ROOT):
    paths = ENGINE_FILES[:3] + [f"schemas/v0.2/{e}.json" for e in ENTITY_ORDER] + ENGINE_FILES[3:]
    files = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    return {"note": "Copies of repository files, byte for byte, generated by tools/build_checker.py. The page writes each one to /owhs/<path> in the browser's in-memory file system and runs the tools from there.",
            "files": files, "sha256": {p: sha((root / p).read_bytes()) for p in paths}}


def checker_data(root=ROOT):
    fields, anchors, rules = spec_facts(root)
    entities = {}
    for e in ENTITY_ORDER:
        s = json.loads((root / "schemas" / "v0.2" / f"{e}.json").read_text(encoding="utf-8"))
        entities[e] = {"schema_id": s["$id"], "schema_path": f"schemas/v0.2/{e}.json", "description": s.get("description"),
                       "required": s.get("required", []), "properties": sorted(s.get("properties", {})), "spec": anchors[e], "fields": fields[e]}
    samples = []
    for label, rel, kind, expect in SAMPLES:
        samples.append({"label": label, "file": "examples/" + rel, "kind": kind, "expect": expect, "text": (root / "examples" / rel).read_text(encoding="utf-8")})
    eng = engine_files(root)
    wheels = [p for p, _, _, _, _, when in PINS if p.startswith("wheels/") and p.endswith(".whl")]
    record_fixtures = sorted(x.name for x in (root / "examples" / "v0.2").glob("*.json"))
    bundle_fixtures = 1 + len(json.loads((root / "examples" / "bundles" / "v0.2" / "cases.manifest.json").read_text(encoding="utf-8"))["cases"])
    lock = json.loads((VENDOR / "pyodide" / "pyodide-lock.json").read_text(encoding="utf-8")) if (VENDOR / "pyodide" / "pyodide-lock.json").exists() else {"info": {}}
    return {"checker": {"name": "OWHS browser checker", "version": CHECKER_VERSION, "page": "https://openworkplacehealth.org/check/",
                        "reference_tools": {p: eng["sha256"][p] for p in ENGINE_FILES[:3]},
                        "runtime": {"pyodide": PYODIDE_VERSION, "python": lock["info"].get("python"), **wheel_versions()}},
            "schema_version": SCHEMA_VERSION, "entities": entities, "rules": rules, "links": LINKS, "samples": samples,
            "engine": {"pyodide_dir": "vendor/pyodide/", "wheels": wheels, "files": "engine-files.json", "runner": "runner.py",
                       "bytes": download_bytes(wheels)},
            "fixtures": {"records": len(record_fixtures), "bundles": bundle_fixtures}}


def download_bytes(wheels):
    names = ["pyodide/pyodide.mjs", "pyodide/pyodide.asm.mjs", "pyodide/pyodide.asm.wasm", "pyodide/python_stdlib.zip", "pyodide/pyodide-lock.json"] + wheels
    return sum((VENDOR / n).stat().st_size for n in names if (VENDOR / n).exists())


def manifest(root=ROOT):
    rows = []
    for path, url, pin, lic, lic_file, when in PINS:
        p = root / "site" / "check" / "vendor" / path
        rows.append({"path": path, "source": url, "sha256": sha(p) if p.exists() else None, "licence": lic, "licence_file": lic_file,
                     "loaded": {"check": "when the visitor first presses Check", "page": "with the page", "never": "never; kept for its licence terms"}[when]})
    return {"note": "Every file under site/check/vendor/, where it came from, its SHA-256 and its licence. Generated by tools/build_checker.py; "
                    "--check fails when a file differs from this list or a file is not listed. Nothing here is fetched from its source at run time.",
            "pyodide_version": PYODIDE_VERSION, "files": rows}


def render_page(data):
    from html import escape
    t = TEMPLATE.read_text(encoding="utf-8")
    opts = "\n".join(f'          <option value="{e}">{e}</option>' for e in ENTITY_ORDER)
    samples = "\n".join(f'        <li><button type="button" class="sample" data-sample="{i}"><span class="sample-kind sample-{s["expect"]}">{"passes" if s["expect"] == "pass" else "fails"}</span>{escape(s["label"])}</button></li>'
                        for i, s in enumerate(data["samples"]))
    mb = data["engine"]["bytes"] / 1_000_000
    rt = data["checker"]["runtime"]
    values = {"CHECKER_VERSION": CHECKER_VERSION, "SCHEMA_VERSION": SCHEMA_VERSION, "ENTITY_OPTIONS": opts, "SAMPLES": samples,
              "DOWNLOAD_MB": f"{mb:.0f}", "PYODIDE_VERSION": PYODIDE_VERSION, "PYTHON_VERSION": rt.get("python") or "3",
              "JSONSCHEMA_VERSION": rt["jsonschema"], "RECORD_FIXTURES": str(data["fixtures"]["records"]), "BUNDLE_FIXTURES": str(data["fixtures"]["bundles"]),
              "ALL_FIXTURES": str(data["fixtures"]["records"] + data["fixtures"]["bundles"]), "VALIDATE_SHA": data["checker"]["reference_tools"]["tools/validate.py"][:12]}
    for k, v in values.items(): t = t.replace("{{" + k + "}}", v)
    if "{{" in t: raise SystemExit("unfilled placeholder in tools/check_template.html: " + re.search(r"\{\{\w+\}\}", t).group(0))
    return t


def dumps(obj): return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def outputs(root=ROOT):
    data = checker_data(root)
    return {"site/check/checker-data.json": dumps(data), "site/check/engine-files.json": dumps(engine_files(root)),
            "site/check/vendor/MANIFEST.json": dumps(manifest(root)), "site/check/index.html": render_page(data)}


def vendor_problems(root=ROOT):
    problems = []
    vendor = root / "site" / "check" / "vendor"
    listed = {p for p, *_ in PINS} | {"MANIFEST.json"}
    for f in sorted(vendor.rglob("*")):
        if f.is_file() and f.relative_to(vendor).as_posix() not in listed: problems.append(f"site/check/vendor/{f.relative_to(vendor).as_posix()}: not listed in tools/build_checker.py PINS")
    committed = json.loads((vendor / "MANIFEST.json").read_text(encoding="utf-8")) if (vendor / "MANIFEST.json").exists() else {"files": []}
    recorded = {r["path"]: r["sha256"] for r in committed["files"]}
    lock = {}
    if (vendor / "pyodide" / "pyodide-lock.json").exists():
        lock = {v["file_name"]: v["sha256"] for v in json.loads((vendor / "pyodide" / "pyodide-lock.json").read_text(encoding="utf-8"))["packages"].values()}
    for path, url, pin, *_ in PINS:
        p = vendor / path
        if not p.exists(): problems.append(f"site/check/vendor/{path}: missing (python tools/build_checker.py --fetch)"); continue
        h = sha(p)
        if pin and not h.startswith(pin): problems.append(f"site/check/vendor/{path}: sha256 {h[:12]} is not the pinned {pin[:12]}")
        if recorded.get(path) and recorded[path] != h: problems.append(f"site/check/vendor/{path}: sha256 {h[:12]} differs from vendor/MANIFEST.json {recorded[path][:12]}")
        name = path.split("/")[-1]
        if path.startswith("wheels/") and name in lock and lock[name] != h: problems.append(f"site/check/vendor/{path}: differs from the hash in Pyodide's own lock file")
    return problems


def check(root=ROOT):
    problems = vendor_problems(root)
    fresh = outputs(root)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(root / "site", tmp_site, ignore=shutil.ignore_patterns("vendor", "*.zip", "*.pdf"))
        (tmp_site / "check" / "index.html").write_text(fresh["site/check/index.html"], encoding="utf-8")
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, str(root / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
        if r.returncode != 0: return problems + ["stamp failed: " + (r.stdout + r.stderr).strip()]
        fresh["site/check/index.html"] = (tmp_site / "check" / "index.html").read_text(encoding="utf-8")
        from build_doc_page import local_link_problems
        problems += [f"site/check/index.html: {h}" for h in local_link_problems(fresh["site/check/index.html"], root / "site", "check/index.html")]
    for rel, text in fresh.items():
        p = root / rel
        if not p.exists(): problems.append(f"{rel}: missing; run tools/build_checker.py then tools/stamp_canonical.py")
        elif p.read_text(encoding="utf-8") != text: problems.append(f"{rel}: differs from a fresh build of its sources")
    data = json.loads(fresh["site/check/checker-data.json"])
    for key, href in data["links"].items():
        problems += [f"checker link {key}: {h}" for h in local_link_problems(f'<a href="{href}">', root / "site", "check/index.html")]
    for e, ent in data["entities"].items():
        problems += [f"checker link for {e}: {h}" for h in local_link_problems(f'<a href="{ent["spec"]}">', root / "site", "check/index.html")]
    return problems


def fetch():
    VENDOR.mkdir(parents=True, exist_ok=True)
    recorded = {r["path"]: r["sha256"] for r in json.loads(HASHES_FILE.read_text(encoding="utf-8"))["files"]} if HASHES_FILE.exists() else {}
    for path, url, pin, *_ in PINS:
        req = urllib.request.Request(url, headers={"User-Agent": "owhs-build-checker"})
        with urllib.request.urlopen(req, timeout=120) as r: body = r.read()
        h = sha(body)
        if pin and not h.startswith(pin): raise SystemExit(f"{url}: sha256 {h} is not the pinned {pin}")
        if recorded.get(path) and recorded[path] != h: raise SystemExit(f"{url}: sha256 {h} differs from vendor/MANIFEST.json; if the upgrade is intended, delete the manifest row first")
        (VENDOR / path).parent.mkdir(parents=True, exist_ok=True); (VENDOR / path).write_bytes(body); print(f"fetched {path} ({len(body)} bytes)")


def self_test():
    failures = 0
    def probe(label, mutate, must):
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"; root.mkdir()
            for d in ("tools", "schemas", "profiles", "examples", "spec", "docs", "site"): shutil.copytree(ROOT / d, root / d, ignore=shutil.ignore_patterns("*.wasm", "*.zip") if d == "site" else None)
            for f in ("robots-policy.txt",):
                if (ROOT / f).exists(): shutil.copy(ROOT / f, root / f)
            for big in ("pyodide/pyodide.asm.wasm", "pyodide/python_stdlib.zip"):          # large files linked, not copied
                os.symlink(VENDOR / big, root / "site" / "check" / "vendor" / big)
            mutate(root)
            probs = check(root)
            ok = any(must in x for x in probs) if must else not probs
            print(("ok  " if ok else "FAIL"), label, "" if ok else probs[:3]); failures += not ok
    probe("the committed checker is a fresh build and every vendored file matches its pin", lambda r: None, "")
    probe("an edited copy of the reference validator is detected", lambda r: (r / "tools" / "validate.py").write_text((r / "tools" / "validate.py").read_text() + "\n# edit\n"), "engine-files.json: differs")
    probe("a changed schema is detected", lambda r: (r / "schemas" / "v0.2" / "OrgUnit.json").write_text((r / "schemas" / "v0.2" / "OrgUnit.json").read_text().replace('"unitId"', '"unitID"', 1)), "engine-files.json: differs")
    probe("a changed rule statement in the specification is detected", lambda r: (r / "spec" / "OWHS-v0.2-draft.md").write_text((r / "spec" / "OWHS-v0.2-draft.md").read_text().replace("parentUnitId, if supplied, differs from unitId", "parentUnitId differs from unitId")), "checker-data.json: differs")
    def tamper(r):
        p = r / "site" / "check" / "vendor" / "wheels" / "six-1.17.0-py2.py3-none-any.whl"; p.write_bytes(p.read_bytes() + b"x")
    probe("a tampered vendored wheel is detected", tamper, "is not the pinned")
    probe("an unlisted vendored file is detected", lambda r: (r / "site" / "check" / "vendor" / "extra.js").write_text("x"), "not listed")
    probe("an edited page is detected", lambda r: (r / "site" / "check" / "index.html").write_text((r / "site" / "check" / "index.html").read_text().replace("</main>", "<p>x</p></main>")), "index.html: differs")
    print(f"{'all' if not failures else failures} probes {'as expected' if not failures else 'FAILED'}")
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv: return self_test()
    if "--fetch" in argv: fetch(); return 0
    if "--check" in argv:
        problems = check()
        if problems:
            print("the browser checker is not a fresh build of its sources; run tools/build_checker.py then tools/stamp_canonical.py", file=sys.stderr)
            for p in problems: print("  " + p, file=sys.stderr)
            return 1
        d = json.loads((CHECK / "checker-data.json").read_text(encoding="utf-8"))
        print(f"up to date: site/check/ (checker {CHECKER_VERSION}, {len(d['entities'])} record types, {len(d['rules'])} named rules, {len(PINS)} vendored files verified)")
        return 0
    for rel, text in outputs().items():
        (ROOT / rel).parent.mkdir(parents=True, exist_ok=True); (ROOT / rel).write_text(text, encoding="utf-8"); print(f"written: {rel}")
    print("now run tools/stamp_canonical.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
