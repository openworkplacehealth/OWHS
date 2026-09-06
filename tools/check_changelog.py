#!/usr/bin/env python3
"""A change to a published surface carries a changelog entry.

Usage:
  python tools/check_changelog.py --base origin/main   compare HEAD with the base and refuse a public change without an entry
  python tools/check_changelog.py --self-test          the rule on fixed path lists

Published surfaces are the site, the specification, the schemas, the code lists, the registry
dataset, the examples, the docs and the README. A change that touches only tooling, tests,
workflows or evidence artefacts needs no entry. The two changelogs are CHANGELOG.md (specification,
schemas, validator, examples) and site/changelog.html (registry, specification and site tabs).
"""
import subprocess
import sys

PUBLISHED_PREFIXES = ("site/", "spec/", "schemas/", "codelists/", "registry/", "examples/", "docs/", "profiles/")
PUBLISHED_FILES = ("README.md",)
CHANGELOGS = ("CHANGELOG.md", "site/changelog.html")


def published(path):
    """True when the path is a surface a reader can see; the changelogs themselves are not counted as a change to record."""
    if path in CHANGELOGS:
        return False
    return path in PUBLISHED_FILES or any(path.startswith(p) for p in PUBLISHED_PREFIXES)


def problems(paths):
    """The published paths that changed without a changelog entry, or an empty list."""
    changed_public = sorted(p for p in paths if published(p))
    if not changed_public:
        return []
    if any(p in CHANGELOGS for p in paths):
        return []
    return changed_public


def changed_paths(base):
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"tool error: git diff against {base} failed: {out.stderr.strip()}")
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def self_test():
    cases = [
        ("a site page without an entry is refused", ["site/index.html"], ["site/index.html"]),
        ("a site page with a site changelog row passes", ["site/index.html", "site/changelog.html"], []),
        ("a schema change with a repository changelog entry passes", ["schemas/v0.2/OrgUnit.json", "CHANGELOG.md"], []),
        ("a schema change without an entry is refused", ["schemas/v0.2/OrgUnit.json", "tools/validate.py"], ["schemas/v0.2/OrgUnit.json"]),
        ("tooling, tests and workflows alone need no entry", ["tools/validate.py", ".github/workflows/validate.yml", "requirements.txt"], []),
        ("evidence artefacts alone need no entry", ["evidence/candidates/2026-09.json"], []),
        ("the changelog alone is not a change to record", ["site/changelog.html"], []),
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
    print(f"{len(cases) - failures}/{len(cases)} changelog checks passed")
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--base" not in argv or argv.index("--base") + 1 >= len(argv):
        print(__doc__)
        return 2
    base = argv[argv.index("--base") + 1]
    missing = problems(changed_paths(base))
    if missing:
        print("PROBLEM these published paths changed and neither CHANGELOG.md nor site/changelog.html did:")
        for p in missing:
            print("  " + p)
        return 1
    print(f"ok: every published change since {base} carries a changelog entry")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
