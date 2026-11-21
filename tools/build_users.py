#!/usr/bin/env python3
"""site/using-owhs.html: the public register of organisations that say they use or map to OWHS, generated from community/using-owhs.json.

    python tools/build_users.py            write site/using-owhs.html
    python tools/build_users.py --check    fail if the committed page differs from a fresh build (stamped like every page), or the data file is invalid
    python tools/build_users.py --self-test

The register is empty today and the page says so in its first line. An entry is a declaration by the organisation: it is not certification, not an
endorsement by the project of the organisation or by the organisation of the project, and the project has not tested it unless the entry links a public
result. Each entry must carry a declared interest (the repository's rule in GOVERNANCE.md is that contributors declare financial or professional interests
and that those declarations are public). To be added, an organisation opens the "Add my organisation" issue form or emails the address the site already uses.
"""
import json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import site_pages as sp

DATA = ROOT / "community" / "using-owhs.json"
GITHUB = "https://github.com/openworkplacehealth/OWHS"
FORM = GITHUB + "/issues/new?template=6-add-my-organisation.yml"
EMAIL = "hello@openworkplacehealth.org"
USES = ["maps data to OWHS entities", "produces or consumes OWHS-shaped data", "uses the instrument registry", "uses the question bank", "other, described in the entry"]
ENTRY_KEYS = {"name", "url", "uses", "what", "declared_interest", "listed_on", "request"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def problems(doc):
    """Schema check for the data file; a list of named problems, empty when valid."""
    out = []
    if not isinstance(doc, dict):
        return ["the file is not an object"]
    if set(doc) - {"schema_version", "note", "organisations"}:
        out.append(f"unknown top-level keys {sorted(set(doc) - {'schema_version', 'note', 'organisations'})}")
    if doc.get("schema_version") != "1.0":
        out.append("schema_version must be '1.0'")
    if not isinstance(doc.get("note"), str) or not doc["note"].strip():
        out.append("note is missing")
    orgs = doc.get("organisations")
    if not isinstance(orgs, list):
        return out + ["organisations must be a list"]
    seen = set()
    for i, e in enumerate(orgs):
        tag = f"organisations[{i}]"
        if not isinstance(e, dict):
            out.append(f"{tag}: not an object"); continue
        if set(e) - ENTRY_KEYS:
            out.append(f"{tag}: unknown keys {sorted(set(e) - ENTRY_KEYS)}")
        for k in ("name", "url", "uses", "what", "declared_interest", "listed_on", "request"):
            if k not in e:
                out.append(f"{tag}: {k} is required")
        for k in ("name", "what", "declared_interest", "request"):
            if k in e and (not isinstance(e[k], str) or not e[k].strip()):
                out.append(f"{tag}: {k} must be non-empty text")
        if "url" in e and not (isinstance(e["url"], str) and re.fullmatch(r"https://[^\s<>\"]+", e["url"])):
            out.append(f"{tag}: url must be an https address")
        if "uses" in e and (not isinstance(e["uses"], list) or not e["uses"] or any(u not in USES for u in e["uses"])):
            out.append(f"{tag}: uses must be a non-empty list drawn from {USES}")
        if "listed_on" in e and not (isinstance(e["listed_on"], str) and ISO.match(e["listed_on"])):
            out.append(f"{tag}: listed_on must be an ISO date")
        if "request" in e and isinstance(e["request"], str) and not (e["request"] == "email" or e["request"].startswith(GITHUB + "/issues/")):
            out.append(f"{tag}: request must be 'email' or the address of the GitHub issue that asked for the listing")
        if isinstance(e.get("name"), str):
            if e["name"].strip().lower() in seen:
                out.append(f"{tag}: {e['name']!r} is listed twice")
            seen.add(e["name"].strip().lower())
        for k, v in e.items():
            if isinstance(v, str) and any(d in v for d in "—–"):
                out.append(f"{tag}: {k} has an em or en dash")
    return out


def load():
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    bad = problems(doc)
    if bad:
        raise SystemExit("community/using-owhs.json is invalid:\n  " + "\n  ".join(bad))
    return doc


def long_date(iso):
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    y, m, d = iso.split("-")
    return f"{int(d)} {months[int(m) - 1]} {y}"


def body(doc):
    orgs = doc["organisations"]
    esc = sp.esc
    if orgs:
        lead = f"{len(orgs)} organisation{'s are' if len(orgs) != 1 else ' is'} listed. Each entry is what that organisation declares."
        items = "".join(f"""<div class="job"><h3><a href="{esc(e['url'])}">{esc(e['name'])}</a></h3>
  <p>{esc(e['what'])}</p>
  <p class="when">{esc('; '.join(e['uses']))} · listed {long_date(e['listed_on'])}</p>
  <p><strong>Interest declared:</strong> {esc(e['declared_interest'])}</p>
</div>""" for e in sorted(orgs, key=lambda e: e["name"].lower()))
        listing = f'<h2 id="listed">Listed organisations</h2>\n{items}'
    else:
        lead = "No organisation is listed yet."
        listing = ""
    return f"""<span class="status-chip">register · generated from the repository</span>
<h1>Who uses OWHS</h1>
<p class="lede">{lead} This is the public register of organisations that say they use, or have mapped data to, the Open Workplace Health Standard.</p>
{listing}
<h2 id="meaning">What being listed means</h2>
<ul>
  <li><strong>It is a declaration by the organisation</strong> that it uses, or has mapped to, a named part of the standard, the registry or the question bank.</li>
  <li><strong>It is not certification.</strong> A listing does not say that an organisation conforms at any level. An entry can link a public result, such as a validation report; the register shows the link and does not treat it as a test of the claim.</li>
  <li><strong>It is not an endorsement</strong> by the project of the organisation, or by the organisation of the project.</li>
  <li><strong>Interests are declared in public.</strong> Contributors to OWHS are asked to declare any financial or professional interest, and those declarations are public (see <a href="governance.html">governance</a>). Every entry carries one, including an organisation that sells a product implementing OWHS.</li>
</ul>
<p>Independent use is also one of the evidence points the project's <a href="governance.html">governance page</a> names for moving to multi-stakeholder governance, which is one reason to keep an honest register: an empty one is more useful than an inflated one.</p>

<h2 id="add">How to be added</h2>
<ul>
  <li>Open the <a href="{FORM}">Add my organisation</a> form on GitHub. It asks for the name, a website, what you use and a declaration of interest. The issue is public.</li>
  <li>Or email <a href="mailto:{EMAIL}">{EMAIL}</a> if you would rather not raise it in public.</li>
</ul>
<p>Do not send real records or personal data. If you tried a mapping and it failed, a <a href="contribute.html">mapping report</a> is worth as much as a listing.</p>
"""


def build():
    return sp.shell("Who uses OWHS | OWHS", "The public register of organisations that say they use or map to OWHS: what a listing means, how to be added, and who is listed. No organisation is listed yet.", body(load()))


def write():
    (sp.SITE_ROOT / "using-owhs.html").write_text(build(), encoding="utf-8")
    print("wrote using-owhs.html")


def check():
    load()
    sp.check_built(Path(__file__).resolve(), ["using-owhs.html"], "the register page")
    t = ROOT / ".github" / "ISSUE_TEMPLATE" / "6-add-my-organisation.yml"
    if not t.exists():
        sys.exit("the register page links the 'Add my organisation' issue form and .github/ISSUE_TEMPLATE/6-add-my-organisation.yml does not exist")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}".strip())
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    t("the committed register is valid and empty", not problems(doc) and doc["organisations"] == [], problems(doc))
    page = body(doc)
    t("an empty register says so first and lists nothing", "No organisation is listed yet." in page and "Listed organisations" not in page)
    t("the page says what listing is not", "not certification" in page.lower() and "not an endorsement" in page.lower() and "declaration by the organisation" in page)
    t("the page names both ways to be added", FORM in page and f"mailto:{EMAIL}" in page)
    t("the issue form named on the page exists with the interest declaration the other forms carry", "Declaration of interest" in (ROOT / ".github" / "ISSUE_TEMPLATE" / "6-add-my-organisation.yml").read_text(encoding="utf-8"))
    ok = {"name": "Example Ltd", "url": "https://example.org/", "uses": [USES[0]], "what": "Maps absence exports.", "declared_interest": "None.", "listed_on": "2026-12-01", "request": GITHUB + "/issues/1"}
    full = {**doc, "organisations": [ok]}
    t("a valid entry passes and is rendered with its interest and date", not problems(full) and "Interest declared:" in body(full) and "1 December 2026" in body(full) and "1 organisation is listed" in body(full))
    for label, bad in (("a missing declared interest", {k: v for k, v in ok.items() if k != "declared_interest"}), ("an unknown key", {**ok, "logo": "x"}), ("an http address", {**ok, "url": "http://example.org/"}),
                       ("an unknown use", {**ok, "uses": ["certified"]}), ("a prose date", {**ok, "listed_on": "1 Dec 2026"}), ("a request that is not an issue or email", {**ok, "request": "a friend"}),
                       ("an em dash", {**ok, "what": "a — b"}), ("an empty name", {**ok, "name": " "})):
        t(f"{label} is refused", bool(problems({**doc, "organisations": [bad]})))
    t("a duplicate name is refused", bool(problems({**doc, "organisations": [ok, {**ok, "name": "example ltd"}]})))
    t("markup in a name cannot reach the page", "<script>" not in body({**doc, "organisations": [{**ok, "name": "<script>x</script>"}]}))
    t("the page is not the steward's own firm or a product: no entry is built in", "Alltoogether" not in page and "All Toogether" not in page)
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("self-test ok: 16 cases (schema, empty register wording, what listing means, both routes to be added, refusals, escaping)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        write()
