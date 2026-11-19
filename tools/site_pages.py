#!/usr/bin/env python3
"""Shared page shell and check for the pages that tools/build_status.py, build_cite.py and build_users.py generate at the top level of site/.

The shell is the same house style the reference pages use (tools/build_reference_pages.py supplies the stylesheet), with the main navigation
every page carries. The footer, the canonical link, the structured data and the visit counting are not written here: tools/stamp_canonical.py adds
them to every page, so a rebuild never loses them.

A generator that uses this module writes its pages to SITE_ROOT and, for its --check, calls check_built(): it regenerates into a temporary copy of
site/, runs the stamp tool on that copy and compares each output byte for byte with the committed file.

    python tools/site_pages.py --self-test
"""
import filecmp, html, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_reference_pages as brp

SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
NAV = [("index.html", "Home"), ("why.html", "The case"), ("how-it-works.html", "How it works"), ("standard.html", "Inside the standard"),
       ("question-bank/index.html", "Question bank"), ("instrument-registry/index.html", "Instrument registry"), ("methods.html", "How we grade"),
       ("governance.html", "Governance"), ("review.html", "Open review"), ("changelog.html", "Changelog"), ("search.html", "Search")]

EXTRA_CSS = """
.job{border:1px solid var(--line);border-radius:8px;padding:12px 18px;margin:12px 0;max-width:780px}
.job h3{margin:0 0 4px}
.job p{margin:6px 0}
.job .when{font-family:var(--mono);font-size:13px;color:var(--muted)}
.job .links{font-size:14.5px}
.live{font-family:var(--mono);font-size:12.5px;color:var(--muted)}
.cite{background:var(--wash);border-left:4px solid var(--accent);padding:12px 18px;margin:12px 0;max-width:780px;overflow-wrap:anywhere}
.cite p{margin:6px 0}
pre.bib{font-family:var(--mono);font-size:12.5px;background:var(--wash);padding:12px 14px;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere;max-width:780px;margin:10px 0}
dl.facts{max-width:780px;margin:10px 0}
dl.facts dt{font-weight:600;color:var(--ink);margin-top:10px}
dl.facts dd{margin:2px 0 0}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def shell(title, desc, body, extra_head=""):
    nav = "\n".join(f'    <a href="{h}">{esc(t)}</a>' for h, t in NAV)
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{brp.CSS}{EXTRA_CSS}</style>
{extra_head}</head>
<body>
<header class="owhs"><div class="navbar">
  <a class="mark" href="index.html"><span class="dot"></span>OWHS</a>
  <nav class="nav-links">
{nav}
  </nav>
</div></header>
<article><div class="wrap">
{body}
</div></article>
<footer class="owhs"><div class="wrap">
  <p>The text of this page is CC BY 4.0 and is generated from the files in the <a href="https://github.com/openworkplacehealth/OWHS">public repository</a>.
  It describes what is published; it is not part of the normative specification.</p>
</div></footer>
</body></html>
"""


def check_built(script, rels, label):
    """Regenerate with `script` into a temporary copy of site/, stamp the copy, and compare each page in rels with the committed one."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(ROOT / "site", tmp_site)
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
        for step in ([sys.executable, str(script)], [sys.executable, str(ROOT / "tools" / "stamp_canonical.py")]):
            r = subprocess.run(step, env=env, capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"[check] {Path(step[-1]).name} failed:\n" + r.stdout + r.stderr)
        stale = [rel for rel in rels if not (ROOT / "site" / rel).exists() or not filecmp.cmp(tmp_site / rel, ROOT / "site" / rel, shallow=False)]
        if stale:
            sys.exit(f"{label} do not match a fresh build; run {Path(script).name} then tools/stamp_canonical.py\n" + "".join(f"  differs: {s}\n" for s in stale))
    print(f"up to date: {label} match a fresh build ({', '.join(rels)})")


def self_test():
    page = shell("Test | OWHS", "A <test>", "<h1>x</h1>")
    ok = ('<title>Test | OWHS</title>' in page and 'content="A &lt;test&gt;"' in page and page.count("</div></footer>") == 1
          and all(f'href="{h}"' in page for h, _ in NAV) and 'name="robots"' in page)
    if not ok:
        print("self-test FAILED: the shell is missing a title, an escaped description, the one footer end the stamp tool needs, the navigation or a robots meta"); sys.exit(1)
    print("self-test ok: shell carries title, escaped description, navigation, robots meta and one footer end")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(__doc__)
