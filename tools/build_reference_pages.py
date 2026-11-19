#!/usr/bin/env python3
"""The two human reference pages for the machine-readable parts of the standard, generated from the files themselves:

    site/schemas/index.html     every JSON Schema, from schemas/catalogue.json and each schema's own title and description,
                                with its identifier, the raw JSON and the specification section that defines it
    site/codelists/index.html   every code list, from codelists/_registry.json and each list's own values, with its version,
                                its anchor source, the raw JSON and the archived versions

Why the schemas page is a real file at site/schemas/index.html. vercel.json rewrites /schemas/:path* to /spec/schemas/:path* so each
schema's $id (https://openworkplacehealth.org/schemas/v0.2/Organisation.json) resolves to raw JSON. A rewrite also caught the bare
/schemas/ path and sent it to a directory with no index, so it returned 404. Vercel serves a file that exists before it applies a
rewrite, so a real index.html under site/schemas/ answers /schemas/ and leaves every $id path to the rewrite, byte for byte as before.
The one extra rewrite (/schemas to /schemas/index.html, listed first) covers the form without the trailing slash. The self-test applies
that rule to every $id and to the bare paths and fails if an identifier would no longer reach its schema file.

    python tools/build_reference_pages.py            write both pages
    python tools/build_reference_pages.py --check    regenerate into a temporary copy of site/, stamp it, compare; exit 1 on drift
    python tools/build_reference_pages.py --self-test
"""
import filecmp, html, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))
ID_BASE = "https://openworkplacehealth.org/"

# Where each entity schema is defined in the specification. Read from the rendered page's own heading identifiers, so a renamed
# heading fails the build instead of leaving a dead link.
SPEC_PAGE = ROOT / "site" / "spec" / "index.html"

CSS = """
:root{--ink:#101418;--body:#33393f;--muted:#5c646c;--line:#e3e6e9;--accent:#0b6e5f;--accent-soft:#e6f2f0;--paper:#ffffff;--wash:#f6f7f8;--mono:'IBM Plex Mono',monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;color:var(--body);background:var(--paper);line-height:1.7;font-size:16.5px}
.wrap{max-width:980px;margin:0 auto;padding:0 24px 30px}
a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}
a:hover{color:var(--ink)}
h1,h2,h3{color:var(--ink);line-height:1.25}
h1{font-size:clamp(26px,4.5vw,38px);font-weight:700;letter-spacing:-0.02em;margin:8px 0 10px}
h2{font-size:21px;font-weight:700;margin:36px 0 12px}
h3{font-size:16px;font-weight:600;margin:22px 0 6px}
p,li{margin:12px 0;overflow-wrap:anywhere}ul{padding-left:20px;max-width:760px}
.lede{font-size:18.5px;max-width:760px;margin:8px 0 18px}
.meta{font-family:var(--mono);font-size:12.5px;color:var(--muted);overflow-wrap:anywhere}
.status-chip{display:inline-flex;gap:8px;font-family:var(--mono);font-size:12.5px;color:var(--accent);background:var(--accent-soft);padding:5px 12px;border-radius:4px;margin-bottom:16px;flex-wrap:wrap}
.callout{background:var(--wash);border-left:4px solid var(--accent);padding:14px 18px;margin:16px 0;max-width:780px;overflow-wrap:anywhere}
.tblwrap{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:8px}
table.ref{border-collapse:collapse;width:100%;font-size:14px;min-width:640px}
table.ref th{text-align:left;background:var(--wash);padding:8px 10px;border-bottom:2px solid var(--ink);font-size:12.5px;color:var(--ink)}
table.ref td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
table.ref td.id{font-family:var(--mono);font-size:12px;min-width:220px}
table.ref td.code{font-family:var(--mono);font-size:12.5px;white-space:nowrap}
details{border:1px solid var(--line);border-radius:8px;padding:6px 16px;margin:12px 0}
details summary{cursor:pointer;font-weight:600;color:var(--ink);padding:6px 0}
details[open] summary{margin-bottom:6px}
code{font-family:var(--mono);font-size:12.5px;background:var(--wash);padding:0 4px;overflow-wrap:anywhere}
header.owhs{border-bottom:1px solid var(--line);padding:18px 0}
.navbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;max-width:1160px;margin:0 auto;padding:0 24px}
.mark{font-weight:700;font-size:18px;color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:10px}
.mark .dot{width:12px;height:12px;border-radius:50%;background:var(--accent);display:inline-block}
.nav-links{display:flex;gap:6px 20px;font-size:15px;flex-wrap:wrap}
.nav-links a{text-decoration:none;color:var(--body)}
.nav-links a:hover{color:var(--accent)}
article{padding:40px 0 20px}
footer.owhs{border-top:1px solid var(--line);padding:28px 0 52px;font-size:14px;color:var(--muted)}
footer.owhs p{max-width:800px}
@media (max-width:640px){ body{font-size:15.5px} .wrap{padding:0 16px 24px} .navbar{padding:0 16px} }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def shell(title, desc, body):
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header class="owhs"><div class="navbar">
  <a class="mark" href="../index.html"><span class="dot"></span>OWHS</a>
  <nav class="nav-links">
    <a href="../index.html">Home</a>
    <a href="../why.html">The case</a>
    <a href="../how-it-works.html">How it works</a>
    <a href="../standard.html">Inside the standard</a>
    <a href="../question-bank/index.html">Question bank</a>
    <a href="../instrument-registry/index.html">Instrument registry</a>
    <a href="../methods.html">How we grade</a>
    <a href="../governance.html">Governance</a>
    <a href="../changelog.html">Changelog</a>
    <a href="../search.html">Search</a>
  </nav>
</div></header>
<article><div class="wrap">
{body}
</div></article>
<footer class="owhs"><div class="wrap">
  <p>The schemas and code lists listed here are licensed under Apache 2.0; the text of this page is CC BY 4.0. Both are generated from the files in the
  <a href="https://github.com/openworkplacehealth/OWHS">public repository</a>. This page lists what is published. It is not part of the normative specification,
  and conformance is defined in the <a href="../spec/index.html#conformance-levels">specification</a>.</p>
</div></footer>
</body></html>
"""


def one_line(text, limit=260):
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    first = re.split(r"(?<=[.;])\s", t)[0]
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + " ..."


def spec_anchors():
    """Heading identifiers in the rendered specification page, in order."""
    return re.findall(r'<h[1-6] id="([^"]+)"', SPEC_PAGE.read_text(encoding="utf-8"))


def anchor_for(entity, anchors):
    """The heading that introduces an entity's field table: its lower-cased name, optionally followed by '-new-in-v0.2'."""
    low = entity.lower()
    for a in anchors:
        if a == low or a.startswith(low + "-new-in"):
            return a
    return None


def read_json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def schema_rows():
    """Sections of (heading, intro, rows) for the schemas page; a row is (name, description, id, raw_path, spec_href, spec_label)."""
    cat = read_json("schemas/catalogue.json")
    anchors = spec_anchors()
    sections = []
    for ver in sorted(cat["versions"], reverse=True):
        block = cat["versions"][ver]
        rows = []
        for name, e in block["entities"].items():
            s = read_json(e["file"])
            a = anchor_for(name, anchors) if ver == "0.2" else None
            if ver == "0.2" and not a:
                raise SystemExit(f"tool error: no heading in site/spec/index.html introduces {name}; the schemas page would link nowhere")
            href = f"../spec/index.html#{a}" if a else ("../spec/OWHS-v0.1-draft.html" if ver == "0.1" else "")
            rows.append((name, s.get("description", ""), s["$id"], "../spec/" + e["file"], href,
                         "field table in the specification" if ver == "0.2" else "archived v0.1 specification"))
        for name, e in (block.get("bundle_envelopes") or {}).items():
            s = read_json(e["file"])
            rows.append((name + " (bundle envelope)", s.get("description", "") or e.get("note", ""), s["$id"], "../spec/" + e["file"],
                         "../entity-graph-validation.html", "supplied-entity graph validation"))
        label = "current" if block["status"] == "current" else block["status"]
        sections.append((f"Version {ver} ({label})", block.get("note") if False else "", rows))
    extra = []
    for f in sorted((ROOT / "profiles").glob("*.schema.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        extra.append((f.stem.replace(".schema", ""), s.get("description", ""), s["$id"], "../profiles/" + f.name,
                      "../spec/index.html#the-profile-mechanism", "the profile mechanism"))
    if extra:
        sections.append(("Profile envelope", "", extra))
    ev = []
    for f in sorted((ROOT / "evidence").glob("*.schema.json")) or sorted((ROOT / "site" / "evidence").glob("*.schema.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        ev.append((f.stem.replace(".schema", ""), s.get("description", ""), s["$id"], "../evidence/" + f.name,
                   "../automation.html", "evidence maintenance"))
    if ev:
        sections.append(("Evidence-maintenance schemas", "These describe the artefacts of the evidence-maintenance tooling, not workplace-health records.", ev))
    return sections


def build_schemas():
    cat = read_json("schemas/catalogue.json")
    n = sum(len(b["entities"]) + len(b.get("bundle_envelopes") or {}) for b in cat["versions"].values())
    parts = [f'<span class="status-chip">JSON Schema Draft 2020-12 &middot; Apache 2.0</span>',
             "<h1>JSON Schemas</h1>",
             f'<p class="lede">Every JSON Schema the Open Workplace Health Standard publishes, listed from the schema files themselves: {n} entity and envelope schemas across v0.1 and v0.2, '
             "plus the profile envelope and the evidence-maintenance schemas. Each schema is published as raw JSON at the address in its <code>$id</code>.</p>",
             '<div class="callout">The specification defines what each entity means and how the schemas are used; these files are its machine-checkable form. '
             'Read <a href="../spec/index.html#json-schemas-and-validation">JSON Schemas and validation</a> in the specification, and the '
             '<a href="../standard.html">entity list</a> for a plain-language tour. The versioned catalogue is '
             '<a href="../spec/schemas/catalogue.json">schemas/catalogue.json</a>. The matching <a href="../codelists/index.html">code lists</a> have their own page.</div>']
    for heading, intro, rows in schema_rows():
        parts.append(f"<h2>{esc(heading)}</h2>")
        if intro:
            parts.append(f"<p>{esc(intro)}</p>")
        body = ""
        for name, desc, sid, raw, href, label in rows:
            spec = f'<a href="{esc(href)}">{esc(label)}</a>' if href else ""
            body += (f'<tr><td><b>{esc(name)}</b></td><td>{esc(one_line(desc))}</td>'
                     f'<td class="id">{esc(sid)}<br><a href="{esc(raw)}">raw JSON</a></td><td>{spec}</td></tr>')
        parts.append('<div class="tblwrap"><table class="ref"><thead><tr><th>Schema</th><th>What it says about itself</th><th>Identifier and raw JSON</th><th>Specification</th></tr></thead>'
                     f"<tbody>{body}</tbody></table></div>")
    return shell("JSON Schemas | OWHS", "Every JSON Schema the Open Workplace Health Standard publishes, with its identifier, the raw JSON, a one-line description taken from the schema and the specification section that defines it.",
                 "\n".join(parts))


def build_codelists():
    reg = read_json("codelists/_registry.json")
    total = sum(x["values"] for x in reg["lists"])
    parts = ['<span class="status-chip">Code lists &middot; versioned independently &middot; Apache 2.0</span>',
             "<h1>Code lists</h1>",
             f'<p class="lede">The {len(reg["lists"])} controlled vocabularies the schemas pin by name and version, {total} codes in all, listed from the files themselves. '
             "Each list is published as raw JSON; every released version of a list is kept.</p>",
             f'<div class="callout">{esc(reg["note"])} The specification\'s <a href="../spec/index.html#code-lists">code lists section</a> says which fields use which list. '
             'The <a href="../schemas/index.html">schemas</a> have their own page. The crosswalk files in <code>mappings/</code> map one list to an external classification; they are not code lists.</div>']
    toc = " &middot; ".join(f'<a href="#{esc(x["name"])}">{esc(x["name"])}</a>' for x in reg["lists"])
    parts.append(f'<p class="meta">{toc}</p>')
    for item in reg["lists"]:
        body = read_json("codelists/" + item["file"])
        cols = []
        for v in body["values"]:
            for k in v:
                if k not in ("code", "label") and k not in cols:
                    cols.append(k)
        head = "<th>Code</th><th>Label</th>" + ("<th>Other fields</th>" if cols else "")
        rows = ""
        for v in body["values"]:
            other = "; ".join(f"{k}: {v[k]}" for k in cols if k in v)
            rows += f'<tr><td class="code">{esc(v["code"])}</td><td>{esc(v.get("label", ""))}</td>' + (f"<td>{esc(other)}</td>" if cols else "") + "</tr>"
        older = [f'<a href="../spec/codelists/{esc(p)}">{esc(v)}</a>' for v, p in item["versions"].items() if p != item["file"]]
        meta = (f'<p class="meta">version {esc(item["version"])} &middot; {item["values"]} codes &middot; <a href="../spec/codelists/{esc(item["file"])}">raw JSON</a>'
                + (f' &middot; earlier versions kept: {", ".join(older)}' if older else "") + "</p>")
        anchor = f'<p>{esc(item["anchor"])}</p>' if item.get("anchor") else ""
        parts.append(f'<details id="{esc(item["name"])}"><summary>{esc(item["name"])} <span class="meta">v{esc(item["version"])}, {item["values"]} codes</span></summary>'
                     f'{anchor}{meta}<div class="tblwrap"><table class="ref"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></details>')
    return shell("Code lists | OWHS", f"The {len(reg['lists'])} controlled vocabularies of the Open Workplace Health Standard, {total} codes in all, each with its version, its source anchor, its codes and labels, and the raw JSON.",
                 "\n".join(parts))


def outputs():
    return {"schemas/index.html": build_schemas(), "codelists/index.html": build_codelists()}


def write(site=None):
    site = Path(site) if site else SITE_ROOT
    for rel, text in outputs().items():
        p = site / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    print("wrote site/schemas/index.html and site/codelists/index.html")


# --- the Vercel routing rule, applied locally -------------------------------------------------------------------------
def resolve(site, rewrites, path):
    """Where a request path ends up: a file that exists wins, a directory serves its index.html, otherwise the first matching
    rewrite is applied once. Returns the site-relative file path or None. This is the documented order (filesystem, then rewrites)."""
    def on_disk(p):
        f = site / p.lstrip("/")
        if f.is_file():
            return f
        if f.is_dir() and (f / "index.html").is_file():
            return f / "index.html"
        return None
    hit = on_disk(path)
    if hit:
        return hit.relative_to(site).as_posix()
    for r in rewrites:
        src, dest = r["source"], r["destination"]
        if src.endswith("/:path*"):
            base = src[:-len("/:path*")]
            if path in (base, base + "/"):
                rest = ""
            elif path.startswith(base + "/"):
                rest = path[len(base) + 1:]
            else:
                continue
            dest = dest.replace(":path*", rest)
        elif path not in (src, src + "/"):
            continue
        hit = on_disk(dest)
        return hit.relative_to(site).as_posix() if hit else None
    return None


def routing_problems(site=None):
    site = Path(site) if site else ROOT / "site"
    rewrites = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8")).get("rewrites", [])
    problems = []
    for rel in sorted(str(p.relative_to(ROOT)) for p in (ROOT / "schemas").rglob("*.json")):
        s = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        sid = s.get("$id", "")
        if not sid.startswith(ID_BASE + "schemas/"):
            continue
        path = "/" + sid[len(ID_BASE):]
        got = resolve(site, rewrites, path)
        if got is None:
            problems.append(f"{sid} resolves to nothing")
        elif (site / got).read_bytes() != (ROOT / rel).read_bytes():
            problems.append(f"{sid} resolves to {got}, which differs from {rel}")
    for path in ("/schemas/", "/schemas"):
        got = resolve(site, rewrites, path)
        if got != "schemas/index.html":
            problems.append(f"{path} resolves to {got!r}, not the schemas index")
    return problems


def check():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(ROOT / "site", tmp_site)
        for d in ("schemas", "codelists"):
            if (tmp_site / d).exists():
                shutil.rmtree(tmp_site / d)
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("[check] build failed:\n" + r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("[check] stamp failed:\n" + r.stdout + r.stderr)
        stale = [rel for rel in outputs() if not (ROOT / "site" / rel).exists() or not filecmp.cmp(tmp_site / rel, ROOT / "site" / rel, shallow=False)]
        if stale:
            sys.exit("the reference pages do not match a fresh build; run tools/build_reference_pages.py then tools/stamp_canonical.py\n" + "".join(f"  differs: {s}\n" for s in stale))
        bad = routing_problems()
        if bad:
            sys.exit("schema identifiers would not resolve:\n" + "".join(f"  {b}\n" for b in bad))
        print(f"up to date: site/schemas/ and site/codelists/ match a fresh build; every schema $id resolves to its file and /schemas/ to the index")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}")
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp)
        (site / "spec" / "schemas" / "v0.2").mkdir(parents=True)
        (site / "spec" / "schemas" / "v0.2" / "A.json").write_text("{}")
        (site / "schemas").mkdir()
        (site / "schemas" / "index.html").write_text("index")
        rw = [{"source": "/schemas", "destination": "/schemas/index.html"}, {"source": "/schemas/:path*", "destination": "/spec/schemas/:path*"}]
        t("an identifier path goes to the schema file", resolve(site, rw, "/schemas/v0.2/A.json") == "spec/schemas/v0.2/A.json", resolve(site, rw, "/schemas/v0.2/A.json"))
        t("the bare directory serves the index", resolve(site, rw, "/schemas/") == "schemas/index.html")
        t("without the trailing slash the index is still served", resolve(site, rw, "/schemas") == "schemas/index.html")
        t("a missing identifier resolves to nothing", resolve(site, rw, "/schemas/v0.2/Nope.json") is None)
        (site / "schemas" / "index.html").unlink(); (site / "schemas").rmdir()
        t("with only the original rewrite and no index the bare path was a 404 (the defect)", resolve(site, rw[1:], "/schemas/") is None)
    t("a long description is cut at its first sentence", one_line("A short one. " + "x " * 200) == "A short one.")
    t("a short description is kept whole", one_line("Whole sentence; with a clause.") == "Whole sentence; with a clause.")
    anchors = ["organisation-new-in-v0.2", "absenceepisode", "orgunit-new-in-v0.2"]
    t("an entity heading is found with or without the new-in suffix", anchor_for("Organisation", anchors) == "organisation-new-in-v0.2" and anchor_for("AbsenceEpisode", anchors) == "absenceepisode")
    t("an unknown entity has no anchor", anchor_for("Nope", anchors) is None)
    bad = routing_problems()
    t("every schema $id in the repository resolves to its file on the real site", not bad, "; ".join(bad[:3]))
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("self-test ok: 10 cases (the rewrite rule applied to every $id and to the bare paths, description cutting, spec anchors)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--self-test" in sys.argv:
        self_test()
    else:
        write()
