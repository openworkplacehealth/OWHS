#!/usr/bin/env python3
"""The changelog page is generated from one file per entry, so two changes never collide.

Usage:
  python tools/build_changelog.py            render the three tabs of site/changelog.html from changelog/entries/*.json
  python tools/build_changelog.py --check    refuse a committed page that differs from a fresh render
  python tools/build_changelog.py --self-test

Each entry is a JSON object: tab (registry, specification or site), date (YYYY-MM-DD, or YYYY-MM when only
the month is known), shown (the date as printed), html (the row text, links allowed), and for the registry and
specification tabs a version. An optional order places entries that share a date: higher first. The page's
head, navigation, footer and stamped lines are not touched; only the rows and the tab counts are rewritten.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRIES = ROOT / "changelog" / "entries"
PAGE = ROOT / "site" / "changelog.html"
TABS = ("registry", "specification", "site")
VERSIONED = ("registry", "specification")
DASHES = "\u2014\u2013"  # em and en dashes are not site copy


def load_entries(folder):
    """The entries, checked one by one; a problem names the file."""
    found, entries = [], []
    files = sorted(p for p in pathlib.Path(folder).glob("*.json"))
    if not files:
        found.append(f"no entries under {folder}")
    for p in files:
        try:
            e = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError) as err:
            found.append(f"{p.name}: not readable JSON ({err})")
            continue
        if not isinstance(e, dict):
            found.append(f"{p.name}: not an object")
            continue
        keys = set(e)
        allowed = {"tab", "date", "shown", "html", "version", "order"}
        if keys - allowed:
            found.append(f"{p.name}: unknown keys {sorted(keys - allowed)}")
        for k in ("tab", "date", "shown", "html"):
            if not isinstance(e.get(k), str) or not e[k].strip():
                found.append(f"{p.name}: {k} is missing or empty")
        if e.get("tab") not in TABS:
            found.append(f"{p.name}: tab must be one of {', '.join(TABS)}")
        if isinstance(e.get("date"), str) and not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", e["date"]):
            found.append(f"{p.name}: date must be YYYY-MM-DD or YYYY-MM")
        if e.get("tab") in VERSIONED and (not isinstance(e.get("version"), str) or not e["version"].strip()):
            found.append(f"{p.name}: a {e.get('tab')} entry needs a version")
        if e.get("tab") == "site" and "version" in e:
            found.append(f"{p.name}: a site entry carries no version")
        if "order" in e and (isinstance(e["order"], bool) or not isinstance(e["order"], int)):
            found.append(f"{p.name}: order must be an integer")
        for k in ("html", "shown", "version"):
            v = e.get(k)
            if isinstance(v, str) and (any(d in v for d in DASHES) or "</td>" in v or "<tr" in v or "\n" in v):
                found.append(f"{p.name}: {k} must be one line of row text without dashes of the em or en kind and without table markup")
        if not found or all(not f.startswith(p.name) for f in found):
            entries.append((p.name, e))
    return entries, found


def ordered(entries, tab):
    rows = [(name, e) for name, e in entries if e["tab"] == tab]
    return sorted(rows, key=lambda x: (_datekey(x[1]["date"]), x[1].get("order", 0), _revname(x[0])), reverse=True)


def _datekey(d):
    return d + ("-00" if len(d) == 7 else "")


def _revname(name):
    """Files sharing a date and order come out in filename order (a-before-b) after the reverse sort."""
    return tuple(-ord(c) for c in name)


def row_html(tab, e):
    if tab in VERSIONED:
        return f'    <tr><td class="mono">{e["version"]}</td><td>{e["shown"]}</td><td>{e["html"]}</td></tr>\n'
    return f'    <tr><td>{e["shown"]}</td><td>{e["html"]}</td></tr>\n'


def render(page_text, entries):
    """The page with each tab's rows and count replaced; a page without the expected markup raises ValueError."""
    out = page_text
    for tab in TABS:
        rows = ordered(entries, tab)
        panel = re.search(r'(<section class="panel" id="panel-%s".*?<tr><th>.*?</th></tr>\n)(.*?)(  </table>)' % tab, out, re.S)
        if not panel:
            raise ValueError(f"the {tab} panel with its header row and table end was not found exactly as expected")
        if len(re.findall(r'id="panel-%s"' % tab, out)) != 1:
            raise ValueError(f"the {tab} panel appears more than once")
        out = out[:panel.start()] + panel.group(1) + "".join(row_html(tab, e) for _, e in rows) + panel.group(3) + out[panel.end():]
        count = re.subn(r'(id="tab-%s"[^>]*>[^<]*<span class="count">)\d+(</span>)' % tab, lambda m: m.group(1) + str(len(rows)) + m.group(2), out)
        if count[1] != 1:
            raise ValueError(f"the {tab} tab count was not found exactly once")
        out = count[0]
    return out


def main(argv):
    if "--self-test" in argv:
        return self_test()
    entries, found = load_entries(ENTRIES)
    if found:
        print("PROBLEM the entries were refused; nothing was written:")
        for f in found:
            print("  " + f)
        return 1
    page = PAGE.read_text(encoding="utf-8")
    try:
        fresh = render(page, entries)
    except ValueError as e:
        print(f"PROBLEM {e}; nothing was written")
        return 1
    if "--check" in argv:
        if fresh != page:
            print("PROBLEM site/changelog.html differs from a fresh render of changelog/entries; run tools/build_changelog.py")
            return 1
        print(f"ok: site/changelog.html is a fresh render of {len(entries)} entries")
        return 0
    PAGE.write_text(fresh, encoding="utf-8")
    counts = {tab: len(ordered(entries, tab)) for tab in TABS}
    print(("wrote" if fresh != page else "unchanged") + f" site/changelog.html from {len(entries)} entries: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    return 0


def self_test():
    import tempfile
    probes, failures = 0, 0

    def t(label, ok, detail=""):
        nonlocal probes, failures
        probes += 1
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else str(detail)[:300])

    entries, found = load_entries(ENTRIES)
    t("the committed entries load without a problem", not found, found)
    page = PAGE.read_text(encoding="utf-8")
    t("the committed page is a fresh render of the committed entries", render(page, entries) == page)
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        def put(name, obj):
            (d / name).write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
        base = {"tab": "site", "date": "2026-09-06", "shown": "6 Sep 2026", "html": "one"}
        put("2026-09-06-one.json", base)
        put("2026-09-06-two.json", {**base, "html": "two"})
        put("2026-09-05-older.json", {**base, "date": "2026-09-05", "shown": "5 Sep 2026", "html": "older"})
        put("2026-09-06-first.json", {**base, "html": "placed first", "order": 5})
        put("2026-07-month.json", {"tab": "specification", "date": "2026-07", "shown": "Jul 2026", "version": "v0.1", "html": "month only"})
        put("2026-09-01-reg.json", {"tab": "registry", "date": "2026-09-01", "shown": "1 Sep 2026", "version": "v0.8.0", "html": "registry row"})
        es, fs = load_entries(d)
        t("a folder of valid entries loads", not fs, fs)
        site = [e["html"] for _, e in ordered(es, "site")]
        t("newest date first; within a date the higher order first, then filename order", site == ["placed first", "one", "two", "older"], site)
        fresh = render(page, es)
        t("rendered counts equal the rows placed in each tab", re.search(r'id="tab-site"[^>]*>[^<]*<span class="count">4<', fresh) and re.search(r'id="tab-registry"[^>]*>[^<]*<span class="count">1<', fresh) and re.search(r'id="tab-specification"[^>]*>[^<]*<span class="count">1<', fresh))
        t("a versioned tab renders the version cell and a site row does not", '<tr><td class="mono">v0.8.0</td><td>1 Sep 2026</td><td>registry row</td></tr>' in fresh and "<tr><td>6 Sep 2026</td><td>placed first</td></tr>" in fresh)
        t("rendering is idempotent", render(fresh, es) == fresh)
        norm = lambda text: re.sub(r'<span class="count">\d+</span>', '<span class="count">N</span>', text)
        head = norm(page[:page.index('<section class="panel"')])
        tail = page[page.rindex("</section>"):]
        t("the head, navigation, footer, stamped lines and script are untouched (only the counts move)", norm(fresh).startswith(head) and fresh.endswith(tail))
        bad = {
            "unknown tab": {**base, "tab": "news"},
            "missing html": {k: v for k, v in base.items() if k != "html"},
            "bad date": {**base, "date": "6 Sep 2026"},
            "site with version": {**base, "version": "v1"},
            "registry without version": {"tab": "registry", "date": "2026-09-01", "shown": "1 Sep 2026", "html": "x"},
            "em dash in the row": {**base, "html": "a \u2014 b"},
            "table markup in the row": {**base, "html": "a</td><td>b"},
            "unknown key": {**base, "author": "x"},
            "order as a string": {**base, "order": "1"},
            "not an object": "[1, 2]",
            "not JSON": "{",
        }
        for label, obj in bad.items():
            e = d / "zz-bad.json"
            e.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
            _, fs = load_entries(d)
            t(f"an entry with {label} is refused by name", any(f.startswith("zz-bad.json") for f in fs), fs)
            e.unlink()
        _, fs = load_entries(d / "empty")
        t("a missing entries folder is refused", bool(fs))
        for label, mutate in (("a page missing a panel", lambda s: s.replace('id="panel-site"', 'id="panel-elsewhere"')), ("a page with a duplicated panel", lambda s: s.replace('<section class="panel" id="panel-site"', '<section class="panel" id="panel-site" ' + "></section><section class=\"panel\" id=\"panel-site\"")), ("a page missing a tab count", lambda s: s.replace('id="tab-site"', 'id="tab-x"'))):
            try:
                render(mutate(page), es)
                t(f"{label} is refused", False)
            except ValueError as err:
                t(f"{label} is refused", True)
    print(f"{probes - failures}/{probes} changelog build checks passed" if not failures else f"self-test: {failures} of {probes} checks FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
