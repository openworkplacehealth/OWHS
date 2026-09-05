#!/usr/bin/env python3
"""Parse every workflow file with a strict YAML loader that refuses duplicate keys.

A duplicate `env:` key in a step is accepted by permissive loaders and silently drops one mapping, which in a
workflow means a token or an input vanishes. This check makes that a failure in CI rather than a mystery at 06:00
on the first of the month.
"""
import glob, sys
import yaml


class Strict(yaml.SafeLoader):
    pass


def no_dup(loader, node, deep=False):
    m = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in m:
            raise yaml.constructor.ConstructorError(f"duplicate key {key!r} at line {k.start_mark.line + 1}")
        m[key] = loader.construct_object(v, deep=deep)
    return m


Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_dup)

bad = 0
for f in sorted(glob.glob(".github/workflows/*.yml")):
    try:
        doc = yaml.load(open(f, encoding="utf-8"), Loader=Strict)
        assert isinstance(doc, dict) and "jobs" in doc and ("on" in doc or True in doc), "not a workflow"
        print("ok", f)
    except Exception as e:
        bad += 1; print("FAIL", f, e)
sys.exit(1 if bad else 0)
