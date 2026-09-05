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

Writes evidence/retraction-signals.json with a run status (complete: every check on every DOI was made;
partial: some checks failed; failed: nothing could be checked), per-source counters, the signals with the
records and cells that cite the work, and the unchecked list. Exit 0 complete and no signal; 3 a signal
exists; 4 partial with no signal; 5 failed. The workflow opens an issue on 3, 4 and 5.

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
            if e.code == 429 or e.code >= 500: time.sleep(3 * (attempt + 1)); continue
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


def crossref_incoming(doi):
    notices, offset, truncated, err = [], 0, False, None
    for page in range(MAX_PAGES):
        data, err = get(f"https://api.crossref.org/works?filter=updates:{urllib.parse.quote(doi, safe='')}&rows={PAGE}&offset={offset}&mailto={MAILTO}")
        if err: break
        msg = data.get("message", {}); items = msg.get("items", [])
        for n in items:
            for u in n.get("update-to") or []:
                if norm_doi(u.get("DOI")) == doi:
                    notices.append({"notice_doi": norm_doi(n.get("DOI")), "type": u.get("type"), "label": u.get("label"),
                                    "updated": (u.get("updated") or {}).get("date-time")})
        total = msg.get("total-results", 0); offset += PAGE
        if offset >= total or not items: break
    else:
        truncated = True
    return {"notices": notices, "truncated": truncated}, err


def openalex_flag(doi):
    oa, err = get(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}?select=is_retracted&mailto={MAILTO}")
    if err: return None, err
    return {"is_retracted": bool(oa.get("is_retracted"))}, None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dataset", default=str(DEFAULT_DATASET)); a = ap.parse_args()
    data = json.loads(Path(a.dataset).read_text(encoding="utf-8"))
    refs = cited_by(data)
    signals, unchecked = [], []
    counters = {s: {"attempted": 0, "succeeded": 0, "failed": 0} for s in ("crossref_record", "crossref_incoming", "openalex")}
    for doi, where in sorted(refs.items()):
        results = {}
        for name, fn in (("crossref_record", crossref_own), ("crossref_incoming", crossref_incoming), ("openalex", openalex_flag)):
            counters[name]["attempted"] += 1
            res, err = fn(doi)
            if err:
                counters[name]["failed"] += 1
                unchecked.append({"doi": doi, "source": name, "reason": ("not registered with Crossref (DataCite or other agency)" if name.startswith("crossref") and err == "http 404" else err), "cited_by": where})
            else:
                counters[name]["succeeded"] += 1; results[name] = res
        own = (results.get("crossref_record") or {}).get("is_notice_about") or []
        inc = (results.get("crossref_incoming") or {}).get("notices") or []
        flag = (results.get("openalex") or {}).get("is_retracted")
        if own or inc or flag:
            signals.append({"doi": doi, "crossref_incoming_notices": inc, "crossref_incoming_truncated": (results.get("crossref_incoming") or {}).get("truncated", False),
                            "openalex_is_retracted": flag, "is_itself_a_notice_about": own, "cited_by": where})
    total_att = sum(c["attempted"] for c in counters.values()); total_ok = sum(c["succeeded"] for c in counters.values())
    status = "complete" if total_att and total_ok == total_att else ("failed" if total_ok == 0 else "partial")
    out = {"status": status, "dataset": Path(a.dataset).name, "dois_checked": len(refs), "sources": counters, "signals": signals, "unchecked": unchecked,
           "citation_mapping": "typed references only: precondition_evidence[].citation and retest[].citation matched on citation key",
           "note": "A signal is a Crossref update notice pointing at the work, the work being itself a notice, or an OpenAlex retraction flag. Read the notice: a correction is not a retraction. An unchecked source is unchecked, not clean. Nothing here changes the registry."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"run {status}: {len(refs)} DOIs, {len(signals)} with a signal, {len(unchecked)} source checks not made")
    sys.exit(3 if signals else (5 if status == "failed" else (4 if status == "partial" else 0)))


if __name__ == "__main__":
    main()
