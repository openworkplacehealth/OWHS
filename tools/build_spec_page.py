#!/usr/bin/env python3
"""Render site/spec/index.html from site/spec/OWHS-v0.1-draft.md.

The rendered specification page and its markdown drifted apart whenever one was edited without the other. This
tool makes the page a function of the markdown: the markdown is rendered with a pinned library, dropped into
tools/spec_template.html (the page shell: head, navigation, sidebar contents, downloads block, footer), and
the sidebar and the download sizes are computed from the files rather than typed.

    python tools/build_spec_page.py            # write site/spec/index.html
    python tools/build_spec_page.py --check    # render into a temporary copy of site/, stamp it, compare; exit 1 on drift

Heading identifiers follow pandoc's auto-identifier rules, because the page was first rendered with pandoc and
other pages link to those anchors.
"""
import os, re, sys, filecmp, shutil, subprocess, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
SPEC_DIR = SITE_ROOT / "spec"
MD = ROOT / "site" / "spec" / "OWHS-v0.1-draft.md"
TEMPLATE = ROOT / "tools" / "spec_template.html"
OUT = SPEC_DIR / "index.html"
BUNDLE = ROOT / "site" / "spec" / "owhs-v0.1-bundle.zip"


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


def build():
    text = MD.read_text(encoding="utf-8")
    body, _ = render_markdown(text)
    # the markdown's single h1 is the document's own title; the shell already has the page h1, so it becomes h2.doc-title
    body = re.sub(r'<h1 id="([^"]*)">(.*?)</h1>', r'<h2 class="doc-title" id="\1">\2</h2>', body, count=1, flags=re.S)
    tpl = TEMPLATE.read_text(encoding="utf-8")
    page = (tpl.replace("{{TOC}}", toc_html(body)).replace("{{BODY}}", body)
               .replace("{{MD_KB}}", str(round(MD.stat().st_size / 1024)))
               .replace("{{ZIP_KB}}", str(round(BUNDLE.stat().st_size / 1024)) if BUNDLE.exists() else "?"))
    assert "{{" not in page, "unfilled placeholder"
    return page


def check():
    committed = ROOT / "site" / "spec" / "index.html"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(ROOT / "site", tmp_site)
        (tmp_site / "spec" / "index.html").write_text(build(), encoding="utf-8")
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("[check] stamp failed:\n" + r.stdout + r.stderr)
        if not filecmp.cmp(tmp_site / "spec" / "index.html", committed, shallow=False):
            import difflib
            a = committed.read_text(encoding="utf-8").splitlines(); b = (tmp_site / "spec" / "index.html").read_text(encoding="utf-8").splitlines()
            excerpt = "\n".join(list(difflib.unified_diff(a, b, "committed", "fresh render", n=0, lineterm=""))[:20])
            sys.exit("site/spec/index.html does not match a fresh render of site/spec/OWHS-v0.1-draft.md; run tools/build_spec_page.py then tools/stamp_canonical.py\n" + excerpt)
        print("up to date: site/spec/index.html matches its markdown")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(build(), encoding="utf-8")
        print(f"rendered {OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT} from {MD.name}")
