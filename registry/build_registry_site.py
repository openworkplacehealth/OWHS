#!/usr/bin/env python3
"""Generate the OWHS Instrument Registry site section from the canonical dataset.

Source of truth: DATASET below (31 records: 27 instruments, 4 ONS-4 item records),
schema 0.7 (rubric 1.6; three-value indirectness flag with population-naming basis; absence_type on ungraded cells; population-tagged precondition_evidence on High cells, archived in previous; relations between records). Static HTML, no JS for content, OWHS house style. Robots posture, canonical links, footer line and visit counting are applied afterwards by tools/stamp_canonical.py, never here.
A build-time neutrality gate fails the build if internal framing or vendor names
appear in output. External links open in a new tab; internal navigation does not.
"""
import html, json, re
from pathlib import Path

import os, sys
HERE = Path(__file__).resolve().parent            # registry/: the dataset versions, rubrics, admission policy, gate
ROOT = HERE.parent                                 # repository root
SITE_ROOT = Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))   # overridable so --check can build into a copy
SITE = SITE_ROOT / "instrument-registry"
SITE.mkdir(parents=True, exist_ok=True)
DATASET = "instrument-evidence-base-v0.9.0.json"
PREVIOUS = ["instrument-evidence-base-v0.8.0.json", "instrument-evidence-base-v0.7.0.json", "instrument-evidence-base-v0.6.0.json", "instrument-evidence-base-v0.5.0.json", "instrument-evidence-base-v0.4.0.json", "instrument-evidence-base-v0.3.0.json", "instrument-evidence-base-v0.2.2.json"]   # kept at stable URLs for citation
RUBRIC_MD = HERE / "RUBRIC-v1.6.md"
ADMISSION_MD = HERE / "ADMISSION-v1.1.md"
D = json.loads((HERE / DATASET).read_text(encoding="utf-8"))
RATER = D.get("rater_disclosure", {})
LIC_CLASSES = D.get("licence_classes", {})
LIC_LABEL = {"open": "open licence", "free-no-permission": "free, no permission needed",
             "free-non-commercial": "free for non-commercial use only", "free-with-registration": "free with registration",
             "fee-bearing": "fee-bearing", "no-formal-licence": "no formal licence", "unverified": "licence unverified"}
RECORDS = D["records"]
BY_ID = {r["instrument_id"]: r for r in RECORDS}
PARENTS = [r for r in RECORDS if not r.get("parent_id")]
# Counting rule (2 Sep 2026, E11): graded and watchlist instruments are counted separately, never summed.
# A parent is on the watchlist when every property is still not_assessed; none is in this version.
def _on_watchlist(r):
    props = [v for v in r.values() if isinstance(v, dict) and "evidence_state" in v]
    return bool(props) and all(p.get("evidence_state") == "not_assessed" for p in props)
WATCHLIST = [r for r in PARENTS if _on_watchlist(r)]
GRADED = [r for r in PARENTS if not _on_watchlist(r)]
# Organisational criterion validity, counted live so the founding finding stays true as instruments are added (2 Sep 2026).
def _org_grade(r):
    return (r.get("criterion_validity_organisational") or {}).get("grade", "Absent")
ORG_ABSENT = sum(1 for r in GRADED if _org_grade(r) == "Absent")
ORG_THIN = sum(1 for r in GRADED if _org_grade(r) in ("Very low", "Low"))
REVIEW_DATE = D.get("generated", "2026-07-12")
CONFIRMED = "2026-09-03"   # grade_last_confirmed across the dataset (rubric 1.6 re-read before first publication)
FROZEN = str(RATER.get("frozen_since", "from first publication"))
FROZEN_PHRASE = f"frozen {FROZEN}" if FROZEN.startswith("from") else f"frozen since {FROZEN}"

# Purpose statement (adopted 2 Sep 2026). Rendered on the index, the how-to-read page and the README.
PURPOSE = ("<b>The instrument registry is the open synthesis of the published evidence on instruments used to measure "
           "workplace health and wellbeing.</b> For every instrument it records what it measures, how well, in which populations "
           "and languages, and on what licence terms, drawn from the literature and existing systematic reviews, every claim cited, "
           "every grade conservative. It is maintained, machine-readable and free to use, so that nobody choosing, building, "
           "licensing or reviewing a workplace measure has to reassemble the field's evidence themselves.")
SYNTHESIS_EDGE = ("<b>Synthesis, not systematic review.</b> A synthesis here means reading across the published studies and reviews "
                  "and stating what they show, including where they disagree. The registry does not run its own meta-analyses and its "
                  "searches are not conducted to systematic-review standard. Where a COSMIN review exists for an instrument, the registry "
                  "cites and summarises it; where none exists, the registry says so and grades what is there. The search venues and strings "
                  "the sweep runs are published, so the coverage can be checked and improved by anyone.")

# Relations (schema 0.4, corresponds-with added in 0.5): recorded forward only on the source record; the inverse is computed here.
REL_LABEL = {"item-of": "item of", "short-form-of": "short form of", "screens-for": "screens for", "embeds": "embeds",
             "corresponds-with": "corresponds with"}
REL_INVERSE = {"item-of": "has item", "short-form-of": "has short form", "screens-for": "screened for by", "embeds": "embedded in",
               "corresponds-with": "corresponded with by"}
def relations_of(rec):
    """(label, target_id or None, target_text, evidence, note) for forward and inverse relations of a record."""
    out = []
    for rel in rec.get("relations") or []:
        tid = rel.get("target")
        out.append((REL_LABEL.get(rel["type"], rel["type"]), tid,
                    BY_ID[tid]["display_name"] if tid else rel.get("target_external", ""), rel.get("evidence", ""), rel.get("note")))
    for other in RECORDS:
        for rel in other.get("relations") or []:
            if rel.get("target") == rec["instrument_id"]:
                out.append((REL_INVERSE.get(rel["type"], rel["type"]), other["instrument_id"], other["display_name"], rel.get("evidence", ""), rel.get("note")))
    return out
SINGLE_ITEMS = [r for r in PARENTS if r["instrument_type"] == "single-item"]

def size_class(rec):
    """Item-count band for the matrix filter (a filter, never a sort)."""
    if rec["instrument_type"] == "single-item": return "n-single"
    if rec["instrument_type"] == "item-set": return "n-set"
    m = re.match(r"^(\d+)", str(rec["identity"].get("item_count") or "").strip())
    if not m: return "n-set"
    return "n-short" if int(m.group(1)) <= 10 else "n-long"

QB = json.loads((SITE_ROOT / "question-bank" / "question-bank.json").read_text(encoding="utf-8"))
QB_ITEMS = QB["items"]
# registry instrument -> question bank source keys
SRC_MAP = {"who-5": ["WHO5"], "csps-wellbeing": ["CSPS"], "eurofound-ewcs": ["EWCS6", "EQLS4"],
           "fcs-maps": ["FINCAP"], "perma": ["PERMA"]}
def bank_links_for(rid):
    rec = BY_ID[rid]
    if rec.get("question_bank_ref"):
        ref = rec["question_bank_ref"]
        it = next((i for i in QB_ITEMS if i["id"] == ref["item_id"]), None)
        return [(it["id"], it["topic"], it["group"])] if it else []
    keys = SRC_MAP.get(rid, [])
    return [(i["id"], i["topic"], i["group"]) for i in QB_ITEMS if i["source_key"] in keys]

PROPS = [
    ("structural_validity", "Structural validity"),
    ("convergent_discriminant_validity", "Convergent and discriminant validity"),
    ("criterion_validity_reference_standard", "Criterion validity: reference standard"),
    ("criterion_validity_organisational", "Criterion validity: organisational"),
    ("internal_consistency", "Internal consistency"),
    ("test_retest_reliability", "Test-retest reliability"),
    ("measurement_invariance", "Measurement invariance"),
    ("responsiveness_mic", "Responsiveness and MIC"),
]
MATRIX_COLS = [("structural_validity", "Structural"), ("convergent_discriminant_validity", "Convergent"),
               ("criterion_validity_reference_standard", "Criterion: reference"),
               ("criterion_validity_organisational", "Criterion: organisational"),
               ("internal_consistency", "Internal consistency"), ("test_retest_reliability", "Test-retest"),
               ("measurement_invariance", "Invariance"), ("responsiveness_mic", "Responsiveness")]

def neutral_voice(t):
    """Presentation-level voice normalization for public pages.

    The dataset prose was written as a research log (first-person voice,
    'this session'). The dataset stays verbatim; pages render in neutral
    registry voice. The first-person pattern requires a following lowercase
    word so author initials ('Schonfeld I.'), 'Part I:', 'I-squared' and
    title-case quotes ('How Am I Doing?') are never touched.
    """
    t = re.sub(r"([.;:] )I (?=[a-z])", r"\1The maintainers ", t)
    t = re.sub(r"^I (?=[a-z])", "The maintainers ", t)
    t = re.sub(r"\bI (?=[a-z])", "the maintainers ", t)
    t = t.replace("the maintainers was ", "the maintainers were ")
    t = t.replace("The maintainers was ", "The maintainers were ")
    t = t.replace(" this session", " in the latest review pass")
    return t

def esc(s):
    s = neutral_voice(str(s if s is not None else ""))
    s = html.escape(s, quote=False)
    return s.replace(chr(8211), "-").replace(chr(8212), "-")

def md(s):
    """Escape then convert [text](url) markdown links."""
    s = esc(s)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)

GRADE_CLASS = {"High": "g-high", "Moderate": "g-mod", "Low": "g-low", "Very low": "g-vlow",
               "Absent": "g-absent", "Not-applicable": "g-na"}
def grade_cell(prop):
    g = prop.get("grade")
    state = prop.get("evidence_state")
    if state == "not_assessed" or (g is None and state != "not_applicable"):
        return '<td class="g-unassessed"><span role="img" aria-label="Not yet assessed: a gap in the registry, not a finding about the literature">not assessed</span></td>'
    cls = GRADE_CLASS.get(g, "g-low")
    if g == "Not-applicable":
        return f'<td class="{cls}"><span role="img" aria-label="Not applicable: a category difference, not a gap">n/a</span></td>'
    if g == "Absent":
        return f'<td class="{cls}"><span role="img" aria-label="{esc(ABSENCE_LONG.get(prop.get("absence_type"), ABSENCE_LONG["population-general"]))}">Absent</span></td>'
    st = prop.get("status") or ""
    mark = {"contested": " *", "thin": " ~"}.get(st, "")
    due = ' <span class="due" title="citation added since the grade was last confirmed; review due">&#9679;</span>' if prop.get("review_due") else ""
    return f'<td class="{cls}"><span aria-label="grade {esc(g)}, status {esc(st)}">{esc(g)}{mark}</span>{due}</td>'

def grade_chip(prop):
    g = prop.get("grade"); cls = GRADE_CLASS.get(g, "g-low")
    if prop.get("evidence_state") == "not_assessed" or g is None:
        return '<span class="grade g-unassessed">Not yet assessed</span>'
    label = {"Not-applicable": "Not applicable (category difference)",
             "Absent": "Absent (" + ABSENCE_SHORT.get(prop.get("absence_type"), "searched; none found in the sweep to date") + ")"}.get(g, g)
    return f'<span class="grade {cls}">{esc(label)}</span>'

def status_chip(st):
    if not st: return ""
    cls = {"well-established": "st-well", "contested": "st-contested", "thin": "st-thin", "untested": "st-untested"}.get(st, "st-thin")
    return f'<span class="stat {cls}">{esc(st)}</span>'

def ef_chip(ef):
    return f'<span class="ef">evidence form: {esc(ef)}</span>' if ef else ""

# Absence types (schema 0.6 R4, unchanged at 0.7): every Absent or Not-applicable cell says why nothing is graded. Two values from 0.6:
# evidence that exists only in other populations is graded indirect, never recorded as Absent.
ABSENCE_SHORT = {"population-general": "searched; none found in the sweep to date",
                 "category-error": "the property does not apply to this construct"}
ABSENCE_LONG = {"population-general": "Absent: searched for, none found in the sweep to date, a finding about the literature",
                "category-error": "Absent: the property does not apply to this construct"}

def ind_head(ind):
    """Three-value indirectness flag (rubric 1.2 onward): direct / general / indirect, or None."""
    low = str(ind or "").strip().lower()
    for h in ("indirect", "direct", "general"):
        if low.startswith(h): return h
    return None

def ind_chip(ind, basis=None):
    if not ind: return ""
    t = str(ind).strip()
    head = ind_head(t)
    note = t[len(head):].lstrip(";, ") if head else t
    out = f'<span class="ind ind-{head or "note"}">{esc(head or "indirectness")}</span>'
    if note: out += f' <span class="indnote">{esc(note)}</span>'
    if basis:
        out += ' <span class="indnote">(flag basis: ' + esc("; ".join(basis) if isinstance(basis, list) else str(basis)) + ')</span>'
    return out

CSS = """
:root{--ink:#101418;--body:#33393f;--muted:#5c646c;--line:#e3e6e9;--accent:#0b6e5f;--accent-soft:#e6f2f0;--paper:#ffffff;--wash:#f6f7f8;--mono:'IBM Plex Mono',monospace;--amber:#8a6d1f;--amber-soft:#f4f0e6;--red:#8a2b2b;--red-soft:#f6ecec}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;color:var(--body);background:var(--paper);line-height:1.7;font-size:16.5px}
.wrap{max-width:880px;margin:0 auto;padding:0 24px 30px}
a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}
a:hover{color:var(--ink)}
h1,h2,h3{color:var(--ink);line-height:1.25}
h1{font-size:clamp(26px,4.5vw,38px);font-weight:700;letter-spacing:-0.02em;margin:8px 0 10px}
h2{font-size:21px;font-weight:700;margin:36px 0 12px}
h3{font-size:16px;font-weight:600;margin:20px 0 6px}
p,li{margin:12px 0}ul,ol{padding-left:20px;max-width:760px}
.lede{font-size:18.5px;color:var(--body);margin:8px 0 18px;max-width:760px}
.meta{font-family:var(--mono);font-size:12.5px;color:var(--muted);overflow-wrap:anywhere}
a{overflow-wrap:anywhere}
p,li,td,.findings,.licok,.licbad,.callout{overflow-wrap:anywhere}
.status-chip{display:inline-flex;gap:8px;font-family:var(--mono);font-size:12.5px;color:var(--accent);background:var(--accent-soft);padding:5px 12px;border-radius:4px;margin-bottom:16px}
.callout{background:var(--wash);border-left:4px solid var(--accent);padding:14px 18px;margin:16px 0;max-width:780px}
.caveat{background:var(--amber-soft);border-left:4px solid var(--amber);padding:14px 18px;margin:16px 0;max-width:780px}
.caveat b{color:var(--amber)}
.licbad{background:var(--amber-soft);border-left:4px solid var(--amber);padding:12px 16px;margin:12px 0;max-width:780px;font-size:14.5px}
.licok{background:var(--accent-soft);border-left:4px solid var(--accent);padding:12px 16px;margin:12px 0;max-width:780px;font-size:14.5px}
.grade{display:inline-block;font-family:var(--mono);font-size:12px;font-weight:600;border-radius:4px;padding:2px 9px;vertical-align:middle}
.g-high{background:#dff0e9;color:#0b5c46}.g-mod{background:#e6efdb;color:#4a6318}
.g-low{background:#f4f0e6;color:#8a6d1f}.g-vlow{background:#f6ecec;color:#8a2b2b}
.g-absent{background:#f0e6e6;color:#7a1f1f}.g-na{background:#eef0f2;color:#5c646c}
.g-unassessed{background:#ffffff;color:#8a93a0;border:1px dashed #b8c0c8}
td.g-unassessed{background:repeating-linear-gradient(45deg,#fafbfc,#fafbfc 4px,#f0f2f4 4px,#f0f2f4 8px);color:#8a93a0;font-style:italic}
.due{color:var(--amber);font-size:9px;vertical-align:middle}
.cellmeta{font-family:var(--mono);font-size:11px;color:var(--muted);margin:2px 0 6px}
.cellmeta .rd{color:var(--amber);font-weight:600}
.freeze{background:#fbf7ea;border:1px solid #e6d9a8;border-radius:8px;padding:12px 16px;margin:14px 0 18px;font-size:14px;max-width:820px}
.freeze b{color:var(--amber)}
.verdict{border:2px solid var(--ink);border-radius:10px;padding:18px 22px;margin:18px 0 26px;max-width:820px;background:var(--paper)}
.verdict h2{margin:0 0 8px;font-size:17px;text-transform:uppercase;letter-spacing:.06em}
.verdict p{margin:8px 0;font-size:16px;color:var(--ink)}
.verdict .facts,.si .facts{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 6px}
.verdict .chip,.si .chip{font-family:var(--mono);font-size:11.5px;background:var(--wash);border:1px solid var(--line);border-radius:4px;padding:3px 8px}
.verdict .chip.c-high,.si .chip.c-high{background:#dff0e9;color:#0b5c46}.verdict .chip.c-mod,.si .chip.c-mod{background:#e6efdb;color:#4a6318}
.verdict .chip.c-low,.si .chip.c-low{background:#f4f0e6;color:#8a6d1f}.verdict .chip.c-vlow,.si .chip.c-vlow{background:#f6ecec;color:#8a2b2b}
.verdict .chip.c-absent,.si .chip.c-absent{background:#f0e6e6;color:#7a1f1f}.verdict .chip.c-na,.si .chip.c-na{color:#8a93a0}
.verdict .chip.c-lic{background:var(--accent-soft);color:var(--accent)}
.si .facts{margin-top:4px}
.verdict .caveat-line{font-size:13.5px;color:var(--muted);margin-top:10px}
.licclass{display:inline-block;font-family:var(--mono);font-size:11.5px;border-radius:4px;padding:2px 8px;background:var(--paper);border:1px solid var(--line);margin-right:6px}
.rubric h2{margin-top:30px}.rubric table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}
.rubric th,.rubric td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
.rubric th{background:var(--wash)}.rubric code{font-family:var(--mono);font-size:12.5px;background:var(--wash);padding:0 4px}
.rubric .tblwrap{overflow-x:auto}
.stat{display:inline-block;font-family:var(--mono);font-size:11px;border-radius:999px;padding:2px 9px;margin-left:6px;vertical-align:middle}
.st-well{background:var(--accent-soft);color:var(--accent)}
.st-contested{background:#7a1f1f;color:#ffffff;font-weight:700}
.st-thin{background:var(--amber-soft);color:var(--amber)}
.st-untested{background:#eef0f2;color:var(--muted)}
.ef{display:inline-block;font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:8px}
.ind{display:inline-block;font-family:var(--mono);font-size:11px;border-radius:4px;padding:1px 7px;margin-left:6px}
.ind-direct{background:var(--accent-soft);color:var(--accent)}
.ind-indirect{background:var(--amber-soft);color:var(--amber)}
.ind-general{background:#e9eef6;color:#2f5480}
.purpose{max-width:760px;font-size:17px;border-left:3px solid var(--accent);padding:4px 0 4px 16px;margin:6px 0 18px}
.rels{max-width:800px}.rels li{margin:8px 0}.relnote{color:var(--muted);font-size:14.5px}
.filter{margin:6px 0 0}.filterlabel{font-family:var(--mono);font-size:12.5px;color:var(--muted);margin-right:6px}
.filter>input{position:absolute;opacity:0;width:0;height:0}
.filter>label{display:inline-block;font-size:13px;padding:3px 10px;border:1px solid var(--line);border-radius:999px;margin:0 4px 6px 0;cursor:pointer;color:var(--body)}
.filter>input:checked+label{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);font-weight:600}
.filter>input:focus-visible+label{outline:2px solid var(--accent);outline-offset:2px}
#f-single:checked~.matrixwrap tbody tr:not(.n-single){display:none}
#f-short:checked~.matrixwrap tbody tr:not(.n-short){display:none}
#f-long:checked~.matrixwrap tbody tr:not(.n-long){display:none}
#f-set:checked~.matrixwrap tbody tr:not(.n-set){display:none}
.si{border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:14px 0;max-width:820px}
.si h3{margin-top:0}
.ind-note{background:#eef0f2;color:var(--muted)}
.indnote{font-size:12.5px;color:var(--muted)}
.prop{border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:14px 0}
.prop h3{margin:2px 0 8px}
.findings{font-size:14.5px;max-width:780px}
.matrixwrap{overflow-x:auto;margin:18px 0;border:1px solid var(--line);border-radius:8px}
table.matrix{border-collapse:collapse;font-size:12.5px;min-width:980px;width:100%}
table.matrix th{position:sticky;top:0;background:var(--wash);text-align:left;padding:8px 9px;border-bottom:2px solid var(--ink);font-size:11.5px;color:var(--ink)}
table.matrix td{padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap;font-family:var(--mono);font-size:11.5px}
table.matrix td:first-child{position:sticky;left:0;background:var(--paper);white-space:normal;min-width:170px;font-family:'Inter',sans-serif;font-size:13px}
table.matrix th:first-child{position:sticky;left:0;z-index:2;background:var(--wash)}
td.g-high{background:#dff0e9;color:#0b5c46}td.g-mod{background:#e6efdb;color:#4a6318}
td.g-low{background:#f4f0e6;color:#8a6d1f}td.g-vlow{background:#f6ecec;color:#8a2b2b}
td.g-absent{background:#f0e6e6;color:#7a1f1f;font-weight:600}
td.g-na{background:#eef0f2;color:#8a93a0;font-style:italic}
.legend{font-size:12.5px;color:var(--muted);max-width:820px;margin:10px 0}
.trwrap{overflow-x:auto;margin:10px 0;max-width:780px}
table.tr{border-collapse:collapse;width:100%;font-size:13px;min-width:520px}
table.tr th{text-align:left;padding:7px 9px;border-bottom:2px solid var(--ink);font-size:11.5px;color:var(--ink)}
table.tr td{padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
.refs{font-size:13px;color:var(--muted);max-width:800px}
.refs li{margin:6px 0}
.idgrid{font-size:14px;max-width:780px}
.idgrid b{color:var(--ink)}
header.owhs{border-bottom:1px solid var(--line);padding:18px 0}
.navbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;max-width:1160px;margin:0 auto;padding:0 24px}
.mark{font-weight:700;font-size:18px;color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:10px}
.mark .dot{width:12px;height:12px;border-radius:50%;background:var(--accent);display:inline-block}
.nav-links{display:flex;gap:20px;font-size:15px;flex-wrap:wrap}
.nav-links a{text-decoration:none;color:var(--body)}
.nav-links a:hover{color:var(--accent)}
.nav-links a.here{color:var(--accent);font-weight:600}
article{padding:40px 0 20px}
footer.owhs{border-top:1px solid var(--line);padding:28px 0 52px;font-size:14px;color:var(--muted)}
footer.owhs p{max-width:800px}
.subnav{border-bottom:1px solid var(--line);background:var(--wash)}
.subnav .wrap{padding:9px 24px;display:flex;gap:18px;flex-wrap:wrap;font-size:14px}
.subnav a{color:var(--muted);text-decoration:none}
.subnav a:hover,.subnav a.here{color:var(--accent);font-weight:600}
.banklink{background:var(--accent-soft);border-radius:6px;padding:10px 14px;font-size:14px;max-width:780px;margin:12px 0}
@media (max-width:640px){ body{font-size:15.5px} .wrap{padding:0 16px 24px} }
"""

def page(title, body, desc="", here=""):
    def lk(href, label, key):
        cls = ' class="here"' if key == here else ''
        return f'<a href="{href}"{cls}>{label}</a>'
    sub = "".join([lk("index.html", "Overview", "index"),
                   lk("how-to-read.html", "How to read this registry", "how"),
                   lk("single-items.html", "Single-item measures", "single"),
                   lk("admission.html", "How an instrument enters", "admission"),
                   lk("rubric.html", "Grading rubric v" + esc(D.get("rubric", {}).get("version", "1.0")), "rubric"),
                   lk("corrections.html", "Corrections, errata and right of reply", "corrections"),
                   lk("downloads.html", "Downloads", "downloads")])
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
    <a href="index.html" class="here">Instrument registry</a>
    <a href="../methods.html">How we grade</a>
    <a href="../governance.html">Governance</a>
    <a href="../changelog.html">Changelog</a>
    <a href="../search.html">Search</a>
  </nav>
</div></header>
<div class="subnav"><div class="wrap">{sub}</div></div>
<article><div class="wrap">
{body}
</div></article>
<footer class="owhs"><div class="wrap">
  <p>OWHS Instrument Registry, dataset version {esc(D['version'])} (schema {esc(D.get('schema_version',''))}), generated {esc(REVIEW_DATE)};
  grades last confirmed {esc(CONFIRMED)} under <a href="rubric.html">rubric v{esc(D.get('rubric', {}).get('version', ''))}</a>. A resource maintained under the
  Open Workplace Health Standard, distinct from the normative specification. Grades are editorial assessments of published
  evidence for a working-adult audience in any country; they are not part of the standard and change through the registry's public
  corrections process, not by RFC. Grades are single-rater and {esc(FROZEN_PHRASE)} until independent raters join
  (see <a href="how-to-read.html#raters">who graded this</a>).</p>
  <p>Registry text CC BY 4.0 &middot; dataset structure Apache 2.0 &middot; no instrument item text is reproduced anywhere in this
  registry. See <a href="how-to-read.html">how to read this registry</a>. Stewarded by
  <a href="https://www.alltoogether.com">Alltoogether</a> · early open specification.</p>
</div></footer>
</body></html>
"""

def licence_display(text):
    """Presentation-level cleanup of licence prose for public pages.

    The dataset's licence_status fields were written as research-session notes
    (first-person voice, 'this session', bracketed [Previously: ...] history).
    The dataset stays verbatim; the page rewrites session-log phrasing to a
    neutral registry voice and drops the inline history (the corrections and
    verifications log is the public home for history).
    """
    t = str(text)
    t = re.sub(r"\s*\[Previously:.*?\]", "", t, flags=re.S)
    t = t.replace("I was unable to reach a primary steward licence page this session.",
                  "a primary steward licence page could not be reached at the last verification attempt.")
    t = t.replace("could NOT be read this session", "could not be read at the last verification attempt")
    t = t.replace("Not verified this session.", "Not yet verified against the steward's current distribution terms.")
    t = t.replace("Not confirmed this session", "Not yet confirmed against the steward's current distribution terms")
    t = t.replace("Rule 7 requires", "The registry's licence-currency rule requires")
    t = t.replace("this session", "at the last verification attempt")
    return t

def archived_links(ident):
    urls = ident.get("licence_page_archived_url") or []
    if not urls: return ""
    links = " &middot; ".join(f'<a href="{esc(u)}">archived copy {i+1}</a>' for i, u in enumerate(urls))
    return f'<br><span class="meta">Steward page as read, Internet Archive: {links}</span>'

def class_line(ident):
    cls = ident.get("licence_class")
    if not cls: return ""
    note = ident.get("licence_class_note", "")
    return (f'<span class="licclass">{esc(cls)}</span><b>{esc(LIC_LABEL.get(cls, cls))}</b> for employer or vendor use. '
            f'{md(note)}<br>')

def licence_block(rec):
    ident = rec["identity"]
    lic = licence_display(ident.get("licence_status", ""))
    date = ident.get("licence_verified_date")
    src = ident.get("licence_source", "")
    unverified = str(lic).lower().startswith(("not verified", "not yet verified", "not yet confirmed")) or ident.get("licence_class") == "unverified"
    if unverified:
        # the bold label already states the position; drop a duplicate leading sentence
        lic = re.sub(r"^Not yet (verified|confirmed) against the steward's current distribution terms\.\s*", "", lic)
        inner = (class_line(ident) + f'<b>Licence status: not yet verified against current steward terms.</b> {md(lic)}'
                 + (f'<br><span class="meta">Verification attempted {esc(date)}; steward source: {md(src)}</span>' if src else "")
                 + archived_links(ident))
        return f'<div class="licbad">{inner}</div>'
    inner = (class_line(ident) + f'<b>Licence status</b> (verified {esc(date)}): {md(lic)}'
             + (f'<br><span class="meta">Source: {md(src)}</span>' if src else "")
             + archived_links(ident)
             + '<br><span class="meta">The registry records the licence class and the steward\'s page, never a price: fees change without notice and the archived page is the record of what was read.</span>')
    return f'<div class="licok">{inner}</div>'

def prop_block(rec, key, label):
    p = rec.get(key)
    if not isinstance(p, dict): return ""
    head = (f'<h3>{esc(label)} {grade_chip(p)}{status_chip(p.get("status"))}'
            f'{ef_chip(p.get("evidence_form"))}</h3>')
    ind = f'<p style="margin:4px 0">{ind_chip(p.get("indirectness"), p.get("indirectness_basis"))}</p>' if p.get("indirectness") else ""
    if p.get("grade") in ("Absent", "Not-applicable") and p.get("absence_type"):
        ind += f'<p style="margin:4px 0"><span class="ind ind-note">absence type: {esc(p["absence_type"])}</span> <span class="indnote">{esc(ABSENCE_SHORT.get(p["absence_type"], ""))}</span></p>'
    if p.get("inherited_from"):
        src = BY_ID.get(p["inherited_from"])
        ind += (f'<p class="cellmeta">Grade and flag inherited from the parent record '
                f'<a href="{esc(p["inherited_from"])}.html">{esc(src["display_name"] if src else p["inherited_from"])}</a>; the evidence is the parent\'s.</p>')
    meta = []
    if p.get("evidence_state"): meta.append(f'state: {esc(p["evidence_state"])}')
    if p.get("rubric_version"): meta.append(f'rubric v{esc(p["rubric_version"])}')
    if p.get("as_of"): meta.append(f'literature as of {esc(p["as_of"])}')
    if p.get("grade_last_confirmed"): meta.append(f'grade confirmed {esc(p["grade_last_confirmed"])}')
    if p.get("review_due"): meta.append('<span class="rd">review due: a citation was added after the grade was last confirmed; the grade is unchanged until a rater confirms it</span>')
    for line in previous_lines(p):
        meta.append(line)
    ind += f'<p class="cellmeta">{" &middot; ".join(meta)}</p>' if meta else ""
    body = ""
    if key == "test_retest_reliability":
        f = p.get("findings")
        if isinstance(f, list) and f:
            rows = "".join(
                "<tr>" + "".join(f"<td>{md(x.get(c,''))}</td>" for c in
                                 ("coefficient", "coefficient_type", "interval", "sample_n", "population", "evidence_form"))
                + "</tr>" for x in f)
            body += ('<div class="trwrap"><table class="tr"><thead><tr><th>Coefficient</th><th>Type</th><th>Interval</th>'
                     '<th>Sample</th><th>Population</th><th>Evidence form</th></tr></thead><tbody>'
                     + rows + "</tbody></table></div>")
        if p.get("summary"):
            body += f'<p class="findings">{md(p["summary"])}</p>'
        elif isinstance(f, str) and f:
            body += f'<p class="findings">{md(f)}</p>'
    else:
        f = p.get("findings")
        if isinstance(f, str) and f:
            body += f'<p class="findings">{md(f)}</p>'
        if p.get("summary"):
            body += f'<p class="findings">{md(p["summary"])}</p>'
    if p.get("subgrades"):
        subs = p["subgrades"]
        items = ""
        if isinstance(subs, list):
            for sgv in subs: items += f"<li>{md(sgv if isinstance(sgv, str) else json.dumps(sgv))}</li>"
        elif isinstance(subs, dict):
            for sk, sv in subs.items(): items += f"<li><b>{esc(sk)}:</b> {md(sv if isinstance(sv, str) else json.dumps(sv))}</li>"
        body += f'<p style="margin-bottom:2px"><b>Sub-grades (evidence differs by subgroup):</b></p><ul class="findings">{items}</ul>'
    if p.get("grade") == "High" and p.get("precondition_evidence"):
        tagged = any("population" in x for x in p["precondition_evidence"])   # population-sensitive property (rubric 1.6 section 3)
        rows = "".join("<tr>" + "".join(f"<td>{md(x.get(c, ''))}</td>" for c in ("citation", "n", "statistic"))
                       + (f'<td>{esc(x.get("population", ""))}</td>' if tagged else "")
                       + (f'<td style="white-space:nowrap"><a href="https://doi.org/{esc(x["doi"])}" target="_blank" rel="noopener">{esc(x["doi"])}</a></td>' if x.get("doi") else "<td></td>")
                       + "</tr>" for x in p["precondition_evidence"])
        body += ('<p style="margin-bottom:2px"><b>High precondition (rubric 1.6):</b> the cited studies that meet the High precondition, each with a sample size and a statistic of this property'
                 + ('; on this population-sensitive property at least one is working-adults or general.' if tagged else '.') + '</p>'
                 '<div class="trwrap"><table class="tr"><thead><tr><th>Study</th><th>Sample</th><th>Statistic</th>'
                 + ('<th>Population</th>' if tagged else '') + '<th>DOI</th></tr></thead><tbody>'
                 + rows + "</tbody></table></div>")
    if p.get("confidence_note"):   # legacy pilot-pass note (rubric 1.6 section 1): never the basis of a grade or a flag
        body += f'<p class="findings"><b>Confidence note (legacy, first pass; not the basis of the grade):</b> {md(p["confidence_note"])}</p>'
    return f'<div class="prop">{head}{ind}{body}</div>'

# Which correction moved a cell off a given rubric version (rubric 1.0 -> C-0004 at v0.4.0; rubric 1.1 -> C-0005 at v0.5.0; rubric 1.2 -> C-0006 at v0.6.0; rubric 1.3 -> C-0007 at v0.7.0; rubric 1.4 -> C-0008 at v0.8.0; rubric 1.5 -> C-0009 at v0.9.0).
CORRECTION_FOR_RUBRIC = {"1.0": "C-0004", "1.1": "C-0005", "1.2": "C-0006", "1.3": "C-0007", "1.4": "C-0008", "1.5": "C-0009"}
PREV_KEYS = ("grade", "status", "evidence_form", "evidence_state", "indirectness", "absence_type", "precondition_evidence")
def previous_lines(p):
    """One meta line per prior state of a cell, oldest last; each names what changed and the correction that changed it."""
    out, cur, prev = [], p, p.get("previous")
    while isinstance(prev, dict):
        diffs = []
        for k in PREV_KEYS:
            a, b = prev.get(k), cur.get(k)
            if k == "indirectness":
                a, b = ind_head(a) or ("unflagged" if a is None else "flagged"), ind_head(b) or ("unflagged" if b is None else "flagged")
            if k == "precondition_evidence":   # schema 0.7: the archived High evidence; shown as a count, the entries stay in the dataset
                a = None if a is None else f"{len(a)} entries"
                b = "none" if b is None else f"{len(b)} entries"
            if prev.get(k) is None and b is not None:
                continue   # a field the older schema did not carry, filled in: not a change of state
            if a != b:
                diffs.append(f'{k.replace("_", " ")} {esc(str(a))} &rarr; {esc(str(b))}')
        rv = str(prev.get("rubric_version", "1.0"))
        corr = CORRECTION_FOR_RUBRIC.get(rv, "a logged correction")
        out.append(f'under rubric v{esc(rv)}: ' + ("; ".join(diffs) if diffs else f'{esc(prev.get("grade"))}, no change of state')
                   + f' (re-read before first publication, correction {corr})')
        cur, prev = prev, prev.get("previous")
    return out

TYPE_PHRASE = {"multi-item-scale": "multi-item scale", "item-set": "item set whose items are separate records",
               "single-item": "single item"}
SHORT = {"structural_validity": "Structural validity", "convergent_discriminant_validity": "Convergent validity",
         "criterion_validity_reference_standard": "Criterion (reference standard)",
         "criterion_validity_organisational": "Criterion (organisational)", "internal_consistency": "Internal consistency",
         "test_retest_reliability": "Test-retest", "measurement_invariance": "Invariance", "responsiveness_mic": "Responsiveness"}
LOWER = {"structural_validity": "structural validity", "convergent_discriminant_validity": "convergent and discriminant validity",
         "criterion_validity_reference_standard": "criterion validity against a reference standard",
         "criterion_validity_organisational": "criterion validity against organisational outcomes (absence, turnover, performance)",
         "internal_consistency": "internal consistency", "test_retest_reliability": "test-retest reliability",
         "measurement_invariance": "measurement invariance", "responsiveness_mic": "responsiveness to change"}

def first_sentence(t, limit=260):
    t = re.split(r"(?<=[.;])\s", str(t or "").strip())[0].rstrip(".;")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " ..."
    return t

def item_phrase(count):
    c = str(count or "").strip()
    m = re.match(r"^(\d+)\s*items?\b", c)
    if m: return f'{m.group(1)} item{"s" if m.group(1) != "1" else ""}'
    m = re.match(r"^(\d+)\s+([a-z]+)", c)
    if m: return f"{m.group(1)} {m.group(2)}"
    m = re.match(r"^(\d+)", c)
    if m: return f'{m.group(1)} item{"s" if m.group(1) != "1" else ""}'
    return ""

def join_list(items):
    items = list(items)
    if not items: return ""
    if len(items) == 1: return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]

def freeze_banner():
    if not RATER.get("grade_moves_frozen"): return ""
    return (f'<div class="freeze"><b>Who graded this.</b> Every grade in this registry was assigned by one rater employed by the steward '
            f'({RATER.get("raters_total", 1)} rater, {RATER.get("independent_raters", 0)} independent), with AI assistance in literature retrieval and drafting. '
            f'Grades and statuses are single-rater and <b>{esc(FROZEN_PHRASE)}</b>; they will not move until two named psychometric raters '
            f'who are not employees of the steward have joined. Until then, automated sweeps add citations and flag cells for review; corrections of fact '
            f'are made in public; no grade changes. <a href="how-to-read.html#raters">Why, and how to volunteer</a>.</div>')

def verdict_box(rec):
    """Plain-English summary generated from the record's own grades and licence class. No hand prose."""
    ident = rec["identity"]
    name = rec["display_name"]
    cols = [(k, rec[k]) for k, _ in MATRIX_COLS if isinstance(rec.get(k), dict)]
    def of(grade): return [LOWER[k] for k, p in cols if p.get("grade") == grade]
    high, mod, low, vlow, absent = of("High"), of("Moderate"), of("Low"), of("Very low"), of("Absent")
    contested = [LOWER[k] for k, p in cols if p.get("status") == "contested"]
    graded = [(k, p) for k, p in cols if p.get("grade") in ("High", "Moderate", "Low", "Very low")]
    indirect = [k for k, p in graded if ind_head(p.get("indirectness")) == "indirect"]
    general = [k for k, p in graded if ind_head(p.get("indirectness")) == "general"]
    absent_pg = [LOWER[k] for k, p in cols if p.get("grade") == "Absent" and p.get("absence_type") in (None, "population-general")]
    absent_ce = [LOWER[k] for k, p in cols if p.get("grade") == "Absent" and p.get("absence_type") == "category-error"]
    ip = item_phrase(ident.get("item_count")) if rec["instrument_type"] != "single-item" else ""
    tp = TYPE_PHRASE.get(rec["instrument_type"], rec["instrument_type"])
    p1 = f'{esc(name)} is {"an" if tp[0] in "aeiou" else "a"} {tp}' + (f' ({esc(ip)})' if ip else "")
    claim = first_sentence(rec.get("constructs_claimed"))
    p1 += f'. <b>What it claims to measure:</b> {esc(claim)}' + ("" if claim.endswith("...") else ".")
    cls = ident.get("licence_class")
    if cls == "unverified":
        p1 += ' <b>Licence for an employer or vendor:</b> could not be verified against the steward\'s current terms; no class is asserted.'
    elif cls:
        p1 += f' <b>Licence for an employer or vendor:</b> {esc(LIC_LABEL.get(cls, cls))}' + (f' (verified {esc(ident.get("licence_verified_date"))}).' if ident.get("licence_verified_date") else ".")
    parts = []
    if high: parts.append(f'The published evidence is strongest for {join_list(high)}')
    if mod: parts.append(('moderate' if high else 'The published evidence is moderate') + f' for {join_list(mod)}')
    if low or vlow:
        parts.append(('weak' if (high or mod) else 'The published evidence is weak') + f' for {join_list(low + vlow)}')
    p2 = "; ".join(parts) + "." if parts else "No property of this record has yet been graded on located evidence."
    if absent_pg:
        p2 += f' No published evidence was located for {join_list(absent_pg)}: the registry searched and found none in the sweep to date, so if you need {"that property" if len(absent_pg) == 1 else "those properties"} evidenced, this instrument does not yet carry {"it" if len(absent_pg) == 1 else "them"}.'
    if absent_ce:
        p2 += f' {join_list(absent_ce)[0].upper() + join_list(absent_ce)[1:]} {"does" if len(absent_ce) == 1 else "do"} not apply to this construct: no reference standard exists for it, so nothing is graded and nothing is missing.'
    if contested:
        p2 += f' The evidence base for {join_list(contested)} is contested in the published literature.'
    if graded and indirect:
        n = len(indirect); m = len(graded)
        head = ("The one graded property rests" if m == 1 else f"All {m} graded properties rest" if n == m else f"{n} of the {m} graded properties rest")
        p2 += f' {head} on evidence from clinical, student or otherwise non-working samples; where the property is sensitive to population that evidence cannot carry a High grade, and the reason is stated on each cell below.'
    if graded and general:
        n = len(general); m = len(graded)
        p2 += (f' {"The one graded property rests" if m == 1 else ("All " + str(m) + " graded properties rest") if n == m else (str(n) + " of the " + str(m) + " graded properties rest")}'
               ' on adult general-population samples rather than samples of working adults; the flag says so on each cell.')
    chips = ""
    for k, p in cols:
        g = p.get("grade"); state = p.get("evidence_state")
        c = {"High": "c-high", "Moderate": "c-mod", "Low": "c-low", "Very low": "c-vlow", "Absent": "c-absent", "Not-applicable": "c-na"}.get(g, "")
        label = {"Not-applicable": "n/a", None: "not assessed"}.get(g, g)
        if state == "not_assessed": label, c = "not assessed", ""
        chips += f'<span class="chip {c}">{esc(SHORT[k])}: {esc(label)}</span>'
    if cls:
        chips += f'<span class="chip c-lic">Licence: {esc(cls)}</span>'
    return (f'<div class="verdict"><h2>In plain English</h2><p>{p1}</p><p>{p2}</p><div class="facts">{chips}</div>'
            '<p class="caveat-line">Grades summarise the published evidence for this instrument on its own terms; they are not comparable '
            'across instruments, and this page makes no recommendation. Whether an instrument fits your workforce is a judgement this '
            'registry informs but cannot make. Full evidence, with citations, below. This summary is generated from the record\'s data, '
            'not written by hand.</p></div>')

def record_page(rec):
    rid = rec["instrument_id"]; ident = rec["identity"]
    contested = [lbl for k, lbl in PROPS if isinstance(rec.get(k), dict) and rec[k].get("status") == "contested"]
    chips = f'<span class="status-chip">{esc(rec["instrument_type"])} &middot; dataset v{esc(D["version"])}</span>'
    if contested:
        chips += f' <span class="stat st-contested" style="font-size:12px">contested: {esc(", ".join(contested))}</span>'
    lvd = str(ident.get("licence_verified_date") or "")
    lvd_disp = lvd if re.match(r"^\d{4}-\d{2}-\d{2}$", lvd) else "not yet verified"
    lr = rec.get("last_reviewed") or REVIEW_DATE
    body = [f'{chips}<h1>{esc(rec["display_name"])}</h1>',
            f'<p class="meta">Licence verified: {esc(lvd_disp)} &middot; literature last reviewed: {esc(lr)} &middot; grades last confirmed: {esc(CONFIRMED)} &middot; rubric v{esc(D.get("rubric", {}).get("version", ""))}</p>']
    if not rec.get("parent_id"):
        body.append(verdict_box(rec))
    body.append(freeze_banner())
    if rec.get("parent_id"):
        par = BY_ID[rec["parent_id"]]
        body.append(f'<div class="callout">An item record of the <a href="{esc(par["instrument_id"])}.html">{esc(par["display_name"])}</a> item set. Graded evidence is held at the set level.</div>')
    if rec.get("items"):
        links = " &middot; ".join(f'<a href="{esc(i)}.html">{esc(BY_ID[i]["display_name"])}</a>' for i in rec["items"])
        body.append(f'<div class="callout"><b>Item set.</b> The items are first-class records: {links}</div>')
    body.append('<h2>Identity</h2><div class="idgrid">')
    for k, lbl in [("current_version", "Version"), ("item_count", "Structure"), ("original_citation", "Original citation"),
                   ("steward_publisher", "Steward / publisher")]:
        if ident.get(k): body.append(f'<p><b>{lbl}:</b> {md(ident[k])}</p>')
    body.append("</div>")
    body.append(licence_block(rec))
    if "steward_product_use" in rec:
        spu = rec["steward_product_use"]
        txt = ("not yet declared" if spu is None else ("yes" if spu else "no"))
        body.append(f'<p class="meta">Used by the steward\'s own products: {txt}. '
                    'The steward discloses this so a reader can check for favourable treatment; the reasons behind any selection are not part of this registry.</p>')
    if rec.get("constructs_claimed"):
        body.append(f'<h2>Constructs claimed</h2><p class="findings">{md(rec["constructs_claimed"])}</p>')
    bl = bank_links_for(rid)
    if bl:
        links = " &middot; ".join(f'<a href="../question-bank/group-{g}.html#{i}">{esc(t)}</a>' for i, t, g in bl)
        body.append(f'<div class="banklink"><b>In the question bank:</b> {links}</div>')
    rels = relations_of(rec)
    if rels:
        lis = ""
        for label, tid, tname, evidence, note in rels:
            tgt = f'<a href="{esc(tid)}.html">{esc(tname)}</a>' if tid else f'{esc(tname)} <span class="meta">(no registry record yet)</span>'
            lis += f'<li><b>{esc(label)}</b> {tgt}. {md(evidence)}' + (f' <span class="relnote">{md(note)}</span>' if note else "") + '</li>'
        body.append(f'<h2>Relations to other records</h2><ul class="rels">{lis}</ul>'
                    '<p class="meta">A relation is published fact about the literature, with the study it rests on. It never says which form an implementer should use.</p>')
    body.append("<h2>Evidence</h2>")
    if rec.get("deployment_context_caveat"):
        body.append(f'<div class="caveat"><b>Deployment context caveat.</b> {md(rec["deployment_context_caveat"])} <span class="meta">(applies to every property below)</span></div>')
    for k, lbl in PROPS:
        body.append(prop_block(rec, k, lbl))
    for k, lbl in [("populations_languages_norms", "Populations, languages and norms"),
                   ("criticisms_controversies", "Criticisms and controversies")]:
        v = rec.get(k)
        if isinstance(v, dict) and (v.get("findings") or v.get("summary")):
            body.append(f'<h2>{lbl}</h2><p class="findings">{md(v.get("findings") or v.get("summary"))}</p>')
        elif isinstance(v, str) and v:
            body.append(f'<h2>{lbl}</h2><p class="findings">{md(v)}</p>')
    cits = rec.get("citations") or []
    if cits:
        lis = ""
        for c in cits:
            link = c.get("doi") or c.get("url") or ""
            txt = f'{esc(c.get("authors",""))} ({esc(c.get("year",""))}). {esc(c.get("title",""))}'
            if c.get("source"): txt += f'. {esc(c["source"])}'
            if link:
                if not str(link).startswith("http"): link = "https://doi.org/" + str(link)
                txt += f' <a href="{esc(link)}">{esc(link)}</a>'
            lis += f"<li>{txt}</li>"
        body.append(f'<h2>References ({len(cits)})</h2><ol class="refs">{lis}</ol>')
    if rec.get("record_notes"):
        body.append(f'<h2>Record notes</h2><p class="findings">{md(rec["record_notes"])}</p>')
    (SITE / f"{rid}.html").write_text(
        page(f'{rec["display_name"]} | OWHS Instrument Registry', "\n".join(body),
             f'Evidence record for {rec["display_name"]}: graded psychometric properties with provenance, licence status and citations.'),
        encoding="utf-8")

def build_index():
    rows = ""
    for r in PARENTS:
        cells = "".join(grade_cell(r[k]) for k, _ in MATRIX_COLS)
        rows += f'<tr class="{size_class(r)}"><td><a href="{esc(r["instrument_id"])}.html">{esc(r["display_name"])}</a></td>{cells}</tr>\n'
    heads = "".join(f"<th>{esc(h)}</th>" for _, h in MATRIX_COLS)
    body = f"""
<span class="status-chip">OWHS v0.1 &middot; resource, not the normative spec &middot; {len(GRADED)} instruments graded, {len(RECORDS)} records, {len(WATCHLIST)} on the watchlist &middot; stage one of the field &middot; dataset v{esc(D["version"])}</span>
<h1>Instrument Registry</h1>
<p class="lede">An evidence registry for the instruments used to measure workplace health and wellbeing: per-property
grades with provenance, licence status verified against current steward terms, and a public corrections log. It is a resource
maintained under the Open Workplace Health Standard, distinct from the normative specification. It describes instruments;
it never reproduces them. It grades evidence about instruments, never evidence about interventions.</p>
<p class="purpose">{PURPOSE}</p>

<div class="callout"><b>The founding finding, stated plainly.</b> Two things stand out across the first {len(GRADED)} instruments.
Test-retest reliability is the field's weakest and most-absent property: practitioners tracking change over time are running
on far less stability evidence than they assume. And the instruments in common UK workplace use carry little evidence that
their scores predict recorded work outcomes such as absence or turnover, while the instruments that carry that evidence, built
in the occupational-epidemiology tradition, are not in common UK use. Organisational criterion validity is absent for
{ORG_ABSENT} of the {len(GRADED)} and thin for a further {ORG_THIN}. The clinical screeners are superbly evidenced for their
constructs and thinly evidenced for workplaces. The matrix below makes each of those asymmetries citable row by row.</div>

{freeze_banner()}
<h2>The grade matrix</h2>
<p class="legend"><b>What inclusion means.</b> Inclusion in the registry records evidence, provenance and
licence position. It does not indicate that the steward uses, recommends or endorses an instrument for a
particular product or workplace setting. Some records are clinical symptom measures that can arise in
occupational-health settings and carry materially different safeguards and interpretation from workplace
wellbeing measures. A grade describes the published evidence for a property, never the suitability of an
instrument for a general employee survey.</p>
<p class="legend"><b>Reading the cells.</b> Grades run High / Moderate / Low / Very low, assigned under
<a href="rubric.html">rubric v{esc(D.get("rubric", {}).get("version", ""))}</a>.
<b>Absent</b> means the property was searched for and no published evidence was found in the sweep to date: a finding about the literature, not a blank.
<b>not assessed</b> (hatched) would mean the registry has not yet searched: a gap in our work, not a finding; no cell is in that state in this version.
<b>n/a</b> means the property is a category error for that instrument type (for example internal consistency of a single
item): a category difference, never a gap. Suffix <b>*</b> marks a contested evidence base; <b>~</b> marks a thin one;
<span class="due">&#9679;</span> marks a cell where a sweep added a citation after the grade was last confirmed (review due, grade unchanged).
Scroll the matrix sideways on small screens; the instrument column stays fixed.</p>
<div class="filter" role="group" aria-label="Filter the matrix by instrument length. A filter, never a sort: rows keep their order.">
<span class="filterlabel">Show:</span>
<input type="radio" name="size" id="f-all" checked><label for="f-all">all {len(PARENTS)}</label>
<input type="radio" name="size" id="f-single"><label for="f-single">single items ({sum(1 for r in PARENTS if size_class(r) == "n-single")})</label>
<input type="radio" name="size" id="f-short"><label for="f-short">2 to 10 items ({sum(1 for r in PARENTS if size_class(r) == "n-short")})</label>
<input type="radio" name="size" id="f-long"><label for="f-long">more than 10 items ({sum(1 for r in PARENTS if size_class(r) == "n-long")})</label>
<input type="radio" name="size" id="f-set"><label for="f-set">item sets and surveys ({sum(1 for r in PARENTS if size_class(r) == "n-set")})</label>
<div class="matrixwrap">
<table class="matrix">
<thead><tr><th>Instrument</th>{heads}</tr></thead>
<tbody>
{rows}</tbody>
</table>
</div>
</div>
<p class="legend">Every cell links to full findings, provenance and citations on the instrument's record page (click the
instrument name). Grades are for a working-adult audience: evidence earned in clinical, student, adolescent or otherwise
non-working samples is flagged indirect and already downgraded, so totals of studies are not what these cells report.
Country and language are never a reason for a downgrade; they are recorded on the record and graded under measurement
invariance. The single-item measures, and what each has been shown to screen for, are on their
<a href="single-items.html">own page</a>. Method in full: <a href="how-to-read.html">how to read this registry</a>.</p>

<h2>The field, in stages</h2>
<p>The registry's scope is the whole field: every instrument with published measurement-property evidence in working-age
populations, in any country, whose construct sits in the workplace health and wellbeing code list. It is built one record at a
time, properly or not at all, and the stages are public.</p>
<p><b>Stage one, the instruments in common UK use.</b> The first {len(GRADED)} records: the instruments the OWHS question bank
draws items from, so that every published item has an evidence record behind it, and the instruments UK employers and vendors
most often field. Chosen for use, not for evidence, which is why the founding finding reads as it does.</p>
<p><b>Stage two, the occupational-epidemiology tradition and the single items.</b> The instruments built to measure job conditions
and validated against recorded outcomes in long cohorts: the Job Content Questionnaire and the Effort-Reward Imbalance
questionnaire first, then the short demand-control forms and the organisational-justice scales. Alongside them, the
well-evidenced single-item measures that have been validated against a multi-item instrument for the same construct.</p>
<p><b>After that, by proposal and by sweep.</b> Anyone may propose an instrument. A proposal names the construct, cites two studies
reporting a measurement property in working-age samples, and identifies the licence position. Verified proposals join the
watchlist, where every property reads not assessed until a rater grades it. Proposals we decline are listed with the reason.
The steward's own proposals go through the same public route. The rule in full:
<a href="admission.html">how an instrument enters this registry</a>.</p>

<h2>Related resources</h2>
<p>The <a href="../question-bank/index.html">Workplace Wellbeing Question Bank</a> catalogues single survey items from the
public commons with per-item provenance and licensing; where an instrument here also appears there, the two records
cross-link. Corrections to any published record are logged publicly on the
<a href="corrections.html">corrections and verifications page</a>.</p>
"""
    (SITE / "index.html").write_text(page("Instrument Registry | Open Workplace Health Standard", body,
        "The open synthesis of the published evidence on instruments used to measure workplace health and wellbeing: graded properties with provenance, licence status, corrections log.",
        here="index"), encoding="utf-8")

def build_how():
    body = f"""
<h1>How to read this registry</h1>
<p class="lede">Every convention in the registry exists to stop a reader over-trusting a number. This page is the method.</p>
<p class="purpose">{PURPOSE}</p>
<p>{SYNTHESIS_EDGE}</p>

<h2>The grade scale</h2>
<p>Each property carries one of <span class="grade g-high">High</span> <span class="grade g-mod">Moderate</span>
<span class="grade g-low">Low</span> <span class="grade g-vlow">Very low</span>, or one of two non-grades:
<span class="grade g-absent">Absent</span>, meaning no published evidence was located, which is reported as a finding about
the literature; and <span class="grade g-na">Not applicable</span>, meaning the property is a category error for the
instrument's type (a single item has no internal consistency to report). The two non-grades are deliberately distinct:
absence is information, not-applicable is taxonomy, and a registry that lets them blur misleads exactly the reader it
exists to protect. Every ungraded cell also names its absence type: <b>population-general</b> (searched, nothing found in any
population) or <b>category-error</b> (the property does not apply to the construct, for example a criterion reference standard for a
construct that has none, or measurement invariance of a single item). Evidence that exists only in other populations is never
recorded as Absent: it is graded and flagged indirect. Ungraded cells carry no indirectness flag: there is no grade for the flag to qualify.</p>

<h2>Evidence states: what the registry did, not what the literature says</h2>
<p>Every cell also records the registry's own work on it. <b>assessed</b>: searched and graded. <b>assessed_absent</b>: searched,
nothing found in the sweep to date, published as a finding with the search basis. <b>not_assessed</b>: not yet searched, which
says nothing about the literature; new instruments enter the watchlist in this state until a rater grades them. <b>not_applicable</b>:
category error. Each cell also carries the rubric version it was graded under, the date its literature was last searched, the
date a human last confirmed the grade, and a review-due flag set whenever a sweep adds a citation after that confirmation.
The full method is the <a href="rubric.html">grading rubric</a>.</p>

<h2 id="raters">Who graded this, and the freeze</h2>
<p>{esc(RATER.get("note", ""))} Unfreeze condition: {esc(RATER.get("unfreeze_condition", ""))} The registry is looking for those raters:
psychometricians or measurement researchers with no financial interest in the instruments they would grade (instrument authors
are welcome as reviewers of their own records, never as raters of them). Write to hello@openworkplacehealth.org.</p>

<h2>The four status tokens</h2>
<p>The grade says how strong the evidence is; the status says what kind of literature produced it:
<span class="stat st-well">well-established</span> a mature, replicated evidence base;
<span class="stat st-contested">contested</span> credible published disagreement (this badge is displayed prominently on
record pages, never buried);
<span class="stat st-thin">thin</span> few studies, small samples, or narrow settings;
<span class="stat st-untested">untested</span> the specific claim has not been directly examined.
Moderate-and-contested and Moderate-and-thin are different situations that previously shared a word; here they never do.</p>

<h2>Indirectness: who the grade is for</h2>
<p>Grades are for a working-adult audience, not bibliometric totals. Every grade carries a three-value indirectness flag with its reason:
<span class="ind ind-direct">direct</span> evidence earned on samples of working adults, in any country and any language;
<span class="ind ind-general">general</span> evidence earned on adult general-population samples that include working adults
without isolating them; <span class="ind ind-indirect">indirect</span> evidence earned in clinical, student, adolescent,
older-adult or otherwise non-working samples. The flag and the grade are separate facts: a grade never moves because a flag moved.
The flag bites only where the property is sensitive to who was sampled (convergent validity, both criterion validities, responsiveness,
populations and languages): there a High grade needs direct or general evidence, and indirect evidence caps the grade at Moderate.
Criterion validity against a reference standard is on that list because a cut-off validated in a clinic, where the condition is common,
is not a cut-off validated in a workforce, where it is rare. For the properties that are about the instrument's own structure
(internal consistency, structural validity, invariance, test-retest) the flag is recorded and shown but does not move the grade.
Each flag names the samples it rests on, quoted from the cell's own findings, each naming a population (a sample size or a country
on its own is not a reason), or says that it falls back to the population the instrument is fielded on because the cited studies describe
no sample. Country and language are never a reason for a downgrade: where the evidence
was earned is recorded on the cell as a fact, and whether an instrument behaves the same across languages is a graded property
of its own, measurement invariance. A large clinical literature does not entitle an instrument to a High grade for workplace use;
the flag is where that discipline lives. A High grade has a precondition: at least two cited studies with a sample size and a
statistic of the property graded, listed on the cell as its High basis, and on a population-sensitive property at least one of them
in a working-adult or general-population sample, and on populations, languages and norms at least one of them carrying a norm,
cut-off, prevalence or reference value; a cell that cannot show them is Moderate at most. The numbers the grade rests on,
with their intervals and sample sizes, are in the findings on each cell. A record-level deployment context caveat, where present, states once anything that cuts across every
property (for example a clinical-origin instrument deployed in a workplace) and is shown at the top of the evidence section.</p>

<h2>Relations between records</h2>
<p>Where a published study links two records, the link is recorded as data and shown on both record pages: an item to its
parent set, a single item or short form to the full instrument it was derived from, a single item to a multi-item instrument
it has been shown to screen for (with reported sensitivity and specificity against the longer instrument's threshold), a
single item to a multi-item instrument it corresponds with (a reported correlation only, which is convergence, not screening),
and a composite survey to an instrument it fields verbatim. Every relation cites the study it rests on; a relation without one is not recorded. A relation
is a fact about the literature, never a recommendation: the registry does not say which form an implementer should use, and
it never states a threshold for action. The single-item measures are gathered on <a href="single-items.html">their own page</a>.</p>

<h2>Evidence-form provenance</h2>
<p>Every grade names what the evidence was earned on: <b>canonical</b> (the fielded instrument, as versioned),
<b>derivative</b> (a named reworded or short form), <b>parent</b> (a longer parent form), or <b>mixed</b>. Borrowed evidence
can no longer be silently read as evidence for the fielded instrument.</p>

<h2>Criterion validity is two properties, never one</h2>
<p>Validity against a diagnostic or health reference standard and validity against organisational outcomes (absence,
turnover, performance) diverge so sharply across this registry that a merged grade actively misleads, in exactly the
direction that harms a workplace reader. They are graded separately everywhere, by schema rule.</p>

<h2 id="organisational-outcomes">Criterion validity against organisational outcomes</h2>
<p>This property records whether an instrument's scores have been shown to relate to outcomes an organisation records:
sickness absence, return to work, occupational health referral, enacted adjustments, benefit use, actual turnover, rated or
objective performance, and safety incidents. Across this registry it is the property most often absent, and that absence is
one of the registry's founding findings.</p>
<p><b>What counts as an outcome here.</b> An organisational outcome is an event the organisation recorded, an outcome linked
from a register, or a performance measure rated independently of the person completing the instrument. Self-reported
constructs do not count in this property, however work-related they are: an association between an instrument and
self-reported turnover intention, self-rated productivity loss or self-rated work capacity is convergent validity between two
self-reports, and it is graded as convergent validity. Keeping the two apart is what stops this property from measuring
itself.</p>
<p><b>What the evidence records.</b> Each located finding names the outcome, its source, the study design, any follow-up
interval, the effect and its direction, the sample and population, and the form of the instrument the evidence was earned on.
In the current dataset version those findings are prose on the record page; from the next dataset version they are
structured fields, so that a reader can filter the registry on which outcomes have located evidence for an instrument.</p>
<p><b>What this property does not say.</b> It does not say the instrument will predict outcomes in your organisation: the
evidence was earned in named populations and settings, which every finding states. It does not rank instruments, and the
registry publishes no ordering of instruments on this or any other property. It says nothing about whether measuring
something changes it: evidence about interventions is a different literature, and this registry does not cover it.</p>

<h2>Test-retest is structured, not prose</h2>
<p>Retest findings are recorded as structured entries (coefficient, coefficient type, interval, sample, population), so
bundled ICCs and internal-consistency contamination cannot pass as stability evidence. This is the property the registry
found weakest across the entire instrument set.</p>

<h2>Licence currency</h2>
<p>Licence status is verified against the steward's current distribution terms, with the verification date shown on every
record. Founding papers and review literature are never acceptable licence sources; that rule was learned publicly
(correction C-0001) and is now schema law. Where a steward's terms could not yet be verified, the record says so plainly
and displays no settled status.</p>

<h2>Licence classes</h2>
<p>Each record carries a licence class for one audience, an employer or a vendor acting for one:
{"; ".join(f"<b>{esc(k)}</b>: {esc(v)}" for k, v in LIC_CLASSES.items())}. The registry records the class, the steward's
source page and an archived copy of it, never a price.</p>

<h2>The corrections policy, errata and right of reply</h2>
<p>Disputed or wrong statements in published records are checked and fixed publicly: every correction carries the old
value, the new value, and the source that settled it, on the <a href="corrections.html">corrections page</a>. A registry
that corrected itself silently would be indistinguishable from one that was never wrong; the log is the difference.
An instrument's steward, developer or copyright holder has a right of reply: a written response is published beside the
record, dated and unedited, with the registry's reply.</p>

<h2>What the automation does and does not do</h2>
<p>AI systems assist the rater with retrieval, screening, extraction and drafting, and run the monthly sweeps. They do not
assign grades, statuses, evidence forms or indirectness flags, and nothing they produce reaches the dataset except through
a change a human reviews and merges. What the automation may do, and where it has failed, is on the
<a href="../automation.html">automation page</a>.</p>

<h2>What this registry is not</h2>
<p>It is not part of the normative OWHS specification, it does not recommend instruments, it does not advise what to
measure, and it never reproduces instrument item text. It grades evidence about instruments, never evidence about
interventions. It describes the published evidence so that whoever chooses can choose with their eyes open. How an
instrument comes to be here at all is a separate rule: <a href="admission.html">how an instrument enters this registry</a>.</p>
"""
    (SITE / "how-to-read.html").write_text(page("How to read this registry | OWHS Instrument Registry", body,
        "The registry's method: grade scale, status tokens, indirectness, evidence-form provenance, licence currency, corrections policy.",
        here="how"), encoding="utf-8")

def build_single_items():
    cards = ""
    for r in SINGLE_ITEMS:
        claim = first_sentence(r.get("constructs_claimed"))
        rels = [x for x in relations_of(r) if x[0] in ("screens for", "corresponds with", "short form of")]
        if rels:
            lis = ""
            for label, tid, tname, evidence, note in rels:
                tgt = f'<a href="{esc(tid)}.html">{esc(tname)}</a>' if tid else f'{esc(tname)} <span class="meta">(no registry record yet)</span>'
                lis += f'<li><b>{esc(label)}</b> {tgt}. {md(evidence)}' + (f' <span class="relnote">{md(note)}</span>' if note else "") + '</li>'
            relhtml = f'<ul class="rels">{lis}</ul>'
        else:
            relhtml = '<p class="findings">No published correspondence with a multi-item instrument has been recorded for this item yet.</p>'
        graded = []
        for k, lbl in [("test_retest_reliability", "test-retest"), ("criterion_validity_reference_standard", "criterion, reference standard"),
                       ("criterion_validity_organisational", "criterion, organisational"), ("convergent_discriminant_validity", "convergent")]:
            p = r.get(k) or {}
            g = p.get("grade")
            if g:
                c = {"High": "c-high", "Moderate": "c-mod", "Low": "c-low", "Very low": "c-vlow", "Absent": "c-absent"}.get(g, "")
                graded.append(f'<span class="chip {c}">{esc(lbl)}: {esc(g)}</span>')
        chips = "".join(graded)
        cards += (f'<div class="si"><h3><a href="{esc(r["instrument_id"])}.html">{esc(r["display_name"])}</a></h3>'
                  f'<p class="findings"><b>What it claims to measure:</b> {esc(claim)}{"" if claim.endswith("...") else "."}</p>'
                  f'{relhtml}<div class="facts">{chips}</div></div>')
    body = f"""
<span class="status-chip">{len(SINGLE_ITEMS)} single-item records &middot; dataset v{esc(D["version"])}</span>
<h1>Single-item measures</h1>
<p class="lede">A single question is what an organisation can field every month. This page gathers every single-item record in
the registry, what each has been shown to screen for, and the published correspondence with the full instrument.</p>
<p>A single item cannot carry internal consistency or structural validity; those properties are category errors for it and are
recorded as not applicable, never as absent. What a single item can carry, and what these records grade, is test-retest
reliability, criterion validity and convergent validity against a multi-item instrument for the same construct. Where a
published study reports that correspondence, it is recorded as a relation with the study cited: <b>screens for</b> where the
study reports sensitivity and specificity against the instrument's threshold, <b>corresponds with</b> where it reports a
correlation only (convergence, which is not a screening claim), and <b>short form of</b> where the item was derived from the
instrument.</p>
<div class="callout">The registry records that a single item has been shown to screen for a construct; it never says that an
organisation should use the item instead of the instrument, and it never states a threshold for action. Those are the
implementer's decisions and outside the registry.</div>
{cards}
<h2>Single items still to enter</h2>
<p>Stage two of the field adds the well-evidenced single items that have been validated against a multi-item instrument for the
same construct: the single-item burnout measure (validated against the Maslach emotional-exhaustion scale) and the single-item
work-engagement measure (validated against the UWES). Each enters through the same <a href="admission.html">admission rule</a>;
single items have exactly the measurement-property literature the rule asks for.</p>
<p class="meta">The four ONS-4 items are single items administered as a set; they are recorded as item records of
<a href="ons-4.html">ONS-4</a> and carry their evidence at the set level.</p>
"""
    (SITE / "single-items.html").write_text(page("Single-item measures | OWHS Instrument Registry", body,
        "Every single-item measure in the registry, what each has been shown to screen for, and the published correspondence with the full instrument.",
        here="single"), encoding="utf-8")

def md_to_html(text):
    """Small markdown subset for the rubric: headings, paragraphs, pipe tables, lists, bold, code, links."""
    out, para, table, lst = [], [], [], None
    def flush_para():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>"); para.clear()
    def flush_table():
        nonlocal table
        if table:
            head, rows = table[0], [r for r in table[2:]]
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tblwrap"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
            table = []
    def flush_list():
        nonlocal lst
        if lst:
            tag, items = lst
            out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>"); lst = None
    def inline(t):
        t = esc(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<i>\1</i>", t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"doi:(10\.\S+?)(?=[),\s])", r'<a href="https://doi.org/\1">doi:\1</a>', t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
        return t
    def cells(line): return [c.strip() for c in line.strip().strip("|").split("|")]
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("|"):
            flush_para(); flush_list(); table.append(cells(st)); continue
        flush_table()
        if not st:
            flush_para(); flush_list(); continue
        if st == "---": flush_para(); flush_list(); out.append("<hr>"); continue
        m = re.match(r"^(#+)\s+(.*)", st)
        if m:
            flush_para(); flush_list(); lvl = min(len(m.group(1)), 3)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); continue
        m = re.match(r"^(\d+)\.\s+(.*)", st)
        if m:
            flush_para()
            if not lst or lst[0] != "ol": flush_list(); lst = ("ol", [])
            lst[1].append(m.group(2)); continue
        if st.startswith("- "):
            flush_para()
            if not lst or lst[0] != "ul": flush_list(); lst = ("ul", [])
            lst[1].append(st[2:]); continue
        para.append(st)
    flush_para(); flush_table(); flush_list()
    return "\n".join(out)

def build_rubric():
    text = RUBRIC_MD.read_text(encoding="utf-8")
    text = re.sub(r"^# .*\n", "", text, count=1)          # page supplies the h1
    body = f"""
<h1>Grading rubric, version {esc(D.get("rubric", {}).get("version", ""))}</h1>
<p class="lede">The reference a reader, a reviewer or a second rater needs to reproduce a cell or to argue with it. Every graded
cell names the rubric version it was graded under; grades move only under a published version, through the public corrections
process, by a human.</p>
{freeze_banner()}
<div class="rubric">{md_to_html(text)}</div>
<p class="meta">Source: <a href="RUBRIC-v{esc(D.get("rubric", {}).get("version", ""))}.md">RUBRIC-v{esc(D.get("rubric", {}).get("version", ""))}.md</a> in the dataset bundle. CC BY 4.0.</p>
"""
    (SITE / "rubric.html").write_text(page("Grading rubric | OWHS Instrument Registry", body,
        "The registry's grading rubric: grade scale, status tokens, evidence states, indirectness, how a cell is derived, what may move a grade, the role of AI.",
        here="rubric"), encoding="utf-8")

def build_admission():
    text = ADMISSION_MD.read_text(encoding="utf-8")
    text = re.sub(r"^# .*\n", "", text, count=1)          # page supplies the h1
    text = re.sub(r"\n---\n\n\*Maintained under.*$", "\n", text, flags=re.S)   # page footer carries this
    text = text.replace("set out in the grading rubric.", "set out in the [grading rubric](rubric.html).")
    body = f"""
<h1>How an instrument enters this registry</h1>
<p class="lede">Who may propose an instrument, what a proposal must contain, what the registry checks before a record exists,
and what happens to proposals it declines. Grading is a separate step under the <a href="rubric.html">rubric</a>; nothing here
assigns a grade.</p>
{freeze_banner()}
<div class="rubric">{md_to_html(text)}</div>
<p class="meta">Source: <a href="{esc(ADMISSION_MD.name)}">{esc(ADMISSION_MD.name)}</a> in the dataset bundle. CC BY 4.0.
Registry text; the construct-domain admission rule for the standard itself is decided by RFC under the
<a href="../governance.html">governance page</a>, not here.</p>
"""
    (SITE / "admission.html").write_text(page("How an instrument enters this registry | OWHS Instrument Registry", body,
        "The registry's admission rule: three doors, what a proposal must contain, the clerical check, watchlist, queue, decline reasons, conflict of interest.",
        here="admission"), encoding="utf-8")

def build_corrections():
    entries = []
    for c in sorted(D.get("corrections_log", []), key=lambda x: x.get("id", ""), reverse=True):
        entries.append(f"""<div class="prop">
<h3>{esc(c.get("id"))} &middot; {(f'<a href="{esc(c.get("instrument_id"))}.html">{esc(BY_ID.get(c.get("instrument_id"), {}).get("display_name", c.get("instrument_id")))}</a>' if c.get("instrument_id") else "every record")}</h3>
<p class="findings">{md(c.get("description", ""))}</p>
<p class="findings"><b>Was:</b> {md(c.get("old_value", ""))}</p>
<p class="findings"><b>Now:</b> {md(c.get("new_value", ""))}</p>
{f'<p class="meta">Source: {md(c.get("source",""))}</p>' if c.get("source") else ""}
</div>""")
    ver = []
    for v in D.get("verifications", []):
        ver.append(f"""<div class="prop">
<h3>{esc(v.get("id"))} &middot; <a href="{esc(v.get("record"))}.html">{esc(BY_ID.get(v.get("record"), {}).get("display_name", v.get("record")))}</a> <span class="meta">{esc(v.get("date",""))}</span></h3>
<p class="findings">{md(v.get("note", ""))} Field: <code style="font-family:var(--mono);font-size:12px">{esc(v.get("field",""))}</code></p>
{f'<p class="meta">Source: {md(v.get("source",""))}</p>' if v.get("source") else ""}
</div>""")
    chg = []
    for c in reversed(D.get("changelog", [])):
        chg.append(f'<div class="prop"><h3>Dataset {esc(c.get("version"))} <span class="meta">{esc(c.get("date"))}</span></h3><p class="findings">{md(c.get("change",""))}</p></div>')
    errata = D.get("errata") or []
    err = "".join(f'<div class="prop"><h3>{esc(e.get("id"))} <span class="meta">{esc(e.get("date",""))}</span></h3><p class="findings">{md(e.get("description",""))}</p></div>' for e in errata) \
          or '<p class="findings">No errata have been published for this dataset version. An erratum is a statement of an error in a published version that could have misled a reader, filed here on discovery and linked from the correction that fixes it.</p>'
    ror = D.get("right_of_reply") or {}
    replies = ror.get("responses") or []
    rr = "".join(f'<div class="prop"><h3><a href="{esc(x.get("instrument_id"))}.html">{esc(BY_ID.get(x.get("instrument_id"), {}).get("display_name", x.get("instrument_id")))}</a> <span class="meta">{esc(x.get("date",""))} &middot; from {esc(x.get("from",""))}</span></h3><p class="findings">{md(x.get("response",""))}</p><p class="findings"><b>Registry reply:</b> {md(x.get("registry_reply",""))}</p></div>' for x in replies) \
         or '<p class="findings">No responses have been filed yet.</p>'
    body = f"""
<h1>Corrections, errata and right of reply</h1>
<p class="lede">Every correction to a published record is logged here with the old value, the new value, and the source
that settled it. This page is trust infrastructure: the registry expects to be wrong sometimes and corrects itself in
public, newest first.</p>
<div class="callout"><b>To file a correction:</b> open an issue in the public repository (a template asks for the record, the
field, the evidence and any interest you hold in the instrument) or write to hello@openworkplacehealth.org. Corrections of
factual error take priority over all other registry work. Grades and statuses are single-rater and {esc(FROZEN_PHRASE)} until
independent raters join (see <a href="how-to-read.html#raters">who graded this</a>); a correction can still fix any error of fact.</div>
<h2>Corrections</h2>
{''.join(entries)}
<h2>Errata</h2>
{err}
<h2>Right of reply</h2>
<p class="findings">{esc(ror.get("policy", ""))}</p>
{rr}
<h2>Verifications</h2>
{''.join(ver)}
<h2>Dataset changes</h2>
{''.join(chg)}
"""
    (SITE / "corrections.html").write_text(page("Corrections, errata and right of reply | OWHS Instrument Registry", body,
        "The registry's public corrections log, errata and right-of-reply responses: old value, new value, and the source that settled it.",
        here="corrections"), encoding="utf-8")

def build_downloads():
    body = f"""
<h1>Downloads</h1>
<p class="lede">The registry is published as a canonical JSON dataset, a grade-matrix CSV, and a printable PDF.</p>
<ul>
<li><a href="{DATASET}">{DATASET}</a>: the canonical dataset
({len(RECORDS)} records at schema v{esc(D.get("schema_version",""))}: full findings, grades with evidence state, rubric version and review flags, provenance, licence classes with archived steward pages, citations, corrections, errata, right of reply).</li>
<li><a href="instrument-evidence-matrix-full.csv">instrument-evidence-matrix-full.csv</a>: the {len(PARENTS)}-instrument
grade matrix, generated from the dataset at each build, with the criterion split and each cell's indirectness flag or absence type.</li>
<li><a href="RUBRIC-v{esc(D.get("rubric", {}).get("version", ""))}.md">RUBRIC-v{esc(D.get("rubric", {}).get("version", ""))}.md</a>: the grading rubric every cell cites.</li>
<li><a href="{esc(ADMISSION_MD.name)}">{esc(ADMISSION_MD.name)}</a>: the admission rule, how an instrument gets a record at all.</li>
<li><a href="instrument-registry.pdf">instrument-registry.pdf</a>: a printable export of the matrix and record summaries.</li>
</ul>
<p>Relations between records (item-of, short-form-of, screens-for, corresponds-with, embeds) are in the dataset as <code>relations</code> on each
record, forward only, each with the study it rests on; the <a href="single-items.html">single-item measures page</a> renders them.</p>
<h2>Previous versions</h2>
<p>Earlier dataset files stay at their URLs so that citations resolve: {", ".join(f'<a href="{v}">{v}</a>' for v in PREVIOUS)}.
What changed between versions is on the <a href="corrections.html">corrections page</a> under dataset changes.</p>
<h2>How to cite</h2>
<div class="callout">Open Workplace Health Standard, Instrument Registry, dataset v{esc(D["version"])} ({esc(REVIEW_DATE)}).
Available at openworkplacehealth.org. Grades are editorial assessments of published evidence for a working-adult
audience; see the methodology page for the grading conventions.</div>
<h2>Licensing</h2>
<p>Registry text is licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; the dataset structure is
licensed <a href="https://www.apache.org/licenses/LICENSE-2.0">Apache 2.0</a>. Instrument item text is never reproduced in
this registry; each instrument's own licence status is recorded on its page, verified against the steward's current terms
where possible.</p>
"""
    (SITE / "downloads.html").write_text(page("Downloads | OWHS Instrument Registry", body,
        "Download the registry as JSON, CSV, or PDF.", here="downloads"), encoding="utf-8")

def build_pdf():
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
    h2 = ParagraphStyle("h2x", parent=styles["Heading2"], fontSize=11, textColor=colors.HexColor("#0b6e5f"), spaceBefore=8, spaceAfter=2)
    small = ParagraphStyle("s", parent=styles["BodyText"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#5c646c"))
    cell = ParagraphStyle("c", parent=styles["BodyText"], fontSize=6.6, leading=8)
    doc = SimpleDocTemplate(str(SITE / "instrument-registry.pdf"), pagesize=landscape(A4),
                            leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm,
                            title="OWHS Instrument Registry")
    story = [Paragraph("OWHS Instrument Registry", h1),
             Paragraph(f"Dataset v{D['version']}, reviewed {REVIEW_DATE}. A resource maintained under the Open Workplace Health "
                       "Standard, distinct from the normative specification. Absent = searched, none found in the sweep to date (a finding); "
                       "n/a = category difference for the instrument type. * contested, ~ thin. Grades assigned by a single "
                       f"rater employed by the steward under rubric v{D.get('rubric', {}).get('version', '')}; {FROZEN_PHRASE} "
                       "until independent raters join.", small),
             Spacer(1, 6)]
    data = [["Instrument"] + [h for _, h in MATRIX_COLS]]
    for r in PARENTS:
        row = [Paragraph(r["display_name"], cell)]
        for k, _ in MATRIX_COLS:
            p = r[k]; g = p.get("grade")
            txt = {"Not-applicable": "n/a", None: ""}.get(g, g)
            if g not in ("Not-applicable", "Absent", None):
                txt += {"contested": " *", "thin": " ~"}.get(p.get("status"), "")
            row.append(Paragraph(txt or "", cell))
        data.append(row)
    t = Table(data, colWidths=[62*mm] + [24.5*mm]*8, repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0,0), (-1,0), 7), ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f6f7f8")),
                           ("LINEBELOW", (0,0), (-1,0), 1, colors.HexColor("#101418")),
                           ("LINEBELOW", (0,1), (-1,-1), 0.25, colors.HexColor("#e3e6e9")),
                           ("VALIGN", (0,0), (-1,-1), "TOP")]))
    story += [t, Spacer(1, 10), Paragraph("Record summaries", h2)]
    for r in PARENTS:
        ident = r["identity"]
        lic = str(ident.get("licence_status", ""))
        licline = "Licence not yet verified against current steward terms." if lic.lower().startswith("not verified") \
                  else f"Licence verified {ident.get('licence_verified_date')}."
        grades = "; ".join(f"{h}: {r[k].get('grade')}" for k, h in MATRIX_COLS)
        story.append(Paragraph(f"<b>{r['display_name']}</b> ({r['instrument_type']}). {licline} {grades}.", small))
    doc.build(story)

# CONFORMANCE GATE (schema 0.7 rule 24; rubric 1.6). registry_gate.gate() is the one code path: migrate_v0.9.py runs it
# before it writes and the build runs it before it publishes, so a rule the rubric states and the dataset breaks fails both.
sys.path.insert(0, str(HERE))
import registry_gate as _G
POP_SENSITIVE = _G.POP_SENSITIVE

def conformance_gate():
    problems, counts = _G.gate(BY_ID)
    for rec in RECORDS:
        rid = rec["instrument_id"]
        for rel in rec.get("relations") or []:
            if rel.get("type") not in REL_LABEL: problems.append(f"{rid}: unknown relation type {rel.get('type')!r}")
    if problems:
        raise SystemExit("CONFORMANCE GATE FAILED:\n  " + "\n  ".join(problems))
    print(f"gate: conformance clean ({counts['graded']} graded cells of {counts['cells']}, {counts['high']} High with precondition_evidence, "
          f"{counts['population_tagged_entries']} population-tagged entries, {counts['mixed_cells']} mixed cells naming a second form, "
          f"{counts['fallback_cells']} fallback flags)")

def write_matrix_csv():
    """Grade matrix CSV generated from the dataset (never hand-maintained): one row per parent instrument, one grade column
    per property with the flag or absence type beside it. Columns are in schema order; nothing is sorted on a grade."""
    import csv, io
    cols = [("structural_validity", "structural"), ("convergent_discriminant_validity", "convergent"),
            ("criterion_validity_reference_standard", "crit_reference"), ("criterion_validity_organisational", "crit_organisational"),
            ("internal_consistency", "internal_consistency"), ("test_retest_reliability", "test_retest"),
            ("measurement_invariance", "invariance"), ("responsiveness_mic", "responsiveness"), ("populations_languages_norms", "populations")]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["instrument_id", "display_name", "type"] + [c for _, c in cols for c in (c, c + "_flag")]
               + ["licence_class", "licence_verified", "n_citations", "dataset_version", "rubric_version"])
    for r in PARENTS:
        row = [r["instrument_id"], r["display_name"], r["instrument_type"]]
        for k, _ in cols:
            p = r.get(k) or {}
            g = p.get("grade") or ("not assessed" if p.get("evidence_state") == "not_assessed" else "")
            flag = ind_head(p.get("indirectness")) or p.get("absence_type") or ""
            row += [g, flag]
        ident = r.get("identity", {})
        row += [ident.get("licence_class", ""), ident.get("licence_verified_date", ""), len(r.get("citations") or []),
                D["version"], D.get("rubric", {}).get("version", "")]
        w.writerow(row)
    for dest in (SITE / "instrument-evidence-matrix-full.csv", HERE / "instrument-evidence-matrix-full.csv"):
        dest.write_text(buf.getvalue(), encoding="utf-8")

def check():
    """Regenerate into a temporary copy of site/, apply the stamping tool to it, and fail if any generated file
    (the PDF excepted: its bytes carry a build date) differs from the committed one. CI runs this so a change to
    the dataset, the rubric or this generator cannot merge without the pages that show it."""
    import shutil, subprocess, tempfile, filecmp
    committed = ROOT / "site" / "instrument-registry"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(ROOT / "site", tmp_site)
        env = dict(os.environ, OWHS_SITE_DIR=str(tmp_site))
        r = subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("[check] build failed:\n" + r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "stamp_canonical.py")], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("[check] stamp failed:\n" + r.stdout + r.stderr)
        fresh = tmp_site / "instrument-registry"
        names = sorted(p.name for p in fresh.iterdir() if p.suffix != ".pdf")
        stale = [n for n in names if not (committed / n).exists() or not filecmp.cmp(fresh / n, committed / n, shallow=False)]
        orphan = sorted(p.name for p in committed.iterdir() if p.suffix != ".pdf" and p.name not in names)
        if stale or orphan:
            sys.exit("site/instrument-registry is out of date; run registry/build_registry_site.py then tools/stamp_canonical.py\n"
                     + "".join(f"  differs: {n}\n" for n in stale) + "".join(f"  not generated: {n}\n" for n in orphan))
        print(f"up to date: site/instrument-registry ({len(names)} generated files match the source)")

def main():
    if "--check" in sys.argv:
        return check()
    conformance_gate()
    build_index(); build_how(); build_admission(); build_rubric(); build_corrections(); build_downloads(); build_single_items()
    for r in RECORDS: record_page(r)
    # data files into site
    for fn in [DATASET] + PREVIOUS:
        (SITE / fn).write_text((HERE / fn).read_text(encoding="utf-8"), encoding="utf-8")
    (SITE / RUBRIC_MD.name).write_text(RUBRIC_MD.read_text(encoding="utf-8"), encoding="utf-8")
    (SITE / ADMISSION_MD.name).write_text(ADMISSION_MD.read_text(encoding="utf-8"), encoding="utf-8")
    write_matrix_csv()
    build_pdf()

    # external links in new tabs
    for f in SITE.glob("*.html"):
        t = f.read_text(encoding="utf-8")
        t = t.replace('<a href="http', '<a target="_blank" rel="noopener" href="http')
        f.write_text(t, encoding="utf-8")

    # NEUTRALITY GATE: internal framing and vendor names must not appear in output.
    # Internal framing never appears in output. Vendor and product names are checked against an optional local
    # word list (OWHS_NEUTRALITY_TERMS, one regular expression per line) that the steward keeps outside this
    # repository, so the public build cannot itself name what it guards against. Absent the list, only the
    # generic terms are checked.
    FORBIDDEN = [r"IP boundary", r"boundary note"]
    extra = os.environ.get("OWHS_NEUTRALITY_TERMS")
    if extra and Path(extra).exists():
        FORBIDDEN += [l.strip() for l in Path(extra).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    hits = []
    for f in sorted(list(SITE.glob("*.html")) + [SITE / RUBRIC_MD.name, SITE / ADMISSION_MD.name, SITE / DATASET]):
        t = f.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            if re.search(pat, t, re.I):
                hits.append(f"{f.name}: {pat}")
    if hits:
        raise SystemExit("NEUTRALITY GATE FAILED:\n  " + "\n  ".join(hits))
    # em/en dash gate on output
    # (the dataset is exempt: citation titles are verbatim and two carry the publisher's en dash)
    dash = [f.name for f in list(SITE.glob("*.html")) + [SITE / RUBRIC_MD.name, SITE / ADMISSION_MD.name]
            if chr(8212) in f.read_text(encoding="utf-8") or chr(8211) in f.read_text(encoding="utf-8")]
    if dash:
        raise SystemExit("DASH GATE FAILED: " + ", ".join(dash))
    # FILTER-NEVER-SORT GATE (2 Sep 2026 scope review, A3): the registry may let a reader
    # filter on what evidence exists; it may never order instruments on a grade. No sort
    # control, no sortable attribute, no composite or overall score anywhere in output.
    RANKING = [r"data-sort", r"\bsortable\b", r"class=\"[^\"]*\bsort", r"onclick=\"[^\"]*sort",
               r"registry (composite|overall|total) score", r"league table", r"leaderboard",
               r"ranked by", r"strongest evidence overall", r"top instruments"]
    # (plain "composite score" / "aggregate score" are legitimate psychometric phrases in
    #  findings text, e.g. the ONS-4 record, so the gate targets registry-level ranking only)
    rank_hits = []
    for f in sorted(SITE.glob("*.html")):
        t = f.read_text(encoding="utf-8")
        for pat in RANKING:
            if re.search(pat, t, re.I):
                rank_hits.append(f"{f.name}: {pat}")
    if rank_hits:
        raise SystemExit("FILTER-NEVER-SORT GATE FAILED:\n  " + "\n  ".join(rank_hits))
    print("gates: neutrality clean, dashes clean, no sort or composite score")
    print(f"site built: {len(list(SITE.glob('*.html')))} pages + JSON/CSV/PDF")

if __name__ == "__main__":
    main()
