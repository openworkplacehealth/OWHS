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
from html.parser import HTMLParser

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


class PageFacts(HTMLParser):
    """Title, meta description and first paragraph of a page, read structurally: attribute order, quoting and whitespace do not matter."""

    def __init__(self):
        super().__init__()
        self.title = None
        self.description = None
        self.first_paragraph = None
        self._in_title = False
        self._p_depth = 0
        self._p_text = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title" and self.title is None:
            self._in_title = True
            self._t = []
        elif tag == "meta" and (a.get("name") or "").strip().lower() == "description" and self.description is None:
            self.description = re.sub(r"\s+", " ", html.unescape(a.get("content") or "")).strip()
        elif tag in ("script", "style"):
            self._skip += 1
        elif tag == "p" and self.first_paragraph is None:
            self._p_depth += 1

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = re.sub(r"\s+", " ", "".join(self._t)).strip()
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "p" and self._p_depth:
            self._p_depth -= 1
            if self._p_depth == 0 and self.first_paragraph is None:
                text = re.sub(r"\s+", " ", "".join(self._p_text)).strip()
                self._p_text = []
                if text:
                    self.first_paragraph = text

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self._t.append(data)
        elif self._p_depth:
            self._p_text.append(data)


def page_facts(text):
    p = PageFacts()
    p.feed(text)
    p.close()
    return p.title, p.description, p.first_paragraph


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
        title, desc, para = page_facts(text)
        if not title:
            raise SystemExit(f"PROBLEM {rel} has no title, so it cannot be indexed; give the page a <title> or exclude it explicitly")
        x = desc if desc else (para or "")
        out.append({"t": "Page", "n": page_name(title), "x": x[:EXCERPT], "u": rel})
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
    reordered = "<html><title>A · OWHS</title>\n<meta content='Actual description' name=\"description\">\n<p>Fallback</p></html>"
    t("a meta description is found whatever its attribute order and quoting", page_facts(reordered) == ("A · OWHS", "Actual description", "Fallback"))
    nested = "<html><head><title> Nested\n page </title><style>p{}</style></head><body><script>var x=1;</script><p>First <b>bold</b> and <a href='#'>linked</a> text.</p><p>Second</p></body></html>"
    t("the first paragraph is read through nested tags, ignoring script and style", page_facts(nested) == ("Nested page", None, "First bold and linked text."))
    empty_desc = "<html><title>B · OWHS</title><meta name=\"description\" content=\"  \"><p>Used</p></html>"
    t("an empty description falls back to the first paragraph", page_facts(empty_desc)[1] == "" and (page_facts(empty_desc)[1] or page_facts(empty_desc)[2]) == "Used")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "ok.html").write_text("<title>Fine · OWHS</title><p>x</p>", encoding="utf-8")
        (d / "untitled.html").write_text("<p>no title here</p>", encoding="utf-8")
        try:
            page_entries(d, ())
            missing_refused = False
        except SystemExit as e:
            missing_refused = "untitled.html has no title" in str(e)
        t("a page without a title is refused by name rather than silently omitted", missing_refused)
        (d / "untitled.html").write_text("<title>   </title><p>blank title</p>", encoding="utf-8")
        try:
            page_entries(d, ())
            empty_refused = False
        except SystemExit as e:
            empty_refused = "untitled.html has no title" in str(e)
        t("a page with an empty title is refused by name", empty_refused)
    committed = json.loads(IDX_LINE.search(page).group(1))
    t("the committed index equals a fresh build (current-output equality)", committed == entries)
    print(f"{16 - failures}/16 search-index checks passed")
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
