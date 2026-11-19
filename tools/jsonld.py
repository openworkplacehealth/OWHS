#!/usr/bin/env python3
"""Structured data (schema.org JSON-LD) for every public page, built from repository data only.

tools/stamp_canonical.py calls blocks_for(rel, text, site) for each page and places the result in one managed block before </head>,
so the generators never write it and a rebuild never loses it. Every value is read from the committed dataset, the question bank, the
specification and registry markdown headers, the changelog entries, the schema catalogue, the code lists or the page's own title,
description and heading. Dates are the dates the repository records; nothing is "today". A page that records no date carries none.

    python tools/jsonld.py --check            every page under site/ carries well-formed JSON-LD that matches a fresh build
    python tools/jsonld.py --self-test        the builder's own contract

Types by page kind:
  home                          WebSite, Organization
  registry index, downloads     Dataset (the evidence base), BreadcrumbList
  instrument record page        WebPage about the instrument, part of the Dataset, with the cited studies; BreadcrumbList
  registry rubric, admission    TechArticle with version and the date the document gives itself; BreadcrumbList
  other registry pages          WebPage; BreadcrumbList
  question bank index, downloads Dataset (the question bank), BreadcrumbList
  question bank topic pages     WebPage about the topic group, part of the Dataset; BreadcrumbList
  specification v0.2, v0.1      TechArticle with version and status; BreadcrumbList
  /schemas/                     CollectionPage listing each schema as a DigitalDocument; BreadcrumbList
  /codelists/                   one DefinedTermSet per code list with its DefinedTerms; BreadcrumbList
  sweep reports                 Report about the Dataset, dated from the report's own filing date; BreadcrumbList
  cite page                     WebPage listing the specification (TechArticle), the registry Dataset and the question bank Dataset with their versions and dates; BreadcrumbList
  changelog                     WebPage dated from the latest changelog entry; BreadcrumbList
  every other page              WebPage; BreadcrumbList
"""
import html, json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import site_data as sd

BASE, GITHUB = sd.BASE, sd.GITHUB
CC_BY = "https://creativecommons.org/licenses/by/4.0/"
APACHE = "https://www.apache.org/licenses/LICENSE-2.0"
LICENCE_URL = {"CC BY 4.0": CC_BY, "CC-BY 4.0": CC_BY, "Apache 2.0": APACHE, "Apache-2.0": APACHE}
PROJECT_ID, SITE_ID = BASE + "#project", BASE + "#website"
REG_DATASET_ID, QB_DATASET_ID = BASE + "instrument-registry/#dataset", BASE + "question-bank/#dataset"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                                       "November", "December"], 1)}
SECTIONS = {"instrument-registry": ("Instrument registry", "instrument-registry/index.html"),
            "question-bank": ("Question bank", "question-bank/index.html"),
            "spec": ("Specification", "spec/index.html")}


def licence_urls(*names):
    out = []
    for n in names:
        if n not in LICENCE_URL:
            raise SystemExit(f"tool error: no licence URL known for {n!r}")
        if LICENCE_URL[n] not in out:
            out.append(LICENCE_URL[n])
    return out


def page_facts(text):
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', text)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    clean = lambda s: " ".join(html.unescape(re.sub(r"<[^>]+>", "", s)).split()) if s else ""
    return clean(title.group(1) if title else ""), clean(desc.group(1) if desc else ""), clean(h1.group(1) if h1 else "")


def page_name(title):
    for sep in (" | ", " · "):
        if sep in title:
            return title.split(sep)[0].strip()
    return title.strip()


def md_date(path):
    """The date a markdown document gives itself in its first lines, e.g. '3 September 2026', as ISO; None if it gives none."""
    for line in path.read_text(encoding="utf-8").splitlines()[:6]:
        m = re.search(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})\b", line)
        if m:
            return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def on_watchlist(r):
    props = [v for v in r.values() if isinstance(v, dict) and "evidence_state" in v]
    return bool(props) and all(p.get("evidence_state") == "not_assessed" for p in props)


def url_of(rel):
    return BASE + ("" if rel == "index.html" else rel[:-len("index.html")] if rel.endswith("/index.html") else rel)


def breadcrumb(rel, name, parents=()):
    """BreadcrumbList: Home, any named parents ((name, rel) pairs), then this page."""
    items = [("Home", BASE)] + [(n, url_of(r)) for n, r in parents] + [(name, url_of(rel))]
    return {"@type": "BreadcrumbList", "@id": url_of(rel) + "#breadcrumb",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": n, "item": u} for i, (n, u) in enumerate(items, 1)]}


def project_node(desc):
    return {"@type": "Organization", "@id": PROJECT_ID, "name": "Open Workplace Health Standard", "alternateName": "OWHS",
            "url": BASE, "description": desc, "sameAs": [GITHUB]}


def registry_dataset_node(d, site):
    parents = [r for r in d["records"] if not r.get("parent_id")]
    graded = [r for r in parents if not on_watchlist(r)]
    registry_date = sd.latest_changelog_date("registry")
    modified = max(x for x in (sd.latest_dataset_date(d), registry_date) if x)
    name = sd.current_dataset_name()
    dist = [{"@type": "DataDownload", "name": f"Instrument evidence base v{d['version']} (JSON, schema {d.get('schema_version')})",
             "contentUrl": f"{BASE}instrument-registry/{name}", "encodingFormat": "application/json"},
            {"@type": "DataDownload", "name": "Instrument evidence matrix with licence class and citation counts (CSV)",
             "contentUrl": BASE + "instrument-registry/instrument-evidence-matrix-full.csv", "encodingFormat": "text/csv"},
            {"@type": "DataDownload", "name": "Instrument registry matrix and records (PDF)",
             "contentUrl": BASE + "instrument-registry/instrument-registry.pdf", "encodingFormat": "application/pdf"}]
    lic = d.get("licence") or {}
    return {"@type": "Dataset", "@id": REG_DATASET_ID, "name": d["dataset"], "alternateName": "OWHS instrument registry dataset",
            "description": (f"Graded evidence on {len(graded)} instruments used to measure workplace health and wellbeing ({len(d['records'])} records), "
                            f"with licence class, provenance and citations for each. Dataset version {d['version']}, schema {d.get('schema_version')}, "
                            f"rubric {d.get('rubric', {}).get('version')}. Grades are single-rater. The registry describes instruments and never reproduces their items."),
            "url": BASE + "instrument-registry/", "version": d["version"], "dateModified": modified, "inLanguage": "en-GB",
            "license": licence_urls(lic.get("prose", "CC BY 4.0"), lic.get("structure", "Apache 2.0")), "isAccessibleForFree": True,
            "creator": {"@id": PROJECT_ID}, "publisher": {"@id": PROJECT_ID}, "distribution": dist}


def bank_dataset_node(q):
    lic = q.get("licences") or {}
    desc = (q["summary"].strip() + " " + lic.get("item_wording", "")).strip()
    cnt = q.get("counts") or {}
    dist = [{"@type": "DataDownload", "name": f"Question bank v{q['version']} (JSON, canonical)", "contentUrl": BASE + "question-bank/question-bank.json",
             "encodingFormat": "application/json"},
            {"@type": "DataDownload", "name": "Question bank (CSV)", "contentUrl": BASE + "question-bank/question-bank.csv", "encodingFormat": "text/csv"},
            {"@type": "DataDownload", "name": "Question bank (PDF)", "contentUrl": BASE + "question-bank/question-bank.pdf", "encodingFormat": "application/pdf"}]
    return {"@type": "Dataset", "@id": QB_DATASET_ID, "name": q["name"], "description": desc, "url": BASE + "question-bank/",
            "version": q["version"], "dateModified": q["updated"], "inLanguage": "en-GB",
            "license": licence_urls(lic.get("guidance_text", "CC BY 4.0"), lic.get("dataset_structure", "Apache 2.0")), "isAccessibleForFree": True,
            "creator": {"@id": PROJECT_ID}, "publisher": {"@id": PROJECT_ID}, "distribution": dist}


def codelist_nodes():
    reg = json.loads((ROOT / "codelists" / "_registry.json").read_text(encoding="utf-8"))
    out = []
    for item in reg["lists"]:
        body = json.loads((ROOT / "codelists" / item["file"]).read_text(encoding="utf-8"))
        sid = f"{BASE}codelists/#{item['name']}"
        terms = []
        for v in body["values"]:
            code = v["code"] if isinstance(v, dict) else v
            label = v.get("label", code) if isinstance(v, dict) else v
            terms.append({"@type": "DefinedTerm", "termCode": str(code), "name": str(label), "inDefinedTermSet": sid})
        out.append({"@type": "DefinedTermSet", "@id": sid, "name": item["name"], "description": item.get("anchor", ""), "version": item["version"],
                    "url": f"{BASE}spec/codelists/{item['file']}", "license": APACHE, "inLanguage": "en-GB", "hasDefinedTerm": terms})
    return out


def schema_nodes():
    cat = json.loads((ROOT / "schemas" / "catalogue.json").read_text(encoding="utf-8"))
    out = []
    for ver, block in cat["versions"].items():
        entries = list(block["entities"].items()) + list((block.get("bundle_envelopes") or {}).items())
        for name, e in entries:
            sch = json.loads((ROOT / e["file"]).read_text(encoding="utf-8"))
            out.append({"@type": "DigitalDocument", "name": sch.get("title", name), "description": sch.get("description", ""),
                        "url": e["$id"], "version": ver, "encodingFormat": "application/schema+json", "license": APACHE,
                        "creativeWorkStatus": "Archived" if block.get("status") == "archived" else "Current"})
    return out


def resolve_refs(graph, site):
    """Replace each bare {"@id": X} whose node is not defined in the graph by a short stub naming it, so a page's structured data
    stands on its own and never points at a node that only another page defines."""
    defined = {n["@id"] for n in graph if "@id" in n and len(n) > 1}
    stubs = {PROJECT_ID: {"@type": "Organization", "@id": PROJECT_ID, "name": "Open Workplace Health Standard", "url": BASE},
             SITE_ID: {"@type": "WebSite", "@id": SITE_ID, "name": "Open Workplace Health Standard", "url": BASE}}
    if any("#dataset" in json.dumps(n) for n in graph):
        d = sd.load_dataset()
        stubs[REG_DATASET_ID] = {"@type": "Dataset", "@id": REG_DATASET_ID, "name": d["dataset"], "url": BASE + "instrument-registry/", "version": d["version"]}
        try:
            q = sd.load_bank(site)
            stubs[QB_DATASET_ID] = {"@type": "Dataset", "@id": QB_DATASET_ID, "name": q["name"], "url": BASE + "question-bank/", "version": q["version"]}
        except OSError:
            pass
    def walk(o, top=False):
        if isinstance(o, dict):
            if set(o) == {"@id"} and o["@id"] not in defined and o["@id"] in stubs:
                return dict(stubs[o["@id"]])
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o
    return [walk(n) for n in graph]


def blocks_for(rel, text, site):
    """The JSON-LD nodes for the page at site-relative path rel, or None for a page that carries none (the 404 page)."""
    site = Path(site)
    title, desc, h1 = page_facts(text)
    name = page_name(title) or h1
    url = url_of(rel)
    d = sd.load_dataset()
    base_page = {"@type": "WebPage", "@id": url, "url": url, "name": name, "description": desc, "inLanguage": "en-GB",
                 "isPartOf": {"@id": SITE_ID}}
    d_ids = {r["instrument_id"]: r for r in d["records"]}
    sec = rel.split("/")[0] if "/" in rel else ""

    if rel == "index.html":
        return [{"@type": "WebSite", "@id": SITE_ID, "name": "Open Workplace Health Standard", "alternateName": "OWHS", "url": BASE,
                 "inLanguage": "en-GB", "description": desc, "license": licence_urls("CC BY 4.0", "Apache 2.0"),
                 "publisher": {"@id": PROJECT_ID}, "sameAs": [GITHUB]},
                project_node(desc)]

    parents = ()
    node = dict(base_page)
    extra = []
    if sec == "instrument-registry":
        parents = (("Instrument registry", "instrument-registry/index.html"),) if rel != "instrument-registry/index.html" else ()
        stem = rel[len("instrument-registry/"):-len(".html")]
        if rel in ("instrument-registry/index.html", "instrument-registry/downloads.html"):
            node = None
            extra = [registry_dataset_node(d, site)]
            wp = dict(base_page)
            wp["about"] = {"@id": REG_DATASET_ID}
            if rel.endswith("downloads.html"):
                wp["mainEntity"] = {"@id": REG_DATASET_ID}
            node = wp
        elif stem in d_ids:
            rec = d_ids[stem]
            sn = sd.short_name(rec)
            parent = d_ids.get(rec.get("parent_id"))
            parents = parents + ((sd.short_name(parent), f"instrument-registry/{parent['instrument_id']}.html"),) if parent else parents
            modified = rec.get("last_reviewed") or d.get("generated")
            about = {"@type": "Thing", "name": rec["display_name"], "identifier": rec["instrument_id"]}
            if sn != rec["display_name"]:
                about["alternateName"] = sn
            node.update({"@type": "WebPage", "about": about, "isPartOf": {"@id": REG_DATASET_ID}, "dateModified": modified,
                         "license": CC_BY, "creator": {"@id": PROJECT_ID}})
            cites = []
            for c in rec.get("citations") or []:
                link = c.get("doi") or c.get("url") or ""
                if link and not str(link).startswith("http"):
                    link = "https://doi.org/" + str(link)
                cn = {"@type": "ScholarlyArticle", "name": c.get("title", "")}
                if c.get("year"):
                    cn["datePublished"] = str(c["year"])
                if link:
                    cn["url"] = link
                cites.append(cn)
            if cites:
                node["citation"] = cites
            name = sn
        elif stem in ("rubric", "admission"):
            md = ROOT / "registry" / (f"RUBRIC-v{d['rubric']['version']}.md" if stem == "rubric" else sd_admission())
            ver = re.search(r"v(\d+\.\d+)\.md$", md.name).group(1)
            node.update({"@type": "TechArticle", "headline": h1 or name, "version": ver, "dateModified": md_date(md), "license": CC_BY,
                         "creator": {"@id": PROJECT_ID}, "isPartOf": {"@id": REG_DATASET_ID}})
            if not node["dateModified"]:
                del node["dateModified"]
        else:
            node["isPartOf"] = {"@id": REG_DATASET_ID}
    elif sec == "question-bank":
        q = sd.load_bank(site)
        parents = (("Question bank", "question-bank/index.html"),) if rel != "question-bank/index.html" else ()
        stem = rel[len("question-bank/"):-len(".html")]
        if rel in ("question-bank/index.html", "question-bank/downloads.html"):
            extra = [bank_dataset_node(q)]
            node["about"] = {"@id": QB_DATASET_ID}
            if rel.endswith("downloads.html"):
                node["mainEntity"] = {"@id": QB_DATASET_ID}
        else:
            node["isPartOf"] = {"@id": QB_DATASET_ID}
            if stem.startswith("group-"):
                g = next((g for g in q["groups"] if g["id"] == stem[len("group-"):]), None)
                if g:
                    node["about"] = {"@type": "Thing", "name": g["name"], "description": g["scope"]}
                parents = parents + (("Topics", "question-bank/domains.html"),)
    elif sec == "spec":
        parents = (("Specification", "spec/index.html"),) if rel != "spec/index.html" else ()
        v2 = rel == "spec/index.html"
        canon = ROOT / "spec" / ("OWHS-v0.2-draft.md" if v2 else "OWHS-v0.1-draft.md")
        if rel in ("spec/index.html", "spec/OWHS-v0.1-draft.html"):
            ver = "0.2" if v2 else "0.1"
            first = canon.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
            md_name = "OWHS-v0.2-draft.md" if v2 else "OWHS-v0.1-draft.md"
            zip_name = "owhs-v0.2-bundle.zip" if v2 else "owhs-v0.1-bundle.zip"
            node.update({"@type": "TechArticle", "headline": first, "version": ver, "creativeWorkStatus": "Draft" if v2 else "Archived draft",
                         "license": licence_urls("CC BY 4.0", "Apache 2.0"), "creator": {"@id": PROJECT_ID}, "inLanguage": "en-GB",
                         "associatedMedia": [{"@type": "MediaObject", "name": "Specification as markdown", "contentUrl": f"{BASE}spec/{md_name}", "encodingFormat": "text/markdown"},
                                             {"@type": "MediaObject", "name": "Complete bundle", "contentUrl": f"{BASE}spec/{zip_name}", "encodingFormat": "application/zip"}]})
            if v2 and sd.latest_changelog_date("specification"):
                node["dateModified"] = sd.latest_changelog_date("specification")
            if not v2:
                parents = (("Specification", "spec/index.html"),)
            else:
                parents = ()
            name = f"Draft specification v{ver}" + ("" if v2 else " (archived)")
            node["name"] = first
    elif sec == "sweeps":
        parents = (("Evidence maintenance", "automation.html"),)
        m = re.search(r"filed (\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})", text)
        node.update({"@type": "Report", "about": {"@id": REG_DATASET_ID}, "creator": {"@id": PROJECT_ID}})
        if m:
            node["datePublished"] = f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    elif rel == "schemas/index.html":
        parents = (("Specification", "spec/index.html"),)
        node.update({"@type": "CollectionPage", "mainEntity": {"@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": i, "item": s} for i, s in enumerate(schema_nodes(), 1)]}})
    elif rel == "codelists/index.html":
        parents = (("Specification", "spec/index.html"),)
        node.update({"@type": "CollectionPage"})
        extra = codelist_nodes()
        node["mainEntity"] = {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i, "item": {"@id": n["@id"]}} for i, n in enumerate(extra, 1)]}
    elif rel == "cite.html":
        c = sd.cite_works()
        sp_ = c["specification"]
        spec_node = {"@type": "TechArticle", "@id": BASE + "spec/#specification", "name": sp_["title"], "version": sp_["version"], "creativeWorkStatus": "Draft",
                     "dateModified": sp_["date"], "url": sp_["url"], "license": licence_urls("CC BY 4.0", "Apache 2.0"), "inLanguage": "en-GB", "creator": {"@id": PROJECT_ID}}
        extra = [spec_node, registry_dataset_node(d, site), bank_dataset_node(sd.load_bank(site))]
        node["mainEntity"] = {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i, "item": {"@id": n["@id"]}} for i, n in enumerate(extra, 1)]}
    elif rel == "changelog.html":
        ds = [e["date"] for e in sd.changelog_entries() if sd.ISO.match(str(e.get("date", "")))]
        if ds:
            node["dateModified"] = max(ds)
    elif rel == "404.html":
        return None

    graph = ([node] if node else []) + extra
    if rel != "index.html":
        graph.append(breadcrumb(rel, name, parents))
        if node:
            node["breadcrumb"] = {"@id": url_of(rel) + "#breadcrumb"}
    return resolve_refs(graph, site)


def sd_admission():
    m = re.search(r'^ADMISSION_MD = HERE / "([^"]+)"', sd.REGISTRY_GENERATOR.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("tool error: registry/build_registry_site.py does not name its ADMISSION_MD")
    return m.group(1)


def serialise(graph):
    body = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, separators=(",", ":"))
    body = body.replace("</", "<\\/").replace("<!--", "<\\!--")
    return '<!-- jsonld --><script type="application/ld+json">' + body + '</script><!-- /jsonld -->'


JSONLD_RE = re.compile(r"<!-- jsonld --><script type=\"application/ld\+json\">(.*?)</script><!-- /jsonld -->", re.S)


def find_json(text):
    m = JSONLD_RE.search(text)
    return json.loads(m.group(1).replace("<\\/", "</").replace("<\\!--", "<!--")) if m else None


def check(site=None):
    site = Path(site) if site else ROOT / "site"
    problems, n = [], 0
    for p in sorted(site.rglob("*.html")):
        rel = p.relative_to(site).as_posix()
        text = p.read_text(encoding="utf-8")
        want = blocks_for(rel, text, site)
        if want is None:
            if JSONLD_RE.search(text):
                problems.append(f"{rel}: carries structured data but should not")
            continue
        n += 1
        try:
            got = find_json(text)
        except json.JSONDecodeError as e:
            problems.append(f"{rel}: JSON-LD is not well-formed JSON ({e})"); continue
        if got is None:
            problems.append(f"{rel}: no JSON-LD block; run tools/stamp_canonical.py"); continue
        if got.get("@context") != "https://schema.org" or not isinstance(got.get("@graph"), list) or not got["@graph"]:
            problems.append(f"{rel}: JSON-LD lacks the schema.org context or a non-empty @graph"); continue
        for node in got["@graph"]:
            if "@type" not in node:
                problems.append(f"{rel}: a JSON-LD node has no @type")
        if serialise(want) != JSONLD_RE.search(text).group(0):
            problems.append(f"{rel}: JSON-LD differs from a fresh build; run tools/stamp_canonical.py")
        refs = {x["@id"] for x in got["@graph"] if "@id" in x and len(x) > 1}
        def walk(o):
            if isinstance(o, dict):
                if set(o) == {"@id"} and o["@id"] not in refs:
                    problems.append(f"{rel}: reference to {o['@id']} that is not defined on the page")
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(got["@graph"])
        for key in ("dateModified", "datePublished"):
            for node in got["@graph"]:
                v = node.get(key)
                if v is not None and not sd.ISO.match(str(v)):
                    problems.append(f"{rel}: {key} {v!r} is not a calendar date")
    if problems:
        sys.exit("structured data check failed:\n  " + "\n  ".join(problems))
    print(f"up to date: {n} pages carry well-formed JSON-LD that matches a fresh build")


def self_test():
    fails = []
    def t(name, ok):
        if not ok:
            fails.append(name)
    d = sd.load_dataset()
    g = serialise([{"@type": "Thing", "name": "a</script><!--b"}])
    t("a closing tag or comment opener inside a value cannot end the block", g.count("</script>") == 1 and "<!--b" not in g)
    t("the serialised block round-trips", find_json(g)["@graph"][0]["name"] == "a</script><!--b")
    t("breadcrumb positions run from 1", [i["position"] for i in breadcrumb("a/b.html", "B", (("A", "a/index.html"),))["itemListElement"]] == [1, 2, 3])
    t("a markdown date is read", md_date(ROOT / "registry" / "RUBRIC-v1.6.md") == "2026-09-03")
    t("the registry Dataset takes its version from the dataset", registry_dataset_node(d, ROOT / "site")["version"] == d["version"])
    t("the registry Dataset date is a repository-recorded date", sd.ISO.match(registry_dataset_node(d, ROOT / "site")["dateModified"]) is not None)
    t("every code list becomes a DefinedTermSet with terms", all(n["hasDefinedTerm"] for n in codelist_nodes()))
    t("every schema in the catalogue becomes a DigitalDocument", len(schema_nodes()) >= 16)
    cite = blocks_for("cite.html", "<title>How to cite OWHS | OWHS</title>", ROOT / "site")
    t("the cite page defines the three works it lists, with their versions", {n["@id"] for n in cite if n.get("@type") in ("TechArticle", "Dataset")} == {BASE + "spec/#specification", REG_DATASET_ID, QB_DATASET_ID}
      and next(n for n in cite if n["@id"] == REG_DATASET_ID)["version"] == d["version"])
    t("the 404 page carries none", blocks_for("404.html", "<title>x</title>", ROOT / "site") is None)
    t("an unknown licence name is refused", _refuses(lambda: licence_urls("Mystery 9")))
    if fails:
        print("self-test FAILED: " + "; ".join(fails)); sys.exit(1)
    print("self-test ok: 11 cases (script-safe serialisation, breadcrumbs, dates, dataset, code lists, schemas, 404, unknown licence)")


def _refuses(fn):
    try:
        fn()
    except SystemExit:
        return True
    return False


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        print(__doc__)
