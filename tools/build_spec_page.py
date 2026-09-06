#!/usr/bin/env python3
"""Render the published specification pages from their canonical markdown, one chain per version:

    spec/OWHS-v0.2-draft.md  ->  site/spec/OWHS-v0.2-draft.md  ->  site/spec/index.html            (current)
    spec/OWHS-v0.1-draft.md  ->  site/spec/OWHS-v0.1-draft.md  ->  site/spec/OWHS-v0.1-draft.html  (archived, same route directory so its links keep resolving)
    (canonical source)           (publication copy)               (rendered page)

The publication copy is the canonical markdown with its links rewritten for the site/spec/ directory and the
reference to the domain routing table removed (that table is not part of the release). For v0.1 that transformation
is publish_markdown() here; for v0.2 it is the publication step of tools/build_spec_v0_2.py, which this renderer
re-applies and compares, so both copies are checked against their canonical source by one command. Each page is the
publication copy rendered with a pinned library and dropped into tools/spec_template.html (head, navigation, sidebar
contents, downloads block with the version's own file names, a note pointing at the other version, footer); the sidebar,
the download sizes and the code-list count are computed from the files rather than typed.

    python tools/build_spec_page.py            # write both publication copies and both pages
    python tools/build_spec_page.py --check    # regenerate into a temporary copy of site/, stamp it, compare; exit 1 on drift

Heading identifiers follow pandoc's auto-identifier rules, and highlighted code blocks carry pandoc's cbN and
cbN-M identifiers, because the page was first rendered with pandoc and other pages may link to those anchors.
"""
import json, os, re, sys, filecmp, shutil, subprocess, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
SPEC_DIR = SITE_ROOT / "spec"
TEMPLATE = ROOT / "tools" / "spec_template.html"
# retained names for the v0.1 chain (other tools import them)
CANONICAL = ROOT / "spec" / "OWHS-v0.1-draft.md"
MD = ROOT / "site" / "spec" / "OWHS-v0.1-draft.md"
OUT = SPEC_DIR / "OWHS-v0.1-draft.html"
BUNDLE = ROOT / "site" / "spec" / "owhs-v0.1-bundle.zip"


def v2_publish(text):
    import build_spec_v0_2 as b2
    return b2.publish(text)


def registry_count(path):
    try: return len(json.loads(path.read_text(encoding="utf-8"))["lists"])
    except Exception: return None


VERSIONS = {
    "v0.2": {"canonical": ROOT / "spec" / "OWHS-v0.2-draft.md", "md": ROOT / "site" / "spec" / "OWHS-v0.2-draft.md", "out": SPEC_DIR / "index.html", "bundle": ROOT / "site" / "spec" / "owhs-v0.2-bundle.zip",
             "publish": v2_publish, "title": "The draft specification",
             "bundle_contents": "specification with its entity diagram, sixteen JSON schemas with valid and invalid conformance examples, {lists} versioned codelists, the reference validator, the measurement-bundle and entity-graph checkers, the profile envelope, governance and decision log",
             "registry": ROOT / "codelists" / "_registry.json",
             "note": 'This is the current draft (v0.2). The previous draft, v0.1, remains available: <a href="OWHS-v0.1-draft.html">page</a>, <a href="OWHS-v0.1-draft.md">markdown</a>, <a href="owhs-v0.1-bundle.zip">bundle</a>.'},
    "v0.1": {"canonical": CANONICAL, "md": MD, "out": OUT, "bundle": BUNDLE, "publish": None, "title": "The draft specification, v0.1 (archived)",
             "bundle_contents": "specification with its entity diagram, JSON schemas with valid and invalid conformance examples, 24 versioned codelists, the reference validator, governance and decision log",
             "registry": None,
             "note": 'This is the archived v0.1 draft, kept as published. The current draft is v0.2: <a href="index.html">read it here</a>.'},
}


# canonical -> publication copy. Each rule is (canonical text, published text) and must apply exactly once.
PUBLISH_RULES = [
    ("[`validation_report.json`](../examples/validation_report.json). Everything else", "[`validation_report.json`](examples/validation_report.json). Everything else"),
    ("The full table is in [`domain_routing_v0.1.csv`](codelists/domain_routing_v0.1.csv); the reasoning", "The full routing table is not included in this release; the reasoning"),
    ("The Mermaid source is [`erd.mmd`](erd.mmd)", "The Mermaid source is [`owhs_erd_v0.1.mmd`](diagrams/owhs_erd_v0.1.mmd)"),
    ("![OWHS v0.1 entity-relationship diagram](../site/owhs-erd-v0.1.svg)", "![OWHS v0.1 entity-relationship diagram](../owhs-erd-v0.1.svg)"),
    ("Files: [codelists/](codelists/).", "Files: every list is in the download bundle (`owhs-v0.1-bundle.zip`) under `codelists/`."),
    ("The machine-checked results are in [`validation_report.json`](../examples/validation_report.json); the validator run", "The machine-checked results are in [`validation_report.json`](examples/validation_report.json); the validator run"),
]
NEVER_PUBLISHED = ("domain_routing_v0.1.csv", "domain-coverage-decisions")


def publish_markdown(canonical_text):
    """The publication copy of the canonical markdown. Refuses to run if a rule does not apply exactly once or if
    excluded material would survive, so a canonical edit that moves a rewritten sentence fails loudly rather than
    publishing the wrong link."""
    t = canonical_text
    for old, new in PUBLISH_RULES:
        if t.count(old) != 1:
            raise SystemExit(f"publication rule applies {t.count(old)} times, expected once: {old[:60]!r}")
        t = t.replace(old, new)
    for term in NEVER_PUBLISHED:
        if term in t:
            raise SystemExit(f"publication copy would carry excluded material: {term!r}")
    return t


def code_block_anchors(body):
    """pandoc gives every highlighted (language-tagged) code block the id cbN and each line cbN-M."""
    n = [0]
    def repl(m):
        n[0] += 1; lang = m.group(1); lines = m.group(2).split("\n")
        if lines and lines[-1] == "": lines = lines[:-1]
        spans = "\n".join(f'<span id="cb{n[0]}-{i}"><a href="#cb{n[0]}-{i}" aria-hidden="true" tabindex="-1"></a>{ln}</span>' for i, ln in enumerate(lines, 1))
        return f'<div class="sourceCode" id="cb{n[0]}"><pre class="sourceCode {lang}"><code class="sourceCode {lang}">{spans}</code></pre></div>'
    return re.sub(r'<pre><code class="language-([a-z0-9]+)">(.*?)</code></pre>', repl, body, flags=re.S)


def pandoc_slug(text):
    """pandoc's auto_identifiers: strip formatting, lowercase, drop all but letters/digits/_/-/./space, spaces to
    hyphens, remove everything up to the first letter, empty becomes 'section'."""
    t = re.sub(r"<[^>]+>", "", text)
    t = t.lower()
    t = re.sub(r"[^\w\s\-.]", "", t, flags=re.UNICODE)
    t = re.sub(r"\s+", "-", t.strip())
    t = re.sub(r"^[^a-z]+", "", t)
    return t or "section"


def render_markdown(text):
    import markdown
    from markdown.extensions.toc import TocExtension
    md = markdown.Markdown(extensions=[
        "tables", "fenced_code", "footnotes", "attr_list", "md_in_html", "sane_lists",
        TocExtension(slugify=lambda value, separator: pandoc_slug(value), toc_depth="2-3", permalink=False),
    ], output_format="html5")
    html = md.convert(text)
    return html, md


def toc_html(body):
    items = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body, flags=re.S)
    out = []
    for hid, inner in items:
        label = re.sub(r"<[^>]+>", "", inner).strip()
        if hid.startswith("open-workplace-health-standard"):      # the document title is the page's h2.doc-title, not a section
            continue
        out.append(f'<li><a href="#{hid}">{label}</a></li>\n')
    return "".join(out)


def build(published_text=None, version="v0.1"):
    v = VERSIONS[version]
    text = published_text if published_text is not None else (v["publish"] or publish_markdown)(v["canonical"].read_text(encoding="utf-8"))
    body, _ = render_markdown(text)
    body = code_block_anchors(body)
    # the markdown's single h1 is the document's own title; the shell already has the page h1, so it becomes h2.doc-title
    body = re.sub(r'<h1 id="([^"]*)">(.*?)</h1>', r'<h2 class="doc-title" id="\1">\2</h2>', body, count=1, flags=re.S)
    tpl = TEMPLATE.read_text(encoding="utf-8")
    lists = registry_count(v["registry"]) if v["registry"] else None
    contents = v["bundle_contents"].format(lists=lists if lists is not None else "the")
    page = (tpl.replace("{{TOC}}", toc_html(body)).replace("{{BODY}}", body).replace("{{VERSION}}", version).replace("{{TITLE}}", v["title"])
               .replace("{{MD_NAME}}", v["md"].name).replace("{{ZIP_NAME}}", v["bundle"].name).replace("{{BUNDLE_CONTENTS}}", contents).replace("{{VERSION_NOTE}}", v["note"])
               .replace("{{MD_KB}}", str(round(len(text.encode("utf-8")) / 1024)))
               .replace("{{ZIP_KB}}", str(round(v["bundle"].stat().st_size / 1024)) if v["bundle"].exists() else "?"))
    assert "{{" not in page, "unfilled placeholder"
    return page


def published_copy(version):
    v = VERSIONS[version]
    return (v["publish"] or publish_markdown)(v["canonical"].read_text(encoding="utf-8"))


def link_problems(page_path, html):
    """Every relative href or src on a rendered spec page must resolve to a file under its directory (fragments aside); external links are not fetched."""
    out = []
    for m in re.finditer(r'(?:href|src)="([^"#]+)(?:#[^"]*)?"', html):
        target = m.group(1)
        if re.match(r"^(https?:|mailto:|/)", target) or target.startswith("#"): continue
        if not (page_path.parent / target).exists(): out.append(target)
    return sorted(set(out))


def check():
    for f in (TEMPLATE,):
        if not f.exists(): sys.exit(f"{f.relative_to(ROOT)} is missing")
    for version, v in VERSIONS.items():
        for f in (v["canonical"], v["md"], v["out"]):
            if not f.exists(): sys.exit(f"{f.relative_to(ROOT)} is missing; run tools/build_spec_page.py then tools/stamp_canonical.py")
        published = published_copy(version)
        if v["md"].read_text(encoding="utf-8") != published:
            import difflib
            a = v["md"].read_text(encoding="utf-8").splitlines(); b = published.splitlines()
            excerpt = "\n".join(list(difflib.unified_diff(a, b, "committed publication copy", "fresh from canonical", n=0, lineterm=""))[:20])
            sys.exit(f"{v['md'].relative_to(ROOT)} is not the publication copy of {v['canonical'].relative_to(ROOT)}; run tools/build_spec_page.py then tools/stamp_canonical.py\n" + excerpt)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(ROOT / "site", tmp_site)
        for version, v in VERSIONS.items():
            (tmp_site / v["out"].relative_to(ROOT / "site")).write_text(build(published_copy(version), version), encoding="utf-8")
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
        if r.returncode != 0: sys.exit("[check] stamp failed:\n" + r.stdout + r.stderr)
        for version, v in VERSIONS.items():
            fresh = tmp_site / v["out"].relative_to(ROOT / "site")
            if not filecmp.cmp(fresh, v["out"], shallow=False):
                import difflib
                a = v["out"].read_text(encoding="utf-8").splitlines(); b = fresh.read_text(encoding="utf-8").splitlines()
                excerpt = "\n".join(list(difflib.unified_diff(a, b, "committed", "fresh render", n=0, lineterm=""))[:20])
                sys.exit(f"{v['out'].relative_to(ROOT)} does not match a fresh render of the publication copy; run tools/build_spec_page.py then tools/stamp_canonical.py\n" + excerpt)
            bad = link_problems(v["out"], v["out"].read_text(encoding="utf-8"))
            if bad: sys.exit(f"{v['out'].relative_to(ROOT)} carries relative links that do not resolve: {bad[:10]}")
    print("up to date: both publication copies and both pages follow their canonical markdown (v0.2 current at spec/, v0.1 archived at spec/OWHS-v0.1-draft.html); every relative link resolves")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        for version, v in VERSIONS.items():
            v["out"].parent.mkdir(parents=True, exist_ok=True)
            published = published_copy(version)
            v["md"].write_text(published, encoding="utf-8")
            v["out"].write_text(build(published, version), encoding="utf-8")
            print(f"wrote {v['md'].relative_to(ROOT)} and {v['out'].relative_to(ROOT) if v['out'].is_relative_to(ROOT) else v['out']} from {v['canonical'].relative_to(ROOT)}")
