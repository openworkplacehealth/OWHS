#!/usr/bin/env python3
"""Retraction and correction watcher for every DOI the registry cites.

For each distinct DOI in the current dataset's citation arrays, ask Crossref two questions: does this work's
own record carry update-to (it is itself a notice about another work), and does any other record declare
an update to it (the updates filter, the direction a retraction notice points). Then ask OpenAlex whether the
work is flagged retracted. Write evidence/retraction-signals.json listing every DOI with a signal, the type of
notice (correction, erratum, expression of concern, retraction, withdrawal, reinstatement are different
events), the notice DOI, and the registry records and cells that cite the work.

Exit 0 when no signal; exit 3 when at least one signal is present so the workflow opens an issue. A missing
flag is "no signal found", never proof that a work stands. DataCite DOIs and unreachable records are listed
as unchecked. Nothing here removes evidence, moves a grade or changes a licence class.

    python tools/watch_retractions.py [--dataset PATH]
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "site" / "instrument-registry" / "instrument-evidence-base-v0.9.0.json"
OUT = ROOT / "evidence" / "retraction-signals.json"
MAILTO = "registry@openworkplacehealth.org"
UA = f"OWHS-retraction-watch/0.1 (https://openworkplacehealth.org; mailto:{MAILTO})"
PROPS = ["structural_validity", "convergent_discriminant_validity", "criterion_validity_reference_standard", "criterion_validity_organisational",
         "internal_consistency", "test_retest_reliability", "measurement_invariance", "responsiveness_mic", "populations_languages_norms"]


def get(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            time.sleep(0.4); return data, None
        except urllib.error.HTTPError as e:
            if e.code in (429,) or e.code >= 500: time.sleep(3 * (attempt + 1)); continue
            return None, f"http {e.code}"
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None, "exhausted retries"


def norm_doi(doi):
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    return urllib.parse.unquote(d).lower() or None


def cited_by(data):
    """doi -> list of (instrument_id, citation_key, cells that reference the key)"""
    out = {}
    for r in data["records"]:
        for c in r.get("citations", []):
            d = norm_doi(c.get("doi"))
            if not d: continue
            key = c.get("key")
            cells = [p for p in PROPS if key and isinstance(r.get(p), dict) and key in json.dumps(r[p])]
            out.setdefault(d, []).append({"instrument_id": r["instrument_id"], "citation_key": key, "cells": cells})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dataset", default=str(DEFAULT_DATASET)); a = ap.parse_args()
    data = json.loads(Path(a.dataset).read_text(encoding="utf-8"))
    refs = cited_by(data)
    signals, unchecked = [], []
    for doi, where in sorted(refs.items()):
        rec, err = get(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}?mailto={MAILTO}")
        if err:
            unchecked.append({"doi": doi, "reason": f"crossref {err}", "cited_by": where}); continue
        m = rec.get("message", {})
        own_updates = m.get("update-to") or []
        incoming, err2 = get(f"https://api.crossref.org/works?filter=updates:{urllib.parse.quote(doi, safe='')}&rows=20&mailto={MAILTO}")
        notices = []
        if not err2 and incoming:
            for n in incoming.get("message", {}).get("items", []):
                for u in n.get("update-to") or []:
                    if norm_doi(u.get("DOI")) == doi:
                        notices.append({"notice_doi": norm_doi(n.get("DOI")), "type": u.get("type"), "label": u.get("label"), "updated": (u.get("updated") or {}).get("date-time")})
        oa, err3 = get(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}?select=is_retracted&mailto={MAILTO}")
        oa_flag = None if err3 or not oa else oa.get("is_retracted")
        if notices or oa_flag or own_updates:
            signals.append({"doi": doi, "crossref_notices": notices, "openalex_is_retracted": oa_flag,
                            "is_itself_a_notice_about": [norm_doi(u.get("DOI")) for u in own_updates], "cited_by": where})
        if err2: unchecked.append({"doi": doi, "reason": f"crossref updates filter {err2}", "cited_by": where})
        if err3: unchecked.append({"doi": doi, "reason": f"openalex {err3}", "cited_by": where})
    out = {"dataset": Path(a.dataset).name, "dois_checked": len(refs), "signals": signals, "unchecked": unchecked,
           "note": "A signal is a Crossref update notice pointing at the work, an OpenAlex retraction flag, or the work being itself a notice. Read the notice: a correction is not a retraction. Absence of a signal is not proof that a work stands. Nothing here changes the registry."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(refs)} DOIs checked; {len(signals)} with a signal; {len(unchecked)} unchecked")
    sys.exit(3 if signals else 0)


if __name__ == "__main__":
    main()
