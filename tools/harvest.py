#!/usr/bin/env python3
"""Deterministic evidence harvester for the instrument registry.

Queries the open scholarly indexes directly and writes one candidates file. No language model is involved:
saved source responses and pinned code and configuration support reproducible replay, every candidate records
the route it came by, and every channel records whether it completed. Live index results can change between
requests; a run's envelope records what was retrieved, not what the index will say tomorrow.

    python tools/harvest.py --from 2026-08-01 --to 2026-09-05 --out evidence/candidates/2026-09.json
    python tools/harvest.py --instrument isi --from 2026-01-01 --to 2026-09-05 --no-verify
    python tools/harvest.py --self-test

Configuration: evidence/queries/instruments-v1.json. Three retrieval routes per parent record:

  names        exact long-name phrases in title or abstract (OpenAlex, Europe PMC)
  abbreviation an abbreviation AND its required context terms AND a property term (OpenAlex, Europe PMC)
  cites        works citing each citation seed (OpenAlex)

plus one untargeted channel for validation papers in working populations that name no tracked instrument,
whose hits go to a separate admission-candidate list.

Every hit from the names and cites routes is retained as a candidate. A hit whose title or abstract carries a
psychometric property term gets screening_priority "normal"; one without gets "low" and an empty property list,
because the abstract may be missing or the evidence may be described in other words. Nothing is dropped by
this tool except a title carrying one of the instrument's configured exclusion terms, and that drop is counted.
The abbreviation route requires a property term server-side and locally, as the design states.

Sources: Europe PMC REST for the names and abbreviation routes; OpenAlex for the cites route, and for the names and
abbreviation routes as well when OPENALEX_API_KEY is set. Keyless OpenAlex use has a daily credit budget (1,000
credits, 10 per search at the time of writing), which a full run of every route exceeds; the 24 citation lookups
fit. Crossref for DOI verification and the update-to field. The mailto identifies the steward so a runaway
script can be reported; it is not a secret. A key, if used, is read from the environment and never logged.
Abstracts are read for matching and not stored: metadata APIs can carry copyrighted abstracts.
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "evidence" / "queries" / "instruments-v1.json"
MAILTO = "registry@openworkplacehealth.org"
UA = f"OWHS-harvester/0.2 (https://openworkplacehealth.org; mailto:{MAILTO})"
PAUSE = 0.5
OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY")          # optional; restores OpenAlex on every route
PAGE_BUDGET = 25            # pages per channel; reaching it marks the channel partial rather than looping
RETRY_BUDGET = 120          # seconds: the longest server-requested wait honoured inside a run; longer defers the channel
SCHEMA_VERSION = "1.1"          # 1.1 adds cycle, expected_channels, channels_not_complete, watermark_proposal


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
                wait = retry_after_seconds(e.headers.get("Retry-After"))
                if wait is not None and wait > RETRY_BUDGET:
                    return None, f"http {e.code}, retry-after {wait}s exceeds the run's wait budget; channel deferred"
                time.sleep(wait if wait is not None else 3 * (attempt + 1)); continue
            return None, f"http {e.code}"
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None, "exhausted retries"


def retry_after_seconds(value):
    """Retry-After as seconds, from either the delta-seconds or the HTTP-date form. None when absent or unparseable."""
    if not value: return None
    v = value.strip()
    if v.isdigit(): return int(v)
    try:
        import email.utils
        dt = email.utils.parsedate_to_datetime(v)
        return max(0, int((dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
    except Exception:
        return None


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
    """One OpenAlex channel on publication date (date_from None: no date filter, a full-history run). search may be None when
    filter_extra carries the whole filter (cites:). OpenAlex's from_updated_date filter needs a premium key and is not used."""
    hits, pages, err, reported = [], 0, None, None
    parts = [] if date_from is None else [f"from_publication_date:{date_from},to_publication_date:{date_to}"]
    if filter_extra: parts.insert(0, filter_extra)
    if search: parts.insert(0, f"title_and_abstract.search:{search}")
    flt = ",".join(parts)
    q = {"filter": flt, "select": "id,doi,title,publication_date,primary_location,ids,abstract_inverted_index,type,language",
         "per-page": 200, "mailto": MAILTO, "cursor": "*"}
    if OPENALEX_KEY: q["api_key"] = OPENALEX_KEY
    while q["cursor"]:
        data, err = get("https://api.openalex.org/works?" + urllib.parse.urlencode(q))
        if err: break
        pages += 1
        reported = (data.get("meta") or {}).get("count", reported)
        hits += [openalex_work(x) for x in data.get("results", [])]
        q["cursor"] = (data.get("meta") or {}).get("next_cursor")
        if pages >= PAGE_BUDGET and q["cursor"]: err = "page budget reached"; break
    return hits, pages, reported, err


def europepmc_channel(query, date_from, date_to, date_field="FIRST_PDATE"):
    """One Europe PMC channel. date_field FIRST_PDATE is the publication date; FIRST_IDATE is the date Europe PMC first indexed
    the record, used for the ingestion catch-up so a work published earlier but indexed late is still seen. None: no date filter."""
    hits, pages, err, reported = [], 0, None, None
    full = f"({query}) AND ({date_field}:[{date_from} TO {date_to}])" if date_from is not None else f"({query})"
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

def channel_id(instrument_id, route, source, date_basis, query):
    return hashlib.sha256(f"{instrument_id}|{route}|{source}|{date_basis}|{query}".encode()).hexdigest()[:16]


def planned_channels(rec, cfg, date_from, date_to, catch_from=None, full_history=False):
    """Every channel a run plans for one record, as descriptors (no runner, no network): instrument, route, source, date basis,
    exact query, channel id, and for a provider filter that is not available in this configuration the reason. The date bases are
    publication (the requested window), first_indexed (Europe PMC's first-index date over the catch-up window, so late indexing is
    caught) and full_history (no date filter; quarterly). The harvester's runners and the cycle verifier both derive from this list,
    so the denominator the verifier uses is exactly what the harvester planned."""
    props = cfg["property_terms"]
    out = []
    def add(route, source, query, basis, unavailable=None):
        out.append({"instrument_id": rec["instrument_id"], "route": route, "source": source, "date_basis": basis, "query": query,
                    "channel_id": channel_id(rec["instrument_id"], route, source, basis, query), "unavailable": unavailable})
    bases = [("publication", date_from, date_to)] + ([("first_indexed", catch_from, date_to)] if catch_from else []) + ([("full_history", None, None)] if full_history else [])
    for name in rec["names"]:
        for basis, f, t in bases:
            if basis == "first_indexed":
                add("names", "europepmc", f"TITLE_ABS:{q_phrase(name)}", basis)
                add("names", "openalex", q_phrase(name), basis, unavailable="OpenAlex update-date filtering needs a premium key; not configured")
                continue
            if OPENALEX_KEY: add("names", "openalex", q_phrase(name), basis)
            add("names", "europepmc", f"TITLE_ABS:{q_phrase(name)}", basis)
    ctx = rec.get("abbreviation_context") or []
    for ab in rec.get("abbreviations") or []:
        if not ctx: continue          # an abbreviation without required context is never queried bare
        oa = f'{q_phrase(ab)} AND ({" OR ".join(q_phrase(c) for c in ctx)})'      # property terms are applied locally; a 28-term OR makes OpenAlex time out
        ep = f'TITLE_ABS:{q_phrase(ab)} AND ({epmc_terms("TITLE_ABS", ctx)}) AND ({epmc_terms("TITLE_ABS", props)})'
        for basis, f, t in bases:
            if basis == "full_history": continue                     # the quarterly rerun covers names and citation links
            if basis == "first_indexed": add("abbreviation", "europepmc", ep, basis); continue
            if OPENALEX_KEY: add("abbreviation", "openalex", oa, basis)
            add("abbreviation", "europepmc", ep, basis)
    for seed in rec.get("citation_seeds") or []:
        wid = seed.get("openalex_id")
        if not wid: continue
        for basis, f, t in bases:
            if basis == "first_indexed": continue                    # citation links have no index-date filter without a premium key
            add("cites", "openalex", f"cites:{wid}", basis)
    return out


def channels_for(rec, cfg, date_from, date_to, catch_from=None, full_history=False):
    """Yield (descriptor, runner) for one record, from planned_channels."""
    windows = {"publication": (date_from, date_to), "first_indexed": (catch_from, date_to), "full_history": (None, None)}
    for ch in planned_channels(rec, cfg, date_from, date_to, catch_from, full_history):
        f, t = windows[ch["date_basis"]]
        if ch["unavailable"]:
            yield ch, None; continue
        if ch["source"] == "europepmc":
            field = "FIRST_IDATE" if ch["date_basis"] == "first_indexed" else "FIRST_PDATE"
            yield ch, (lambda q=ch["query"], f=f, t=t, field=field: europepmc_channel(q, f, t, field))
        elif ch["route"] == "cites":
            yield ch, (lambda q=ch["query"], f=f, t=t: openalex_channel(None, f, t, filter_extra=q))
        else:
            yield ch, (lambda q=ch["query"], f=f, t=t: openalex_channel(q, f, t))


def new_instrument_channels(cfg, date_from, date_to):
    q = cfg.get("new_instrument_query")
    if not q: return
    ctx, obj, ev = q["context_terms"], q["object_terms"], q["evidence_terms"]
    ep = f'({epmc_terms("TITLE_ABS", ctx)}) AND ({epmc_terms("TITLE_ABS", obj)}) AND ({epmc_terms("TITLE", ev)})'
    desc = {"instrument_id": None, "route": "new-instrument", "source": "europepmc", "date_basis": "publication", "query": ep,
            "channel_id": channel_id(None, "new-instrument", "europepmc", "publication", ep), "unavailable": None}
    yield desc, (lambda s=ep: europepmc_channel(s, date_from, date_to))


# ---------- assembly ----------

def matched_terms(text, terms):
    t = text.lower()
    return sorted({term for term in terms if term.lower() in t})


def harvest(cfg, records, date_from, date_to, verify=True, now=None, catch_from=None, full_history=False):
    now = now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    props = cfg["property_terms"]
    by_id = {r["instrument_id"]: r for r in records}
    def tracked_mentions(text):
        """Instrument ids whose long name appears as a phrase, or whose abbreviation appears as a whole token beside a context term."""
        t = " " + re.sub(r"\s+", " ", text.lower()) + " "
        out = []
        for r in cfg["records"]:
            if any(re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", t) for n in r["names"]):
                out.append(r["instrument_id"]); continue
            ctx = [c.lower() for c in (r.get("abbreviation_context") or [])]
            if any(re.search(r"(?<![a-z0-9])" + re.escape(a.lower()) + r"(?![a-z0-9])", t) for a in (r.get("abbreviations") or [])) \
                    and any(c in t for c in ctx):
                out.append(r["instrument_id"])
        return out
    candidates, low, channels, warnings = {}, {}, [], []

    def absorb(rec_id, route, w, ch):
        terms = matched_terms(w["title"] + " " + w["abstract"], props)
        title_l = w["title"].lower()
        if rec_id and any(x.lower() in title_l for x in (by_id[rec_id].get("exclusions") or [])):
            ch["excluded"] = ch.get("excluded", 0) + 1; return
        if not terms and route == "abbreviation":
            # the abbreviation route's rule is abbreviation AND context AND property term; a server hit without a term is out of rule
            ch["out_of_rule"] = ch.get("out_of_rule", 0) + 1; return
        if not terms:
            low.setdefault(rec_id, {}).setdefault(route, 0); low[rec_id][route] += 1
        key = w["doi"] or (f"pmid:{w['pmid']}" if w["pmid"] else None) or (f"openalex:{w['openalex']}" if w["openalex"] else None) or f"title:{norm_title(w['title'])}"
        c = candidates.setdefault(key, {"id": key, "doi": w["doi"], "pmid": w["pmid"], "openalex": w["openalex"], "title": w["title"],
                                        "publication_date": w["date"], "venue": w["venue"], "type": w["type"], "language": w["language"],
                                        "instruments": [], "routes": [], "property_terms": [], "screening_priority": "low",
                                        "first_seen_at": now, "screening_state": "not_screened"})
        if terms: c["screening_priority"] = "normal"
        if rec_id not in c["instruments"]: c["instruments"].append(rec_id)
        tag = f"{route}:{ch['source']}:{rec_id}"
        if tag not in c["routes"]: c["routes"].append(tag)
        c["property_terms"] = sorted(set(c["property_terms"]) | set(terms))
        for k in ("doi", "pmid", "openalex", "language"):
            if not c[k] and w.get(k): c[k] = w[k]

    for rec in records:
        for desc, run in channels_for(rec, cfg, date_from, date_to, catch_from, full_history):
            if run is None:      # a provider filter this configuration cannot use: logged as unavailable, never as run
                channels.append({**desc, "pages": 0, "reported_hits": None, "collected_hits": 0, "outcome": "unavailable", "error": desc["unavailable"]}); continue
            hits, pages, reported, err = run()
            ch = {**desc, "pages": pages, "reported_hits": reported, "collected_hits": len(hits),
                  "outcome": "complete" if not err else ("partial" if hits else "failed"), "error": err}
            channels.append(ch)
            for w in hits: absorb(rec["instrument_id"], desc["route"], w, ch)
    new_items = {}
    for desc, run in new_instrument_channels(cfg, date_from, date_to):
        hits, pages, reported, err = run()
        channels.append({**desc, "pages": pages, "reported_hits": reported, "collected_hits": len(hits), "outcome": "complete" if not err else ("partial" if hits else "failed"), "error": err})
        for w in hits:
            overlap = tracked_mentions(w["title"] + " " + w["abstract"])
            key = w["doi"] or (f"pmid:{w['pmid']}" if w["pmid"] else None) or f"title:{norm_title(w['title'])}"
            new_items.setdefault(key, {"id": key, "doi": w["doi"], "pmid": w["pmid"], "title": w["title"], "publication_date": w["date"],
                                       "venue": w["venue"], "language": w["language"], "possible_tracked_instrument_overlap": overlap,
                                       "screening_state": "not_screened"})
    # Same normalised title, one side without a DOI, same publication year where both are known, and consistent
    # identifiers: merge, record it, and make the DOI the canonical id. Anything weaker is left as two records
    # linked by possible_duplicate_of. Two DOIs sharing a title are never merged.
    by_title = {}
    for key, c in list(candidates.items()):
        nt = norm_title(c["title"])
        if not nt: continue
        if nt in by_title and by_title[nt] != key:
            other = candidates[by_title[nt]]
            ya, yb = (other.get("publication_date") or "")[:4], (c.get("publication_date") or "")[:4]
            ids_conflict = any(other[k] and c[k] and other[k] != c[k] for k in ("doi", "pmid", "openalex"))
            if ids_conflict or (ya and yb and ya != yb) or (other["doi"] and c["doi"]):
                c["possible_duplicate_of"] = other["id"]; other.setdefault("possible_duplicates", []).append(key)
                warnings.append({"type": "same title, not merged", "a": other["id"], "b": key, "reason": "conflicting identifiers or year" if (ids_conflict or (ya and yb and ya != yb)) else "two DOIs"})
                continue
            for k in ("instruments", "routes", "property_terms"): other[k] = sorted(set(other[k]) | set(c[k]))
            for k in ("doi", "pmid", "openalex", "language"):
                if not other[k] and c[k]: other[k] = c[k]
            if c.get("screening_priority") == "normal": other["screening_priority"] = "normal"
            other.setdefault("merged_from", []).append(key); del candidates[key]
            if other["doi"] and other["id"] != other["doi"]:
                candidates[other["doi"]] = candidates.pop(other["id"]); other["merged_from"].append(other["id"]); other["id"] = other["doi"]; by_title[nt] = other["doi"]
        else:
            by_title[nt] = key
    if verify:
        for c in candidates.values():
            c["crossref"] = crossref_check(c["doi"]) if c["doi"] else {"resolves": None}
    items = sorted(candidates.values(), key=lambda c: (c["doi"] or "~", c["title"]))
    for c in items: c["instruments"].sort(); c["routes"].sort()
    new_list = sorted(new_items.values(), key=lambda c: (c["doi"] or "~", c["title"]))
    return items, new_list, channels, low, warnings


def envelope(cfg, records, date_from, date_to, started, items, new_list, channels, low, warnings, sources):
    ran = [c for c in channels if c["outcome"] != "unavailable"]
    failed = [c for c in ran if c["outcome"] != "complete"]
    if not ran:
        status = "failed"; warnings = warnings + [{"type": "configuration", "detail": "no retrieval channels were planned"}]
    else:
        status = "complete" if not failed else ("failed" if all(c["outcome"] == "failed" for c in ran) else "partial")
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
            "low_priority_counts": low, "warnings": warnings,
            "note": "A candidate is a work retrieved by an instrument's names, abbreviation or citation route. screening_priority normal means a psychometric property term appears in its title or abstract; low means none was found, which may mean a missing abstract. Nothing here is a grade, a judgement or a registry change. status complete means every planned retrieval channel completed all its pages; it says nothing about screening."}


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
    assert st([]) == "failed", "an empty channel set is a configuration failure, not a complete run"
    assert norm_doi("10.1027//1015-5759.19.1.12") == "10.1027//1015-5759.19.1.12", "the OLBI double slash survives"
    assert retry_after_seconds("120") == 120 and retry_after_seconds(None) is None and retry_after_seconds("garbage") is None
    q = json.loads(QUERIES.read_text(encoding="utf-8"))
    ids = [r["instrument_id"] for r in q["records"]]
    assert len(ids) == len(set(ids)) == 27, "27 unique parent records expected"
    for r in q["records"]:
        assert r["names"] and r["canonical_name"] == r["names"][0]
        if r.get("abbreviations"): assert r.get("abbreviation_context"), f"{r['instrument_id']}: abbreviations need context"
    from cycle import expected_channels, channels_not_complete
    exp = expected_channels(q, "2026-01-01", "2026-01-31", "2025-11-02", False)
    ids = [c["channel_id"] for c in exp]
    assert len(ids) == len(set(ids)), "channel ids must be unique"
    assert any(c["date_basis"] == "first_indexed" and c["source"] == "europepmc" for c in exp), "catch-up channels planned on first-index date"
    assert any(c["unavailable"] for c in exp), "the unavailable OpenAlex update-date filter is listed, not hidden"
    exp_q = expected_channels(q, "2026-01-01", "2026-01-31", None, True)
    assert any(c["date_basis"] == "full_history" and c["route"] == "cites" for c in exp_q), "quarterly full-history citation channels planned"
    # dropping one sibling alias while its sibling completes leaves the pair incomplete at channel granularity
    two = [c for c in exp if c["route"] == "names" and c["date_basis"] == "publication" and c["source"] == "europepmc"]
    rec_two = next(r for r in q["records"] if len(r["names"]) > 1)
    sib = [c for c in two if c["instrument_id"] == rec_two["instrument_id"]]
    ran = [{**c, "outcome": "complete"} for c in exp if c["channel_id"] != sib[0]["channel_id"]]
    missing = channels_not_complete(exp, ran)
    assert [m["channel_id"] for m in missing] == [sib[0]["channel_id"]], "a missing alias channel must stay visible in the denominator"
    assert channels_not_complete(exp, [{**c, "outcome": "complete"} for c in exp]) == [], "all complete: nothing missing"
    unav = [c for c in exp if c["unavailable"]][0]
    assert channels_not_complete(exp, [{**c, "outcome": ("unavailable" if c["channel_id"] == unav["channel_id"] else "complete")} for c in exp]) == [], "a declared-unavailable channel reported as unavailable is not counted missing"
    assert channels_not_complete(exp, [{**c, "outcome": ("complete" if c["channel_id"] != unav["channel_id"] else "complete")} for c in exp]) == [], "an unavailable channel that did run and complete is also fine"
    print(f"self-test passed: canonicalisation, matching, status logic, query file shape, {len(exp)} expected channels at query granularity with one catch-up basis, {len(exp_q)} with the quarterly rerun")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from"); ap.add_argument("--to", dest="date_to")
    ap.add_argument("--instrument", action="append"); ap.add_argument("--out")
    ap.add_argument("--no-verify", action="store_true"); ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cycle-id", help="from tools/cycle.py window; a planned cycle is YYYY-MM, a manual one manual-FROM-TO")
    ap.add_argument("--cycle-kind", choices=["planned", "manual"])
    ap.add_argument("--catch-from", help="start of the ingestion catch-up window (first-index date, Europe PMC); from tools/cycle.py window")
    ap.add_argument("--full-history", action="store_true", help="quarterly: names and citation links with no date filter, beside the windowed channels")
    a = ap.parse_args()
    if a.self_test: return self_test()
    if not (a.date_from and a.date_to): sys.exit("--from and --to are required (YYYY-MM-DD)")
    try:
        d0, d1 = datetime.date.fromisoformat(a.date_from), datetime.date.fromisoformat(a.date_to)
    except ValueError:
        sys.exit("configuration error: dates must be YYYY-MM-DD")
    if d1 < d0: sys.exit("configuration error: --to precedes --from")
    cfg = json.loads(QUERIES.read_text(encoding="utf-8"))
    known_ids = {r["instrument_id"] for r in cfg["records"]}
    unknown = set(a.instrument or []) - known_ids
    if unknown: sys.exit(f"configuration error: unknown instrument ids {sorted(unknown)}")
    records = [r for r in cfg["records"] if not a.instrument or r["instrument_id"] in a.instrument]
    if not records: sys.exit("configuration error: no records selected")
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    if a.catch_from:
        try: cf = datetime.date.fromisoformat(a.catch_from)
        except ValueError: sys.exit("configuration error: --catch-from must be YYYY-MM-DD")
        if cf > d1: sys.exit("configuration error: --catch-from after --to")
    items, new_list, channels, low, warnings = harvest(cfg, records, a.date_from, a.date_to, verify=not a.no_verify, now=started, catch_from=a.catch_from, full_history=a.full_history)
    sources = ["europepmc", "openalex (cites" + (", names, abbreviation)" if OPENALEX_KEY else " only: no API key)")] + (["crossref"] if not a.no_verify else [])
    out = envelope(cfg, records, a.date_from, a.date_to, started, items, new_list, channels, low, warnings, sources)
    out["full_inventory"] = not a.instrument       # a manual one-instrument run is not a monthly cycle
    if a.instrument and a.cycle_kind == "planned": sys.exit("configuration error: a planned cycle covers the full inventory; use no --cycle-kind or manual for a one-instrument run")
    out["cycle"] = {"id": a.cycle_id or f"manual-{a.date_from}-{a.date_to}", "kind": a.cycle_kind or "manual",
                    "note": "planned cycles are named by the month of the run; the publication window is separate and recorded in requested_window"}
    from cycle import expected_channels, channels_not_complete
    out["date_bases"] = {"publication": {"from": a.date_from, "to": a.date_to}, "first_indexed": ({"from": a.catch_from, "to": a.date_to} if a.catch_from else None), "full_history": bool(a.full_history)}
    out["expected_channels"] = expected_channels(cfg, a.date_from, a.date_to, a.catch_from, a.full_history)
    out["channels_not_complete"] = channels_not_complete(out["expected_channels"], channels)
    if out["status"] == "complete" and out["full_inventory"] and not out["channels_not_complete"] and a.cycle_kind == "planned":
        out["watermark_proposal"] = {"query_sha256": out["query_sha256"], "last_complete_to": a.date_to, "catch_from": a.catch_from, "cycle_id": out["cycle"]["id"], "run_id": out["run_id"],
                                     "channels_complete": len(out["expected_channels"]),
                                     "note": "apply with tools/cycle.py advance --artefact FILE in the screening pull request; nothing advances automatically"}
    else:
        out["watermark_proposal"] = None
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if a.out: Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(text, encoding="utf-8")
    else: sys.stdout.write(text)
    n_fail = sum(1 for c in channels if c["outcome"] != "complete")
    n_low = sum(1 for c in items if c.get("screening_priority") == "low")
    print(f"status {out['status']}: {len(items)} candidates ({n_low} low priority), {len(new_list)} new-instrument candidates, "
          f"{len(channels)} channels ({n_fail} not complete) -> {a.out or 'stdout'}", file=sys.stderr)
    if out["status"] != "complete":
        sys.exit(2)          # the artefact is written; the process says the cycle is incomplete


if __name__ == "__main__":
    main()
