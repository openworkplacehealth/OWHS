#!/usr/bin/env python3
"""Shared facts for the site tools: the current registry dataset, the question bank, the wording of a licence position,
the short name of a record, and the dates the repository itself records. Imported by registry/build_registry_site.py (page titles,
descriptions and the plain-English answer), tools/stamp_canonical.py (structured data), tools/build_llms.py and
tools/build_reference_pages.py. Nothing here invents a value: every date, count and name is read from the committed dataset, the
question bank, the changelog entries or the code lists.

    python tools/site_data.py --self-test
"""
import json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://openworkplacehealth.org/"
GITHUB = "https://github.com/openworkplacehealth/OWHS"
REGISTRY_GENERATOR = ROOT / "registry" / "build_registry_site.py"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Licence positions, in the words of the dataset's own licence_classes. The audience is an employer, or a vendor acting for one,
# deploying the instrument in a workplace. Keys are checked against the dataset's classes, so a new class cannot be left unworded.
LICENCE_ANSWER = {
    "open": "an open licence, so commercial and non-commercial use are allowed without permission or fee",
    "free-no-permission": "free to use with no permission needed, but not under a formal open licence",
    "free-non-commercial": "free for research or non-commercial use only; employer or vendor use needs the steward's permission and may be charged",
    "free-with-registration": "free only after registration or application with the steward",
    "fee-bearing": "a paid licence is required for employer or vendor workplace use",
    "no-formal-licence": "no steward or instrument-level licence exists",
    "unverified": "not verified against the steward's current terms, so no licence class is asserted",
}

# Short names for page titles. A record not listed falls back to a short parenthetical abbreviation, else its display name.
SHORT_NAMES = {
    "ons-4": "ONS-4", "ons-4-life-satisfaction": "ONS-4 life satisfaction item", "ons-4-worthwhile": "ONS-4 worthwhile item",
    "ons-4-happiness": "ONS-4 happiness item", "ons-4-anxiety": "ONS-4 anxiety item",
    "who-5": "WHO-5", "wemwbs": "WEMWBS", "hse-msit": "HSE Management Standards Indicator Tool", "perma": "Workplace PERMA-Profiler",
    "uwes-9": "UWES-9", "phq-9": "PHQ-9", "gad-7": "GAD-7", "k10": "K10", "ghq-12": "GHQ-12", "copsoq-iii": "COPSOQ III",
    "mbi": "MBI", "cbi": "CBI", "olbi": "OLBI", "wai": "WAI", "was": "WAS", "wpai": "WPAI", "ipaq-sf": "IPAQ-SF", "isi": "ISI",
    "miss": "MISS", "tis-6": "TIS-6", "csps-wellbeing": "Civil Service People Survey wellbeing items",
    "eurofound-ewcs": "Eurofound EWCS/EQLS items", "fcs-maps": "MaPS financial capability survey items",
    "single-job-satisfaction": "Single-item job satisfaction", "single-stress": "SISQ single-item stress",
    "single-fatigue": "Single-item fatigue (Van Hooff)",
}


def current_dataset_name():
    """The dataset file the registry pages are generated from, read from the generator so there is one source of truth."""
    m = re.search(r'^DATASET = "([^"]+)"', REGISTRY_GENERATOR.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("tool error: registry/build_registry_site.py does not name its DATASET")
    return m.group(1)


def load_dataset():
    return json.loads((ROOT / "registry" / current_dataset_name()).read_text(encoding="utf-8"))


def load_bank(site=None):
    site = Path(site) if site else ROOT / "site"
    return json.loads((site / "question-bank" / "question-bank.json").read_text(encoding="utf-8"))


def short_name(rec):
    rid = rec["instrument_id"]
    if rid in SHORT_NAMES:
        return SHORT_NAMES[rid]
    m = re.search(r"\(([^()]*)\)\s*$", rec["display_name"])
    if m:
        first = m.group(1).split(",")[0].strip()
        if first and " " not in first and len(first) <= 14:
            return first
    return rec["display_name"]


def strict_date(text):
    """The date when the whole string is one ISO date; None otherwise (the dataset holds some prose in these fields)."""
    t = str(text or "").strip()
    return t if ISO.match(t) else None


def leading_date(text):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\b", str(text or "").strip())
    return m.group(1) if m else None


def licence_clause(ident):
    """(answer, date_clause_plain) for a record's identity block: what the record says about employer or vendor use and when it was checked."""
    cls = ident.get("licence_class")
    answer = LICENCE_ANSWER.get(cls, "")
    raw = ident.get("licence_verified_date")
    if strict_date(raw):
        when = f"Verified {strict_date(raw)}."
    elif cls == "unverified" or not leading_date(raw):
        when = ""
    else:
        when = f"Checked {leading_date(raw)}; the basis is stated on the record."
    return answer, when


def sentence_case(t):
    return t[:1].upper() + t[1:]


def record_title(rec):
    s = short_name(rec)
    t = f"{s}: free for employers to use? Licence and evidence | OWHS"
    if len(t) > 72:
        t = f"{s}: employer licence and evidence | OWHS"
    return t


def record_description(rec, on_watchlist=False):
    s = short_name(rec)
    answer, when = licence_clause(rec["identity"])
    if answer:
        head = f"Licence for employer or vendor use of {s}: {answer}."
    else:
        head = f"No licence class is recorded for {s}."
    tail = ("It is on the watchlist and not yet graded." if on_watchlist
            else "Graded psychometric evidence with citations; grades are single-rater and not a recommendation.")
    return " ".join(x for x in (head, when, tail) if x)


def latest_dataset_date(d):
    """The latest ISO date the dataset itself records: its generated date, its changelog, corrections and verifications, and each record's
    last_reviewed and verified licence date."""
    dates = [d.get("generated")]
    for key in ("changelog", "corrections", "verifications"):
        for row in d.get(key) or []:
            dates.append(row.get("date"))
    for r in d["records"]:
        dates.append(r.get("last_reviewed"))
        dates.append(strict_date(r["identity"].get("licence_verified_date")))
    dates = [x for x in dates if x and ISO.match(str(x))]
    return max(dates)


def changelog_entries(tab=None):
    out = []
    for f in sorted((ROOT / "changelog" / "entries").glob("*.json")):
        e = json.loads(f.read_text(encoding="utf-8"))
        if tab is None or e.get("tab") == tab:
            out.append(e)
    return out


def latest_changelog_date(tab):
    ds = [e["date"] for e in changelog_entries(tab) if ISO.match(str(e.get("date", "")))]
    return max(ds) if ds else None


def self_test():
    d = load_dataset()
    fails = []
    def t(name, ok):
        if not ok:
            fails.append(name)
    t("every licence class in the dataset has wording", set(d["licence_classes"]) == set(LICENCE_ANSWER))
    t("every record has a short name", all(short_name(r) for r in d["records"]))
    t("no short name is a parenthetical fragment", all("(" not in short_name(r) for r in d["records"]))
    t("every record's licence class has wording", all(r["identity"].get("licence_class") in LICENCE_ANSWER for r in d["records"]))
    t("a prose licence date is never printed as a date", licence_clause({"licence_class": "unverified", "licence_verified_date": "not verified this session"})[1] == "")
    t("a date followed by prose is flagged, not asserted as verified", "basis is stated" in licence_clause({"licence_class": "free-non-commercial", "licence_verified_date": "2026-07-12 (secondary)"})[1])
    t("a strict date is verified", licence_clause({"licence_class": "open", "licence_verified_date": "2026-07-12"})[1] == "Verified 2026-07-12.")
    titles = [record_title(r) for r in d["records"]]
    t("record titles are unique", len(set(titles)) == len(titles))
    t("titles end in the site name", all(x.endswith(" | OWHS") for x in titles))
    t("latest dataset date is an ISO date", ISO.match(latest_dataset_date(d)) is not None)
    if fails:
        print("self-test FAILED: " + "; ".join(fails)); sys.exit(1)
    print(f"self-test ok: {len(d['records'])} records worded, {len(LICENCE_ANSWER)} licence classes covered")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(__doc__)
