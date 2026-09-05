#!/usr/bin/env python3
"""Parse every workflow file with a strict YAML loader that refuses duplicate keys, and run the tripwire step's actual shell
body with gh and the verifier stubbed.

A duplicate `env:` key in a step is accepted by permissive loaders and silently drops one mapping, which in a
workflow means a token or an input vanishes. This check makes that a failure in CI rather than a mystery at 06:00
on the first of the month. The tripwire body is exercised for verifier exit 0 (step exits 0, no issue), exit 1 (issue
created once, step exits 1) and a tool error exit 2 (issue created with the exit recorded, step exits 1); a stubbed gh
records every call and never reaches the network.
"""
import glob, os, stat, subprocess, sys, tempfile
from pathlib import Path
import yaml


class Strict(yaml.SafeLoader):
    pass


def no_dup(loader, node, deep=False):
    m = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in m:
            raise yaml.constructor.ConstructorError(f"duplicate key {key!r} at line {k.start_mark.line + 1}")
        m[key] = loader.construct_object(v, deep=deep)
    return m


Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_dup)

def tripwire_body_cases():
    """Run the tripwire step body under bash with stubs on PATH. Returns a list of (label, ok, detail)."""
    doc = yaml.load(open(".github/workflows/tripwire.yml", encoding="utf-8"), Loader=Strict)
    step = next(s for s in doc["jobs"]["check"]["steps"] if s.get("name", "").startswith("verify"))
    body = step["run"]
    out = []
    if step.get("shell") != "bash" or "pipefail" not in body:
        out.append(("tripwire step declares bash with pipefail", False, step.get("shell"))); return out
    for rc, expect_exit, expect_issue in ((0, 0, False), (1, 1, True), (2, 1, True)):
        with tempfile.TemporaryDirectory() as tmp:
            bin_ = Path(tmp) / "bin"; bin_.mkdir(); log = Path(tmp) / "gh.log"
            (bin_ / "gh").write_text("#!/bin/bash\necho \"$@\" >> " + str(log) + "\ncase \"$1 $2\" in\n  'issue list') echo 0;;\n  'issue create') echo created;;\n  *) echo '[]';;\nesac\n")
            (bin_ / "python").write_text("#!/bin/bash\nif [ \"$2\" = \"window\" ]; then exec python3 \"$@\"; fi\nif [ \"$2\" = \"verify\" ]; then echo \"stub verifier exit " + str(rc) + "\"; echo \"stub stderr\" >&2; exit " + str(rc) + "; fi\nexec python3 \"$@\"\n")
            for f in bin_.iterdir(): f.chmod(f.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", REPO="example/repo", GH_TOKEN="x")
            r = subprocess.run(["bash", "-e", "-c", body], env=env, capture_output=True, text=True)
            calls = log.read_text() if log.exists() else ""
            issued = "issue create" in calls
            ok = r.returncode == expect_exit and issued == expect_issue and (rc == 0 or "stub stderr" in (r.stdout + r.stderr)) and (rc != 2 or "tool error" in r.stdout)
            out.append((f"tripwire body with verifier exit {rc}: step exit {expect_exit}, issue {'created' if expect_issue else 'not created'}, stderr captured", ok, f"exit {r.returncode}, gh calls: {calls.strip()[:200]}"))
    return out


bad = 0
for label, ok, detail in tripwire_body_cases():
    print(("ok  " if ok else "FAIL"), label, "" if ok else detail); bad += not ok
for f in sorted(glob.glob(".github/workflows/*.yml")):
    try:
        doc = yaml.load(open(f, encoding="utf-8"), Loader=Strict)
        assert isinstance(doc, dict) and "jobs" in doc and ("on" in doc or True in doc), "not a workflow"
        print("ok", f)
    except Exception as e:
        bad += 1; print("FAIL", f, e)
sys.exit(1 if bad else 0)
