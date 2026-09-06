#!/usr/bin/env python3
"""Licence-page watcher for the instrument registry.

For every parent record, fetch each licence page named in its identity block, reduce it to visible text, hash
it, and compare with the hash recorded at the last run in evidence/licence-hashes.json. Writes
evidence/licence-changes.json with a run status (complete, partial, failed), per-page attempted/succeeded/
failed counts, the changed pages with both hashes and the archived copy the registry holds, and the
unreachable pages. Exit codes: 0 complete and nothing changed; 3 something changed; 4 incomplete (one or more
pages unreachable, no change seen); 5 every fetch failed. The workflow opens an issue on 3, 4 and 5: a page
that cannot be checked is not a page whose terms are unchanged.

The watcher never edits a licence class, a licence status or any dataset field. A changed page is a reason
for a human to read it, not evidence of what changed. First run records baselines and reports nothing.

    python tools/watch_licences.py                       # compare and update baselines
    python tools/watch_licences.py --dataset PATH        # a different dataset file
    python tools/watch_licences.py --dry-run             # compare only, write no baseline
"""
import argparse, hashlib, html, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "site" / "instrument-registry" / "instrument-evidence-base-v0.9.0.json"
HASHES = ROOT / "evidence" / "licence-hashes.json"
CHANGES = ROOT / "evidence" / "licence-changes.json"
UA = "OWHS-licence-watch/0.1 (https://openworkplacehealth.org; mailto:registry@openworkplacehealth.org)"


def licence_urls(record):
    ident = record.get("identity", {})
    urls = {u.rstrip(".") for u in re.findall(r"https?://[^\s\)\];,\"']+", ident.get("licence_source", "") or "")}
    archived = ident.get("licence_page_archived_url") or []
    if isinstance(archived, str): archived = [archived]
    originals = {}
    for a in archived:
        m = re.match(r"https?://web\.archive\.org/web/\d+/(https?://.+)$", a)
        if m:
            urls.add(m.group(1)); originals[m.group(1)] = a
    return sorted(urls), originals


def visible_text(raw, content_type):
    if "pdf" in (content_type or "").lower() or raw[:5] == b"%PDF-":
        return None      # a PDF is hashed as bytes
    t = raw.decode("utf-8", errors="replace")
    t = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch_hash(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read(); ct = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:
        return None, f"error {type(e).__name__}"
    text = visible_text(raw, ct)
    h = hashlib.sha256(raw if text is None else text.encode("utf-8")).hexdigest()
    return h, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = json.loads(Path(a.dataset).read_text(encoding="utf-8"))
    baseline = json.loads(HASHES.read_text(encoding="utf-8")) if HASHES.exists() else {"hashes": {}}
    hashes, changes, unreachable, attempted, succeeded = dict(baseline.get("hashes", {})), [], [], 0, 0
    for r in data["records"]:
        if r.get("parent_id"): continue
        urls, originals = licence_urls(r)
        for u in urls:
            attempted += 1
            h, err = fetch_hash(u); time.sleep(0.5)
            if err:
                unreachable.append({"instrument": r["instrument_id"], "url": u, "error": err}); continue
            succeeded += 1
            prev = baseline.get("hashes", {}).get(u)
            if prev and prev != h:
                changes.append({"instrument": r["instrument_id"], "url": u, "previous_hash": prev, "current_hash": h,
                                "archived_copy": originals.get(u)})
            hashes[u] = h
    status = "complete" if attempted and succeeded == attempted else ("failed" if succeeded == 0 else "partial")
    first_run = not baseline.get("hashes")
    out = {"status": status, "attempted": attempted, "succeeded": succeeded, "failed": attempted - succeeded,
           "baseline_pages": len(baseline.get("hashes", {})), "changed": changes, "unreachable": unreachable,
           "baseline_written": (not a.dry_run) and status != "failed", "first_run": first_run,
           "note": "A changed hash means the page's visible text changed. It is a reason to read the page; it says nothing about what changed or whether a licence class should move. An unreachable page is unchecked, not unchanged."}
    CHANGES.parent.mkdir(parents=True, exist_ok=True)
    CHANGES.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not a.dry_run and status != "failed":     # a failed run preserves the previous baseline untouched
        HASHES.write_text(json.dumps({"dataset": Path(a.dataset).name, "hashes": dict(sorted(hashes.items()))}, indent=2) + "\n", encoding="utf-8")
    print(f"run {status}: {attempted} pages attempted, {succeeded} fetched, {len(changes)} changed, {len(unreachable)} unreachable"
          + ("; dry run, no baseline written" if a.dry_run else ("; first run, baselines recorded" if first_run and status != "failed" else "")))
    for u in unreachable: print("  unreachable:", u["instrument"], u["url"], u["error"])
    sys.exit(3 if changes else (5 if status == "failed" else (4 if status == "partial" else 0)))


if __name__ == "__main__":
    main()
