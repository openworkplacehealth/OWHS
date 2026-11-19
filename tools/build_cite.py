#!/usr/bin/env python3
"""How to cite OWHS: site/cite.html, CITATION.cff and .zenodo.json, all generated from tools/site_data.cite_works() so they cannot drift from each
other or from the structured data tools/jsonld.py puts on the cite page.

    python tools/build_cite.py            write the three files
    python tools/build_cite.py --check    fail if any differs from a fresh build (the page is stamped like every page)
    python tools/build_cite.py --self-test

Versions are identified by version number and address. No DOI has been issued, and nothing here says one has: .zenodo.json exists so that a future
tagged GitHub release can be archived by Zenodo, which is what would mint one. The dates are the ones each source records for itself (the specification
and the question bank carry theirs; the registry dataset carries the date it was generated, and the page says plainly that citations were appended to it
in place afterwards).
"""
import json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import site_data as sd
import site_pages as sp

CFF = ROOT / "CITATION.cff"
ZENODO = ROOT / ".zenodo.json"
ORG = "Open Workplace Health Standard"
LICENCE_FILE = {"CC-BY-4.0": "CC BY 4.0", "Apache-2.0": "Apache 2.0"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def long_date(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def abstract():
    t = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    return re.search(r'<meta name="description" content="([^"]*)"', t).group(1)


def plain(w):
    return f"{ORG} ({w['date'][:4]}). {w['title']}. Version {w['version']}, {long_date(w['date'])}. {w['url']}"


def bibtex(key, w, note):
    return (f"@misc{{{key},\n  author = {{{{{ORG}}}}},\n  title = {{{{{w['title']}}}}},\n  year = {{{w['date'][:4]}}},\n  version = {{{w['version']}}},\n"
            f"  url = {{{w['url']}}},\n  note = {{{note}}}\n}}")


def notes(c):
    return {"specification": "Draft specification. Text CC BY 4.0; schemas and tools Apache 2.0",
            "registry": "Dataset. Text CC BY 4.0; dataset structure Apache 2.0. Grades are single-rater",
            "question_bank": "Dataset. Guidance text CC BY 4.0; structure Apache 2.0; item wording stays with each source"}


def cite_page():
    c = sd.cite_works()
    s, r, q = c["specification"], c["registry"], c["question_bank"]
    n = notes(c)
    inplace = ""
    if r["in_place"]:
        dates = ", ".join(long_date(d) for d in r["in_place"])
        inplace = (f"<p><strong>This version was changed in place.</strong> The changelog records changes made inside version {r['version']} without a new version number "
                   f"(latest {long_date(r['in_place'][-1])}: <a href=\"changelog.html\">see the registry tab</a>). A version number alone therefore does not fix the content: "
                   f"add the date you accessed it, and for exact reproduction quote the commit of the <a href=\"{sd.GITHUB}\">repository</a> you used. Dates of in-place changes: {dates}.</p>")
    def block(h, w, extra, key):
        return f"""<h2 id="{key}">{sp.esc(h)}</h2>
<dl class="facts">
  <dt>Version</dt><dd>{sp.esc(w['version'])}</dd>
  <dt>Date</dt><dd>{long_date(w['date'])} ({sp.esc(w['date_meaning'])})</dd>
  <dt>Address</dt><dd><a href="{w['url']}">{w['url']}</a></dd>
  <dt>Licence</dt><dd>{sp.esc(w['licence'])}</dd>
</dl>
<div class="cite"><p>{sp.esc(plain(w))}</p></div>
{extra}<details><summary>BibTeX</summary><pre class="bib">{sp.esc(bibtex(key, w, n[key if key != 'specification' else 'specification']))}</pre></details>"""
    spec_extra = (f"<p>{sp.esc(s['status'])} The archived v0.1 draft stays at <a href=\"spec/OWHS-v0.1-draft.html\">its own address</a> and is cited by that address and its own version.</p>")
    reg_extra = (f"<p><strong>Caveat that the registry itself publishes.</strong> {sp.esc(r['caveat'])} The dataset is schema {sp.esc(r['schema_version'])}, graded under rubric {sp.esc(r['rubric'])}. "
                 f"The file is at <a href=\"{r['file']}\">{r['file']}</a>.</p>{inplace}")
    qb_extra = (f"<p>The bank holds {q['counts']['items_catalogued']} catalogued items in {q['counts']['groups']} topic groups. Wording is reproduced only for the {q['counts']['items_verified_rendered']} items "
                f"verified verbatim and licensed for redistribution; cite an item's own source for its wording, not this bank. The file is at <a href=\"{q['file']}\">{q['file']}</a>.</p>")
    return f"""<span class="status-chip">cite · generated from the repository</span>
<h1>How to cite OWHS</h1>
<p class="lede">Each part of OWHS is cited by its version number and its address. <strong>There is no DOI yet.</strong> No archived release has been made, so none has been issued, and this page will say so when that changes. The repository also carries a <a href="{sd.GITHUB}/blob/main/CITATION.cff">CITATION.cff</a> file, which GitHub reads to offer a citation for the repository as a whole.</p>
<p>Add the date you accessed the page to any reference. The three works below are different things with their own versions: the specification, the registry dataset and the question bank.</p>
{block("The specification", s, spec_extra, "specification")}
{block("The instrument registry dataset", r, reg_extra, "registry")}
{block("The question bank", q, qb_extra, "question_bank")}
<h2 id="what">What a citation does and does not say</h2>
<p>Citing a version records which document or dataset you used. It does not mean the thing is endorsed, certified or final. The specification is a draft. The registry's grades are single-rater and are not a recommendation. Where you rely on a specific grade, licence class or item, cite the page for that record and the date you read it.</p>
<p>To report something wrong in what you cite, see the <a href="instrument-registry/corrections.html">corrections process</a> or <a href="contribute.html">how to contribute</a>.</p>
"""


def cff():
    c = sd.cite_works()
    s, r, q = c["specification"], c["registry"], c["question_bank"]
    p = sd.people()
    j = json.dumps
    def ref(w):
        return (f"  - type: database\n    title: {j(w['title'])}\n    version: {j(w['version'])}\n    date-released: {j(w['date'])}\n    url: {j(w['url'])}\n"
                f"    authors:\n      - name: {j(ORG)}\n")
    return (f"cff-version: 1.2.0\nmessage: {j('If you use OWHS, please cite it with the metadata in this file. Versions are identified by version number and address; no DOI has been issued.')}\n"
            f"title: {j(s['title'])}\ntype: dataset\nabstract: {j(abstract())}\nauthors:\n  - family-names: {j(p['family'])}\n    given-names: {j(p['given'])}\n  - name: {j(p['steward_legal'])}\n"
            f"version: {j(s['version'])}\ndate-released: {j(s['date'])}\n") + (
            f"license:\n" + "".join(f"  - {i}\n" for i in s["licence_ids"]) +
            f"repository-code: {j(sd.GITHUB)}\nurl: {j(sd.BASE)}\nkeywords:\n  - workplace health\n  - data standard\n  - open data\n  - psychometric instruments\n  - survey questions\n  - JSON Schema\n"
            f"references:\n{ref(r)}{ref(q)}")


def zenodo():
    c = sd.cite_works()
    s, r, q = c["specification"], c["registry"], c["question_bank"]
    p = sd.people()
    desc = (f"<p>{sp.esc(abstract())}</p><p>This record is a draft release: the specification is {sp.esc(s['version'])}, the instrument registry dataset is version {sp.esc(r['version'])} "
            f"and the question bank is version {sp.esc(q['version'])}. The specification text, registry text and guidance text are CC BY 4.0; the schemas, code lists, examples, dataset structure and tools are "
            f"Apache 2.0. Grades in the registry are single-rater. The record is a snapshot of the repository at the release; the live site is {sd.BASE}.</p>")
    doc = {"title": s["title"], "description": desc, "upload_type": "dataset", "version": s["version"], "access_right": "open", "license": "cc-by-4.0", "language": "eng",
           "creators": [{"name": f"{p['family']}, {p['given']}"}, {"name": p["steward_legal"]}],
           "keywords": ["workplace health", "data standard", "open data", "psychometric instruments", "survey questions", "JSON Schema"],
           "related_identifiers": [{"identifier": sd.GITHUB, "relation": "isSupplementTo", "scheme": "url"}, {"identifier": sd.BASE, "relation": "isDocumentedBy", "scheme": "url"}]}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def build():
    return sp.shell(f"How to cite OWHS | OWHS", "How to cite the OWHS specification, the instrument registry dataset and the question bank: version, date, licence and address, with the registry's single-rater caveat. No DOI has been issued.", cite_page())


def write():
    (sp.SITE_ROOT / "cite.html").write_text(build(), encoding="utf-8")
    if sp.SITE_ROOT == ROOT / "site":
        CFF.write_text(cff(), encoding="utf-8")
        ZENODO.write_text(zenodo(), encoding="utf-8")
    print("wrote cite.html, CITATION.cff, .zenodo.json")


def check():
    sp.check_built(Path(__file__).resolve(), ["cite.html"], "the cite page")
    bad = [f.name for f, text in ((CFF, cff()), (ZENODO, zenodo())) if not f.exists() or f.read_text(encoding="utf-8") != text]
    if bad:
        sys.exit("run tools/build_cite.py: out of date: " + ", ".join(bad))
    print("up to date: CITATION.cff and .zenodo.json match a fresh build from the same sources as the cite page")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}".strip())
    c = sd.cite_works()
    page, f, z = cite_page(), cff(), json.loads(zenodo())
    for k, w in c.items():
        t(f"the cite page states the {k} version, date and address", w["version"] in page and long_date(w["date"]) in page and w["url"] in page)
    t("the specification's date is the specification tab's latest changelog date", c["specification"]["date"] == sd.latest_changelog_date("specification"))
    t("the page says plainly that there is no DOI and claims none", "no DOI yet" in page and not re.search(r"10\.\d{4,}/zenodo", page + f + json.dumps(z)) and "doi:" not in f.lower())
    t("the registry citation carries the single-rater caveat and the in-place note", "one rater" in page and "changed in place" in page)
    t("CITATION.cff names the creator and the steward as the repository does", 'family-names: "Fenton"' in f and 'given-names: "Zak"' in f and 'name: "All Toogether Ltd"' in f)
    t("CITATION.cff and .zenodo.json carry the same title, version and licences", z["title"] in f and z["version"] == c["specification"]["version"] and 'version: "0.2-draft"' in f and "CC-BY-4.0" in f and "Apache-2.0" in f)
    t("the Zenodo file names the same creators", [x["name"] for x in z["creators"]] == ["Fenton, Zak", "All Toogether Ltd"])
    t("the Zenodo file carries no publication date or DOI of its own", "publication_date" not in z and "doi" not in z)
    t("repository-code and url are the repository and the site", f'repository-code: "{sd.GITHUB}"' in f and f'url: "{sd.BASE}"' in f)
    t("no em or en dash anywhere", not any(ch in page + f + json.dumps(z, ensure_ascii=False) for ch in "—–"))
    t("each BibTeX entry has balanced braces", all(bibtex(k, w, notes(c)[k]).count("{") == bibtex(k, w, notes(c)[k]).count("}") for k, w in c.items()))
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("self-test ok: 10 cases (versions, dates and addresses on the page, no DOI claimed, caveat, creators, cff and Zenodo agree)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        write()
