#!/usr/bin/env python3
"""The v0.1 release archive served at site/spec/owhs-v0.1-bundle.zip is the published one, byte for byte.

Usage: python tools/check_v01_archive.py

The archive was published from the v0.1 specification and never rebuilt; the current bundle is owhs-v0.2-bundle.zip.
This check holds the published archive's identity (source commit, SHA-256, member count, the three v0.1 schema members,
the absence of any v0.2 result section, and the hash of the corrected v0.1 publication copy it carries) and refuses any
substitute, including a prepared mixed-version bundle under the same name.
"""
import hashlib
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "site" / "spec" / "owhs-v0.1-bundle.zip"
SOURCE_COMMIT = "ddbf9ac627b4d481ad8bfb2ae5fe54f65c613caa"          # public main when the archive was frozen
ARCHIVE_SHA256 = "02a141b737f6bbc8da8a7f10db2bb0a2fdfc14a9d816ac891bc1fc9ed6c327cb"
MEMBERS = 48
SCHEMAS = {"schemas/AbsenceEpisode.json", "schemas/ReturnToWorkOutcome.json", "schemas/OHEpisode.json"}
SPEC_MEMBER = "spec/OWHS-v0.1-draft.md"
SPEC_SHA256 = "089eb2028cc9e749937ea0b5dbc51baf6da93ccd37ec085d2c57c78d5c7c6991"   # the corrected v0.1 publication copy


def problems(path=ARCHIVE):
    found = []
    if not path.exists():
        return [f"{path.relative_to(ROOT)} is missing"]
    b = path.read_bytes()
    if hashlib.sha256(b).hexdigest() != ARCHIVE_SHA256:
        found.append(f"the archive's SHA-256 is not the published {ARCHIVE_SHA256[:12]} (source commit {SOURCE_COMMIT[:7]})")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return found + ["the archive is not a zip file"]
    names = z.namelist()
    if len(names) != MEMBERS:
        found.append(f"the archive holds {len(names)} members, not {MEMBERS}")
    schemas = {n for n in names if n.startswith("schemas/")}
    if schemas != SCHEMAS:
        found.append(f"the archive's schema members are {sorted(schemas)}, not the three v0.1 schemas")
    if any("v0_2" in n or "v0.2" in n or "results_v0_2" in n for n in names):
        found.append("the archive carries a v0.2 member; the v0.1 archive has none")
    if SPEC_MEMBER not in names:
        found.append(f"the archive lacks {SPEC_MEMBER}")
    elif hashlib.sha256(z.read(SPEC_MEMBER)).hexdigest() != SPEC_SHA256:
        found.append("the archive's specification member is not the corrected v0.1 publication copy")
    return found


def main(argv):
    found = problems()
    if found:
        print("PROBLEM " + "; ".join(found))
        return 1
    print(f"ok: site/spec/owhs-v0.1-bundle.zip is the published v0.1 release archive ({MEMBERS} members, three v0.1 schemas, no v0.2 member, corrected publication copy; SHA-256 {ARCHIVE_SHA256[:12]}, frozen at {SOURCE_COMMIT[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
