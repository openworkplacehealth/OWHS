#!/usr/bin/env python3
"""Render the document pages listed in docs/MANIFEST.json through tools/doc_template.html, with a check in CI.

    python tools/build_doc_page.py            # render every page in the manifest
    python tools/build_doc_page.py --check    # render into a temporary copy of site/, stamp it, compare; exit 1 on drift, a missing source or a broken local link
    python tools/build_doc_page.py --self-test

The manifest is the expected set: a listed source that is absent fails the check even when its output survives, and a
docs/*.md file that is not listed fails it too. The first heading of the markdown is the page title. A line
`<!-- meta: ... -->` at the top supplies the grey meta line; a line `<!-- description: ... -->` supplies the description
tag. Local links are parsed as URLs: a relative or root-relative href must name a file under site/ (a directory resolves
to its index.html; a query string is not part of the file name), and a fragment on a local link must name an id in
the target page. Links with a scheme are not fetched.
"""
import filecmp, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
DOCS = ROOT / "docs"
MANIFEST = DOCS / "MANIFEST.json"
TEMPLATE = ROOT / "tools" / "doc_template.html"


def manifest_pages(root=ROOT):
    """[(source Path, output relative to site/)] from the manifest; problems for an absent source or an unlisted docs file."""
    m = json.loads((root / "docs" / "MANIFEST.json").read_text(encoding="utf-8"))
    pages, problems = [], []
    listed = set()
    for e in m["pages"]:
        src = root / e["source"]; listed.add(src.resolve())
        out = e["output"]
        if not out.startswith("site/"): problems.append(f"{out}: output must be under site/"); continue
        if not src.exists(): problems.append(f"{e['source']}: listed in the manifest but absent; its output {out} has no source"); continue
        pages.append((src, out[len("site/"):]))
    for md in sorted((root / "docs").glob("*.md")):
        if md.resolve() not in listed: problems.append(f"docs/{md.name}: not listed in docs/MANIFEST.json")
    return pages, problems


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


def local_link_problems(page: str, site_root: Path, page_rel: str = "") -> list:
    """Every local href (relative or root-relative) must resolve to a file under site/, and a fragment must name an id
    in the target page. Links with a scheme (https, mailto) are left alone."""
    out = []
    page_dir = Path(page_rel).parent if page_rel else Path(".")
    for href in re.findall(r'href="([^"]+)"', page):
        u = urlsplit(href.replace("&amp;", "&"))
        if u.scheme or u.netloc: continue
        if not u.path:
            target = site_root / page_rel if page_rel else None      # same-page fragment
        else:
            rel = Path(u.path.lstrip("/")) if u.path.startswith("/") else (page_dir / u.path)
            target = site_root / rel
            if target.is_dir(): target = target / "index.html"
        if target is None or not target.is_file():
            out.append(f"{href}: no such file under site/"); continue
        if u.fragment and target.suffix == ".html":
            if not re.search(r'\b(?:id|name)="' + re.escape(u.fragment) + '"', target.read_text(encoding="utf-8", errors="replace")):
                out.append(f"{href}: no id {u.fragment!r} in {target.name}")
    return sorted(set(out))


def check(root: Path) -> list:
    """Problems with the committed pages: manifest, drift, links. Renders into a temporary copy; writes nothing under root."""
    pages, problems = manifest_pages(root)
    rendered = {out_rel: render(src) for src, out_rel in pages}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"; shutil.copytree(root / "site", tmp_site)
        for out_rel, html in rendered.items():
            (tmp_site / out_rel).write_text(html, encoding="utf-8")
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, str(root / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
        if r.returncode != 0: return problems + ["stamp failed: " + (r.stdout + r.stderr).strip()]
        for out_rel in rendered:
            fresh, committed = tmp_site / out_rel, root / "site" / out_rel
            if not committed.exists(): problems.append(f"site/{out_rel}: missing; run tools/build_doc_page.py then tools/stamp_canonical.py")
            elif not filecmp.cmp(fresh, committed, shallow=False): problems.append(f"site/{out_rel}: differs from a fresh render of its source")
            problems += [f"site/{out_rel}: {h}" for h in local_link_problems(fresh.read_text(encoding="utf-8"), tmp_site, out_rel)]
    return problems


def self_test():
    """Probes on a temporary copy of the repository; the working tree is never written."""
    failures = 0
    def probe(label, mutate, must):
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir(); shutil.copytree(ROOT / "docs", root / "docs"); shutil.copytree(ROOT / "site", root / "site"); shutil.copytree(ROOT / "tools", root / "tools")
            if (ROOT / "robots-policy.txt").exists(): shutil.copy(ROOT / "robots-policy.txt", root / "robots-policy.txt")     # the stamp reads the policy from the repository root
            mutate(root)
            probs = check(root)
            ok = (any(must in x for x in probs) if must else not probs)
            print(("ok  " if ok else "FAIL"), label, "" if ok else probs[:3]); failures += not ok
    probe("committed pages check clean", lambda r: None, "")
    probe("a listed source deleted while its output survives is detected", lambda r: (r / "docs" / "science.md").unlink(), "absent; its output")
    probe("an unlisted docs file is detected", lambda r: (r / "docs" / "stray.md").write_text("# Stray\n\ntext\n"), "not listed in docs/MANIFEST.json")
    def root_rel(r):
        p = r / "docs" / "science.md"; p.write_text(p.read_text() + "\n[gone](/missing-review-target.html)\n")
    probe("a root-relative link to a missing target is detected (source edited, so drift is also reported)", root_rel, "missing-review-target.html: no such file")
    def frag(r):
        p = r / "docs" / "science.md"; p.write_text(p.read_text() + "\n[frag](methods.html#no-such-id)\n")
    probe("a fragment naming no id in the target page is detected", frag, "no id 'no-such-id'")
    def query(r):
        p = r / "docs" / "science.md"; p.write_text(p.read_text() + "\n[q](methods.html?utm=x)\n")
        html = render(p); (r / "site" / "science.html").write_text(html)
        env = dict(os.environ, OWHS_SITE_DIR=str(r / "site"), PYTHONDONTWRITEBYTECODE="1")
        subprocess.run([sys.executable, str(r / "tools" / "stamp_canonical.py")], env=env, capture_output=True)
    probe("a query string is a URL component, not part of the file name", query, "")
    def html_only(r):
        p = r / "site" / "science.html"; p.write_text(p.read_text().replace("</footer>", "<p>x</p></footer>"))
    probe("an edited output with an unchanged source is detected", html_only, "differs from a fresh render")
    def meta_change(r):
        p = r / "docs" / "science.md"; p.write_text(p.read_text().replace("<!-- description: How", "<!-- description: Changed how"))
    probe("a changed description tag in the source is detected as drift", meta_change, "differs from a fresh render")
    print(f"{'all' if not failures else failures} probes {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


def main():
    if "--self-test" in sys.argv: return self_test()
    if "--check" in sys.argv:
        problems = check(ROOT)
        if problems: sys.exit("generated document pages do not match their manifest and sources; run tools/build_doc_page.py then tools/stamp_canonical.py\n" + "".join(f"  {b}\n" for b in problems))
        pages, _ = manifest_pages(ROOT)
        print(f"up to date: {len(pages)} document page(s) match docs/MANIFEST.json and docs/, every local link and fragment resolves")
        return
    pages, problems = manifest_pages(ROOT)
    if problems: sys.exit("manifest problems:\n" + "".join(f"  {b}\n" for b in problems))
    for src, out_rel in pages:
        (SITE_ROOT / out_rel).write_text(render(src), encoding="utf-8"); print(f"rendered site/{out_rel} from docs/{src.name}")


if __name__ == "__main__":
    main()
