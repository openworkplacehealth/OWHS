#!/usr/bin/env python3
"""Checks on the versioned code lists, their archive, the absence-reason crosswalk and version resolution.

    python tools/check_codelist_mappings.py --self-test
    OWHS_ONS_WORKBOOK=/path/to/sicknessabsence2025.xlsx python tools/check_codelist_mappings.py --self-test

What is checked: the registry lists exactly 24 code lists and resolves every pinned version to a file; archived
files are byte-identical to the pinned originals and no command here writes a code list; absence-reason@0.2.0
carries the eleven ONS rows once each with no Total row, keeps the four previously omitted categories distinct,
and maps neither non-disclosure nor missing data to Other; no legacy Other is upgraded by default; the v0.1
AbsenceEpisode schema still accepts its six codes and rejects the new ones; the v0.2 schema accepts all eleven
and rejects an unknown code while keeping the v0.1 structural rules; org-size-band keeps its codes and bounds
with the boundary values classified as before; when the ONS workbook is supplied its hash and cells A5:A16 of
Tables 4, 4a and 5 are read from the worksheet XML and compared with the crosswalk.

Nothing here validates a real payload's reason against a diagnosis or converts any recorded value.
"""
import hashlib, json, os, subprocess, sys, tempfile, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
CL = ROOT / "codelists"
VALIDATE = ROOT / "tools" / "validate.py"
LEGACY_CODES = ["minor-illness", "musculoskeletal", "mental-health", "respiratory", "gastrointestinal", "other"]
NEW_CODES = ["eye-ear-nose-mouth-dental", "genito-urinary", "heart-blood-pressure-circulation", "headaches-migraines"]
NON_DISCLOSURE = "prefers-not-to-give-details"
EXPECTED_ROWS = [("A5", "Minor illnesses"), ("A6", "Musculoskeletal problems"), ("A7", "Other"), ("A8", "Mental health conditions"),
                 ("A9", "Gastrointestinal problems"), ("A10", "Respiratory conditions"), ("A11", "Eye/ear/nose/mouth/dental problems"),
                 ("A12", "Genito-urinary problems"), ("A13", "Heart, blood pressure, circulation problems"), ("A14", "Headaches and migraines"),
                 ("A15", "Prefers not to give details")]


def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))


def resolve(name, version):
    """The file for name@version through the registry's versions map; None when the version was never released."""
    for entry in load(CL / "_registry.json")["lists"]:
        if entry["name"] == name:
            f = entry.get("versions", {}).get(version)
            return CL / f if f else None
    return None


def size_band(headcount):
    """The org-size-band code for an integer headcount, or None: negative, fractional and missing values have no band."""
    if isinstance(headcount, bool) or not isinstance(headcount, int) or headcount < 0:
        return None
    for v in load(CL / "org-size-band.json")["values"]:
        lo, hi = v["min_inclusive"], v["max_inclusive"]
        if headcount >= lo and (hi is None or headcount <= hi):
            return v["code"]
    return None


def validate(schema, instance):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(instance, f); p = f.name
    r = subprocess.run([sys.executable, str(VALIDATE), str(schema), p], capture_output=True, text=True, env={**os.environ, "OWHS_ASSERT_NO_NETWORK": "1"})
    Path(p).unlink()
    return r.returncode, r.stdout + r.stderr


def workbook_rows(path):
    """(sheet, cell, label without footnote markers) for A5:A16 of Tables 4, 4a and 5, read from the worksheet XML."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml")); rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    sheets = {s.get("name"): target[s.get(f"{{{ns['r']}}}id")] for s in wb.find("m:sheets", ns)}
    strings = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    out = {}
    for name in ("Table 4", "Table 4a", "Table 5"):
        x = ET.fromstring(z.read("xl/" + sheets[name].lstrip("/").removeprefix("xl/")))
        for c in x.iter(f"{{{ns['m']}}}c"):
            v = c.find("m:v", ns)
            if v is not None and c.get("r") in [f"A{i}" for i in range(5, 17)]:
                text = strings[int(v.text)] if c.get("t") == "s" else v.text
                out[(name, c.get("r"))] = text.split(" [note")[0].strip()
    return out


def main():
    checks = []
    def check(label, ok, detail=""):
        checks.append(ok); print(("ok  " if ok else "FAIL"), label, "" if ok else detail)

    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in CL.rglob("*.json")}
    reg = load(CL / "_registry.json")
    check("registry lists exactly 24 code lists", len(reg["lists"]) == 24, str(len(reg["lists"])))
    check("the crosswalk is registered as a mapping, not a 25th list", any(m["id"] == "absence-reason-ons-2025" for m in reg.get("mappings", [])) and not any(l["name"] == "absence-reason-ons-2025" for l in reg["lists"]))
    unresolved = [(l["name"], v) for l in reg["lists"] for v, f in l.get("versions", {}).items() if not (CL / f).exists()]
    check("every registered version resolves to an existing file", not unresolved, str(unresolved))
    current_mismatch = [l["name"] for l in reg["lists"] if load(CL / l["file"]).get("version") != l["version"] or l.get("versions", {}).get(l["version"]) != l["file"]]
    check("each list's current version matches its file and its versions map", not current_mismatch, str(current_mismatch))
    for name, ver, pinned in (("absence-reason", "0.1.0", "6b8c"), ("org-size-band", "0.1.0", "")):
        f = resolve(name, ver)
        check(f"{name}@{ver} resolves to the archive, not the current file", f is not None and f.parent.name == "archive" and load(f)["version"] == ver, str(f))
    check("absence-reason@0.9.9 was never released and does not resolve", resolve("absence-reason", "0.9.9") is None)
    check("the archived absence-reason@0.1.0 carries the six legacy codes unchanged", [v["code"] for v in load(resolve("absence-reason", "0.1.0"))["values"]] == LEGACY_CODES)
    ar_old = load(resolve("absence-reason", "0.1.0")); ar_old_git = subprocess.run(["git", "-C", str(ROOT), "show", "8b1bf90:codelists/absence-reason.json"], capture_output=True, text=True)
    if ar_old_git.returncode == 0:
        check("archived absence-reason@0.1.0 is byte-identical to the pinned original (public main 8b1bf90)", resolve("absence-reason", "0.1.0").read_bytes().decode() == ar_old_git.stdout)
        osb_git = subprocess.run(["git", "-C", str(ROOT), "show", "8b1bf90:codelists/org-size-band.json"], capture_output=True, text=True).stdout
        check("archived org-size-band@0.1.0 is byte-identical to the pinned original (public main 8b1bf90)", resolve("org-size-band", "0.1.0").read_bytes().decode() == osb_git)
    else:
        print("skip archive byte comparison with the pinned commit: not a git checkout")

    ar = load(CL / "absence-reason.json"); xw = load(CL / "mappings" / "absence-reason-ons-2025-v1.json")
    codes = [v["code"] for v in ar["values"]]
    check("absence-reason is 0.2.0 with eleven values", ar["version"] == "0.2.0" and len(codes) == 11 and len(set(codes)) == 11)
    check("registry counts eleven absence-reason values", next(l for l in reg["lists"] if l["name"] == "absence-reason")["values"] == 11)
    check("crosswalk targets absence-reason@0.2.0 and records the source hash and tables", xw["target"] == "absence-reason@0.2.0" and len(xw["source_sha256"]) == 64 and xw["source_tables"] == ["Table 4", "Table 4a", "Table 5"])
    rows = xw["rows"]
    check("eleven rows, A5 to A15 once each, no Total", [r["source_cell"] for r in rows] == [c for c, _ in EXPECTED_ROWS] and not any("total" in r["source_label"].lower() for r in rows))
    check("each row's target code is a list value and each list value has one row", sorted(r["target_code"] for r in rows) == sorted(codes))
    check("source labels match the workbook categories as expected", [r["source_label"] for r in rows] == [l for _, l in EXPECTED_ROWS])
    check("the four previously omitted categories are distinct codes with no legacy mapping", all(next(r for r in rows if r["target_code"] == c)["legacy_relation"] == "no_exact_mapping" and next(r for r in rows if r["target_code"] == c)["legacy_code"] is None for c in NEW_CODES))
    nd = next(r for r in rows if r["target_code"] == NON_DISCLOSURE)
    check("non-disclosure is unmappable and never Other", nd["legacy_code"] is None and nd["legacy_relation"] == "unmappable_non_disclosure" and "other" not in nd["target_code"])
    check("source Other is the ambiguous residual, retained as other", next(r for r in rows if r["source_cell"] == "A7")["legacy_relation"] == "ambiguous_residual" and next(r for r in rows if r["source_cell"] == "A7")["target_code"] == "other")
    check("the five retained categories map to their legacy codes", all(r["legacy_code"] == r["target_code"] and r["legacy_relation"] == "retained" for r in rows if r["target_code"] in set(LEGACY_CODES) - {"other"}))
    check("legacy policy forbids automatic upgrade of Other and splitting an aggregate", "Do not automatically upgrade a legacy Other value" in xw["legacy_policy"] and "Never infer" in xw["legacy_policy"])
    check("missing data is not converted to non-disclosure", "not converted" in xw.get("missing_data", ""))
    check("no roll-up of a new category is a default conversion", all("not a default conversion" in r.get("explanatory_note", "") for r in rows if r["legacy_relation"] == "no_exact_mapping"))

    v1, v2 = ROOT / "schemas" / "AbsenceEpisode.json", ROOT / "schemas" / "v0.2" / "AbsenceEpisode.json"
    check("v0.1 schema enum is the six legacy codes, pinned at 0.1.0", load(v1)["properties"]["reasonCode"]["enum"] == LEGACY_CODES and "absence-reason@0.1.0" in load(v1)["properties"]["reasonCode"]["$comment"])
    check("schemas/v0.1/AbsenceEpisode.json is byte-identical to the entry point", (ROOT / "schemas" / "v0.1" / "AbsenceEpisode.json").read_bytes() == v1.read_bytes())
    check("v0.2 schema enum is the eleven codes, pinned at 0.2.0", load(v2)["properties"]["reasonCode"]["enum"] == codes and "absence-reason@0.2.0" in load(v2)["properties"]["reasonCode"]["$comment"])
    base = load(ROOT / "examples" / "v0.2" / "AbsenceEpisode.valid.json"); base.pop("ext", None)
    for code in LEGACY_CODES:
        rc1, _ = validate(v1, {**base, "reasonCode": code}); rc2, _ = validate(v2, {**base, "reasonCode": code})
        check(f"{code}: accepted by v0.1 and v0.2", rc1 == 0 and rc2 == 0, f"v0.1 exit {rc1}, v0.2 exit {rc2}")
    for code in NEW_CODES + [NON_DISCLOSURE]:
        rc1, out1 = validate(v1, {**base, "reasonCode": code}); rc2, _ = validate(v2, {**base, "reasonCode": code})
        check(f"{code}: rejected by v0.1 with an enum error, accepted by v0.2", rc1 == 1 and "[enum]" in out1 and rc2 == 0, f"v0.1 exit {rc1}, v0.2 exit {rc2}")
    rc, out = validate(v2, {**base, "reasonCode": "unknown"}); check("v0.2 rejects an unknown code", rc == 1 and "[enum]" in out)
    rc, out = validate(v2, {**base, "reasonCode": None}); check("v0.2 rejects a null reason: missing is not guessed", rc == 1)
    rc, out = validate(v2, {**base, "startDate": "2026-03-10", "endDate": "2026-03-01"}); check("v0.2 keeps the v0.1 chronology rule C1", rc == 1 and "[C1]" in out)
    rc, out = validate(v2, {**base, "startDate": "banana"}); check("v0.2 keeps the v0.1 date format check", rc == 1 and "[format]" in out)
    rc, out = validate(v2, {**base, "name": "x"}); check("v0.2 keeps the v0.1 closed object", rc == 1 and "additionalProperties" in out)

    osb = load(CL / "org-size-band.json"); old = load(resolve("org-size-band", "0.1.0"))
    check("org-size-band is 0.1.1 with the same four codes in the same order", osb["version"] == "0.1.1" and [v["code"] for v in osb["values"]] == [v["code"] for v in old["values"]])
    check("org-size-band anchor no longer claims a Companies Act classification", "Not a Companies Act" in osb["anchor"] and "Companies Act 2006 size classification" not in osb["anchor"])
    check("bounds: 0 and 9 micro, 10 and 49 small, 50 and 249 medium, 250 and 10000 large", [size_band(n) for n in (0, 9, 10, 49, 50, 249, 250, 10000)] == ["micro", "micro", "small", "small", "medium", "medium", "large", "large"])
    check("negative, fractional, boolean and missing headcounts have no band", [size_band(x) for x in (-1, 2.5, True, None, "12")] == [None] * 5)
    check("bounds are contiguous with no gap or overlap", all(osb["values"][i]["max_inclusive"] + 1 == osb["values"][i + 1]["min_inclusive"] for i in range(3)) and osb["values"][3]["max_inclusive"] is None)

    wb = os.environ.get("OWHS_ONS_WORKBOOK")
    if wb:
        digest = hashlib.sha256(Path(wb).read_bytes()).hexdigest()
        check("supplied ONS workbook hash matches the crosswalk's source_sha256", digest == xw["source_sha256"], digest)
        cells = workbook_rows(wb)
        for sheet in ("Table 4", "Table 4a", "Table 5"):
            check(f"{sheet} A5:A15 match the crosswalk rows and A16 is the total", [cells.get((sheet, c)) for c, _ in EXPECTED_ROWS] == [l for _, l in EXPECTED_ROWS] and cells.get((sheet, "A16")) == "Total")
    else:
        print("skip workbook cell comparison: set OWHS_ONS_WORKBOOK to the downloaded sicknessabsence2025.xlsx (sha256 recorded in the crosswalk)")

    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in CL.rglob("*.json")}
    check("no code list, archive or mapping file was written by these checks", before == after)
    print(f"{sum(checks)}/{len(checks)} checks passed")
    sys.exit(0 if all(checks) else 1)


if __name__ == "__main__":
    if "--self-test" not in sys.argv:
        sys.exit("usage: check_codelist_mappings.py --self-test")
    main()
