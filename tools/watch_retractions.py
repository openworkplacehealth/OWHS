#!/usr/bin/env python3
"""Retraction and correction watcher for every DOI the registry cites.

For each distinct DOI in the current dataset's citation arrays, three independent checks, each recorded
separately so one source's failure never hides another's answer:

  crossref record     does the work's own record carry update-to (it is itself a notice about another work),
                      kept with type, label and target
  crossref incoming   does any record declare an update to it (the `updates` filter, the direction a
                      retraction or correction notice points), paged until exhausted or marked truncated
  openalex            is the work flagged retracted

Correction, erratum, expression of concern, retraction, withdrawal and reinstatement are different events and
are kept by type. A signal is any of the three answering yes. A check that could not be made is recorded as
unchecked for that source; absence of a signal is never proof that a work stands. DataCite DOIs are reported as
outside Crossref's coverage rather than as clean.

Writes evidence/retraction-signals.json with a run status (complete: every check on every DOI was made in
full; partial: some checks failed or a paged check hit its page cap before the index was exhausted; failed:
nothing could be checked), per-source counters including truncations, the signals with the records and cells
that cite the work, and the unchecked list, in which a truncated check appears per DOI and source as incomplete
coverage whether or not a signal was found. Exit 0 complete and no signal; 3 a signal exists; 4 partial with no
signal; 5 failed. The workflow opens an issue on 3, 4 and 5.

    python tools/watch_retractions.py --self-test      offline: stubbed pages, page-cap truncation with and without a signal

Cells are mapped to citations by the typed references the dataset carries: the `citation` field of each
precondition_evidence entry and each retest entry, matched on the citation key. Prose mentions are not used.

    python tools/watch_retractions.py [--dataset PATH]
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "site" / "instrument-registry" / "instrument-evidence-base-v0.9.0.json"
OUT = ROOT / "evidence" / "retraction-signals.json"
MAILTO = "registry@openworkplacehealth.org"
UA = f"OWHS-retraction-watch/0.2 (https://openworkplacehealth.org; mailto:{MAILTO})"
PROPS = ["structural_validity", "convergent_discriminant_validity", "criterion_validity_reference_standard", "criterion_validity_organisational",
         "internal_consistency", "test_retest_reliability", "measurement_invariance", "responsiveness_mic", "populations_languages_norms"]
PAGE = 100
MAX_PAGES = 5


def get(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            time.sleep(0.4); return data, None
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = e.headers.get("Retry-After")
                if ra and ra.strip().isdigit() and int(ra) > 120:
                    return None, f"http {e.code}, retry-after {ra}s (budget exhausted); source deferred"   # fail fast, report unchecked
                time.sleep(3 * (attempt + 1)); continue
            return None, f"http {e.code}"
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None, "exhausted retries"


def norm_doi(doi):
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    return urllib.parse.unquote(d).lower() or None


def norm_key(k):
    return re.sub(r"[^a-z0-9]", "", (k or "").lower())


def cited_by(data):
    """doi -> [{instrument_id, citation_key, cells}] using typed references only."""
    out = {}
    for r in data["records"]:
        keys = {}
        for c in r.get("citations", []):
            d = norm_doi(c.get("doi"))
            if d and c.get("key"):
                keys[norm_key(c["key"])] = (d, c["key"])
        cells_by_key = {}
        for p in PROPS:
            cell = r.get(p)
            if not isinstance(cell, dict): continue
            refs = []
            for e in (cell.get("precondition_evidence") or []):
                if isinstance(e, dict) and e.get("citation"): refs.append(e["citation"])
            for e in (cell.get("retest") or []):
                if isinstance(e, dict) and e.get("citation"): refs.append(e["citation"])
            for ref in refs:
                cells_by_key.setdefault(norm_key(ref), set()).add(p)
        for nk, (d, key) in keys.items():
            out.setdefault(d, []).append({"instrument_id": r["instrument_id"], "citation_key": key, "cells": sorted(cells_by_key.get(nk, set()))})
    return out


def crossref_own(doi):
    rec, err = get(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}?mailto={MAILTO}")
    if err: return None, err
    m = rec.get("message", {})
    return {"is_notice_about": [{"target_doi": norm_doi(u.get("DOI")), "type": u.get("type"), "label": u.get("label"),
                                 "updated": (u.get("updated") or {}).get("date-time")} for u in (m.get("update-to") or [])],
            "registration_agency_ok": True}, None


def crossref_incoming(doi, fetch=None):
    fetch = fetch or get
    notices, offset, err, total = [], 0, None, 0
    pages = 0
    for page in range(MAX_PAGES):
        data, err = fetch(f"https://api.crossref.org/works?filter=updates:{urllib.parse.quote(doi, safe='')}&rows={PAGE}&offset={offset}&mailto={MAILTO}")
        if err: break
        pages += 1
        msg = data.get("message", {}); items = msg.get("items", [])
        for n in items:
            for u in n.get("update-to") or []:
                if norm_doi(u.get("DOI")) == doi:
                    notices.append({"notice_doi": norm_doi(n.get("DOI")), "type": u.get("type"), "label": u.get("label"),
                                    "updated": (u.get("updated") or {}).get("date-time")})
        total = msg.get("total-results", 0); offset += PAGE
        if offset >= total or not items: break
    truncated = err is None and offset < total       # the cap stopped us before the index was exhausted
    if err and pages: err = f"{err} after {pages} page(s)"
    return {"notices": notices, "truncated": truncated, "pages": pages, "total_results": total}, err


def openalex_flag(doi):
    oa, err = get(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}?select=is_retracted&mailto={MAILTO}")
    if err: return None, err
    return {"is_retracted": bool(oa.get("is_retracted"))}, None


def run(refs, checkers):
    """Pure assembly over the three checkers, each (doi) -> (result, error). A truncated paged check is incomplete
    coverage for that DOI and source, recorded in unchecked and counted, independently of any signal."""
    signals, unchecked = [], []
    counters = {s: {"attempted": 0, "succeeded": 0, "failed": 0, "truncated": 0} for s in ("crossref_record", "crossref_incoming", "openalex")}
    for doi, where in sorted(refs.items()):
        results = {}
        for name, fn in checkers:
            counters[name]["attempted"] += 1
            res, err = fn(doi)
            if err:
                counters[name]["failed"] += 1
                unchecked.append({"doi": doi, "source": name, "reason": ("not registered with Crossref (DataCite or other agency)" if name.startswith("crossref") and err.startswith("http 404") else err), "cited_by": where})
                continue
            results[name] = res
            if res.get("truncated"):
                counters[name]["truncated"] += 1
                unchecked.append({"doi": doi, "source": name, "reason": f"incomplete coverage: page cap reached after {res.get('pages')} page(s) of {res.get('total_results')} reported results; later notices were not read", "cited_by": where})
            else:
                counters[name]["succeeded"] += 1
        own = (results.get("crossref_record") or {}).get("is_notice_about") or []
        inc = (results.get("crossref_incoming") or {}).get("notices") or []
        flag = (results.get("openalex") or {}).get("is_retracted")
        if own or inc or flag:
            signals.append({"doi": doi, "crossref_incoming_notices": inc, "crossref_incoming_truncated": (results.get("crossref_incoming") or {}).get("truncated", False),
                            "openalex_is_retracted": flag, "is_itself_a_notice_about": own, "cited_by": where})
    total_att = sum(c["attempted"] for c in counters.values()); total_ok = sum(c["succeeded"] for c in counters.values())
    status = "complete" if total_att and total_ok == total_att else ("failed" if total_ok == 0 else "partial")
    return status, counters, signals, unchecked


def exit_code(status, signals):
    return 3 if signals else (5 if status == "failed" else (4 if status == "partial" else 0))


def self_test():
    """Offline: a Crossref incoming query whose total exceeds the page cap, with rows that do not match, must make the
    run partial with a non-zero exit even when nothing signals; the same truncation beside a signal is kept as coverage."""
    def pages(total, matching=False):
        def fetch(url):
            offset = int(re.search(r"offset=(\d+)", url).group(1))
            items = [{"DOI": f"10.1/notice{offset + i}", "update-to": [{"DOI": "10.1/target" if matching and i == 0 else "10.1/other", "type": "correction", "label": "Correction"}]} for i in range(PAGE)]
            return {"message": {"total-results": total, "items": items}}, None
        return fetch
    refs = {"10.1/target": [{"instrument_id": "x", "citation_key": "K", "cells": []}]}
    clean = lambda d: ({"is_notice_about": []}, None); oa = lambda d: ({"is_retracted": False}, None)
    r, err = crossref_incoming("10.1/target", fetch=pages(total=PAGE * MAX_PAGES + 1))
    assert err is None and r["truncated"] and r["pages"] == MAX_PAGES and r["notices"] == [], r
    status, counters, signals, unchecked = run(refs, (("crossref_record", clean), ("crossref_incoming", lambda d: crossref_incoming(d, fetch=pages(PAGE * MAX_PAGES + 1))), ("openalex", oa)))
    assert status == "partial" and not signals and len(unchecked) == 1 and "page cap" in unchecked[0]["reason"] and exit_code(status, signals) == 4, (status, unchecked)
    print("ok   page-cap truncation without a signal: run partial, coverage gap recorded per DOI and source, exit 4")
    status, counters, signals, unchecked = run(refs, (("crossref_record", clean), ("crossref_incoming", lambda d: crossref_incoming(d, fetch=pages(PAGE * MAX_PAGES + 1, matching=True))), ("openalex", oa)))
    assert status == "partial" and len(signals) == 1 and signals[0]["crossref_incoming_truncated"] and len(unchecked) == 1 and exit_code(status, signals) == 3
    print("ok   page-cap truncation with a signal: signal kept, coverage gap still recorded, run partial, exit 3")
    status, counters, signals, unchecked = run(refs, (("crossref_record", clean), ("crossref_incoming", lambda d: crossref_incoming(d, fetch=pages(PAGE * 2))), ("openalex", oa)))
    assert status == "complete" and not unchecked and exit_code(status, signals) == 0, (status, unchecked)
    print("ok   two full pages within the cap: complete, exit 0")
    status, counters, signals, unchecked = run(refs, (("crossref_record", lambda d: (None, "http 429, retry-after 30000s (budget exhausted); source deferred")), ("crossref_incoming", lambda d: crossref_incoming(d, fetch=pages(PAGE))), ("openalex", oa)))
    assert status == "partial" and unchecked[0]["source"] == "crossref_record" and exit_code(status, signals) == 4
    print("ok   a deferred source is unchecked, run partial, exit 4")
    status, *_ = run(refs, (("crossref_record", lambda d: (None, "x")), ("crossref_incoming", lambda d: (None, "x")), ("openalex", lambda d: (None, "x"))))
    assert status == "failed" and exit_code(status, []) == 5
    print("ok   every source failing: failed, exit 5")
    print("self-test passed")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dataset", default=str(DEFAULT_DATASET)); ap.add_argument("--self-test", action="store_true"); a = ap.parse_args()
    if a.self_test: return self_test()
    data = json.loads(Path(a.dataset).read_text(encoding="utf-8"))
    refs = cited_by(data)
    status, counters, signals, unchecked = run(refs, (("crossref_record", crossref_own), ("crossref_incoming", crossref_incoming), ("openalex", openalex_flag)))
    out = {"status": status, "dataset": Path(a.dataset).name, "dois_checked": len(refs), "sources": counters, "signals": signals, "unchecked": unchecked,
           "citation_mapping": "typed references only: precondition_evidence[].citation and retest[].citation matched on citation key",
           "note": "A signal is a Crossref update notice pointing at the work, the work being itself a notice, or an OpenAlex retraction flag. Read the notice: a correction is not a retraction. An unchecked source is unchecked, not clean; a truncated paged check is listed there as incomplete coverage. Nothing here changes the registry."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"run {status}: {len(refs)} DOIs, {len(signals)} with a signal, {len(unchecked)} source checks not made or not complete")
    sys.exit(exit_code(status, signals))


if __name__ == "__main__":
    main()
