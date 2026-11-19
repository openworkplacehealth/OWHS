#!/usr/bin/env python3
"""The sitemap, generated from the pages that exist and the date each page's content last changed.

    python tools/build_sitemap.py            update the ledger for changed pages (their date is today), write site/sitemap.xml
    python tools/build_sitemap.py --check    fail if a page changed without the ledger and sitemap being regenerated, or the sitemap is not the ledger's rendering
    python tools/build_sitemap.py --self-test
    python tools/build_sitemap.py --seed-from-git REF   one-off bootstrap: record each page as it was at REF, dated by the last commit that touched it

Every HTML page under site/ is listed except the 404 page. lastmod is the date the page's content last changed, and that is recorded, not
guessed. tools/sitemap-lastmod.json holds, for each page, a fingerprint of what a reader sees (the title, the description and the body, with the
managed footer line, the visit-counting script, the structured-data block and the search page's index removed) and the date that fingerprint first
appeared. When a page's fingerprint differs from the ledger's, the page changed: its date becomes the date the tool runs, so the date is the day the change
was made, not the day of any later commit or merge. --check recomputes every fingerprint and needs no clock and no git history, so it gives the same
answer on any machine and on CI. A page whose words did not change keeps its date, whatever else is regenerated around it.
"""
import datetime, hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SITE = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
LEDGER = Path(os.environ.get("OWHS_SITEMAP_LEDGER", ROOT / "tools" / "sitemap-lastmod.json"))
BASE = "https://openworkplacehealth.org/"
EXCLUDE = {"404.html"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def pages(site=SITE):
    return sorted(p.relative_to(site).as_posix() for p in site.rglob("*.html") if p.relative_to(site).as_posix() not in EXCLUDE)


def fingerprint(text):
    """sha256 (first 16 hex) of what a reader sees: title, description, and the body without managed blocks."""
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', text)
    i = text.find("<body")
    body = text[i:] if i >= 0 else text
    for pat in (r"<!-- mark -->.*?<!-- /mark -->", r"<!-- analytics -->.*?<!-- /analytics -->", r"<!-- jsonld -->.*?<!-- /jsonld -->", r"const IDX=\[.*?\];\n"):
        body = re.sub(pat, "", body, flags=re.S)
    blob = "\n".join([title.group(1) if title else "", desc.group(1) if desc else "", body])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def read_ledger(path=LEDGER):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: (v[0], v[1]) for k, v in data["pages"].items()}


def write_ledger(ledger, path=LEDGER):
    lines = ",\n".join(f"  {json.dumps(k)}: {json.dumps(list(v))}" for k, v in sorted(ledger.items()))
    path.write_text('{"note": "Fingerprint and date each page\'s content last changed; maintained by tools/build_sitemap.py, never by hand.",\n"pages": {\n' + lines + "\n}}\n", encoding="utf-8")


def url_of(rel):
    return BASE + ("" if rel == "index.html" else rel[:-len("index.html")] if rel.endswith("/index.html") else rel)


def render(ledger):
    order = sorted(ledger, key=lambda r: (r != "index.html", r))
    rows = "\n".join(f"  <url><loc>{url_of(r)}</loc><lastmod>{ledger[r][1]}</lastmod></url>" for r in order)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}\n</urlset>\n'


def current(site=SITE):
    return {rel: fingerprint((site / rel).read_text(encoding="utf-8")) for rel in pages(site)}


def update(site=SITE, ledger_path=LEDGER, today=None):
    today = today or os.environ.get("OWHS_TODAY") or datetime.date.today().isoformat()
    if not ISO.match(today):
        sys.exit(f"tool error: {today!r} is not a calendar date")
    old = read_ledger(ledger_path)
    new, changed = {}, []
    for rel, fp in current(site).items():
        if rel in old and old[rel][0] == fp:
            new[rel] = old[rel]
        else:
            new[rel] = (fp, today)
            changed.append(rel)
    write_ledger(new, ledger_path)
    (site / "sitemap.xml").write_text(render(new), encoding="utf-8")
    return new, changed


def problems(site=SITE, ledger_path=LEDGER):
    led = read_ledger(ledger_path)
    now = current(site)
    out = []
    for rel, fp in now.items():
        if rel not in led:
            out.append(f"{rel}: public page with no ledger entry")
        elif led[rel][0] != fp:
            out.append(f"{rel}: content changed since the ledger recorded it")
        elif not ISO.match(led[rel][1]):
            out.append(f"{rel}: ledger date {led[rel][1]!r} is not a calendar date")
    out += [f"{rel}: ledger entry for a page that does not exist" for rel in led if rel not in now]
    want = render({r: led[r] for r in now if r in led})
    sm = site / "sitemap.xml"
    if not sm.exists() or sm.read_text(encoding="utf-8") != want:
        out.append("sitemap.xml is not the rendering of the ledger")
    return out


def check():
    bad = problems()
    if bad:
        sys.exit("the sitemap is out of date; run tools/build_sitemap.py\n" + "".join(f"  {b}\n" for b in bad))
    print(f"up to date: sitemap.xml lists all {len(pages())} public pages, each dated by the last change to its content")


def seed_from_git(ref):
    def git(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout
    ledger = {}
    for rel in pages():
        try:
            text = git("show", f"{ref}:site/{rel}")
        except subprocess.CalledProcessError:
            continue
        date = git("log", "-1", "--format=%cs", ref, "--", f"site/{rel}").strip()
        ledger[rel] = (fingerprint(text), date)
    write_ledger(ledger)
    print(f"seeded {len(ledger)} pages from {ref}")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}")
    with tempfile.TemporaryDirectory() as tmp:
        site, led = Path(tmp) / "site", Path(tmp) / "ledger.json"
        (site / "sub").mkdir(parents=True)
        def page(name, body, extra=""):
            (site / name).write_text(f"<html><head><title>T</title><meta name=\"description\" content=\"D\">{extra}</head><body>{body}</body></html>", encoding="utf-8")
        page("index.html", "home"); page("sub/index.html", "sub"); page("sub/a.html", "a")
        (site / "404.html").write_text("<html><title>x</title><body>missing</body></html>", encoding="utf-8")
        new, changed = update(site, led, "2026-01-01")
        t("every page but the 404 is listed", sorted(new) == ["index.html", "sub/a.html", "sub/index.html"], str(sorted(new)))
        t("a new page takes the run date", all(v[1] == "2026-01-01" for v in new.values()))
        t("a fresh build passes its own check", not problems(site, led), str(problems(site, led)))
        xml = (site / "sitemap.xml").read_text()
        t("the home page is first and directory pages end in a slash", xml.index(BASE + "</loc>") < xml.index("sub/a.html") and "sub/</loc>" in xml)
        page("sub/a.html", "a changed")
        t("a changed page fails the check until regenerated", any("sub/a.html" in p and "changed" in p for p in problems(site, led)))
        _, changed = update(site, led, "2026-02-02")
        read = read_ledger(led)
        t("only the changed page takes the new date", changed == ["sub/a.html"] and read["sub/a.html"][1] == "2026-02-02" and read["index.html"][1] == "2026-01-01", str(read))
        page("index.html", "home", extra="<!-- jsonld --><script>x</script><!-- /jsonld -->")
        t("structured data and other head blocks do not move a date", not problems(site, led) or [p for p in problems(site, led)] == [])
        (site / "index.html").write_text((site / "index.html").read_text().replace("</body>", "<!-- mark -->new footer line<!-- /mark --></body>"), encoding="utf-8")
        t("the managed footer line does not move a date", not problems(site, led), str(problems(site, led)))
        page("index.html", "home", extra="")
        (site / "index.html").write_text((site / "index.html").read_text().replace("<title>T</title>", "<title>New title</title>"), encoding="utf-8")
        t("a changed title is a changed page", any("index.html" in p for p in problems(site, led)))
        update(site, led, "2026-03-03")
        (site / "sub" / "a.html").unlink()
        t("a deleted page leaves a stale ledger entry that fails the check", any("does not exist" in p for p in problems(site, led)))
        update(site, led, "2026-03-04")
        t("regenerating drops it", "sub/a.html" not in read_ledger(led) and "sub/a.html" not in (site / "sitemap.xml").read_text())
        (site / "sitemap.xml").write_text("tampered", encoding="utf-8")
        t("a sitemap that is not the ledger's rendering fails", any("rendering" in p for p in problems(site, led)))
        t("a page fingerprint ignores the search index constant", fingerprint("<body>x<script>const IDX=[1];\n</script></body>") == fingerprint("<body>x<script>const IDX=[2,3];\n</script></body>"))
        try:
            update(site, led, "yesterday"); t("a non-date run date is refused", False)
        except SystemExit:
            pass
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("self-test ok: 14 cases (listing, dating, unchanged pages keep their date, managed blocks ignored, stale and tampered files fail)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    elif "--seed-from-git" in sys.argv:
        seed_from_git(sys.argv[sys.argv.index("--seed-from-git") + 1])
    else:
        new, changed = update()
        print(f"sitemap.xml written: {len(new)} pages, {len(changed)} with changed content dated {max(v[1] for v in new.values())}")
