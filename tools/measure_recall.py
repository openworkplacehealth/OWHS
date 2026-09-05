#!/usr/bin/env python3
"""Held-out known-item retrieval evaluation for the evidence harvester: correct accounting first, a number second.

    python tools/measure_recall.py --self-test
    python tools/measure_recall.py --manifest M --split S --coverage C --queries Q --candidates CAND --query-lock LOCK --out REPORT

Two quantities, kept apart. Coverage: which judged works the configured indexes contain (a lookup with identifiers supplied; never
discovery). Known-item retrieval: which judged-relevant holdout works the frozen discovery queries returned without being given
their identifiers. Let E be the eligible holdout works known to be inside the requested window (non-seed, non-calibration, not
previously exposed to tuning, with at least one eligible in-scope link); F the subset a legitimate discovery route returned; C the
subset of E demonstrated indexed by at least one enabled source at the coverage check. The report gives |F|/|E| with every miss
listed, |F and C|/|C| with failed and unknown coverage counted separately, work-level micro recall and macro recall over instruments
with a non-zero denominator (null and not_evaluated otherwise), per-property, route and source counts, and an exclusion
reconciliation that sums to the whole manifest. Unresolved relevance or boundary dates make the figure provisional, with counts;
they are never dropped from a denominator. A stale query, split or manifest hash against the lock stops the run. The evaluator reads
gold; the harvester never does. Output goes only to the supplied path; the self-test uses a temporary directory and no network.
"""
import argparse, copy, datetime, hashlib, json, re, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def sha(b): return hashlib.sha256(b).hexdigest()
def sha_obj(o): return sha(json.dumps(o, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def norm_doi(doi):
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    return d.lower() or None


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


DISCOVERY_ROUTES = {"names", "abbreviation", "cites", "new-instrument"}


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


def contract_problems(manifest, split, coverage, candidates, lock, queries):
    """Everything that must hold before any arithmetic: identities, judgements, split structure and algorithm, exposure propagation,
    candidate execution binding, coverage row shape. Returns a list of problems."""
    p = []
    rows = {r["work_id"]: r for r in manifest.get("rows", [])}
    if len(rows) != len(manifest.get("rows", [])): p.append("duplicate work ids in the manifest")
    if manifest.get("state") not in ("split_locked", "evaluated"): p.append(f"manifest state {manifest.get('state')!r}: judgements and split must be locked before evaluation")
    instruments = {r["instrument_id"] for r in queries.get("records", [])} | {r["instrument_id"] for r in queries.get("inherited_records", []) if isinstance(r, dict) and r.get("instrument_id")}
    props = {"structural_validity", "convergent_discriminant_validity", "criterion_validity_reference_standard", "criterion_validity_organisational", "internal_consistency", "test_retest_reliability", "measurement_invariance", "responsiveness_mic", "populations_languages_norms"}
    for w, r in rows.items():
        wid_norm = ("doi:" + norm_doi(w[4:])) if w.startswith("doi:") else w
        if wid_norm != w: p.append(f"{w}: work id is not canonical (lower-case DOI, no resolver prefix)")
        ids = r.get("identifiers") or {}
        if w.startswith("doi:") and norm_doi(ids.get("doi")) != w[4:]: p.append(f"{w}: identifiers.doi conflicts with the work id")
        for l in r.get("links", []):
            if l.get("scope") == "measurement_property":
                if l.get("instrument_id") not in instruments: p.append(f"{w}: link names instrument {l.get('instrument_id')!r} that the query configuration does not carry")
                if l.get("property") not in props: p.append(f"{w}: link names property {l.get('property')!r} that is not a registry property")
            if l.get("judgement") in ("eligible", "ineligible"):
                if not (l.get("reason") or "").strip(): p.append(f"{w}: a judged link needs a rationale")
                if (l.get("source_location") or {}).get("read_level") in (None, "metadata_only", "inaccessible"): p.append(f"{w}: a link judged {l['judgement']} needs a read source (full_text or abstract_only); metadata alone cannot judge relevance")
                if not l.get("judged_by") or l.get("judged_by") == "unjudged": p.append(f"{w}: a judged link needs an attributed judge")
        if r.get("overlap_state") == "resolved" and not r.get("study_families"): p.append(f"{w}: overlap resolved but no study family recorded")
    # split: unique membership, component exclusion propagation, connected-family allocation, deterministic algorithm
    seen = {}
    for comp in split.get("components", []):
        if comp.get("allocation") not in ("development", "holdout"): p.append(f"component {comp.get('component_id')}: allocation must be development or holdout")
        for w in comp.get("work_ids", []):
            if w in seen: p.append(f"{w}: in two components ({seen[w]} and {comp.get('component_id')})")
            seen[w] = comp.get("component_id")
    fam_comp = {}
    for comp in split.get("components", []):
        for w in comp.get("work_ids", []):
            for fam in (rows.get(w) or {}).get("study_families", []):
                fam_comp.setdefault(fam, set()).add(comp.get("component_id"))
    for fam, comps in fam_comp.items():
        if len(comps) > 1: p.append(f"study family {fam!r} spans components {sorted(comps)}: a linked family cannot cross the split boundary")
    for w in rows:
        if rows[w].get("overlap_state") == "unknown" and w in seen and not any(x.get("work_id") == w for x in split.get("unknown_overlap_dispositions", [])): p.append(f"{w}: unknown overlap allocated without a recorded disposition")
    excluded_ids = {e.get("work_id") for e in split.get("excluded", [])}
    seeds = seeds_from_queries(queries)
    for w in rows:
        if (seeds & work_ids(rows[w]) or rows[w].get("seed_membership")) and w not in excluded_ids: p.append(f"{w}: a seed work is not in the split's exclusion list")
        if rows[w].get("calibration_only") and w not in excluded_ids: p.append(f"{w}: a calibration work is not in the split's exclusion list")
    if split.get("algorithm") != "sort component ids by sha256('owhs-recall-v1|' + component_id); floor(0.70*N) development, remainder holdout":
        p.append("split does not declare the designed deterministic algorithm")
    else:
        comps = sorted(split.get("components", []), key=lambda c: hashlib.sha256(f"owhs-recall-v1|{c['component_id']}".encode()).hexdigest())
        n_dev = int(0.70 * len(comps)) if comps else 0
        want = {c["component_id"]: ("development" if i < n_dev else "holdout") for i, c in enumerate(comps)}
        bad = [c["component_id"] for c in comps if c.get("allocation") != want[c["component_id"]]]
        if bad: p.append(f"split allocation does not follow the declared algorithm for components {bad[:5]}")
    # exposure propagates to the whole component
    exposed = set(lock.get("exposed_work_ids", []))
    for comp in split.get("components", []):
        if exposed & set(comp.get("work_ids", [])) and not set(comp.get("work_ids", [])) <= exposed: p.append(f"component {comp.get('component_id')}: exposure of one work must exclude the whole component (siblings share the leak)")
    # candidate artefact bound to its execution
    ex = candidates.get("execution") or {}
    if ex.get("query_sha256") != lock.get("query_sha256"): p.append("candidates were not produced by the locked query file (execution query hash differs)")
    rw = ex.get("requested_window") or {}
    if (rw.get("from"), rw.get("to")) != (lock.get("run_window", {}).get("from"), lock.get("run_window", {}).get("to")): p.append("candidates were produced over a different window than the lock's run window")
    if not ex.get("harvester_version") or not ex.get("run_id"): p.append("candidates carry no harvester version or run id")
    for c in candidates.get("candidates", []):
        routes = c.get("routes")
        if not isinstance(routes, list) or not routes: p.append(f"candidate {c.get('doi') or c.get('pmid') or '?'} has no discovery provenance (routes)"); continue
        unknown = set(routes) - DISCOVERY_ROUTES - {"identifier_lookup"}
        if unknown: p.append(f"candidate {c.get('doi') or '?'}: unrecognised route(s) {sorted(unknown)}")
    # coverage rows: shape, duplicates, sources within the profile
    prof = set(sources_from_queries(queries))
    seen_cov = set()
    for row in coverage.get("rows", []):
        k = (row.get("work_id"), row.get("source_id"))
        if k in seen_cov: p.append(f"coverage: duplicate row for {k}")
        seen_cov.add(k)
        if row.get("source_id") not in prof: p.append(f"coverage: source {row.get('source_id')!r} is not in the configured provider profile; it cannot manufacture C")
        if row.get("status") not in ("indexed", "not_indexed", "failed", "unsupported", "unresolved"): p.append(f"coverage: {k} status {row.get('status')!r}")
        for f in ("checked_at", "lookup_method", "response_sha256"):
            if not row.get(f): p.append(f"coverage: {k} lacks {f}")
    return p


def evaluate(manifest, split, coverage, candidates, lock, queries_sha, queries, enabled_sources=None):
    """Accounting after the contracts hold. Returns the report dict; raises SystemExit on a stale lock or a contract failure."""
    problems = []
    if lock["query_sha256"] != queries_sha: problems.append("query file hash differs from the lock")
    if lock["manifest_sha256"] != sha_obj(manifest): problems.append("manifest hash differs from the lock")
    if lock["split_sha256"] != sha_obj(split): problems.append("split hash differs from the lock")
    if problems: raise SystemExit("stale inputs against the query lock: " + "; ".join(problems))
    cp = contract_problems(manifest, split, coverage, candidates, lock, queries)
    if cp: raise SystemExit("contract problems, nothing measured:\n  " + "\n  ".join(cp[:30]))
    enabled_sources = sources_from_queries(queries)          # the configured profile, never an unconstrained argument
    win = lock["run_window"]
    rows = {r["work_id"]: r for r in manifest["rows"]}
    component_of = {}
    for comp in split["components"]:
        for w in comp["work_ids"]: component_of[w] = comp
    holdout = {w for w, c in component_of.items() if c["allocation"] == "holdout"}
    excluded = {e["work_id"]: e["reason"] for e in split.get("excluded", [])}
    exposed = set(lock.get("exposed_work_ids", []))
    seeds = seeds_from_queries(queries)
    # candidates found by a legitimate discovery route (a seed's own record retrieved by an identifier lookup is not discovery)
    found_ids, found_routes = set(), {}
    for c in candidates.get("candidates", []):
        routes = set(c.get("routes", []))
        disc = routes & DISCOVERY_ROUTES
        if not disc: continue
        for i in candidate_ids(c): found_ids.add(i); found_routes.setdefault(i, set()).update(disc)
    recon = {"manifest_total": len(rows), "seed": 0, "calibration": 0, "exposed": 0, "development": 0, "not_in_split": 0, "out_of_window": 0, "date_unresolved": 0, "no_eligible_link": 0, "relevance_unresolved": 0, "eligible_holdout": 0}
    E, unresolved_rel, misses, hits = [], [], [], []
    for w, r in rows.items():
        if (seeds & work_ids(r)) or r.get("seed_membership") or excluded.get(w, "").startswith("seed"): recon["seed"] += 1; continue
        if r.get("calibration_only") or excluded.get(w, "").startswith("calibration"): recon["calibration"] += 1; continue
        if w in exposed: recon["exposed"] += 1; continue
        if w not in component_of: recon["not_in_split"] += 1; continue
        if w not in holdout: recon["development"] += 1; continue
        links = [l for l in r.get("links", []) if l.get("scope") == "measurement_property"]
        if any(l.get("judgement") == "unresolved" for l in links) and not any(l.get("judgement") == "eligible" for l in links):
            recon["relevance_unresolved"] += 1; unresolved_rel.append(w); continue
        if not any(l.get("judgement") == "eligible" for l in links): recon["no_eligible_link"] += 1; continue
        dw = date_in_window(r.get("publication_date"), win["from"], win["to"])
        if dw == "out": recon["out_of_window"] += 1; continue
        if dw == "unresolved": recon["date_unresolved"] += 1; continue
        recon["eligible_holdout"] += 1; E.append(w)
        (hits if work_ids(r) & found_ids else misses).append(w)
    assert sum(v for k, v in recon.items() if k != "manifest_total") == recon["manifest_total"], "reconciliation does not sum to the manifest"
    # coverage: indexed by any enabled source at the coverage check; failed/unsupported/unresolved counted, never read as not indexed
    cov = {}
    for row in coverage.get("rows", []):
        cov.setdefault(row["work_id"], {})[row["source_id"]] = row["status"]
    C = [w for w in E if any(cov.get(w, {}).get(s) == "indexed" for s in enabled_sources)]
    # policy: a work is 'known not indexed' only when EVERY enabled source answered not_indexed; any failed, unresolved, unsupported or
    # missing source answer leaves its coverage unknown, even beside another source's negative answer
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
            if l.get("scope") == "measurement_property" and l.get("judgement") == "eligible":
                per_instrument.setdefault(l["instrument_id"], {"eligible_links": set(), "found_links": set()})
                per_instrument[l["instrument_id"]]["eligible_links"].add((w, l["property"]))
                if w in hits: per_instrument[l["instrument_id"]]["found_links"].add((w, l["property"]))
    inst = {k: {"eligible_work_links": len(v["eligible_links"]), "found_work_links": len(v["found_links"]), "recall": ratio(len(v["found_links"]), len(v["eligible_links"])), "state": "evaluated" if v["eligible_links"] else "not_evaluated"} for k, v in per_instrument.items()}
    for iid in lock.get("instrument_ids", []):
        inst.setdefault(iid, {"eligible_work_links": 0, "found_work_links": 0, "recall": None, "state": "not_evaluated"})
    per_property, per_route, per_language = {}, {}, {}
    for w in E:
        r = rows[w]; hit = w in hits
        lang = (r.get("citation") or {}).get("language") or "unknown"
        per_language.setdefault(lang, {"eligible_works": 0, "found": 0}); per_language[lang]["eligible_works"] += 1; per_language[lang]["found"] += hit
        for l in r["links"]:
            if l.get("scope") == "measurement_property" and l.get("judgement") == "eligible":
                per_property.setdefault(l["property"], {"eligible_work_links": 0, "found_work_links": 0, "miss_ids": []})
                per_property[l["property"]]["eligible_work_links"] += 1
                if hit: per_property[l["property"]]["found_work_links"] += 1
                else: per_property[l["property"]]["miss_ids"].append(w)
        if hit:
            for rt in set().union(*(found_routes.get(i, set()) for i in work_ids(r))): per_route[rt] = per_route.get(rt, 0) + 1
    for v in per_property.values(): v["recall"] = ratio(v["found_work_links"], v["eligible_work_links"])
    for v in per_language.values(): v["recall"] = ratio(v["found"], v["eligible_works"])
    unresolved_links = {w: [f"{l['instrument_id']}.{l['property']}" for l in rows[w]["links"] if l.get("scope") == "measurement_property" and l.get("judgement") == "unresolved"] for w in E if any(l.get("judgement") == "unresolved" for l in rows[w]["links"])}
    non_gold = sorted(found_ids - {i for w in rows for i in work_ids(rows[w])})
    macro_vals = [v["recall"] for v in inst.values() if v["recall"] is not None]
    provisional = bool(unresolved_rel or recon["date_unresolved"] or unresolved_links)
    return {"schema_version": "1.0", "state": "evaluated" if not provisional else "evaluated_provisional",
            "window": win, "denominators": {"E_eligible_holdout_works": len(E), "F_found": len(hits), "C_indexed_by_an_enabled_source": len(C), "F_and_C": len([w for w in hits if w in C]),
                                            "coverage_failed_or_unresolved": len(cov_failed), "coverage_unknown": len(cov_unknown)},
            "work_level_recall": ratio(len(hits), len(E)), "work_level_recall_state": "evaluated" if E else "not_evaluated",
            "conditional_recall_given_indexed": ratio(len([w for w in hits if w in C]), len(C)), "conditional_state": "evaluated" if C else "not_evaluated",
            "hits_absent_from_coverage_snapshot": hits_not_in_C,
            "macro_recall_over_instruments": (round(sum(macro_vals) / len(macro_vals), 4) if macro_vals else None), "instruments": dict(sorted(inst.items())),
            "misses": sorted(misses), "hits": sorted(hits), "provisional": provisional, "unresolved_relevance": sorted(unresolved_rel),
            "unresolved_links_on_eligible_works": unresolved_links,
            "by_property": dict(sorted(per_property.items())), "by_route_of_hit": dict(sorted(per_route.items())), "by_language": dict(sorted(per_language.items())),
            "coverage_by_source": per_source, "coverage_state_counts": {k: sum(1 for v in cov_state.values() if v == k) for k in ("indexed", "not_indexed", "failed_or_unresolved", "unknown")},
            "reconciliation": recon, "candidates_not_in_gold_count": len(non_gold), "candidates_not_in_gold": non_gold,
            "note": "A work is counted once however many instruments it serves; by-instrument rows count distinct work-link pairs and are not independent studies. A hit absent from the coverage snapshot stays in F and is listed. No recall threshold means complete; every miss relevant to a High cell needs written review before any public claim."}


# ---------- fixtures ----------

ALGO = "sort component ids by sha256('owhs-recall-v1|' + component_id); floor(0.70*N) development, remainder holdout"


def _row(wid, inst_links, date=("2026-08-15", "day"), calib=False, ids=None, read="abstract_only", judged_by="fixture-judge", families=None):
    return {"work_id": wid, "identifiers": ids or {"doi": wid[4:] if wid.startswith("doi:") else None, "pmid": None, "openalex_id": None},
            "citation": {"title": f"Title {wid}", "authors": ["A"], "year": 2026, "source_url": "https://example.org"},
            "publication_date": {"value": date[0], "precision": date[1], "source_url": "https://example.org"},
            "record_type": "primary_study", "calibration_only": calib, "overlap_state": "resolved", "study_families": families if families is not None else [f"fam-{wid}"], "seed_membership": [],
            "links": [{"instrument_id": i, "property": pr, "form": None, "scope": "measurement_property", "judgement": j, "reason": "fixture rationale" if j != "unresolved" else "",
                       "source_location": {"url": "https://example.org", "read_level": read, "section": None, "printed_pages": None, "table_or_figure": None, "accessed_at": "2026-09-05T00:00:00Z", "response_status": 200},
                       "judged_by": judged_by if j != "unresolved" else "unjudged", "judged_at": "2026-09-05T00:00:00Z"} for i, pr, j in inst_links],
            "judgements": [], "unresolved": []}


def _queries(seed_dois=()):
    return {"version": "fixture", "providers": {"europepmc": {}, "openalex": {}}, "property_terms": ["validation"],
            "records": [{"instrument_id": "isi", "names": ["Insomnia Severity Index"], "citation_seeds": [{"doi": d, "openalex_id": None} for d in seed_dois]}, {"instrument_id": "who-5", "names": ["WHO-5"], "citation_seeds": []}]}


def _split(rows, excluded_ids=(), reasons=None, allocation=None, components=None):
    comps = components if components is not None else [{"component_id": f"c-{r['work_id']}", "work_ids": [r["work_id"]]} for r in rows if r["work_id"] not in excluded_ids]
    order = sorted(comps, key=lambda c: hashlib.sha256(f"owhs-recall-v1|{c['component_id']}".encode()).hexdigest())
    n_dev = int(0.70 * len(order))
    for i, c in enumerate(order): c["allocation"] = (allocation or {}).get(c["component_id"], "development" if i < n_dev else "holdout")
    return {"algorithm": ALGO, "components": comps, "excluded": [{"work_id": w, "reason": (reasons or {}).get(w, "seed: query citation seed")} for w in excluded_ids], "unknown_overlap_dispositions": []}


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
    split = _split(rows + fillers, excluded_ids=excluded, components=comps)
    manifest = {"schema_version": "1.0", "benchmark_id": "fx", "state": "split_locked", "rows": rows + fillers}
    queries = _queries(seeds); qsha = sha_obj(queries)
    lock = {"query_sha256": qsha, "manifest_sha256": sha_obj(manifest), "split_sha256": sha_obj(split), "run_window": {"from": "2026-08-01", "to": "2026-09-05"}, "exposed_work_ids": [], "instrument_ids": ["isi", "who-5"]}
    cands = {"execution": {"query_sha256": qsha, "requested_window": {"from": "2026-08-01", "to": "2026-09-05"}, "harvester_version": "tools/harvest.py fixture", "run_id": "fx-run"},
             "candidates": [{"doi": f"10.5555/w{i}", "routes": ["names"]} for i in range(n_found)]}
    cov = {"rows": [{"work_id": r["work_id"], "source_id": src, "status": "indexed", "checked_at": "2026-09-05T00:00:00Z", "lookup_method": "fixture", "response_sha256": "0" * 64} for r in rows for src in ("europepmc", "openalex")]}
    return manifest, split, cov, cands, lock, queries


def _relock(lock, manifest=None, split=None, queries=None):
    if manifest is not None: lock["manifest_sha256"] = sha_obj(manifest)
    if split is not None: lock["split_sha256"] = sha_obj(split)
    if queries is not None: lock["query_sha256"] = sha_obj(queries)
    return lock


def self_test():
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else detail); failures += not ok
    def run(m, s, c, cand, lock, q): return evaluate(m, s, c, cand, lock, lock["query_sha256"], q)
    def refused(m, s, c, cand, lock, q):
        try: evaluate(m, s, c, cand, lock, lock["query_sha256"], q); return None
        except SystemExit as e: return str(e)
    # the fixture forces holdout allocation; the algorithm probe below uses the real algorithm
    def comp_of(split, wid): return next(x for x in split["components"] if wid in x["work_ids"])
    m, s, c, cand, lock, q = _setup(); r = run(m, s, c, cand, lock, q)
    t("10 eligible with 7 found gives 7/10", r["denominators"]["E_eligible_holdout_works"] == 10 and r["work_level_recall"] == 0.7 and len(r["misses"]) == 3)
    m, s, c, cand, lock, q = _setup(10, 3)
    c = {"rows": [{**row, "status": ("indexed" if int(row["work_id"][-1]) < 4 else "not_indexed")} for row in c["rows"]]}
    r = run(m, s, c, cand, lock, q); t("10 eligible, 4 known indexed, 3 found gives 3/10 and 3/4", r["work_level_recall"] == 0.3 and r["conditional_recall_given_indexed"] == 0.75)
    m, s, c, cand, lock, q = _setup(seeds=("10.5555/w0",)); r = run(m, s, c, cand, lock, q)
    t("a seed (from the pinned query file) retrieved is excluded from numerator and denominator", r["denominators"]["E_eligible_holdout_works"] == 9 and r["denominators"]["F_found"] == 6 and r["reconciliation"]["seed"] == 1)
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["seed_membership"] = ["isi:seed"]; _relock(lock, manifest=m)
    t("a row marked seed that the split does not exclude is a contract failure, not a silently evaluated run", "not in the split's exclusion list" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"].append({**m["rows"][0]["links"][0], "instrument_id": "who-5"}); _relock(lock, manifest=m)
    r = run(m, s, c, cand, lock, q); t("one work linked to two instruments is counted once at work level and appears in both instrument rows", r["denominators"]["E_eligible_holdout_works"] == 10 and r["instruments"]["who-5"]["eligible_work_links"] == 1 and r["instruments"]["isi"]["eligible_work_links"] == 10)
    # shared cohort: same family across two components is refused; in one component moves together
    m, s, c, cand, lock, q = _setup(); m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]; _relock(lock, manifest=m)
    t("two publications sharing a family allocated to different components are refused", "cannot cross the split boundary" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]
    # w1 joins w0's component; both then sit in that component's allocation (holdout here), and the split still follows the algorithm
    c1 = comp_of(s, "doi:10.5555/w1"); s["components"].remove(c1); comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w1")
    s = _split(m["rows"], components=[{"component_id": x["component_id"], "work_ids": x["work_ids"]} for x in s["components"]]); _relock(lock, manifest=m, split=s)
    r = run(m, s, c, cand, lock, q); t("a shared cohort in one component moves together (both in one allocation; the split still follows the algorithm)", comp_of(s, "doi:10.5555/w0")["allocation"] == comp_of(s, "doi:10.5555/w1")["allocation"] and r["denominators"]["E_eligible_holdout_works"] + r["reconciliation"]["development"] + r["reconciliation"]["out_of_window"] == 33)
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["publication_date"] = {"value": "2026", "precision": "year", "source_url": "x"}; m["rows"][1]["publication_date"] = {"value": "2025", "precision": "year", "source_url": "x"}; m["rows"][2]["publication_date"] = {"value": None, "precision": "unknown", "source_url": "x"}; _relock(lock, manifest=m)
    r = run(m, s, c, cand, lock, q); t("a year-only date straddling the window is unresolved, one wholly outside is out, an unknown date is unresolved; the figure is provisional", r["reconciliation"]["date_unresolved"] == 2 and r["reconciliation"]["out_of_window"] == 1 and r["provisional"] is True)
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"][0].update({"judgement": "unresolved", "reason": "", "judged_by": "unjudged"}); _relock(lock, manifest=m)
    r = run(m, s, c, cand, lock, q); t("unresolved relevance is counted and reported, not dropped, and makes the figure provisional", r["reconciliation"]["relevance_unresolved"] == 1 and r["unresolved_relevance"] == ["doi:10.5555/w0"] and r["provisional"])
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["abstract"] = ""; r = run(m, s, c, cand, lock, q); t("an eligible hit with no abstract still counts as found", "doi:10.5555/w0" in r["hits"])
    m, s, c, cand, lock, q = _setup(); cand["candidates"].append({"doi": "10.9999/not-gold", "routes": ["names"]}); r = run(m, s, c, cand, lock, q)
    t("a candidate not in gold is listed in full with a count and does not change recall", r["candidates_not_in_gold"] == ["doi:10.9999/not-gold"] and r["candidates_not_in_gold_count"] == 1 and r["work_level_recall"] == 0.7)
    m, s, c, cand, lock, q = _setup(0, 0); r = run(m, s, c, cand, lock, q)
    t("an all-zero denominator yields metric null and state not_evaluated, never 100%", r["work_level_recall"] is None and r["work_level_recall_state"] == "not_evaluated" and r["instruments"]["isi"]["recall"] is None)
    m, s, c, cand, lock, q = _setup(); lock["query_sha256"] = "z" * 64
    try: evaluate(m, s, c, cand, lock, sha_obj(q), q); t("a stale query hash stops the run", False)
    except SystemExit as e: t("a stale query hash stops the run", "query file hash" in str(e))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["unresolved"] = ["x"]; t("a stale manifest hash stops the run", "manifest hash" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(10, 3); c = {"rows": [{**row, "status": "failed"} for row in c["rows"]]}; r = run(m, s, c, cand, lock, q)
    t("a failed coverage lookup is not read as not indexed: conditional recall not evaluated, failures counted", r["conditional_state"] == "not_evaluated" and r["denominators"]["coverage_failed_or_unresolved"] == 10)
    # exposure propagates to the component
    m, s, c, cand, lock, q = _setup(); lock["exposed_work_ids"] = ["doi:10.5555/w0"]; r = run(m, s, c, cand, lock, q)
    t("an exposed holdout work is excluded and counted as exposure", r["reconciliation"]["exposed"] == 1 and r["denominators"]["E_eligible_holdout_works"] == 9)
    m, s, c, cand, lock, q = _setup(); c1 = comp_of(s, "doi:10.5555/w1"); s["components"].remove(c1); comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w1")
    m["rows"][1]["study_families"] = ["fam-doi:10.5555/w0"]; s = _split(m["rows"], components=[{"component_id": x["component_id"], "work_ids": x["work_ids"]} for x in s["components"]]); _relock(lock, manifest=m, split=s); lock["exposed_work_ids"] = ["doi:10.5555/w0"]
    t("exposure of one work in a two-work component without its sibling is refused", "exclude the whole component" in (refused(m, s, c, cand, lock, q) or ""))
    lock["exposed_work_ids"] = ["doi:10.5555/w0", "doi:10.5555/w1"]; r = run(m, s, c, cand, lock, q); t("exposure declared for the whole component excludes both", r["reconciliation"]["exposed"] == 2)
    m, s, c, cand, lock, q = _setup(); m["rows"][1]["citation"]["title"] = m["rows"][0]["citation"]["title"]; _relock(lock, manifest=m); cand["candidates"] = [{"doi": "10.5555/w0", "title": "Title doi:10.5555/w0", "routes": ["names"]}]
    r = run(m, s, c, cand, lock, q); t("a title collision with a different DOI does not count the second work as found", r["hits"] == ["doi:10.5555/w0"])
    m, s, c, cand, lock, q = _setup(); m["rows"].append(_row("doi:10.5555/w0corr", [("isi", "internal_consistency", "eligible")])); m["rows"][-1]["record_type"] = "correction"
    comp_of(s, "doi:10.5555/w0")["work_ids"].append("doi:10.5555/w0corr"); m["rows"][-1]["study_families"] = ["fam-doi:10.5555/w0"]; _relock(lock, manifest=m, split=s)
    r = run(m, s, c, cand, lock, q); t("a correction notice is a distinct work from its original and is a separate miss when not retrieved", "doi:10.5555/w0corr" in r["misses"] and "doi:10.5555/w0" in r["hits"])
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["identifiers"]["doi"] = "10.1027//1015-5759.19.1.12"; m["rows"][0]["work_id"] = "doi:10.1027//1015-5759.19.1.12"; comp_of(s, "doi:10.5555/w0")["work_ids"] = ["doi:10.1027//1015-5759.19.1.12"]
    for row in c["rows"]:
        if row["work_id"] == "doi:10.5555/w0": row["work_id"] = "doi:10.1027//1015-5759.19.1.12"
    _relock(lock, manifest=m, split=s)
    cand["candidates"][0] = {"doi": "HTTPS://DOI.ORG/10.1027//1015-5759.19.1.12", "routes": ["names"]}; r = run(m, s, c, cand, lock, q)
    t("duplicate casing and the OLBI double slash canonicalise to the same identity", "doi:10.1027//1015-5759.19.1.12" in r["hits"])
    # routes: identifier lookup, missing routes, unrecognised route
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["routes"] = ["identifier_lookup"]; r = run(m, s, c, cand, lock, q); t("an identifier lookup is not discovery", "doi:10.5555/w0" in r["misses"])
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["routes"] = []; t("a candidate with no routes (no discovery provenance) is a contract failure", "no discovery provenance" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); cand["candidates"][0]["routes"] = ["identifier_lookup", "unrecognised_route"]; t("an unrecognised route string is a contract failure and cannot convert a lookup into discovery", "unrecognised route" in (refused(m, s, c, cand, lock, q) or ""))
    # judgement needs reading
    m, s, c, cand, lock, q = _setup(); 
    for r_ in m["rows"]: r_["links"][0]["source_location"]["read_level"] = "metadata_only"
    _relock(lock, manifest=m); t("eligible links judged from metadata only are a contract failure: relevance needs a read source", "metadata alone" in (refused(m, s, c, cand, lock, q) or ""))
    # coverage policy: negative from one source with the other missing is unknown, not not_indexed
    m, s, c, cand, lock, q = _setup(10, 3); c = {"rows": [{**row, "status": "not_indexed"} for row in c["rows"] if row["source_id"] == "europepmc"]}; r = run(m, s, c, cand, lock, q)
    t("Europe PMC not_indexed with OpenAlex rows absent leaves coverage unknown for every work; C is 0 and F/E is untouched", r["denominators"]["C_indexed_by_an_enabled_source"] == 0 and r["denominators"]["coverage_unknown"] == 10 and r["coverage_by_source"]["openalex"]["missing"] == 10 and r["work_level_recall"] == 0.3)
    m, s, c, cand, lock, q = _setup(); c["rows"].append({"work_id": "doi:10.5555/w0", "source_id": "crossref-not-in-profile", "status": "indexed", "checked_at": "x", "lookup_method": "x", "response_sha256": "0" * 64})
    t("a coverage source outside the configured profile cannot manufacture C", "cannot manufacture C" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); c["rows"].append(dict(c["rows"][0])); t("duplicate coverage rows are refused", "duplicate row" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(10, 7); c = {"rows": [row for row in c["rows"] if row["work_id"] != "doi:10.5555/w0"]}
    r = run(m, s, c, cand, lock, q); t("a hit absent from the coverage snapshot stays in F and is listed; C is not rewritten", r["denominators"]["F_found"] == 7 and r["hits_absent_from_coverage_snapshot"] == ["doi:10.5555/w0"] and r["denominators"]["C_indexed_by_an_enabled_source"] == 9)
    # execution binding
    m, s, c, cand, lock, q = _setup(); cand["execution"]["query_sha256"] = "y" * 64; t("candidates produced by another query file are refused even with today's matching query supplied", "not produced by the locked query file" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); cand["execution"]["requested_window"] = {"from": "2026-01-01", "to": "2026-03-31"}; t("candidates produced over another window are refused", "different window" in (refused(m, s, c, cand, lock, q) or ""))
    # split structure and algorithm
    m, s, c, cand, lock, q = _setup(); comp_of(s, "doi:10.5555/w1")["work_ids"].append("doi:10.5555/w0"); _relock(lock, split=s); t("a work in two components is refused", "in two components" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); r = run(m, s, c, cand, lock, q); t("the baseline is a deterministic 70/30 component split following the declared algorithm (23 development, 10 holdout of 33)", r["reconciliation"]["development"] == 23 and r["denominators"]["E_eligible_holdout_works"] == 10)
    m, s, c, cand, lock, q = _setup(); s["components"][0]["allocation"] = "holdout" if s["components"][0]["allocation"] == "development" else "development"; _relock(lock, split=s)
    t("an allocation that departs from the declared algorithm is refused", "does not follow the declared algorithm" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["overlap_state"] = "unknown"; _relock(lock, manifest=m); t("unknown overlap allocated without a recorded disposition is refused", "unknown overlap" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["publication_date"] = {"value": "2026-13-40", "precision": "day", "source_url": "x"}; _relock(lock, manifest=m)
    try: run(m, s, c, cand, lock, q); t("a malformed calendar date is refused", False)
    except (SystemExit, ValueError): t("a malformed calendar date is refused", True)
    m, s, c, cand, lock, q = _setup(); m["state"] = "judged"; _relock(lock, manifest=m); t("an unlocked manifest (state judged) is refused", "locked" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); m["rows"][0]["links"][0]["instrument_id"] = "not-an-instrument"; _relock(lock, manifest=m); t("a link naming an instrument absent from the query configuration is refused", "does not carry" in (refused(m, s, c, cand, lock, q) or ""))
    m, s, c, cand, lock, q = _setup(); r = run(m, s, c, cand, lock, q)
    t("breakdowns present: by property, route of hit, language and coverage by source", r["by_property"]["internal_consistency"]["eligible_work_links"] == 10 and r["by_route_of_hit"] == {"names": 7} and "unknown" in r["by_language"] and r["coverage_by_source"]["europepmc"]["indexed"] == 10)
    # the CLI itself, on the synthetic public fixtures
    with tempfile.TemporaryDirectory() as tmp:
        d = ROOT / "evidence" / "evaluation-tests"; out = Path(tmp) / "report.json"
        import subprocess
        r_ = subprocess.run([sys.executable, str(ROOT / "tools" / "measure_recall.py"), "--manifest", str(d / "manifest.synthetic.json"), "--split", str(d / "split.synthetic.json"), "--coverage", str(d / "coverage.synthetic.json"), "--queries", str(d / "queries.synthetic.json"), "--candidates", str(d / "candidates.synthetic.json"), "--query-lock", str(d / "query-lock.synthetic.json"), "--out", str(out)], capture_output=True, text=True)
        t("the CLI runs the synthetic public fixtures end to end and writes only the supplied path", r_.returncode == 0 and out.exists(), r_.stdout[-200:] + r_.stderr[-300:])
        r_ = subprocess.run([sys.executable, str(ROOT / "tools" / "measure_recall.py"), "--manifest", str(d / "manifest.synthetic.json"), "--split", str(d / "split.synthetic.json"), "--coverage", str(d / "coverage.synthetic.json"), "--queries", str(d / "manifest.schema.json"), "--candidates", str(d / "candidates.synthetic.json"), "--query-lock", str(d / "query-lock.synthetic.json"), "--out", str(Path(tmp) / "r2.json")], capture_output=True, text=True)
        t("the CLI refuses a query file whose hash is not the locked one", r_.returncode != 0 and "query file hash" in (r_.stdout + r_.stderr))
    print(f"{'all' if not failures else failures} evaluator probes {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


def main():
    ap = argparse.ArgumentParser()
    for k in ("manifest", "split", "coverage", "queries", "candidates", "query-lock", "out"): ap.add_argument(f"--{k}")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: return self_test()
    # the enabled coverage sources come from the pinned query configuration's provider profile; there is no --sources argument
    need = [k for k in ("manifest", "split", "coverage", "queries", "candidates", "query_lock", "out") if not getattr(a, k)]
    if need: sys.exit(f"missing: {need}; every input path is explicit, there is no default")
    L = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    rep = evaluate(L(a.manifest), L(a.split), L(a.coverage), L(a.candidates), L(a.query_lock), sha(Path(a.queries).read_bytes()), L(a.queries))
    Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report written to {a.out}: E={rep['denominators']['E_eligible_holdout_works']} F={rep['denominators']['F_found']} recall={rep['work_level_recall']} ({rep['state']})")


if __name__ == "__main__":
    main()
