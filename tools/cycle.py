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


def read_at_head(head_sha, path, root=None):
    """Bytes of `path` as committed at `head_sha`, from this repository's object store; None when unreadable. The working tree is
    never consulted: the plan is derived from what the run actually checked out."""
    try:
        r = subprocess.run(["git", "-C", str(root or ROOT), "show", f"{head_sha}:{path}"], capture_output=True)
        return r.stdout if r.returncode == 0 else None
    except Exception: return None


def trusted_plan(run, reader=read_at_head):
    """The plan a run was required to follow, derived from trusted run context and the pinned policy, never from the artefact:
    the run's event, its start date (UTC) and the watermarks and query configuration as committed at the run's head. Returns
    (plan dict with the head's configuration and query hash, None) or (None, reason) when the provenance is not readable."""
    head, started, event = run.get("head_sha"), run.get("started_at"), run.get("event")
    if not head or not started or not event: return None, "run context lacks head, start time or event; the plan cannot be derived"
    try: today = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00")).astimezone(datetime.timezone.utc).date()
    except ValueError: return None, f"run start time {started!r} is not a date-time"
    qbytes = reader(head, "evidence/queries/instruments-v1.json")
    if qbytes is None: return None, f"query configuration at head {str(head)[:12]} is not readable; the plan cannot be derived"
    wbytes = reader(head, "evidence/watermarks.json")
    try:
        cfg = json.loads(qbytes.decode("utf-8")); marks = json.loads(wbytes.decode("utf-8")) if wbytes is not None else load_watermarks("/nonexistent")
    except (ValueError, UnicodeDecodeError) as e: return None, f"configuration at head {str(head)[:12]} does not parse: {e}"
    qsha_head = hashlib.sha256(qbytes).hexdigest()
    if event not in ("schedule", "workflow_dispatch"): return None, f"run event {event!r} is not a harvest trigger"
    try: pl = plan(event, None, None, today, marks, qsha_head)          # a planned cycle: explicit inputs would make a manual cycle, which cannot satisfy it
    except SystemExit as e: return None, str(e)
    return {**pl, "cfg": cfg, "qsha_at_head": qsha_head, "head_sha": head, "run_date": today}, None


def envelope_against_plan(env, pl):
    """Every window and date-base declaration in the artefact must equal the trusted plan; the artefact never relabels the plan."""
    p = []
    cyc = env.get("cycle") or {}
    if cyc.get("id") != pl["cycle_id"] or cyc.get("kind") != pl["kind"]: p.append(f"cycle {cyc.get('id')!r}/{cyc.get('kind')!r} is not the trusted {pl['cycle_id']!r}/{pl['kind']!r}")
    rw = env.get("requested_window") or {}
    if (rw.get("from"), rw.get("to")) != (pl["from"].isoformat(), pl["to"].isoformat()): p.append(f"requested window {rw.get('from')} to {rw.get('to')} is not the trusted {pl['from']} to {pl['to']}")
    db = env.get("date_bases") or {}
    fi = db.get("first_indexed") or {}
    if (fi.get("from"), fi.get("to")) != (pl["catch_from"].isoformat(), pl["to"].isoformat()): p.append(f"first-index catch-up {fi.get('from')} to {fi.get('to')} is not the trusted {pl['catch_from']} to {pl['to']}")
    if bool(db.get("full_history")) != bool(pl["full_history"]): p.append(f"full history {bool(db.get('full_history'))} is not the trusted {pl['full_history']} for {pl['cycle_id']}")
    if env.get("query_sha256") != pl["qsha_at_head"]: p.append(f"query file hash {str(env.get('query_sha256'))[:12]} is not the configuration at the run's head {pl['qsha_at_head'][:12]}")
    return p


def policy_problems(expected, declared):
    """The artefact's declared channel set must equal the authoritative plan channel by channel, including whether each is
    required or declared unavailable, its provider, route, date basis and exact query. Duplicate ids are refused."""
    p = []
    ids = [c.get("channel_id") for c in declared]
    if len(ids) != len(set(ids)): p.append("duplicate channel ids in the artefact's expected set")
    exp = {c["channel_id"]: c for c in expected}; dec = {c.get("channel_id"): c for c in declared}
    missing = sorted(set(exp) - set(dec)); extra = sorted(set(dec) - set(exp))
    if missing: p.append(f"{len(missing)} channels required by the plan are absent from the artefact's expected set: {missing[:5]}")
    if extra: p.append(f"{len(extra)} channels in the artefact's expected set are not in the plan: {extra[:5]}")
    for cid in set(exp) & set(dec):
        e, d = exp[cid], dec[cid]
        for k in ("instrument_id", "route", "source", "date_basis", "query"):
            if e.get(k) != d.get(k): p.append(f"channel {cid}: {k} differs from the plan"); break
        if bool(e.get("unavailable")) != bool(d.get("unavailable")): p.append(f"channel {cid}: the artefact declares {'unavailable' if d.get('unavailable') else 'required'}, the plan says {'unavailable' if e.get('unavailable') else 'required'}")
    return p


def verify(cycle_id, qsha, expected, runs, artefacts, issues, cfg=None, trusted=None):
    """Pure correlation. runs: [{github_run_id, conclusion, event, head_sha, started_at}]; artefacts: {github_run_id: (envelope dict,
    sha256)}; issues: [{author, body}]. The plan is either `expected` (a fixed authoritative channel set, for offline contract tests)
    or, in the live path, `trusted[run_id]`: the plan derived from the run's own context by trusted_plan(), against which the
    artefact's windows, date bases, cycle and configuration hash are compared before its channels are judged. An artefact's own
    dates never reconstruct the plan; a run without a derivable plan is unverified with the reason. Returns (accepted_run_id or
    None, reasons)."""
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
        declared = env.get("expected_channels") if isinstance(env.get("expected_channels"), list) else None
        if not declared: reasons.append(f"run {rid}: artefact carries no expected channel set"); continue
        if expected is not None: plan = expected
        elif trusted is not None:
            tp, why_not = trusted.get(rid, (None, "no trusted plan derived for this run"))
            if tp is None: reasons.append(f"run {rid}: unverified, {why_not}"); continue
            mism = envelope_against_plan(env, tp)
            if mism: reasons.append(f"run {rid}: artefact departs from the trusted plan: " + "; ".join(mism[:3])); continue
            plan = expected_channels(tp["cfg"], tp["from"].isoformat(), tp["to"].isoformat(), tp["catch_from"].isoformat(), tp["full_history"])
        else: reasons.append(f"run {rid}: no authoritative plan available to judge the artefact against (the artefact's own dates are not one)"); continue
        pol = policy_problems(plan, declared)
        if pol: reasons.append(f"run {rid}: " + "; ".join(pol[:3])); continue
        missing = channels_not_complete(plan, env.get("channels", []))          # judged against the plan's policy, not the artefact's
        if missing: reasons.append(f"run {rid}: {len(missing)} of {len(plan)} required channels not complete: {[m['channel_id'] for m in missing][:5]}"); continue
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


def fetch_live(cycle_id, repo, gh_json=None, download=None):
    """Read-only collection through gh: runs of the workflow this month, each successful run's artefact, and the cycle's issues."""
    gh_json = gh_json or gh
    since = f"{cycle_id}-01T00:00:00Z"
    runs = json.loads(gh_json("run", "list", "--repo", repo, "--workflow", WORKFLOW, "--created", f">={since}", "--json", "databaseId,conclusion,event,headSha,startedAt", "--limit", "50"))
    runs = [{"github_run_id": str(r["databaseId"]), "conclusion": r["conclusion"], "event": r["event"], "head_sha": r.get("headSha"), "started_at": r.get("startedAt")} for r in runs]
    artefacts = {}
    for r in runs:
        if r["conclusion"] != "success": continue
        got = (download or _download_artefact)(r["github_run_id"], repo, cycle_id)
        if got: artefacts[r["github_run_id"]] = got
    issues = json.loads(gh_json("issue", "list", "--repo", repo, "--label", "evidence-sweep", "--state", "all", "--search", f'"Evidence harvest {cycle_id}" in:title', "--json", "author,body"))
    issues = [{"author": ("app/" + i["author"]["login"]) if i["author"].get("is_bot") else i["author"]["login"], "body": i["body"]} for i in issues]
    return runs, artefacts, issues


def _download_artefact(run_id, repo, cycle_id):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / run_id
        p = subprocess.run(["gh", "run", "download", run_id, "--repo", repo, "-n", f"candidates-{cycle_id}", "-D", str(d)], capture_output=True, text=True)
        if p.returncode != 0: return None
        files = list(d.glob("*.json"))
        if not files: return None
        return (json.loads(files[0].read_text(encoding="utf-8")), hashlib.sha256(files[0].read_bytes()).hexdigest())


def verify_live(cycle_id, repo, gh_json=None, download=None, cfg=None, qsha=None, reader=read_at_head):
    """The live wrapper: fetch, derive each run's trusted plan from its head commit (watermarks and query configuration as
    committed there), start date and event, then judge every artefact against that plan. Nothing in the artefact and nothing in
    the ambient environment (a key present or absent) changes the plan; a run whose provenance is unreadable is unverified."""
    runs, artefacts, issues = fetch_live(cycle_id, repo, gh_json, download)
    trusted = {r["github_run_id"]: trusted_plan(r, reader) for r in runs}
    return verify(cycle_id, qsha or query_sha(), None, runs, artefacts, issues, cfg=cfg, trusted=trusted)


def advance_problems(env, reader=read_at_head, queries_path=None):
    """Why an artefact cannot advance the watermark. Fails closed: the current query configuration must exist and carry the
    proposal's hash, and the plan is derived from the run's recorded head (registry_commit) and start time through the trusted
    reader; the artefact's own dates and channel list are validated against it, never used in their place."""
    p = []
    prop = env.get("watermark_proposal")
    if not isinstance(prop, dict): return ["no watermark proposal: the run was not a complete full-inventory planned run"]
    if env.get("status") != "complete": p.append(f"status is {env.get('status')!r}, not complete")
    if env.get("full_inventory") is not True: p.append("not a full-inventory run")
    if (env.get("cycle") or {}).get("kind") != "planned": p.append("not a planned cycle")
    if env.get("channels_not_complete"): p.append(f"{len(env['channels_not_complete'])} expected channels not complete")
    exp = env.get("expected_channels") or []
    if not exp: p.append("no expected channel set")
    qpath = Path(queries_path) if queries_path else QUERIES
    if not qpath.exists(): p.append("the query configuration is missing; cannot advance without it")
    elif prop.get("query_sha256") != query_sha(qpath): p.append(f"the proposal's query hash {str(prop.get('query_sha256'))[:12]} is not the current configuration's {query_sha(qpath)[:12]}; a watermark belongs to the configuration that produced it")
    tp, why = trusted_plan({"head_sha": env.get("registry_commit"), "started_at": env.get("started_at"), "event": env.get("run_event", "schedule")}, reader)
    if tp is None: p.append(f"run provenance: {why}")
    elif exp:
        mism = envelope_against_plan(env, tp)
        if mism: p.append("the artefact departs from the trusted plan: " + mism[0])
        else:
            plan_ch = expected_channels(tp["cfg"], tp["from"].isoformat(), tp["to"].isoformat(), tp["catch_from"].isoformat(), tp["full_history"])
            pol = policy_problems(plan_ch, exp)
            if pol: p.append("the artefact's expected set differs from the trusted plan: " + pol[0])
            elif channels_not_complete(plan_ch, env.get("channels", [])): p.append("a channel required by the trusted plan did not complete")
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


def advance(artefact_path, path=WATERMARKS, reader=read_at_head, queries_path=None):
    env = json.loads(Path(artefact_path).read_text(encoding="utf-8"))
    problems = advance_problems(env, reader, queries_path)
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
    t("an artefact whose own expected set is narrower than the current plan is refused", rid is None and "required by the plan are absent" in why[0], why)
    # the live wrapper, with gh stubbed: the plan is reconstructed from the query file at the artefact's dates, never taken from the artefact
    def stub_gh_factory(runs_json, issues_json):
        def stub(*args):
            if args[0] == "run": return json.dumps(runs_json)
            if args[0] == "issue": return json.dumps(issues_json)
            raise AssertionError(args)
        return stub
    def env_live(expected, channels, q=Q, **kw):
        e = {"cycle": {"id": "2026-10", "kind": "planned"}, "status": "complete", "full_inventory": True, "query_sha256": q, "run_id": "r1",
             "requested_window": {"from": "2026-09-01", "to": "2026-10-01"}, "date_bases": {"publication": {"from": "2026-09-01", "to": "2026-10-01"}, "first_indexed": {"from": "2026-07-03", "to": "2026-10-01"}, "full_history": False},
             "expected_channels": expected, "channels": channels}
        e.update(kw); e["channels_not_complete"] = channels_not_complete(e["expected_channels"], e["channels"]); return e
    # trusted run context: the fixture configuration is what the run's head committed, so its hash is the query hash everywhere below
    CFG_BYTES = json.dumps(cfg).encode(); QH = hashlib.sha256(CFG_BYTES).hexdigest(); HEAD = "a" * 40
    MARKS_AT_HEAD = {"overlap_days": 14, "entries": {}}
    def reader_factory(marks=None, missing_query=False):
        def reader(head, path):
            if head != HEAD: return None
            if path.endswith("instruments-v1.json"): return None if missing_query else CFG_BYTES
            if path.endswith("watermarks.json"): return json.dumps(marks if marks is not None else MARKS_AT_HEAD).encode()
            return None
        return reader
    # 1 October 2026 is a quarterly month: the trusted plan is 1 September to 1 October, catch-up from 3 July, full history on
    plan_live = expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", True)
    full_live = [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in plan_live]
    runs_json = [{"databaseId": 100, "conclusion": "success", "event": "schedule", "headSha": HEAD, "startedAt": "2026-10-01T06:00:12Z"}]
    def env_trusted(expected, channels, **kw):
        e = env_live(expected, channels, q=QH, date_bases={"publication": {"from": "2026-09-01", "to": "2026-10-01"}, "first_indexed": {"from": "2026-07-03", "to": "2026-10-01"}, "full_history": True})
        e.update(kw); e["channels_not_complete"] = channels_not_complete(e["expected_channels"], e["channels"]); return e
    def live_with(envelope, runs=runs_json, reader=None, cycle="2026-10", run_id="100"):
        sha_ = hashlib.sha256(json.dumps(envelope).encode()).hexdigest()
        issues = [{"author": {"login": "github-actions", "is_bot": True}, "body": f"<!-- owhs-cycle cycle_id={cycle} kind=planned github_run_id={run_id} artefact_sha256={sha_} -->"}]
        return verify_live(cycle, "example/repo", gh_json=stub_gh_factory(runs, issues), download=lambda rid_, repo, cyc: (envelope, sha_), cfg=cfg, qsha=QH, reader=reader or reader_factory())
    rid, why = live_with(env_trusted(plan_live, full_live)); t("live wrapper: an artefact matching the trusted plan (windows, catch-up, quarterly full history, configuration at head) passes", rid == "100", why)
    # five counterexamples: each departs from the trusted plan in one declaration and is refused
    nofh = env_trusted(expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", False), [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", False)])
    nofh["date_bases"]["full_history"] = False
    rid, why = live_with(nofh); t("trusted plan: an October artefact with full history disabled is refused", rid is None and "full history" in why[0], why)
    nocatch = env_trusted(expected_channels(cfg, "2026-09-01", "2026-10-01", None, True), [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in expected_channels(cfg, "2026-09-01", "2026-10-01", None, True)])
    nocatch["date_bases"]["first_indexed"] = None
    rid, why = live_with(nocatch); t("trusted plan: an artefact omitting the first-index catch-up is refused", rid is None and "first-index catch-up" in why[0], why)
    narrow = env_trusted(plan_live, full_live, requested_window={"from": "2026-09-30", "to": "2026-10-01"}); narrow["date_bases"]["publication"] = {"from": "2026-09-30", "to": "2026-10-01"}
    rid, why = live_with(narrow); t("trusted plan: a publication window narrowed to two days is refused even with the same channel count", rid is None and "requested window" in why[0], why)
    old = env_trusted(plan_live, full_live, requested_window={"from": "2020-09-01", "to": "2020-10-01"}); old["date_bases"] = {"publication": {"from": "2020-09-01", "to": "2020-10-01"}, "first_indexed": {"from": "2020-07-03", "to": "2020-10-01"}, "full_history": True}
    rid, why = live_with(old); t("trusted plan: a 2020 window labelled cycle 2026-10 is refused", rid is None and "requested window" in why[0], why)
    # provenance missing: unverified with the reason, never a fallback to the artefact's own dates
    rid, why = live_with(env_trusted(plan_live, full_live), reader=reader_factory(missing_query=True)); t("trusted plan: configuration unreadable at the run's head leaves the run unverified with the reason", rid is None and "not readable" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live), runs=[{"databaseId": 100, "conclusion": "success", "event": "schedule"}]); t("trusted plan: a run listed without head or start time is unverified", rid is None and "lacks head" in why[0], why)
    # legitimate replay: a planned re-run by dispatch on 2 October (window to 2 October, catch-up from 4 July) passes
    rerun = [{"databaseId": 101, "conclusion": "success", "event": "workflow_dispatch", "headSha": HEAD, "startedAt": "2026-10-02T09:30:00Z"}]
    pl2 = expected_channels(cfg, "2026-09-01", "2026-10-02", "2026-07-04", True); fl2 = [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in pl2]
    e2 = env_trusted(pl2, fl2, requested_window={"from": "2026-09-01", "to": "2026-10-02"}); e2["date_bases"] = {"publication": {"from": "2026-09-01", "to": "2026-10-02"}, "first_indexed": {"from": "2026-07-04", "to": "2026-10-02"}, "full_history": True}
    rid, why = live_with(e2, runs=rerun, run_id="101"); t("trusted plan: a later planned re-run by dispatch with its own run-date window passes", rid == "101", why)
    # a previously advanced watermark at the run's head moves the trusted window start (15 September minus 14 days = 1 September)
    marks_adv = {"overlap_days": 14, "entries": {QH: {"last_complete_to": "2026-09-15"}}}
    rid, why = live_with(env_trusted(plan_live, full_live), reader=reader_factory(marks=marks_adv)); t("trusted plan: a previously advanced watermark at the run's head is honoured (window from 1 September)", rid == "100", why)
    marks_adv2 = {"overlap_days": 14, "entries": {QH: {"last_complete_to": "2026-09-20"}}}
    rid, why = live_with(env_trusted(plan_live, full_live), reader=reader_factory(marks=marks_adv2)); t("trusted plan: an artefact whose window start ignores the head's watermark (6 September expected) is refused", rid is None and "requested window" in why[0], why)
    one = env_trusted([plan_live[0]], [full_live[0]]); rid, why = live_with(one)
    t("live wrapper: a one-channel self-declared manifest fails against the trusted plan", rid is None and "required by the plan are absent" in why[0], why)
    exempt = [dict(c) for c in plan_live]; req = next(c for c in exempt if not c["unavailable"]); req["unavailable"] = "synthetic exemption not in the plan"
    chans = [{**c, "outcome": ("unavailable" if c["unavailable"] else "complete")} for c in exempt]
    rid, why = live_with(env_trusted(exempt, chans)); t("live wrapper: a required channel self-exempted as unavailable by the artefact fails", rid is None and "declares unavailable, the plan says required" in why[0], why)
    import os as _os
    saved = _os.environ.get("OPENALEX_API_KEY"); _os.environ["OPENALEX_API_KEY"] = "probe-not-a-real-key"
    try:
        rid_k, _ = live_with(env_trusted(plan_live, full_live)); plan_k = [c["channel_id"] for c in expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", True)]
    finally:
        if saved is None: _os.environ.pop("OPENALEX_API_KEY", None)
        else: _os.environ["OPENALEX_API_KEY"] = saved
    t("live wrapper: a key present in the ambient environment changes neither the authorised inventory nor the verdict", rid_k == "100" and plan_k == [c["channel_id"] for c in plan_live])
    unav = next(c for c in plan_live if c["unavailable"])
    rid, why = live_with(env_trusted(plan_live, full_live)); t("a configured unavailable channel stays reported as unavailable and the cycle still verifies", rid == "100" and any(c["channel_id"] == unav["channel_id"] and c["outcome"] == "unavailable" for c in full_live))
    dup = env_trusted(plan_live + [plan_live[0]], full_live); rid, why = live_with(dup); t("duplicate channel ids in the artefact are refused", rid is None and "duplicate channel ids" in why[0], why)
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
        wm = Path(tmp) / "w.json"; art = Path(tmp) / "a.json"; qfile = Path(tmp) / "instruments-v1.json"; qfile.write_bytes(CFG_BYTES)
        rd = reader_factory()
        def adv(): return advance(art, wm, reader=rd, queries_path=qfile)
        # a complete planned envelope with its run provenance (head, start) and the trusted plan's windows and channel set
        def env_adv(**kw):
            e = env_trusted(plan_live, full_live, registry_commit=HEAD, started_at="2026-10-01T06:00:12+00:00")
            e.update(kw); e["channels_not_complete"] = channels_not_complete(e["expected_channels"], e["channels"]); return e
        stale = {"query_sha256": QH, "last_complete_to": "2026-10-01", "catch_from": "2026-07-03", "cycle_id": "2026-10", "run_id": "r1", "channels_complete": len(plan_live)}
        art.write_text(json.dumps({**env_adv(status="failed", full_inventory=False, channels=[]), "watermark_proposal": stale}))
        try: adv(); t("a failed envelope carrying a populated proposal is refused", False)
        except SystemExit as e: t("a failed envelope carrying a populated proposal is refused", "not complete" in str(e) and "full-inventory" in str(e))
        partial = env_adv(status="partial"); partial["watermark_proposal"] = stale; art.write_text(json.dumps(partial))
        try: adv(); t("a partial envelope with a stale proposal is refused", False)
        except SystemExit as e: t("a partial envelope with a stale proposal is refused", "partial" in str(e))
        missing_ch = env_adv(channels=[c for c in full_live if c["channel_id"] != plan_live[0]["channel_id"]]); missing_ch["watermark_proposal"] = stale; art.write_text(json.dumps(missing_ch))
        try: adv(); t("a complete-looking envelope missing one expected channel is refused", False)
        except SystemExit as e: t("a complete-looking envelope missing one expected channel is refused", "not complete" in str(e), str(e))
        okenv = env_adv(); okenv["watermark_proposal"] = dict(stale); art.write_text(json.dumps(okenv))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()): adv()
        t("a legitimate complete forward advance writes the proposal with its date bases", json.loads(wm.read_text())["entries"][QH]["last_complete_to"] == "2026-10-01")
        try: adv(); t("re-advance refused", False)
        except SystemExit: t("an advance that does not move forward is refused", True)
        bad = env_adv(); bad["watermark_proposal"] = dict(stale, query_sha256="y" * 64); art.write_text(json.dumps(bad))
        try: adv(); t("a proposal whose query hash is not the current configuration's is refused", False)
        except SystemExit as e: t("a proposal whose query hash is not the current configuration's is refused", "query hash" in str(e) or "configuration" in str(e))
        bad = env_adv(); bad["watermark_proposal"] = dict(stale, last_complete_to="2026-13-40"); art.write_text(json.dumps(bad))
        try: adv(); t("a proposal with an invalid date is refused", False)
        except SystemExit as e: t("a proposal with an invalid date is refused", "valid date" in str(e) or "differs" in str(e))
        # fail closed: configuration missing, or the run's head unreadable, or the artefact departing from the trusted plan
        okenv = env_adv(); okenv["watermark_proposal"] = dict(stale); art.write_text(json.dumps(okenv))
        try: advance(art, Path(tmp) / "w2.json", reader=rd, queries_path=Path(tmp) / "absent.json"); t("advance with the query configuration missing is refused (fail closed)", False)
        except SystemExit as e: t("advance with the query configuration missing is refused (fail closed)", "missing" in str(e))
        try: advance(art, Path(tmp) / "w2.json", reader=reader_factory(missing_query=True), queries_path=qfile); t("advance with the run's head unreadable is refused", False)
        except SystemExit as e: t("advance with the run's head unreadable is refused", "provenance" in str(e))
        narrow_adv = env_adv(requested_window={"from": "2026-09-30", "to": "2026-10-01"}); narrow_adv["date_bases"]["publication"] = {"from": "2026-09-30", "to": "2026-10-01"}; narrow_adv["watermark_proposal"] = dict(stale); art.write_text(json.dumps(narrow_adv))
        try: advance(art, Path(tmp) / "w2.json", reader=rd, queries_path=qfile); t("advance from an artefact whose window departs from the trusted plan is refused", False)
        except SystemExit as e: t("advance from an artefact whose window departs from the trusted plan is refused", "trusted plan" in str(e))
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
