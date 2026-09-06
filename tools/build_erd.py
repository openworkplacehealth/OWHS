#!/usr/bin/env python3
"""Draw the entity map as one hand-laid SVG, in two labellings, and place each where the site shows it.

Source of truth for the relationships is spec/erd.mmd; this file lays those relationships out
on a fixed grid in the house figure style (the same frame, marks and colours as the figures on
how-it-works.html) so the map reads on one screen instead of a sideways scroll. The geometry
and relationships are the same in both labellings; only the title and three subtitles differ.

Writes  site/owhs-erd-v0.1.svg          the archived v0.1 drawing (the v0.1 specification page and archive)
        site/owhs-erd-current.svg       the current drawing (the v0.2 specification page and bundle)
and splices the current drawing between <!-- erd --> ... <!-- /erd --> markers in
        site/erd.html                   the full-size page
        site/standard.html              the entity-map figure

  python tools/build_erd.py            write every output (a second run makes no change)
  python tools/build_erd.py --check    regenerate in memory and fail on any difference, a missing marker pair or a duplicated one
Run from anywhere; paths are relative to the repository root.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.environ.get("OWHS_SITE_DIR", os.path.join(ROOT, "site"))    # overridable so the self-test can run against temporary copies

# House colours, written out because the SVG also renders as a plain <img>.
INK, BODY, MUTED, LINE = "#101418", "#33393f", "#5c646c", "#e3e6e9"
ACCENT, ACCENT_MID, ACCENT_SOFT, WASH, PAPER = "#0b6e5f", "#6fb0a4", "#e6f2f0", "#f6f7f8", "#ffffff"
RESERVED = "#9aa3ab"
MONO = "'IBM Plex Mono', ui-monospace, Menlo, monospace"
SANS = "Inter, system-ui, -apple-system, sans-serif"

W, H = 170, 46                       # box size
GAP = 68                             # column gap, wide enough for a short verb on the line
COLS = [20 + i * (W + GAP) for i in range(4)]      # left edges
ROWS = [40, 140, 240, 340, 440]      # top edges
RING_L = 8                           # the left margin line (Organisation reports DisabilityParticipation)
RING_R1 = COLS[3] + W + 16           # inner right margin line (AggregateReport references MeasurementContext)
RING_R2 = COLS[3] + W + 32           # outer right margin line (BenefitEntitlement tagged with ConstructDomain)
VIEW_W, VIEW_H = RING_R2 + 24, 540

# name, column, row, class, one-line purpose (from the entity catalogue)
BOXES = [
    ("Organisation",             0, 0, "org",    "the employer, outer boundary"),
    ("OrgUnit",                  1, 0, "org",    "team; smallest unit reported"),
    ("BenefitEntitlement",       2, 0, "org",    "what support the workforce has"),
    ("BenefitUtilisation",       3, 0, "org",    "counts per service per period"),
    ("WorkerPseudonym",          0, 1, "person", "opaque, per employer, banded"),
    ("AbsenceEpisode",           1, 1, "person", "one sickness absence"),
    ("ReturnToWorkOutcome",      2, 1, "person", "what happened after"),
    ("WorkplaceIncident",        0, 2, "reserved", "reserved, no fields in v0.1"),   # subtitle is relabelled per version, see LABELS
    ("OHEpisode",                1, 2, "person", "referral to fitness opinion"),
    ("ReasonableAdjustment",     2, 2, "person", "Equality Act s.20 adjustment"),
    ("AggregateReport",          3, 2, "output", "the only way results leave"),
    ("DisabilityParticipation",  0, 3, "org",    "org level, banded, n at least 10"),
    ("InstrumentAdministration", 1, 3, "person", "scores and band, never items"),
    ("WellbeingObservation",     2, 3, "person", "one item, one occasion"),
    ("BenchmarkRelease",         3, 3, "output", "comparison set, composition shown"),
    ("RiskAssessment",           0, 4, "reserved", "reserved, no fields in v0.1"),
    ("Crosswalk",                1, 4, "shared", "to HSE MS, ISO 45003, whiu:"),
    ("ConstructDomain",          2, 4, "shared", "one health-domain vocabulary"),
    ("MeasurementContext",       3, 4, "shared", "what makes scores comparable"),
]

# The two labellings. The archived drawing is the v0.1 release figure and never changes; the current drawing carries the
# neutral labels the current pages use. Everything else about the two drawings is identical.
LABELS = {
    "v0.1": {"title": "OWHS v0.1 entity map", "reserved": "reserved, no fields in v0.1", "AggregateReport": "the only way results leave"},
    "current": {"title": "OWHS entity map, drawn for v0.1 and unchanged in v0.2", "reserved": "reserved, no fields yet", "AggregateReport": "aggregate results for release"},
}
OUTPUTS = {"v0.1": "owhs-erd-v0.1.svg", "current": "owhs-erd-current.svg"}
PAGES = ("erd.html", "standard.html")   # the current drawing is spliced into these

STYLE = {
    "org":      dict(fill=PAPER,       stroke=BODY,       dash="",    name=INK,   sub=MUTED,   sw=1.4),
    "person":   dict(fill=ACCENT_SOFT, stroke=ACCENT_MID, dash="",    name=INK,   sub=MUTED,   sw=1.2),
    "output":   dict(fill=ACCENT,      stroke=ACCENT,     dash="",    name=PAPER, sub="#cfe5e0", sw=1.2),
    "shared":   dict(fill=WASH,        stroke="#b9c0c6",  dash="",    name=INK,   sub=MUTED,   sw=1.2),
    "reserved": dict(fill="none",      stroke=RESERVED,   dash="5 4", name=MUTED, sub=MUTED,   sw=1.2),
}


def box_geom(col, row):
    x, y = COLS[col], ROWS[row]
    return dict(x=x, y=y, l=x, r=x + W, t=y, b=y + H, cx=x + W // 2, cy=y + H // 2)


G = {name: box_geom(c, r) for name, c, r, *_ in BOXES}


def pts(*p):
    return "M " + " L ".join(f"{x} {y}" for x, y in p)


def curve(p0, p1):
    (x0, y0), (x1, y1) = p0, p1
    return f"M {x0} {y0} C {x0} {(y0 + y1) / 2:.0f} {x1} {(y0 + y1) / 2:.0f} {x1} {y1}"


# Each edge: path, kind (ref | agg | reserved), arrow at end?, label, label anchor (x, y), text-anchor, rotated?
EDGES = []


def edge(path, kind="ref", arrow=True, label=None, at=None, anchor="middle", rotate=False):
    EDGES.append((path, kind, arrow, label, at, anchor, rotate))


def word(label, at, anchor="middle", kind="ref"):
    EDGES.append((None, kind, False, label, at, anchor, False))


g = G
C = {n: G[n]["cx"] for n in G}
GX = [COLS[i] + W + GAP // 2 for i in range(3)]     # gap centres between columns
BUS1 = COLS[0] + W + 22                              # the subject-of bus, right of the pseudonym
BUS2 = COLS[2] + W + GAP // 2                        # the aggregation bus, left of the report
LANE_TOP, LANE_PROV, LANE_SCOPE, LANE_AGG = 8, 20, 100, 126
LANE_SUBJ, LANE_MEAS, LANE_RES, LANE_TAG = 313, 412, 508, 522
R = {n: G[n] for n in G}

# Identity
edge(pts((R["Organisation"]["r"], 63), (R["OrgUnit"]["l"], 63)), label="has", at=(GX[0], 57))
edge(pts((C["Organisation"], R["Organisation"]["b"]), (C["Organisation"], R["WorkerPseudonym"]["t"])),
     label="scopes", at=(C["Organisation"] + 7, 118), anchor="start")
edge(curve((R["OrgUnit"]["l"] + 22, R["OrgUnit"]["b"]), (R["WorkerPseudonym"]["r"] - 14, R["WorkerPseudonym"]["t"])),
     label="groups", at=(R["OrgUnit"]["l"] + 6, 118), anchor="start")
edge(pts((R["Organisation"]["l"], 63), (RING_L, 63), (RING_L, 363), (R["DisabilityParticipation"]["l"], 363)),
     label="reports", at=(RING_L + 6, 226), anchor="start")
edge(pts((C["Organisation"], R["Organisation"]["t"]), (C["Organisation"], LANE_PROV), (C["BenefitEntitlement"], LANE_PROV),
         (C["BenefitEntitlement"], R["BenefitEntitlement"]["t"])), label="provides", at=(C["OrgUnit"], LANE_PROV - 5))
edge(pts((R["BenefitEntitlement"]["r"], 63), (R["BenefitUtilisation"]["l"], 63)), label="used via", at=(GX[2], 57))

# The subject-of bus: one line from the pseudonym, five records hang off it
edge(pts((R["WorkerPseudonym"]["r"], 163), (BUS1, 163), (BUS1, 363), (R["InstrumentAdministration"]["l"], 363)))
edge(pts((BUS1, 163), (R["AbsenceEpisode"]["l"], 163)))
edge(pts((BUS1, 263), (R["OHEpisode"]["l"], 263)))
edge(pts((BUS1, LANE_SUBJ), (C["ReasonableAdjustment"], LANE_SUBJ), (C["ReasonableAdjustment"], R["ReasonableAdjustment"]["b"])))
edge(pts((C["ReasonableAdjustment"], LANE_SUBJ), (C["ReasonableAdjustment"], R["WellbeingObservation"]["t"])))
word("subject of", (BUS1 + 6, 236), "start")

# Absence, adjustment, OH
edge(pts((R["AbsenceEpisode"]["r"], 163), (R["ReturnToWorkOutcome"]["l"], 163)), label="resolved by", at=(GX[1], 157))
edge(pts((R["OHEpisode"]["r"], 263), (R["ReasonableAdjustment"]["l"], 263)), label="recommends", at=(GX[1], 257))
edge(curve((R["OHEpisode"]["r"] - 18, R["OHEpisode"]["t"]), (R["ReturnToWorkOutcome"]["l"] + 20, R["ReturnToWorkOutcome"]["b"])),
     label="informs", at=(R["OHEpisode"]["r"] - 10, 216), anchor="start")
edge(pts((R["ReasonableAdjustment"]["r"] - 35, R["ReasonableAdjustment"]["t"]), (R["ReasonableAdjustment"]["r"] - 35, R["ReturnToWorkOutcome"]["b"])),
     label="enacted in", at=(R["ReasonableAdjustment"]["r"] - 29, 216), anchor="start")

# Measurement: both records measure the shared domain and sit under a context
edge(pts((C["InstrumentAdministration"], R["InstrumentAdministration"]["b"]), (C["InstrumentAdministration"], LANE_MEAS),
         (C["MeasurementContext"], LANE_MEAS), (C["MeasurementContext"], R["MeasurementContext"]["t"])))
edge(pts((C["WellbeingObservation"], R["WellbeingObservation"]["b"]), (C["WellbeingObservation"], R["ConstructDomain"]["t"])))
word("measures, scores", (C["WellbeingObservation"] + 6, LANE_MEAS + 16), "start")
word("produced under", (C["MeasurementContext"] - 6, LANE_MEAS + 16), "end")

# Benefits tag the same domain vocabulary (the outer ring)
edge(pts((C["BenefitEntitlement"] + 60, R["BenefitEntitlement"]["t"]), (C["BenefitEntitlement"] + 60, LANE_TOP), (RING_R2, LANE_TOP),
         (RING_R2, LANE_TAG), (C["ConstructDomain"] + 35, LANE_TAG), (C["ConstructDomain"] + 35, R["ConstructDomain"]["b"])),
     label="tagged with", at=(RING_R2 + 10, 300), rotate=True)

# Aggregation flow into the report (dotted), then the benchmark
edge(pts((C["AbsenceEpisode"], R["AbsenceEpisode"]["t"]), (C["AbsenceEpisode"], LANE_AGG), (BUS2, LANE_AGG), (BUS2, 263),
         (R["AggregateReport"]["l"], 263)), kind="agg")
edge(pts((R["ReturnToWorkOutcome"]["r"], 163), (BUS2, 163)), kind="agg", arrow=False)
edge(pts((R["WellbeingObservation"]["r"], 363), (BUS2, 363), (BUS2, 263)), kind="agg", arrow=False)
edge(pts((C["BenefitUtilisation"], R["BenefitUtilisation"]["b"]), (C["BenefitUtilisation"], R["AggregateReport"]["t"])),
     kind="agg", label="aggregated into", at=(C["BenefitUtilisation"] + 6, 166), anchor="start")
word("aggregated into", (BUS2 - 6, 236), "end", kind="agg")
edge(pts((C["BenchmarkRelease"], R["BenchmarkRelease"]["t"]), (C["BenchmarkRelease"], R["AggregateReport"]["b"])),
     label="composed from", at=(C["BenchmarkRelease"] + 6, 318), anchor="start")
edge(pts((R["AggregateReport"]["l"] + 24, R["AggregateReport"]["t"]), (R["AggregateReport"]["l"] + 24, LANE_SCOPE),
         (C["OrgUnit"] + 35, LANE_SCOPE), (C["OrgUnit"] + 35, R["OrgUnit"]["b"])), label="scoped to", at=(GX[1] + 30, LANE_SCOPE - 5))
edge(pts((R["AggregateReport"]["r"], 275), (RING_R1, 275), (RING_R1, 463), (R["MeasurementContext"]["r"], 463)),
     label="references", at=(RING_R1 + 9, 380), rotate=True)

# Shared definitions
edge(pts((R["Crosswalk"]["r"], 463), (R["ConstructDomain"]["l"], 463)), label="maps", at=(GX[1], 457))

# Reserved names, dashed and unarrowed
edge(pts((C["WorkplaceIncident"], R["WorkplaceIncident"]["t"]), (C["WorkplaceIncident"], R["WorkerPseudonym"]["b"])), kind="reserved",
     arrow=False, label="reserved", at=(C["WorkplaceIncident"] + 7, 216), anchor="start")
edge(pts((C["RiskAssessment"], R["RiskAssessment"]["b"]), (C["RiskAssessment"], LANE_RES), (C["ConstructDomain"], LANE_RES),
         (C["ConstructDomain"], R["ConstructDomain"]["b"])), kind="reserved", arrow=False,
     label="reserved", at=(C["Crosswalk"], LANE_RES - 5))


def svg(version="current", inline=False):
    labels = LABELS[version]
    o = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" role="img" '
             f'aria-labelledby="erd-title erd-desc" font-family="{SANS}">')
    o.append(f'<title id="erd-title">{labels["title"]}</title>')
    o.append('<desc id="erd-desc">Nineteen boxes on a grid: organisation-level entities across the top, '
             'the worker pseudonym and its individual-level records in the middle, the shared definitions along '
             'the bottom, the aggregate report and benchmark release on the right, and two reserved names. '
             'Solid lines are structural references, dotted lines are the aggregation flow into the report, '
             'dashed lines mark reserved names.</desc>')
    o.append('<defs>'
             f'<marker id="erd-ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{ACCENT_MID}"/></marker>'
             f'<marker id="erd-ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{ACCENT}"/></marker>'
             '</defs>')
    o.append(f'<rect x="0" y="0" width="{VIEW_W}" height="{VIEW_H}" fill="{PAPER}"/>')
    # paths first, then every label, then the boxes, so nothing is drawn over a word
    for path, kind, arrow, label, at, anchor, rotate in EDGES:
        if not path:
            continue
        if kind == "agg":
            attrs = f'stroke="{ACCENT}" stroke-width="1.3" stroke-dasharray="2 4" stroke-linecap="round"'
            mk = ' marker-end="url(#erd-ag)"' if arrow else ""
        elif kind == "reserved":
            attrs = f'stroke="{RESERVED}" stroke-width="1.2" stroke-dasharray="5 4"'
            mk = ""
        else:
            attrs = f'stroke="{ACCENT_MID}" stroke-width="1.3"'
            mk = ' marker-end="url(#erd-ar)"' if arrow else ""
        o.append(f'<path d="{path}" fill="none" {attrs} stroke-linejoin="round"{mk}/>')
    for path, kind, arrow, label, at, anchor, rotate in EDGES:
        if not label:
            continue
        x, y = at
        colour = RESERVED if kind == "reserved" else (ACCENT if kind == "agg" else MUTED)
        tr = f' transform="rotate(-90 {x} {y})"' if rotate else ""
        o.append(f'<text x="{x}" y="{y}"{tr} font-family="{MONO}" font-size="9.5" fill="{colour}" text-anchor="{anchor}" '
                 f'paint-order="stroke" stroke="{PAPER}" stroke-width="4" stroke-linejoin="round">{label}</text>')
    for name, c, r, cls, sub in BOXES:
        if cls == "reserved":
            sub = labels["reserved"]
        elif name in labels:
            sub = labels[name]
        s = STYLE[cls]
        b = G[name]
        dash = f' stroke-dasharray="{s["dash"]}"' if s["dash"] else ""
        o.append(f'<g><rect x="{b["x"]}" y="{b["y"]}" width="{W}" height="{H}" rx="6" fill="{s["fill"]}" '
                 f'stroke="{s["stroke"]}" stroke-width="{s["sw"]}"{dash}/>')
        o.append(f'<text x="{b["cx"]}" y="{b["y"] + 20}" text-anchor="middle" font-family="{MONO}" font-size="10.5" '
                 f'font-weight="500" fill="{s["name"]}">{name}</text>')
        o.append(f'<text x="{b["cx"]}" y="{b["y"] + 35}" text-anchor="middle" font-size="9.5" fill="{s["sub"]}">{sub}</text></g>')
    o.append("</svg>")
    return "\n".join(o)


MARK_OPEN, MARK_CLOSE = "<!-- erd -->", "<!-- /erd -->"


def spliced(text, drawing, path):
    """The page text with the drawing between its one ordered marker pair; a missing, duplicated or reversed marker is refused, never chosen silently."""
    opens, closes = text.count(MARK_OPEN), text.count(MARK_CLOSE)
    if opens != 1 or closes != 1:
        raise SystemExit(f"PROBLEM {path}: expected one erd marker pair, found {opens} opening and {closes} closing markers")
    if text.index(MARK_OPEN) > text.index(MARK_CLOSE):
        raise SystemExit(f"PROBLEM {path}: the closing erd marker precedes the opening one; nothing was written")
    new, n = re.subn(re.escape(MARK_OPEN) + r".*?" + re.escape(MARK_CLOSE), lambda m: MARK_OPEN + "\n" + drawing + "\n" + MARK_CLOSE, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"PROBLEM {path}: the erd marker pair did not match as one complete span; nothing was written")
    return new


def standalone(version):
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg(version) + "\n"


def expected_outputs():
    """Every output as fresh generation would write it: (path, text)."""
    out = [(os.path.join(SITE, name), standalone(version)) for version, name in OUTPUTS.items()]
    current = svg("current")
    for page in PAGES:
        p = os.path.join(SITE, page)
        out.append((p, spliced(open(p, encoding="utf-8").read(), current, p)))
    return out


def check():
    problems = []
    for path, text in expected_outputs():
        rel = os.path.relpath(path, ROOT)
        if not os.path.exists(path):
            problems.append(f"{rel} is missing")
        elif open(path, encoding="utf-8").read() != text:
            problems.append(f"{rel} differs from fresh generation")
    if problems:
        print("PROBLEM " + "; ".join(problems) + "; run python tools/build_erd.py")
        return 1
    print(f"up to date: {', '.join(OUTPUTS.values())} and the spliced drawing on {', '.join(PAGES)} match fresh generation; "
          f"{len(BOXES)} boxes, {sum(1 for e in EDGES if e[0])} edges, one marker pair per page")
    return 0


def self_test():
    """The marker contract against temporary copies: reversed, missing and duplicated markers are refused with the copy unchanged; a good copy regenerates and checks."""
    import hashlib
    import shutil
    import subprocess
    import tempfile
    failures = 0
    me = os.path.abspath(__file__)
    real_site = os.path.join(ROOT, "site")
    with tempfile.TemporaryDirectory() as tmp:
        site = os.path.join(tmp, "site")
        os.makedirs(site)
        for name in list(OUTPUTS.values()) + list(PAGES):
            shutil.copy(os.path.join(real_site, name), os.path.join(site, name))
        env = dict(os.environ, OWHS_SITE_DIR=site)
        good = open(os.path.join(site, "erd.html"), encoding="utf-8").read()
        variants = {
            "reversed markers": good.replace(MARK_OPEN, "\x00").replace(MARK_CLOSE, MARK_OPEN).replace("\x00", MARK_CLOSE),
            "missing closing marker": good.replace(MARK_CLOSE, "", 1),
            "duplicated opening marker": good.replace(MARK_OPEN, MARK_OPEN + "\n" + MARK_OPEN, 1),
        }
        for label, text in variants.items():
            for mode in ("--check", "write"):
                open(os.path.join(site, "erd.html"), "w", encoding="utf-8").write(text)
                before = hashlib.sha256(text.encode("utf-8")).hexdigest()
                args = [sys.executable, "-B", me] + ([mode] if mode == "--check" else [])
                r = subprocess.run(args, capture_output=True, text=True, env=env)
                after = hashlib.sha256(open(os.path.join(site, "erd.html"), "rb").read()).hexdigest()
                ok = r.returncode != 0 and "PROBLEM" in (r.stdout + r.stderr) and before == after
                failures += not ok
                print(("ok  " if ok else "FAIL"), f"{label}: {mode} refuses by name and leaves the page unchanged", "" if ok else (r.stdout + r.stderr)[-200:])
        open(os.path.join(site, "erd.html"), "w", encoding="utf-8").write(good)
        r = subprocess.run([sys.executable, "-B", me, "--check"], capture_output=True, text=True, env=env)
        ok = r.returncode == 0
        failures += not ok
        print(("ok  " if ok else "FAIL"), "an unchanged copy passes --check", "" if ok else r.stdout[-200:])
        r = subprocess.run([sys.executable, "-B", me], capture_output=True, text=True, env=env)
        r2 = subprocess.run([sys.executable, "-B", me], capture_output=True, text=True, env=env)
        ok = r.returncode == 0 and r2.returncode == 0 and "written" not in r2.stdout
        failures += not ok
        print(("ok  " if ok else "FAIL"), "a second writer run makes no change", "" if ok else r2.stdout[-200:])
    print(f"self-test: {'all' if not failures else failures} {'checks passed' if not failures else 'checks FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    for path, text in expected_outputs():
        rel = os.path.relpath(path, ROOT)
        changed = open(path, encoding="utf-8").read() != text if os.path.exists(path) else True
        if changed:
            open(path, "w", encoding="utf-8").write(text)
        print(f"{rel}: {'written' if changed else 'unchanged'}")
    print(f"{len(BOXES)} boxes, {sum(1 for e in EDGES if e[0])} edges")
