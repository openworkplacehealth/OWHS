#!/usr/bin/env python3
"""Parse every workflow file with a strict YAML loader that refuses duplicate keys, and run the actual shell bodies of the
tripwire step, the harvest's cycle-issue step and the licence watcher's comment step with gh (and the verifier) stubbed.

A duplicate `env:` key in a step is accepted by permissive loaders and silently drops one mapping, which in a
workflow means a token or an input vanishes. This check makes that a failure in CI rather than a mystery at 06:00
on the first of the month. The tripwire body is exercised for verifier exit 0 (step exits 0, no issue), exit 1 (issue
created once, step exits 1) and a tool error exit 2 (issue created with the exit recorded, step exits 1); a stubbed gh
records every call and never reaches the network. The issue each alerting step opens is assigned to the steward named
in tools/cycle.py and mentions that login exactly once; the tripwire's title names the month and the one action; when last
month's tripwire issue is still open and that month is still not verified, it is retitled and told plainly that it can no
longer be recovered. The harvest issue keeps the owhs-cycle marker tools/cycle.py correlates on, mentions and assigns
only when the cycle is not complete, and names the cause the run recorded. The licence step comments only when the
report asks it to (a change, a checkable page failing, or the monthly reminder) and still comments when no report exists.
"""
import glob, json, os, stat, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cycle
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

GH_STUB = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
call = {"argv": a}
if "--body-file" in a:
    call["body_file_text"] = open(a[a.index("--body-file") + 1], encoding="utf-8").read()
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as f: f.write(json.dumps(call) + "\\n")
if a[:2] == ["issue", "list"]:
    print(os.environ.get("GH_PREV_ISSUE", "") if "number,title" in a else os.environ.get("GH_LIST", "0"))
elif a[:2] == ["issue", "create"]:
    print("https://github.com/example/repo/issues/1")
"""


def stubbed(tmp, python_stub=None):
    """A bin directory with the recording gh stub (and, when given, a python stub) first on PATH."""
    bin_ = Path(tmp) / "bin"; bin_.mkdir()
    (bin_ / "gh").write_text(GH_STUB)
    (bin_ / "python").write_text(python_stub or f"#!/bin/bash\nexec {sys.executable} \"$@\"\n")
    for f in bin_.iterdir(): f.chmod(f.stat().st_mode | stat.S_IEXEC)
    log = Path(tmp) / "gh.log"
    return bin_, log


def calls_of(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def arg_after(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def step_body(workflow, job, prefix):
    doc = yaml.load(open(workflow, encoding="utf-8"), Loader=Strict)
    return next(s for s in doc["jobs"][job]["steps"] if s.get("name", "").startswith(prefix))


def tripwire_body_cases():
    """Run the tripwire step body under bash with stubs on PATH. Returns a list of (label, ok, detail)."""
    step = step_body(".github/workflows/tripwire.yml", "check", "verify")
    body = step["run"]
    out = []
    if step.get("shell") != "bash" or "pipefail" not in body:
        out.append(("tripwire step declares bash with pipefail", False, step.get("shell"))); return out
    steward = cycle.ALERT_ASSIGNEE
    this = cycle.plan("schedule", None, None, __import__("datetime").date.today(), {"entries": {}}, "x")["cycle_id"]
    for rc, expect_exit, expect_issue, prev_issue in ((0, 0, False, ""), (1, 1, True, ""), (2, 1, True, ""), (1, 1, True, "42"), (0, 0, False, "42")):
        with tempfile.TemporaryDirectory() as tmp:
            bin_, log = stubbed(tmp, "#!/bin/bash\nif [ \"$2\" = \"verify\" ]; then echo \"stub verifier exit " + str(rc) + "\"; echo \"stub stderr\" >&2; exit " + str(rc) + "; fi\nexec " + sys.executable + " \"$@\"\n")
            env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", REPO="example/repo", GH_TOKEN="x", GH_LOG=str(log), GH_LIST="0", GH_PREV_ISSUE=prev_issue)
            r = subprocess.run(["bash", "-e", "-c", body], env=env, capture_output=True, text=True)
            calls = calls_of(log)
            creates = [c for c in calls if c["argv"][:2] == ["issue", "create"]]
            issued = bool(creates)
            ok = r.returncode == expect_exit and issued == expect_issue and len(creates) <= 1 and (rc == 0 or "stub stderr" in (r.stdout + r.stderr)) and (rc != 2 or "tool error" in r.stdout)
            label = f"tripwire body with verifier exit {rc}" + (f" and last month's issue #{prev_issue} open" if prev_issue else "") + f": step exit {expect_exit}, issue {'created' if expect_issue else 'not created'}, stderr captured"
            out.append((label, ok, f"exit {r.returncode}, gh calls: {[c['argv'][:3] for c in calls]}, {r.stderr[-300:]}"))
            if creates:
                a = creates[0]["argv"]; text = creates[0].get("body_file_text", "")
                title = arg_after(a, "--title") or ""
                out.append((f"  the issue is assigned to {steward}, mentions that login exactly once, and its title names the month and the one action",
                             arg_after(a, "--assignee") == steward and text.count("@") == 1 and f"@{steward}," in text
                             and title.startswith(f"No verified evidence sweep for {this}: re-run evidence-harvest by ") and "can be recovered until" in text, (a, text[:200])))
            edits = [c for c in calls if c["argv"][:3] == ["issue", "edit", "42"]]
            comments = [c for c in calls if c["argv"][:3] == ["issue", "comment", "42"]]
            if prev_issue and rc == 1:
                prev = cycle.previous_cycle(this)
                out.append((f"  last month's open issue is retitled and told plainly, once, that {prev} can no longer be recovered",
                             len(edits) == 1 and arg_after(edits[0]["argv"], "--title") == f"No verified evidence sweep for {prev}: missed, can no longer be recovered"
                             and len(comments) == 1 and "can no longer be recovered" in comments[0].get("body_file_text", "") and comments[0]["body_file_text"].count("@") == 1, [c["argv"][:4] for c in calls]))
            if prev_issue and rc == 0:
                out.append(("  last month's issue is left as it is when that month verifies", not edits and not comments, [c["argv"][:4] for c in calls]))
    return out


def harvest_issue_cases():
    """Run the harvest workflow's cycle-issue step body against fixture candidates files in a scratch tree."""
    body = step_body(".github/workflows/harvest.yml", "harvest", "cycle issue")["run"]
    steward = cycle.ALERT_ASSIGNEE
    out = []
    ch = lambda iid, src, outcome, err: {"instrument_id": iid, "route": "cites", "source": src, "date_basis": "publication", "outcome": outcome, "error": err, "channel_id": iid}
    def env_of(status, channels, warnings, action):
        return {"schema_version": "1.1", "cycle": {"id": "2026-11", "kind": "planned"}, "run_id": "r1", "status": status, "full_inventory": True,
                "requested_window": {"from": "2026-10-01", "to": "2026-11-01"}, "date_bases": {"publication": {"from": "2026-10-01", "to": "2026-11-01"}, "first_indexed": None, "full_history": False},
                "query_version": "q", "query_sha256": "a" * 64, "candidates": [], "new_instrument_candidates": [], "expected_channels": channels, "channels": channels,
                "channels_not_complete": [{**c, "outcome": c["outcome"]} for c in channels if c["outcome"] != "complete"], "warnings": warnings, "watermark_proposal": None, "next_action": action}
    partial = env_of("partial", [ch("phq-9", "openalex", "partial", "http 401: API key required for cursor paging")],
                     [{"type": "openalex http 401", "detail": "OpenAlex refused a request made without a key (http 401: API key required for cursor paging). Setting the OPENALEX_API_KEY repository secret is the fix."}],
                     "Set the OPENALEX_API_KEY repository secret, then re-run evidence-harvest (Run workflow, both window fields empty) by 30 November 2026 (UTC).")
    complete = env_of("complete", [ch("phq-9", "openalex", "complete", None)], [], None)
    for label, fixture in (("a partial run", partial), ("a complete run", complete), ("a run with no candidates file", None)):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"; (work / "evidence" / "candidates").mkdir(parents=True)
            (work / "tools").symlink_to(Path(__file__).resolve().parent)
            if fixture is not None: (work / "evidence" / "candidates" / "2026-11.json").write_text(json.dumps(fixture))
            bin_, log = stubbed(tmp)
            env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", GH_TOKEN="x", GH_LOG=str(log), GH_LIST="", MONTH="2026-11", KIND="planned", GH_RUN_ID="100", RUN_URL="https://example/run/100")
            r = subprocess.run(["bash", "-e", "-c", body], env=env, capture_output=True, text=True, cwd=work)
            creates = [c for c in calls_of(log) if c["argv"][:2] == ["issue", "create"]]
            if r.returncode != 0 or len(creates) != 1:
                out.append((f"harvest issue step, {label}: one issue created", False, (r.returncode, r.stderr[-400:], creates))); continue
            a = creates[0]["argv"]; title = arg_after(a, "--title"); text = arg_after(a, "--body")
            marks = [dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv) for m in cycle.MARK.finditer(text)]
            marker_ok = len(marks) == 1 and marks[0].get("cycle_id") == "2026-11" and marks[0].get("github_run_id") == "100" and marks[0].get("kind") == "planned"
            if fixture is complete:
                ok = marker_ok and "--assignee" not in a and "@" not in text and title == "Evidence harvest 2026-11: complete run, candidates for screening" and marks[0].get("status") == "complete"
                out.append((f"harvest issue step, {label}: the marker tools/cycle.py correlates on is intact, no one is assigned or mentioned", ok, (title, a[-4:], marks)))
            elif fixture is partial:
                ok = (marker_ok and arg_after(a, "--assignee") == steward and text.count("@") == 1 and text.startswith(f"@{steward}, cycle 2026-11 is partial. **The one action:** Set the OPENALEX_API_KEY")
                      and title == "Evidence harvest 2026-11: partial run. " + partial["next_action"] and "Setting the OPENALEX_API_KEY repository secret is the fix." in text and marks[0].get("status") == "partial")
                out.append((f"harvest issue step, {label}: assigned to {steward}, one mention, the action in the title and first line, the 401 line in the body, marker intact", ok, (title, text[:300], marks)))
            else:
                ok = (marker_ok and marks[0].get("status") == "failed" and marks[0].get("artefact_sha256") == "none" and arg_after(a, "--assignee") == steward and text.count("@") == 1
                      and title == "Evidence harvest 2026-11: failed run, no candidates file. Read the run log, then re-run evidence-harvest by 30 November 2026 (UTC)")
                out.append((f"harvest issue step, {label}: assigned, one mention, the recovery date in the title, failed marker intact", ok, (title, text[:300], marks)))
    return out


def licence_comment_cases():
    """Run the licence watcher's comment step body against fixture reports."""
    step = step_body(".github/workflows/licence-watch.yml", "watch", "comment on the one source-monitoring issue")
    body = step["run"]
    out = [("licence comment step runs whatever the watcher's exit", step.get("if") == "always()", step.get("if"))]
    for label, report, expect in (("a quiet week", {"notify": None, "comment_body": None}, None),
                                  ("the monthly reminder", {"notify": "monthly-reminder", "comment_body": "Monthly reminder: 6 licence pages refuse automated requests"}, "Monthly reminder: 6 licence pages"),
                                  ("a failure of a checkable page", {"notify": "failure", "comment_body": "Licence-source check: partial."}, "Licence-source check: partial."),
                                  ("no report at all", None, "wrote no report")):
        with tempfile.TemporaryDirectory() as tmp:
            bin_, log = stubbed(tmp)
            rep = Path(tmp) / "report.json"
            if report is not None: rep.write_text(json.dumps(report))
            env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", GH_TOKEN="x", GH_LOG=str(log), GH_LIST="57", REPORT=str(rep), RUN_URL="https://example/run/7")
            r = subprocess.run(["bash", "-e", "-c", body], env=env, capture_output=True, text=True)
            comments = [c for c in calls_of(log) if c["argv"][:3] == ["issue", "comment", "57"]]
            if expect is None:
                ok = r.returncode == 0 and not comments
            else:
                ok = r.returncode == 0 and len(comments) == 1 and expect in comments[0].get("body_file_text", "") and "<!-- owhs-licence-source-monitor -->" in comments[0]["body_file_text"]
            out.append((f"licence comment step, {label}: {'no comment' if expect is None else 'one comment on the standing issue'}", ok, (r.returncode, r.stderr[-300:], comments)))
    return out


bad = 0
for label, ok, detail in tripwire_body_cases() + harvest_issue_cases() + licence_comment_cases():
    print(("ok  " if ok else "FAIL"), label, "" if ok else detail); bad += not ok
for f in sorted(glob.glob(".github/workflows/*.yml")):
    try:
        doc = yaml.load(open(f, encoding="utf-8"), Loader=Strict)
        assert isinstance(doc, dict) and "jobs" in doc and ("on" in doc or True in doc), "not a workflow"
        print("ok", f)
    except Exception as e:
        bad += 1; print("FAIL", f, e)
sys.exit(1 if bad else 0)
