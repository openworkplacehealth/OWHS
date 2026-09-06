#!/usr/bin/env python3
"""The search index on site/search.html, generated from the pages, the registry dataset and the question bank.

Usage:
  python tools/build_search_index.py             rewrite the index in site/search.html
  python tools/build_search_index.py --check     regenerate in memory and fail if the committed index differs
  python tools/build_search_index.py --self-test the index's shape: every target exists, no markup, no duplicates, withheld wording stays withheld

Three kinds of entry, each {"t", "n", "x", "u"}: t is the kind, n the name shown, x the text searched
and excerpted, u the page relative to site/.

  Page        every HTML page under site/ except the search page, the 404 page and the instrument
              record pages; n from <title> (the site suffix removed), x from the page's meta description
  Instrument  every record in the current registry dataset (the one registry/build_registry_site.py
              names); n the display name, x the full name and the constructs claimed
  Question    every item in site/question-bank/question-bank.json; n the topic, x the wording (only
              where the bank renders it; withheld wording is never indexed), the source survey and the group

The index is the one JavaScript constant `IDX` in site/search.html; nothing else on the page changes.
"""
import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SEARCH = SITE / "search.html"
REGISTRY_GENERATOR = ROOT / "registry" / "build_registry_site.py"
QUESTION_BANK = SITE / "question-bank" / "question-bank.json"
EXCERPT = 300
SKIP_PAGES = {"search.html", "404.html"}
IDX_LINE = re.compile(r"^const IDX=(\[.*?\]);$", re.M | re.S)


def strip_tags(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def page_name(title):
    for sep in (" · ", " | "):
        if sep in title:
            return title.split(sep)[0].strip()
    return title.strip()


def current_dataset():
    """The dataset file the registry site is generated from; read from the generator so there is one source of truth."""
    m = re.search(r'^DATASET = "([^"]+)"', REGISTRY_GENERATOR.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("tool error: registry/build_registry_site.py does not name its DATASET")
    return json.loads((ROOT / "registry" / m.group(1)).read_text(encoding="utf-8"))


def page_entries(site=SITE, record_ids=()):
    out = []
    for f in sorted(site.rglob("*.html")):
        rel = f.relative_to(site).as_posix()
        if f.name in SKIP_PAGES or (f.parent.name == "instrument-registry" and f.stem in record_ids):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        desc = re.search(r'<meta name="description" content="([^"]*)"', text)
        if not title:
            continue
        if desc and desc.group(1).strip():
            x = strip_tags(desc.group(1))
        else:
            para = re.search(r"<p[^>]*>(.*?)</p>", text, re.S)
            x = strip_tags(para.group(1)) if para else ""
        out.append({"t": "Page", "n": page_name(strip_tags(title.group(1))), "x": x[:EXCERPT], "u": rel})
    return out


def instrument_entries(dataset):
    out = []
    for r in dataset["records"]:
        name = r.get("identity", {}).get("name", r["display_name"])
        x = (name + " " + (r.get("constructs_claimed") or "")).strip()
        out.append({"t": "Instrument", "n": r["display_name"], "x": x[:EXCERPT], "u": f"instrument-registry/{r['instrument_id']}.html"})
    return out


def question_entries(bank):
    out = []
    for it in bank["items"]:
        wording = it.get("wording", "") if it.get("render", True) else ""
        x = " ".join(p for p in (wording, it.get("source_survey", ""), it.get("group_name", "")) if p)
        out.append({"t": "Question", "n": it["topic"], "x": x[:EXCERPT], "u": f"question-bank/group-{it['group']}.html"})
    return out


def build():
    dataset = current_dataset()
    ids = {r["instrument_id"] for r in dataset["records"]}
    bank = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
    return page_entries(SITE, ids) + instrument_entries(dataset) + question_entries(bank)


def render(page_text, entries):
    line = "const IDX=" + json.dumps(entries, ensure_ascii=False) + ";"
    if len(IDX_LINE.findall(page_text)) != 1:
        raise SystemExit("tool error: site/search.html does not carry exactly one IDX constant")
    return IDX_LINE.sub(lambda m: line, page_text, count=1)


def shape_problems(entries, site=SITE):
    found = []
    seen = set()
    for e in entries:
        if set(e) != {"t", "n", "x", "u"} or e["t"] not in ("Page", "Instrument", "Question"):
            found.append(f"bad shape: {e}")
            continue
        if not e["n"]:
            found.append(f"empty name for {e['u']}")
        if "<" in e["n"] or "<" in e["x"]:
            found.append(f"markup in the entry for {e['u']}")
        if not (site / e["u"]).exists():
            found.append(f"target does not exist: {e['u']}")
        key = (e["t"], e["n"], e["u"])
        if key in seen:
            found.append(f"duplicate entry: {key}")
        seen.add(key)
    return found


def self_test():
    failures = 0

    def t(label, ok, detail=""):
        nonlocal failures
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else str(detail)[:300])

    entries = build()
    t("the generated index has no shape problem", not shape_problems(entries), shape_problems(entries))
    dataset = current_dataset()
    t("one Instrument entry per dataset record", sum(e["t"] == "Instrument" for e in entries) == len(dataset["records"]))
    bank = json.loads(QUESTION_BANK.read_text(encoding="utf-8"))
    t("one Question entry per question-bank item", sum(e["t"] == "Question" for e in entries) == len(bank["items"]))
    withheld = [it for it in bank["items"] if not it.get("render", True)]
    qx = {e["n"]: e["x"] for e in entries if e["t"] == "Question"}
    t("withheld wording is never indexed", all(it["wording"] not in qx.get(it["topic"], "") for it in withheld if it.get("wording")), len(withheld))
    t("no Page entry points at an instrument record page or the search page", not any(e["t"] == "Page" and (e["u"] == "search.html" or e["u"] in {f"instrument-registry/{r['instrument_id']}.html" for r in dataset["records"]}) for e in entries))
    t("the registry index, the question bank and the specification are indexed as pages", {"instrument-registry/index.html", "question-bank/index.html", "spec/index.html"} <= {e["u"] for e in entries if e["t"] == "Page"})
    t("no excerpt is longer than the limit", all(len(e["x"]) <= EXCERPT for e in entries))
    t("the page name drops the site suffix", page_name("How it works · OWHS") == "How it works" and page_name("Instrument Registry | Open Workplace Health Standard") == "Instrument Registry")
    fake = [{"t": "Page", "n": "x", "x": "<b>", "u": "nowhere.html"}, {"t": "Page", "n": "x", "x": "", "u": "nowhere.html"}]
    probs = shape_problems(fake)
    t("markup, a missing target and a duplicate are each named", any("markup" in p for p in probs) and any("does not exist" in p for p in probs) and any("duplicate" in p for p in probs), probs)
    page = SEARCH.read_text(encoding="utf-8")
    t("the committed page carries exactly one IDX constant and the render replaces only it", render(page, entries).count("const IDX=") == 1 and IDX_LINE.sub("", render(page, entries)) == IDX_LINE.sub("", page))
    print(f"{10 - failures}/10 search-index checks passed")
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    entries = build()
    probs = shape_problems(entries)
    if probs:
        print("PROBLEM " + "\nPROBLEM ".join(probs))
        return 1
    page = SEARCH.read_text(encoding="utf-8")
    new = render(page, entries)
    if "--check" in argv:
        if new != page:
            print("PROBLEM site/search.html's index differs from a fresh build; run python tools/build_search_index.py")
            return 1
        print(f"up to date: the search index carries {len(entries)} entries built from the pages, the registry dataset and the question bank")
        return 0
    SEARCH.write_text(new, encoding="utf-8")
    counts = {k: sum(e["t"] == k for e in entries) for k in ("Page", "Instrument", "Question")}
    print(f"wrote site/search.html with {len(entries)} entries: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
