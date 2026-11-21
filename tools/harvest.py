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

Sources: Europe PMC REST for the names and abbreviation routes; OpenAlex for the cites route (the provider profile in
the query file decides which routes use OpenAlex; a key never changes the plan). Without OPENALEX_API_KEY, OpenAlex
answers the second page of a cursor-paged query with http 401 ("API key required for cursor paging"), so a citation
channel with more than 200 results in its window ends partial, and keyless calls share a small daily budget per
network address. The channel records the server's reason and the run prints one line saying the secret is the fix.
Crossref for DOI verification and the update-to field. The mailto identifies the steward so a runaway script can be
reported; it is not a secret. A key, if used, is read from the environment and never logged.
Abstracts are read for matching and not stored: metadata APIs can carry copyrighted abstracts.

Progress: one flushed line per channel on stderr as the run goes. --time-budget-minutes: after the budget no new
page, channel or Crossref check starts; what was not reached is recorded with the reason, the file is still written
and the run is partial. Windowed channels run first and the quarterly full-history channels last.
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
POLICY_VERSION = "2026.09-1"      # planning policy shared with tools/cycle.py (window, catch-up, quarterly full history, channel set); the verifier binds a run to it at its head
SCHEMA_VERSION = "1.1"          # 1.1 adds cycle, expected_channels, channels_not_complete, watermark_proposal
DEADLINE = None             # time.monotonic() value after which no new page, channel or Crossref check starts (--time-budget-minutes); None: no budget
BUDGET_REASON = "time budget reached"


def past_deadline():
    return DEADLINE is not None and time.monotonic() >= DEADLINE


def progress(msg):
    """One line on stderr, flushed, so the Actions log shows where a run is while it runs."""
    print(msg, file=sys.stderr, flush=True)


def http_error_text(e):
    """'http CODE' plus the server's own short reason when it gives one (OpenAlex returns JSON with error and message). The key,
    if any, is scrubbed, and the text is cut short: it goes into the artefact and the issue."""
    text = f"http {e.code}"
    detail = ""
    try:
        body = e.read(2000).decode("utf-8", "replace") if e.fp is not None else ""
        j = json.loads(body) if body.strip().startswith("{") else {}
        detail = ". ".join(str(j[k]).strip().rstrip(".") for k in ("error", "message") if isinstance(j, dict) and j.get(k))
    except Exception:
        detail = ""
    detail = detail or (e.reason if isinstance(e.reason, str) else "")
    if OPENALEX_KEY: detail = detail.replace(OPENALEX_KEY, "***")
    detail = re.sub(r"\s+", " ", detail).strip()[:200]
    return f"{text}: {detail}" if detail else text


def openalex_401_line(error, key_set):
    """The one plain line printed (and recorded as a warning) when OpenAlex answers 401."""
    reason = error.split(":", 1)[1].strip() if ":" in error else "no reason given"
    if key_set:
        return f"OpenAlex refused a request made with a key (http 401: {reason}). Check that the OPENALEX_API_KEY repository secret is a valid key."
    return (f"OpenAlex refused a request made without a key (http 401: {reason}). Keyless use cannot page past the first page of results "
            "and shares one small daily budget per network address; setting the OPENALEX_API_KEY repository secret is the fix.")


# ---------- read boundary ----------

READ_BOUNDARY_APIS = ["builtins.open", "io.open", "io.FileIO", "_io.FileIO", "os.open", "pathlib.Path.read_text", "pathlib.Path.read_bytes"]
READ_BOUNDARY_INTERVAL = "the harvest() call only: after the query configuration was loaded and the modules imported, before the artefact envelope was assembled and written"


class ReadBoundary:
    """A read guard for the discovery run. While active, the standard Python file-open surface listed in READ_BOUNDARY_APIS
    (builtins.open, io.open, io.FileIO and _io.FileIO by a guarded subclass, os.open, Path.read_text, Path.read_bytes) raises for any
    path outside the allowed set, which is empty for a harvest (the configuration is already in memory and the indexes are queried
    over the network), and every attempted path is recorded as attempted and, when refused, as refused. The record states the
    monitored interval and API coverage; it is an attestation about that interval and those APIs, not a claim about every read in the
    process's lifetime, and not a sandbox against code that holds a reference bound before the guard. The artefact carries the
    record, and an execution receipt that hashes the artefact binds it to the run that produced the candidates."""
    def __init__(self, allowed=()):
        self.allowed = {Path(a).resolve() for a in allowed}; self.attempted = []; self.refused = []; self.succeeded = []
    def _check(self, target):
        try: p = Path(target).resolve()
        except Exception: p = Path(str(target))
        self.attempted.append(str(p))
        if p not in self.allowed:
            self.refused.append(str(p)); raise RuntimeError(f"file read during the discovery run refused: {target}")
        self.succeeded.append(str(p))
    def __enter__(self):
        import builtins, io, _io
        g = self
        self._orig = (builtins.open, io.open, os.open, Path.read_text, Path.read_bytes, io.FileIO, _io.FileIO)
        orig_fileio = _io.FileIO
        def g_open(file, mode="r", *a, **k): g._check(file); return g._orig[0](file, mode, *a, **k)
        def g_io(file, mode="r", *a, **k): g._check(file); return g._orig[1](file, mode, *a, **k)
        def g_os(path, flags, *a, **k): g._check(path); return g._orig[2](path, flags, *a, **k)
        def g_rt(self_, *a, **k): g._check(self_); return g._orig[3](self_, *a, **k)
        def g_rb(self_, *a, **k): g._check(self_); return g._orig[4](self_, *a, **k)
        class GuardedFileIO(orig_fileio):
            def __init__(self_, file, mode="r", *a, **k):
                if not isinstance(file, int): g._check(file)          # an integer is an already-open descriptor, which os.open guarded
                super().__init__(file, mode, *a, **k)
        builtins.open, io.open, os.open, Path.read_text, Path.read_bytes = g_open, g_io, g_os, g_rt, g_rb
        io.FileIO = GuardedFileIO; _io.FileIO = GuardedFileIO
        return self
    def __exit__(self, *a):
        import builtins, io, _io
        builtins.open, io.open, os.open, Path.read_text, Path.read_bytes, io.FileIO, _io.FileIO = self._orig
    def record(self):
        clean = not self.attempted
        return {"enforced": True, "interval": READ_BOUNDARY_INTERVAL, "api_coverage": list(READ_BOUNDARY_APIS), "allowed_paths": sorted(str(a) for a in self.allowed),
                "files_attempted": sorted(set(self.attempted)), "files_refused": sorted(set(self.refused)), "files_opened": sorted(set(self.succeeded)),
                "note": ("no read attempt was observed on the monitored APIs during the monitored interval" if clean else "read attempts were observed on the monitored APIs during the monitored interval; see files_attempted, files_refused and files_opened")
                        + "; the attestation covers that interval and those APIs only, and gold lists, manifests and splits belong to the evaluator's separate process"}


# ---------- http ----------

def get(url, tries=5):
    """GET JSON with a polite pause, Retry-After honoured, bounded backoff. Returns (data, error)."""
    for attempt in range(tries):
        if attempt and past_deadline():
            return None, f"{BUDGET_REASON} while retrying"
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
            return None, http_error_text(e)
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
        if pages and past_deadline(): err = f"{BUDGET_REASON} after {pages} page(s)"; break
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
        if pages and past_deadline(): err = f"{BUDGET_REASON} after {pages} page(s)"; break
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
    if err or not data: return {"resolves": False if (err or "").startswith("http 404") else None, "error": err}
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
    prov = cfg.get("providers") or {"openalex": {"search_routes": False, "update_date_filter": False}}
    oa_search = bool(prov.get("openalex", {}).get("search_routes"))          # from the hashed profile, never from the environment
    oa_update = bool(prov.get("openalex", {}).get("update_date_filter"))
    out = []
    def add(route, source, query, basis, unavailable=None):
        out.append({"instrument_id": rec["instrument_id"], "route": route, "source": source, "date_basis": basis, "query": query,
                    "channel_id": channel_id(rec["instrument_id"], route, source, basis, query), "unavailable": unavailable})
    bases = [("publication", date_from, date_to)] + ([("first_indexed", catch_from, date_to)] if catch_from else []) + ([("full_history", None, None)] if full_history else [])
    for name in rec["names"]:
        for basis, f, t in bases:
            if basis == "first_indexed":
                add("names", "europepmc", f"TITLE_ABS:{q_phrase(name)}", basis)
                if oa_update: add("names", "openalex", q_phrase(name), basis)
                else: add("names", "openalex", q_phrase(name), basis, unavailable="OpenAlex update-date filtering is off in the provider profile (needs a premium key)")
                continue
            if oa_search: add("names", "openalex", q_phrase(name), basis)
            add("names", "europepmc", f"TITLE_ABS:{q_phrase(name)}", basis)
    ctx = rec.get("abbreviation_context") or []
    for ab in rec.get("abbreviations") or []:
        if not ctx: continue          # an abbreviation without required context is never queried bare
        oa = f'{q_phrase(ab)} AND ({" OR ".join(q_phrase(c) for c in ctx)})'      # property terms are applied locally; a 28-term OR makes OpenAlex time out
        ep = f'TITLE_ABS:{q_phrase(ab)} AND ({epmc_terms("TITLE_ABS", ctx)}) AND ({epmc_terms("TITLE_ABS", props)})'
        for basis, f, t in bases:
            if basis == "full_history": continue                     # the quarterly rerun covers names and citation links
            if basis == "first_indexed": add("abbreviation", "europepmc", ep, basis); continue
            if oa_search: add("abbreviation", "openalex", oa, basis)
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

    # Run order: the windowed channels first, then the untargeted channel, then the quarterly full-history pass, so a run that
    # reaches its time budget loses the full-history channels before the monthly ones. The order changes no channel and no id.
    work = [(rec["instrument_id"], desc, run) for rec in records for desc, run in channels_for(rec, cfg, date_from, date_to, catch_from, full_history)]
    new_work = [(None, desc, run) for desc, run in new_instrument_channels(cfg, date_from, date_to)]
    work = [w for w in work if w[1]["date_basis"] != "full_history"] + new_work + [w for w in work if w[1]["date_basis"] == "full_history"]
    t0, said_401, not_started = time.monotonic(), False, 0
    new_items = {}
    for n, (rec_id, desc, run) in enumerate(work, 1):
        if run is None:      # a provider filter this configuration cannot use: logged as unavailable, never as run
            ch = {**desc, "pages": 0, "reported_hits": None, "collected_hits": 0, "outcome": "unavailable", "error": desc["unavailable"]}; hits = []
        elif past_deadline():   # recorded as a channel that did not complete, with the reason; it stays in the denominator
            ch = {**desc, "pages": 0, "reported_hits": None, "collected_hits": 0, "outcome": "failed", "error": f"{BUDGET_REASON} before this channel started"}; hits = []
            not_started += 1
        else:
            hits, pages, reported, err = run()
            ch = {**desc, "pages": pages, "reported_hits": reported, "collected_hits": len(hits),
                  "outcome": "complete" if not err else ("partial" if hits else "failed"), "error": err}
        channels.append(ch)
        progress(f"[{n}/{len(work)}] {rec_id or 'untargeted'} {desc['route']} {desc['source']} {desc['date_basis']}: {ch['outcome']}"
                 + ("" if ch["outcome"] == "unavailable" else f", {ch['pages']} page(s), {ch['collected_hits']} of {ch['reported_hits']} hits")
                 + (f", {ch['error']}" if ch["error"] and ch["outcome"] != "unavailable" else "") + f" ({int(time.monotonic() - t0)}s)")
        if desc["source"] == "openalex" and (ch["error"] or "").startswith("http 401") and not said_401:
            said_401 = True
            line = openalex_401_line(ch["error"], bool(OPENALEX_KEY)); progress(line)
            warnings.append({"type": "openalex http 401", "detail": line})
        if rec_id is not None:
            for w in hits: absorb(rec_id, desc["route"], w, ch)
            continue
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
    if not_started:
        warnings.append({"type": "time budget", "detail": f"{not_started} channels were not started because the run's time budget was reached; they are listed as failed with that reason"})
    if verify:
        with_doi = [c for c in candidates.values() if c["doi"]]
        progress(f"checking {len(with_doi)} candidate DOIs against Crossref ({int(time.monotonic() - t0)}s)")
        skipped = 0
        for i, c in enumerate(candidates.values(), 1):
            if not c["doi"]: c["crossref"] = {"resolves": None}; continue
            if past_deadline(): c["crossref"] = {"resolves": None, "error": f"not checked: {BUDGET_REASON}"}; skipped += 1; continue
            c["crossref"] = crossref_check(c["doi"])
            if i % 500 == 0: progress(f"  {i} of {len(candidates)} candidates checked ({int(time.monotonic() - t0)}s)")
        if skipped:
            warnings.append({"type": "time budget", "detail": f"{skipped} candidate DOIs were not checked against Crossref because the run's time budget was reached"})
            progress(f"{skipped} candidate DOIs not checked against Crossref: {BUDGET_REASON}")
    items = sorted(candidates.values(), key=lambda c: (c["doi"] or "~", c["title"]))
    for c in items: c["instruments"].sort(); c["routes"].sort()
    new_list = sorted(new_items.values(), key=lambda c: (c["doi"] or "~", c["title"]))
    return items, new_list, channels, low, warnings


def envelope(cfg, records, date_from, date_to, started, items, new_list, channels, low, warnings, sources, evaluation_id=None):
    ran = [c for c in channels if c["outcome"] != "unavailable"]
    failed = [c for c in ran if c["outcome"] != "complete"]
    if not ran:
        status = "failed"; warnings = warnings + [{"type": "configuration", "detail": "no retrieval channels were planned"}]
    else:
        status = "complete" if not failed else ("failed" if all(c["outcome"] == "failed" for c in ran) else "partial")
    if status == "complete" and any(w.get("type") == "time budget" for w in warnings):
        status = "partial"          # every channel ran, but the Crossref check of the candidates was cut short
    try: commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip() or None
    except Exception: commit = None
    return {"schema_version": SCHEMA_VERSION, "harvester": "tools/harvest.py 0.2",
            "run_id": hashlib.sha256(f"{date_from}|{date_to}|{started}".encode()).hexdigest()[:16],
            "registry_commit": commit, "query_version": cfg["version"],
            "query_sha256": hashlib.sha256(QUERIES.read_bytes()).hexdigest() if QUERIES.exists() else None,
            "requested_window": {"from": date_from, "to": date_to, "type": "publication date, inclusive"},
            "evaluation_id": evaluation_id,          # predeclared by a retrieval-evaluation lock when this run is its discovery run; null otherwise
            "started_at": started, "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "status": status, "sources": sources, "instruments": sorted(r["instrument_id"] for r in records),
            "channels": channels, "candidates": items, "new_instrument_candidates": new_list,
            "low_priority_counts": low, "warnings": warnings,
            "note": "A candidate is a work retrieved by an instrument's names, abbreviation or citation route. screening_priority normal means a psychometric property term appears in its title or abstract; low means none was found, which may mean a missing abstract. Nothing here is a grade, a judgement or a registry change. status complete means every planned retrieval channel completed all its pages and, when verification was asked for, no Crossref check was cut short by the time budget; it says nothing about screening."}


def next_action(env):
    """The one action a person needs to take after this run, in plain words, or None when the run is complete. Used in the
    cycle issue's title and first line, so it names the cause the run itself recorded rather than guessing."""
    if env.get("status") == "complete": return None
    from cycle import recovery_deadline, long_date
    cyc = env.get("cycle") or {}
    rerun = "re-run evidence-harvest (Run workflow, both window fields empty)"
    if cyc.get("kind") == "planned" and re.fullmatch(r"\d{4}-\d{2}", str(cyc.get("id"))):
        rerun += f" by {long_date(recovery_deadline(cyc['id']))} (UTC)"
    elif cyc.get("kind") == "manual":
        rerun = "re-run the same manual window"
    bad = [c for c in env.get("channels", []) if c.get("outcome") not in ("complete", "unavailable")]
    if any(c.get("source") == "openalex" and str(c.get("error") or "").startswith("http 401") for c in bad):
        if any("authenticated" in str(s) for s in env.get("sources", [])):
            return f"Check that the OPENALEX_API_KEY repository secret is a valid key, then {rerun}."
        return f"Set the OPENALEX_API_KEY repository secret, then {rerun}."
    if (env.get("time_budget") or {}).get("reached"):
        if (env.get("date_bases") or {}).get("full_history"):
            return "Decide how the quarterly full-history pass should run: it does not fit in one run's time budget, so a re-run stops in the same place (evidence/README.md)."
        return f"{rerun[0].upper() + rerun[1:]}; if it stops at the time budget again, the run log shows which channels were slow."
    return f"{rerun[0].upper() + rerun[1:]}; if the same channels fail again, their errors are listed below."


# ---------- self test ----------

def budget_and_progress_checks(cfg):
    """Offline, with the network layer stubbed: progress lines per channel, the time budget (channels not started, a page loop
    stopped, the Crossref check cut short, full-history channels last), the OpenAlex 401 line, error text and next_action."""
    global get, DEADLINE, OPENALEX_KEY
    import io, contextlib
    real_get, saved_key = get, OPENALEX_KEY
    OPENALEX_KEY = None                      # the checks describe a keyless run whatever the environment holds
    cfg2 = {**cfg, "records": [{**cfg["records"][0], "citation_seeds": [{"openalex_id": "W1"}]},
                               {"instrument_id": "b", "names": ["Beta Index"], "abbreviations": [], "abbreviation_context": [], "citation_seeds": [{"openalex_id": "W2"}]}]}
    calls = {"n": 0, "stop_after": None}
    def stub(url, tries=5):
        calls["n"] += 1
        if calls["stop_after"] is not None and calls["n"] >= calls["stop_after"]:
            globals()["DEADLINE"] = time.monotonic() - 1                 # the budget runs out during this request
        if "openalex" in url:
            return None, "http 401: API key required for cursor paging Paging past the first page with cursor= needs a free API key."
        if "crossref" in url:
            return {"message": {"type": "journal-article"}}, None
        n = calls["n"]
        return {"hitCount": 1, "resultList": {"result": [{"doi": f"10.1/x{n}", "title": f"Alpha Scale validation {n}"}]}, "nextCursorMark": None}, None
    def run_stubbed(full_history=False, verify=False):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = harvest(cfg2, cfg2["records"], "2026-01-01", "2026-01-31", verify=verify, now="t", catch_from="2025-11-02", full_history=full_history)
        return out, err.getvalue()
    get = stub
    try:
        DEADLINE = None
        (items, _n, chs, _l, warns), log = run_stubbed(verify=True)
        lines = [x for x in log.splitlines() if x.startswith("[")]
        assert len(lines) == len(chs) and lines[0].startswith(f"[1/{len(chs)}]") and lines[-1].startswith(f"[{len(chs)}/{len(chs)}]"), "one progress line per channel, numbered"
        assert sum("OPENALEX_API_KEY" in x for x in log.splitlines()) == 1, "the 401 line is printed once, however many OpenAlex channels fail"
        w401 = [w for w in warns if w["type"] == "openalex http 401"]
        assert len(w401) == 1 and "API key required for cursor paging" in w401[0]["detail"] and "setting the OPENALEX_API_KEY repository secret is the fix" in w401[0]["detail"], w401
        oa = [c for c in chs if c["source"] == "openalex" and c["outcome"] != "unavailable"]
        assert oa and all(c["outcome"] == "failed" and c["error"].startswith("http 401: API key required") for c in oa), "the server's reason is kept in the channel outcome"
        assert "a key" in openalex_401_line("http 401: x", True) and "valid key" in openalex_401_line("http 401: x", True)
        # the budget runs out during the third request: later channels are not started, full-history ones are last, the file still has every channel
        DEADLINE = None; calls.update(n=0, stop_after=3)
        (items, _n, chs, _l, warns), log = run_stubbed(full_history=True)
        ran = [c for c in chs if c["outcome"] != "unavailable"]
        skipped = [c for c in ran if (c["error"] or "").endswith("before this channel started")]
        first_skip = next(i for i, c in enumerate(ran) if c in skipped)
        assert skipped and all(c["outcome"] == "failed" and c["pages"] == 0 for c in skipped), "a channel never started is failed with the reason, not missing"
        assert all(c in skipped for c in ran[first_skip:]), "once the budget is reached no further channel starts"
        assert [c["date_basis"] == "full_history" for c in ran] == sorted(c["date_basis"] == "full_history" for c in ran), "every full-history channel comes after every windowed channel"
        assert any(w["type"] == "time budget" for w in warns)
        st = envelope(cfg2, cfg2["records"], "2026-01-01", "2026-01-31", "t", items, [], chs, {}, warns, ["s"])
        assert st["status"] == "partial", st["status"]
        # every channel completes, then the budget runs out before the Crossref check: the run is partial, the unchecked DOIs say why
        cfg3 = {**cfg, "records": [cfg["records"][0]]}
        DEADLINE = None; calls.update(n=0, stop_after=None)
        err = io.StringIO()
        def stub_last(url, tries=5):
            r = stub(url, tries)
            if "europepmc" in url and calls["n"] >= 2: globals()["DEADLINE"] = time.monotonic() - 1     # after the second and last channel
            return r
        get = stub_last
        with contextlib.redirect_stderr(err):
            items, _n, chs, _l, warns = harvest(cfg3, cfg3["records"], "2026-01-01", "2026-01-31", verify=True, now="t", catch_from="2025-11-02")
        assert all(c["outcome"] in ("complete", "unavailable") for c in chs), [c["outcome"] for c in chs]
        assert items and all(c["crossref"].get("error") == f"not checked: {BUDGET_REASON}" for c in items), [c["crossref"] for c in items]
        assert envelope(cfg3, cfg3["records"], "2026-01-01", "2026-01-31", "t", items, [], chs, {}, warns, ["s"])["status"] == "partial", "a Crossref check cut short is not a complete run"
        # a page loop stops at the budget between pages and says after how many
        DEADLINE = None
        def two_pages(url, tries=5):
            globals()["DEADLINE"] = time.monotonic() - 1
            return {"hitCount": 300, "resultList": {"result": [{"doi": "10.1/p", "title": "t"}]}, "nextCursorMark": "next"}, None
        get = two_pages
        hits, pages, reported, e = europepmc_channel("x", "2026-01-01", "2026-01-31")
        assert pages == 1 and e == f"{BUDGET_REASON} after 1 page(s)", (pages, e)
        # the real command line: the artefact a planned cycle writes carries the action, the recovery date and the 401 line
        DEADLINE = None; get = lambda url, tries=5: ((None, "http 401: API key required for cursor paging") if "openalex" in url else
                                                    ({"hitCount": 0, "resultList": {"result": []}, "nextCursorMark": None}, None))
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            outp = Path(tmp) / "2026-11.json"
            argv = sys.argv
            sys.argv = ["harvest.py", "--from", "2026-10-01", "--to", "2026-11-01", "--catch-from", "2026-08-03", "--cycle-id", "2026-11", "--cycle-kind", "planned", "--no-verify", "--time-budget-minutes", "240", "--out", str(outp)]
            try:
                with contextlib.redirect_stderr(io.StringIO()): main()
                code = 0
            except SystemExit as ex: code = ex.code
            finally: sys.argv = argv
            art = json.loads(outp.read_text(encoding="utf-8"))
        assert code == 2 and art["status"] == "partial" and art["time_budget"] == {"minutes": 240, "reached": False}, (code, art["status"], art.get("time_budget"))
        assert art["next_action"] == "Set the OPENALEX_API_KEY repository secret, then re-run evidence-harvest (Run workflow, both window fields empty) by 30 November 2026 (UTC).", art["next_action"]
        assert [w["type"] for w in art["warnings"]].count("openalex http 401") == 1
    finally:
        get = real_get; DEADLINE = None
    # the server's reason survives into the error text, the key never does
    import urllib.error as ue
    try:
        OPENALEX_KEY = "sekret-key"
        body = json.dumps({"error": "API key required for cursor paging", "message": "bad key sekret-key"}).encode()
        txt = http_error_text(ue.HTTPError("https://x", 401, "Unauthorized", {}, io.BytesIO(body)))
        assert txt.startswith("http 401: API key required for cursor paging") and "sekret-key" not in txt and "***" in txt, txt
        assert http_error_text(ue.HTTPError("https://x", 404, "Not Found", {}, None)) == "http 404: Not Found"
    finally:
        OPENALEX_KEY = saved_key
    get = lambda url, tries=5: (None, "http 404: Not Found")
    try: assert crossref_check("10.1/none")["resolves"] is False, "a 404 with its reason still means the DOI does not resolve"
    finally: get = real_get
    # next_action names the cause the run recorded
    base = {"status": "partial", "cycle": {"id": "2026-11", "kind": "planned"}, "sources": ["openalex (cites only; keyless)"], "date_bases": {"full_history": False}, "time_budget": {"reached": False}}
    c401 = [{"source": "openalex", "outcome": "partial", "error": "http 401: API key required"}]
    assert next_action({**base, "status": "complete"}) is None
    assert next_action({**base, "channels": c401}) == "Set the OPENALEX_API_KEY repository secret, then re-run evidence-harvest (Run workflow, both window fields empty) by 30 November 2026 (UTC)."
    assert next_action({**base, "sources": ["openalex (cites only; authenticated)"], "channels": c401}).startswith("Check that the OPENALEX_API_KEY repository secret is a valid key")
    fh = next_action({**base, "channels": [{"source": "europepmc", "outcome": "failed", "error": "time budget reached before this channel started"}], "date_bases": {"full_history": True}, "time_budget": {"reached": True}})
    assert fh.startswith("Decide how the quarterly full-history pass should run"), fh
    assert next_action({**base, "channels": [{"source": "europepmc", "outcome": "failed", "error": "http 500"}]}).startswith("Re-run evidence-harvest")
    print("budget and progress checks passed: a numbered line per channel, the 401 reason kept and one fix line printed, channels after the budget recorded as not started with full history last, a cut Crossref check makes the run partial, a page loop stops between pages, the key is scrubbed, next_action names the cause")


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
    # read boundary: a discovery run with the network layer stubbed opens no file; a read of a gold-like path inside the run is refused
    global get
    real_get = get
    def stub_get(url, tries=5): return {"hitCount": 0, "resultList": {"result": []}, "nextCursorMark": None, "results": [], "meta": {"count": 0}}, None
    get = stub_get
    try:
        import io as _io_quiet, contextlib as _cl
        with ReadBoundary() as g, _cl.redirect_stderr(_io_quiet.StringIO()):
            _items, _new, _chs, _low, _warn = harvest(cfg, cfg["records"], "2026-01-01", "2026-01-31", verify=False, now="t")
        assert g.record()["files_attempted"] == [] and g.record()["files_refused"] == [] and g.record()["files_opened"] == [], f"the stubbed discovery run attempted reads: {g.record()}"
        assert g.record()["interval"] == READ_BOUNDARY_INTERVAL and g.record()["api_coverage"] == READ_BOUNDARY_APIS
        import tempfile, io as _io_mod, _io as _cio
        with tempfile.TemporaryDirectory() as tmp:
            gold = Path(tmp) / "manifest.json"; gold.write_text("{}")
            import builtins as _b
            for name, read in (("builtins.open", lambda: _b.open(gold).read()), ("io.open", lambda: _io_mod.open(gold).read()), ("io.FileIO", lambda: _io_mod.FileIO(gold, "r").read()), ("_io.FileIO", lambda: _cio.FileIO(gold, "r").read()),
                               ("os.open", lambda: os.open(gold, os.O_RDONLY)), ("Path.read_text", lambda: gold.read_text()), ("Path.read_bytes", lambda: gold.read_bytes())):
                refused = False
                try:
                    with ReadBoundary() as g2: read()
                except RuntimeError: refused = True
                rec = g2.record()
                assert refused and rec["files_refused"] == [str(gold.resolve())] and rec["files_opened"] == [] and "read attempts were observed" in rec["note"], f"{name}: a read of a gold-like path inside the boundary must be refused and recorded ({rec})"
            assert gold.read_text() == "{}" and _io_mod.FileIO(gold, "r").read() == b"{}", "the guard is lifted after the block"
            with ReadBoundary(allowed=[gold]) as g3: gold.read_text()
            assert g3.record()["files_opened"] == [str(gold.resolve())] and g3.record()["files_refused"] == [], "an allowed read is recorded as opened, not refused"
    finally:
        get = real_get
    budget_and_progress_checks(cfg)
    from cycle import expected_channels, channels_not_complete
    q = json.loads(QUERIES.read_text(encoding="utf-8"))
    assert "providers" in q and "openalex" in q["providers"] and isinstance(q["providers"]["openalex"].get("search_routes"), bool), "the provider profile is pinned in the query file"
    import os as _os
    with_key = dict(_os.environ); _os.environ["OPENALEX_API_KEY"] = "probe-not-a-real-key"
    try: plan_key = [c["channel_id"] for c in expected_channels(q, "2026-01-01", "2026-01-31", "2025-11-02", False)]
    finally: _os.environ.pop("OPENALEX_API_KEY", None); _os.environ.update({k: v for k, v in with_key.items() if k == "OPENALEX_API_KEY"})
    ids = [r["instrument_id"] for r in q["records"]]
    assert len(ids) == len(set(ids)) == 27, "27 unique parent records expected"
    for r in q["records"]:
        assert r["names"] and r["canonical_name"] == r["names"][0]
        if r.get("abbreviations"): assert r.get("abbreviation_context"), f"{r['instrument_id']}: abbreviations need context"
    exp = expected_channels(q, "2026-01-01", "2026-01-31", "2025-11-02", False)
    ids = [c["channel_id"] for c in exp]
    assert ids == plan_key, "a key in the environment must not change the plan"
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
    print(f"self-test passed: canonicalisation, matching, status logic, read boundary (stubbed run opens no file; a gold read is refused), query file shape, {len(exp)} expected channels at query granularity with one catch-up basis, {len(exp_q)} with the quarterly rerun")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from"); ap.add_argument("--to", dest="date_to")
    ap.add_argument("--instrument", action="append"); ap.add_argument("--out")
    ap.add_argument("--no-verify", action="store_true"); ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cycle-id", help="from tools/cycle.py window; a planned cycle is YYYY-MM, a manual one manual-FROM-TO")
    ap.add_argument("--cycle-kind", choices=["planned", "manual"])
    ap.add_argument("--evaluation-id", help="the predeclared id of a retrieval-evaluation lock this run serves; recorded in the artefact so the evaluator can bind it")
    ap.add_argument("--catch-from", help="start of the ingestion catch-up window (first-index date, Europe PMC); from tools/cycle.py window")
    ap.add_argument("--full-history", action="store_true", help="quarterly: names and citation links with no date filter, beside the windowed channels")
    ap.add_argument("--time-budget-minutes", type=int, help="after this many minutes no new page, channel or Crossref check starts; what did not run is recorded with the reason and the file is still written")
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
    global DEADLINE
    if a.time_budget_minutes is not None:
        if a.time_budget_minutes <= 0: sys.exit("configuration error: --time-budget-minutes must be positive")
        DEADLINE = time.monotonic() + 60 * a.time_budget_minutes
    progress(f"harvest {a.cycle_id or 'manual'}: {len(records)} instruments, window {a.date_from} to {a.date_to}"
             + (f", catch-up from {a.catch_from}" if a.catch_from else "") + (", full history" if a.full_history else "")
             + (f", time budget {a.time_budget_minutes} min" if a.time_budget_minutes else ", no time budget") + (", OpenAlex key set" if OPENALEX_KEY else ", no OpenAlex key"))
    with ReadBoundary() as guard:         # the run itself opens no file: configuration is already in memory, the indexes are over the network
        items, new_list, channels, low, warnings = harvest(cfg, records, a.date_from, a.date_to, verify=not a.no_verify, now=started, catch_from=a.catch_from, full_history=a.full_history)
    prov = cfg.get("providers") or {}
    sources = ["europepmc", "openalex (" + ("cites, names, abbreviation" if prov.get("openalex", {}).get("search_routes") else "cites only, per the provider profile") + ("; authenticated" if OPENALEX_KEY else "; keyless") + ")"] + (["crossref"] if not a.no_verify else [])
    if a.evaluation_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{4,80}", a.evaluation_id): sys.exit("configuration error: --evaluation-id is 4 to 80 characters of letters, digits, _ . : -")
    out = envelope(cfg, records, a.date_from, a.date_to, started, items, new_list, channels, low, warnings, sources, a.evaluation_id)
    out["read_boundary"] = guard.record()
    out["time_budget"] = {"minutes": a.time_budget_minutes, "reached": any(w.get("type") == "time budget" for w in warnings)}
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
    out["next_action"] = next_action(out)          # after cycle, date bases and status are all in place
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
