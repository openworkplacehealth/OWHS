#!/usr/bin/env python3
"""The maintenance cycle: one definition, consumed by the harvest workflow, the tripwire and the harvester.

    python tools/cycle.py window  [--event schedule|workflow_dispatch] [--from D] [--to D] [--today D]
    python tools/cycle.py verify  --cycle 2026-10             read-only: correlates run, artefact and issue through gh
    python tools/cycle.py advance --artefact FILE             writes the artefact's watermark proposal into evidence/watermarks.json
    python tools/cycle.py --self-test                         offline contract suite, no network, no gh

Cycle identity. A planned cycle is named by the month the run happens in: the run on 1 October is cycle 2026-10,
and the tripwire on 3 October looks for cycle 2026-10. The publication window it searches is separate: by default
from the watermark (the end of the last complete full-inventory run) minus an overlap for late indexing, or the
first day of the previous month when no watermark exists, to today. A manual run with an explicit window is a
manual cycle, named manual-FROM-TO; it never satisfies a planned cycle. A manual run with no window is a re-run
of the current planned cycle.

Watermarks (evidence/watermarks.json) advance only after a complete full-inventory run, and only through the
screening pull request a person merges: the harvest writes a proposal into its artefact, `advance` copies it in.
The next planned window then starts overlap_days before the watermark, so a work indexed late is seen again.

Verification. `verify` finds successful runs of the evidence-harvest workflow, downloads the cycle's artefact from
each, and accepts the cycle only when one artefact names this cycle as planned, reports status complete over the
full inventory, has every expected channel complete (the denominator is the query file's channel set, so a missing
channel counts as incomplete), carries the current query file's hash, and a bot-authored issue names that exact
GitHub run and that artefact's hash. A partial run, an unrelated successful run, a hand-written issue or an issue
describing a run that failed does not satisfy it.
"""
import datetime, hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "evidence" / "queries" / "instruments-v1.json"
WATERMARKS = ROOT / "evidence" / "watermarks.json"
WORKFLOW = "evidence-harvest"
MARK = re.compile(r"<!-- owhs-cycle (.*?) -->", re.S)


def query_sha(path=QUERIES):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_channels(cfg):
    """Every (instrument, route) a full-inventory run must complete, from the query file alone: names for every record,
    abbreviation where the record has abbreviations with context terms, cites where a seed carries an OpenAlex id, and
    the untargeted new-instrument channel (instrument None) when the query file defines one. The harvester's self-test
    asserts this equals the channels it plans, so the two cannot drift."""
    out = []
    for r in cfg["records"]:
        out.append((r["instrument_id"], "names"))
        if r.get("abbreviations") and r.get("abbreviation_context"): out.append((r["instrument_id"], "abbreviation"))
        if any(sd.get("openalex_id") for sd in (r.get("citation_seeds") or [])): out.append((r["instrument_id"], "cites"))
    if cfg.get("new_instrument_query"): out.append((None, "new-instrument"))
    return sorted(out, key=lambda x: (x[0] or "", x[1]))


def complete_pairs(channels):
    """(instrument, route) pairs every one of whose channels completed; a pair with one failed source is not complete."""
    by = {}
    for c in channels:
        by.setdefault((c.get("instrument_id"), c.get("route")), []).append(c.get("outcome") == "complete")
    return {k for k, v in by.items() if all(v)}


def load_watermarks(path=WATERMARKS):
    if Path(path).exists(): return json.loads(Path(path).read_text(encoding="utf-8"))
    return {"schema_version": "1.0", "overlap_days": 14, "entries": {}, "note": "Advanced only through a merged pull request, after a complete full-inventory run."}


def window(event, in_from, in_to, today, marks, qsha):
    """(cycle_id, kind, from, to). Explicit inputs make a manual cycle; otherwise the planned cycle of today's month."""
    def parse(v):
        v = (v or "").strip()
        if not v: return None
        try: return datetime.date.fromisoformat(v)
        except ValueError: raise SystemExit(f"configuration error: {v!r} is not YYYY-MM-DD")
    f, t = parse(in_from), parse(in_to)
    if event == "schedule" and (f or t): raise SystemExit("configuration error: a scheduled run takes no window inputs")
    if f or t:
        f = f or (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1); t = t or today
        if t < f: raise SystemExit("configuration error: window end precedes start")
        return f"manual-{f.isoformat()}-{t.isoformat()}", "manual", f, t
    entry = marks.get("entries", {}).get(qsha)
    if entry:
        f = datetime.date.fromisoformat(entry["last_complete_to"]) - datetime.timedelta(days=int(marks.get("overlap_days", 14)))
    else:
        f = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    return today.strftime("%Y-%m"), "planned", f, today


def verify(cycle_id, qsha, expected, runs, artefacts, issues):
    """Pure correlation. runs: [{github_run_id, conclusion, event}]; artefacts: {github_run_id: (envelope dict, sha256)};
    issues: [{author, body}]. Returns (accepted_run_id or None, reasons)."""
    reasons = []
    marks = []
    for i in issues:
        if i.get("author") != "app/github-actions": continue
        for m in MARK.finditer(i.get("body", "")):
            marks.append(dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv))
    for run in runs:
        rid = str(run["github_run_id"])
        if run.get("conclusion") != "success": reasons.append(f"run {rid}: conclusion {run.get('conclusion')}"); continue
        if rid not in artefacts: reasons.append(f"run {rid}: no artefact candidates-{cycle_id}"); continue
        env, sha = artefacts[rid]
        cyc = env.get("cycle") or {}
        if cyc.get("id") != cycle_id: reasons.append(f"run {rid}: artefact is cycle {cyc.get('id')!r}, not {cycle_id}"); continue
        if cyc.get("kind") != "planned": reasons.append(f"run {rid}: cycle kind {cyc.get('kind')!r} is not planned"); continue
        if env.get("status") != "complete": reasons.append(f"run {rid}: status {env.get('status')!r}"); continue
        if env.get("full_inventory") is not True: reasons.append(f"run {rid}: not a full-inventory run"); continue
        if env.get("query_sha256") != qsha: reasons.append(f"run {rid}: query file hash {str(env.get('query_sha256'))[:12]} is not the current {qsha[:12]}"); continue
        done = complete_pairs(env.get("channels", []))
        missing = [f"{i}/{r}" for i, r in expected if (i, r) not in done]
        if missing: reasons.append(f"run {rid}: {len(missing)} of {len(expected)} expected channels not complete: {missing[:5]}"); continue
        matched = [m for m in marks if m.get("cycle_id") == cycle_id and m.get("github_run_id") == rid and m.get("artefact_sha256") == sha]
        if not matched: reasons.append(f"run {rid}: no bot-authored issue names this run and artefact hash {sha[:12]}"); continue
        return rid, reasons
    if not runs: reasons.append("no runs of the workflow found for the cycle's month")
    return None, reasons


# ---------- gh-backed verify ----------

def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0: raise SystemExit(f"gh {' '.join(args[:2])} failed: {r.stderr.strip()}")
    return r.stdout


def verify_live(cycle_id, repo):
    since = f"{cycle_id}-01T00:00:00Z"
    runs = json.loads(gh("run", "list", "--repo", repo, "--workflow", WORKFLOW, "--created", f">={since}", "--json", "databaseId,conclusion,event", "--limit", "50"))
    runs = [{"github_run_id": str(r["databaseId"]), "conclusion": r["conclusion"], "event": r["event"]} for r in runs]
    artefacts = {}
    with tempfile.TemporaryDirectory() as tmp:
        for r in runs:
            if r["conclusion"] != "success": continue
            d = Path(tmp) / r["github_run_id"]
            p = subprocess.run(["gh", "run", "download", r["github_run_id"], "--repo", repo, "-n", f"candidates-{cycle_id}", "-D", str(d)], capture_output=True, text=True)
            if p.returncode != 0: continue
            files = list(d.glob("*.json"))
            if files: artefacts[r["github_run_id"]] = (json.loads(files[0].read_text(encoding="utf-8")), hashlib.sha256(files[0].read_bytes()).hexdigest())
    issues = json.loads(gh("issue", "list", "--repo", repo, "--label", "evidence-sweep", "--state", "all", "--search", f'"Evidence harvest {cycle_id}" in:title', "--json", "author,body"))
    issues = [{"author": ("app/" + i["author"]["login"]) if i["author"].get("is_bot") else i["author"]["login"], "body": i["body"]} for i in issues]
    cfg = json.loads(QUERIES.read_text(encoding="utf-8"))
    return verify(cycle_id, query_sha(), expected_channels(cfg), runs, artefacts, issues)


def advance(artefact_path, path=WATERMARKS):
    env = json.loads(Path(artefact_path).read_text(encoding="utf-8"))
    prop = env.get("watermark_proposal")
    if not prop: raise SystemExit("this artefact carries no watermark proposal: the run was not a complete full-inventory run")
    marks = load_watermarks(path)
    cur = marks["entries"].get(prop["query_sha256"])
    if cur and cur["last_complete_to"] >= prop["last_complete_to"]: raise SystemExit(f"watermark already at {cur['last_complete_to']}; nothing to advance")
    marks["entries"][prop["query_sha256"]] = {**prop, "advanced_on": datetime.date.today().isoformat()}
    Path(path).write_text(json.dumps(marks, indent=2) + "\n", encoding="utf-8")
    print(f"watermark for query {prop['query_sha256'][:12]} advanced to {prop['last_complete_to']} (cycle {prop['cycle_id']}, run {prop['run_id']}); commit this in the screening pull request")


# ---------- offline suite ----------

def self_test():
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else detail); failures += not ok
    D = datetime.date
    marks0 = {"overlap_days": 14, "entries": {}}
    c, k, f, to = window("schedule", None, None, D(2026, 10, 1), marks0, "q1")
    t("scheduled run on 1 October is cycle 2026-10 with the default window from 1 September", (c, k, f, to) == ("2026-10", "planned", D(2026, 9, 1), D(2026, 10, 1)), (c, k, f, to))
    c2, *_ = window("schedule", None, None, D(2026, 10, 31), marks0, "q1")
    t("month rollover: any day in October is cycle 2026-10, 1 November is 2026-11", c2 == "2026-10" and window("schedule", None, None, D(2026, 11, 1), marks0, "q1")[0] == "2026-11")
    c, k, f, to = window("workflow_dispatch", "2026-01-01", "2026-03-31", D(2026, 10, 1), marks0, "q1")
    t("manual run with an old window is a manual cycle that never equals a planned one", k == "manual" and c == "manual-2026-01-01-2026-03-31" and c != "2026-10")
    c, k, *_ = window("workflow_dispatch", None, None, D(2026, 10, 2), marks0, "q1")
    t("manual run with no window is a re-run of the planned cycle", (c, k) == ("2026-10", "planned"))
    marks1 = {"overlap_days": 14, "entries": {"q1": {"last_complete_to": "2026-10-01"}}}
    c, k, f, to = window("schedule", None, None, D(2026, 11, 1), marks1, "q1")
    t("watermark present: next planned window starts overlap_days before the watermark (replayable catch-up)", (f, to) == (D(2026, 9, 17), D(2026, 11, 1)), (f, to))
    c, k, f, to = window("schedule", None, None, D(2026, 11, 1), marks1, "q2-changed")
    t("a changed query file has no watermark and falls back to the default window", f == D(2026, 10, 1))
    try: window("schedule", "2026-01-01", None, D(2026, 10, 1), marks0, "q1"); t("scheduled run with inputs refused", False)
    except SystemExit: t("scheduled run with window inputs is a configuration error", True)

    cfg = {"new_instrument_query": {"x": 1}, "records": [{"instrument_id": "a", "abbreviations": ["A"], "abbreviation_context": ["c"], "citation_seeds": [{"openalex_id": "W1"}]},
                                                       {"instrument_id": "b", "abbreviations": ["B"], "citation_seeds": [{"doi": "no id"}]}]}
    exp = expected_channels(cfg)
    t("expected channel set: names for both, abbreviation and cites for a only (b lacks context and an OpenAlex id), plus new-instrument",
      exp == [(None, "new-instrument"), ("a", "abbreviation"), ("a", "cites"), ("a", "names"), ("b", "names")], exp)
    t("a pair with one failed source channel is not complete", complete_pairs([{"instrument_id": "a", "route": "names", "outcome": "complete"}, {"instrument_id": "a", "route": "names", "outcome": "failed"}]) == set())
    Q = "q" * 64
    def env(cycle="2026-10", kind="planned", status="complete", full=True, q=Q, drop=None):
        chans = [{"instrument_id": i, "route": r, "outcome": "complete"} for i, r in exp if (i, r) != drop]
        return {"cycle": {"id": cycle, "kind": kind}, "status": status, "full_inventory": full, "query_sha256": q, "channels": chans}
    def mark(run, sha, cycle="2026-10", status="complete"):
        return {"author": "app/github-actions", "body": f"text\n<!-- owhs-cycle cycle_id={cycle} kind=planned github_run_id={run} artefact_sha256={sha} status={status} -->"}
    good = env(); sha = hashlib.sha256(json.dumps(good).encode()).hexdigest()
    runs = [{"github_run_id": "100", "conclusion": "success", "event": "schedule"}]
    rid, why = verify("2026-10", Q, exp, runs, {"100": (good, sha)}, [mark("100", sha)])
    t("a successful, complete, full-inventory, correlated cycle is accepted", rid == "100", why)
    rid, why = verify("2026-10", Q, exp, runs, {"100": (good, sha)}, [mark("999", sha)])
    t("an unrelated successful run plus an issue naming another run is refused", rid is None and "names this run" in why[0], why)
    rid, why = verify("2026-10", Q, exp, runs, {"100": (good, sha)}, [{"author": "someone", "body": mark("100", sha)["body"]}])
    t("a hand-authored issue with the right marker is refused", rid is None, why)
    miss = env(drop=("b", "names")); s2 = hashlib.sha256(json.dumps(miss).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (miss, s2)}, [mark("100", s2)])
    t("a missing channel is counted against the expected denominator and refused", rid is None and "expected channels not complete" in why[0], why)
    alt = env(q="z" * 64); s3 = hashlib.sha256(json.dumps(alt).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (alt, s3)}, [mark("100", s3)])
    t("an artefact built from a different query file is refused", rid is None and "query file hash" in why[0], why)
    failed_runs = [{"github_run_id": "100", "conclusion": "failure", "event": "schedule"}]
    rid, why = verify("2026-10", Q, exp, failed_runs, {"100": (good, sha)}, [mark("100", sha)])
    t("a failed run with a complete-looking issue is refused", rid is None and "conclusion failure" in why[0], why)
    part = env(status="partial"); s4 = hashlib.sha256(json.dumps(part).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (part, s4)}, [mark("100", s4)])
    t("a partial run is refused even with a matching issue", rid is None and "status 'partial'" in why[0], why)
    man = env(cycle="manual-2026-01-01-2026-03-31", kind="manual"); s5 = hashlib.sha256(json.dumps(man).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (man, s5)}, [mark("100", s5, cycle="manual-2026-01-01-2026-03-31")])
    t("a manual catch-up run does not satisfy the planned cycle", rid is None, why)
    rid, why = verify("2026-10", Q, exp, runs, {"100": (good, sha)}, [mark("100", "0" * 64)])
    t("an issue whose artefact hash differs from the artefact is refused", rid is None, why)
    rid, why = verify("2026-10", Q, exp, [], {}, [])
    t("no runs at all is refused with a reason", rid is None and why)
    one = env(full=False); s6 = hashlib.sha256(json.dumps(one).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (one, s6)}, [mark("100", s6)])
    t("a one-instrument run is refused as not full inventory", rid is None and "full-inventory" in why[0], why)
    # watermark advance only from a complete proposal, only forward, in a temporary file
    with tempfile.TemporaryDirectory() as tmp:
        wm = Path(tmp) / "w.json"; art = Path(tmp) / "a.json"
        art.write_text(json.dumps({"status": "partial"})); 
        try: advance(art, wm); t("advance from a partial artefact refused", False)
        except SystemExit: t("advance from an artefact without a proposal is refused", True)
        art.write_text(json.dumps({"watermark_proposal": {"query_sha256": Q, "last_complete_to": "2026-10-01", "cycle_id": "2026-10", "run_id": "r1"}}))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()): advance(art, wm)
        t("advance writes the proposal", json.loads(wm.read_text())["entries"][Q]["last_complete_to"] == "2026-10-01")
        try: advance(art, wm); t("re-advance refused", False)
        except SystemExit: t("an advance that does not move forward is refused", True)
    print(f"{'all' if not failures else failures} cycle contract cases {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


def main():
    a = sys.argv[1:]
    if a == ["--self-test"]: return self_test()
    if a and a[0] == "window":
        opts = dict(zip(a[1::2], a[2::2]))
        today = datetime.date.fromisoformat(opts["--today"]) if "--today" in opts else datetime.date.today()
        cycle_id, kind, f, t = window(opts.get("--event", "workflow_dispatch"), opts.get("--from"), opts.get("--to"), today, load_watermarks(), query_sha())
        print(f"cycle_id={cycle_id}\nkind={kind}\nfrom={f.isoformat()}\nto={t.isoformat()}"); return
    if a and a[0] == "verify":
        opts = dict(zip(a[1::2], a[2::2])); repo = opts.get("--repo") or os.environ.get("GITHUB_REPOSITORY") or "openworkplacehealth/OWHS"
        rid, why = verify_live(opts["--cycle"], repo)
        for w in why: print("  ", w)
        if rid: print(f"cycle {opts['--cycle']} verified: run {rid}"); return
        print(f"cycle {opts['--cycle']} not verified"); sys.exit(1)
    if a and a[0] == "advance":
        opts = dict(zip(a[1::2], a[2::2])); return advance(opts["--artefact"])
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
