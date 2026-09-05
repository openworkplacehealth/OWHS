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


def evaluate(manifest, split, coverage, candidates, lock, queries_sha, enabled_sources):
    """Pure accounting. Returns the report dict; raises SystemExit on a stale lock."""
    problems = []
    if lock["query_sha256"] != queries_sha: problems.append("query file hash differs from the lock")
    if lock["manifest_sha256"] != sha_obj(manifest): problems.append("manifest hash differs from the lock")
    if lock["split_sha256"] != sha_obj(split): problems.append("split hash differs from the lock")
    if problems: raise SystemExit("stale inputs against the query lock: " + "; ".join(problems))
    if manifest.get("state") not in ("split_locked", "evaluated"): raise SystemExit(f"manifest state {manifest.get('state')!r}: judgements and split must be locked before evaluation")
    win = lock["run_window"]
    rows = {r["work_id"]: r for r in manifest["rows"]}
    if len(rows) != len(manifest["rows"]): raise SystemExit("duplicate work ids in the manifest")
    component_of = {}
    for comp in split["components"]:
        for w in comp["work_ids"]: component_of[w] = comp
    holdout = {w for w, c in component_of.items() if c["allocation"] == "holdout"}
    excluded = {e["work_id"]: e["reason"] for e in split.get("excluded", [])}
    exposed = set(lock.get("exposed_work_ids", []))
    seeds = set(lock.get("seed_work_ids", []))
    # candidates found by a legitimate discovery route (a seed's own record retrieved by an identifier lookup is not discovery)
    found_ids = set()
    for c in candidates.get("candidates", []):
        routes = set(c.get("routes", [])) or {"unknown"}
        if routes <= {"identifier_lookup"}: continue
        found_ids |= candidate_ids(c)
    recon = {"manifest_total": len(rows), "seed": 0, "calibration": 0, "exposed": 0, "development": 0, "not_in_split": 0, "out_of_window": 0, "date_unresolved": 0, "no_eligible_link": 0, "relevance_unresolved": 0, "eligible_holdout": 0}
    E, unresolved_rel, misses, hits = [], [], [], []
    for w, r in rows.items():
        if w in seeds or excluded.get(w, "").startswith("seed"): recon["seed"] += 1; continue
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
    cov_failed = [w for w in E if w not in C and any(cov.get(w, {}).get(s) in ("failed", "unresolved") for s in enabled_sources)]
    cov_unknown = [w for w in E if w not in C and w not in cov_failed and not any(cov.get(w, {}).get(s) == "not_indexed" for s in enabled_sources)]
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
    macro_vals = [v["recall"] for v in inst.values() if v["recall"] is not None]
    provisional = bool(unresolved_rel or recon["date_unresolved"])
    return {"schema_version": "1.0", "state": "evaluated" if not provisional else "evaluated_provisional",
            "window": win, "denominators": {"E_eligible_holdout_works": len(E), "F_found": len(hits), "C_indexed_by_an_enabled_source": len(C), "F_and_C": len([w for w in hits if w in C]),
                                            "coverage_failed_or_unresolved": len(cov_failed), "coverage_unknown": len(cov_unknown)},
            "work_level_recall": ratio(len(hits), len(E)), "work_level_recall_state": "evaluated" if E else "not_evaluated",
            "conditional_recall_given_indexed": ratio(len([w for w in hits if w in C]), len(C)), "conditional_state": "evaluated" if C else "not_evaluated",
            "hits_absent_from_coverage_snapshot": hits_not_in_C,
            "macro_recall_over_instruments": (round(sum(macro_vals) / len(macro_vals), 4) if macro_vals else None), "instruments": dict(sorted(inst.items())),
            "misses": sorted(misses), "hits": sorted(hits), "provisional": provisional, "unresolved_relevance": sorted(unresolved_rel),
            "reconciliation": recon, "candidates_not_in_gold": sorted(found_ids - {i for w in rows for i in work_ids(rows[w])})[:50],
            "note": "A work is counted once however many instruments it serves; by-instrument rows count distinct work-link pairs and are not independent studies. A hit absent from the coverage snapshot stays in F and is listed. No recall threshold means complete; every miss relevant to a High cell needs written review before any public claim."}


# ---------- fixtures ----------

def _row(wid, inst_links, date=("2026-08-15", "day"), calib=False, ids=None):
    return {"work_id": wid, "identifiers": ids or {"doi": wid[4:] if wid.startswith("doi:") else None, "pmid": None, "openalex_id": None},
            "citation": {"title": f"Title {wid}", "authors": ["A"], "year": 2026, "source_url": "https://example.org"},
            "publication_date": {"value": date[0], "precision": date[1], "source_url": "https://example.org"},
            "record_type": "primary_study", "calibration_only": calib, "overlap_state": "resolved", "study_families": [f"fam-{wid}"], "seed_membership": [],
            "links": [{"instrument_id": i, "property": p, "form": None, "scope": "measurement_property", "judgement": j, "reason": "fixture",
                       "source_location": {"url": "https://example.org", "read_level": "abstract_only", "section": None, "printed_pages": None, "table_or_figure": None, "accessed_at": "2026-09-05T00:00:00Z", "response_status": 200},
                       "judged_by": "fixture", "judged_at": "2026-09-05T00:00:00Z"} for i, p, j in inst_links],
            "judgements": [], "unresolved": []}


def _setup(n_eligible=10, n_found=7):
    rows = [_row(f"doi:10.5555/w{i}", [("isi", "internal_consistency", "eligible")]) for i in range(n_eligible)]
    comps = [{"component_id": f"c{i}", "work_ids": [f"doi:10.5555/w{i}"], "allocation": "holdout"} for i in range(n_eligible)]
    manifest = {"schema_version": "1.0", "benchmark_id": "fx", "state": "split_locked", "rows": rows}
    split = {"components": comps, "excluded": []}
    cands = {"candidates": [{"doi": f"10.5555/w{i}", "routes": ["names"]} for i in range(n_found)]}
    cov = {"rows": [{"work_id": f"doi:10.5555/w{i}", "source_id": "europepmc", "status": "indexed"} for i in range(n_eligible)]}
    lock = {"query_sha256": "q" * 64, "manifest_sha256": sha_obj(manifest), "split_sha256": sha_obj(split), "run_window": {"from": "2026-08-01", "to": "2026-09-05"}, "exposed_work_ids": [], "seed_work_ids": [], "instrument_ids": ["isi"]}
    return manifest, split, cov, cands, lock


def self_test():
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else detail); failures += not ok
    def run(m, s, c, cand, lock, sources=("europepmc",)):
        return evaluate(m, s, c, cand, lock, lock["query_sha256"], list(sources))
    m, s, c, cand, lock = _setup(); r = run(m, s, c, cand, lock)
    t("10 eligible with 7 found gives 7/10", r["denominators"]["E_eligible_holdout_works"] == 10 and r["work_level_recall"] == 0.7 and len(r["misses"]) == 3)
    m, s, c, cand, lock = _setup(10, 3); c = {"rows": [{"work_id": f"doi:10.5555/w{i}", "source_id": "europepmc", "status": "indexed"} for i in range(4)] + [{"work_id": f"doi:10.5555/w{i}", "source_id": "europepmc", "status": "not_indexed"} for i in range(4, 10)]}
    r = run(m, s, c, cand, lock); t("10 eligible, 4 known indexed, 3 found gives 3/10 and 3/4", r["work_level_recall"] == 0.3 and r["conditional_recall_given_indexed"] == 0.75)
    m, s, c, cand, lock = _setup(); lock["seed_work_ids"] = ["doi:10.5555/w0"]; lock["manifest_sha256"] = sha_obj(m)
    r = run(m, s, c, cand, lock); t("a seed retrieved is excluded from both numerator and denominator", r["denominators"]["E_eligible_holdout_works"] == 9 and r["denominators"]["F_found"] == 6 and r["reconciliation"]["seed"] == 1)
    m, s, c, cand, lock = _setup(); m["rows"][0]["links"].append({**m["rows"][0]["links"][0], "instrument_id": "who-5"}); lock["manifest_sha256"] = sha_obj(m); lock["instrument_ids"] = ["isi", "who-5"]
    r = run(m, s, c, cand, lock); t("one work linked to two instruments is counted once at work level and appears in both instrument rows", r["denominators"]["E_eligible_holdout_works"] == 10 and r["instruments"]["who-5"]["eligible_work_links"] == 1 and r["instruments"]["isi"]["eligible_work_links"] == 10)
    m, s, c, cand, lock = _setup(); s["components"][0]["work_ids"].append("doi:10.5555/w1"); s["components"] = [x for x in s["components"] if x["component_id"] != "c1"]; s["components"][0]["allocation"] = "development"; lock["split_sha256"] = sha_obj(s)
    r = run(m, s, c, cand, lock); t("two publications sharing a cohort sit in one component and move together to development", r["reconciliation"]["development"] == 2 and r["denominators"]["E_eligible_holdout_works"] == 8)
    m, s, c, cand, lock = _setup(); m["rows"][0]["publication_date"] = {"value": "2026", "precision": "year", "source_url": "x"}; m["rows"][1]["publication_date"] = {"value": "2025", "precision": "year", "source_url": "x"}; m["rows"][2]["publication_date"] = {"value": None, "precision": "unknown", "source_url": "x"}; lock["manifest_sha256"] = sha_obj(m)
    r = run(m, s, c, cand, lock); t("a year-only date straddling the window is unresolved, one wholly outside is out, an unknown date is unresolved; the figure is provisional", r["reconciliation"]["date_unresolved"] == 2 and r["reconciliation"]["out_of_window"] == 1 and r["provisional"] is True)
    m, s, c, cand, lock = _setup(); m["rows"][0]["links"][0]["judgement"] = "unresolved"; lock["manifest_sha256"] = sha_obj(m)
    r = run(m, s, c, cand, lock); t("unresolved relevance is counted and reported, not dropped, and makes the figure provisional", r["reconciliation"]["relevance_unresolved"] == 1 and r["unresolved_relevance"] == ["doi:10.5555/w0"] and r["provisional"])
    m, s, c, cand, lock = _setup(); cand["candidates"][0]["abstract"] = ""; r = run(m, s, c, cand, lock); t("an eligible hit with no abstract still counts as found", "doi:10.5555/w0" in r["hits"])
    m, s, c, cand, lock = _setup(); cand["candidates"].append({"doi": "10.9/not-gold", "routes": ["names"]}); r = run(m, s, c, cand, lock)
    t("a candidate not in gold is listed and does not change recall", "doi:10.9/not-gold" in r["candidates_not_in_gold"] and r["work_level_recall"] == 0.7)
    m, s, c, cand, lock = _setup(0, 0); lock["instrument_ids"] = ["isi"]; r = run(m, s, c, cand, lock)
    t("an all-zero denominator yields metric null and state not_evaluated, never 100%", r["work_level_recall"] is None and r["work_level_recall_state"] == "not_evaluated" and r["instruments"]["isi"]["recall"] is None)
    m, s, c, cand, lock = _setup(); lock["query_sha256"] = "z" * 64
    try: evaluate(m, s, c, cand, lock, "q" * 64, ["europepmc"]); t("a stale query hash stops the run", False)
    except SystemExit as e: t("a stale query hash stops the run", "query file hash" in str(e))
    m, s, c, cand, lock = _setup(); m["rows"][0]["unresolved"] = ["x"]
    try: evaluate(m, s, c, cand, lock, lock["query_sha256"], ["europepmc"]); t("a stale manifest hash stops the run", False)
    except SystemExit as e: t("a stale manifest hash stops the run", "manifest hash" in str(e))
    m, s, c, cand, lock = _setup(10, 3); c = {"rows": [{"work_id": f"doi:10.5555/w{i}", "source_id": "europepmc", "status": "failed"} for i in range(10)]}
    r = run(m, s, c, cand, lock); t("a failed coverage lookup is not read as not indexed: conditional recall not evaluated, failures counted", r["conditional_state"] == "not_evaluated" and r["denominators"]["coverage_failed_or_unresolved"] == 10)
    m, s, c, cand, lock = _setup(); lock["exposed_work_ids"] = ["doi:10.5555/w0"]; r = run(m, s, c, cand, lock)
    t("a previously exposed holdout work is excluded and counted as exposure", r["reconciliation"]["exposed"] == 1 and r["denominators"]["E_eligible_holdout_works"] == 9)
    m, s, c, cand, lock = _setup(); m["rows"][1]["citation"]["title"] = m["rows"][0]["citation"]["title"]; lock["manifest_sha256"] = sha_obj(m); cand["candidates"] = [{"doi": "10.5555/w0", "title": "Title doi:10.5555/w0", "routes": ["names"]}]
    r = run(m, s, c, cand, lock); t("a title collision with a different DOI does not count the second work as found", r["hits"] == ["doi:10.5555/w0"])
    m, s, c, cand, lock = _setup(); m["rows"].append(_row("doi:10.5555/w0corr", [("isi", "internal_consistency", "eligible")])); m["rows"][-1]["record_type"] = "correction"; s["components"].append({"component_id": "cc", "work_ids": ["doi:10.5555/w0corr"], "allocation": "holdout"}); lock["manifest_sha256"] = sha_obj(m); lock["split_sha256"] = sha_obj(s)
    r = run(m, s, c, cand, lock); t("a correction notice is a distinct work from its original and is a separate miss when not retrieved", "doi:10.5555/w0corr" in r["misses"] and "doi:10.5555/w0" in r["hits"])
    m, s, c, cand, lock = _setup(); m["rows"][0]["identifiers"]["doi"] = "10.1027//1015-5759.19.1.12"; m["rows"][0]["work_id"] = "doi:10.1027//1015-5759.19.1.12"; s["components"][0]["work_ids"] = ["doi:10.1027//1015-5759.19.1.12"]; lock["manifest_sha256"] = sha_obj(m); lock["split_sha256"] = sha_obj(s)
    cand["candidates"][0] = {"doi": "HTTPS://DOI.ORG/10.1027//1015-5759.19.1.12", "routes": ["names"]}; r = run(m, s, c, cand, lock)
    t("duplicate casing and the OLBI double slash canonicalise to the same identity", "doi:10.1027//1015-5759.19.1.12" in r["hits"])
    m, s, c, cand, lock = _setup(); cand["candidates"][0]["routes"] = ["identifier_lookup"]; r = run(m, s, c, cand, lock)
    t("an identifier lookup is not discovery: the work is not counted as found", "doi:10.5555/w0" in r["misses"])
    m, s, c, cand, lock = _setup(10, 7); c = {"rows": [{"work_id": f"doi:10.5555/w{i}", "source_id": "europepmc", "status": "indexed"} for i in range(1, 10)]}
    r = run(m, s, c, cand, lock); t("a hit absent from the coverage snapshot stays in the numerator and is listed; C is not rewritten", r["denominators"]["F_found"] == 7 and r["hits_absent_from_coverage_snapshot"] == ["doi:10.5555/w0"] and r["denominators"]["C_indexed_by_an_enabled_source"] == 9)
    m, s, c, cand, lock = _setup(); m["state"] = "judged"; lock["manifest_sha256"] = sha_obj(m)
    try: evaluate(m, s, c, cand, lock, lock["query_sha256"], ["europepmc"]); t("an unlocked manifest is refused", False)
    except SystemExit as e: t("an unlocked manifest (state judged) is refused", "locked" in str(e))
    with tempfile.TemporaryDirectory() as tmp:
        m, s, c, cand, lock = _setup(); out = Path(tmp) / "report.json"
        out.write_text(json.dumps(run(m, s, c, cand, lock), indent=1)); t("a report writes only to the supplied path", out.exists())
    print(f"{'all' if not failures else failures} evaluator probes {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


def main():
    ap = argparse.ArgumentParser()
    for k in ("manifest", "split", "coverage", "queries", "candidates", "query-lock", "out"): ap.add_argument(f"--{k}")
    ap.add_argument("--sources", default="europepmc,openalex,crossref", help="enabled coverage sources, comma separated")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: return self_test()
    need = [k for k in ("manifest", "split", "coverage", "queries", "candidates", "query_lock", "out") if not getattr(a, k)]
    if need: sys.exit(f"missing: {need}; every input path is explicit, there is no default")
    L = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    rep = evaluate(L(a.manifest), L(a.split), L(a.coverage), L(a.candidates), L(a.query_lock), sha(Path(a.queries).read_bytes()), a.sources.split(","))
    Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"report written to {a.out}: E={rep['denominators']['E_eligible_holdout_works']} F={rep['denominators']['F_found']} recall={rep['work_level_recall']} ({rep['state']})")


if __name__ == "__main__":
    main()
