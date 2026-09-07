#!/usr/bin/env python3
"""Watch the licence sources the registry cites, and say honestly what was and was not checked.

The previous watcher reduced every page to visible text by deleting tags, so a licence hyperlink
could be repointed at a different licence entirely and, as long as the words around it were
unchanged, the hash matched and nothing was reported. It also fetched shared URLs once per citing
instrument, counted those fetches as pages, and kept no snapshot, so a reported change could not be
replayed.

This version:

  * plans one acquisition per transport URL from a reviewed source plan, then fans the result out to
    every instrument that cites it, so counters name their denominator;
  * builds its comparison representation with an HTML parser, keeping visible text, hyperlink targets
    and rights metadata, so an href-only change is a change;
  * retains raw bytes, decoded bytes and the normalised representation, each addressed by digest and
    re-read before the manifest may claim it exists;
  * separates acquisition coverage from comparison outcome, and never records a failed source as
    unchanged;
  * refuses to accept a new baseline on its own. A candidate observation is written for review.

    watch_licences.py --plan FILE --captures DIR --report FILE   # compare, write no baseline
    watch_licences.py --self-test                                # offline controls, no network

Exit 0 complete with no unresolved change; 3 a change needs review; 4 incomplete with no change
signal; 5 no successful required check. A page that could not be checked is unchecked, not unchanged.

Nothing here edits a licence class, a status, a verification date or any dataset field.
"""
import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_HASHES = ROOT / "evidence" / "licence-hashes.json"
UA = "OWHS-licence-watch/1.0 (https://openworkplacehealth.org; mailto:registry@openworkplacehealth.org)"
POLICY_VERSION = "2"           # the normalisation policy; a v1 hash and a v2 hash are never compared

PURPOSES = ("terms_document", "article_licence_declaration", "general_landing_page", "rights_scope_unverified")
PROFILES = ("google-sites-ipaq", "aosis-article-licence", "generic-landing-unverified", "generic-page-or-pdf")

# Acquisition outcomes: what happened when we asked for the source.
ACQUIRED_OK = "acquired"
ACQUIRE_FAILED = "acquisition_failed"
EXTRACT_FAILED = "extraction_failed"

# Comparison outcomes. These are monitoring labels, never registry grades or licence states.
OUTCOMES = ("baseline_capture_only", "legacy_hash_match_snapshot_missing", "legacy_hash_change_snapshot_missing",
            "comparison_policy_changed", "same_recorded_representation", "reviewed_presentation_variant",
            "selected_source_change_needs_review", "page_change_scope_unverified", "unchecked")

# The one reviewed consent element that may be excluded, and only when its whole parsed subtree
# matches this fingerprint. A changed or unmatched banner stays in the page signal.
IPAQ_COOKIE_FINGERPRINT = "bd898dde974430f51ccdaae81c08ce12327589c820ca41ce926a28bdf0ff0e17"


class ToolError(Exception):
    """Bad invocation, or a plan or capture the tool cannot stand behind."""


def sha(b):
    return hashlib.sha256(b).hexdigest()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- source plan

def load_plan(path):
    """A closed, strictly validated plan. An unknown key or an unknown profile is a refusal."""
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ToolError(f"{path}: not readable as strict JSON ({e})")
    if plan.get("kind") != "owhs_licence_watch_source_plan":
        raise ToolError("not a licence-watch source plan")
    allowed_top = {"kind", "version", "note", "dataset", "sources"}
    if set(plan) - allowed_top:
        raise ToolError(f"plan carries unknown key(s): {', '.join(sorted(set(plan) - allowed_top))}")
    seen_ids, seen_urls = set(), set()
    allowed = {"source_id", "url", "instrument_ids", "purpose", "required", "extraction_profile_id",
               "extraction_profile_version", "required_linked_document_ids", "archived_reference", "reviewed_addition"}
    for e in plan["sources"]:
        missing = allowed - set(e)
        if missing: raise ToolError(f"{e.get('source_id')}: plan entry missing {', '.join(sorted(missing))}")
        if set(e) - allowed: raise ToolError(f"{e.get('source_id')}: plan entry has unknown key(s)")
        if e["source_id"] in seen_ids: raise ToolError(f"duplicate source_id {e['source_id']}")
        if e["url"] in seen_urls: raise ToolError(f"duplicate url {e['url']}; plan one acquisition per transport URL")
        if e["purpose"] not in PURPOSES: raise ToolError(f"{e['source_id']}: unknown purpose {e['purpose']}")
        if e["extraction_profile_id"] not in PROFILES: raise ToolError(f"{e['source_id']}: unknown extraction profile")
        if not e["instrument_ids"]: raise ToolError(f"{e['source_id']}: names no instrument")
        seen_ids.add(e["source_id"]); seen_urls.add(e["url"])
    return plan


# ---------------------------------------------------------------- extraction

class Representation(HTMLParser):
    """Visible text, hyperlink targets and rights metadata, kept together.

    Deleting tags loses exactly the thing a licence page is about: where its licence link points.
    This keeps the link target beside the words, so a repointed href changes the representation even
    when every visible word is identical."""

    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self, profile):
        super().__init__(convert_charrefs=True)
        self.profile = profile
        self.parts, self.links, self.rights, self._skip = [], [], [], 0
        self._excluded_cookie = False
        self._depth_stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
            return
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").strip()
            if name.lower() in ("dc.rights", "dcterms.rights", "dc.rights.license", "citation_license"):
                self.rights.append(f"{name}={a.get('content', '')}")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())
            self.parts.append(f"href:{a['href'].strip()}")
        if tag == "link" and (a.get("rel") or "").lower() == "license" and a.get("href"):
            self.rights.append(f"link.license={a['href'].strip()}")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t: self.parts.append(t)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def normalise(raw, content_type, profile):
    """The comparison representation, its policy version, and the links it saw.

    A PDF is compared as bytes: a byte change is a document signal, not a conclusion that licence
    text changed. Recording the media type stops a PDF silently becoming a login page's HTML."""
    ct = (content_type or "").lower()
    if "pdf" in ct or raw[:5] == b"%PDF-":
        return {"media": "application/pdf", "representation": None, "representation_sha256": sha(raw),
                "policy_version": POLICY_VERSION, "links": [], "rights": [], "profile": profile}
    m = re.search(r"charset=([\w-]+)", ct)
    charset = (m.group(1) if m else "utf-8")
    try:
        text = raw.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError):
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return {"media": ct or "unknown", "representation": None, "representation_sha256": None,
                    "policy_version": POLICY_VERSION, "links": [], "rights": [], "profile": profile,
                    "error": "decode_failed"}
    p = Representation(profile)
    p.feed(text)
    body = p.text()
    rep = json.dumps({"profile": profile, "policy": POLICY_VERSION, "text": body,
                      "links": p.links, "rights": p.rights}, sort_keys=True, ensure_ascii=False)
    return {"media": ct.split(";")[0] or "text/html", "representation": rep,
            "representation_sha256": sha(rep.encode("utf-8")), "policy_version": POLICY_VERSION,
            "links": p.links, "rights": p.rights, "profile": profile, "charset": charset}


# ---------------------------------------------------------------- acquisition

def fetch(url, opener=None):
    """One attempt, with its full provenance. A failure carries null bytes and null hash, truthfully."""
    started = now()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=60) as r:
            raw = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower()
            body = raw
            if enc == "gzip":
                body = gzip.decompress(raw)
            elif enc == "deflate":
                body = zlib.decompress(raw)
            return {"requested_url": url, "final_url": r.geturl(), "fetched_at_utc": started,
                    "http_status": getattr(r, "status", 200), "content_type": r.headers.get("Content-Type", ""),
                    "content_encoding": enc or None, "raw": raw, "decoded": body,
                    "raw_sha256": sha(raw), "raw_bytes": len(raw), "decoded_sha256": sha(body),
                    "outcome": ACQUIRED_OK, "error_code": None}
    except urllib.error.HTTPError as e:
        return _failed(url, started, f"http_{e.code}", e.code)
    except Exception as e:
        return _failed(url, started, f"transport_{type(e).__name__.lower()}", None)


def _failed(url, started, code, status):
    return {"requested_url": url, "final_url": None, "fetched_at_utc": started, "http_status": status,
            "content_type": None, "content_encoding": None, "raw": None, "decoded": None,
            "raw_sha256": None, "raw_bytes": None, "decoded_sha256": None,
            "outcome": ACQUIRE_FAILED, "error_code": code}


def retain(captures, attempt, rep):
    """Write raw, decoded and normalised objects, then re-read and hash each before claiming it exists.

    A digest plus a file that vanished when the runner ended is not a retained snapshot."""
    if attempt["raw"] is None:
        return {"capture_retention": "capture_retention_pending", "objects": {}}
    captures.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, data in (("raw", attempt["raw"]), ("decoded", attempt["decoded"]),
                       ("representation", (rep.get("representation") or "").encode("utf-8") if rep.get("representation") else None)):
        if data is None: continue
        digest = sha(data)
        p = captures / f"{digest}.{name}"
        if not p.exists():
            p.write_bytes(data)                          # raw bytes are never overwritten by decoded output
        back = p.read_bytes()
        if sha(back) != digest:
            raise ToolError(f"retained capture {p.name} does not re-read to its digest")
        written[name] = {"sha256": digest, "bytes": len(back), "path": p.name}
    return {"capture_retention": "retained", "objects": written}


# ---------------------------------------------------------------- comparison

def compare(entry, attempt, rep, legacy, retained):
    """Acquisition coverage and comparison outcome, kept separate and both stated."""
    if attempt["outcome"] == ACQUIRE_FAILED:
        return "unchecked", None
    if rep.get("error") == "decode_failed" or rep["representation_sha256"] is None and rep["media"] != "application/pdf":
        return "unchecked", EXTRACT_FAILED
    prev = legacy.get(entry["url"])
    current = rep["representation_sha256"]
    if prev is None:
        return "baseline_capture_only", None
    # A v1 whole-text hash and a v2 representation hash describe different things. Comparing them
    # would manufacture a change on every source at once.
    if legacy.get("_policy_version", "1") != POLICY_VERSION:
        return ("legacy_hash_change_snapshot_missing" if retained["capture_retention"] != "retained"
                else "comparison_policy_changed"), None
    if prev == current:
        return "same_recorded_representation", None
    if entry["purpose"] == "rights_scope_unverified":
        return "page_change_scope_unverified", None
    return "selected_source_change_needs_review", None


# ---------------------------------------------------------------- reporting

def issue_body(counts, changed, incomplete):
    """Safe generated Markdown. Fetched page content is never echoed into an issue."""
    lines = [f"Licence-source check: {counts['status']}. {counts['source_url_count']} unique source URLs "
             f"checked for {counts['instrument_source_checks']} instrument-source relationships. "
             f"{len(changed)} source changes need review; {counts['failed_urls']} source checks were incomplete. "
             "These are monitoring results, not confirmed changes to permissions or registry classifications.", ""]
    if changed:
        lines.append("Changes needing review:")
        for c in changed:
            lines.append(f"- **{', '.join(c['instrument_ids'])}**: `{c['url']}` ({c['outcome']})")
        lines.append("")
    if incomplete:
        lines.append("Unchecked this run:")
        for c in incomplete:
            lines.append(f"- **{', '.join(c['instrument_ids'])}**: `{c['url']}` ({c['error_code']})")
    return "\n".join(lines)


def run(plan, captures, opener=None, sleep=0.5):
    legacy = json.loads(LEGACY_HASHES.read_text(encoding="utf-8")) if LEGACY_HASHES.exists() else {"hashes": {}}
    legacy_hashes = dict(legacy.get("hashes", {}))
    legacy_hashes["_policy_version"] = legacy.get("policy_version", "1")
    results = []
    for entry in plan["sources"]:
        attempt = fetch(entry["url"], opener)
        if sleep: time.sleep(sleep)
        rep = (normalise(attempt["decoded"], attempt["content_type"], entry["extraction_profile_id"])
               if attempt["raw"] is not None else {"media": None, "representation": None,
                                                   "representation_sha256": None, "policy_version": POLICY_VERSION,
                                                   "links": [], "rights": [], "profile": entry["extraction_profile_id"]})
        retained = retain(captures, attempt, rep) if captures else {"capture_retention": "capture_retention_pending", "objects": {}}
        outcome, extract_error = compare(entry, attempt, rep, legacy_hashes, retained)
        results.append({
            "source_id": entry["source_id"], "url": entry["url"], "instrument_ids": entry["instrument_ids"],
            "purpose": entry["purpose"], "extraction_profile_id": entry["extraction_profile_id"],
            "extraction_profile_version": entry["extraction_profile_version"],
            "requested_url": attempt["requested_url"], "final_url": attempt["final_url"],
            "fetched_at_utc": attempt["fetched_at_utc"], "http_status": attempt["http_status"],
            "media_type": rep.get("media"), "charset": rep.get("charset"),
            "content_encoding": attempt["content_encoding"],
            "raw_sha256": attempt["raw_sha256"], "raw_bytes": attempt["raw_bytes"],
            "decoded_sha256": attempt["decoded_sha256"],
            "comparison_representation_sha256": rep.get("representation_sha256"),
            "comparison_policy_version": POLICY_VERSION,
            "rights_metadata": rep.get("rights", []),
            "linked_hrefs": rep.get("links", [])[:50],
            "acquisition_outcome": extract_error or attempt["outcome"],
            "comparison_outcome": outcome,
            "error_code": attempt["error_code"],
            "archived_reference": entry["archived_reference"],
            "capture_retention": retained["capture_retention"],
            "retained_objects": retained["objects"],
            "comparison_replayable": retained["capture_retention"] == "retained" and rep.get("representation_sha256") is not None,
            "source_extraction_replayable": "raw" in retained["objects"],
        })
    return results


def summarise(plan, results):
    attempted = len(results)
    succeeded = sum(1 for r in results if r["acquisition_outcome"] == ACQUIRED_OK)
    failed = attempted - succeeded
    checks = sum(len(r["instrument_ids"]) for r in results)
    affected = sum(len(r["instrument_ids"]) for r in results if r["acquisition_outcome"] != ACQUIRED_OK)
    changed = [r for r in results if r["comparison_outcome"] in ("selected_source_change_needs_review", "page_change_scope_unverified", "legacy_hash_change_snapshot_missing")]
    status = "complete" if failed == 0 else ("failed" if succeeded == 0 else "partial")
    return {"status": status, "source_url_count": attempted, "attempted_urls": attempted,
            "succeeded_urls": succeeded, "failed_urls": failed,
            "instrument_source_checks": checks, "affected_instrument_source_failures": affected,
            "changes_needing_review": len(changed),
            "note": ("A source URL is not an instrument-source relationship. A failed source is unchecked, "
                     "never unchanged. No comparison outcome is a licence determination.")}, changed


def exit_code(counts, changed):
    if counts["status"] == "failed": return 5
    if changed: return 3
    if counts["status"] == "partial": return 4
    return 0


# ---------------------------------------------------------------- self-test

class _Resp:
    def __init__(self, body, ct="text/html; charset=utf-8", url="https://example.org/x", status=200, enc=None):
        self._b, self.headers, self._u, self.status = body, {"Content-Type": ct, "Content-Encoding": enc or ""}, url, status
    def read(self): return self._b
    def geturl(self): return self._u
    def __enter__(self): return self
    def __exit__(self, *a): return False


def self_test(tmp):
    ran = failed = 0

    def t(label, ok, detail=""):
        nonlocal ran, failed
        ran += 1; failed += not ok
        print(("ok   " if ok else "FAIL "), label, "" if ok else str(detail)[:200])

    # The defect this rewrite exists for: identical visible words, a different licence target.
    a = b'<html><body><p>This work is licensed under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY</a></p></body></html>'
    b = b'<html><body><p>This work is licensed under <a href="https://creativecommons.org/licenses/by/2.0/">CC BY</a></p></body></html>'
    ra, rb = normalise(a, "text/html", "aosis-article-licence"), normalise(b, "text/html", "aosis-article-licence")
    old_a = re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", a.decode()))).strip()
    old_b = re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", b.decode()))).strip()
    t("the old tag-stripping representation could not see a repointed licence href", old_a == old_b)
    t("the new representation does see it", ra["representation_sha256"] != rb["representation_sha256"])
    t("and it keeps the licence target itself", "creativecommons.org/licenses/by/4.0/" in ra["links"][0])

    # Rights metadata is carried, so a DC.Rights-only change signals.
    m1 = b'<html><head><meta name="DC.Rights" content="CC BY 4.0"></head><body>Same words</body></html>'
    m2 = b'<html><head><meta name="DC.Rights" content="CC BY 2.0"></head><body>Same words</body></html>'
    t("a DC.Rights-only change signals even when the visible text is identical",
      normalise(m1, "text/html", "aosis-article-licence")["representation_sha256"]
      != normalise(m2, "text/html", "aosis-article-licence")["representation_sha256"])

    # A PDF is bytes, and its media type is recorded so it cannot silently become a login page.
    t("a PDF is compared as bytes", normalise(b"%PDF-1.4 x", "application/pdf", "generic-page-or-pdf")["media"] == "application/pdf")
    t("an undecodable body is not silently treated as empty",
      normalise(b"\xff\xfe\x00bad", "text/html; charset=ascii", "generic-page-or-pdf").get("error") == "decode_failed")

    # Plan validation.
    def plan_of(sources, **kw):
        p = {"kind": "owhs_licence_watch_source_plan", "version": "1", "note": "n", "dataset": "d", "sources": sources}
        p.update(kw); return p

    def entry(sid="SRC-001", url="https://example.org/a", insts=("x",), profile="generic-page-or-pdf", purpose="terms_document"):
        return {"source_id": sid, "url": url, "instrument_ids": list(insts), "purpose": purpose, "required": True,
                "extraction_profile_id": profile, "extraction_profile_version": "1.0.0",
                "required_linked_document_ids": [], "archived_reference": None, "reviewed_addition": None}

    def refuses(label, obj, needle):
        p = Path(tmp) / f"plan-{abs(hash(label))}.json"
        p.write_text(json.dumps(obj))
        try:
            load_plan(p); t(label, False, "accepted")
        except ToolError as e:
            t(label, needle in str(e), str(e))

    refuses("a plan with a duplicate transport URL is refused", plan_of([entry(), entry(sid="SRC-002")]), "duplicate url")
    refuses("a plan with a duplicate source id is refused", plan_of([entry(), entry(url="https://example.org/b")]), "duplicate source_id")
    refuses("a plan with an unknown extraction profile is refused", plan_of([entry(profile="invented")]), "unknown extraction profile")
    refuses("a plan with an unknown purpose is refused", plan_of([entry(purpose="whatever")]), "unknown purpose")
    refuses("a plan entry naming no instrument is refused", plan_of([entry(insts=())]), "names no instrument")
    refuses("a plan with an unknown top-level key is refused", plan_of([entry()], extra=1), "unknown key")

    # One acquisition per URL, fanned out; counters name their denominator.
    shared = plan_of([entry(sid="SRC-001", url="https://example.org/shared", insts=("wai", "was")),
                      entry(sid="SRC-002", url="https://example.org/solo", insts=("k10",))])
    calls = []

    def opener(req, timeout=None):
        calls.append(req.full_url)
        if "solo" in req.full_url: raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return _Resp(b"<html><body>terms</body></html>", url=req.full_url)

    res = run(shared, Path(tmp) / "caps", opener=opener, sleep=0)
    counts, changed = summarise(shared, res)
    t("a shared URL is acquired once, not once per instrument", len(calls) == 2, calls)
    t("counters separate URLs from instrument-source relationships",
      counts["source_url_count"] == 2 and counts["instrument_source_checks"] == 3, counts)
    t("one failed URL is reported as affecting its instruments", counts["affected_instrument_source_failures"] == 1, counts)
    t("a failed source is unchecked, never unchanged",
      [r["comparison_outcome"] for r in res if r["error_code"]] == ["unchecked"])
    t("a failed source carries null bytes and null hash truthfully",
      all(r["raw_sha256"] is None and r["raw_bytes"] is None for r in res if r["error_code"]))
    t("a partial run exits 4 when nothing changed", exit_code(counts, changed) == 4, counts["status"])

    # Retention is proved by re-reading, not by asserting.
    ok_row = [r for r in res if not r["error_code"]][0]
    t("a retained capture is re-read and hashed before the manifest claims it",
      ok_row["capture_retention"] == "retained" and ok_row["source_extraction_replayable"])
    t("a source that was never acquired is not called replayable",
      all(not r["comparison_replayable"] for r in res if r["error_code"]))

    # Every fetch failing is 5, not 4.
    def all_fail(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "no", {}, None)
    res2 = run(shared, Path(tmp) / "caps2", opener=all_fail, sleep=0)
    c2, ch2 = summarise(shared, res2)
    t("every required check failing exits 5", exit_code(c2, ch2) == 5 and c2["status"] == "failed")

    # The issue body is generated, and carries no fetched page content.
    body = issue_body(counts, [{"instrument_ids": ["wai"], "url": "https://example.org/shared", "outcome": "selected_source_change_needs_review"}],
                      [{"instrument_ids": ["k10"], "url": "https://example.org/solo", "error_code": "http_503"}])
    t("the issue body states monitoring results, not confirmed permission changes",
      "not confirmed changes to permissions" in body)
    t("the issue body carries no fetched page text", "terms" not in body)
    t("the issue body names both denominators", "unique source URLs" in body and "instrument-source relationships" in body)

    print(f"\n{ran} control(s) run, {failed} failure(s)")
    return 1 if failed else 0


def main(argv):
    ap = argparse.ArgumentParser(allow_abbrev=False, add_help=False)
    ap.add_argument("--plan"); ap.add_argument("--captures"); ap.add_argument("--report")
    ap.add_argument("--self-test", action="store_true"); ap.add_argument("--sleep", type=float, default=0.5)
    try:
        args, extra = ap.parse_known_args(argv)
    except SystemExit:
        print("[tool] invalid invocation", file=sys.stderr); return 2
    if extra:
        print(f"[tool] unrecognised argument(s): {' '.join(extra)}", file=sys.stderr); return 2
    try:
        if args.self_test:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                return self_test(tmp)
        if not (args.plan and args.report):
            print(__doc__); return 2
        plan = load_plan(args.plan)
        captures = Path(args.captures) if args.captures else None
        results = run(plan, captures, sleep=args.sleep)
        counts, changed = summarise(plan, results)
        report = {"generated_utc": now(), "plan_version": plan["version"], "counts": counts,
                  "results": results, "issue_body": issue_body(counts, changed, [r for r in results if r["error_code"]])}
        Path(args.report).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"run {counts['status']}: {counts['source_url_count']} unique source URLs, "
              f"{counts['instrument_source_checks']} instrument-source checks, "
              f"{counts['failed_urls']} failed URL(s) affecting {counts['affected_instrument_source_failures']} pair(s), "
              f"{counts['changes_needing_review']} change(s) needing review")
        return exit_code(counts, changed)
    except ToolError as e:
        print(f"[tool] {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
