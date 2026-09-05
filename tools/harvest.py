#!/usr/bin/env python3
"""Deterministic evidence harvester for the instrument registry.

Queries the open scholarly indexes directly and writes one candidates file. No language model is involved:
the same inputs on the same day produce the same file, and every candidate records where it was found.

    python tools/harvest.py --from 2026-07-12 --to 2026-09-05 --out evidence/candidates/2026-09.json
    python tools/harvest.py --instrument isi --from 2026-01-01 --to 2026-09-05      # one instrument
    python tools/harvest.py --recall registry/instrument-evidence-base-v0.9.0.json  # regression check

Sources (all open, no credentials):
  OpenAlex      title-and-abstract phrase search per instrument name, plus works citing each development paper
  Europe PMC    fielded TITLE_ABS queries per instrument name, restricted to the window
  Crossref      DOI verification and the update-to (retraction/correction) field for every survivor

A candidate is a work whose title or abstract carries one of the instrument's names AND one of the
psychometric property terms in registry/harvest-queries.json. Works whose title carries an exclusion term are
dropped and the drop is recorded. Candidates are de-duplicated by DOI, then PMID, then OpenAlex id, then a
normalised title. The output is sorted, so a diff between two runs is meaningful.

The --recall mode runs the harvester over a wide window and reports what fraction of the registry's own cited
DOIs it finds. That is a regression check on the queries, not an estimate of coverage of new literature: the
registry's citations were themselves found by searching, so rediscovering them cannot measure what searching
misses. A held-out reference set is needed for that and is not part of this tool.

Polite-pool contact: the mailto below identifies the steward to OpenAlex and Crossref so a runaway script
can be reported. It is not a credential.
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "registry" / "harvest-queries.json"
MAILTO = "registry@openworkplacehealth.org"
UA = f"OWHS-harvester/0.1 (https://openworkplacehealth.org; mailto:{MAILTO})"
PAUSE = 0.25            # seconds between requests: well inside every published limit at this volume


def get(url, tries=4):
    """GET JSON with a polite pause and simple retry. Returns None on a hard failure, which the caller records."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            time.sleep(PAUSE)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1)); continue
            return None
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def norm_doi(doi):
    if not doi: return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = urllib.parse.unquote(d)
    return d or None


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


# ---------- OpenAlex ----------

def openalex_search(phrase, date_from, date_to, terms):
    """Works whose title or abstract carry the phrase, in the window, then filtered locally on property terms."""
    out = []
    cursor = "*"
    q = {
        "filter": f'title_and_abstract.search:"{phrase}",from_publication_date:{date_from},to_publication_date:{date_to}',
        "select": "id,doi,title,publication_date,primary_location,ids,abstract_inverted_index,type",
        "per-page": 200, "mailto": MAILTO,
    }
    while cursor:
        q["cursor"] = cursor
        data = get("https://api.openalex.org/works?" + urllib.parse.urlencode(q))
        if data is None: return out, "openalex: request failed"
        for w in data.get("results", []):
            out.append(openalex_work(w))
        cursor = data.get("meta", {}).get("next_cursor")
        if len(out) > 2000: break     # a phrase this broad is a query problem, not a result
    return out, None


def openalex_cited_by(doi, date_from, date_to):
    w = get(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi, safe='')}?mailto={MAILTO}")
    if not w or not w.get("id"): return [], f"openalex: development work not found for {doi}"
    wid = w["id"].rsplit("/", 1)[-1]
    out, cursor = [], "*"
    q = {"filter": f"cites:{wid},from_publication_date:{date_from},to_publication_date:{date_to}",
         "select": "id,doi,title,publication_date,primary_location,ids,abstract_inverted_index,type",
         "per-page": 200, "mailto": MAILTO}
    while cursor:
        q["cursor"] = cursor
        data = get("https://api.openalex.org/works?" + urllib.parse.urlencode(q))
        if data is None: return out, "openalex: cited-by request failed"
        out += [openalex_work(x) for x in data.get("results", [])]
        cursor = data.get("meta", {}).get("next_cursor")
    return out, None


def openalex_work(w):
    inv = w.get("abstract_inverted_index") or {}
    words = sorted(((pos, tok) for tok, poss in inv.items() for pos in poss), key=lambda x: x[0])
    abstract = " ".join(t for _, t in words)
    loc = w.get("primary_location") or {}
    src = (loc.get("source") or {}).get("display_name")
    return {"openalex": w.get("id"), "doi": norm_doi(w.get("doi")), "pmid": (w.get("ids") or {}).get("pmid"),
            "title": w.get("title") or "", "date": w.get("publication_date"), "venue": src, "type": w.get("type"),
            "abstract": abstract}


# ---------- Europe PMC ----------

def europepmc_search(phrase, date_from, date_to, terms):
    prop = " OR ".join(f'TITLE_ABS:"{t}"' for t in terms)
    query = f'(TITLE_ABS:"{phrase}") AND ({prop}) AND (FIRST_PDATE:[{date_from} TO {date_to}])'
    out, cursor = [], "*"
    while cursor:
        q = {"query": query, "format": "json", "pageSize": 100, "resultType": "core", "cursorMark": cursor}
        data = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(q))
        if data is None: return out, "europepmc: request failed"
        for r in data.get("resultList", {}).get("result", []):
            out.append({"openalex": None, "doi": norm_doi(r.get("doi")), "pmid": r.get("pmid"), "title": r.get("title") or "",
                        "date": r.get("firstPublicationDate"), "venue": (r.get("journalInfo") or {}).get("journal", {}).get("title") or r.get("journalTitle"),
                        "type": r.get("pubType"), "abstract": r.get("abstractText") or ""})
        nxt = data.get("nextCursorMark")
        cursor = nxt if nxt and nxt != cursor else None
    return out, None


# ---------- Crossref ----------

def crossref_check(doi):
    data = get(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}?mailto={MAILTO}")
    if not data: return {"resolves": False}
    m = data.get("message", {})
    return {"resolves": True, "type": m.get("type"), "update_to": m.get("update-to"),
            "updated_by": m.get("updated-by"), "issued": (m.get("issued") or {}).get("date-parts")}


# ---------- assembly ----------

def matches_terms(text, terms):
    t = text.lower()
    return sorted({term for term in terms if term.lower() in t})


def harvest(instruments, date_from, date_to, cfg, verify=True):
    terms = cfg["property_terms"]
    candidates, dropped, failures, seen_without_terms = {}, [], [], {}
    for iid, spec in instruments.items():
        found = []
        for name in spec["names"]:
            works, err = openalex_search(name, date_from, date_to, terms)
            if err: failures.append({"instrument": iid, "source": "openalex", "query": name, "error": err})
            found += [(w, "openalex:search", name) for w in works]
            works, err = europepmc_search(name, date_from, date_to, terms)
            if err: failures.append({"instrument": iid, "source": "europepmc", "query": name, "error": err})
            found += [(w, "europepmc:search", name) for w in works]
        for doi in spec.get("development_dois", []):
            works, err = openalex_cited_by(doi, date_from, date_to)
            if err: failures.append({"instrument": iid, "source": "openalex", "query": f"cites:{doi}", "error": err})
            found += [(w, f"openalex:cites:{doi}", doi) for w in works]
        for w, via, q in found:
            title_l = w["title"].lower()
            if any(x.lower() in title_l for x in spec.get("exclude", [])):
                dropped.append({"instrument": iid, "doi": w["doi"], "title": w["title"], "reason": "exclusion term in title"}); continue
            hit_terms = matches_terms(w["title"] + " " + w["abstract"], terms)
            if not hit_terms:
                seen_without_terms[iid] = seen_without_terms.get(iid, 0) + 1
                continue        # a work that names or cites the instrument but carries no psychometric term is a use, not evidence about it
            key = w["doi"] or (f"pmid:{w['pmid']}" if w["pmid"] else None) or w["openalex"] or f"title:{norm_title(w['title'])}"
            c = candidates.setdefault(key, {"doi": w["doi"], "pmid": w["pmid"], "openalex": w["openalex"], "title": w["title"],
                                            "date": w["date"], "venue": w["venue"], "type": w["type"],
                                            "instruments": [], "found_via": [], "property_terms": []})
            if iid not in c["instruments"]: c["instruments"].append(iid)
            tag = f"{via} [{q}]"
            if tag not in c["found_via"]: c["found_via"].append(tag)
            c["property_terms"] = sorted(set(c["property_terms"]) | set(hit_terms))
            for k in ("doi", "pmid", "openalex"):
                if not c[k] and w[k]: c[k] = w[k]
    # second pass: merge on normalised title where DOIs were missing on one side
    by_title = {}
    for key, c in list(candidates.items()):
        nt = norm_title(c["title"])
        if nt in by_title and by_title[nt] != key:
            other = candidates[by_title[nt]]
            for k in ("instruments", "found_via", "property_terms"):
                other[k] = sorted(set(other[k]) | set(c[k]))
            for k in ("doi", "pmid", "openalex"):
                if not other[k] and c[k]: other[k] = c[k]
            del candidates[key]
        else:
            by_title[nt] = key
    if verify:
        for c in candidates.values():
            c["crossref"] = crossref_check(c["doi"]) if c["doi"] else {"resolves": None}
    items = sorted(candidates.values(), key=lambda c: (c["doi"] or "", c["title"]))
    for c in items:
        c["instruments"].sort(); c["found_via"].sort()
    return items, dropped, failures, seen_without_terms


def new_instrument_candidates(cfg, date_from, date_to, known_names):
    """Untargeted query: validation papers in working populations that name none of the tracked instruments."""
    q = cfg.get("new_instrument_query")
    if not q: return [], []
    out, failures = {}, []
    ctx = " OR ".join(f'TITLE_ABS:"{t}"' for t in q["context_terms"])
    for phrase in q["title_phrases"]:
        query = f'(TITLE:"{phrase}") AND ({ctx}) AND (FIRST_PDATE:[{date_from} TO {date_to}])'
        cursor = "*"
        while cursor:
            data = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
                {"query": query, "format": "json", "pageSize": 100, "resultType": "lite", "cursorMark": cursor}))
            if data is None: failures.append({"source": "europepmc", "query": phrase, "error": "request failed"}); break
            for r in data.get("resultList", {}).get("result", []):
                title = r.get("title") or ""
                if any(n in title.lower() for n in known_names): continue      # tracked instruments are handled per instrument
                key = norm_doi(r.get("doi")) or f"pmid:{r.get('pmid')}" or norm_title(title)
                out.setdefault(key, {"doi": norm_doi(r.get("doi")), "pmid": r.get("pmid"), "title": title,
                                     "date": r.get("firstPublicationDate"), "venue": r.get("journalTitle"), "matched_phrase": phrase})
            nxt = data.get("nextCursorMark"); cursor = nxt if nxt and nxt != cursor else None
    items = sorted(out.values(), key=lambda c: (c["doi"] or "", c["title"]))
    return items, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=False)
    ap.add_argument("--to", dest="date_to", required=False)
    ap.add_argument("--instrument", action="append", help="instrument id; repeatable; default all")
    ap.add_argument("--out", help="candidates file to write")
    ap.add_argument("--no-verify", action="store_true", help="skip Crossref verification")
    ap.add_argument("--recall", help="dataset JSON: report the fraction of its cited DOIs the harvester finds in the window")
    a = ap.parse_args()
    cfg = json.loads(QUERIES.read_text(encoding="utf-8"))
    instruments = cfg["instruments"]
    if a.instrument:
        instruments = {k: v for k, v in instruments.items() if k in a.instrument}
    if a.recall:
        d = json.loads(Path(a.recall).read_text(encoding="utf-8"))
        cited = {}
        for r in d["records"]:
            if r.get("parent_id") or r["instrument_id"] not in instruments: continue
            for c in r.get("citations", []):
                nd = norm_doi(c.get("doi"))
                if nd: cited.setdefault(nd, set()).add(r["instrument_id"])
        years = [int(c["year"]) for r in d["records"] for c in r.get("citations", []) if str(c.get("year", "")).isdigit()]
        date_from = a.date_from or f"{min(years)}-01-01"; date_to = a.date_to or f"{max(years)}-12-31"
        items, dropped, failures, _ = harvest(instruments, date_from, date_to, cfg, verify=False)
        found = {c["doi"] for c in items if c["doi"]}
        hit = sorted(doi for doi in cited if doi in found)
        miss = sorted(doi for doi in cited if doi not in found)
        report = {"window": [date_from, date_to], "cited_dois": len(cited), "found": len(hit), "recall": round(len(hit) / max(1, len(cited)), 3),
                  "candidates_total": len(items), "missed": [{"doi": m, "instruments": sorted(cited[m])} for m in miss], "failures": failures,
                  "note": "Regression check on the queries. Not an estimate of coverage of new literature."}
        out = Path(a.out) if a.out else None
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if out: out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text + "\n", encoding="utf-8")
        print(f"recall {report['recall']} ({len(hit)}/{len(cited)} cited DOIs found among {len(items)} candidates; {len(failures)} request failures)")
        return
    if not (a.date_from and a.date_to):
        sys.exit("--from and --to are required (YYYY-MM-DD)")
    items, dropped, failures, seen = harvest(instruments, a.date_from, a.date_to, cfg, verify=not a.no_verify)
    known = [n.lower() for spec in cfg["instruments"].values() for n in spec["names"]]
    new_items, new_failures = new_instrument_candidates(cfg, a.date_from, a.date_to, known)
    failures += new_failures
    result = {"harvester": "tools/harvest.py 0.1", "queries": cfg["version"], "window": [a.date_from, a.date_to],
              "instruments": sorted(instruments), "sources": ["openalex", "europepmc", "crossref" if not a.no_verify else None],
              "candidates": items, "dropped": dropped, "failures": failures, "seen_without_property_terms": seen,
              "new_instrument_candidates": new_items,
              "note": "Candidates are works that name an instrument and a psychometric property term in title or abstract. Nothing here is a grade, a judgement or a registry change."}
    result["sources"] = [s for s in result["sources"] if s]
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print(f"{len(items)} candidates, {len(dropped)} dropped by exclusion, {len(new_items)} new-instrument candidates, {len(failures)} request failures -> {a.out or 'stdout'}", file=sys.stderr)


if __name__ == "__main__":
    main()
