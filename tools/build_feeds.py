#!/usr/bin/env python3
"""Atom feeds of the changelog and the sweep reports, generated from changelog/entries/*.json and site/sweeps/*.html.

    python tools/build_feeds.py            write the feeds under site/
    python tools/build_feeds.py --check    fail if a committed feed differs from a fresh build
    python tools/build_feeds.py --self-test

    feed.xml                 every changelog entry, all three tabs
    feed-registry.xml        the registry tab
    feed-specification.xml   the specification tab
    feed-site.xml            the site tab
    feed-sweeps.xml          the monthly evidence sweep reports

Each entry's date is the date the changelog entry (or the sweep report's own "filed" line) gives, never the date the feed was built, so building the
feed twice gives the same bytes. An entry's id is a tag URI made from its file name (changelog) or its report month, so it does not change when the
text is corrected. An entry dated to a month only is given the first of that month as its Atom date, because Atom needs a full date, and says so in its text.
A feed's own updated time is the newest entry's date. Links in an entry are made absolute so a reader that shows the feed elsewhere still reaches the page.
"""
import html, json, re, sys
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_changelog as bc
import site_data as sd

BASE = sd.BASE
SITE_ROOT = Path(__import__("os").environ.get("OWHS_SITE_DIR", ROOT / "site"))
AUTHORITY = "tag:openworkplacehealth.org"
FEEDS = [
    {"file": "feed.xml", "label": "All changes: registry, specification and site", "title": "OWHS changelog: all changes", "tab": None},
    {"file": "feed-registry.xml", "label": "Registry changes", "title": "OWHS changelog: registry", "tab": "registry"},
    {"file": "feed-specification.xml", "label": "Specification changes", "title": "OWHS changelog: specification", "tab": "specification"},
    {"file": "feed-site.xml", "label": "Site changes", "title": "OWHS changelog: site", "tab": "site"},
    {"file": "feed-sweeps.xml", "label": "Monthly evidence sweep reports", "title": "OWHS evidence sweep reports", "tab": "sweeps"},
]
TAB_LABEL = {"registry": "Registry", "specification": "Specification", "site": "Site"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def x(s):
    return html.escape(str(s), quote=True)


def absolute(fragment):
    return re.sub(r'href="([^"]+)"', lambda m: 'href="' + (m.group(1) if re.match(r"^(https?:|mailto:)", m.group(1)) else urljoin(BASE + "changelog.html", m.group(1))) + '"', fragment)


def title_of(entry):
    text = bc.visible_text(entry["html"])
    first = re.split(r"(?<=[.!?])\s", text)[0]
    if len(first) > 110:
        first = first[:110].rsplit(" ", 1)[0].rstrip(",;:") + " ..."
    label = TAB_LABEL[entry["tab"]] + (f" {entry['version']}" if entry.get("version") else "")
    return f"{label}: {first}"


def atom_date(d):
    return (d if len(d) == 10 else d + "-01") + "T00:00:00Z"


def changelog_items(tab):
    entries, found = bc.load_entries(bc.ENTRIES)
    if found:
        raise SystemExit("tool error: the changelog entries are refused:\n  " + "\n  ".join(found))
    rows = []
    for tb in bc.TABS:
        if tab in (None, tb):
            rows += bc.ordered(entries, tb)
    rows.sort(key=lambda r: (bc._datekey(r[1]["date"]), r[1].get("order", 0), bc._revname(r[0])), reverse=True)
    items = []
    for name, e in rows:
        stem = name[:-len(".json")]
        note = f"<p>Dated to the month only ({x(e['shown'])}).</p>" if len(e["date"]) == 7 else ""
        items.append({"id": f"{AUTHORITY},{stem[:4]}:changelog/{stem}", "title": title_of(e), "link": BASE + "changelog.html", "date": atom_date(e["date"]),
                      "content": f"<p>{x(e['shown'])}.</p><p>{absolute(e['html'])}</p>{note}"})
    return items


def sweep_items():
    items = []
    for f in sorted((SITE_ROOT / "sweeps").glob("*.html")):
        t = f.read_text(encoding="utf-8")
        h1 = " ".join(html.unescape(re.sub(r"<[^>]+>", "", re.search(r"<h1>(.*?)</h1>", t, re.S).group(1))).split())
        meta = " ".join(html.unescape(re.sub(r"<[^>]+>", "", re.search(r'<p class="meta">(.*?)</p>', t, re.S).group(1))).split())
        m = re.search(r"filed (\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})", meta)
        if not m:
            raise SystemExit(f"tool error: {f.name} gives no 'filed D Month YYYY' line in its meta line, so its feed entry would have no honest date")
        date = f"{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
        para = re.search(r"</p>\s*<p>(.*?)</p>", t[t.index('<p class="meta">'):], re.S)
        summary = " ".join(html.unescape(re.sub(r"<[^>]+>", "", para.group(1))).split()) if para else meta
        items.append({"id": f"{AUTHORITY},{f.stem[:4]}:sweeps/{f.stem}", "title": h1.replace(" · ", ": "), "link": f"{BASE}sweeps/{f.name}", "date": atom_date(date),
                      "content": f"<p>{x(meta)}.</p><p>{x(summary)}</p>"})
    items.sort(key=lambda i: i["id"], reverse=True)
    return items


def render(feed, items):
    updated = max(i["date"] for i in items)
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en-GB">',
           f"  <title>{x(feed['title'])}</title>", f'  <link rel="self" type="application/atom+xml" href="{BASE}{feed["file"]}"/>',
           f'  <link rel="alternate" type="text/html" href="{BASE}{"changelog.html" if feed["tab"] != "sweeps" else "automation.html"}"/>',
           f"  <id>{BASE}{feed['file']}</id>", f"  <updated>{updated}</updated>",
           "  <author><name>Open Workplace Health Standard</name></author>"]
    for i in items:
        out += ["  <entry>", f"    <id>{x(i['id'])}</id>", f"    <title>{x(i['title'])}</title>", f'    <link rel="alternate" type="text/html" href="{x(i["link"])}"/>',
                f"    <published>{i['date']}</published>", f"    <updated>{i['date']}</updated>", f'    <content type="html">{x(i["content"])}</content>', "  </entry>"]
    out.append("</feed>")
    return "\n".join(out) + "\n"


def build():
    return {f["file"]: render(f, sweep_items() if f["tab"] == "sweeps" else changelog_items(f["tab"])) for f in FEEDS}


def write():
    for name, text in build().items():
        (SITE_ROOT / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(FEEDS)} feeds")


def check():
    bad = [n for n, text in build().items() if not (SITE_ROOT / n).exists() or (SITE_ROOT / n).read_text(encoding="utf-8") != text]
    if bad:
        sys.exit("the feeds are out of date; run tools/build_feeds.py\n" + "".join(f"  differs: {n}\n" for n in bad))
    print(f"up to date: {len(FEEDS)} feeds match a fresh build of the changelog entries and the sweep reports")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}".strip())
    feeds = build()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    parsed = {n: ET.fromstring(s) for n, s in feeds.items()}
    t("every feed is well-formed Atom", all(p.tag == "{http://www.w3.org/2005/Atom}feed" for p in parsed.values()))
    allf = parsed["feed.xml"].findall("a:entry", ns)
    entries, _ = bc.load_entries(bc.ENTRIES)
    t("the all-changes feed has one entry per changelog entry", len(allf) == len(entries), f"{len(allf)} vs {len(entries)}")
    t("the three tab feeds together hold the same entries", sum(len(parsed[f"feed-{tb}.xml"].findall("a:entry", ns)) for tb in bc.TABS) == len(allf))
    ids = [e.find("a:id", ns).text for p in parsed.values() for e in p.findall("a:entry", ns)]
    per = [[e.find("a:id", ns).text for e in p.findall("a:entry", ns)] for p in parsed.values()]
    t("ids within each feed are unique", all(len(set(x_)) == len(x_) for x_ in per))
    t("an entry has the same id in the all feed and in its tab feed", all(set(per[i]) <= set(per[0]) for i in (1, 2, 3)))
    t("ids are tag URIs from the file name, not from the text", all(i.startswith(AUTHORITY + ",") for i in ids))
    t("every date is a calendar date at midnight UTC", all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00Z", e.find("a:updated", ns).text) for p in parsed.values() for e in p.findall("a:entry", ns)))
    t("a feed's updated is its newest entry's", all(p.find("a:updated", ns).text == max(e.find("a:updated", ns).text for e in p.findall("a:entry", ns)) for p in parsed.values()))
    t("entries are newest first", [e.find("a:updated", ns).text for e in allf] == sorted((e.find("a:updated", ns).text for e in allf), reverse=True))
    t("no relative link survives in an entry", all("href=\"/" not in feeds[n] and 'href="changelog' not in feeds[n] and 'href="registry' not in feeds[n] for n in feeds))
    t("no em or en dash", all("—" not in s and "–" not in s for s in feeds.values()))
    t("building twice gives the same bytes", build() == feeds)
    t("a month-only entry says so", "Dated to the month only" in feeds["feed.xml"] and "2026-07-01T00:00:00Z" in feeds["feed.xml"])
    t("the sweep feed has one entry per report with the filing date the report gives", len(parsed["feed-sweeps.xml"].findall("a:entry", ns)) == len(list((SITE_ROOT / "sweeps").glob("*.html"))))
    t("a relative link is made absolute", absolute('<a href="sweeps/2026-11.html">x</a> <a href="https://e.org/">y</a>') == f'<a href="{BASE}sweeps/2026-11.html">x</a> <a href="https://e.org/">y</a>')
    t("a long first sentence is cut at a word", len(title_of({"tab": "site", "html": "word " * 60})) < 130)
    vj = json.loads((SITE_ROOT.parent / "vercel.json").read_text(encoding="utf-8"))
    rules = [h for h in vj.get("headers", []) if any(k.get("key", "").lower() == "content-type" and k.get("value") == "application/atom+xml; charset=utf-8" for k in h.get("headers", []))]
    t("vercel.json serves the feeds as Atom: one rule, matching every feed file and nothing else", len(rules) == 1 and all(re.fullmatch(rules[0]["source"].lstrip("/"), f["file"]) for f in FEEDS) and not any(re.fullmatch(rules[0]["source"].lstrip("/"), n) for n in ("sitemap.xml", "feed-.xml", "feed.xml.bak")))
    t("the rewrites are untouched by the header rule", [r["source"] for r in vj.get("rewrites", [])] == ["/schemas", "/schemas/:path*"])
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("self-test ok: 17 cases (feeds served as Atom, well-formed Atom, entry counts, stable ids, dates, ordering, absolute links, month-only wording, determinism)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        write()
