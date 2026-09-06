#!/usr/bin/env python3
"""A change to a published surface carries a changelog entry.

Usage:
  python tools/check_changelog.py --base origin/main   compare HEAD with the base and refuse a public change without an entry
  python tools/check_changelog.py --self-test          the rule on fixed path lists
  python tools/check_changelog.py --counts             each tab's count on site/changelog.html equals its number of rows
  python tools/check_changelog.py --fix-counts         rewrite the counts to the row numbers

Published surfaces are the site, the specification, the schemas, the code lists, the registry
dataset, the examples, the docs and the README. A change that touches only tooling, tests,
workflows or evidence artefacts needs no entry. The two changelogs are CHANGELOG.md (specification,
schemas, validator, examples) and site/changelog.html (registry, specification and site tabs). The
site changelog is generated from one file per entry under changelog/entries/, so an entry is a new
file there, never a hand edit of the page; tools/build_changelog.py --check keeps the page current.
"""
import pathlib
import re
import subprocess
import sys

PUBLISHED_PREFIXES = ("site/", "spec/", "schemas/", "codelists/", "registry/", "examples/", "docs/", "profiles/")
PUBLISHED_FILES = ("README.md",)
CHANGELOGS = ("CHANGELOG.md", "site/changelog.html")
ENTRIES_PREFIX = "changelog/entries/"


def published(path):
    """True when the path is a surface a reader can see; the changelogs themselves are not counted as a change to record."""
    if path in CHANGELOGS:
        return False
    return path in PUBLISHED_FILES or any(path.startswith(p) for p in PUBLISHED_PREFIXES)


def carries_entry(paths):
    """True when the change adds or edits a site changelog entry file or a line of CHANGELOG.md. The generated page alone does not count."""
    return any(p == "CHANGELOG.md" or (p.startswith(ENTRIES_PREFIX) and p.endswith(".json")) for p in paths)


def problems(paths):
    """The published paths that changed without a changelog entry, or an empty list."""
    changed_public = sorted(p for p in paths if published(p))
    if not changed_public:
        return []
    if carries_entry(paths):
        return []
    return changed_public


SITE_CHANGELOG = pathlib.Path(__file__).resolve().parents[1] / "site" / "changelog.html"
TABS = ("registry", "specification", "site")


def tab_counts(page_text):
    """(tab, rows, count) for each of the three tabs; a tab whose panel or count is missing raises ValueError."""
    out = []
    for name in TABS:
        panel = re.search(r'<section class="panel" id="panel-%s".*?</section>' % name, page_text, re.S)
        count = re.search(r'id="tab-%s"[^>]*>[^<]*<span class="count">(\d+)</span>' % name, page_text)
        if not panel or not count:
            raise ValueError(f"the {name} tab or its panel was not found")
        if len(re.findall(r'id="tab-%s"' % name, page_text)) != 1 or len(re.findall(r'id="panel-%s"' % name, page_text)) != 1:
            raise ValueError(f"the {name} tab or its panel appears more than once")
        out.append((name, len(re.findall(r"<tr><td", panel.group(0))), int(count.group(1))))
    return out


def count_problems(page_text):
    try:
        return [f"the {n} tab says {c} and has {r} rows" for n, r, c in tab_counts(page_text) if r != c]
    except ValueError as e:
        return [str(e)]


def fix_counts(page_text):
    for name, rows, count in tab_counts(page_text):
        if rows != count:
            page_text = re.sub(r'(id="tab-%s"[^>]*>[^<]*<span class="count">)\d+(</span>)' % name, lambda m: m.group(1) + str(rows) + m.group(2), page_text, count=1)
    return page_text


def changed_paths(base):
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"tool error: git diff against {base} failed: {out.stderr.strip()}")
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def self_test():
    cases = [
        ("a site page without an entry is refused", ["site/index.html"], ["site/index.html"]),
        ("a site page with a new site changelog entry file passes", ["site/index.html", "changelog/entries/2026-09-06-site-home-copy.json", "site/changelog.html"], []),
        ("a site page with only the generated page edited by hand is refused", ["site/index.html", "site/changelog.html"], ["site/index.html"]),
        ("a file under changelog/entries that is not an entry does not count", ["site/index.html", "changelog/entries/README.md"], ["site/index.html"]),
        ("a schema change with a repository changelog entry passes", ["schemas/v0.2/OrgUnit.json", "CHANGELOG.md"], []),
        ("a schema change without an entry is refused", ["schemas/v0.2/OrgUnit.json", "tools/validate.py"], ["schemas/v0.2/OrgUnit.json"]),
        ("tooling, tests and workflows alone need no entry", ["tools/validate.py", ".github/workflows/validate.yml", "requirements.txt"], []),
        ("evidence artefacts alone need no entry", ["evidence/candidates/2026-09.json"], []),
        ("the changelog alone is not a change to record", ["site/changelog.html"], []),
        ("an entry file alone is not a change to record", ["changelog/entries/2026-09-06-site-note.json", "site/changelog.html"], []),
        ("the README is a published surface", ["README.md"], ["README.md"]),
        ("a registry dataset change is a published surface", ["registry/dataset-v0.11.0.json"], ["registry/dataset-v0.11.0.json"]),
        ("a doc page source is a published surface", ["docs/science.md"], ["docs/science.md"]),
        ("every refused path is listed, sorted", ["spec/OWHS-v0.2-draft.md", "site/spec/index.html"], ["site/spec/index.html", "spec/OWHS-v0.2-draft.md"]),
        ("an empty change passes", [], []),
    ]
    failures = 0
    for label, paths, want in cases:
        got = problems(paths)
        ok = got == want
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else f"got {got}")
    page = SITE_CHANGELOG.read_text(encoding="utf-8")
    count_cases = [
        ("the committed page's counts equal its rows", page, []),
        ("a row added without a count change is refused, naming the tab", page.replace('<h2 class="panel-title">Site</h2>\n  <table>\n    <tr><th>Date</th><th>What changed</th></tr>\n', '<h2 class="panel-title">Site</h2>\n  <table>\n    <tr><th>Date</th><th>What changed</th></tr>\n    <tr><td>1 Jan 2026</td><td>x</td></tr>\n', 1), ["the site tab says {} and has {} rows"]),
        ("a missing tab is refused", page.replace('id="tab-site"', 'id="tab-elsewhere"', 1), ["the site tab or its panel was not found"]),
        ("a duplicated tab button, the shape a merge leaves behind, is refused", page.replace('  <button type="button" class="tab" role="tab" id="tab-site"', '  <button type="button" class="tab" role="tab" id="tab-site" aria-controls="panel-site" aria-selected="false">Site <span class="count">1</span></button>\n  <button type="button" class="tab" role="tab" id="tab-site"', 1), ["the site tab or its panel appears more than once"]),
    ]
    for label, text, want in count_cases:
        got = count_problems(text)
        if want and "{}" in want[0]:
            n = [r for r in tab_counts(page) if r[0] == "site"][0]
            want = [want[0].format(n[2], n[1] + 1)]
        ok = got == want
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else f"got {got}")
    fixed = fix_counts(count_cases[1][1])
    ok = count_problems(fixed) == []
    failures += not ok
    print(("ok  " if ok else "FAIL"), "fix-counts rewrites a stale count to the row number")
    cases += count_cases + [None]
    print(f"{len(cases) - failures}/{len(cases)} changelog checks passed")
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--counts" in argv:
        found = count_problems(SITE_CHANGELOG.read_text(encoding="utf-8"))
        if found:
            print("PROBLEM " + "; ".join(found))
            return 1
        print("ok: every tab count on site/changelog.html equals its number of rows")
        return 0
    if "--fix-counts" in argv:
        text = SITE_CHANGELOG.read_text(encoding="utf-8")
        fixed = fix_counts(text)
        SITE_CHANGELOG.write_text(fixed, encoding="utf-8")
        print("counts rewritten" if fixed != text else "counts already equal their rows")
        return 0
    if "--base" not in argv or argv.index("--base") + 1 >= len(argv):
        print(__doc__)
        return 2
    base = argv[argv.index("--base") + 1]
    missing = problems(changed_paths(base))
    if missing:
        print("PROBLEM these published paths changed without a changelog entry (a file under changelog/entries/ or a line of CHANGELOG.md):")
        for p in missing:
            print("  " + p)
        return 1
    print(f"ok: every published change since {base} carries a changelog entry")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
