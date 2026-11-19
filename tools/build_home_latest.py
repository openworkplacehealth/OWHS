#!/usr/bin/env python3
"""The "Latest" strip on the home page: the three most recent changelog entries, rewritten between the <!-- latest --> markers in site/index.html.

    python tools/build_home_latest.py            rewrite the block
    python tools/build_home_latest.py --check    fail if the block is not a fresh render of changelog/entries
    python tools/build_home_latest.py --self-test

Each row is the entry's own date as printed, its tab, the first sentence of its text (cut at a word if long) and a link to the changelog. Nothing is
written that the entry does not say. Entries are taken newest first by date, then by the entry's own order within a tab, then file name, the same
rule the changelog page uses; across tabs on one date that is the tab-by-tab order, not a ranking of importance. Run after tools/build_changelog.py.
"""
import html, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_changelog as bc

PAGE = ROOT / "site" / "index.html"
BLOCK = re.compile(r"<!-- latest -->\n.*?<!-- /latest -->", re.S)
TAB = {"registry": "Registry", "specification": "Specification", "site": "Site"}
N = 3


def one_line(text, limit=170):
    first = re.split(r"(?<=[.!?])\s", text)[0]
    if len(first) > limit:
        first = first[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " ..."
    return first


def latest(entries, n=N):
    rows = sorted(entries, key=lambda r: (bc._datekey(r[1]["date"]), r[1].get("order", 0), bc._revname(r[0])), reverse=True)
    return rows[:n]


def block(entries):
    items = []
    for _, e in latest(entries):
        items.append(f'  <li><span class="when">{html.escape(e["shown"])}</span><span class="tab">{TAB[e["tab"]]}</span>{html.escape(one_line(bc.visible_text(e["html"])))} <a href="changelog.html">Changelog</a></li>')
    return ("<!-- latest -->\n<ul class=\"latest\">\n" + "\n".join(items) + "\n</ul>\n"
            "<p class=\"small\"><a href=\"changelog.html\">Every change</a> · <a href=\"feed.xml\">Atom feed</a> · <a href=\"status.html\">Is it maintained?</a></p>\n<!-- /latest -->")


def render(text, entries):
    if len(BLOCK.findall(text)) != 1:
        raise ValueError("the home page must carry exactly one <!-- latest --> block")
    return BLOCK.sub(lambda m: block(entries), text)


def main(argv):
    if "--self-test" in argv:
        return self_test()
    entries, found = bc.load_entries(bc.ENTRIES)
    if found:
        print("PROBLEM the changelog entries were refused:\n  " + "\n  ".join(found)); return 1
    text = PAGE.read_text(encoding="utf-8")
    fresh = render(text, entries)
    if "--check" in argv:
        if fresh != text:
            print("PROBLEM the home page's Latest strip differs from a fresh render; run tools/build_home_latest.py"); return 1
        print("ok: the home page's Latest strip shows the three most recent changelog entries")
        return 0
    PAGE.write_text(fresh, encoding="utf-8")
    print("wrote the Latest strip" if fresh != text else "Latest strip unchanged")
    return 0


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}".strip())
    mk = lambda d, tab, h, name, **k: (name, {"tab": tab, "date": d, "shown": d, "html": h, **k})
    es = [mk("2026-01-01", "site", "Oldest one.", "a.json"), mk("2026-03-01", "registry", "Third. More.", "c.json", version="v1"), mk("2026-02-01", "site", "Second.", "b.json"),
          mk("2026-04-01", "site", "Newest <em>one</em>. Tail.", "d.json"), mk("2026-04-01", "site", "Same day, placed first.", "e.json", order=5)]
    got = [n for n, _ in latest(es)]
    t("the three newest, newest first, order breaking a tie on one date", got == ["e.json", "d.json", "c.json"], got)
    t("only the first sentence is shown, as visible text", "Newest one." in block(es) and "Tail" not in block(es))
    t("a long sentence is cut at a word", len(one_line("word " * 80)) <= 175 and one_line("word " * 80).endswith("..."))
    t("a row carries date, tab and a link", '<span class="when">2026-04-01</span><span class="tab">Site</span>' in block(es) and 'href="changelog.html"' in block(es))
    t("text is escaped", "&lt;" in block([mk("2026-05-01", "site", "Require n &lt; 5.", "z.json")]) and "<em>" not in block(es))
    t("rendering is idempotent", render(render("x<!-- latest -->\n<!-- /latest -->y", es), es) == render("x<!-- latest -->\n<!-- /latest -->y", es))
    for bad in ("no block", "<!-- latest -->\n<!-- /latest --><!-- latest -->\n<!-- /latest -->"):
        try:
            render(bad, es); t(f"a page with {bad[:18]!r} is refused", False)
        except ValueError:
            pass
    real, found = bc.load_entries(bc.ENTRIES)
    t("the committed home page is a fresh render", not found and render(PAGE.read_text(encoding="utf-8"), real) == PAGE.read_text(encoding="utf-8"))
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); return 1
    print("self-test ok: 9 cases (newest three, tie order, first sentence, cut, escaping, idempotence, marker contract, committed page)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
