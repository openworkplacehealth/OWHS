#!/usr/bin/env python3
"""Stamp a <link rel="canonical"> on every HTML page under site/, keyed to its path, plus the favicon link and
the Open Graph / Twitter card tags (derived from each page's own <title> and description, never new copy), and apply the
robots policy: the one word in ../robots-policy.txt (noindex | index) decides the robots meta on every page.
The generators always emit noindex; this tool is what makes a build match the published posture, so a
rebuild after the lift cannot quietly put noindex back. Also places the one managed footer line (trade mark
and licence) as the last element of every page footer, so every generator shares it. Idempotent. Run before any deploy."""
import re, sys, pathlib
BASE = "https://openworkplacehealth.org/"
ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
POLICY = (ROOT / "robots-policy.txt").read_text(encoding="utf-8").strip().lower() if (ROOT / "robots-policy.txt").exists() else "noindex"
if POLICY not in ("noindex", "index"):
    sys.exit(f"robots-policy.txt must say noindex or index, not {POLICY!r}")
ROBOTS = '<meta name="robots" content="noindex, nofollow">' if POLICY == "noindex" else '<meta name="robots" content="index, follow">'
MARK = ('<!-- mark --><p class="tm" style="margin-top:12px;font-size:13px;color:var(--muted,#5c646c)">OWHS\u2122 is a trade mark of '
        'All Toogether Ltd (UK application pending). The specification and registry are CC-BY 4.0.</p><!-- /mark -->')

def footer_mark(t):
    """One managed line at the end of the first footer; rebuilt on every run, added where absent."""
    if "<!-- mark -->" in t:
        return re.sub(r"<!-- mark -->.*?<!-- /mark -->", lambda m: MARK, t, count=1, flags=re.S)
    if "</div></footer>" in t:
        return t.replace("</div></footer>", MARK + "\n</div></footer>", 1)
    return t

n = 0
for p in sorted(SITE.rglob("*.html")):
    rel = p.relative_to(SITE).as_posix()
    if rel == "404.html":
        orig = p.read_text(encoding="utf-8"); t2 = footer_mark(orig)   # always noindex, never canonical; footer line only
        if t2 != orig:
            p.write_text(t2, encoding="utf-8"); n += 1
        continue
    url = BASE + ("" if rel == "index.html" else rel[:-len("index.html")] if rel.endswith("/index.html") else rel)
    tag = f'<link rel="canonical" href="{url}">'
    orig = p.read_text(encoding="utf-8")
    t = re.sub(r'<meta name="robots" content="[^"]*">', ROBOTS, orig, count=1)
    if 'rel="canonical"' in t:
        t2 = re.sub(r'<link rel="canonical" href="[^"]*">', tag, t, count=1)
    elif '<meta name="robots"' in t:
        t2 = re.sub(r'(<meta name="robots"[^>]*>)', r'\1\n' + tag, t, count=1)
    else:
        print("no robots meta, skipped:", rel, file=sys.stderr); continue
    # favicon + social cards: one managed block after the canonical, rebuilt on every run from the page's own title/description
    title = re.search(r"<title>(.*?)</title>", t2, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', t2)
    block = ['<!-- auto -->', '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
             '<meta property="og:type" content="website">', '<meta property="og:site_name" content="Open Workplace Health Standard">',
             f'<meta property="og:url" content="{url}">']
    if title: block.append(f'<meta property="og:title" content="{" ".join(title.group(1).split())}">')
    if desc: block.append(f'<meta property="og:description" content="{desc.group(1)}">')
    block += ['<meta name="twitter:card" content="summary">', '<!-- /auto -->']
    block = "\n".join(block)
    if "<!-- auto -->" in t2:
        t2 = re.sub(r"<!-- auto -->.*?<!-- /auto -->", lambda m: block, t2, count=1, flags=re.S)
    else:
        t2 = t2.replace(tag, tag + "\n" + block, 1)
    t2 = footer_mark(t2)
    if t2 != orig:
        p.write_text(t2, encoding="utf-8"); n += 1
print(f"canonical stamped or refreshed on {n} pages; robots policy {POLICY} applied")
