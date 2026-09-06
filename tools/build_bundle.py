#!/usr/bin/env python3
"""Build or check site/spec/owhs-v0.2-bundle.zip and the site's schema, example and code-list mirrors.

    python tools/build_bundle.py               rebuild the current bundle and refresh the managed mirrors under site/spec/
    python tools/build_bundle.py --check       read-only: the bundle's member set, order and uncompressed bytes equal the declared
                                               source mapping, and every managed mirror path holds exactly the repository's JSON
                                               files byte for byte; nothing is written, so a stale checkout cannot repair itself
    python tools/build_bundle.py --self-test   the controls below in a temporary copy of the tree

The bundle holds both specification versions as published under site/spec/ (v0.2 current, v0.1 archive, each labelled by its
file name), the ERD, the versioned schemas and catalogue, examples, code lists, validator and checkers, licences, notice,
governance, decisions and README. The earlier owhs-v0.1-bundle.zip is the published release archive and is never touched here
(tools/check_v01_archive.py holds its identity). The domain routing table is not part of the release and is never included.
File order is deterministic. ZIP timestamps and compression metadata are not content: a metadata-only regeneration with the same
ordered members and bytes passes the check."""
import hashlib, pathlib, shutil, sys, tempfile, warnings, zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUBDIRS = {"schemas": ("v0.1", "v0.2", "bundles"), "examples": ("v0.2", "bundles/v0.2", "bundles/v0.2/cases"), "codelists": ("archive", "mappings")}   # versioned sets, the graph envelope, fixtures, archived lists and the crosswalk
TOOLS = ("check_profiles.py", "check_measurement.py", "check_codelist_mappings.py", "check_remaining_entities.py", "check_entity_graph.py")


def files(root):
    """Archive path -> source path. Both spec markdown members come from their publication copies under site/spec/."""
    F = {
        "spec/OWHS-v0.2-draft.md": root / "site" / "spec" / "OWHS-v0.2-draft.md",           # current
        "spec/OWHS-v0.1-draft.md": root / "site" / "spec" / "OWHS-v0.1-draft.md",           # archive
        "spec/erd.mmd": root / "spec" / "erd.mmd",
        "owhs-erd-v0.1.svg": root / "site" / "owhs-erd-v0.1.svg",
        "owhs-erd-current.svg": root / "site" / "owhs-erd-current.svg",
        "README.md": root / "README.md", "GOVERNANCE.md": root / "GOVERNANCE.md", "DECISIONS.md": root / "DECISIONS.md",
        "LICENSE": root / "LICENSE", "LICENSE-DOCS.md": root / "LICENSE-DOCS.md", "NOTICE": root / "NOTICE", "tools/validate.py": root / "tools" / "validate.py",
    }
    for d, subs in SUBDIRS.items():
        for p in sorted((root / d).glob("*.json")):
            F[f"{d}/{p.name}"] = p
        for sub in subs:
            for p in sorted((root / d / sub).glob("*.json")):
                F[f"{d}/{sub}/{p.name}"] = p
    for p in sorted((root / "profiles").rglob("*.json")):
        F[f"profiles/{p.relative_to(root / 'profiles').as_posix()}"] = p
    F["docs/entity-graph-validation-v0.2.md"] = root / "docs" / "entity-graph-validation-v0.2.md"
    for t in TOOLS:
        F[f"tools/{t}"] = root / "tools" / t
    assert not any("domain-coverage" in k or "domain_routing" in k for k in F)
    return F


def mirror_pairs(root):
    """(destination, source) for every JSON file a managed mirror path must hold; managed directories are the three mirrors' tops and their listed subdirectories."""
    pairs, managed = [], []
    for d, subs in SUBDIRS.items():
        dest = root / "site" / "spec" / d
        managed.append(dest)
        for p in sorted((root / d).glob("*.json")):
            pairs.append((dest / p.name, p))
        for sub in subs:
            if (root / d / sub).is_dir():
                managed.append(dest / sub)
                for p in sorted((root / d / sub).glob("*.json")):
                    pairs.append((dest / sub / p.name, p))
    return pairs, managed


def build(root):
    out = root / "site" / "spec" / "owhs-v0.2-bundle.zip"
    F = files(root)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in sorted(F.items()):
            z.write(src, arc)
    print(f"bundle written: {out.relative_to(root)} ({len(F)} files)")
    # Publish-time mirror: the site serves its own copies of the schemas, examples and code lists, so a reader downloading from
    # the site gets the same bytes as the repository. Keeping them in step by hand is how the validation-report link came to be
    # right in one copy and wrong in the other.
    pairs, managed = mirror_pairs(root)
    for m in managed:
        if m.is_dir():
            for p in m.glob("*.json"):
                p.unlink()
        else:
            m.mkdir(parents=True, exist_ok=True)
    for dest, src in pairs:
        shutil.copy2(src, dest)
    print("site/spec mirror refreshed from schemas/, examples/ and codelists/ (versioned sets, archive and mappings included)")


def check(root):
    """Read-only. Returns a list of problems; empty means the bundle and mirrors are a fresh build of the current sources."""
    problems = []
    out = root / "site" / "spec" / "owhs-v0.2-bundle.zip"
    F = files(root)
    expected = [arc for arc, _ in sorted(F.items())]
    for arc, src in F.items():
        if not src.is_file():
            problems.append(f"source missing for bundle member {arc}: {src.relative_to(root)}")
    if not out.is_file():
        return problems + [f"{out.relative_to(root)} is missing; run tools/build_bundle.py"]
    try:
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                problems.append(f"bundle has duplicate member names: {dupes}")
            if names != expected:
                extra, missing = sorted(set(names) - set(F)), sorted(set(F) - set(names))
                if extra: problems.append(f"bundle has members the mapping does not declare: {extra}")
                if missing: problems.append(f"bundle lacks declared members: {missing}")
                if not extra and not missing: problems.append("bundle members are not in the deterministic sorted order")
            for arc in names:
                src = F.get(arc)
                if src is None or not src.is_file():
                    continue
                if z.read(arc) != src.read_bytes():
                    problems.append(f"bundle member {arc} differs from its source {src.relative_to(root)} (stale bundle; rebuild after the source edit)")
    except zipfile.BadZipFile:
        return problems + [f"{out.relative_to(root)} is not a ZIP file"]
    pairs, managed = mirror_pairs(root)
    wanted = {dest for dest, _ in pairs}
    for dest, src in pairs:
        if not dest.is_file():
            problems.append(f"mirror missing: {dest.relative_to(root)}")
        elif dest.read_bytes() != src.read_bytes():
            problems.append(f"mirror {dest.relative_to(root)} differs from {src.relative_to(root)}")
    for m in managed:
        if not m.is_dir():
            problems.append(f"managed mirror directory missing: {m.relative_to(root)}")
            continue
        for p in sorted(m.glob("*.json")):
            if p not in wanted:
                problems.append(f"orphan in a managed mirror path: {p.relative_to(root)} has no source in the repository")
    return problems


def _tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode()); h.update(p.read_bytes())
    return h.hexdigest()


def self_test():
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else str(detail)[:240]); failures += not ok
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "tree"
        for d in ("spec", "schemas", "examples", "codelists", "profiles", "docs", "tools"):
            shutil.copytree(ROOT / d, root / d)
        (root / "site" / "spec").mkdir(parents=True)
        for f in ("owhs-erd-v0.1.svg", "owhs-erd-current.svg"):
            shutil.copy2(ROOT / "site" / f, root / "site" / f)
        for f in ("OWHS-v0.2-draft.md", "OWHS-v0.1-draft.md", "owhs-v0.1-bundle.zip"):
            shutil.copy2(ROOT / "site" / "spec" / f, root / "site" / "spec" / f)
        for f in ("README.md", "GOVERNANCE.md", "DECISIONS.md", "LICENSE", "LICENSE-DOCS.md", "NOTICE"):
            shutil.copy2(ROOT / f, root / f)
        for d in SUBDIRS:
            (root / "site" / "spec" / d).mkdir()
        before_archive = (root / "site" / "spec" / "owhs-v0.1-bundle.zip").read_bytes()
        t("an absent bundle is refused by name", any("is missing" in x for x in check(root)), check(root)[:2])
        build(root)
        t("a fresh build passes", not check(root), check(root)[:3])
        h = _tree_hash(root); check(root); t("a check run leaves every file unchanged", _tree_hash(root) == h)
        readme = root / "README.md"; original = readme.read_bytes()
        readme.write_bytes(original + b"\nedited after the build\n")
        p = check(root); t("a source README edited after the build refuses (this head's stale-README shape)", any("bundle member README.md differs" in x for x in p), p[:2])
        readme.write_bytes(original); t("restoring the source passes again", not check(root), check(root)[:2])
        out = root / "site" / "spec" / "owhs-v0.2-bundle.zip"
        def rewrite(members, drop=(), add=(), dup=None):
            with zipfile.ZipFile(out) as z:
                data = [(n, z.read(n)) for n in z.namelist()]
            with warnings.catch_warnings(), zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                warnings.simplefilter("ignore")          # the duplicate-name control writes a member twice on purpose
                for n, b in data:
                    if n in drop: continue
                    z.writestr(n, b)
                    if n == dup: z.writestr(n, b)
                for n, b in add: z.writestr(n, b)
        keep = out.read_bytes()
        rewrite(None, drop=("NOTICE",)); p = check(root); t("a missing member refuses", any("lacks declared members" in x and "NOTICE" in x for x in p), p[:2]); out.write_bytes(keep)
        rewrite(None, add=(("extra.txt", b"x"),)); p = check(root); t("an extra member refuses", any("does not declare" in x and "extra.txt" in x for x in p), p[:2]); out.write_bytes(keep)
        rewrite(None, dup="NOTICE"); p = check(root); t("a duplicate member refuses", any("duplicate member names" in x for x in p), p[:2]); out.write_bytes(keep)
        rewrite(None); t("a metadata-only regeneration with identical ordered members and bytes passes", not check(root), check(root)[:2]); out.write_bytes(keep)
        with zipfile.ZipFile(out) as z: data = [(n, z.read(n)) for n in z.namelist()]
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in reversed(data): z.writestr(n, b)
        p = check(root); t("members out of the deterministic order refuse", any("sorted order" in x for x in p), p[:2]); out.write_bytes(keep)
        mirror = next(iter(sorted((root / "site" / "spec" / "schemas" / "v0.2").glob("*.json"))))
        mb = mirror.read_bytes(); mirror.write_bytes(mb + b"\n")
        p = check(root); t("a mismatched managed mirror file refuses", any("mirror" in x and "differs" in x for x in p), p[:2]); mirror.write_bytes(mb)
        orphan = root / "site" / "spec" / "codelists" / "archive" / "orphan.json"; orphan.write_text("{}")
        p = check(root); t("an orphan JSON in a managed mirror path refuses", any("orphan" in x for x in p), p[:2]); orphan.unlink()
        unmanaged = root / "site" / "spec" / "notes.json"; unmanaged.write_text("{}")
        t("an unmanaged path beside the mirrors is left alone", not check(root), check(root)[:2]); unmanaged.unlink()
        t("the check never refreshed the mirrors: the mismatch above was reported, not repaired", mirror.read_bytes() == mb)
        h2 = _tree_hash(root); build(root)
        t("a second normal build keeps the same logical content and managed mirror", not check(root) and _tree_hash(root / "site" / "spec" / "schemas") == _tree_hash(root / "site" / "spec" / "schemas") and check(root) == [], check(root)[:2])
        t("the v0.1 release archive is byte-identical throughout", (root / "site" / "spec" / "owhs-v0.1-bundle.zip").read_bytes() == before_archive)
        with zipfile.ZipFile(out) as z:
            t("both spec markdown members come from the publication copies under site/spec/", z.read("spec/OWHS-v0.2-draft.md") == (root / "site" / "spec" / "OWHS-v0.2-draft.md").read_bytes() and z.read("spec/OWHS-v0.1-draft.md") == (root / "site" / "spec" / "OWHS-v0.1-draft.md").read_bytes())
    print(f"{'all' if not failures else failures} bundle probes {'as expected' if not failures else 'FAILED'}")
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    if "--check" in argv:
        problems = check(ROOT)
        for x in problems:
            print("PROBLEM", x)
        if problems:
            print(f"{len(problems)} problem(s): the current bundle or a managed mirror is not a fresh build of the sources; run tools/build_bundle.py after the final source edits and commit the result")
            return 1
        print(f"up to date: owhs-v0.2-bundle.zip holds the {len(files(ROOT))} declared members in order with their source bytes; every managed mirror path matches the repository")
        return 0
    build(ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
