#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_intake_optin_face.py -- t261009-76 L3: the ticket face tells an operator
which lane version and line a ticket was created with, without reading the
workflow history (grey-box L2, offline seconds, stdlib only, zero
docker/Temporal/browser, never touches 3099/7233).

intent: ticket t261009-76 spec (4). A user looking at the tool's declared
contract and the ticket list must be able to tell an opted-in ticket from a
legacy one:
  A  the create op's DECLARED schema accepts exactly the two opt-in fields,
     each described (the schema is the machine-consumed contract every caller
     reads; `additionalProperties: False` means an undeclared field is dropped
     or refused, so the declaration IS the reachability of the opt-in).
  B  the ticket list face projects the lane fields from the engine rows, with
     the declared old-row tolerance (a row from an older engine without the
     keys reads as empty strings, never a KeyError) — source-anchored on the
     real projection, so a face that silently drops the fields goes red.

Intent split: the engine meta that FEEDS the face (lane_version/develop_line
seeded at workflow start) landed with t261009-46 and is owned there; this
entry owns the caller-facing declaration and the list-row projection only.
Pre-implement tree red = the expected TDD signal; green required at the
integration gate / merge. Engine/tool tree missing = ENV_FAIL exit 2.
"""
import ast
import os
import subprocess
import sys

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True)
if REPO.returncode != 0 or not REPO.stdout.strip():
    print("ENV_FAIL: git repo root unresolved")
    sys.exit(2)
ROOT = REPO.stdout.strip()
TOOLS = os.path.join(ROOT, "server", "tools")
ENGINE = os.path.join(ROOT, "server", "engine")
for d in (TOOLS, ENGINE):
    if not os.path.isdir(d):
        print("ENV_FAIL: tree missing: %s" % d)
        sys.exit(2)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


TICKET_PY = os.path.join(TOOLS, "ticket.py")

# ---- A: the declared create contract carries the two fields ----
sys.path.insert(0, TOOLS)
schema = None
try:
    import ticket  # noqa: E402
    for n in dir(ticket):
        obj = getattr(ticket, n)
        if isinstance(obj, dict):
            props = ((obj.get("parameters") or {}).get("properties")
                     or obj.get("properties"))
            if isinstance(props, dict) and "op" in props:
                schema = props
                break
except Exception as e:  # noqa: BLE001
    check("A0.ticket-module-importable", False, repr(e))

if schema is None:
    check("A0.ticket-module-importable", False, "declared schema dict not found")
else:
    check("A0.ticket-module-importable", True)
    for field, words, cn_words in (
            ("lane_version", ("lane", "version"), ("lane", "版本")),
            ("develop_line_id", ("line",), ("line", "line"))):
        desc = str((schema.get(field) or {}).get("description") or "")
        low = desc.lower()
        # semantic anchors, either copy language (legacy CN face copy stays;
        # host order keeps stored data un-migrated)
        ok = field in schema and all(
            w in low or cn in desc for w, cn in zip(words, cn_words))
        check("A1.schema-declares-%s" % field, ok, "desc=%r" % desc)

# ---- B: the list projection carries the fields with old-row tolerance ----
src = open(TICKET_PY, encoding="utf-8").read()
tree = ast.parse(src)
fn = next((n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_list"), None)
row_keys = []
if fn is not None:
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    row_keys.append(k.value)
check("B1.list-row-projects-lane-version", "lane_version" in row_keys,
      "row keys seen: %r" % sorted(set(row_keys)))
check("B2.list-row-projects-develop-line", "develop_line" in row_keys,
      "row keys seen: %r" % sorted(set(row_keys)))
# tolerance face: the projection must fall back to '' (older-engine rows),
# never an unconditional r['key'] that raises on an old payload.
gets = ".get('lane_version')" in src or '.get("lane_version")' in src
fallback = "or ''" in src or 'or ""' in src
check("B3.old-row-tolerance-declared", gets and fallback,
      "projection must read via .get with an empty-string fallback")

print("INTEG_RESULT pass=%d fail=%d" % (passed, failed))
sys.exit(1 if failed else 0)
