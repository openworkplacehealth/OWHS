#!/usr/bin/env python3
"""Held-out known-item retrieval evaluation for the evidence harvester: correct accounting first, a number second.

    python tools/measure_recall.py --self-test
    python tools/measure_recall.py --manifest M --split S --coverage C --queries Q --candidates CAND --query-lock LOCK \
                                   [--execution-record REC] --out REPORT
    python tools/measure_recall.py --write-fixtures DIR        (maintainers: regenerate the synthetic public fixtures)

Two quantities, kept apart. Coverage: which judged works the configured indexes contain (a lookup with identifiers supplied; never
discovery). Known-item retrieval: which judged-relevant holdout works the frozen discovery queries returned without being given
their identifiers. Let E be the eligible holdout works known to be inside the requested window (non-seed, non-calibration, not
previously exposed to tuning, with at least one eligible in-scope link); F the subset a discovery route returned; C the subset of E
demonstrated indexed by at least one enabled source at the coverage check. The report gives |F|/|E| with every miss listed,
|F and C|/|C| with failed and unknown coverage counted separately, work-level micro recall and macro recall over instruments with
a non-zero denominator (null and not_evaluated otherwise), per-property, route and source counts, and a reconciliation that sums
to the whole manifest.

Contracts before arithmetic. Every input is validated against its closed typed schema in evidence/evaluation-contracts/ (formats
asserted) and then semantically: canonical identities; judged links with a rationale and a read source; calendar validity per
declared date precision; split components with unique ids and membership whose union with the categorised exclusions partitions
the manifest exactly (a work in neither is a contract failure, never a silent drop); every exclusion substantiated by its category
(seed from the pinned query file, calibration for the whole family component of a disclosed calibration work, exposed from the
lock, or an explicitly unresolved allocation, which makes the result provisional); study families never crossing components;
unknown overlap placed only with a disposition naming its component, the works it was grouped with and a rationale; the declared
deterministic algorithm reproduced; exposure propagated to a whole component. The candidates file is the harvester's own artefact
(route tags route:source:instrument) and is bound to the lock by query hash, window, immutable harvester commit and predeclared
evaluation id; an unseen-holdout claim additionally requires an independently captured execution record (head, run id, start after
the lock time, the locked tool hashes among the dependencies that ran); without it the run can only be a retrospective replay and
is labelled so. A stale query, split or manifest hash against the lock stops the run. The evaluator reads gold; the harvester never
does. Output goes only to the supplied path; the self-test uses a temporary directory and no network. Invalid input exits nonzero
with named diagnostics, never a traceback.
"""
import argparse, copy, datetime, hashlib, json, re, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "evidence" / "evaluation-contracts"
FIXTURES = ROOT / "evidence" / "evaluation-tests"
ALGO = "sort component ids by sha256('owhs-recall-v1|' + component_id); floor(0.70*N) development, remainder holdout"
DISCOVERY_ROUTES = {"names", "abbreviation", "cites", "new-instrument"}
CLAIMS = ("unseen_holdout", "retrospective_replay")
EXCLUSION_CATEGORIES = ("seed", "calibration", "exposed", "unresolved_allocation")
PROPS = {"structural_validity", "convergent_discriminant_validity", "criterion_validity_reference_standard", "criterion_validity_organisational",
         "internal_consistency", "test_retest_reliability", "measurement_invariance", "responsiveness_mic", "populations_languages_norms"}


class Refused(SystemExit):
    """A contract failure: nothing measured. The message lists every named problem."""


def sha(b): return hashlib.sha256(b).hexdigest()
def sha_obj(o): return sha(json.dumps(o, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def norm_doi(doi):
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    return d.lower() or None


def instant(v):
    try: return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError): return None


def work_ids(row):
    ids = row.get("identifiers") or {}
    out = set()
    if ids.get("doi"): out.add("doi:" + norm_doi(ids["doi"]))
    if ids.get("pmid"): out.add("pmid:" + str(ids["pmid"]).strip())
    if ids.get("openalex_id"): out.add("openalex:" + str(ids["openalex_id"]).strip().upper())
    out.add(row["work_id"].lower() if row["work_id"].startswith("doi:") else row["work_id"])
    return out


def candidate_ids(c):
    out = set()
    if c.get("doi"): out.add("doi:" + norm_doi(c["doi"]))
    if c.get("pmid"): out.add("pmid:" + str(c["pmid"]).strip())
    oa = c.get("openalex") or c.get("openalex_id")
    if oa: out.add("openalex:" + str(oa).strip().upper())
    return out


def route_of(tag):
    """The harvester's route tag is route:source:instrument; the route is the first field."""
    return str(tag).split(":", 1)[0]


def calendar_problems(where, pub):
    """value and precision must agree and the value must be a real calendar date at that precision."""
    v, prec = (pub or {}).get("value"), (pub or {}).get("precision")
    if prec == "unknown": return [] if v is None else [f"{where}: precision unknown with a value"]
    if v is None: return [f"{where}: precision {prec} without a value"]
    want = {"day": 10, "month": 7, "year": 4}.get(prec)
    if want is None or len(v) != want: return [f"{where}: value {v!r} does not match precision {prec!r}"]
    try:
        if prec == "day": datetime.date.fromisoformat(v)
        elif prec == "month": datetime.date(int(v[:4]), int(v[5:7]), 1)
        else: int(v)
    except ValueError: return [f"{where}: {v!r} is not a calendar date"]
    return []


def date_in_window(pub, win_from, win_to):
    """eligible / out / unresolved from a publication_date object {value, precision} against an inclusive window."""
    v, prec = (pub or {}).get("value"), (pub or {}).get("precision", "unknown")
    if not v or prec == "unknown": return "unresolved"
    f, t = datetime.date.fromisoformat(win_from), datetime.date.fromisoformat(win_to)
    if prec == "day":
        d = datetime.date.fromisoformat(v); return "eligible" if f <= d <= t else "out"
    if prec == "month":
        y, m = map(int, v.split("-")[:2]); start = datetime.date(y, m, 1); end = (datetime.date(y + (m == 12), (m % 12) + 1, 1) - datetime.timedelta(days=1))
    elif prec == "year":
        y = int(v[:4]); start, end = datetime.date(y, 1, 1), datetime.date(y, 12, 31)
    else: return "unresolved"
    if f <= start and end <= t: return "eligible"          # wholly inside
    if end < f or start > t: return "out"                    # wholly outside
    return "unresolved"                                      # straddles a boundary: not silently placed


def seeds_from_queries(queries):
    """Seed work ids derived from the pinned query configuration, never hand-maintained."""
    out = set()
    for r in queries.get("records", []):
        for sd in r.get("citation_seeds") or []:
            if sd.get("doi"): out.add("doi:" + norm_doi(sd["doi"]))
            if sd.get("openalex_id"): out.add("openalex:" + str(sd["openalex_id"]).upper())
    return out


def sources_from_queries(queries):
    return sorted((queries.get("providers") or {}).keys()) or ["europepmc", "openalex"]


def family_components(rows):
    """Connected components of works joined by a shared study family: the unit a calibration disclosure or an exposure removes whole."""
    parent = {w: w for w in rows}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    by_fam = {}
    for w, r in rows.items():
        for fam in r.get("study_families", []): by_fam.setdefault(fam, []).append(w)
    for members in by_fam.values():
        for w in members[1:]: parent[find(w)] = find(members[0])
    groups = {}
    for w in rows: groups.setdefault(find(w), set()).add(w)
    return {w: frozenset(groups[find(w)]) for w in rows}


# ---------- typed contracts ----------

def schema_problems(kind, obj):
    from jsonschema.validators import Draft202012Validator as V
    from jsonschema import FormatChecker
    schema = json.loads((CONTRACTS / f"{kind}.schema.json").read_text(encoding="utf-8"))
    errs = sorted(V(schema, format_checker=FormatChecker()).iter_errors(obj), key=lambda e: list(map(str, e.path)))
    return [f"{kind}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:160]}" for e in errs]


def contract_problems(manifest, split, coverage, candidates, lock, queries, execution=None):
    """Everything that must hold before any arithmetic. Typed schemas first; a schema failure returns at once, because semantic checks
    assume the shapes. Then identities, judgements, calendar validity, partition, exclusions, families, dispositions, algorithm,
    exposure, provenance binding, routes and coverage shape. Returns a list of named problems."""
    p = []
    for kind, obj in (("manifest", manifest), ("split", split), ("coverage", coverage), ("candidates", candidates), ("query-lock", lock)):
        p += schema_problems(kind, obj)
    if execution is not None: p += schema_problems("execution-record", execution)
    if p: return p
    rows = {r["work_id"]: r for r in manifest["rows"]}
    if len(rows) != len(manifest["rows"]): p.append("manifest: duplicate work ids")
    if manifest["state"] not in ("split_locked", "evaluated"): p.append(f"manifest: state {manifest['state']!r}: judgements and split must be locked before evaluation")
    instruments = {r["instrument_id"] for r in queries.get("records", [])} | {r["instrument_id"] for r in queries.get("inherited_records", []) if isinstance(r, dict) and r.get("instrument_id")}
    for w, r in rows.items():
        wid_norm = ("doi:" + norm_doi(w[4:])) if w.startswith("doi:") else w
        if wid_norm != w: p.append(f"{w}: work id is not canonical (lower-case DOI, no resolver prefix)")
        ids = r["identifiers"]
        if w.startswith("doi:") and norm_doi(ids.get("doi")) != w[4:]: p.append(f"{w}: identifiers.doi conflicts with the work id")
        p += calendar_problems(f"{w}: publication_date", r["publication_date"])
        for i, l in enumerate(r["links"]):
            if l["scope"] == "measurement_property":
                if l["instrument_id"] not in instruments: p.append(f"{w}: link names instrument {l['instrument_id']!r} that the query configuration does not carry")
                if l["property"] not in PROPS: p.append(f"{w}: link names property {l['property']!r} that is not a registry property")
            if l["judgement"] in ("eligible", "ineligible"):
                if not l["reason"].strip(): p.append(f"{w}: a judged link needs a rationale")
                if l["source_location"]["read_level"] in ("metadata_only", "inaccessible"): p.append(f"{w}: a link judged {l['judgement']} needs a read source (full_text or abstract_only); metadata alone cannot judge relevance")
                if not l["judged_by"] or l["judged_by"] == "unjudged": p.append(f"{w}: a judged link needs an attributed judge")
                if l["judged_at"] is None: p.append(f"{w}: a judged link needs a judgement time")
            acc, jud = instant(l["source_location"]["accessed_at"]), instant(l["judged_at"])
            if acc and jud and jud < acc: p.append(f"{w}: link {i} judged before its source was accessed")
        if r["overlap_state"] == "resolved" and not r["study_families"]: p.append(f"{w}: overlap resolved but no study family recorded")
    # split structure: unique component ids, unique membership, every reference a manifest work
    comp_ids, membership = {}, {}
    for comp in split["components"]:
        if comp["component_id"] in comp_ids: p.append(f"component {comp['component_id']}: duplicate component id")
        comp_ids[comp["component_id"]] = comp
        for w in comp["work_ids"]:
            if w in membership: p.append(f"{w}: in two components ({membership[w]} and {comp['component_id']})")
            membership[w] = comp["component_id"]
            if w not in rows: p.append(f"{w}: in component {comp['component_id']} but not in the manifest")
    excluded = {}
    for e in split["excluded"]:
        if e["work_id"] in excluded: p.append(f"{e['work_id']}: excluded twice")
        excluded[e["work_id"]] = e
        if e["work_id"] not in rows: p.append(f"{e['work_id']}: excluded but not in the manifest")
        if e["work_id"] in membership: p.append(f"{e['work_id']}: both excluded and in component {membership[e['work_id']]}")
    # exact partition: every manifest work is in the split or carries a categorised exclusion
    unaccounted = sorted(set(rows) - set(membership) - set(excluded))
    if unaccounted: p.append(f"partition incomplete: {len(unaccounted)} manifest work(s) neither in the split nor excluded ({unaccounted[:5]}); an unexplained removal is not a disposition")
    # exclusions substantiated by category
    seeds = seeds_from_queries(queries)
    fam = family_components(rows) if rows else {}
    calib_component = set().union(*(fam[w] for w, r in rows.items() if r["calibration_only"])) if any(r["calibration_only"] for r in rows.values()) else set()
    exposed_lock = set(lock["exposed_work_ids"])
    for w, e in excluded.items():
        if w not in rows: continue
        r = rows[w]
        if e["category"] == "seed" and not (seeds & work_ids(r) or r["seed_membership"]): p.append(f"{w}: excluded as a seed but neither the pinned query file nor seed_membership names it")
        if e["category"] == "calibration" and w not in calib_component: p.append(f"{w}: excluded as calibration but it is neither a disclosed calibration work nor in one's family component")
        if e["category"] == "exposed" and w not in exposed_lock: p.append(f"{w}: excluded as exposed but the lock does not list it")
    for w, r in rows.items():
        is_seed = bool(seeds & work_ids(r) or r["seed_membership"])
        if is_seed and w in membership: p.append(f"{w}: a seed work is in the split; it must be excluded")
        if is_seed and w in excluded and excluded[w]["category"] != "seed": p.append(f"{w}: a seed work excluded under category {excluded[w]['category']!r}")
        if w in calib_component and w in membership: p.append(f"{w}: in the family component of a disclosed calibration work yet allocated; the whole component is removed before allocation")
    # families never cross components; unknown overlap needs a disposition naming the actual grouping
    fam_comp = {}
    for w, cid in membership.items():
        for f in (rows.get(w) or {}).get("study_families", []): fam_comp.setdefault(f, set()).add(cid)
    for f, comps in fam_comp.items():
        if len(comps) > 1: p.append(f"study family {f!r} spans components {sorted(comps)}: a linked family cannot cross the split boundary")
    disp = {}
    for d in split["unknown_overlap_dispositions"]:
        if d["work_id"] in disp: p.append(f"{d['work_id']}: two dispositions")
        disp[d["work_id"]] = d
    for w, cid in membership.items():
        if (rows.get(w) or {}).get("overlap_state") == "unknown":
            d = disp.get(w)
            if d is None: p.append(f"{w}: unknown overlap allocated without a recorded disposition"); continue
            if d["component_id"] != cid: p.append(f"{w}: disposition names component {d['component_id']} but the work sits in {cid}")
            others = sorted(set(comp_ids[cid]["work_ids"]) - {w}) if cid in comp_ids else []
            if sorted(d["grouped_with"]) != others: p.append(f"{w}: disposition grouped_with {sorted(d['grouped_with'])} is not the component's other works {others}; the actual conservative grouping must be stated")
    for w in disp:
        if w not in membership: p.append(f"{w}: a disposition for a work that is not allocated")
    # the declared deterministic algorithm, reproduced
    comps = sorted(split["components"], key=lambda c: hashlib.sha256(f"owhs-recall-v1|{c['component_id']}".encode()).hexdigest())
    n_dev = int(0.70 * len(comps)) if comps else 0
    want = {c["component_id"]: ("development" if i < n_dev else "holdout") for i, c in enumerate(comps)}
    bad = [c["component_id"] for c in comps if c["allocation"] != want[c["component_id"]]]
    if bad: p.append(f"split allocation does not follow the declared algorithm for components {bad[:5]}")
    # exposure propagates to the whole component
    for comp in split["components"]:
        ws = set(comp["work_ids"])
        if exposed_lock & ws and not ws <= exposed_lock: p.append(f"component {comp['component_id']}: exposure of one work must exclude the whole component (siblings share the leak)")
    # provenance: candidates bound to the lock; an unseen-holdout claim bound to an independently captured execution record
    if candidates["query_sha256"] != lock["query_sha256"]: p.append("candidates were not produced by the locked query file (query hash differs)")
    rw = candidates["requested_window"]
    if (rw["from"], rw["to"]) != (lock["run_window"]["from"], lock["run_window"]["to"]): p.append("candidates were produced over a different window than the lock's run window")
    if candidates["registry_commit"] != lock["harvester"]["commit"]: p.append(f"candidates name harvester commit {str(candidates['registry_commit'])[:12]!r}, the lock {lock['harvester']['commit'][:12]!r}")
    cs, cf, lt = instant(candidates["started_at"]), instant(candidates["finished_at"]), instant(lock["locked_at"])
    if cs and cf and cf < cs: p.append("candidates finished before they started")
    if candidates["evaluation_id"] is not None and candidates["evaluation_id"] != lock["evaluation_id"]: p.append(f"candidates carry evaluation id {candidates['evaluation_id']!r}, the lock {lock['evaluation_id']!r}")
    if lock["claim"] == "unseen_holdout":
        if candidates["evaluation_id"] is None: p.append("an unseen-holdout claim needs the candidates to carry the predeclared evaluation id (harvest.py --evaluation-id)")
        if cs and lt and cs <= lt: p.append(f"an unseen-holdout claim needs discovery to start after the lock ({candidates['started_at']} is not after {lock['locked_at']})")
        if execution is None: p.append("an unseen-holdout claim needs an independently captured execution record (--execution-record); without it the run can only be a retrospective replay")
    if execution is not None:
        if execution["head_sha"] != lock["harvester"]["commit"]: p.append(f"execution record head {execution['head_sha'][:12]} is not the locked harvester commit {lock['harvester']['commit'][:12]}")
        if execution["run_id"] != candidates["run_id"]: p.append(f"execution record run {execution['run_id']!r} is not the candidates' run {candidates['run_id']!r}")
        es, ef = instant(execution["started_at"]), instant(execution["finished_at"])
        if es and cs and abs((es - cs).total_seconds()) > 120: p.append("execution record start differs from the candidates' start by more than 120 s")
        if es and ef and ef < es: p.append("execution record finished before it started")
        if lock["claim"] == "unseen_holdout" and es and lt and es <= lt: p.append("execution record shows the run starting at or before the lock time; not an unseen holdout")
        ran = {d["path"]: d["sha256"] for d in execution["dependencies"]}
        for path, h in lock["harvester"]["tools_sha256"].items():
            if ran.get(path) != h: p.append(f"locked hash for {path} is not among the dependencies the execution record captured as having run")
    # candidate routes are the harvester's tags; the route field must be a discovery route
    for c in candidates["candidates"]:
        unknown = {route_of(t) for t in c["routes"]} - DISCOVERY_ROUTES
        if unknown: p.append(f"candidate {c.get('doi') or c.get('pmid') or '?'}: unrecognised route(s) {sorted(unknown)}")
    # coverage rows: duplicates, sources within the profile
    prof = set(sources_from_queries(queries))
    seen_cov = set()
    for row in coverage["rows"]:
        k = (row["work_id"], row["source_id"])
        if k in seen_cov: p.append(f"coverage: duplicate row for {k}")
        seen_cov.add(k)
        if row["source_id"] not in prof: p.append(f"coverage: source {row['source_id']!r} is not in the configured provider profile; it cannot manufacture C")
    return p


def evaluate(manifest, split, coverage, candidates, lock, queries_sha, queries, execution=None):
    """Accounting after the contracts hold. Returns the report dict; raises Refused (a SystemExit) on a stale lock or a contract failure."""
    stale = []
    if not isinstance(lock, dict): raise Refused("contract problems, nothing measured:\n  query-lock: <root>: not an object")
    if lock.get("query_sha256") != queries_sha: stale.append("query file hash differs from the lock")
    if lock.get("manifest_sha256") != sha_obj(manifest): stale.append("manifest hash differs from the lock")
    if lock.get("split_sha256") != sha_obj(split): stale.append("split hash differs from the lock")
    if stale: raise Refused("stale inputs against the query lock: " + "; ".join(stale))
    cp = contract_problems(manifest, split, coverage, candidates, lock, queries, execution)
    if cp: raise Refused(f"contract problems, nothing measured ({len(cp)}):\n  " + "\n  ".join(cp[:40]))
    enabled_sources = sources_from_queries(queries)          # the configured profile, never an unconstrained argument
    win = lock["run_window"]
    rows = {r["work_id"]: r for r in manifest["rows"]}
    component_of = {}
    for comp in split["components"]:
        for w in comp["work_ids"]: component_of[w] = comp
    holdout = {w for w, c in component_of.items() if c["allocation"] == "holdout"}
    excluded = {e["work_id"]: e["category"] for e in split["excluded"]}
    exposed = set(lock["exposed_work_ids"])
    # candidates found by a discovery route: the harvester's route tags, and the separate new-instrument list
    found_ids, found_routes = set(), {}
    for c in candidates["candidates"]:
        disc = {route_of(t) for t in c["routes"]} & DISCOVERY_ROUTES
        if not disc: continue
        for i in candidate_ids(c): found_ids.add(i); found_routes.setdefault(i, set()).update(disc)
    for c in candidates["new_instrument_candidates"]:
        for i in candidate_ids(c): found_ids.add(i); found_routes.setdefault(i, set()).add("new-instrument")
    recon = {"manifest_total": len(rows), "seed": 0, "calibration": 0, "exposed": 0, "unresolved_allocation": 0, "development": 0, "out_of_window": 0, "date_unresolved": 0, "no_eligible_link": 0, "relevance_unresolved": 0, "eligible_holdout": 0}
    E, unresolved_rel, misses, hits, unresolved_alloc = [], [], [], [], []
    for w, r in rows.items():
        if w in excluded:
            recon[excluded[w]] += 1
            if excluded[w] == "unresolved_allocation": unresolved_alloc.append(w)
            continue
        if w in exposed: recon["exposed"] += 1; continue
        if w not in holdout: recon["development"] += 1; continue
        links = [l for l in r["links"] if l["scope"] == "measurement_property"]
        if any(l["judgement"] == "unresolved" for l in links) and not any(l["judgement"] == "eligible" for l in links):
            recon["relevance_unresolved"] += 1; unresolved_rel.append(w); continue
        if not any(l["judgement"] == "eligible" for l in links): recon["no_eligible_link"] += 1; continue
        dw = date_in_window(r["publication_date"], win["from"], win["to"])
        if dw == "out": recon["out_of_window"] += 1; continue
        if dw == "unresolved": recon["date_unresolved"] += 1; continue
        recon["eligible_holdout"] += 1; E.append(w)
        (hits if work_ids(r) & found_ids else misses).append(w)
    assert sum(v for k, v in recon.items() if k != "manifest_total") == recon["manifest_total"], "reconciliation does not sum to the manifest"
    # coverage: indexed by any enabled source at the coverage check; failed/unsupported/unresolved counted, never read as not indexed
    cov = {}
    for row in coverage["rows"]: cov.setdefault(row["work_id"], {})[row["source_id"]] = row["status"]
    C = [w for w in E if any(cov.get(w, {}).get(s) == "indexed" for s in enabled_sources)]
    def state(w):
        st = {s: cov.get(w, {}).get(s, "missing") for s in enabled_sources}
        if "indexed" in st.values(): return "indexed"
        if all(v == "not_indexed" for v in st.values()): return "not_indexed"
        if any(v in ("failed", "unresolved") for v in st.values()): return "failed_or_unresolved"
        return "unknown"
    cov_state = {w: state(w) for w in E}
    cov_failed = [w for w in E if cov_state[w] == "failed_or_unresolved"]
    cov_unknown = [w for w in E if cov_state[w] == "unknown"]
    per_source = {s: {"indexed": 0, "not_indexed": 0, "failed": 0, "unsupported": 0, "unresolved": 0, "missing": 0} for s in enabled_sources}
    for w in E:
        for s in enabled_sources: per_source[s][cov.get(w, {}).get(s, "missing")] += 1
    hits_not_in_C = [w for w in hits if w not in C]          # kept in the full numerator; reported, C never rewritten
    def ratio(n, d): return None if d == 0 else round(n / d, 4)
    per_instrument = {}
    for w in E:
        for l in rows[w]["links"]:
            if l["scope"] == "measurement_property" and l["judgement"] == "eligible":
                per_instrument.setdefault(l["instrument_id"], {"eligible_links": set(), "found_links": set()})
                per_instrument[l["instrument_id"]]["eligible_links"].add((w, l["property"]))
                if w in hits: per_instrument[l["instrument_id"]]["found_links"].add((w, l["property"]))
    inst = {k: {"eligible_work_links": len(v["eligible_links"]), "found_work_links": len(v["found_links"]), "recall": ratio(len(v["found_links"]), len(v["eligible_links"])), "state": "evaluated" if v["eligible_links"] else "not_evaluated"} for k, v in per_instrument.items()}
    for iid in lock["instrument_ids"]: inst.setdefault(iid, {"eligible_work_links": 0, "found_work_links": 0, "recall": None, "state": "not_evaluated"})
    per_property, per_route, per_language = {}, {}, {}
    for w in E:
        r = rows[w]; hit = w in hits
        lang = (r.get("citation") or {}).get("language") or "unknown"
        per_language.setdefault(lang, {"eligible_works": 0, "found": 0}); per_language[lang]["eligible_works"] += 1; per_language[lang]["found"] += hit
        for l in r["links"]:
            if l["scope"] == "measurement_property" and l["judgement"] == "eligible":
                per_property.setdefault(l["property"], {"eligible_work_links": 0, "found_work_links": 0, "miss_ids": []})
                per_property[l["property"]]["eligible_work_links"] += 1
                if hit: per_property[l["property"]]["found_work_links"] += 1
                else: per_property[l["property"]]["miss_ids"].append(w)
        if hit:
            for rt in set().union(*(found_routes.get(i, set()) for i in work_ids(r))): per_route[rt] = per_route.get(rt, 0) + 1
    for v in per_property.values(): v["recall"] = ratio(v["found_work_links"], v["eligible_work_links"])
    for v in per_language.values(): v["recall"] = ratio(v["found"], v["eligible_works"])
    unresolved_links = {w: [f"{l['instrument_id']}.{l['property']}" for l in rows[w]["links"] if l["scope"] == "measurement_property" and l["judgement"] == "unresolved"] for w in E if any(l["judgement"] == "unresolved" for l in rows[w]["links"])}
    non_gold = sorted(found_ids - {i for w in rows for i in work_ids(rows[w])})
    macro_vals = [v["recall"] for v in inst.values() if v["recall"] is not None]
    provisional = bool(unresolved_rel or recon["date_unresolved"] or unresolved_links or unresolved_alloc)
    claim_state = {"unseen_holdout": "unseen holdout: discovery ran after the lock, bound to an independently captured execution record",
                   "retrospective_replay": "retrospective replay: regression coverage of the locked queries over an earlier run, not unseen holdout performance"}[lock["claim"]]
    return {"schema_version": "1.1", "state": "evaluated" if not provisional else "evaluated_provisional", "claim": lock["claim"], "claim_state": claim_state,
            "provenance": {"evaluation_id": lock["evaluation_id"], "locked_at": lock["locked_at"], "harvester_commit": lock["harvester"]["commit"], "locked_tool_hashes": lock["harvester"]["tools_sha256"],
                           "candidates_run_id": candidates["run_id"], "candidates_started_at": candidates["started_at"], "candidates_evaluation_id": candidates["evaluation_id"],
                           "execution_record": (None if execution is None else {k: execution[k] for k in ("run_id", "mode", "head_sha", "started_at", "run_url", "captured_at", "captured_by")})},
            "window": win, "denominators": {"E_eligible_holdout_works": len(E), "F_found": len(hits), "C_indexed_by_an_enabled_source": len(C), "F_and_C": len([w for w in hits if w in C]),
                                            "coverage_failed_or_unresolved": len(cov_failed), "coverage_unknown": len(cov_unknown)},
            "work_level_recall": ratio(len(hits), len(E)), "work_level_recall_state": "evaluated" if E else "not_evaluated",
            "conditional_recall_given_indexed": ratio(len([w for w in hits if w in C]), len(C)), "conditional_state": "evaluated" if C else "not_evaluated",
            "hits_absent_from_coverage_snapshot": hits_not_in_C,
            "macro_recall_over_instruments": (round(sum(macro_vals) / len(macro_vals), 4) if macro_vals else None), "instruments": dict(sorted(inst.items())),
            "misses": sorted(misses), "hits": sorted(hits), "provisional": provisional, "unresolved_relevance": sorted(unresolved_rel), "unresolved_allocation": sorted(unresolved_alloc),
            "unresolved_links_on_eligible_works": unresolved_links,
            "by_property": dict(sorted(per_property.items())), "by_route_of_hit": dict(sorted(per_route.items())), "by_language": dict(sorted(per_language.items())),
            "coverage_by_source": per_source, "coverage_state_counts": {k: sum(1 for v in cov_state.values() if v == k) for k in ("indexed", "not_indexed", "failed_or_unresolved", "unknown")},
            "reconciliation": recon, "candidates_not_in_gold_count": len(non_gold), "candidates_not_in_gold": non_gold,
            "note": "A work is counted once however many instruments it serves; by-instrument rows count distinct work-link pairs and are not independent studies. A hit absent from the coverage snapshot stays in F and is listed. Works excluded as unresolved_allocation are counted and make the figure provisional. No recall threshold means complete; every miss relevant to a High cell needs written review before any public claim."}


# ---------- fixtures ----------

FX_COMMIT = "1" * 40
FX_TOOLS = {"tools/harvest.py": "2" * 64, "tools/cycle.py": "3" * 64, "evidence/queries/instruments-v1.json": "4" * 64}
FX_LOCKED_AT, FX_STARTED, FX_FINISHED = "2026-09-04T12:00:00Z", "2026-09-05T06:00:00+00:00", "2026-09-05T06:20:00+00:00"


def _row(wid, inst_links, date=("2026-08-15", "day"), calib=False, ids=None, read="abstract_only", judged_by="fixture-judge", families=None):
    return {"work_id": wid, "identifiers": ids or {"doi": wid[4:] if wid.startswith("doi:") else None, "pmid": None, "openalex_id": None},
            "citation": {"title": f"Title {wid}", "authors": ["A"], "year": 2026, "source_url": "https://example.org"},
            "publication_date": {"value": date[0], "precision": date[1], "source_url": "https://example.org"},
            "record_type": "primary_study", "calibration_only": calib, "overlap_state": "resolved", "study_families": families if families is not None else [f"fam-{wid}"], "seed_membership": [],
            "links": [{"instrument_id": i, "property": pr, "form": None, "scope": "measurement_property", "judgement": j, "reason": "fixture rationale" if j != "unresolved" else "",
                       "source_location": {"url": "https://example.org", "read_level": read, "section": None, "printed_pages": None, "table_or_figure": None, "accessed_at": "2026-09-04T00:00:00Z", "response_status": 200},
                       "judged_by": judged_by if j != "unresolved" else "unjudged", "judged_at": "2026-09-04T01:00:00Z" if j != "unresolved" else None} for i, pr, j in inst_links],
            "judgements": [], "unresolved": []}


def _queries(seed_dois=()):
    return {"version": "fixture", "providers": {"europepmc": {}, "openalex": {}}, "property_terms": ["validation"],
            "records": [{"instrument_id": "isi", "names": ["Insomnia Severity Index"], "citation_seeds": [{"doi": d, "openalex_id": None} for d in seed_dois]}, {"instrument_id": "who-5", "names": ["WHO-5"], "citation_seeds": []}]}


def _split(components, excluded=(), dispositions=()):
    """Allocate the given components by the declared algorithm; exclusions are (work_id, category, detail) triples."""
    comps = [{"component_id": c["component_id"], "work_ids": list(c["work_ids"])} for c in components]
    order = sorted(comps, key=lambda c: hashlib.sha256(f"owhs-recall-v1|{c['component_id']}".encode()).hexdigest())
    n_dev = int(0.70 * len(order))
    for i, c in enumerate(order): c["allocation"] = "development" if i < n_dev else "holdout"
    return {"schema_version": "1.0", "algorithm": ALGO, "components": comps, "excluded": [{"work_id": w, "category": cat, "detail": det} for w, cat, det in excluded], "unknown_overlap_dispositions": list(dispositions)}


def _lock(manifest, split, queries, claim="unseen_holdout", exposed=()):
    return {"schema_version": "1.0", "evaluation_id": "eval-fixture-001", "locked_at": FX_LOCKED_AT, "claim": claim, "query_sha256": sha_obj(queries), "manifest_sha256": sha_obj(manifest), "split_sha256": sha_obj(split),
            "harvester": {"commit": FX_COMMIT, "tools_sha256": dict(FX_TOOLS)}, "run_window": {"from": "2026-08-01", "to": "2026-09-05"}, "exposed_work_ids": list(exposed), "instrument_ids": ["isi", "who-5"]}


def _cands(queries, found_dois, evaluation_id="eval-fixture-001"):
    return {"schema_version": "1.1", "harvester": "tools/harvest.py 0.2", "run_id": "fx-run-0001", "registry_commit": FX_COMMIT, "query_version": "fixture", "query_sha256": sha_obj(queries),
            "requested_window": {"from": "2026-08-01", "to": "2026-09-05", "type": "publication date, inclusive"}, "started_at": FX_STARTED, "finished_at": FX_FINISHED, "status": "complete",
            "evaluation_id": evaluation_id, "candidates": [{"id": d, "doi": d, "pmid": None, "openalex": None, "title": f"Title doi:{d}", "routes": ["names:europepmc:isi"]} for d in found_dois], "new_instrument_candidates": []}


def _exec():
    return {"schema_version": "1.0", "run_id": "fx-run-0001", "mode": "github_action", "head_sha": FX_COMMIT, "started_at": FX_STARTED, "finished_at": FX_FINISHED, "run_url": "https://github.com/example/repo/actions/runs/1",
            "dependencies": [{"path": k, "sha256": v} for k, v in FX_TOOLS.items()] + [{"path": ".github/workflows/harvest.yml", "sha256": "5" * 64}], "captured_at": "2026-09-05T07:00:00Z", "captured_by": "fixture"}


def _setup(n=10, n_found=7, seeds=()):
    """n target works that the real deterministic algorithm places in holdout, plus development filler rows: 33 components in all
    give floor(0.70*33)=23 development and 10 holdout; the ten component ids highest in hash order carry the targets."""
    n_total = 33 if n else 0
    ids = [f"c{i}" for i in range(n_total)]
    order = sorted(ids, key=lambda cid: hashlib.sha256(f"owhs-recall-v1|{cid}".encode()).hexdigest())
    holdout_ids, dev_ids = order[23:], order[:23]
    rows = [_row(f"doi:10.5555/w{i}", [("isi", "internal_consistency", "eligible")]) for i in range(n)]
    fillers = [_row(f"doi:10.5555/d{i}", [("isi", "internal_consistency", "eligible")], date=("2020-01-15", "day")) for i in range(len(dev_ids))]     # out of window: never in E
    for r in rows:
        if r["identifiers"]["doi"] in seeds: r["seed_membership"] = ["isi:seed"]
    excluded = tuple(f"doi:10.5555/{d.split('/')[-1]}" for d in seeds)
    comps = [{"component_id": cid, "work_ids": [rows[i]["work_id"]]} for i, cid in enumerate(holdout_ids[:n]) if rows[i]["work_id"] not in excluded]
    comps += [{"component_id": cid, "work_ids": [fillers[i]["work_id"]]} for i, cid in enumerate(dev_ids)]
    split = _split(comps, excluded=[(w, "seed", "query citation seed in the pinned query file") for w in excluded])
    manifest = {"schema_version": "1.0", "benchmark_id": "synthetic-fixture", "created_at": "2026-09-04T00:00:00Z", "dataset": {"commit": "0" * 40, "relative_path": "none", "sha256": "0" * 64, "version": "synthetic"},
                "query_seed_source": {"version": "synthetic", "sha256": "0" * 64}, "eligibility_protocol_version": "synthetic", "calibration_ids": [], "state": "split_locked", "rows": rows + fillers}
    queries = _queries(seeds)
    lock = _lock(manifest, split, queries)
    cands = _cands(queries, [f"10.5555/w{i}" for i in range(n_found)])
    cov = {"schema_version": "1.0", "rows": [{"work_id": r["work_id"], "source_id": src, "status": "indexed", "checked_at": "2026-09-05T08:00:00Z", "lookup_method": "fixture", "response_sha256": "0" * 64} for r in rows for src in ("europepmc", "openalex")]}
    return manifest, split, cov, cands, lock, queries


def _relock(lock, manifest=None, split=None, queries=None):
    if manifest is not None: lock["manifest_sha256"] = sha_obj(manifest)
    if split is not None: lock["split_sha256"] = sha_obj(split)
    if queries is not None: lock["query_sha256"] = sha_obj(queries)
    return lock


def synthetic_fixtures():
    """The public synthetic fixture set: 33 works, four holdout works of interest, three retrieved; one execution record."""
    m, s, c, cand, lock, q = _setup(4, 3)
    return {"manifest.synthetic.json": m, "split.synthetic.json": s, "coverage.synthetic.json": c, "candidates.synthetic.json": cand, "query-lock.synthetic.json": lock, "queries.synthetic.json": q, "execution-record.synthetic.json": _exec()}


def write_fixtures(d):
    d = Path(d); d.mkdir(parents=True, exist_ok=True)
    fx = synthetic_fixtures()
    # the lock pins the query FILE bytes, so the query file is written first and its file hash taken
    (d / "queries.synthetic.json").write_text(json.dumps(fx["queries.synthetic.json"], indent=1) + "\n", encoding="utf-8")
    qsha = sha((d / "queries.synthetic.json").read_bytes())
    fx["query-lock.synthetic.json"]["query_sha256"] = qsha; fx["candidates.synthetic.json"]["query_sha256"] = qsha
    for name, obj in fx.items():
        if name != "queries.synthetic.json": (d / name).write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")
    return sorted(fx)


def self_test():
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else detail); failures += not ok
    def run(m, s, c, cand, lock, q, ex="default"): return evaluate(m, s, c, cand, lock, lock["query_sha256"], q, _exec() if ex == "default" else ex)
    def refused(m, s, c, cand, lock, q, ex="default"):
        try: evaluate(m, s, c, cand, lock, lock["query_sha256"], q, _exec() if ex == "default" else ex); return None
        except SystemExit as e: return str(e)
    def comp_of(split, wid): return next(x for x in split["components"] if wid in x["work_ids"])
    def rebuild(split): return _split([{"component_id": x["component_id"], "work_ids": x["work_ids"]} for x in split["components"]], excluded=[(e["work_id"], e["category"], e["detail"]) for e in split["excluded"]], dispositions=split["unknown_overlap_dispositions"])
    m, s, c, cand, lock, q = _setup(); r = run(m, s, c, cand, lock, q)
    t("10 eligible with 7 found gives 7/10", r["denominators"]["E_eligible_holdout_works"] == 10 and r["work_level_recall"] == 0.7 and len(r["misses"]) == 3)
    m, s, c, cand, lock, q = _setup(10, 3)
    c = {"schema_version": "1.0", "rows": [{**row, "status": ("indexed" if int(row["work_id"][-1]) < 4 else "not_indexed")} for row in c["rows"]]}
    r = run(m, s, c, cand, lock, q); t("10 eligible, 4 known indexed, 3 found gives 3/10 and 3/4", r["work_level_recall"] == 0.3 and r["conditional_recall_given_indexed"] == 0.75)
    m, s, c, cand, lock, q = _setup(seeds=("10.5555/w0",)); r = run(m, s, c, cand, lock, q)
    t("a seed (from the pinned query file) retrieved is excluded from numerator and denominator", r["denominators"]["E_eligible_holdout_works"] == 9 and r["denominators"]["F_found"] == 6 and r["reconciliation"]["seed"] == 1)
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["seed_membership"] = ["isi:seed"]; _relock(lock, manifest=m)
    t("a row marked seed that the split still allocates is a contract failure, not a silently evaluated run", "a seed work is in the split" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"].append({**m["rows"][0]["links"][0], "instrument_id": "who-5"}); _relock(lock, manifest=m)
    r = run(m, s, c, cand, lock, q); t("one work linked to two instruments is counted once at work level and appears in both instrument rows", r["denominators"]["E_eligible_holdout_works"] == 10 and r["instruments"]["who-5"]["eligible_work_links"] == 1 and r["instruments"]["isi"]["eligible_work_links"] == 10)
    # shared cohort: same family across two components is refused; in one component moves together
    m, s, c, cand, lock, q = _setup(); m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]; _relock(lock, manifest=m)
    t("two publications sharing a family allocated to different components are refused", "cannot cross the split boundary" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]
    c1 = comp_of(s, "doi:10.5555/w1"); s["components"].remove(c1); comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w1"); s = rebuild(s); _relock(lock, manifest=m, split=s)
    r = run(m, s, c, cand, lock, q); t("a shared cohort in one component moves together (both in one allocation; the split still follows the algorithm)", comp_of(s, "doi:10.5555/w0")["allocation"] == comp_of(s, "doi:10.5555/w1")["allocation"] and sum(r["reconciliation"][k] for k in ("eligible_holdout", "development", "out_of_window")) == 33)
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["publication_date"] = {"value": "2026", "precision": "year", "source_url": "x"}; m["rows"][1]["publication_date"] = {"value": "2025", "precision": "year", "source_url": "x"}; m["rows"][2]["publication_date"] = {"value": None, "precision": "unknown", "source_url": "x"}; _relock(lock, manifest=m)
    r = run(m, s, c, cand, lock, q); t("a year-only date straddling the window is unresolved, one wholly outside is out, an unknown date is unresolved; the figure is provisional", r["reconciliation"]["date_unresolved"] == 2 and r["reconciliation"]["out_of_window"] == 1 and r["provisional"] is True)
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"][0].update({"judgement": "unresolved", "reason": "", "judged_by": "unjudged", "judged_at": None}); _relock(lock, manifest=m)
    r = run(m, s, c, cand, lock, q); t("unresolved relevance is counted and reported, not dropped, and makes the figure provisional", r["reconciliation"]["relevance_unresolved"] == 1 and r["unresolved_relevance"] == ["doi:10.5555/w0"] and r["provisional"])
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["abstract"] = ""; r = run(m, s, c, cand, lock, q); t("an eligible hit with no abstract still counts as found", "doi:10.5555/w0" in r["hits"])
    m, s, c, cand, lock, q = _setup(); cand["candidates"].append({"id": "10.9999/not-gold", "doi": "10.9999/not-gold", "pmid": None, "openalex": None, "routes": ["names:europepmc:isi"]}); r = run(m, s, c, cand, lock, q)
    t("a candidate not in gold is listed in full with a count and does not change recall", r["candidates_not_in_gold"] == ["doi:10.9999/not-gold"] and r["candidates_not_in_gold_count"] == 1 and r["work_level_recall"] == 0.7)
    m, s, c, cand, lock, q = _setup(0, 0); r = run(m, s, c, cand, lock, q)
    t("an all-zero denominator yields metric null and state not_evaluated, never 100%", r["work_level_recall"] is None and r["work_level_recall_state"] == "not_evaluated" and r["instruments"]["isi"]["recall"] is None)
    m, s, c, cand, lock, q = _setup(); lock["query_sha256"] = "f" * 64
    try: evaluate(m, s, c, cand, lock, sha_obj(q), q, _exec()); t("a stale query hash stops the run", False)
    except SystemExit as e: t("a stale query hash stops the run", "query file hash" in str(e))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["unresolved"] = ["x"]; t("a stale manifest hash stops the run", "manifest hash" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(10, 3); c = {"schema_version": "1.0", "rows": [{**row, "status": "failed"} for row in c["rows"]]}; r = run(m, s, c, cand, lock, q)
    t("a failed coverage lookup is not read as not indexed: conditional recall not evaluated, failures counted", r["conditional_state"] == "not_evaluated" and r["denominators"]["coverage_failed_or_unresolved"] == 10)
    # exposure propagates to the component
    m, s, c, cand, lock, q = _setup(); lock["exposed_work_ids"] = ["doi:10.5555/w0"]; r = run(m, s, c, cand, lock, q)
    t("an exposed holdout work is excluded and counted as exposure", r["reconciliation"]["exposed"] == 1 and r["denominators"]["E_eligible_holdout_works"] == 9)
    m, s, c, cand, lock, q = _setup(); c1 = comp_of(s, "doi:10.5555/w1"); s["components"].remove(c1); comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w1")
    m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]; s = rebuild(s); _relock(lock, manifest=m, split=s); lock["exposed_work_ids"] = ["doi:10.5555/w0"]
    t("exposure of one work in a two-work component without its sibling is refused", "exclude the whole component" in (refused(m, s, c, cand, lock, q) or ""))
    lock["exposed_work_ids"] = ["doi:10.5555/w0", "doi:10.5555/w1"]; r = run(m, s, c, cand, lock, q); t("exposure declared for the whole component excludes both", r["reconciliation"]["exposed"] == 2)
    m, s, c, cand, lock, q = _setup(); m["rows"][1]["citation"]["title"] = m["rows"][0]["citation"]["title"]; _relock(lock, manifest=m); cand["candidates"] = [{"id": "10.5555/w0", "doi": "10.5555/w0", "pmid": None, "openalex": None, "title": "Title doi:10.5555/w0", "routes": ["names:europepmc:isi"]}]
    r = run(m, s, c, cand, lock, q); t("a title collision with a different DOI does not count the second work as found", r["hits"] == ["doi:10.5555/w0"])
    m, s, c, cand, lock, q = _setup(); m["rows"].append(_row("doi:10.5555/w0corr", [("isi", "internal_consistency", "eligible")])); m["rows"][-1]["record_type"] = "correction"
    comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w0corr"); m["rows"][-1]["study_families"] = ["fam-doi:10.5555/w0"]; _relock(lock, manifest=m, split=s)
    r = run(m, s, c, cand, lock, q); t("a correction notice is a distinct work from its original and is a separate miss when not retrieved", "doi:10.5555/w0corr" in r["misses"] and "doi:10.5555/w0" in r["hits"])
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["identifiers"]["doi"] = "10.1027//1015-5759.19.1.12"; m["rows"][0]["work_id"] = "doi:10.1027//1015-5759.19.1.12"; comp_of(s, "doi:10.5555/w0")["work_ids"] = ["doi:10.1027//1015-5759.19.1.12"]
    for row in c["rows"]:
        if row["work_id"] == "doi:10.5555/w0": row["work_id"] = "doi:10.1027//1015-5759.19.1.12"
    _relock(lock, manifest=m, split=s)
    cand["candidates"][0] = {"id": "x", "doi": "HTTPS://DOI.ORG/10.1027//1015-5759.19.1.12", "pmid": None, "openalex": None, "routes": ["names:europepmc:isi"]}; r = run(m, s, c, cand, lock, q)
    t("duplicate casing and the OLBI double slash canonicalise to the same identity", "doi:10.1027//1015-5759.19.1.12" in r["hits"])
    # routes: the harvester's tags; an identifier lookup is not among them; unrecognised or missing routes fail the typed contract
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["routes"] = ["identifier_lookup:europepmc:isi"]; t("an identifier lookup tag is not a discovery route and fails the candidates contract", "routes" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["routes"] = []; t("a candidate with no routes (no discovery provenance) is a contract failure", "routes" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); cand["new_instrument_candidates"] = [{"id": "10.5555/w9", "doi": "10.5555/w9", "pmid": None}]; cand["candidates"] = cand["candidates"][:6]; r = run(m, s, c, cand, lock, q)
    t("a gold work in the harvester's separate new-instrument list counts as found by the new-instrument route", "doi:10.5555/w9" in r["hits"] and r["by_route_of_hit"].get("new-instrument") == 1)
    # judgement needs reading; the typed read-level enum is enforced by the schema
    m, s, c, cand, lock, q = _setup()
    for r_ in m["rows"]: r_["links"][0]["source_location"]["read_level"] = "metadata_only"
    _relock(lock, manifest=m); t("eligible links judged from metadata only are a contract failure: relevance needs a read source", "metadata alone" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup()
    for r_ in m["rows"]: r_["links"][0]["source_location"]["read_level"] = "glanced"
    _relock(lock, manifest=m); msg = refused(m, s, c, cand, lock, q) or ""; t("an unrecognised read-level string fails the typed manifest contract (invented reading provenance is refused)", "read_level" in msg and "manifest:" in msg, msg[:200])
    # coverage policy and typed coverage rows
    m, s, c, cand, lock, q = _setup(10, 3); c = {"schema_version": "1.0", "rows": [{**row, "status": "not_indexed"} for row in c["rows"] if row["source_id"] == "europepmc"]}; r = run(m, s, c, cand, lock, q)
    t("Europe PMC not_indexed with OpenAlex rows absent leaves coverage unknown for every work; C is 0 and F/E is untouched", r["denominators"]["C_indexed_by_an_enabled_source"] == 0 and r["denominators"]["coverage_unknown"] == 10 and r["coverage_by_source"]["openalex"]["missing"] == 10 and r["work_level_recall"] == 0.3)
    m, s, c, cand, lock, q = _setup(); c["rows"].append({"work_id": "doi:10.5555/w0", "source_id": "crossref-not-in-profile", "status": "indexed", "checked_at": "2026-09-05T08:00:00Z", "lookup_method": "x", "response_sha256": "0" * 64})
    t("a coverage source outside the configured profile cannot manufacture C", "cannot manufacture C" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); c["rows"].append(dict(c["rows"][0])); t("duplicate coverage rows are refused", "duplicate row" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); c["rows"][0]["checked_at"] = "not-a-date"; c["rows"][1]["response_sha256"] = "x"; msg = refused(m, s, c, cand, lock, q) or ""
    t("coverage rows with an invalid date and a short hash fail the typed coverage contract", "coverage: rows/0/checked_at" in msg and "coverage: rows/1/response_sha256" in msg, msg[:300])
    m, s, c, cand, lock, q = _setup(10, 7); c = {"schema_version": "1.0", "rows": [row for row in c["rows"] if row["work_id"] != "doi:10.5555/w0"]}
    r = run(m, s, c, cand, lock, q); t("a hit absent from the coverage snapshot stays in F and is listed; C is not rewritten", r["denominators"]["F_found"] == 7 and r["hits_absent_from_coverage_snapshot"] == ["doi:10.5555/w0"] and r["denominators"]["C_indexed_by_an_enabled_source"] == 9)
    # execution binding: query, window, commit, evaluation id, lock time, execution record
    m, s, c, cand, lock, q = _setup(); cand["query_sha256"] = "e" * 64; t("candidates produced by another query file are refused even with today's matching query supplied", "not produced by the locked query file" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); cand["requested_window"] = {"from": "2026-01-01", "to": "2026-03-31", "type": "publication date, inclusive"}; t("candidates produced over another window are refused", "different window" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); lock["harvester"]["commit"] = "a" * 40; msg = refused(m, s, c, cand, lock, q) or ""
    t("a locked harvester commit that the candidates and execution record do not name is refused", "harvester commit" in msg and "execution record head" in msg, msg[:300])
    m, s, c, cand, lock, q = _setup(); cand["evaluation_id"] = None; t("an unseen-holdout claim needs the candidates to carry the predeclared evaluation id", "predeclared evaluation id" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); cand["evaluation_id"] = "eval-other"; t("candidates carrying another evaluation id are refused", "carry evaluation id" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); t("an unseen-holdout claim without an execution record is refused", "independently captured execution record" in (refused(m, s, c, cand, lock, q, ex=None) or ""))
    m, s, c, cand, lock, q = _setup(); lock["locked_at"] = "2026-09-05T06:30:00Z"; ex = _exec(); msg = refused(m, s, c, cand, lock, q, ex=ex) or ""
    t("discovery that started at or before the lock time cannot support an unseen-holdout claim (candidates and execution record both checked)", "is not after" in msg and "at or before the lock time" in msg, msg[:300])
    lock["claim"] = "retrospective_replay"; cand["evaluation_id"] = None; r = run(m, s, c, cand, lock, q, ex=ex)
    t("the same inputs under a retrospective-replay claim evaluate and are labelled as regression coverage, never unseen holdout", r["claim"] == "retrospective_replay" and "not unseen holdout performance" in r["claim_state"] and r["work_level_recall"] == 0.7)
    m, s, c, cand, lock, q = _setup(); lock["claim"] = "retrospective_replay"; r = run(m, s, c, cand, lock, q, ex=None); t("a retrospective replay may run without an execution record and says so in provenance", r["provenance"]["execution_record"] is None and r["claim"] == "retrospective_replay")
    m, s, c, cand, lock, q = _setup(); ex = _exec(); ex["dependencies"] = [d for d in ex["dependencies"] if d["path"] != "tools/harvest.py"]; t("a locked tool hash absent from the dependencies that ran is refused", "not among the dependencies" in (refused(m, s, c, cand, lock, q, ex=ex) or ""))
    m, s, c, cand, lock, q = _setup(); ex = _exec(); ex["dependencies"][0]["sha256"] = "9" * 64; t("a locked tool hash differing from the dependency that ran is refused", "not among the dependencies" in (refused(m, s, c, cand, lock, q, ex=ex) or ""))
    m, s, c, cand, lock, q = _setup(); ex = _exec(); ex["run_id"] = "other-run"; t("an execution record for another run is refused", "is not the candidates' run" in (refused(m, s, c, cand, lock, q, ex=ex) or ""))
    m, s, c, cand, lock, q = _setup(); ex = _exec(); ex["started_at"] = "2026-09-05T09:00:00Z"; t("an execution record whose start differs from the candidates' start is refused", "more than 120 s" in (refused(m, s, c, cand, lock, q, ex=ex) or ""))
    m, s, c, cand, lock, q = _setup(); lock["harvester"]["tools_sha256"] = {}; t("a lock without tool hashes fails the typed lock contract", "tools_sha256" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); ex = _exec(); ex["extra"] = 1; t("an execution record with an unknown key fails its closed contract", "execution-record" in (refused(m, s, c, cand, lock, q, ex=ex) or ""))
    # split structure, partition and algorithm
    m, s, c, cand, lock, q = _setup(); comp_of(s, "doi:10.5555/w1")["work_ids"].append("doi:10.5555/w0"); _relock(lock, split=s); t("a work in two components is refused", "in two components" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); s["components"][1]["component_id"] = s["components"][0]["component_id"]; _relock(lock, split=s); t("a duplicate component id is refused", "duplicate component id" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); r = run(m, s, c, cand, lock, q); t("the baseline is a deterministic 70/30 component split following the declared algorithm (23 development, 10 holdout of 33)", r["reconciliation"]["development"] == 23 and r["denominators"]["E_eligible_holdout_works"] == 10)
    m, s, c, cand, lock, q = _setup(); s["components"][0]["allocation"] = "holdout" if s["components"][0]["allocation"] == "development" else "development"; _relock(lock, split=s)
    t("an allocation that departs from the declared algorithm is refused", "does not follow the declared algorithm" in (refused(m, s, c, cand, lock, q) or ""))
    # the missing miss: removing an actual miss from the split without any disposition, recomputing the allocation, is refused
    m, s, c, cand, lock, q = _setup(); miss = "doi:10.5555/w9"; s["components"] = [x for x in s["components"] if miss not in x["work_ids"]]; s = rebuild(s); _relock(lock, split=s); msg = refused(m, s, c, cand, lock, q) or ""
    t("removing an actual miss from the split with no exclusion, allocation recomputed, is refused as an incomplete partition (not_in_split cannot legitimise it)", "partition incomplete" in msg and miss in msg, msg[:300])
    s["excluded"].append({"work_id": miss, "category": "unresolved_allocation", "detail": "family membership under review; allocation deferred"}); _relock(lock, split=s); r = run(m, s, c, cand, lock, q)
    t("the same removal declared as an unresolved allocation evaluates provisionally with the work counted, never as a completed held-out result", r["state"] == "evaluated_provisional" and r["reconciliation"]["unresolved_allocation"] == 1 and r["unresolved_allocation"] == [miss] and r["denominators"]["E_eligible_holdout_works"] == 9)
    # the calibration component: two family-linked works in one component, the first disclosed as calibration and alone excluded
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["calibration_only"] = True; m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]
    c1 = comp_of(s, "doi:10.5555/w1"); s["components"].remove(c1); comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w1")
    comp_of(s, "doi:10.5555/w0")["work_ids"].remove("doi:10.5555/w0"); s["excluded"].append({"work_id": "doi:10.5555/w0", "category": "calibration", "detail": "disclosed worked example"}); s = rebuild(s); _relock(lock, manifest=m, split=s); msg = refused(m, s, c, cand, lock, q) or ""
    t("a calibration work's family sibling left in the split is refused: the whole family component is removed before allocation", "family component of a disclosed calibration work" in msg and "doi:10.5555/w1" in msg, msg[:300])
    s["components"] = [x for x in s["components"] if "doi:10.5555/w1" not in x["work_ids"]]; s["excluded"].append({"work_id": "doi:10.5555/w1", "category": "calibration", "detail": "same cohort as the disclosed example"}); s = rebuild(s); _relock(lock, split=s); r = run(m, s, c, cand, lock, q)
    t("with the whole calibration component excluded the run evaluates and counts both as calibration", r["reconciliation"]["calibration"] == 2 and r["denominators"]["E_eligible_holdout_works"] == 8)
    m, s, c, cand, lock, q = _setup(); s["components"] = [x for x in s["components"] if "doi:10.5555/w2" not in x["work_ids"]]; s["excluded"].append({"work_id": "doi:10.5555/w2", "category": "calibration", "detail": "claimed"}); s = rebuild(s); _relock(lock, split=s)
    t("an exclusion claiming calibration for a work that is not one (nor in a calibration family) is refused", "neither a disclosed calibration work" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); s["components"] = [x for x in s["components"] if "doi:10.5555/w2" not in x["work_ids"]]; s["excluded"].append({"work_id": "doi:10.5555/w2", "category": "exposed", "detail": "claimed"}); s = rebuild(s); _relock(lock, split=s)
    t("an exclusion claiming exposure that the lock does not record is refused", "the lock does not list it" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); s["excluded"].append({"work_id": "doi:10.5555/w2", "category": "seed", "detail": "x"}); _relock(lock, split=s)
    t("a work both excluded and allocated is refused", "both excluded and in component" in (refused(m, s, c, cand, lock, q) or ""))
    # unknown overlap: a disposition must name the component and the actual grouping
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["overlap_state"] = "unknown"; _relock(lock, manifest=m); t("unknown overlap allocated without a recorded disposition is refused", "unknown overlap" in (refused(m, s, c, cand, lock, q) or ""))
    cid0 = comp_of(s, "doi:10.5555/w0")["component_id"]
    s["unknown_overlap_dispositions"] = [{"work_id": "doi:10.5555/w0", "component_id": cid0, "grouped_with": ["doi:10.5555/w1"], "rationale": "possibly the same cohort as w1; grouped conservatively"}]; _relock(lock, split=s)
    t("a disposition whose stated grouping is not the component's actual membership is refused", "actual conservative grouping" in (refused(m, s, c, cand, lock, q) or ""))
    s["unknown_overlap_dispositions"] = [{"work_id": "doi:10.5555/w0", "component_id": cid0, "grouped_with": [], "rationale": "x"}]; _relock(lock, split=s)
    t("a disposition carrying only the work id (empty rationale) fails the typed split contract", "rationale" in (refused(m, s, c, cand, lock, q) or ""))
    s["unknown_overlap_dispositions"] = [{"work_id": "doi:10.5555/w0", "component_id": cid0, "grouped_with": [], "rationale": "no shared cohort could be established with any manifest work; kept as its own component"}]; _relock(lock, split=s)
    t("a disposition naming the component, the (empty) actual grouping and a rationale is accepted", refused(m, s, c, cand, lock, q) is None)
    # calendar validity and dates
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["publication_date"] = {"value": "2026-13-40", "precision": "day", "source_url": "x"}; _relock(lock, manifest=m)
    t("a malformed calendar date is refused by name, not by exception", "not a calendar date" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["publication_date"] = {"value": "2026-08", "precision": "day", "source_url": "x"}; _relock(lock, manifest=m)
    t("a value that does not match its declared precision is refused", "does not match precision" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"][0]["judged_at"] = "2026-09-03T00:00:00Z"; _relock(lock, manifest=m); t("a link judged before its source was accessed is refused", "judged before its source" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["state"] = "judged"; _relock(lock, manifest=m); t("an unlocked manifest (state judged) is refused", "locked" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"][0]["instrument_id"] = "not-an-instrument"; _relock(lock, manifest=m); t("a link naming an instrument absent from the query configuration is refused", "does not carry" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); r = run(m, s, c, cand, lock, q)
    t("breakdowns present: by property, route of hit, language and coverage by source", r["by_property"]["internal_consistency"]["eligible_work_links"] == 10 and r["by_route_of_hit"] == {"names": 7} and "unknown" in r["by_language"] and r["coverage_by_source"]["europepmc"]["indexed"] == 10)
    t("the in-memory fixture satisfies the same typed contracts as supplied inputs (no schema problems on the baseline)", not [x for kind, obj in (("manifest", m), ("split", s), ("coverage", c), ("candidates", cand), ("query-lock", lock)) for x in schema_problems(kind, obj)] and not schema_problems("execution-record", _exec()))
    # the committed public fixtures are exactly the generated ones, and the CLI runs them (valid) and refuses mutated copies (invalid)
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        gen = Path(tmp) / "gen"; write_fixtures(gen)
        same = all((gen / n).read_bytes() == (FIXTURES / n).read_bytes() for n in sorted(x.name for x in gen.iterdir()))
        t("the committed synthetic fixtures are byte-identical to the generator's output (regenerate with --write-fixtures)", same, [n.name for n in gen.iterdir() if not (FIXTURES / n.name).exists() or (gen / n.name).read_bytes() != (FIXTURES / n.name).read_bytes()])
        d = FIXTURES; out = Path(tmp) / "report.json"
        def cli(**over):
            args = {"manifest": d / "manifest.synthetic.json", "split": d / "split.synthetic.json", "coverage": d / "coverage.synthetic.json", "queries": d / "queries.synthetic.json", "candidates": d / "candidates.synthetic.json", "query-lock": d / "query-lock.synthetic.json", "execution-record": d / "execution-record.synthetic.json", "out": out}
            args.update(over)
            cmd = [sys.executable, str(ROOT / "tools" / "measure_recall.py")] + [x for k, v in args.items() for x in (f"--{k}", str(v))]
            return subprocess.run(cmd, capture_output=True, text=True)
        r_ = cli(); t("the CLI runs the synthetic public fixtures end to end (E=4, F=3) and writes only the supplied path", r_.returncode == 0 and out.exists() and "E=4 F=3" in r_.stdout, r_.stdout[-200:] + r_.stderr[-300:])
        r_ = cli(queries=d / "split.synthetic.json"); t("the CLI refuses a query file whose hash is not the locked one", r_.returncode != 0 and "query file hash" in (r_.stdout + r_.stderr))
        bad = Path(tmp) / "coverage.bad.json"; cv = json.loads((d / "coverage.synthetic.json").read_text()); cv["rows"][0]["checked_at"] = "not-a-date"; bad.write_text(json.dumps(cv))
        r_ = cli(coverage=bad); t("the CLI refuses an invalid coverage file with a named diagnostic and no traceback", r_.returncode != 0 and "coverage: rows/0/checked_at" in (r_.stdout + r_.stderr) and "Traceback" not in r_.stderr, r_.stderr[-300:])
        (Path(tmp) / "broken.json").write_text("{not json")
        r_ = cli(split=Path(tmp) / "broken.json"); t("the CLI refuses unparseable JSON with a named diagnostic and no traceback", r_.returncode != 0 and "not valid JSON" in (r_.stdout + r_.stderr) and "Traceback" not in r_.stderr, r_.stderr[-300:])
        r_ = cli(**{"execution-record": Path(tmp) / "absent.json"}); t("the CLI refuses a missing execution record path by name", r_.returncode != 0 and "cannot be read" in (r_.stdout + r_.stderr) and "Traceback" not in r_.stderr)
        r_ = subprocess.run([sys.executable, str(ROOT / "tools" / "measure_recall.py"), "--manifest", str(d / "manifest.synthetic.json")], capture_output=True, text=True)
        t("the CLI names every missing input path; there is no default", r_.returncode != 0 and "missing" in (r_.stdout + r_.stderr))
    print(f"{'all' if not failures else failures} evaluator probes {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


def main():
    ap = argparse.ArgumentParser()
    for k in ("manifest", "split", "coverage", "queries", "candidates", "query-lock", "execution-record", "out", "write-fixtures"): ap.add_argument(f"--{k}")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: return self_test()
    if a.write_fixtures: print("written:", write_fixtures(a.write_fixtures)); return
    # the enabled coverage sources come from the pinned query configuration's provider profile; there is no --sources argument
    need = [k for k in ("manifest", "split", "coverage", "queries", "candidates", "query_lock", "out") if not getattr(a, k)]
    if need: sys.exit(f"missing: {need}; every input path is explicit, there is no default")
    def load(path, what):
        try: return json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as e: sys.exit(f"{what}: {path} cannot be read ({e.strerror})")
        except json.JSONDecodeError as e: sys.exit(f"{what}: {path} is not valid JSON ({e.msg} at line {e.lineno})")
    try: qbytes = Path(a.queries).read_bytes()
    except OSError as e: sys.exit(f"queries: {a.queries} cannot be read ({e.strerror})")
    execution = load(a.execution_record, "execution-record") if a.execution_record else None
    rep = evaluate(load(a.manifest, "manifest"), load(a.split, "split"), load(a.coverage, "coverage"), load(a.candidates, "candidates"), load(a.query_lock, "query-lock"), sha(qbytes), load(a.queries, "queries"), execution)
    Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report written to {a.out}: E={rep['denominators']['E_eligible_holdout_works']} F={rep['denominators']['F_found']} recall={rep['work_level_recall']} ({rep['state']}; {rep['claim']})")


if __name__ == "__main__":
    main()
