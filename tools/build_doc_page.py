#!/usr/bin/env python3
"""Render docs/<name>.md to site/<name>.html through tools/doc_template.html, with a check in CI.

    python tools/build_doc_page.py            # render every docs/*.md
    python tools/build_doc_page.py --check    # render into a temporary copy of site/, stamp it, compare; exit 1 on drift or a broken local link

The first heading of the markdown is the page title. A line `<!-- meta: ... -->` at the top supplies the grey meta line;
a line `<!-- description: ... -->` supplies the description tag. Local links (href without a scheme) must resolve to a
file under site/, or the check fails.
"""
import filecmp, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
DOCS = ROOT / "docs"
TEMPLATE = ROOT / "tools" / "doc_template.html"


def render(md_path: Path) -> str:
    import markdown
    text = md_path.read_text(encoding="utf-8")
    meta = re.search(r"<!-- meta: (.*?) -->", text); desc = re.search(r"<!-- description: (.*?) -->", text)
    text = re.sub(r"<!-- (meta|description): .*? -->\n?", "", text)
    title = re.search(r"^# (.*)$", text, re.M).group(1).strip()
    body_md = re.sub(r"^# .*\n", "", text, count=1)
    body = markdown.markdown(body_md, extensions=["tables", "sane_lists"], output_format="html5")
    tpl = TEMPLATE.read_text(encoding="utf-8")
    page = (tpl.replace("{{TITLE}}", title).replace("{{META}}", meta.group(1) if meta else "")
               .replace("{{DESCRIPTION}}", desc.group(1) if desc else title).replace("{{BODY}}", body))
    assert "{{" not in page, "unfilled placeholder"
    return page


def local_link_problems(page: str, site_root: Path) -> list:
    out = []
    for href in re.findall(r'href="([^"#]+)(?:#[^"]*)?"', page):
        if re.match(r"^[a-z]+:", href) or href.startswith("/"):
            continue
        if not (site_root / href).exists():
            out.append(href)
    return sorted(set(out))


def main():
    pages = {p: render(p) for p in sorted(DOCS.glob("*.md"))}
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_site = Path(tmp) / "site"; shutil.copytree(ROOT / "site", tmp_site)
            for p, html in pages.items():
                (tmp_site / f"{p.stem}.html").write_text(html, encoding="utf-8")
            env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
            if r.returncode != 0: sys.exit("[check] stamp failed:\n" + r.stdout + r.stderr)
            bad = []
            for p in pages:
                fresh, committed = tmp_site / f"{p.stem}.html", ROOT / "site" / f"{p.stem}.html"
                if not committed.exists() or not filecmp.cmp(fresh, committed, shallow=False): bad.append(f"differs or missing: site/{p.stem}.html")
                bad += [f"site/{p.stem}.html: local link to missing target {h}" for h in local_link_problems(fresh.read_text(encoding="utf-8"), tmp_site)]
            if bad: sys.exit("generated document pages do not match their sources; run tools/build_doc_page.py then tools/stamp_canonical.py\n" + "".join(f"  {b}\n" for b in bad))
            print(f"up to date: {len(pages)} document page(s) match docs/ and every local link resolves")
        return
    for p, html in pages.items():
        (SITE_ROOT / f"{p.stem}.html").write_text(html, encoding="utf-8"); print(f"rendered site/{p.stem}.html from docs/{p.name}")


if __name__ == "__main__":
    main()
