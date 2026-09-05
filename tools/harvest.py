#!/usr/bin/env python3
"""Deterministic evidence harvester for the instrument registry.

Queries the open scholarly indexes directly and writes one candidates file. No language model is involved:
the same inputs on the same day produce the same candidate set, every candidate records the route it came
by, and every channel records whether it completed.

    python tools/harvest.py --from 2026-08-01 --to 2026-09-05 --out evidence/candidates/2026-09.json
    python tools/harvest.py --instrument isi --from 2026-01-01 --to 2026-09-05 --no-verify
    python tools/harvest.py --self-test

Configuration: evidence/queries/instruments-v1.json. Three retrieval routes per parent record:

  names        exact long-name phrases in title or abstract (OpenAlex, Europe PMC)
  abbreviation an abbreviation AND its required context terms AND a property term (OpenAlex, Europe PMC)
  cites        works citing each citation seed (OpenAlex)

plus one untargeted channel for validation papers in working populations that name no tracked instrument,
whose hits go to a separate admission-candidate list.

A hit becomes a candidate when a psychometric property term appears in its title or abstract. A hit without
one is counted per instrument and route as a use, not evidence about the instrument, and is not stored. That
filter is applied to every route here; the design asked for the names and cites routes to be unfiltered, and
the counts show why they are not: over two months the unfiltered routes returned more than ten uses for
every candidate. Screening capacity is the constraint; the counts are published so the trade-off is visible.

Sources: OpenAlex (polite pool), Europe PMC REST, Crossref for DOI verification and the update-to field.
No credentials. The mailto identifies the steward so a runaway script can be reported; it is not a secret.
Abstracts are read for matching and not stored: metadata APIs can carry copyrighted abstracts.
"""
import argparse, datetime, hashlib, json, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "evidence" / "queries" / "instruments-v1.json"
MAILTO = "registry@openworkplacehealth.org"
UA = f"OWHS-harvester/0.2 (https://openworkplacehealth.org; mailto:{MAILTO})"
PAUSE = 0.5
PAGE_BUDGET = 25            # pages per channel; reaching it marks the channel partial rather than looping
SCHEMA_VERSION = "1.0"


# ---------- http ----------

def get(url, tries=5):
    """GET JSON with a polite pause, Retry-After honoured, bounded backoff. Returns (data, error)."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            time.sleep(PAUSE)
            return data, None
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                ra = e.headers.get("Retry-After")
                time.sleep(min(60, float(ra)) if ra and ra.isdigit() else 3 * (attempt + 1)); continue
            return None, f"http {e.code}"
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None, "exhausted retries"


def norm_doi(doi):
    if not doi: return None
    d = doi.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = urllib.parse.unquote(d).lower()
    return d or None


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


# ---------- sources ----------

def openalex_work(w):
    inv = w.get("abstract_inverted_index") or {}
    words = sorted(((pos, tok) for tok, poss in inv.items() for pos in poss), key=lambda x: x[0])
    loc = w.get("primary_location") or {}
    return {"openalex": (w.get("id") or "").rsplit("/", 1)[-1] or None, "doi": norm_doi(w.get("doi")),
            "pmid": ((w.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None,
            "title": w.get("title") or "", "date": w.get("publication_date"), "venue": (loc.get("source") or {}).get("display_name"),
            "type": w.get("type"), "language": w.get("language"), "abstract": " ".join(t for _, t in words)}


def openalex_channel(search, date_from, date_to, filter_extra=None):
    """One OpenAlex channel. search may be None when filter_extra carries the whole filter (cites:)."""
    hits, pages, err, reported = [], 0, None, None
    flt = f"from_publication_date:{date_from},to_publication_date:{date_to}"
    if filter_extra: flt = filter_extra + "," + flt
    if search: flt = f"title_and_abstract.search:{search}," + flt
    q = {"filter": flt, "select": "id,doi,title,publication_date,primary_location,ids,abstract_inverted_index,type,language",
         "per-page": 200, "mailto": MAILTO, "cursor": "*"}
    while q["cursor"]:
        data, err = get("https://api.openalex.org/works?" + urllib.parse.urlencode(q))
        if err: break
        pages += 1
        reported = (data.get("meta") or {}).get("count", reported)
        hits += [openalex_work(x) for x in data.get("results", [])]
        q["cursor"] = (data.get("meta") or {}).get("next_cursor")
        if pages >= PAGE_BUDGET and q["cursor"]: err = "page budget reached"; break
    return hits, pages, reported, err


def europepmc_channel(query, date_from, date_to):
    hits, pages, err, reported = [], 0, None, None
    full = f"({query}) AND (FIRST_PDATE:[{date_from} TO {date_to}])"
    cursor = "*"
    while cursor:
        q = {"query": full, "format": "json", "pageSize": 100, "resultType": "core", "cursorMark": cursor}
        data, err = get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(q))
        if err: break
        pages += 1
        reported = data.get("hitCount", reported)
        for r in data.get("resultList", {}).get("result", []):
            hits.append({"openalex": None, "doi": norm_doi(r.get("doi")), "pmid": r.get("pmid"), "title": r.get("title") or "",
                         "date": r.get("firstPublicationDate"), "venue": ((r.get("journalInfo") or {}).get("journal") or {}).get("title") or r.get("journalTitle"),
                         "type": r.get("pubType"), "language": r.get("language"), "abstract": r.get("abstractText") or ""})
        nxt = data.get("nextCursorMark"); cursor = nxt if nxt and nxt != cursor else None
        if pages >= PAGE_BUDGET and cursor: err = "page budget reached"; break
    return hits, pages, reported, err


def crossref_check(doi):
    data, err = get(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}?mailto={MAILTO}")
    if err or not data: return {"resolves": False if err == "http 404" else None, "error": err}
    m = data.get("message", {})
    return {"resolves": True, "type": m.get("type"), "update_to": m.get("update-to"), "updated_by": m.get("updated-by")}


# ---------- query construction ----------

def q_phrase(s): return '"' + s.replace('"', "") + '"'

def epmc_terms(field, terms): return " OR ".join(f"{field}:{q_phrase(t)}" for t in terms)

def channels_for(rec, cfg, date_from, date_to):
    """Yield (route, source, query, runner) for one record."""
    props = cfg["property_terms"]
    for name in rec["names"]:
        yield ("names", "openalex", q_phrase(name), lambda n=name: openalex_channel(q_phrase(n), date_from, date_to))
        yield ("names", "europepmc", f"TITLE_ABS:{q_phrase(name)}", lambda n=name: europepmc_channel(f"TITLE_ABS:{q_phrase(n)}", date_from, date_to))
    ctx = rec.get("abbreviation_context") or []
    for ab in rec.get("abbreviations") or []:
        if not ctx: continue          # an abbreviation without required context is never queried bare
        oa = f'{q_phrase(ab)} AND ({" OR ".join(q_phrase(c) for c in ctx)})'      # property terms are applied locally; a 28-term OR makes OpenAlex time out
        ep = f'TITLE_ABS:{q_phrase(ab)} AND ({epmc_terms("TITLE_ABS", ctx)}) AND ({epmc_terms("TITLE_ABS", props)})'
        yield ("abbreviation", "openalex", oa, lambda s=oa: openalex_channel(s, date_from, date_to))
        yield ("abbreviation", "europepmc", ep, lambda s=ep: europepmc_channel(s, date_from, date_to))
    for seed in rec.get("citation_seeds") or []:
        wid = seed.get("openalex_id")
        if not wid: continue
        yield ("cites", "openalex", f"cites:{wid}", lambda w=wid: openalex_channel(None, date_from, date_to, filter_extra=f"cites:{w}"))


def new_instrument_channels(cfg, date_from, date_to):
    q = cfg.get("new_instrument_query")
    if not q: return
    ctx, obj, ev = q["context_terms"], q["object_terms"], q["evidence_terms"]
    ep = f'({epmc_terms("TITLE_ABS", ctx)}) AND ({epmc_terms("TITLE_ABS", obj)}) AND ({epmc_terms("TITLE", ev)})'
    yield ("new-instrument", "europepmc", ep, lambda s=ep: europepmc_channel(s, date_from, date_to))


# ---------- assembly ----------

def matched_terms(text, terms):
    t = text.lower()
    return sorted({term for term in terms if term.lower() in t})


def harvest(cfg, records, date_from, date_to, verify=True, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    props = cfg["property_terms"]
    by_id = {r["instrument_id"]: r for r in records}
    known = [n.lower() for r in cfg["records"] for n in r["names"] + (r.get("abbreviations") or [])]
    candidates, uses, channels, warnings = {}, {}, [], []

    def absorb(rec_id, route, w, ch):
        terms = matched_terms(w["title"] + " " + w["abstract"], props)
        title_l = w["title"].lower()
        if rec_id and any(x.lower() in title_l for x in (by_id[rec_id].get("exclusions") or [])):
            ch["excluded"] = ch.get("excluded", 0) + 1; return
        if not terms:
            uses.setdefault(rec_id, {}).setdefault(route, 0); uses[rec_id][route] += 1; return
        key = w["doi"] or (f"pmid:{w['pmid']}" if w["pmid"] else None) or (f"openalex:{w['openalex']}" if w["openalex"] else None) or f"title:{norm_title(w['title'])}"
        c = candidates.setdefault(key, {"id": key, "doi": w["doi"], "pmid": w["pmid"], "openalex": w["openalex"], "title": w["title"],
                                        "publication_date": w["date"], "venue": w["venue"], "type": w["type"], "language": w["language"],
                                        "instruments": [], "routes": [], "property_terms": [], "first_seen_at": now, "screening_state": "not_screened"})
        if rec_id not in c["instruments"]: c["instruments"].append(rec_id)
        tag = f"{route}:{ch['source']}:{rec_id}"
        if tag not in c["routes"]: c["routes"].append(tag)
        c["property_terms"] = sorted(set(c["property_terms"]) | set(terms))
        for k in ("doi", "pmid", "openalex", "language"):
            if not c[k] and w.get(k): c[k] = w[k]

    for rec in records:
        for route, source, query, run in channels_for(rec, cfg, date_from, date_to):
            hits, pages, reported, err = run()
            ch = {"instrument_id": rec["instrument_id"], "route": route, "source": source, "query": query, "pages": pages,
                  "reported_hits": reported, "collected_hits": len(hits),
                  "outcome": "complete" if not err else ("partial" if hits else "failed"), "error": err}
            channels.append(ch)
            for w in hits: absorb(rec["instrument_id"], route, w, ch)
    new_items = {}
    for route, source, query, run in new_instrument_channels(cfg, date_from, date_to):
        hits, pages, reported, err = run()
        channels.append({"instrument_id": None, "route": route, "source": source, "query": query, "pages": pages, "reported_hits": reported,
                         "collected_hits": len(hits), "outcome": "complete" if not err else ("partial" if hits else "failed"), "error": err})
        for w in hits:
            if any(n in w["title"].lower() for n in known): continue
            key = w["doi"] or (f"pmid:{w['pmid']}" if w["pmid"] else None) or f"title:{norm_title(w['title'])}"
            new_items.setdefault(key, {"id": key, "doi": w["doi"], "pmid": w["pmid"], "title": w["title"], "publication_date": w["date"],
                                       "venue": w["venue"], "language": w["language"], "screening_state": "not_screened"})
    # merge on normalised title where one side lacked a DOI; recorded on the candidate, never silent
    by_title = {}
    for key, c in list(candidates.items()):
        nt = norm_title(c["title"])
        if nt and nt in by_title and by_title[nt] != key:
            other = candidates[by_title[nt]]
            if c["doi"] and other["doi"] and c["doi"] != other["doi"]:
                warnings.append({"type": "same title, different doi", "a": other["doi"], "b": c["doi"]}); continue
            for k in ("instruments", "routes", "property_terms"): other[k] = sorted(set(other[k]) | set(c[k]))
            for k in ("doi", "pmid", "openalex", "language"):
                if not other[k] and c[k]: other[k] = c[k]
            other.setdefault("merged_from", []).append(key); del candidates[key]
        elif nt:
            by_title[nt] = key
    if verify:
        for c in candidates.values():
            c["crossref"] = crossref_check(c["doi"]) if c["doi"] else {"resolves": None}
    items = sorted(candidates.values(), key=lambda c: (c["doi"] or "~", c["title"]))
    for c in items: c["instruments"].sort(); c["routes"].sort()
    new_list = sorted(new_items.values(), key=lambda c: (c["doi"] or "~", c["title"]))
    return items, new_list, channels, uses, warnings


def envelope(cfg, records, date_from, date_to, started, items, new_list, channels, uses, warnings, sources):
    failed = [c for c in channels if c["outcome"] != "complete"]
    status = "complete" if not failed else ("failed" if all(c["outcome"] == "failed" for c in channels) else "partial")
    try: commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip() or None
    except Exception: commit = None
    return {"schema_version": SCHEMA_VERSION, "harvester": "tools/harvest.py 0.2",
            "run_id": hashlib.sha256(f"{date_from}|{date_to}|{started}".encode()).hexdigest()[:16],
            "registry_commit": commit, "query_version": cfg["version"],
            "query_sha256": hashlib.sha256(QUERIES.read_bytes()).hexdigest() if QUERIES.exists() else None,
            "requested_window": {"from": date_from, "to": date_to, "type": "publication date, inclusive"},
            "started_at": started, "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "status": status, "sources": sources, "instruments": sorted(r["instrument_id"] for r in records),
            "channels": channels, "candidates": items, "new_instrument_candidates": new_list,
            "uses_not_stored": uses, "warnings": warnings,
            "note": "A candidate names an instrument and a psychometric property term. Nothing here is a grade, a judgement or a registry change. status complete means every declared retrieval channel completed all pages; it says nothing about screening."}


# ---------- self test ----------

def self_test():
    """Offline checks of the pure functions: DOI canonicalisation, term matching, status logic, query file shape."""
    assert norm_doi("https://doi.org/10.1027//1015-5759.19.1.12") == "10.1027//1015-5759.19.1.12"
    assert norm_doi("10.1002/MPR.145 ") == "10.1002/mpr.145"
    assert norm_doi("https://doi.org/10.1016%2Fs1389-9457%2800%2900065-4") == "10.1016/s1389-9457(00)00065-4"
    assert matched_terms("Validation of the X in workers", ["validation", "Rasch"]) == ["validation"]
    assert matched_terms("A study of X", ["validation"]) == []
    cfg = {"version": "t", "property_terms": ["validation"], "records": [{"instrument_id": "a", "names": ["Alpha Scale"], "abbreviations": [], "abbreviation_context": []}]}
    def st(chs): return envelope(cfg, cfg["records"], "2026-01-01", "2026-01-31", "t", [], [], chs, {}, [], ["s"])["status"]
    assert st([{"source": "s", "outcome": "complete"}]) == "complete"
    assert st([{"source": "s", "outcome": "complete"}, {"source": "s", "outcome": "failed"}]) == "partial"
    assert st([{"source": "s", "outcome": "failed"}]) == "failed"
    q = json.loads(QUERIES.read_text(encoding="utf-8"))
    ids = [r["instrument_id"] for r in q["records"]]
    assert len(ids) == len(set(ids)) == 27, "27 unique parent records expected"
    for r in q["records"]:
        assert r["names"] and r["canonical_name"] == r["names"][0]
        if r.get("abbreviations"): assert r.get("abbreviation_context"), f"{r['instrument_id']}: abbreviations need context"
    print("self-test passed: canonicalisation, matching, status logic, query file shape")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from"); ap.add_argument("--to", dest="date_to")
    ap.add_argument("--instrument", action="append"); ap.add_argument("--out")
    ap.add_argument("--no-verify", action="store_true"); ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: return self_test()
    if not (a.date_from and a.date_to): sys.exit("--from and --to are required (YYYY-MM-DD)")
    cfg = json.loads(QUERIES.read_text(encoding="utf-8"))
    records = [r for r in cfg["records"] if not a.instrument or r["instrument_id"] in a.instrument]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    items, new_list, channels, uses, warnings = harvest(cfg, records, a.date_from, a.date_to, verify=not a.no_verify, now=started)
    sources = ["openalex", "europepmc"] + (["crossref"] if not a.no_verify else [])
    out = envelope(cfg, records, a.date_from, a.date_to, started, items, new_list, channels, uses, warnings, sources)
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if a.out: Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(text, encoding="utf-8")
    else: sys.stdout.write(text)
    n_fail = sum(1 for c in channels if c["outcome"] != "complete")
    print(f"status {out['status']}: {len(items)} candidates, {len(new_list)} new-instrument candidates, {len(channels)} channels ({n_fail} not complete), "
          f"{sum(sum(v.values()) for v in uses.values())} uses not stored -> {a.out or 'stdout'}", file=sys.stderr)


if __name__ == "__main__":
    main()
