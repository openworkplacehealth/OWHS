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

# The same positions as a short answer for a page title: what an employer deploying the instrument needs to know first. One entry per class, in
# step with LICENCE_ANSWER (the self-test refuses a class with no entry). None means the title states no answer, because the registry asserts none
# for that class; the title then uses the neutral form.
LICENCE_TITLE = {
    "open": "open licence for employer use",
    "free-no-permission": "free for employers to use",
    "free-non-commercial": "permission needed for employer use",
    "free-with-registration": "registration needed for employer use",
    "fee-bearing": "paid licence needed for employer use",
    "no-formal-licence": "no formal licence for employer use",
    "unverified": None,
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


TITLE_LIMIT = 74


def record_title(rec):
    """The title states the answer for the record's licence class, from LICENCE_TITLE: 'PHQ-9: free for employers to use. Licence and evidence | OWHS'.
    A class with no stated answer (unverified) gets the neutral form. When the full form is over TITLE_LIMIT, the answer is kept and the tail is dropped,
    and only then the answer is replaced by the neutral wording."""
    s = short_name(rec)
    phrase = LICENCE_TITLE.get(rec["identity"].get("licence_class"))
    if phrase is None:
        forms = [f"{s}: licence for employer use and evidence | OWHS", f"{s}: employer licence and evidence | OWHS"]
    else:
        forms = [f"{s}: {phrase}. Licence and evidence | OWHS", f"{s}: {phrase} | OWHS", f"{s}: employer licence and evidence | OWHS"]
    return next((t for t in forms if len(t) <= TITLE_LIMIT), forms[-1])


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


CREATOR_LINE = re.compile(r"OWHS was created by (?:\[)?([A-Z][a-z]+ [A-Z][a-z]+)(?:\]\([^)]*\))? and is currently stewarded by (?:\[)?(\w+)")
STEWARD_LEGAL = re.compile(r"currently stewarded by \*\*([^*]+)\*\* \(trading as (\w+)\)")


def people():
    """The creator and the current steward, named exactly as GOVERNANCE.md and README.md name them. Both files must agree."""
    found = {}
    for name in ("GOVERNANCE.md", "README.md"):
        m = CREATOR_LINE.search((ROOT / name).read_text(encoding="utf-8"))
        if not m:
            raise SystemExit(f"tool error: {name} no longer says who created and who stewards OWHS in the expected sentence")
        found[name] = m.groups()
    if found["GOVERNANCE.md"] != found["README.md"]:
        raise SystemExit(f"tool error: GOVERNANCE.md and README.md name the creator and steward differently: {found}")
    legal = STEWARD_LEGAL.search((ROOT / "GOVERNANCE.md").read_text(encoding="utf-8"))
    if not legal or legal.group(2) != found["GOVERNANCE.md"][1]:
        raise SystemExit("tool error: GOVERNANCE.md does not give the steward's legal name and trading name as expected")
    creator, steward = found["GOVERNANCE.md"]
    given, family = creator.split(" ", 1)
    return {"creator": creator, "given": given, "family": family, "steward": steward, "steward_legal": legal.group(1).strip()}


def in_place_dates():
    """Dates of registry changelog entries that record a change made inside a published version number."""
    return sorted(e["date"] for e in changelog_entries("registry") if "in place" in e.get("version", "") and ISO.match(str(e["date"])))


def cite_works():
    """The three works a reader may cite, each with its version, date, licence, address and the caveat the source itself publishes.
    The cite page, CITATION.cff, .zenodo.json and the structured data on the cite page all read this one function."""
    d, q = load_dataset(), load_bank()
    spec_md = (ROOT / "spec" / "OWHS-v0.2-draft.md").read_text(encoding="utf-8")
    spec_title = spec_md.splitlines()[0].lstrip("# ").strip()
    spec_date = latest_changelog_date("specification")
    reg_name = current_dataset_name()
    inplace = in_place_dates()
    rd = d["rater_disclosure"]
    return {
        "specification": {"title": spec_title, "short": "OWHS specification", "version": "0.2-draft", "date": spec_date, "url": BASE + "spec/",
                          "licence": "CC BY 4.0 for the specification text; Apache 2.0 for the schemas, code lists, examples and tools",
                          "licence_ids": ["CC-BY-4.0", "Apache-2.0"],
                          "status": "Draft, early open specification, published for review. Not a final or certified standard.",
                          "date_meaning": "the date of the latest entry on the specification tab of the changelog"},
        "registry": {"title": d["dataset"], "short": "OWHS instrument evidence base", "version": d["version"], "date": d["generated"], "url": BASE + "instrument-registry/",
                     "file": BASE + "instrument-registry/" + reg_name, "schema_version": d["schema_version"], "rubric": d["rubric"]["version"],
                     "licence": "CC BY 4.0 for the text; Apache 2.0 for the dataset structure", "licence_ids": ["CC-BY-4.0", "Apache-2.0"],
                     "in_place": inplace, "date_meaning": "the date the dataset version was generated",
                     "caveat": (f"Every grade was assigned by one rater employed by the steward ({rd['raters_total']} rater, {rd['independent_raters']} independent raters), "
                                "and grades and statuses are frozen until two named psychometric raters who are not employees of the steward have joined. "
                                "Grades are not a recommendation and are not comparable across instruments.")},
        "question_bank": {"title": q["name"], "short": "OWHS question bank", "version": q["version"], "date": q["updated"], "url": BASE + "question-bank/",
                          "file": BASE + "question-bank/question-bank.json", "counts": q["counts"],
                          "licence": "CC BY 4.0 for the guidance text; Apache 2.0 for the dataset structure; the wording of each item stays with its primary source under the licence recorded per item",
                          "licence_ids": ["CC-BY-4.0", "Apache-2.0"], "date_meaning": "the date the question bank was last updated, as it records itself"},
    }


def self_test():
    d = load_dataset()
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}".strip())
    t("every licence class in the dataset has wording", set(d["licence_classes"]) == set(LICENCE_ANSWER))
    t("every record has a short name", all(short_name(r) for r in d["records"]))
    t("no derived short name is a parenthetical fragment", all("(" not in short_name(r) for r in d["records"] if r["instrument_id"] not in SHORT_NAMES))
    t("every listed short name belongs to a record", set(SHORT_NAMES) <= {r["instrument_id"] for r in d["records"]})
    t("every licence class has title wording or an explicit neutral form", set(d["licence_classes"]) == set(LICENCE_TITLE))
    t("every record's licence class has wording", all(r["identity"].get("licence_class") in LICENCE_ANSWER for r in d["records"]))
    t("a prose licence date is never printed as a date", licence_clause({"licence_class": "unverified", "licence_verified_date": "not verified this session"})[1] == "")
    t("a date followed by prose is flagged, not asserted as verified", "basis is stated" in licence_clause({"licence_class": "free-non-commercial", "licence_verified_date": "2026-07-12 (secondary)"})[1])
    t("a strict date is verified", licence_clause({"licence_class": "open", "licence_verified_date": "2026-07-12"})[1] == "Verified 2026-07-12.")
    titles = [record_title(r) for r in d["records"]]
    t("record titles are unique", len(set(titles)) == len(titles))
    long_ok = [x for x in titles if len(x) > TITLE_LIMIT and not x.endswith(": employer licence and evidence | OWHS")]
    t("a title over the length limit is only one whose own name leaves no room, and it then uses the shortest form", not long_ok, long_ok)
    ex = {r["instrument_id"]: record_title(r) for r in d["records"]}
    t("a free instrument's title says so", ex["phq-9"] == "PHQ-9: free for employers to use. Licence and evidence | OWHS", ex["phq-9"])
    t("a fee-bearing instrument's title says a paid licence is needed", ex["wemwbs"] == "WEMWBS: paid licence needed for employer use. Licence and evidence | OWHS", ex["wemwbs"])
    t("a non-commercial instrument's title says permission is needed", ex["uwes-9"] == "UWES-9: permission needed for employer use. Licence and evidence | OWHS", ex["uwes-9"])
    t("a title never asks a question", not any("?" in x for x in titles))
    t("an unverified class gets the neutral form", record_title({"instrument_id": "x", "display_name": "Foo", "identity": {"licence_class": "unverified"}}) == "Foo: licence for employer use and evidence | OWHS")
    t("titles end in the site name", all(x.endswith(" | OWHS") for x in titles))
    t("latest dataset date is an ISO date", ISO.match(latest_dataset_date(d)) is not None)
    p = people()
    t("the creator and steward are named as GOVERNANCE.md and README.md name them", (p["creator"], p["steward"], p["steward_legal"]) == ("Zak Fenton", "Alltoogether", "All Toogether Ltd"), p)
    gov = (ROOT / "site" / "governance.html").read_text(encoding="utf-8")
    m = re.search(r'<h2 id="maintainers">Who maintains this</h2>\s*<p>(.*?)</p>', gov, re.S)
    t("the governance page's maintainers passage names the creator and steward as GOVERNANCE.md does", bool(m) and p["creator"] in m.group(1) and p["steward_legal"] in m.group(1) and f"trading as {p['steward']}" in m.group(1))
    c = cite_works()
    t("every citable work has a version, an ISO date, an address and a licence", all(w["version"] and ISO.match(w["date"]) and w["url"].startswith(BASE) and w["licence"] for w in c.values()), c)
    t("the registry citation carries the single-rater caveat from the dataset", "one rater" in c["registry"]["caveat"] and "frozen" in c["registry"]["caveat"])
    if fails:
        print("self-test FAILED: " + "; ".join(fails)); sys.exit(1)
    print(f"self-test ok: {len(d['records'])} records worded, {len(LICENCE_ANSWER)} licence classes covered")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(__doc__)
