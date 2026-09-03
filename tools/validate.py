#!/usr/bin/env python3
"""OWHS v0.1 reference validator (structural level). Usage: python validate.py <schema.json> <instance.json>"""
import sys, json
from jsonschema.validators import Draft202012Validator as V
schema = json.load(open(sys.argv[1])); inst = json.load(open(sys.argv[2]))
V.check_schema(schema)
errs = sorted(V(schema).iter_errors(inst), key=lambda e: list(e.path))
if not errs:
    print("VALID"); sys.exit(0)
for e in errs:
    print(f"[{e.validator}] {'/'.join(map(str,e.path)) or '<root>'}: {e.message}")
sys.exit(1)
