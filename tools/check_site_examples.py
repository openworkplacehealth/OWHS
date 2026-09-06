#!/usr/bin/env python3
"""The worked record on the "Inside the standard" page validates, and the validator output the page shows is real.

Usage:
  python tools/check_site_examples.py             check site/standard.html against schemas/AbsenceEpisode.json
  python tools/check_site_examples.py --self-test the check refuses a renamed field and an altered output line

The page shows one AbsenceEpisode record and says the schema accepts it, then shows what the reference
validator says about a record that carries a name, a raw identifier as its pseudonym, a free-text reason
and no provenance. This check parses the record out of the page, validates it through tools/validate.py,
derives the second record from the first by exactly those four changes, and compares the validator's
lines with the lines the page shows.
"""
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "standard.html"
SCHEMA = ROOT / "schemas" / "AbsenceEpisode.json"
VALIDATOR = ROOT / "tools" / "validate.py"


def blocks(page_text):
    """The record block and the output block that follow the 'A real record' heading, tags stripped and entities unescaped."""
    i = page_text.find("<h2>A real record</h2>")
    if i < 0:
        raise ValueError("the page has no 'A real record' section")
    pres = re.findall(r"<pre>(.*?)</pre>", page_text[i:], flags=re.S)
    if len(pres) < 2:
        raise ValueError("the section does not show a record followed by validator output")
    strip = lambda t: html.unescape(re.sub(r"<[^>]+>", "", t))
    return strip(pres[0]), strip(pres[1])


def record_from(block):
    return json.loads(re.sub(r"//[^\n]*", "", block))


def altered(record):
    """The second record: a name added, a raw identifier as the pseudonym, a free-text reason, no provenance."""
    r = dict(record)
    r["name"] = "Jane Smith"
    r["pseudonymId"] = "EMP-Jane-Smith"
    r["reasonCode"] = "back-pain"
    r.pop("sourceProvenance", None)
    return r


def validate(record):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(record, f)
        path = f.name
    try:
        out = subprocess.run([sys.executable, str(VALIDATOR), str(SCHEMA), path], capture_output=True, text=True)
    finally:
        os.unlink(path)
    return out.returncode, out.stdout.strip().splitlines()


def problems(page_text):
    try:
        rec_block, out_block = blocks(page_text)
        record = record_from(rec_block)
    except (ValueError, json.JSONDecodeError) as e:
        return [f"the page's record could not be read: {e}"]
    found = []
    rc, lines = validate(record)
    if rc != 0 or lines != ["VALID"]:
        found.append("the record the page calls valid does not validate: " + "; ".join(lines))
    rc, lines = validate(altered(record))
    shown = [ln for ln in out_block.splitlines() if ln.strip()]
    if rc == 0:
        found.append("the altered record validates, so the page's output block describes nothing")
    elif shown != lines:
        found.append("the validator output shown on the page differs from the validator's output:\n  shown:\n    " + "\n    ".join(shown) + "\n  actual:\n    " + "\n    ".join(lines))
    return found


def self_test():
    text = PAGE.read_text(encoding="utf-8")
    cases = [
        ("the committed page passes", text, False),
        ("a field the schema does not declare is refused", text.replace('"fitNoteFlag"', '"fitNoteProvided"', 1), True),
        ("an altered output line is refused", text.replace("'sourceProvenance' is a required property", "'sourceProvenance' is recommended", 1), True),
        ("a missing section is refused", text.replace("<h2>A real record</h2>", "<h2>A record</h2>", 1), True),
    ]
    failures = 0
    for label, variant, expect_problem in cases:
        got = problems(variant)
        ok = bool(got) == expect_problem
        failures += not ok
        print(("ok  " if ok else "FAIL"), label, "" if ok else got)
    print(f"{len(cases) - failures}/{len(cases)} site-example checks passed")
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    found = problems(PAGE.read_text(encoding="utf-8"))
    if found:
        print("PROBLEM " + "\nPROBLEM ".join(found))
        return 1
    print("ok: the worked record on site/standard.html validates and its shown validator output is the validator's")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
