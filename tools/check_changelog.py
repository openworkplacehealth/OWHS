#!/usr/bin/env python3
"""A change to a published surface carries a changelog entry.

Usage:
  python tools/check_changelog.py --base origin/main   compare HEAD with the base and refuse a public change without an entry
  python tools/check_changelog.py --self-test          the rule on path lists and on real temporary repositories
  python tools/check_changelog.py --counts             each tab's count on site/changelog.html equals its number of rows
  python tools/check_changelog.py --fix-counts         rewrite the counts to the row numbers

Published surfaces fall into three categories, each with its changelog:
  site           site/ and docs/ (the rendered pages)          a new site-tab entry file
  registry       registry/                                     a new registry-tab entry file
  specification  spec/, schemas/, codelists/, examples/,       a new specification-tab entry file AND a new entry
                 profiles/ and the conformance checkers        added to CHANGELOG.md under a dated section
                 (validate, measurement, profiles, mappings,
                 and the entity-graph validator once composed)
  README.md                                                    a new entry added to CHANGELOG.md under a dated section
A CHANGELOG.md entry is a "### " heading with words under a "## <day> <Month> <year>" section that is a real calendar
date (a new section or an existing one), with at least one line of body text beneath it before the next heading. An
entry ends at any "## " heading; an undated or impossible section carries no date; headings compare with their
whitespace normalised. A bare date, a generic heading, a heading without a body, blank lines or re-spacing record nothing.
An entry is a file ADDED under changelog/entries/ in the change, valid as tools/build_changelog.py
loads it, in the tab its category names. Editing, deleting or re-spacing an old entry, or adding
blank lines to CHANGELOG.md, does not record a new change. The gate reads the base and head objects
through git; the generated page site/changelog.html is never counted as the entry. A change that
touches only other tooling, tests, workflows or evidence artefacts needs no entry.
"""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

CATEGORY_PREFIXES = {"site": ("site/", "docs/"), "registry": ("registry/",), "specification": ("spec/", "schemas/", "codelists/", "examples/", "profiles/")}
CATEGORY_FILES = {"specification": ("tools/validate.py", "tools/check_measurement.py", "tools/check_profiles.py", "tools/check_codelist_mappings.py", "tools/check_entity_graph.py"), "readme": ("README.md",)}
NEEDS_TAB = {"site": "site", "registry": "registry", "specification": "specification"}
NEEDS_REPOSITORY_LOG = ("specification", "readme")
PUBLISHED_PREFIXES = tuple(p for ps in CATEGORY_PREFIXES.values() for p in ps)
PUBLISHED_FILES = tuple(f for fs in CATEGORY_FILES.values() for f in fs)
CHANGELOGS = ("CHANGELOG.md", "site/changelog.html")
ENTRIES_PREFIX = "changelog/entries/"


def published(path):
    """True when the path is a surface a reader can see; the changelogs themselves are not counted as a change to record."""
    if path in CHANGELOGS:
        return False
    return path in PUBLISHED_FILES or any(path.startswith(p) for p in PUBLISHED_PREFIXES)


def category(path):
    for cat, prefixes in CATEGORY_PREFIXES.items():
        if any(path.startswith(p) for p in prefixes):
            return cat
    for cat, files in CATEGORY_FILES.items():
        if path in files:
            return cat
    return None


def problems(paths, added_entry_tabs=(), repository_log_added=False):
    """The published paths whose category lacks its required new entry, or an empty list.

    paths: every changed path. added_entry_tabs: the tabs of entry files ADDED and valid in the change.
    repository_log_added: a new dated section or entry heading was added to CHANGELOG.md."""
    found = []
    for p in sorted(paths):
        cat = category(p)
        if cat is None or p in CHANGELOGS:
            continue
        tab = NEEDS_TAB.get(cat)
        if tab and tab not in added_entry_tabs:
            found.append(f"{p}: needs a new {tab}-tab entry file under {ENTRIES_PREFIX}")
        if cat in NEEDS_REPOSITORY_LOG and not repository_log_added:
            found.append(f"{p}: needs a new dated section or entry heading in CHANGELOG.md")
    return found


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"tool error: git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def load_entry_checker(repo):
    spec = importlib.util.spec_from_file_location("build_changelog", pathlib.Path(repo) / "tools" / "build_changelog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def added_valid_entry_tabs(repo, base, head="HEAD"):
    """Tabs of entry files added between base and head that load as valid entries at head; an invalid added entry is reported."""
    tabs, invalid = set(), []
    checker = load_entry_checker(repo)
    for line in git(repo, "diff", "--name-status", f"{base}...{head}").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[-1].startswith(ENTRIES_PREFIX) or not parts[-1].endswith(".json") or parts[0][0] != "A":
            continue
        path = parts[-1]
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / pathlib.Path(path).name
            target.write_text(git(repo, "show", f"{head}:{path}"), encoding="utf-8")
            entries, found = checker.load_entries(tmp)
        if found:
            invalid.extend(f"{path}: {f.split(': ', 1)[-1]}" for f in found)
        else:
            tabs.add(entries[0][1]["tab"])
    return tabs, invalid


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
DATED_SECTION = re.compile(r"^## (\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})\s*$")
SECTION_HEADING = re.compile(r"^## \S")
ENTRY_HEADING = re.compile(r"^### \S")


def dated_section(line):
    """The normalised date of a '## <day> <Month> <year>' heading when it is a real calendar date, else None."""
    m = DATED_SECTION.match(line.strip())
    if not m:
        return None
    try:
        import datetime
        d = datetime.date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))
    except ValueError:
        return None
    return d.isoformat()


def normalise_heading(line):
    return re.sub(r"\s+", " ", line.strip())


def log_entries(text):
    """(section date, entry heading, body lines) for every '### ' entry heading in a CHANGELOG.md text, in order. An entry ends at the next
    entry heading or at any '## ' section heading; a section heading is never body text. An undated or impossible section resets the date
    to None, so entries beneath it carry no dated context. Headings are whitespace-normalised so re-spacing does not create a new identity."""
    out, date, heading, body = [], None, None, []
    for line in text.splitlines():
        stripped = line.strip()
        if SECTION_HEADING.match(stripped) and not ENTRY_HEADING.match(stripped):
            if heading:
                out.append((date, heading, body))
            date, heading, body = dated_section(stripped), None, []
        elif ENTRY_HEADING.match(stripped):
            if heading:
                out.append((date, heading, body))
            heading, body = normalise_heading(stripped), []
        elif heading is not None:
            body.append(line)
    if heading:
        out.append((date, heading, body))
    return out


def repository_log_added(repo, base, head="HEAD"):
    """True when CHANGELOG.md at head carries an entry that base does not: a ### heading with words under a dated section, with at least one
    non-blank body line. A bare date heading, a generic heading without a body, blank lines or re-spacing of old entries do not count."""
    try:
        base_text = git(repo, "show", f"{base}:CHANGELOG.md")
    except SystemExit:
        base_text = ""
    try:
        head_text = git(repo, "show", f"{head}:CHANGELOG.md")
    except SystemExit:
        return False
    old_ids = {(d, h) for d, h, _ in log_entries(base_text)}
    for date, heading, body in log_entries(head_text):
        body_lines = tuple(re.sub(r"\s+", " ", ln.strip()) for ln in body if ln.strip())
        if date is not None and body_lines and (date, heading) not in old_ids:
            return True
    return False


def gate(repo, base, head="HEAD"):
    """Every problem for the change between base and head in the repository, read from git objects."""
    paths = [ln.strip() for ln in git(repo, "diff", "--name-only", f"{base}...{head}").splitlines() if ln.strip()]
    tabs, invalid = added_valid_entry_tabs(repo, base, head)
    return invalid + problems(paths, tabs, repository_log_added(repo, base, head))


SITE_CHANGELOG = pathlib.Path(__file__).resolve().parents[1] / "site" / "changelog.html"
TABS = ("registry", "specification", "site")


class RowCounter(HTMLParser):
    """Counts table data rows structurally: a tr element that contains a td, whatever the letter case of the tags."""

    def __init__(self):
        super().__init__()
        self.rows = 0
        self.in_tr = False
        self.tr_has_td = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_tr, self.tr_has_td = True, False
        elif tag == "td" and self.in_tr:
            self.tr_has_td = True

    def handle_endtag(self, tag):
        if tag == "tr" and self.in_tr:
            self.rows += 1 if self.tr_has_td else 0
            self.in_tr = False


def data_rows(fragment):
    counter = RowCounter()
    counter.feed(fragment)
    counter.close()
    return counter.rows


def tab_counts(page_text):
    """(tab, rows, count) for each of the three tabs; a tab whose panel or count is missing raises ValueError."""
    out = []
    for name in TABS:
        panel = re.search(r'<section class="panel" id="panel-%s".*?</section>' % name, page_text, re.S | re.I)
        count = re.search(r'id="tab-%s"[^>]*>[^<]*<span class="count">(\d+)</span>' % name, page_text)
        if not panel or not count:
            raise ValueError(f"the {name} tab or its panel was not found")
        if len(re.findall(r'id="tab-%s"' % name, page_text, re.I)) != 1 or len(re.findall(r'id="panel-%s"' % name, page_text, re.I)) != 1:
            raise ValueError(f"the {name} tab or its panel appears more than once")
        out.append((name, data_rows(panel.group(0)), int(count.group(1))))
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


def self_test():
    cases = [
        ("a site page without an entry is refused", (["site/index.html"], set(), False), ["site/index.html: needs a new site-tab entry file under changelog/entries/"]),
        ("a site page with a new valid site-tab entry passes", (["site/index.html", "changelog/entries/2026-09-06-site-home-copy.json", "site/changelog.html"], {"site"}, False), []),
        ("a site page with only a registry-tab entry is refused", (["site/index.html", "changelog/entries/2026-09-06-registry-x.json"], {"registry"}, False), ["site/index.html: needs a new site-tab entry file under changelog/entries/"]),
        ("a site page with only the generated page edited is refused", (["site/index.html", "site/changelog.html"], set(), False), ["site/index.html: needs a new site-tab entry file under changelog/entries/"]),
        ("a schema change with both logs passes", (["schemas/v0.2/OrgUnit.json", "CHANGELOG.md", "changelog/entries/2026-09-06-specification-x.json"], {"specification"}, True), []),
        ("a schema change with only the repository log is refused", (["schemas/v0.2/OrgUnit.json", "CHANGELOG.md"], set(), True), ["schemas/v0.2/OrgUnit.json: needs a new specification-tab entry file under changelog/entries/"]),
        ("a schema change with only a site-tab entry is refused twice over", (["schemas/v0.2/OrgUnit.json", "changelog/entries/2026-09-06-site-x.json"], {"site"}, False), ["schemas/v0.2/OrgUnit.json: needs a new specification-tab entry file under changelog/entries/", "schemas/v0.2/OrgUnit.json: needs a new dated section or entry heading in CHANGELOG.md"]),
        ("the reference validator is a published surface needing both logs", (["tools/validate.py"], set(), False), ["tools/validate.py: needs a new specification-tab entry file under changelog/entries/", "tools/validate.py: needs a new dated section or entry heading in CHANGELOG.md"]),
        ("the measurement and profile checkers are conformance surfaces needing both logs", (["tools/check_measurement.py", "tools/check_profiles.py"], set(), False), ["tools/check_measurement.py: needs a new specification-tab entry file under changelog/entries/", "tools/check_measurement.py: needs a new dated section or entry heading in CHANGELOG.md", "tools/check_profiles.py: needs a new specification-tab entry file under changelog/entries/", "tools/check_profiles.py: needs a new dated section or entry heading in CHANGELOG.md"]),
        ("the entity-graph validator is a conformance surface needing both logs; its regression suite is not", (["tools/check_entity_graph.py", "tools/check_remaining_entities.py"], set(), False), ["tools/check_entity_graph.py: needs a new specification-tab entry file under changelog/entries/", "tools/check_entity_graph.py: needs a new dated section or entry heading in CHANGELOG.md"]),
        ("other tooling, tests and workflows alone need no entry", (["tools/build_search_index.py", ".github/workflows/validate.yml", "requirements.txt"], set(), False), []),
        ("evidence artefacts alone need no entry", (["evidence/candidates/2026-09.json"], set(), False), []),
        ("the changelog alone is not a change to record", (["site/changelog.html"], set(), False), []),
        ("an entry file alone is not a change to record", (["changelog/entries/2026-09-06-site-note.json", "site/changelog.html"], {"site"}, False), []),
        ("the README needs a repository-log heading", (["README.md"], set(), False), ["README.md: needs a new dated section or entry heading in CHANGELOG.md"]),
        ("the README with a repository-log heading passes", (["README.md", "CHANGELOG.md"], set(), True), []),
        ("a registry dataset change needs a registry-tab entry", (["registry/dataset-v0.11.0.json"], set(), False), ["registry/dataset-v0.11.0.json: needs a new registry-tab entry file under changelog/entries/"]),
        ("a doc page source is a site surface", (["docs/science.md"], set(), False), ["docs/science.md: needs a new site-tab entry file under changelog/entries/"]),
        ("every refused path is listed, sorted", (["spec/OWHS-v0.2-draft.md", "site/spec/index.html"], set(), False), ["site/spec/index.html: needs a new site-tab entry file under changelog/entries/", "spec/OWHS-v0.2-draft.md: needs a new specification-tab entry file under changelog/entries/", "spec/OWHS-v0.2-draft.md: needs a new dated section or entry heading in CHANGELOG.md"]),
        ("an empty change passes", ([], set(), False), []),
    ]
    failures = 0
    for label, (paths, tabs, log), want in cases:
        got = problems(paths, tabs, log)
        ok = got == want
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else f"got {got}")
    page = SITE_CHANGELOG.read_text(encoding="utf-8")
    count_cases = [
        ("the committed page's counts equal its rows", page, []),
        ("a row added without a count change is refused, naming the tab", page.replace('<h2 class="panel-title">Site</h2>\n  <table>\n    <tr><th>Date</th><th>What changed</th></tr>\n', '<h2 class="panel-title">Site</h2>\n  <table>\n    <tr><th>Date</th><th>What changed</th></tr>\n    <tr><td>1 Jan 2026</td><td>x</td></tr>\n', 1), ["the site tab says {} and has {} rows"]),
        ("an upper-case row smuggled inside a cell is counted as a row and refused", page.replace('<h2 class="panel-title">Site</h2>\n  <table>\n    <tr><th>Date</th><th>What changed</th></tr>\n', '<h2 class="panel-title">Site</h2>\n  <table>\n    <tr><th>Date</th><th>What changed</th></tr>\n    <tr><td>1 Jan 2026</td><td>A</TD></TR><TR><TD>6 Sep 2026</TD><TD>B</td></tr>\n', 1), ["the site tab says {} and has {} rows"]),
        ("a missing tab is refused", page.replace('id="tab-site"', 'id="tab-elsewhere"', 1), ["the site tab or its panel was not found"]),
        ("a duplicated tab button, the shape a merge leaves behind, is refused", page.replace('  <button type="button" class="tab" role="tab" id="tab-site"', '  <button type="button" class="tab" role="tab" id="tab-site" aria-controls="panel-site" aria-selected="false">Site <span class="count">1</span></button>\n  <button type="button" class="tab" role="tab" id="tab-site"', 1), ["the site tab or its panel appears more than once"]),
    ]
    for label, text, want in count_cases:
        got = count_problems(text)
        if want and "{}" in want[0]:
            n = [r for r in tab_counts(page) if r[0] == "site"][0]
            extra = 2 if "upper-case" in label else 1
            want = [want[0].format(n[2], n[1] + extra)]
        ok = got == want
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else f"got {got}")
    fixed = fix_counts(count_cases[1][1])
    ok = count_problems(fixed) == []
    failures += not ok
    print(("ok  " if ok else "FAIL"), "fix-counts rewrites a stale count to the row number")
    # real temporary repositories: the gate reads base and head objects, not filenames
    repo_cases = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        here = pathlib.Path(__file__).resolve().parents[1]
        (root / "tools").mkdir()
        for name in ("build_changelog.py", "check_changelog.py"):
            (root / "tools" / name).write_bytes((here / "tools" / name).read_bytes())
        (root / "changelog" / "entries").mkdir(parents=True)
        for src in sorted((here / "changelog" / "entries").glob("*.json"))[:3]:
            (root / "changelog" / "entries" / src.name).write_bytes(src.read_bytes())
        (root / "site").mkdir()
        (root / "site" / "changelog.html").write_bytes((here / "site" / "changelog.html").read_bytes())
        (root / "site" / "index.html").write_text("<p>home</p>\n", encoding="utf-8")
        (root / "schemas").mkdir()
        (root / "schemas" / "OrgUnit.json").write_text("{}\n", encoding="utf-8")
        (root / "tools" / "validate.py").write_text("print('v1')\n", encoding="utf-8")
        base_log = "# Changelog\n\n## 1 September 2026\n\n### Added: a first entry\n\ntext\n"
        (root / "CHANGELOG.md").write_text(base_log, encoding="utf-8")
        (root / "README.md").write_text("# OWHS\n", encoding="utf-8")
        def run(*args):
            return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.org", *args], capture_output=True, text=True, check=True)
        run("init", "-q", "-b", "main")
        run("add", "-A")
        run("commit", "-q", "-m", "base")
        base = run("rev-parse", "HEAD").stdout.strip()
        entry = json.dumps({"tab": "site", "date": "2026-09-06", "shown": "6 Sep 2026", "html": "Home copy changed."})

        def scenario(label, edits, want_pass, needle=None):
            nonlocal failures, repo_cases
            run("checkout", "-q", base)
            run("checkout", "-q", "-B", "case")
            for path, content in edits.items():
                target = root / path
                if content is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
            run("add", "-A")
            run("commit", "-q", "--allow-empty", "-m", label)
            got = gate(root, base)
            ok = (not got) if want_pass else (bool(got) and (needle is None or any(needle in g for g in got)))
            failures += not ok
            repo_cases += 1
            print(("ok  " if ok else "FAIL"), "repository: " + label, "" if ok else f"got {got}")
        old_entry = sorted((root / "changelog" / "entries").glob("*.json"))[0]
        old_rel = str(old_entry.relative_to(root))
        old_text = old_entry.read_text(encoding="utf-8")
        scenario("a site change without any entry fails", {"site/index.html": "<p>changed</p>\n"}, False, "site-tab entry")
        scenario("a site change with a new valid site entry passes", {"site/index.html": "<p>changed</p>\n", "changelog/entries/2026-09-06-site-home.json": entry}, True)
        scenario("a site change with a blank line appended to CHANGELOG.md fails", {"site/index.html": "<p>changed</p>\n", "CHANGELOG.md": base_log + "\n"}, False, "site-tab entry")
        scenario("a site change with a historical entry deleted fails", {"site/index.html": "<p>changed</p>\n", old_rel: None}, False, "site-tab entry")
        scenario("a site change with whitespace appended to an old entry fails", {"site/index.html": "<p>changed</p>\n", old_rel: old_text + "\n"}, False, "site-tab entry")
        scenario("a site change with only a registry-tab entry fails", {"site/index.html": "<p>changed</p>\n", "changelog/entries/2026-09-06-registry-x.json": json.dumps({"tab": "registry", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.9.1", "html": "A registry row."})}, False, "site-tab entry")
        scenario("a schema change with only the repository log fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: OrgUnit\n\ntext\n"}, False, "specification-tab entry")
        scenario("a schema change with only a site-tab entry fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "changelog/entries/2026-09-06-site-x.json": entry}, False, "CHANGELOG.md")
        scenario("a schema change with both logs passes", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: OrgUnit\n\ntext\n", "changelog/entries/2026-09-06-specification-orgunit.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "OrgUnit changed."})}, True)
        scenario("a validator change with no entry fails", {"tools/validate.py": "print('v2')\n"}, False, "tools/validate.py")
        scenario("a schema change whose repository log gains only a generic heading fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## Not a dated entry\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change whose repository log gains a bare date with nothing beneath fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## 6 September 2026\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change whose repository log gains an entry heading with no body fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: OrgUnit\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change with a genuine additional entry under the existing same-day section passes", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n### Changed: OrgUnit again\n\nmore text\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, True)
        scenario("a schema change whose repository log gains an undated section with an entry beneath it fails (date context resets)", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## Undated notes\n\n### Changed: OrgUnit\n\ntext\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change whose repository log gains an impossible date section fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n## 32 September 2026\n\n### Changed: OrgUnit\n\ntext\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change whose repository log only re-spaces an old entry heading fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log.replace("### Added: a first entry", "### Added: a first  entry"), "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change whose new entry heading is followed only by a section heading fails (a heading is not body)", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log + "\n### Changed: OrgUnit\n\n## Undated notes\n", "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        scenario("a schema change whose repository log only re-spaces an old entry fails", {"schemas/OrgUnit.json": '{"changed": true}\n', "CHANGELOG.md": base_log.replace("text\n", "text\n\n\n"), "changelog/entries/2026-09-06-specification-x.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "x"})}, False, "CHANGELOG.md")
        (root / "tools" / "check_measurement.py").write_text("print('m1')\n", encoding="utf-8"); (root / "tools" / "check_profiles.py").write_text("print('p1')\n", encoding="utf-8"); (root / "tools" / "check_entity_graph.py").write_text("print('g1')\n", encoding="utf-8")
        run("add", "-A"); run("commit", "-q", "-m", "checkers"); base = run("rev-parse", "HEAD").stdout.strip()
        scenario("a measurement-checker change with no entry fails", {"tools/check_measurement.py": "print('m2')\n"}, False, "tools/check_measurement.py")
        scenario("a profile-checker change with no entry fails", {"tools/check_profiles.py": "print('p2')\n"}, False, "tools/check_profiles.py")
        scenario("an entity-graph validator change with no entry fails", {"tools/check_entity_graph.py": "raise SystemExit(1)\n"}, False, "tools/check_entity_graph.py")
        scenario("an entity-graph validator change with both logs passes", {"tools/check_entity_graph.py": "print('g2')\n", "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: entity-graph validator\n\ntext\n", "changelog/entries/2026-09-06-specification-graph.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.2", "html": "Entity-graph validator changed."})}, True)
        scenario("a measurement-checker change with both logs passes", {"tools/check_measurement.py": "print('m2')\n", "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: measurement checker\n\ntext\n", "changelog/entries/2026-09-06-specification-measurement.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.2", "html": "Measurement checker changed."})}, True)
        scenario("a validator change with both logs passes", {"tools/validate.py": "print('v2')\n", "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: validator\n\ntext\n", "changelog/entries/2026-09-06-specification-validator.json": json.dumps({"tab": "specification", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.1", "html": "Validator changed."})}, True)
        scenario("a registry change with a new registry-tab entry passes", {"registry/dataset.json": "{}\n", "changelog/entries/2026-09-06-registry-dataset.json": json.dumps({"tab": "registry", "date": "2026-09-06", "shown": "6 Sep 2026", "version": "v0.9.1", "html": "Dataset changed."})}, True)
        scenario("a README change with a repository-log heading passes", {"README.md": "# OWHS\n\nmore\n", "CHANGELOG.md": base_log + "\n## 6 September 2026\n\n### Changed: README\n\ntext\n"}, True)
        scenario("a README change with only blank lines in CHANGELOG.md fails", {"README.md": "# OWHS\n\nmore\n", "CHANGELOG.md": base_log + "\n\n"}, False, "CHANGELOG.md")
        scenario("an added entry that is invalid (a fake date) is refused by name", {"site/index.html": "<p>changed</p>\n", "changelog/entries/2026-99-99-site-x.json": json.dumps({"tab": "site", "date": "2026-99-99", "shown": "x", "html": "y"})}, False, "calendar date")
        scenario("tooling and workflow changes alone pass", {"tools/build_search_index.py": "print('x')\n"}, True)
    total = len(cases) + len(count_cases) + 1 + repo_cases
    print(f"{total - failures}/{total} changelog checks passed")
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
    missing = gate(pathlib.Path(__file__).resolve().parents[1], base)
    if missing:
        print("PROBLEM published paths changed without the changelog entries their categories need (a new entry file in the right tab, and for the specification a new dated heading in CHANGELOG.md):")
        for p in missing:
            print("  " + p)
        return 1
    print(f"ok: every published change since {base} carries a changelog entry")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
