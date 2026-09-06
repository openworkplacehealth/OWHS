#!/usr/bin/env python3
"""Rebuild site/spec/owhs-v0.2-bundle.zip from the repository tree: both specification versions as published under site/spec/
(v0.2 current, v0.1 archive, each labelled by its file name), the ERD, the versioned schemas and catalogue, examples, code lists,
validator and checkers, licences, notice, governance, decisions and README. The earlier owhs-v0.1-bundle.zip is left as an archive.
The domain routing table is not part of the release and is never included. Deterministic file order."""
import pathlib, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "spec" / "owhs-v0.2-bundle.zip"
ARCHIVE = ROOT / "site" / "spec" / "owhs-v0.1-bundle.zip"   # the published v0.1 release archive; left untouched
FILES = {  # archive path -> source path
    "spec/OWHS-v0.2-draft.md": ROOT / "site" / "spec" / "OWHS-v0.2-draft.md",           # current
    "spec/OWHS-v0.1-draft.md": ROOT / "site" / "spec" / "OWHS-v0.1-draft.md",           # archive
    "spec/erd.mmd": ROOT / "spec" / "erd.mmd",
    "owhs-erd-v0.1.svg": ROOT / "site" / "owhs-erd-v0.1.svg",
    "owhs-erd-current.svg": ROOT / "site" / "owhs-erd-current.svg",
    "README.md": ROOT / "README.md", "GOVERNANCE.md": ROOT / "GOVERNANCE.md", "DECISIONS.md": ROOT / "DECISIONS.md",
    "LICENSE": ROOT / "LICENSE", "LICENSE-DOCS.md": ROOT / "LICENSE-DOCS.md", "NOTICE": ROOT / "NOTICE", "tools/validate.py": ROOT / "tools" / "validate.py",
}
SUBDIRS = {"schemas": ("v0.1", "v0.2", "bundles"), "examples": ("v0.2", "bundles/v0.2", "bundles/v0.2/cases"), "codelists": ("archive", "mappings")}   # versioned sets, the graph envelope, fixtures, archived lists and the crosswalk
for d, subs in SUBDIRS.items():
    for p in sorted((ROOT / d).glob("*.json")):
        FILES[f"{d}/{p.name}"] = p
    for sub in subs:
        for p in sorted((ROOT / d / sub).glob("*.json")):
            FILES[f"{d}/{sub}/{p.name}"] = p
for p in sorted((ROOT / "profiles").rglob("*.json")):
    FILES[f"profiles/{p.relative_to(ROOT / 'profiles').as_posix()}"] = p
FILES["docs/entity-graph-validation-v0.2.md"] = ROOT / "docs" / "entity-graph-validation-v0.2.md"
for t in ("check_profiles.py", "check_measurement.py", "check_codelist_mappings.py", "check_remaining_entities.py", "check_entity_graph.py"):
    FILES[f"tools/{t}"] = ROOT / "tools" / t
assert not any("domain-coverage" in k or "domain_routing" in k for k in FILES)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for arc, src in sorted(FILES.items()):
        z.write(src, arc)
print(f"bundle written: {OUT.relative_to(ROOT)} ({len(FILES)} files)")

# Publish-time mirror: the site serves its own copies of the schemas, examples and code lists, so a reader
# downloading from the site gets the same bytes as the repository. Keeping them in step by hand
# is how the validation-report link came to be right in one copy and wrong in the other.
import shutil
for d, subs in SUBDIRS.items():
    dest = ROOT / "site" / "spec" / d
    if dest.is_dir():
        for p in dest.glob("*.json"):
            p.unlink()
        for p in sorted((ROOT / d).glob("*.json")):
            shutil.copy2(p, dest / p.name)
        for sub in subs:
            if (ROOT / d / sub).is_dir():
                (dest / sub).mkdir(parents=True, exist_ok=True)
                for p in (dest / sub).glob("*.json"):
                    p.unlink()
                for p in sorted((ROOT / d / sub).glob("*.json")):
                    shutil.copy2(p, dest / sub / p.name)
print("site/spec mirror refreshed from schemas/, examples/ and codelists/ (versioned sets, archive and mappings included)")
