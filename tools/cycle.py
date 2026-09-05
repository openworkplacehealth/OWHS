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


def expected_channels(cfg, date_from, date_to, catch_from=None, full_history=False):
    """Every channel a full-inventory run must account for, at query granularity: one descriptor per instrument, route, provider,
    date basis and exact query (or seed), with a stable channel id, from the harvester's own planning function so the verifier's
    denominator is exactly what the harvester planned. A provider filter that is not available in this configuration is listed
    with its reason; the run reports it as unavailable rather than claiming it ran."""
    import harvest
    out = []
    for rec in cfg["records"]:
        out += harvest.planned_channels(rec, cfg, date_from, date_to, catch_from, full_history)
    out += [desc for desc, _ in harvest.new_instrument_channels(cfg, date_from, date_to)]
    return sorted(out, key=lambda c: (c["instrument_id"] or "", c["route"], c["source"], c["date_basis"], c["query"]))


def channels_not_complete(expected, channels):
    """Expected channels whose run did not complete, by channel id. A channel declared unavailable in the plan may be reported as
    unavailable; anything else must be complete. A channel absent from the run is missing, and stays in the denominator."""
    by_id = {c.get("channel_id"): c for c in channels}
    out = []
    for e in expected:
        ran = by_id.get(e["channel_id"])
        ok = ran is not None and (ran.get("outcome") == "complete" or (e.get("unavailable") and ran.get("outcome") == "unavailable"))
        if not ok: out.append({k: e[k] for k in ("instrument_id", "route", "source", "date_basis", "channel_id")} | {"outcome": ran.get("outcome") if ran else "missing"})
    return out


def load_watermarks(path=WATERMARKS):
    if Path(path).exists(): return json.loads(Path(path).read_text(encoding="utf-8"))
    return {"schema_version": "1.0", "overlap_days": 14, "entries": {}, "note": "Advanced only through a merged pull request, after a complete full-inventory run."}


CATCH_UP_DAYS = 90       # ingestion catch-up: Europe PMC first-index date over this many days before the window end
QUARTER_MONTHS = (1, 4, 7, 10)


def window(event, in_from, in_to, today, marks, qsha):
    """(cycle_id, kind, from, to). Explicit inputs make a manual cycle; otherwise the planned cycle of today's month.
    See plan() for the catch-up window and the quarterly full-history flag."""
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


def plan(event, in_from, in_to, today, marks, qsha):
    """The full plan for a run: cycle id and kind, publication window, first-index catch-up window (90 days before the end) and
    whether this planned cycle is a quarterly one that also reruns names and citation links over the full history."""
    cycle_id, kind, f, t = window(event, in_from, in_to, today, marks, qsha)
    catch_from = t - datetime.timedelta(days=CATCH_UP_DAYS)
    quarterly = kind == "planned" and today.month in QUARTER_MONTHS
    return {"cycle_id": cycle_id, "kind": kind, "from": f, "to": t, "catch_from": catch_from, "full_history": quarterly}


def verify(cycle_id, qsha, expected, runs, artefacts, issues):
    """Pure correlation. runs: [{github_run_id, conclusion, event}]; artefacts: {github_run_id: (envelope dict, sha256)};
    issues: [{author, body}]; expected: the current plan's channel descriptors for this cycle (None: accept the artefact's own set).
    Returns (accepted_run_id or None, reasons)."""
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
        exp = env.get("expected_channels") if isinstance(env.get("expected_channels"), list) else None
        if not exp: reasons.append(f"run {rid}: artefact carries no expected channel set"); continue
        if expected is not None and {c["channel_id"] for c in exp} != {c["channel_id"] for c in expected}:
            reasons.append(f"run {rid}: the artefact's expected channel set differs from the current plan for this cycle"); continue
        missing = channels_not_complete(exp, env.get("channels", []))
        if missing: reasons.append(f"run {rid}: {len(missing)} of {len(exp)} expected channels not complete: {[m['channel_id'] for m in missing][:5]}"); continue
        if env.get("channels_not_complete"): reasons.append(f"run {rid}: artefact itself lists {len(env['channels_not_complete'])} channels not complete"); continue
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
    pl = plan("schedule", None, None, datetime.date.fromisoformat(f"{cycle_id}-01"), load_watermarks(), query_sha())
    # the expected set is compared on channel ids, which depend on the exact queries and not on the window dates
    return verify(cycle_id, query_sha(), None, runs, artefacts, issues)


def advance_problems(env):
    """Why an artefact cannot advance the watermark. The proposal is checked against the envelope it sits in, never trusted alone."""
    p = []
    prop = env.get("watermark_proposal")
    if not isinstance(prop, dict): return ["no watermark proposal: the run was not a complete full-inventory planned run"]
    if env.get("status") != "complete": p.append(f"status is {env.get('status')!r}, not complete")
    if env.get("full_inventory") is not True: p.append("not a full-inventory run")
    if (env.get("cycle") or {}).get("kind") != "planned": p.append("not a planned cycle")
    if env.get("channels_not_complete"): p.append(f"{len(env['channels_not_complete'])} expected channels not complete")
    exp = env.get("expected_channels") or []
    if not exp: p.append("no expected channel set")
    elif channels_not_complete(exp, env.get("channels", [])): p.append("a channel in the expected set did not complete")
    if prop.get("query_sha256") != env.get("query_sha256"): p.append("proposal query hash differs from the envelope's")
    if prop.get("cycle_id") != (env.get("cycle") or {}).get("id"): p.append("proposal cycle id differs from the envelope's")
    if prop.get("run_id") != env.get("run_id"): p.append("proposal run id differs from the envelope's")
    if prop.get("last_complete_to") != (env.get("requested_window") or {}).get("to"): p.append("proposal window end differs from the requested window")
    if prop.get("channels_complete") != len(exp): p.append("proposal channel count differs from the expected set")
    for k in ("last_complete_to", "catch_from"):
        v = prop.get(k)
        if v is not None:
            try: datetime.date.fromisoformat(v)
            except (TypeError, ValueError): p.append(f"proposal {k} is not a valid date")
    if not isinstance(prop.get("query_sha256"), str) or len(prop["query_sha256"]) != 64: p.append("proposal query hash malformed")
    return p


def advance(artefact_path, path=WATERMARKS):
    env = json.loads(Path(artefact_path).read_text(encoding="utf-8"))
    problems = advance_problems(env)
    if problems: raise SystemExit("this artefact cannot advance the watermark: " + "; ".join(problems))
    prop = env["watermark_proposal"]
    marks = load_watermarks(path)
    cur = marks["entries"].get(prop["query_sha256"])
    if cur and cur["last_complete_to"] >= prop["last_complete_to"]: raise SystemExit(f"watermark already at {cur['last_complete_to']}; nothing to advance")
    marks["entries"][prop["query_sha256"]] = {k: v for k, v in prop.items() if k != "note"} | {"advanced_on": datetime.date.today().isoformat(), "date_bases": env.get("date_bases")}
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

    cfg = {"property_terms": ["validation"], "new_instrument_query": {"context_terms": ["work"], "object_terms": ["scale"], "evidence_terms": ["validation"]},
           "records": [{"instrument_id": "a", "names": ["Alpha Scale", "Alpha Inventory"], "abbreviations": ["A"], "abbreviation_context": ["c"], "citation_seeds": [{"openalex_id": "W1"}, {"openalex_id": "W2"}]},
                       {"instrument_id": "b", "names": ["Beta"], "abbreviations": ["B"], "citation_seeds": [{"doi": "no id"}]}]}
    exp = expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", False)
    kinds = sorted({(c["instrument_id"] or "", c["route"], c["source"], c["date_basis"]) for c in exp})
    t("expected channels at query granularity: two alias names and two seeds for a are separate channels; b has no abbreviation context and no OpenAlex seed id",
      sum(1 for c in exp if c["instrument_id"] == "a" and c["route"] == "names" and c["date_basis"] == "publication") == 2 and sum(1 for c in exp if c["route"] == "cites") == 2 and not any(c["instrument_id"] == "b" and c["route"] in ("abbreviation", "cites") for c in exp), kinds)
    t("the catch-up basis adds first-index channels on Europe PMC and lists the OpenAlex update filter as unavailable", any(c["date_basis"] == "first_indexed" and c["source"] == "europepmc" for c in exp) and any(c["unavailable"] for c in exp))
    expq = expected_channels(cfg, "2026-09-01", "2026-10-01", None, True)
    t("a quarterly plan adds full-history names and citation channels", any(c["date_basis"] == "full_history" and c["route"] == "cites" for c in expq) and not any(c["date_basis"] == "full_history" and c["route"] == "abbreviation" for c in expq))
    alias = [c for c in exp if c["instrument_id"] == "a" and c["route"] == "names" and c["date_basis"] == "publication" and c["source"] == "europepmc"]
    ran_minus_one = [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in exp if c["channel_id"] != alias[1]["channel_id"]]
    t("dropping one alias channel while its sibling completes is visible in the denominator", [m["channel_id"] for m in channels_not_complete(exp, ran_minus_one)] == [alias[1]["channel_id"]])
    full_run = [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in exp]
    t("a full run with the declared-unavailable filter reported as unavailable has nothing missing", channels_not_complete(exp, full_run) == [])
    Q = "q" * 64
    def env(cycle="2026-10", kind="planned", status="complete", full=True, q=Q, drop=None, channels=None, expected=None):
        chans = channels if channels is not None else [c for c in full_run if c["channel_id"] != drop]
        e = {"cycle": {"id": cycle, "kind": kind}, "status": status, "full_inventory": full, "query_sha256": q, "run_id": "r1",
             "requested_window": {"from": "2026-09-01", "to": "2026-10-01"}, "expected_channels": expected if expected is not None else exp, "channels": chans}
        e["channels_not_complete"] = channels_not_complete(e["expected_channels"], chans)
        return e
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
    miss = env(drop=alias[1]["channel_id"]); s2 = hashlib.sha256(json.dumps(miss).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (miss, s2)}, [mark("100", s2)])
    t("one missing alias channel (sibling complete) is refused against the full denominator", rid is None and "not complete" in why[0], why)
    alt = env(q="z" * 64); s3 = hashlib.sha256(json.dumps(alt).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (alt, s3)}, [mark("100", s3)])
    t("an artefact built from a different query file is refused", rid is None and "query file hash" in why[0], why)
    narrower = env(expected=[c for c in exp if c["route"] != "cites"], channels=[c for c in full_run if c["route"] != "cites"]); s7 = hashlib.sha256(json.dumps(narrower).encode()).hexdigest()
    rid, why = verify("2026-10", Q, exp, runs, {"100": (narrower, s7)}, [mark("100", s7)])
    t("an artefact whose own expected set is narrower than the current plan is refused", rid is None and "differs from the current plan" in why[0], why)
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
    # plan: quarterly flag and catch-up window
    pl = plan("schedule", None, None, D(2026, 10, 1), marks0, "q1")
    t("1 October plan: cycle 2026-10, catch-up from 3 July (90 days), quarterly full history on", (pl["cycle_id"], pl["catch_from"], pl["full_history"]) == ("2026-10", D(2026, 7, 3), True), pl)
    pl = plan("schedule", None, None, D(2026, 11, 1), marks0, "q1")
    t("1 November plan: not quarterly", pl["full_history"] is False)
    # watermark advance: the proposal is checked against its envelope; a stale proposal on a failed, partial or incomplete envelope is refused
    with tempfile.TemporaryDirectory() as tmp:
        wm = Path(tmp) / "w.json"; art = Path(tmp) / "a.json"
        stale = {"query_sha256": Q, "last_complete_to": "2026-10-01", "catch_from": "2026-07-03", "cycle_id": "2026-10", "run_id": "r1", "channels_complete": len(exp)}
        art.write_text(json.dumps({"status": "failed", "full_inventory": False, "channels": [], "expected_channels": exp, "cycle": {"id": "2026-10", "kind": "planned"}, "query_sha256": Q, "run_id": "r1", "requested_window": {"to": "2026-10-01"}, "watermark_proposal": stale}))
        try: advance(art, wm); t("a failed envelope carrying a populated proposal is refused", False)
        except SystemExit as e: t("a failed envelope carrying a populated proposal is refused", "not complete" in str(e) and "full-inventory" in str(e))
        partial = env(status="partial"); partial["watermark_proposal"] = stale; art.write_text(json.dumps(partial))
        try: advance(art, wm); t("a partial envelope with a stale proposal is refused", False)
        except SystemExit as e: t("a partial envelope with a stale proposal is refused", "partial" in str(e))
        missing_ch = env(drop=alias[1]["channel_id"]); missing_ch["watermark_proposal"] = stale; art.write_text(json.dumps(missing_ch))
        try: advance(art, wm); t("a complete-looking envelope missing one expected channel is refused", False)
        except SystemExit as e: t("a complete-looking envelope missing one expected channel is refused", "not complete" in str(e))
        okenv = env(); okenv["watermark_proposal"] = dict(stale); art.write_text(json.dumps(okenv))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()): advance(art, wm)
        t("a legitimate complete forward advance writes the proposal with its date bases", json.loads(wm.read_text())["entries"][Q]["last_complete_to"] == "2026-10-01")
        try: advance(art, wm); t("re-advance refused", False)
        except SystemExit: t("an advance that does not move forward is refused", True)
        bad = env(); bad["watermark_proposal"] = dict(stale, query_sha256="y" * 64); art.write_text(json.dumps(bad))
        try: advance(art, wm); t("a proposal whose query hash disagrees with its envelope is refused", False)
        except SystemExit as e: t("a proposal whose query hash disagrees with its envelope is refused", "query hash" in str(e))
        bad = env(); bad["watermark_proposal"] = dict(stale, last_complete_to="2026-13-40"); art.write_text(json.dumps(bad))
        try: advance(art, wm); t("a proposal with an invalid date is refused", False)
        except SystemExit as e: t("a proposal with an invalid date is refused", "valid date" in str(e) or "differs" in str(e))
    print(f"{'all' if not failures else failures} cycle contract cases {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


def main():
    a = sys.argv[1:]
    if a == ["--self-test"]: return self_test()
    if a and a[0] == "window":
        opts = dict(zip(a[1::2], a[2::2]))
        today = datetime.date.fromisoformat(opts["--today"]) if "--today" in opts else datetime.date.today()
        pl = plan(opts.get("--event", "workflow_dispatch"), opts.get("--from"), opts.get("--to"), today, load_watermarks(), query_sha())
        print(f"cycle_id={pl['cycle_id']}\nkind={pl['kind']}\nfrom={pl['from'].isoformat()}\nto={pl['to'].isoformat()}\ncatch_from={pl['catch_from'].isoformat()}\nfull_history={'true' if pl['full_history'] else 'false'}"); return
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
