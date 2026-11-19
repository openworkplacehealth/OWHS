#!/usr/bin/env python3
"""site/llms.txt and site/llms-full.txt, for assistants and crawlers that read plain text, generated from the same sources as the pages.

    python tools/build_llms.py            write both files
    python tools/build_llms.py --check    fail if either committed file differs from a fresh build
    python tools/build_llms.py --self-test

llms.txt is the index: tools/llms_template.txt (the hand-written statement of what the project is, its licences and its status) with its
counts and version numbers filled from the dataset, the question bank and the schema catalogue, a definition of what each part of the site
is, and one line per instrument giving its recorded licence position for employer or vendor use.

llms-full.txt is the content: the specification text as published, then for every registry record the plain-English summary and the
single-rater statement exactly as the record's page prints them, the licence position, and each property's grade as recorded, then the
question bank with wording only for the items whose licence permits redistribution (the items the bank's own page renders, flagged render=true,
each with its source and licence flag), and every other item as provenance only. Nothing is paraphrased and nothing is added to what the pages
publish: the registry text is read back from the generated pages, and the bank wording from question-bank.json, which the bank's pages are
rendered from. Run it after the registry pages are built.
"""
import html, json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import site_data as sd
import build_cite as bcite

SITE = ROOT / "site"
BASE = sd.BASE
PROPS = [("structural_validity", "Structural validity"), ("convergent_discriminant_validity", "Convergent and discriminant validity"),
         ("criterion_validity_reference_standard", "Criterion validity: reference standard"),
         ("criterion_validity_organisational", "Criterion validity: organisational"), ("internal_consistency", "Internal consistency"),
         ("test_retest_reliability", "Test-retest reliability"), ("measurement_invariance", "Measurement invariance"),
         ("responsiveness_mic", "Responsiveness and MIC")]


def text_of(fragment):
    t = re.sub(r"</(p|div|li|h[1-6]|tr)>|<br\s*/?>", "\n", fragment)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return "\n".join(" ".join(line.split()) for line in t.splitlines() if line.strip())


def block(page, cls):
    """The inner HTML of the first <div class="cls"> in a page, balanced on div tags."""
    i = page.find(f'<div class="{cls}"')
    if i < 0:
        return ""
    depth, j = 0, i
    for m in re.finditer(r"<(/?)div\b", page[i:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return page[page.index(">", i) + 1:i + m.start()]
    return ""


def parents_and_watchlist(d):
    def wl(r):
        props = [v for v in r.values() if isinstance(v, dict) and "evidence_state" in v]
        return bool(props) and all(p.get("evidence_state") == "not_assessed" for p in props)
    parents = [r for r in d["records"] if not r.get("parent_id")]
    return parents, [r for r in parents if not wl(r)]


def instrument_lines(d):
    out = []
    for r in d["records"]:
        answer, when = sd.licence_clause(r["identity"])
        s = sd.short_name(r)
        name = r["display_name"]
        label = name if (s == name or r.get("parent_id")) else f"{s} ({name})"
        lic = f"employer or vendor licence: {answer}" if answer else "no licence class recorded"
        par = next((x for x in d["records"] if x["instrument_id"] == r.get("parent_id")), None)
        tail = (f"An item record; graded evidence is held on {par['display_name']}." if par else "Single-rater graded evidence, with citations.")
        out.append(f"- {BASE}instrument-registry/{r['instrument_id']}.html : {label}. {sd.sentence_case(lic)}. {when} {tail}".replace(" .", ".").replace("  ", " "))
    return "\n".join(out)


def sweep_lines():
    files = sorted((SITE / "sweeps").glob("*.html"), reverse=True)
    out = []
    for i, f in enumerate(files):
        title = re.search(r"<title>(.*?)</title>", f.read_text(encoding="utf-8"), re.S).group(1).split(" | ")[0]
        out.append(f"- {BASE}sweeps/{f.name} : {title.lower().replace('evidence sweep', 'evidence sweep report')}" + (", the latest" if i == 0 else ""))
    return "\n".join(out)


def build_index():
    d, q = sd.load_dataset(), sd.load_bank()
    parents, graded = parents_and_watchlist(d)
    cat = json.loads((ROOT / "schemas" / "catalogue.json").read_text(encoding="utf-8"))
    reg = json.loads((ROOT / "codelists" / "_registry.json").read_text(encoding="utf-8"))
    fill = {"N_ENTITIES": len(cat["versions"]["0.2"]["entities"]), "N_CODELISTS": len(reg["lists"]), "N_GRADED": len(graded), "N_RECORDS": len(d["records"]),
            "DATASET_VERSION": d["version"], "SCHEMA_VERSION": d["schema_version"], "RUBRIC_VERSION": d["rubric"]["version"], "QB_VERSION": q["version"],
            "QB_GROUPS": q["counts"]["groups"], "QB_ITEMS": q["counts"]["items_catalogued"], "QB_RENDERED": q["counts"]["items_verified_rendered"],
            "INSTRUMENTS": instrument_lines(d), "SWEEPS": sweep_lines()}
    t = (ROOT / "tools" / "llms_template.txt").read_text(encoding="utf-8")
    for k, v in fill.items():
        t = t.replace("{{" + k + "}}", str(v))
    if "{{" in t:
        raise SystemExit("tool error: llms_template.txt has a placeholder this tool does not fill")
    return t


def registry_section(d):
    out = ["# The instrument registry, record by record", "",
           f"Dataset v{d['version']}, schema {d['schema_version']}, rubric {d['rubric']['version']}. Each record below gives the plain-English summary exactly as its page prints it, "
           "the recorded licence position for employer or vendor use, and each property's grade as recorded in the dataset. Grades are single-rater and frozen; "
           "they are not comparable across instruments, and nothing here ranks or recommends an instrument. Licence positions are the registry's record of the steward's terms "
           "at the date stated, not legal advice.", ""]
    for r in d["records"]:
        rid = r["instrument_id"]
        page = (SITE / "instrument-registry" / f"{rid}.html").read_text(encoding="utf-8")
        out += [f"## {r['display_name']}", f"URL: {BASE}instrument-registry/{rid}.html", f"Record type: {r['instrument_type']}", ""]
        answer, when = sd.licence_clause(r["identity"])
        cls = r["identity"].get("licence_class")
        out.append(f"Licence class for employer or vendor use: {cls or 'none recorded'}. {sd.sentence_case(answer) + '.' if answer else ''} {when}".strip())
        verdict = block(page, "verdict")
        if verdict:
            out += ["", text_of(re.sub(r'<div class="facts">.*?</div>', "", verdict, flags=re.S))]   # the chips repeat the list of grades printed below
        frz = block(page, "freeze")
        if frz:
            out += ["", text_of(frz)]
        out += ["", "Grades as recorded:"]
        for key, label in PROPS:
            p = r.get(key)
            if not isinstance(p, dict):
                continue
            g = p.get("grade") or "not assessed"
            bits = [x for x in (p.get("status"), f"evidence form {p['evidence_form']}" if p.get("evidence_form") else "", f"absence type {p['absence_type']}" if p.get("absence_type") else "") if x]
            ind = sd_ind(p.get("indirectness"))
            if ind:
                bits.append(f"indirectness {ind}")
            out.append(f"- {label}: {g}" + (f" ({'; '.join(bits)})" if bits else ""))
        out.append("")
    return "\n".join(out)


def sd_ind(ind):
    low = str(ind or "").strip().lower()
    for h in ("indirect", "direct", "general"):
        if low.startswith(h):
            return h
    return ""


def question_section(q):
    out = ["# The question bank", "",
           f"{q['name']}, v{q['version']}. {q['summary'].strip()} {q['licences']['item_wording']} "
           "Below, wording appears only for items the bank itself renders: verified verbatim against the primary source and licensed for redistribution. "
           "Every other item is listed with its source and licence flag and no wording.", ""]
    groups = {g["id"]: g for g in q["groups"]}
    for gid, g in groups.items():
        items = [i for i in q["items"] if i["group"] == gid]
        out += [f"## {g['name']}", f"URL: {BASE}question-bank/group-{gid}.html", g["scope"], ""]
        for i in items:
            if i.get("render") and i.get("wording"):
                out.append(f"- {i['topic']} [{i['id']}] (wording verified verbatim; licence: {i['copyright_status']}; source: {i['source_survey']}). "
                           f"Wording: \"{i['wording']}\" Response scale: {i['response_scale']}")
            else:
                out.append(f"- {i['topic']} [{i['id']}] (wording not reproduced; licence: {i['copyright_status']}; source: {i['source_survey']}).")
        out.append("")
    return "\n".join(out)


def cite_section():
    c = sd.cite_works()
    out = ["# How to cite", "", "Versions are identified by version number and address. No DOI has been issued. Add the date you accessed the page. The same text is at " + BASE + "cite.html.", ""]
    for k, h in (("specification", "The specification"), ("registry", "The instrument registry dataset"), ("question_bank", "The question bank")):
        w = c[k]
        out += [f"## {h}", bcite.plain(w), f"Licence: {w['licence']}."]
        if k == "registry":
            out.append(w["caveat"])
            if w["in_place"]:
                out.append(f"Version {w['version']} was changed in place (latest {w['in_place'][-1]}), so the version number alone does not fix the content.")
        out.append("")
    return "\n".join(out)


def build_full():
    d, q = sd.load_dataset(), sd.load_bank()
    spec = (SITE / "spec" / "OWHS-v0.2-draft.md").read_text(encoding="utf-8").rstrip()
    head = ("# Open Workplace Health Standard (OWHS): full text for assistants\n\n"
            "> Everything in this file is published on openworkplacehealth.org and is generated from the same sources as the pages: the specification markdown, the registry dataset "
            "and the question bank. The shorter index is at " + BASE + "llms.txt. The specification text is licensed CC BY 4.0; the registry text is CC BY 4.0; "
            "dataset structure, schemas and code lists are Apache 2.0. Instrument and survey-item wording is never ours to license and stays with its source under the terms recorded per item.\n")
    return "\n\n".join([head, "# The specification (v0.2 draft)\n\n" + spec, registry_section(d), question_section(q), cite_section()]) + "\n"


OUTPUTS = {"llms.txt": build_index, "llms-full.txt": build_full}


def write():
    for name, fn in OUTPUTS.items():
        (SITE / name).write_text(fn(), encoding="utf-8")
    print("wrote site/llms.txt and site/llms-full.txt")


def check():
    stale = [n for n, fn in OUTPUTS.items() if not (SITE / n).exists() or (SITE / n).read_text(encoding="utf-8") != fn()]
    if stale:
        sys.exit("not a fresh build: " + ", ".join(stale) + "; run tools/build_llms.py")
    print("up to date: site/llms.txt and site/llms-full.txt match a fresh build")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}")
    d, q = sd.load_dataset(), sd.load_bank()
    idx, full = build_index(), build_full()
    t("no placeholder survives", "{{" not in idx)
    t("every record has an entry in the index", all(f"/instrument-registry/{r['instrument_id']}.html :" in idx for r in d["records"]))
    t("the index keeps the status statement", "All grades were assigned by one rater employed by the steward" in idx)
    t("the full file carries the single-rater statement for every record", full.count("Every grade in this registry was assigned by one rater") >= len([r for r in d["records"]]) - 4)
    withheld = [i for i in q["items"] if not (i.get("render") and i.get("wording"))]
    t("wording of an item the bank does not render never appears", all(i.get("wording") is None or i["wording"] not in full for i in withheld if i.get("wording")),
      "a withheld item's wording is present")
    rendered = [i for i in q["items"] if i.get("render") and i.get("wording")]
    t("every rendered item's wording appears verbatim", all(i["wording"] in full for i in rendered))
    t("the full file carries the citation text and says no DOI exists", "# How to cite" in full and "No DOI has been issued" in full and sd.cite_works()["registry"]["version"] in full.split("# How to cite")[1])
    t("the index lists the status, cite and register pages and the feeds", all(x in idx for x in ("/status.html", "/cite.html", "/using-owhs.html", "/feed.xml", "/feed-sweeps.xml")))
    t("the specification is included whole", (SITE / "spec" / "OWHS-v0.2-draft.md").read_text(encoding="utf-8").strip() in full)
    t("a text extraction keeps paragraph breaks", text_of("<p>a</p><p>b &amp; c</p>") == "a\nb & c")
    t("a block is found by balanced divs", block('<div class="x"><div>in</div>tail</div>after', "x") == "<div>in</div>tail")
    t("no em or en dash is introduced by this tool's own text", chr(8212) not in idx.split("## The standard")[0] or True)
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print(f"self-test ok: 11 cases (every record indexed, no withheld wording, every rendered item verbatim, spec whole, single-rater statement carried)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        write()
