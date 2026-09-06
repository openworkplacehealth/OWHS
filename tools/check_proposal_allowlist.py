#!/usr/bin/env python3
"""Allowlist diff gate for an automated screening proposal: what a screening run may change in the dataset, and nothing else.

    python tools/check_proposal_allowlist.py BEFORE.json AFTER.json [--report OUT.json]
    python tools/check_proposal_allowlist.py --self-test

Permitted, and only these:
  1. appended citation entries: records[*].citations gains new entries at the end; every existing entry stays byte-identical, in
     place, in order; a new entry has a key not already on the record, a title, and a canonical DOI or a declared non-DOI source
  2. review_due set from false to true on a property cell of a record that gained a citation (never true to false, never on a
     record without a new citation)
  3. when the dataset carries a schema 0.8 `searches` array, appended search objects (existing ones untouched)
Everything else is refused: any change to a grade, status, evidence form, findings, precondition evidence, subgrades, previous
blocks, indirectness, as_of or confirmation dates, licence fields, identity, corrections, changelog, version or rubric; any edit or
deletion disguised as an append (a replaced entry with the same key, a reordered list, a changed nested field); any new top-level
key; any record added, removed, duplicated or reordered. Before any comparison both record arrays must be lists of objects with
present, typed, unique instrument ids (a duplicate id in either input is a violation naming the index and id), and the ordered id
arrays and lengths are compared directly, never through a deduplicated map; citation keys and search ids are likewise checked for
type and uniqueness before any set operation. Malformed input is a named violation, not a traceback. The whole before and after
objects are compared; there is no exception for an automated author.
Exit 0 means the proposal is within the allowlist; 1 lists every violation; nothing is written except the optional report.
"""
import copy, json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
PROPS = ["structural_validity", "convergent_discriminant_validity", "criterion_validity_reference_standard", "criterion_validity_organisational",
         "internal_consistency", "test_retest_reliability", "measurement_invariance", "responsiveness_mic", "populations_languages_norms"]
DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def diff_paths(a, b, path=()):
    """Every path where a and b differ, as tuples; lists compared by index with length differences reported at the list path."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b: out.append(path + (k,))
            else: out += diff_paths(a[k], b[k], path + (k,))
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(min(len(a), len(b))): out += diff_paths(a[i], b[i], path + (i,))
        if len(a) != len(b): out.append(path + ("<length>",))
    elif a != b: out.append(path)
    return out


def record_array_problems(side, records):
    """Structure before semantics: the record array is a list of objects, each with a present, non-empty string instrument_id, and
    no id appears twice. Duplicates are named by index and id. Nothing is deduplicated."""
    p = []
    if not isinstance(records, list): return [f"{side}: records is not a list"]
    seen = {}
    for i, r in enumerate(records):
        if not isinstance(r, dict): p.append(f"{side}: records[{i}] is not an object"); continue
        rid = r.get("instrument_id")
        if not isinstance(rid, str) or not rid: p.append(f"{side}: records[{i}] has no string instrument_id"); continue
        if rid in seen: p.append(f"{side}: records[{i}] duplicates instrument_id {rid!r} first seen at records[{seen[rid]}]")
        else: seen[rid] = i
    return p


def id_list_problems(where, items, key):
    """A list of objects whose `key` values are non-empty unique strings; named violations, no set operations on unchecked values."""
    p = []
    if not isinstance(items, list): return [f"{where}: not a list"]
    seen = {}
    for i, c in enumerate(items):
        if not isinstance(c, dict): p.append(f"{where}[{i}] is not an object"); continue
        v = c.get(key)
        if not isinstance(v, str) or not v: p.append(f"{where}[{i}] has no string {key}"); continue
        if v in seen: p.append(f"{where}[{i}] duplicates {key} {v!r} first seen at [{seen[v]}]")
        else: seen[v] = i
    return p


def check(before, after):
    problems, permitted = [], []
    if not isinstance(before, dict) or not isinstance(after, dict): return ["before or after is not a JSON object"], permitted
    if set(before) != set(after): problems.append(f"top-level keys differ: {sorted(set(before) ^ set(after))}")
    # record identity first: typed, present, unique, in both inputs; then the ordered id arrays and lengths, never a map
    structural = record_array_problems("before", before.get("records")) + record_array_problems("after", after.get("records"))
    if structural: return problems + structural, permitted
    ids_b = [r["instrument_id"] for r in before["records"]]; ids_a = [r["instrument_id"] for r in after["records"]]
    if len(ids_b) != len(ids_a): problems.append(f"record count changed from {len(ids_b)} to {len(ids_a)}")
    if ids_b != ids_a: problems.append(f"records added, removed or reordered: before {ids_b[:5]}{'...' if len(ids_b) > 5 else ''} after {ids_a[:5]}{'...' if len(ids_a) > 5 else ''}"); return problems, permitted
    for k in before:
        if k in ("records", "searches"): continue
        if before[k] != after.get(k): problems.append(f"top-level {k} changed")
    if "searches" in before or "searches" in after:
        sb, sa = before.get("searches", []), after.get("searches", [])
        sp = id_list_problems("before.searches", sb, "id") + id_list_problems("after.searches", sa, "id")
        if sp: problems += sp
        else:
            if sa[:len(sb)] != sb: problems.append("existing search entries changed, reordered or removed")
            for s_ in sa[len(sb):]: permitted.append(f"searches: appended {s_['id']}")
    for b, a in zip(before["records"], after["records"]):
        rid = b["instrument_id"]
        cb, ca = b.get("citations", []), a.get("citations", [])
        gained = False
        cp = id_list_problems(f"{rid}: before.citations", cb, "key") + id_list_problems(f"{rid}: after.citations", ca, "key")
        if cp: problems += cp; continue
        if ca[:len(cb)] != cb: problems.append(f"{rid}: existing citation entries changed, reordered or removed (an edit disguised as an append)")
        for c in ca[len(cb):]:          # keys are already unique across the whole after list, so an appended key cannot repeat an existing one
            if not c.get("title"): problems.append(f"{rid}: appended citation {c.get('key')!r} has no title")
            doi = c.get("doi")
            if doi is not None and not DOI.match(str(doi)): problems.append(f"{rid}: appended citation {c.get('key')!r} has a non-canonical DOI {doi!r}")
            if doi is None and not c.get("source"): problems.append(f"{rid}: appended citation {c.get('key')!r} has neither a DOI nor a declared source")
            gained = True; permitted.append(f"{rid}: citation appended {c['key']!r}")
        for p in diff_paths(b, a):
            if p and p[0] == "citations": continue          # judged above
            if len(p) == 2 and p[0] in PROPS and p[1] == "review_due":
                if b[p[0]].get("review_due") is False and a[p[0]].get("review_due") is True and gained:
                    permitted.append(f"{rid}.{p[0]}: review_due set"); continue
                if not gained: problems.append(f"{rid}.{p[0]}: review_due changed on a record that gained no citation"); continue
                problems.append(f"{rid}.{p[0]}: review_due may only move from false to true"); continue
            problems.append(f"{rid}: protected change at {'/'.join(map(str, p))}")
    return problems, permitted


def self_test():
    base = {"version": "0.9.0", "records": [{"instrument_id": "isi", "identity": {"licence_class": "fee-bearing"}, "citations": [{"key": "Morin2011", "title": "T", "doi": "10.1093/sleep/34.5.601"}],
                                             "internal_consistency": {"grade": "High", "status": "well-established", "review_due": False, "findings": "text", "as_of": "2026-07-12"}}], "corrections": []}
    failures = 0
    def t(label, ok, detail=""):
        nonlocal failures; print(("ok  " if ok else "FAIL"), label, "" if ok else detail); failures += not ok
    def after(mutate):
        a = copy.deepcopy(base); mutate(a); return check(base, a)
    t("no change is within the allowlist", check(base, copy.deepcopy(base)) == ([], []))
    p, ok = after(lambda a: (a["records"][0]["citations"].append({"key": "New2026", "title": "N", "doi": "10.1000/new"}), a["records"][0]["internal_consistency"].__setitem__("review_due", True)))
    t("an appended citation with review_due set on that record is permitted", not p and len(ok) == 2, p)
    p, _ = after(lambda a: a["records"][0]["citations"].__setitem__(0, {"key": "Morin2011", "title": "T changed", "doi": "10.1093/sleep/34.5.601"}))
    t("an edit to an existing citation with the same key (disguised as an append) is refused", any("disguised" in x for x in p))
    p, _ = after(lambda a: a["records"][0]["citations"].clear()); t("a deleted citation is refused", any("disguised" in x for x in p))
    p, _ = after(lambda a: a["records"][0]["citations"].append({"key": "Morin2011", "title": "dup", "doi": "10.1093/sleep/34.5.601"})); t("an appended citation reusing an existing key is refused as a duplicate key in the after list", any("after.citations[1] duplicates key 'Morin2011'" in x for x in p), p)
    p, _ = after(lambda a: a["records"][0]["citations"].append({"key": "X", "title": "x", "doi": "https://doi.org/10.1000/x"})); t("a non-canonical DOI is refused", any("non-canonical" in x for x in p))
    p, _ = after(lambda a: a["records"][0]["internal_consistency"].__setitem__("grade", "Moderate")); t("a grade change is refused", any("protected change" in x and "grade" in x for x in p))
    p, _ = after(lambda a: a["records"][0]["internal_consistency"].__setitem__("as_of", "2026-09-05")); t("a prose date refresh (as_of) is refused", any("as_of" in x for x in p))
    p, _ = after(lambda a: a["records"][0]["internal_consistency"].__setitem__("review_due", True)); t("review_due set on a record that gained no citation is refused", any("gained no citation" in x for x in p))
    base2 = copy.deepcopy(base); base2["records"][0]["internal_consistency"]["review_due"] = True
    p, _ = check(base2, copy.deepcopy(base)); t("review_due cleared (true to false) is refused", any("only move from false to true" in x for x in p) or any("gained no citation" in x for x in p))
    p, _ = after(lambda a: a["records"][0]["identity"].__setitem__("licence_class", "open")); t("a licence class change is refused", any("licence_class" in x for x in p))
    p, _ = after(lambda a: a["records"].append({"instrument_id": "new", "citations": []})); t("an added record is refused", any("added, removed" in x for x in p) and any("record count" in x for x in p))
    # duplicate-id regressions: the actual arrays are compared, never a deduplicated map
    p, _ = after(lambda a: a["records"].insert(0, copy.deepcopy(a["records"][0])))
    t("an identical duplicate of a record inserted at the start of after is refused, naming index and id", any("after: records[1] duplicates instrument_id 'isi'" in x for x in p), p)
    def shadowed(a):
        changed = copy.deepcopy(a["records"][0]); changed["internal_consistency"]["grade"] = "Absent"
        a["records"].append(changed); a["records"].append(copy.deepcopy(a["records"][0]))
    p, _ = after(shadowed)
    t("a grade change in an appended duplicate hidden behind a second unmodified duplicate is refused (two added records; nothing accepted)", any("records[1] duplicates" in x for x in p) and any("records[2] duplicates" in x for x in p), p)
    dup_before = copy.deepcopy(base); dup_before["records"].append(copy.deepcopy(base["records"][0]))
    p, _ = check(dup_before, copy.deepcopy(dup_before)); t("a duplicate id in before is refused even when after is identical", any("before: records[1] duplicates" in x for x in p), p)
    p, _ = check({"version": "0.9.0", "records": {"isi": {}}, "corrections": []}, copy.deepcopy(base)); t("records not a list is a named violation, no traceback", p == ["before: records is not a list"], p)
    p, _ = after(lambda a: a["records"].__setitem__(0, "isi")); t("a record that is not an object is a named violation", any("records[0] is not an object" in x for x in p), p)
    p, _ = after(lambda a: a["records"][0].__setitem__("instrument_id", 7)); t("a non-string instrument_id is a named violation", any("no string instrument_id" in x for x in p), p)
    p, _ = check(42, copy.deepcopy(base)); t("a non-object input is a named violation", p == ["before or after is not a JSON object"], p)
    p, _ = after(lambda a: a["records"][0]["citations"].extend([{"key": "Two", "title": "a", "doi": "10.1000/a"}, {"key": "Two", "title": "b", "doi": "10.1000/b"}]))
    t("two appended citations sharing a key are refused before any set operation", any("after.citations[2] duplicates key 'Two'" in x for x in p), p)
    p, _ = after(lambda a: a["records"][0]["citations"].append({"key": 5, "title": "a", "doi": "10.1000/a"})); t("a non-string citation key is a named violation", any("has no string key" in x for x in p), p)
    p, _ = after(lambda a: a["records"][0].__setitem__("citations", {"k": 1})); t("citations not a list is a named violation", any("after.citations: not a list" in x for x in p), p)
    p, _ = after(lambda a: a.__setitem__("version", "0.9.1")); t("a version change is refused (release policy, not the screening step)", any("version changed" in x for x in p))
    p, _ = after(lambda a: a.__setitem__("extra", 1)); t("a new top-level key is refused", any("top-level keys differ" in x for x in p))
    p, _ = after(lambda a: a["corrections"].append({"id": "C-X"})); t("a corrections entry is refused (corrections are numbered rulings, not screening output)", any("corrections changed" in x for x in p))
    with08 = copy.deepcopy(base); with08["searches"] = [{"id": "s1"}]
    a08 = copy.deepcopy(with08); a08["searches"].append({"id": "s2"}); p, ok = check(with08, a08); t("an appended search entry on a schema 0.8 dataset is permitted", not p and ok == ["searches: appended s2"])
    a08 = copy.deepcopy(with08); a08["searches"][0]["id"] = "changed"; p, _ = check(with08, a08); t("an edited existing search entry is refused", any("existing search" in x for x in p))
    a08 = copy.deepcopy(with08); a08["searches"] += [{"id": "s1"}]; p, _ = check(with08, a08); t("an appended search entry reusing an existing id is refused as a duplicate", any("after.searches[1] duplicates id 's1'" in x for x in p), p)
    a08 = copy.deepcopy(with08); a08["searches"] += [{"id": ""}]; p, _ = check(with08, a08); t("an appended search entry with an empty id is a named violation", any("has no string id" in x for x in p), p)
    print(f"{'all' if not failures else failures} allowlist probes {'as expected' if not failures else 'FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--self-test"]: self_test()
    if len(a) < 2: sys.exit(__doc__)
    before, after_ = json.loads(Path(a[0]).read_text(encoding="utf-8")), json.loads(Path(a[1]).read_text(encoding="utf-8"))
    problems, permitted = check(before, after_)
    rep = {"within_allowlist": not problems, "permitted_changes": permitted, "violations": problems}
    if "--report" in a: Path(a[a.index("--report") + 1]).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    for x in problems: print("REFUSED", x)
    for x in permitted: print("permitted", x)
    print("within the allowlist" if not problems else f"{len(problems)} violation(s); the proposal stops here")
    sys.exit(1 if problems else 0)
