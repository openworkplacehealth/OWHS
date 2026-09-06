#!/usr/bin/env python3
"""The maintenance cycle: one definition, consumed by the harvest workflow, the tripwire and the harvester.

    python tools/cycle.py window  [--event schedule|workflow_dispatch] [--from D] [--to D] [--today D]
    python tools/cycle.py verify  --cycle 2026-10             read-only: correlates run, artefact and issue through gh
    python tools/cycle.py advance --cycle 2026-10 --repo R    verifies the cycle through gh, then writes the accepted run's watermark proposal
                                  [--artefact FILE]          (the file must be byte-identical to the artefact downloaded from that run)
    python tools/cycle.py --self-test                         offline contract suite, no network, no gh

Cycle identity. A planned cycle is named by the month the run happens in: the run on 1 October is cycle 2026-10,
and the tripwire on 3 October looks for cycle 2026-10. The publication window it searches is separate: by default
from the watermark (the end of the last complete full-inventory run) minus an overlap for late indexing, or the
first day of the previous month when no watermark exists, to today. A manual run with an explicit window is a
manual cycle, named manual-FROM-TO; it never satisfies a planned cycle. A manual run with no window is a re-run
of the current planned cycle.

Watermarks (evidence/watermarks.json) advance only after a complete full-inventory run, and only through the
screening pull request a person merges: the harvest writes a proposal into its artefact, `advance` copies it in
after verifying the cycle exactly as the tripwire does, so the authority for a write is the correlated GitHub run,
its head commit and the artefact bytes downloaded from it, never a file supplied on the command line by itself.
The next planned window then starts overlap_days before the watermark, so a work indexed late is seen again.

Trusted run context. The plan a run had to follow is derived from what GitHub records about the run (head commit,
start time, event, and the run name that carries the dispatch inputs) and from the bytes committed at that head:
the watermarks, the query configuration and the planning policy version in tools/harvest.py and tools/cycle.py.
The policy functions execute from the verifier's checkout; a head whose recorded policy version differs from this
file's is unverified as an unsupported historical policy rather than reinterpreted. A shallow checkout cannot read
another commit's tree, so both workflows that verify check out the full history.

Verification. `verify` finds successful runs of the evidence-harvest workflow, downloads the cycle's artefact from
each, and accepts the cycle only when one artefact names this cycle as planned, reports status complete over the
full inventory, has every expected channel complete (the denominator is the query file's channel set, so a missing
channel counts as incomplete), carries the current query file's hash, and a bot-authored issue names that exact
GitHub run and that artefact's hash. A partial run, an unrelated successful run, a hand-written issue or an issue
describing a run that failed does not satisfy it.
"""
import copy, datetime, hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "evidence" / "queries" / "instruments-v1.json"
WATERMARKS = ROOT / "evidence" / "watermarks.json"
WORKFLOW = "evidence-harvest"
MARK = re.compile(r"<!-- owhs-cycle (.*?) -->", re.S)
POLICY_VERSION = "2026.09-1"      # the planning policy (window, catch-up, quarterly full history, channel set); must equal harvest.POLICY_VERSION at a run's head
POLICY_FILES = ("tools/harvest.py", "tools/cycle.py")
POLICY_RE = re.compile(r'^POLICY_VERSION\s*=\s*"([^"]+)"', re.M)
RUN_NAME_RE = re.compile(r"^evidence-harvest (schedule|workflow_dispatch) from=\[(.*?)\] to=\[(.*?)\]$")
HARVEST_START_BOUND = datetime.timedelta(hours=6)   # the harvest step starts after checkout and setup, within the job's default 360-minute timeout
WATERMARKS_PATH = "evidence/watermarks.json"
QUERIES_PATH = "evidence/queries/instruments-v1.json"


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


def tree_at_head(head_sha, root=None):
    """The set of paths committed at `head_sha`, or None when the commit is not readable here (unknown, or absent from a shallow
    checkout). Distinguishes a file historically absent from the tree from an object this checkout cannot read."""
    if not head_sha or not re.fullmatch(r"[0-9a-f]{40}", str(head_sha)): return None
    try:
        r = subprocess.run(["git", "-C", str(root or ROOT), "ls-tree", "-r", "--name-only", str(head_sha)], capture_output=True, text=True)
        return set(r.stdout.split()) if r.returncode == 0 else None
    except Exception: return None


def watermark_shape_problems(marks):
    """Named problems with a committed watermark document; anything here makes the run's provenance unusable, never a default."""
    if not isinstance(marks, dict): return ["watermark document root is not an object"]
    p = []
    od = marks.get("overlap_days", 14)
    if isinstance(od, bool) or not isinstance(od, int) or not 0 <= od <= 90: p.append(f"overlap_days {od!r} is not an integer between 0 and 90")
    ents = marks.get("entries")
    if not isinstance(ents, dict): return p + ["watermark entries is not an object"]
    for k, e in ents.items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(k)): p.append(f"watermark entry key {str(k)[:16]!r} is not a query hash")
        if not isinstance(e, dict): p.append(f"watermark entry {str(k)[:12]} is not an object"); continue
        try: datetime.date.fromisoformat(str(e.get("last_complete_to")))
        except ValueError: p.append(f"watermark entry {str(k)[:12]} has no valid last_complete_to date")
    return p


def policy_at_head(head, reader):
    """The planning policy version recorded in both policy files at the head, or (None, reason)."""
    found = {}
    for path in POLICY_FILES:
        b = reader(head, path)
        if b is None: return None, f"{path} not readable at head {str(head)[:12]}; the policy that run followed cannot be established"
        m = POLICY_RE.search(b.decode("utf-8", "replace"))
        if not m: return None, f"{path} at head {str(head)[:12]} records no policy version; unsupported historical policy"
        found[path] = m.group(1)
    if len(set(found.values())) != 1: return None, f"policy versions disagree at head {str(head)[:12]}: {found}"
    v = next(iter(found.values()))
    if v != POLICY_VERSION: return None, f"policy version {v!r} at head {str(head)[:12]} is not the supported {POLICY_VERSION!r}; unsupported historical policy"
    return v, None


def dispatch_inputs(run):
    """(from, to) inputs of a run as GitHub recorded them in the run name, or (None, reason). A scheduled run carries none by
    construction but must still carry the name, so the same record answers for every run."""
    name = run.get("display_title")
    m = RUN_NAME_RE.match(str(name or ""))
    if not m: return None, "the run name does not record the dispatch inputs (run-name missing or of another form); whether inputs were absent cannot be established"
    if m.group(1) != run.get("event"): return None, f"the run name says {m.group(1)!r} but the run event is {run.get('event')!r}"
    return (m.group(2).strip(), m.group(3).strip()), None


def trusted_plan(run, reader=read_at_head, lister=tree_at_head):
    """The plan a run was required to follow, derived from trusted run context and the pinned policy, never from the artefact:
    the run's event and recorded inputs, its start date (UTC), and the watermarks, query configuration and policy version as
    committed at the run's head. Returns (plan dict with the head's configuration and query hash, None) or (None, reason).
    Missing or malformed historical inputs are reasons, not defaults."""
    head, started, event = run.get("head_sha"), run.get("started_at"), run.get("event")
    if not head or not started or not event: return None, "run context lacks head, start time or event; the plan cannot be derived"
    try: start_dt = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except ValueError: return None, f"run start time {started!r} is not a date-time"
    if event not in ("schedule", "workflow_dispatch"): return None, f"run event {event!r} is not a harvest trigger"
    tree = lister(head)
    if tree is None: return None, f"head {str(head)[:12]} is not readable in this checkout (unknown commit or shallow clone); the plan cannot be derived"
    for path in (QUERIES_PATH, WATERMARKS_PATH):
        if path not in tree: return None, f"{path} is not committed at head {str(head)[:12]}; no default is assumed"
    qbytes, wbytes = reader(head, QUERIES_PATH), reader(head, WATERMARKS_PATH)
    if qbytes is None or wbytes is None: return None, f"configuration or watermarks committed at head {str(head)[:12]} could not be read from the object store"
    try: cfg = json.loads(qbytes.decode("utf-8")); marks = json.loads(wbytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e: return None, f"configuration or watermarks at head {str(head)[:12]} do not parse: {e}"
    if not isinstance(cfg, dict) or not isinstance(cfg.get("records"), list): return None, f"query configuration at head {str(head)[:12]} has no records list"
    wp = watermark_shape_problems(marks)
    if wp: return None, f"watermarks at head {str(head)[:12]}: " + "; ".join(wp[:3])
    _, why = policy_at_head(head, reader)
    if why: return None, why
    inputs, why = dispatch_inputs(run)
    if why: return None, why
    if inputs != ("", ""): return None, f"the run carried window inputs {inputs}; a manual cycle never satisfies a planned one"
    qsha_head = hashlib.sha256(qbytes).hexdigest()
    try: pl = plan(event, None, None, start_dt.date(), marks, qsha_head)
    except SystemExit as e: return None, str(e)
    return {**pl, "cfg": cfg, "qsha_at_head": qsha_head, "head_sha": head, "run_date": start_dt.date(), "run_started": start_dt}, None


def _iso(d): return d.isoformat()


def envelope_against_plan(env, pl):
    """Every declaration in the artefact that describes this plan must equal the trusted plan, with the JSON type the plan uses;
    the artefact never relabels the plan. Its head must be the run's head and its harvest start must fall inside the run."""
    p = []
    cyc = env.get("cycle") if isinstance(env.get("cycle"), dict) else {}
    if cyc.get("id") != pl["cycle_id"] or cyc.get("kind") != pl["kind"]: p.append(f"cycle {cyc.get('id')!r}/{cyc.get('kind')!r} is not the trusted {pl['cycle_id']!r}/{pl['kind']!r}")
    rw = env.get("requested_window") if isinstance(env.get("requested_window"), dict) else {}
    if (rw.get("from"), rw.get("to")) != (_iso(pl["from"]), _iso(pl["to"])): p.append(f"requested window {rw.get('from')} to {rw.get('to')} is not the trusted {pl['from']} to {pl['to']}")
    db = env.get("date_bases") if isinstance(env.get("date_bases"), dict) else {}
    pub = db.get("publication") if isinstance(db.get("publication"), dict) else {}
    if (pub.get("from"), pub.get("to")) != (_iso(pl["from"]), _iso(pl["to"])): p.append(f"publication date basis {pub.get('from')} to {pub.get('to')} is not the trusted {pl['from']} to {pl['to']}")
    fi = db.get("first_indexed") if isinstance(db.get("first_indexed"), dict) else {}
    if (fi.get("from"), fi.get("to")) != (_iso(pl["catch_from"]), _iso(pl["to"])): p.append(f"first-index catch-up {fi.get('from')} to {fi.get('to')} is not the trusted {pl['catch_from']} to {pl['to']}")
    fh = db.get("full_history")
    if not isinstance(fh, bool): p.append(f"full history {fh!r} is not a JSON boolean")
    elif fh != bool(pl["full_history"]): p.append(f"full history {fh} is not the trusted {pl['full_history']} for {pl['cycle_id']}")
    if env.get("query_sha256") != pl["qsha_at_head"]: p.append(f"query file hash {str(env.get('query_sha256'))[:12]} is not the configuration at the run's head {pl['qsha_at_head'][:12]}")
    if env.get("registry_commit") != pl["head_sha"]: p.append(f"artefact registry_commit {str(env.get('registry_commit'))[:12]} is not the run's head {pl['head_sha'][:12]}")
    try: hs = datetime.datetime.fromisoformat(str(env.get("started_at")).replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    except ValueError: hs = None
    if hs is None: p.append(f"artefact started_at {env.get('started_at')!r} is not a date-time")
    elif not (pl["run_started"] <= hs <= pl["run_started"] + HARVEST_START_BOUND): p.append(f"artefact started_at {env.get('started_at')} is outside the run's interval {pl['run_started'].isoformat()} to +{int(HARVEST_START_BOUND.total_seconds() // 3600)}h")
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


OUTCOMES = ("complete", "partial", "failed", "unavailable")
DESCRIPTOR_KEYS = ("instrument_id", "route", "source", "date_basis", "query", "unavailable")


def _count_ok(v, nullable=False):
    if v is None: return nullable
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def envelope_shape_problems(env):
    """Named shape problems with an artefact envelope, checked before any field is read, hashed, sorted or indexed."""
    if not isinstance(env, dict): return ["artefact root is not an object"]
    p = []
    if not isinstance(env.get("cycle"), dict): p.append("cycle is not an object")
    for k in ("expected_channels", "channels"):
        v = env.get(k)
        if not isinstance(v, list): p.append(f"{k} is not a list")
        elif not all(isinstance(x, dict) for x in v): p.append(f"{k} contains a non-object element")
    if env.get("channels_not_complete") is not None and not isinstance(env.get("channels_not_complete"), list): p.append("channels_not_complete is not a list")
    for k in ("requested_window", "date_bases"):
        if env.get(k) is not None and not isinstance(env.get(k), dict): p.append(f"{k} is not an object")
    if env.get("watermark_proposal") is not None and not isinstance(env.get("watermark_proposal"), dict): p.append("watermark_proposal is not an object")
    return p


def execution_problems(plan, channels):
    """The execution log against the authoritative plan: exactly one result per planned channel (missing, extra and duplicate ids
    refused, whichever order a duplicate arrives in); each result's descriptor equal to the plan's (instrument, route, source, date
    basis, exact query and the plan's unavailable policy or reason, in the producer's own nullable representation); a required channel
    complete with no error; a planned-unavailable channel reported unavailable with the plan's reason or no error; counts typed as the
    producer writes them (pages and collected_hits non-negative integers, reported_hits a non-negative integer or null, error a string
    or null, outcome one of the four). No collected-versus-reported equality is imposed: that needs provider-specific rules."""
    p = []
    if not isinstance(channels, list) or not all(isinstance(c, dict) for c in channels): return ["execution log is not a list of objects"]
    ids = [c.get("channel_id") for c in channels]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup: p.append(f"duplicate execution results for channel(s) {dup[:5]}; one result per planned channel")
    planned = {c["channel_id"]: c for c in plan}
    missing = sorted(set(planned) - set(ids)); extra = sorted(set(ids) - set(planned))
    if missing: p.append(f"{len(missing)} planned channel(s) have no execution result: {missing[:5]}")
    if extra: p.append(f"{len(extra)} execution result(s) for unplanned channel(s): {[str(x)[:40] for x in extra[:5]]}")
    for c in channels:
        cid = c.get("channel_id")
        if cid not in planned: continue
        e = planned[cid]
        diff = [k for k in DESCRIPTOR_KEYS if c.get(k) != e.get(k)]
        if diff: p.append(f"channel {cid}: the executed descriptor differs from the plan in {diff}"); continue
        out = c.get("outcome")
        if out not in OUTCOMES: p.append(f"channel {cid}: outcome {out!r} is not one of {OUTCOMES}"); continue
        err = c.get("error")
        if err is not None and not isinstance(err, str): p.append(f"channel {cid}: error is not a string or null"); continue
        if not _count_ok(c.get("pages")) or not _count_ok(c.get("collected_hits")) or not _count_ok(c.get("reported_hits"), nullable=True): p.append(f"channel {cid}: pages, collected_hits or reported_hits is not a non-negative integer (booleans are not counts)"); continue
        if e.get("unavailable"):
            if out != "unavailable": p.append(f"channel {cid}: the plan declares it unavailable ({e['unavailable']}) but the run reports {out!r}")
            elif err not in (None, e["unavailable"]): p.append(f"channel {cid}: unavailable with an error {err!r} that is not the plan's reason")
        else:
            if out != "complete": p.append(f"channel {cid}: required channel reported {out!r}")
            elif err: p.append(f"channel {cid}: reported complete yet carries error {err!r}")
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
        if env is None: reasons.append(f"run {rid}: artefact refused: {sha}"); continue          # (None, reason) from the download path
        shape = envelope_shape_problems(env)
        if shape: reasons.append(f"run {rid}: artefact shape: " + "; ".join(shape[:3])); continue
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
        ex = execution_problems(plan, env.get("channels", []))                   # what actually ran, bound to the plan, one result per channel
        if ex: reasons.append(f"run {rid}: execution log: " + "; ".join(ex[:3])); continue
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
    runs = json.loads(gh_json("run", "list", "--repo", repo, "--workflow", WORKFLOW, "--created", f">={since}", "--json", "databaseId,conclusion,event,headSha,startedAt,displayTitle", "--limit", "50"))
    runs = [{"github_run_id": str(r["databaseId"]), "conclusion": r["conclusion"], "event": r["event"], "head_sha": r.get("headSha"), "started_at": r.get("startedAt"), "display_title": r.get("displayTitle")} for r in runs]
    artefacts = {}
    for r in runs:
        if r["conclusion"] != "success": continue
        got = (download or _download_artefact)(r["github_run_id"], repo, cycle_id)
        if got: artefacts[r["github_run_id"]] = got            # (envelope, sha256), or (None, reason) which verify reports by name
    issues = json.loads(gh_json("issue", "list", "--repo", repo, "--label", "evidence-sweep", "--state", "all", "--search", f'"Evidence harvest {cycle_id}" in:title', "--json", "author,body"))
    issues = [{"author": ("app/" + i["author"]["login"]) if i["author"].get("is_bot") else i["author"]["login"], "body": i["body"]} for i in issues]
    return runs, artefacts, issues


def _no_dupes(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)): raise ValueError(f"duplicate object key {next(k for k in keys if keys.count(k) > 1)!r}")
    return dict(pairs)


def _no_nonfinite(name): raise ValueError(f"non-finite number {name}")


def parse_artefact_dir(d):
    """The downloaded artefact directory: exactly one JSON file (an ambiguous directory is refused, never resolved by picking the first),
    strict JSON (duplicate keys at any depth, NaN and Infinity refused) whose root is an object. Returns (envelope, sha256) or (None, reason)."""
    files = sorted(Path(d).glob("*.json"))
    if not files: return None, "no JSON file in the downloaded artefact"
    if len(files) > 1: return None, f"ambiguous artefact: {len(files)} JSON files downloaded ({[f.name for f in files][:4]}); none is chosen"
    raw = files[0].read_bytes()
    try: env = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes, parse_constant=_no_nonfinite)
    except (UnicodeDecodeError, ValueError) as e: return None, f"artefact {files[0].name} is not strict JSON: {str(e)[:100]}"
    if not isinstance(env, dict): return None, f"artefact {files[0].name} root is not an object"
    return env, hashlib.sha256(raw).hexdigest()


def _download_artefact(run_id, repo, cycle_id):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / run_id
        p = subprocess.run(["gh", "run", "download", run_id, "--repo", repo, "-n", f"candidates-{cycle_id}", "-D", str(d)], capture_output=True, text=True)
        if p.returncode != 0: return None, f"gh run download failed: {p.stderr.strip()[:120]}"
        if not d.exists(): return None, "gh run download produced no directory"
        return parse_artefact_dir(d)


def verify_live_detail(cycle_id, repo, gh_json=None, download=None, cfg=None, qsha=None, reader=read_at_head, lister=tree_at_head):
    """The live wrapper: fetch, derive each run's trusted plan from its head commit (watermarks, query configuration and policy
    version as committed there), start date, event and recorded inputs, then judge every artefact against that plan. Nothing in
    the artefact and nothing in the ambient environment (a key present or absent) changes the plan; a run whose provenance is
    unreadable is unverified. Returns (accepted run id or None, reasons, the accepted artefact (envelope, sha256) or None, its
    trusted plan or None), so a caller that writes can use exactly the context that verified."""
    runs, artefacts, issues = fetch_live(cycle_id, repo, gh_json, download)
    trusted = {r["github_run_id"]: trusted_plan(r, reader, lister) for r in runs}
    rid, why = verify(cycle_id, qsha or query_sha(), None, runs, artefacts, issues, cfg=cfg, trusted=trusted)
    return rid, why, (artefacts.get(rid) if rid else None), (trusted[rid][0] if rid else None)


def verify_live(cycle_id, repo, gh_json=None, download=None, cfg=None, qsha=None, reader=read_at_head, lister=tree_at_head):
    rid, why, _, _ = verify_live_detail(cycle_id, repo, gh_json, download, cfg, qsha, reader, lister)
    return rid, why


def advance_problems(env, tp, queries_path=None, artefact_sha=None, expected_sha=None):
    """Why an accepted artefact cannot advance the watermark, given the trusted plan `tp` of the run that produced it (never derived
    from the envelope). The current query configuration must exist and be the configuration the run used; the proposal must be bound
    to the plan and the run; a file supplied by hand must be byte-identical to the artefact downloaded from the run."""
    p = []
    if tp is None: return ["no trusted run context: the cycle was not verified, so nothing is advanced"]
    if expected_sha is not None and artefact_sha != expected_sha: p.append(f"the supplied file ({str(artefact_sha)[:12]}) is not the artefact downloaded from the accepted run ({str(expected_sha)[:12]})")
    prop = env.get("watermark_proposal")
    if not isinstance(prop, dict): return p + ["no watermark proposal: the run was not a complete full-inventory planned run"]
    if env.get("status") != "complete": p.append(f"envelope status is {env.get('status')!r}, not complete")
    if env.get("full_inventory") is not True: p.append("envelope is not a full-inventory run")
    if env.get("channels_not_complete"): p.append(f"{len(env['channels_not_complete'])} expected channels not complete")
    qpath = Path(queries_path) if queries_path else QUERIES
    if not qpath.exists(): p.append("the query configuration is missing; cannot advance without it")
    elif query_sha(qpath) != tp["qsha_at_head"]: p.append(f"the current configuration {query_sha(qpath)[:12]} is not the configuration the run used {tp['qsha_at_head'][:12]}; a watermark belongs to the configuration that produced it")
    shape = envelope_shape_problems(env)
    if shape: return p + ["artefact shape: " + "; ".join(shape[:3])]
    mism = envelope_against_plan(env, tp)
    if mism: p.append("the artefact departs from the trusted plan: " + mism[0])
    plan_ch = expected_channels(tp["cfg"], _iso(tp["from"]), _iso(tp["to"]), _iso(tp["catch_from"]), tp["full_history"])
    pol = policy_problems(plan_ch, env.get("expected_channels") or [])
    if pol: p.append("the artefact's expected set differs from the trusted plan: " + pol[0])
    ex = execution_problems(plan_ch, env.get("channels", []))
    if ex: p.append("execution log: " + ex[0])
    binds = {"query_sha256": tp["qsha_at_head"], "cycle_id": tp["cycle_id"], "run_id": env.get("run_id"), "last_complete_to": _iso(tp["to"]), "catch_from": _iso(tp["catch_from"])}
    for k, want in binds.items():
        if prop.get(k) != want: p.append(f"proposal {k} {prop.get(k)!r} is not the trusted {want!r}")
    complete = sum(1 for c in env.get("channels", []) if isinstance(c, dict) and c.get("outcome") == "complete")
    if prop.get("channels_complete") != complete: p.append(f"proposal channels_complete {prop.get('channels_complete')!r} is not the {complete} complete channels in the artefact")
    try: datetime.date.fromisoformat(str(prop.get("last_complete_to")))
    except ValueError: p.append("proposal last_complete_to is not a valid date")
    return p


def advance_with(env, tp, path=WATERMARKS, queries_path=None, artefact_sha=None, expected_sha=None, github_run_id=None, artefact_sha256=None):
    """Write the accepted run's proposal into the watermark file. Refuses before writing on any problem; never moves backwards. The
    entry records the harvester's own run_id (from the proposal) and, separately, the GitHub run id and artefact SHA-256 returned by
    acquisition; the two identifiers are never conflated."""
    problems = advance_problems(env, tp, queries_path, artefact_sha, expected_sha)
    if problems: raise SystemExit("this artefact cannot advance the watermark: " + "; ".join(problems))
    prop = env["watermark_proposal"]
    marks = load_watermarks(path)
    cur = marks["entries"].get(prop["query_sha256"])
    if cur and cur["last_complete_to"] >= prop["last_complete_to"]: raise SystemExit(f"watermark already at {cur['last_complete_to']}; nothing to advance")
    marks["entries"][prop["query_sha256"]] = {k: v for k, v in prop.items() if k != "note"} | {"advanced_on": datetime.date.today().isoformat(), "date_bases": env.get("date_bases"), "run_head": tp["head_sha"], "policy_version": POLICY_VERSION,
                                                                                               "github_run_id": github_run_id, "artefact_sha256": artefact_sha256}
    Path(path).write_text(json.dumps(marks, indent=2) + "\n", encoding="utf-8")
    print(f"watermark for query {prop['query_sha256'][:12]} advanced to {prop['last_complete_to']} (cycle {prop['cycle_id']}, harvester run {prop['run_id']}, GitHub run {github_run_id}, artefact {str(artefact_sha256)[:12]}, head {tp['head_sha'][:12]}); commit this in the screening pull request")


def advance(cycle_id, repo, artefact_path=None, path=WATERMARKS, gh_json=None, download=None, reader=read_at_head, lister=tree_at_head, queries_path=None):
    """The production write: verify the cycle exactly as the tripwire does, then advance from the artefact downloaded from the
    accepted run under that run's trusted plan. A file given with --artefact is checked against those bytes; it is never the authority."""
    qpath = Path(queries_path) if queries_path else QUERIES
    if not qpath.exists(): raise SystemExit("the query configuration is missing; cannot advance without it")
    rid, why, art, tp = verify_live_detail(cycle_id, repo, gh_json, download, qsha=query_sha(qpath), reader=reader, lister=lister)
    if not rid or art is None: raise SystemExit("cycle not verified; nothing advanced:\n  " + "\n  ".join(why[:10]))
    env, sha = art
    supplied = hashlib.sha256(Path(artefact_path).read_bytes()).hexdigest() if artefact_path else None
    advance_with(env, tp, path, queries_path, artefact_sha=supplied, expected_sha=(sha if artefact_path else None), github_run_id=rid, artefact_sha256=sha)


# ---------- offline suite ----------

def self_test():
    failures = 0
    def res(c, outcome=None):
        """An execution result as the producer writes it: descriptor plus pages, hit counts, outcome and error."""
        out = outcome or ("unavailable" if c["unavailable"] else "complete")
        return {**c, "pages": 0 if out == "unavailable" else 1, "reported_hits": None if out == "unavailable" else 0, "collected_hits": 0, "outcome": out, "error": (c["unavailable"] or None) if out == "unavailable" else None}
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
    ran_minus_one = [res(c) for c in exp if c["channel_id"] != alias[1]["channel_id"]]
    t("dropping one alias channel while its sibling completes is visible in the denominator", [m["channel_id"] for m in channels_not_complete(exp, ran_minus_one)] == [alias[1]["channel_id"]])
    full_run = [res(c) for c in exp]
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
    t("one missing alias channel (sibling complete) is refused against the full denominator", rid is None and ("not complete" in why[0] or "no execution result" in why[0]), why)
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
    # trusted run context: a real temporary Git repository holds what the run's head committed (configuration, watermarks and the
    # policy files), so the plan is read from the object store exactly as in production; stubs are used only to inject malformed bytes
    import functools, shutil
    CFG_BYTES = json.dumps(cfg).encode(); QH = hashlib.sha256(CFG_BYTES).hexdigest()
    MARKS_AT_HEAD = {"schema_version": "1.0", "overlap_days": 14, "entries": {}}
    HARVEST_SRC = (Path(__file__).resolve().parent / "harvest.py").read_bytes(); CYCLE_SRC = Path(__file__).resolve().read_bytes()
    fixture_root = Path(tempfile.mkdtemp(prefix="owhs-cycle-fixture-"))
    def git_(repo, *a): return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()
    repo = fixture_root / "repo"; (repo / "evidence" / "queries").mkdir(parents=True); (repo / "tools").mkdir()
    (repo / QUERIES_PATH).write_bytes(CFG_BYTES); (repo / WATERMARKS_PATH).write_text(json.dumps(MARKS_AT_HEAD)); (repo / "tools" / "harvest.py").write_bytes(HARVEST_SRC); (repo / "tools" / "cycle.py").write_bytes(CYCLE_SRC)
    git_(repo, "init", "-q"); git_(repo, "add", "-A"); git_(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "run head")
    HEAD = git_(repo, "rev-parse", "HEAD")
    (repo / "later.txt").write_text("a later commit\n"); git_(repo, "add", "later.txt"); git_(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "later head")
    HEAD2 = git_(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(fixture_root / "shallow")], check=True, capture_output=True)
    subprocess.run(["git", "clone", "-q", repo.as_uri(), str(fixture_root / "full")], check=True, capture_output=True)
    real_reader, real_lister = functools.partial(read_at_head, root=repo), functools.partial(tree_at_head, root=repo)
    FILES = {QUERIES_PATH: CFG_BYTES, WATERMARKS_PATH: json.dumps(MARKS_AT_HEAD).encode(), "tools/harvest.py": HARVEST_SRC, "tools/cycle.py": CYCLE_SRC}
    def stubs(files=None, tree=None, head=HEAD):
        files = FILES if files is None else files; tree = set(files) if tree is None else tree
        return (lambda h, path: files.get(path) if h == head else None), (lambda h: set(tree) if h == head else None)
    # 1 October 2026 is a quarterly month: the trusted plan is 1 September to 1 October, catch-up from 3 July, full history on
    plan_live = expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", True)
    full_live = [res(c) for c in plan_live]
    RUN_NAME = "evidence-harvest schedule from=[] to=[]"
    runs_json = [{"databaseId": 100, "conclusion": "success", "event": "schedule", "headSha": HEAD, "startedAt": "2026-10-01T06:00:12Z", "displayTitle": RUN_NAME}]
    def env_trusted(expected, channels, **kw):
        e = env_live(expected, channels, q=QH, date_bases={"publication": {"from": "2026-09-01", "to": "2026-10-01"}, "first_indexed": {"from": "2026-07-03", "to": "2026-10-01"}, "full_history": True},
                     registry_commit=HEAD, started_at="2026-10-01T06:02:40+00:00")
        e.update(kw); e["channels_not_complete"] = channels_not_complete(e["expected_channels"], e["channels"]); return e
    def live_with(envelope, runs=runs_json, reader=None, lister=None, cycle="2026-10", run_id="100"):
        sha_ = hashlib.sha256(json.dumps(envelope).encode()).hexdigest()
        issues = [{"author": {"login": "github-actions", "is_bot": True}, "body": f"<!-- owhs-cycle cycle_id={cycle} kind=planned github_run_id={run_id} artefact_sha256={sha_} -->"}]
        try: return verify_live(cycle, "example/repo", gh_json=stub_gh_factory(runs, issues), download=lambda rid_, repo_, cyc: (envelope, sha_), cfg=cfg, qsha=QH, reader=reader or real_reader, lister=lister or real_lister)
        except Exception as ex: return None, [f"EXCEPTION {type(ex).__name__}: {ex}"]
    rid, why = live_with(env_trusted(plan_live, full_live)); t("live wrapper: an artefact matching the trusted plan read from the run's head in a real repository passes", rid == "100", why)
    # five counterexamples: each departs from the trusted plan in one declaration and is refused
    nofh = env_trusted(expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", False), [res(c) for c in expected_channels(cfg, "2026-09-01", "2026-10-01", "2026-07-03", False)])
    nofh["date_bases"]["full_history"] = False
    rid, why = live_with(nofh); t("trusted plan: an October artefact with full history disabled is refused", rid is None and "full history" in why[0], why)
    nocatch = env_trusted(expected_channels(cfg, "2026-09-01", "2026-10-01", None, True), [res(c) for c in expected_channels(cfg, "2026-09-01", "2026-10-01", None, True)])
    nocatch["date_bases"]["first_indexed"] = None
    rid, why = live_with(nocatch); t("trusted plan: an artefact omitting the first-index catch-up is refused", rid is None and "first-index catch-up" in why[0], why)
    narrow = env_trusted(plan_live, full_live, requested_window={"from": "2026-09-30", "to": "2026-10-01"}); narrow["date_bases"]["publication"] = {"from": "2026-09-30", "to": "2026-10-01"}
    rid, why = live_with(narrow); t("trusted plan: a publication window narrowed to two days is refused even with the same channel count", rid is None and "requested window" in why[0], why)
    old = env_trusted(plan_live, full_live, requested_window={"from": "2020-09-01", "to": "2020-10-01"}); old["date_bases"] = {"publication": {"from": "2020-09-01", "to": "2020-10-01"}, "first_indexed": {"from": "2020-07-03", "to": "2020-10-01"}, "full_history": True}
    rid, why = live_with(old); t("trusted plan: a 2020 window labelled cycle 2026-10 is refused", rid is None and "requested window" in why[0], why)
    # every declaration is bound and typed
    pubonly = env_trusted(plan_live, full_live); pubonly["date_bases"]["publication"] = {"from": "2020-09-01", "to": "2020-10-01"}
    rid, why = live_with(pubonly); t("binding: only the publication date basis moved to 2020 is refused", rid is None and "publication date basis" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live, registry_commit="f" * 40)); t("binding: an artefact whose registry_commit is not the run's head is refused", rid is None and "registry_commit" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live, started_at="2020-10-01T06:00:12Z")); t("binding: an artefact whose start time is in 2020 is refused", rid is None and "outside the run's interval" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live, started_at="2026-10-01T13:00:00Z")); t("binding: a harvest start seven hours after the run started is outside the interval and refused", rid is None and "outside the run's interval" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live, started_at="2026-10-01T06:20:00Z")); t("binding: a harvest step starting twenty minutes after the run is a plausible later start and passes", rid == "100", why)
    rid, why = live_with(env_trusted(plan_live, full_live, started_at="not a time")); t("binding: a malformed artefact start time is refused by name", rid is None and "not a date-time" in why[0], why)
    strfh = env_trusted(plan_live, full_live); strfh["date_bases"]["full_history"] = "false"
    rid, why = live_with(strfh); t("binding: full_history as the string false is refused as not a JSON boolean", rid is None and "not a JSON boolean" in why[0], why)
    # missing or malformed historical inputs are reasons, never defaults; a shallow checkout cannot read the head
    def run_with(**kw): return [{**runs_json[0], **kw}]
    rid, why = live_with(env_trusted(plan_live, full_live), reader=functools.partial(read_at_head, root=fixture_root / "shallow"), lister=functools.partial(tree_at_head, root=fixture_root / "shallow"))
    t("checkout: a valid earlier run is unverified in a depth-one clone of a later commit, with the reason", rid is None and "not readable in this checkout" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live), reader=functools.partial(read_at_head, root=fixture_root / "full"), lister=functools.partial(tree_at_head, root=fixture_root / "full"))
    t("checkout: the same run is accepted from a full-history clone at the descendant commit", rid == "100", why)
    rid, why = live_with(env_trusted(plan_live, full_live, registry_commit="f" * 40), runs=run_with(headSha="f" * 40)); t("checkout: an unknown head is unverified", rid is None and "not readable in this checkout" in why[0], why)
    r_, l_ = stubs(files={k: v for k, v in FILES.items() if k != WATERMARKS_PATH})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("inputs: watermarks not committed at the head is a reason, not a default", rid is None and "not committed at head" in why[0] and "no default" in why[0], why)
    r_, l_ = stubs(files={k: v for k, v in FILES.items() if k != WATERMARKS_PATH}, tree=set(FILES))
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("inputs: watermarks committed but unreadable from the object store is a reason", rid is None and "could not be read" in why[0], why)
    r_, l_ = stubs(files={**FILES, WATERMARKS_PATH: b"[]"})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("inputs: a watermark document whose root is a list is refused by name, no traceback", rid is None and "root is not an object" in why[0], why)
    r_, l_ = stubs(files={**FILES, WATERMARKS_PATH: json.dumps({"overlap_days": "x", "entries": {"nothex": {"last_complete_to": "yesterday"}}}).encode()})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("inputs: malformed overlap, entry key and date are named", rid is None and "overlap_days" in why[0] and "query hash" in why[0] and "valid last_complete_to" in why[0], why)
    r_, l_ = stubs(files={**FILES, WATERMARKS_PATH: b"{not json"})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("inputs: watermarks that do not parse are a reason", rid is None and "do not parse" in why[0], why)
    r_, l_ = stubs(files={k: v for k, v in FILES.items() if k != QUERIES_PATH})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("inputs: configuration not committed at the head is a reason", rid is None and "not committed at head" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live), runs=[{"databaseId": 100, "conclusion": "success", "event": "schedule"}]); t("inputs: a run listed without head or start time is unverified", rid is None and "lacks head" in why[0], why)
    # the planning policy is bound to the run's head
    OLD_POLICY = {"tools/harvest.py": HARVEST_SRC.replace(b'POLICY_VERSION = "2026.09-1"', b'POLICY_VERSION = "2025.01-0"'), "tools/cycle.py": CYCLE_SRC.replace(b'POLICY_VERSION = "2026.09-1"', b'POLICY_VERSION = "2025.01-0"')}
    r_, l_ = stubs(files={**FILES, **OLD_POLICY})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("policy: a head whose policy files record another policy version is unverified as an unsupported historical policy", rid is None and "unsupported historical policy" in why[0], why)
    r_, l_ = stubs(files={**FILES, "tools/harvest.py": OLD_POLICY["tools/harvest.py"]})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("policy: policy files that disagree at the head are unverified by name", rid is None and "policy versions disagree" in why[0], why)
    r_, l_ = stubs(files={**FILES, "tools/harvest.py": HARVEST_SRC.replace(b'POLICY_VERSION = "2026.09-1"', b'')})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("policy: a head whose harvest.py records no policy version is unverified", rid is None and "records no policy version" in why[0], why)
    # dispatch provenance comes from GitHub's run name, never from the artefact
    rerun = [{"databaseId": 101, "conclusion": "success", "event": "workflow_dispatch", "headSha": HEAD, "startedAt": "2026-10-02T09:30:00Z", "displayTitle": "evidence-harvest workflow_dispatch from=[] to=[]"}]
    pl2 = expected_channels(cfg, "2026-09-01", "2026-10-02", "2026-07-04", True); fl2 = [res(c) for c in pl2]
    e2 = env_trusted(pl2, fl2, requested_window={"from": "2026-09-01", "to": "2026-10-02"}, started_at="2026-10-02T09:33:00Z"); e2["date_bases"] = {"publication": {"from": "2026-09-01", "to": "2026-10-02"}, "first_indexed": {"from": "2026-07-04", "to": "2026-10-02"}, "full_history": True}
    rid, why = live_with(e2, runs=rerun, run_id="101"); t("dispatch: a later planned re-run whose run name records empty inputs passes with its own run-date window", rid == "101", why)
    rid, why = live_with(e2, runs=[{**rerun[0], "displayTitle": "evidence-harvest workflow_dispatch from=[2026-09-01] to=[2026-10-02]"}], run_id="101"); t("dispatch: a run whose recorded inputs carry a window is a manual cycle and never satisfies the planned one, whatever the artefact says", rid is None and "carried window inputs" in why[0], why)
    rid, why = live_with(e2, runs=[{k: v for k, v in rerun[0].items() if k != "displayTitle"}], run_id="101"); t("dispatch: a run without the recording run name is unverified, not assumed planned", rid is None and "does not record the dispatch inputs" in why[0], why)
    rid, why = live_with(env_trusted(plan_live, full_live), runs=run_with(displayTitle="evidence-harvest workflow_dispatch from=[] to=[]")); t("dispatch: a run name naming another trigger than the run's event is unverified", rid is None and "run event" in why[0], why)
    # a previously advanced watermark at the run's head moves the trusted window start (15 September minus 14 days = 1 September)
    r_, l_ = stubs(files={**FILES, WATERMARKS_PATH: json.dumps({"overlap_days": 14, "entries": {QH: {"last_complete_to": "2026-09-15"}}}).encode()})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("trusted plan: a previously advanced watermark at the run's head is honoured (window from 1 September)", rid == "100", why)
    r_, l_ = stubs(files={**FILES, WATERMARKS_PATH: json.dumps({"overlap_days": 14, "entries": {QH: {"last_complete_to": "2026-09-20"}}}).encode()})
    rid, why = live_with(env_trusted(plan_live, full_live), reader=r_, lister=l_); t("trusted plan: an artefact whose window start ignores the head's watermark (6 September expected) is refused", rid is None and "requested window" in why[0], why)
    one = env_trusted([plan_live[0]], [full_live[0]]); rid, why = live_with(one)
    t("live wrapper: a one-channel self-declared manifest fails against the trusted plan", rid is None and "required by the plan are absent" in why[0], why)
    exempt = [dict(c) for c in plan_live]; req = next(c for c in exempt if not c["unavailable"]); req["unavailable"] = "synthetic exemption not in the plan"
    chans = [res(c) for c in exempt]
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
    # the execution log is bound to the plan: what ran, not only what was declared
    def exec_case(label, change, needle):
        e = env_trusted(copy.deepcopy(plan_live), copy.deepcopy(full_live)); change(e); rid_, why_ = live_with(e)
        t(f"execution log: {label} is refused", rid_ is None and needle in why_[0], why_)
    exec_case("a result whose query differs from the plan", lambda e: e["channels"][0].update(query="unrelated query"), "executed descriptor differs")
    exec_case("a result whose provider differs from the plan", lambda e: e["channels"][0].update(source="unrelated-provider"), "executed descriptor differs")
    exec_case("a result whose date basis differs from the plan", lambda e: e["channels"][0].update(date_basis="unrelated-date-basis"), "executed descriptor differs")
    exec_case("a failed duplicate inserted before the complete result", lambda e: e["channels"].insert(0, {**e["channels"][0], "outcome": "failed"}), "duplicate execution results")
    exec_case("a complete duplicate inserted after a failed result", lambda e: (e["channels"].append({**e["channels"][0]}), e["channels"][0].update(outcome="failed")), "duplicate execution results")
    exec_case("a complete result carrying an error", lambda e: e["channels"][0].update(error="http 503"), "carries error")
    exec_case("a result for an unplanned channel", lambda e: e["channels"].append({**e["channels"][0], "channel_id": "unplanned"}), "unplanned channel")
    exec_case("a planned-unavailable channel reported complete", lambda e: next(c for c in e["channels"] if c["outcome"] == "unavailable").update(outcome="complete", error=None, reported_hits=0, pages=1), "plan declares it unavailable")
    exec_case("a boolean page count", lambda e: e["channels"][0].update(pages=True), "booleans are not counts")
    exec_case("a negative hit count", lambda e: e["channels"][0].update(collected_hits=-1), "non-negative integer")
    exec_case("an outcome outside the producer's vocabulary", lambda e: e["channels"][0].update(outcome="done"), "not one of")
    exec_case("a missing result for a planned channel", lambda e: e["channels"].pop(0), "no execution result")
    for label, change, needle in (("a null execution result", lambda e: e["channels"].__setitem__(0, None), "non-object"), ("a null declared channel", lambda e: e["expected_channels"].__setitem__(0, None), "non-object"), ("a cycle that is an array", lambda e: e.update(cycle=["not-an-object"]), "cycle is not an object")):
        e = env_trusted(copy.deepcopy(plan_live), copy.deepcopy(full_live)); change(e)          # mutated after construction on private copies: the checker, not the fixture helper, must cope
        rid_, why_ = live_with(e)
        t(f"artefact shape: {label} is refused by name, no exception", rid_ is None and "artefact shape" in why_[0] and needle in why_[0], why_)
    # the download path: strict JSON, one file, an object root
    with tempfile.TemporaryDirectory() as dtmp:
        dd = Path(dtmp)
        (dd / "a.json").write_text('{"cycle": {"id": "x"}, "cycle": {"id": "y"}}', encoding="utf-8"); env_, why_ = parse_artefact_dir(dd); t("download: duplicate JSON keys are refused", env_ is None and "duplicate object key" in why_, why_)
        (dd / "a.json").write_text('{not json', encoding="utf-8"); env_, why_ = parse_artefact_dir(dd); t("download: invalid JSON is refused by name", env_ is None and "not strict JSON" in why_, why_)
        (dd / "a.json").write_text('[1, 2]', encoding="utf-8"); env_, why_ = parse_artefact_dir(dd); t("download: a non-object root is refused", env_ is None and "not an object" in why_, why_)
        (dd / "a.json").write_text('{"x": NaN}', encoding="utf-8"); env_, why_ = parse_artefact_dir(dd); t("download: NaN is refused", env_ is None and "non-finite" in why_, why_)
        (dd / "a.json").write_text('{"ok": 1}', encoding="utf-8"); (dd / "b.json").write_text('{"ok": 2}', encoding="utf-8"); env_, why_ = parse_artefact_dir(dd); t("download: two JSON files are ambiguous and neither is chosen", env_ is None and "ambiguous" in why_, why_)
        (dd / "b.json").unlink(); env_, sha_ = parse_artefact_dir(dd); t("download: one strict object file is returned with its byte hash", env_ == {"ok": 1} and sha_ == hashlib.sha256(b'{"ok": 1}').hexdigest())
    rid, why = live_with(env_trusted(plan_live, full_live), runs=runs_json) if False else (None, None)
    refused_dl = verify("2026-10", QH, None, [{"github_run_id": "100", "conclusion": "success", "event": "schedule"}], {"100": (None, "artefact a.json is not strict JSON: duplicate object key 'cycle'")}, [], trusted={"100": (None, "x")})
    t("verify reports a refused artefact by its reason and never touches the watermark", refused_dl[0] is None and "artefact refused" in refused_dl[1][0], refused_dl[1])
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
    # watermark advance: authority is the verified run's trusted plan and the artefact bytes downloaded from it, never a file alone
    import io, contextlib
    with tempfile.TemporaryDirectory() as tmp:
        wm = Path(tmp) / "w.json"; qfile = Path(tmp) / "instruments-v1.json"; qfile.write_bytes(CFG_BYTES)
        tp, why_tp = trusted_plan({"head_sha": HEAD, "started_at": "2026-10-01T06:00:12Z", "event": "schedule", "display_title": RUN_NAME}, real_reader, real_lister)
        t("advance: a trusted plan derives from the fixture run", tp is not None, why_tp)
        prop = {"query_sha256": QH, "last_complete_to": "2026-10-01", "catch_from": "2026-07-03", "cycle_id": "2026-10", "run_id": "r1", "channels_complete": sum(1 for c in full_live if c["outcome"] == "complete")}
        def env_adv(**kw):
            e = env_trusted(copy.deepcopy(plan_live), copy.deepcopy(full_live)); e["watermark_proposal"] = dict(prop); e.update(kw); e["channels_not_complete"] = channels_not_complete(e["expected_channels"], e["channels"]); return e
        def refused(label, e, needle, tp_=tp, **kw):
            try: advance_with(e, tp_, wm, qfile, **kw); t(label, False, "written")
            except SystemExit as ex: t(label, needle in str(ex), str(ex)[:200])
        refused("advance: no trusted run context refuses before anything is written", env_adv(), "no trusted run context", tp_=None)
        refused("advance: a failed envelope carrying a populated proposal is refused", env_adv(status="failed", full_inventory=False, channels=[]), "not complete")
        refused("advance: a partial envelope is refused", env_adv(status="partial"), "partial")
        refused("advance: an envelope missing one expected channel is refused", env_adv(channels=[c for c in full_live if c["channel_id"] != plan_live[0]["channel_id"]]), "not complete")
        refused("advance: a proposal whose catch-up date is not the plan's is refused", env_adv(watermark_proposal=dict(prop, catch_from="2026-07-04")), "catch_from")
        refused("advance: a proposal whose end is not the plan's is refused", env_adv(watermark_proposal=dict(prop, last_complete_to="2040-01-01")), "last_complete_to")
        refused("advance: a proposal whose channel count is not the artefact's is refused", env_adv(watermark_proposal=dict(prop, channels_complete=1)), "channels_complete")
        refused("advance: a proposal whose query hash is not the run's configuration is refused", env_adv(watermark_proposal=dict(prop, query_sha256="y" * 64)), "query_sha256")
        narrow_adv = env_adv(requested_window={"from": "2026-09-30", "to": "2026-10-01"}); narrow_adv["date_bases"]["publication"] = {"from": "2026-09-30", "to": "2026-10-01"}
        refused("advance: an artefact departing from the trusted plan is refused", narrow_adv, "trusted plan")
        refused("advance: a supplied file whose bytes are not the downloaded artefact's is refused", env_adv(), "not the artefact downloaded", artefact_sha="a" * 64, expected_sha="b" * 64)
        try: advance_with(env_adv(), tp, wm, Path(tmp) / "absent.json"); t("advance: missing current configuration is refused (fail closed)", False)
        except SystemExit as ex: t("advance: missing current configuration is refused (fail closed)", "missing" in str(ex))
        t("advance: nothing was written by any refusal", not wm.exists())
        with contextlib.redirect_stdout(io.StringIO()): advance_with(env_adv(), tp, wm, qfile)
        entry = json.loads(wm.read_text())["entries"][QH]
        t("advance: the legitimate forward advance writes the proposal with the run head and policy version", entry["last_complete_to"] == "2026-10-01" and entry["run_head"] == HEAD and entry["policy_version"] == POLICY_VERSION, entry)
        try: advance_with(env_adv(), tp, wm, qfile); t("re-advance refused", False)
        except SystemExit: t("advance: an advance that does not move forward is refused", True)
        # the production write path: verification through the same acquisition as the tripwire, then the write
        good_env = env_adv(); good_sha = hashlib.sha256(json.dumps(good_env).encode()).hexdigest()
        issues_ok = [{"author": {"login": "github-actions", "is_bot": True}, "body": f"<!-- owhs-cycle cycle_id=2026-10 kind=planned github_run_id=100 artefact_sha256={good_sha} -->"}]
        wm2 = Path(tmp) / "w2.json"
        with contextlib.redirect_stdout(io.StringIO()):
            advance("2026-10", "example/repo", None, wm2, gh_json=stub_gh_factory(runs_json, issues_ok), download=lambda rid_, repo_, cyc: (good_env, good_sha), reader=real_reader, lister=real_lister, queries_path=qfile)
        ent2 = json.loads(wm2.read_text())["entries"][QH]
        t("production advance: a verified cycle advances from the downloaded artefact under the run's plan, recording the GitHub run id and artefact hash separately from the harvester's run id", ent2["run_head"] == HEAD and ent2["github_run_id"] == "100" and ent2["artefact_sha256"] == good_sha and ent2["run_id"] == "r1", ent2)
        for label, change in (("a result whose query differs from the plan", lambda e: e["channels"][0].update(query="unrelated query")), ("a failed duplicate result", lambda e: e["channels"].insert(0, {**e["channels"][0], "outcome": "failed"})), ("a null execution result", lambda e: e["channels"].__setitem__(0, None))):
            bad_env = env_adv(); change(bad_env); bad_sha = hashlib.sha256(json.dumps(bad_env).encode()).hexdigest()      # mutated after construction
            issues_bad = [{"author": {"login": "github-actions", "is_bot": True}, "body": f"<!-- owhs-cycle cycle_id=2026-10 kind=planned github_run_id=100 artefact_sha256={bad_sha} -->"}]
            wmx = Path(tmp) / f"wx-{label[:8].replace(' ', '')}.json"
            try:
                advance("2026-10", "example/repo", None, wmx, gh_json=stub_gh_factory(runs_json, issues_bad), download=lambda rid_, repo_, cyc: (bad_env, bad_sha), reader=real_reader, lister=real_lister, queries_path=qfile); t(f"production advance: {label} with a matching issue and artefact refuses", False, "written")
            except SystemExit as ex: t(f"production advance: {label} with a matching issue and artefact refuses and writes nothing", "cycle not verified" in str(ex) and not wmx.exists(), str(ex)[:160])
        wm3 = Path(tmp) / "w3.json"
        try:
            advance("2026-10", "example/repo", None, wm3, gh_json=stub_gh_factory([], []), download=lambda *a: None, reader=real_reader, lister=real_lister, queries_path=qfile); t("production advance: an unverifiable cycle refuses", False)
        except SystemExit as ex: t("production advance: an unverifiable cycle refuses before writing, with the reasons", "cycle not verified" in str(ex) and not wm3.exists())
        supplied = Path(tmp) / "supplied.json"; supplied.write_text(json.dumps(env_adv(started_at="2026-10-01T06:02:41+00:00")))
        try:
            advance("2026-10", "example/repo", supplied, wm3, gh_json=stub_gh_factory(runs_json, issues_ok), download=lambda rid_, repo_, cyc: (good_env, good_sha), reader=real_reader, lister=real_lister, queries_path=qfile); t("production advance: a supplied file that differs from the downloaded artefact refuses", False)
        except SystemExit as ex: t("production advance: a supplied file that differs from the downloaded artefact refuses", "not the artefact downloaded" in str(ex) and not wm3.exists())
        # the real command line: a fabricated, internally consistent envelope with no --cycle cannot write anything
        fab = Path(tmp) / "fabricated.json"; fab.write_text(json.dumps(env_adv()))
        r = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "advance", "--artefact", str(fab)], capture_output=True, text=True, cwd=tmp)
        t("command line: advance with only --artefact exits nonzero and names the missing trusted context", r.returncode != 0 and "--cycle" in (r.stderr + r.stdout) and "Traceback" not in r.stderr, (r.returncode, r.stderr[-200:]))
    shutil.rmtree(fixture_root, ignore_errors=True)
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
        opts = dict(zip(a[1::2], a[2::2])); repo = opts.get("--repo") or os.environ.get("GITHUB_REPOSITORY") or "openworkplacehealth/OWHS"
        if "--cycle" not in opts: sys.exit("advance needs --cycle (and --repo): the watermark moves only from a verified run's artefact, never from a file alone")
        return advance(opts["--cycle"], repo, opts.get("--artefact"))
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
