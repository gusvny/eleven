#!/usr/bin/env python3
"""Canonical serialization for the JSON registries under integration/
(t261009-51, incident KI-01M4HD396VNTTAY20CH0681N0Q).

Measured fault: every ticket that appended an anchor entry re-serialized
integration/test_anchors.json with whatever json.dumps defaults its script
happened to use. The style flipped 1-space ↔ 2-space between writers, so a
3-entry append produced a 9082-line diff (t261009-48) and a 4561/4546 diff
(t261009-49) — zero semantic change, the whole diff was style. Parallel
anchor appends became guaranteed conflicts. This module declares the ONE
canonical form in the repo instead of in a writer's head:

    UTF-8, ensure_ascii=False, indent=2, insertion key order (no sort_keys),
    exactly one trailing newline.

This is the style integration/known-red-baseline.json already uses — the
sibling every new registry is matched against.

Root types: canonicalization is ROOT-AGNOSTIC — any JSON value (object,
array, string, …) serializes the same way. batch_stage_exceptions.json is a
JSON array and is a declared registry in good standing; a "non-object root"
is a malformed-input case only for code that consumes a registry EXPECTING a
mapping, never for this module.

Known failure modes of the borrowed style (declared, not discovered):
  - ensure_ascii=False + a lone-surrogate payload makes write_text raise
    UnicodeEncodeError. write_registry PROPAGATES that error loudly — it
    never silently downgrades to ensure_ascii=True (a silent downgrade would
    flip the bytes behind every reader's back, the exact fault class this
    module exists to kill). Family precedent for the escape discipline:
    integration/lib_emit_anchor.py (print + backslashreplace fallback).
  - non-JSON-serializable objects raise TypeError from json.dumps — also
    propagated; a writer must not half-write a registry.
  - write is a single write_text (replace), so a reader never observes a
    torn file; no temp-file dance is needed at these sizes.

Write path contract: lib_registry.write_registry is the single entry point
that produces canonical bytes. The lint counterpart is L23 in
integration/lint_tests.py: it re-serializes each declared registry in memory
and byte-compares with disk, naming the first differing line — it REPORTS,
never rewrites (fail loud, never silently reformat a shared source of truth).
"""
import json
from pathlib import Path

#: The canonical json.dumps kwargs, declared once. sort_keys stays absent on
#: purpose: registries are read by humans in insertion order and a sort would
#: itself restyle whole files on unrelated appends.
CANONICAL_JSON_KWARGS = {
    "ensure_ascii": False,
    "indent": 2,
}

#: Declared registry set (paths relative to the repository root). Only JSON
#: registries under integration/ whose format is part of this class.
#: Deliberately excluded: the L8 tmpdir baseline (lint-generated output of
#: `lint_tests.py --write-tmpdir-baseline`, not a hand-edited registry —
#: normalizing it is a one-flag regeneration, not this ticket's change).
DECLARED_REGISTRIES = [
    "integration/test_anchors.json",
    "integration/known-red-baseline.json",
    "integration/batch_stage_exceptions.json",
]


def canonical_registry_bytes(obj):
    """Serialize `obj` to the canonical registry text (str, per module doc).

    Root-agnostic: works for any JSON value. Errors (TypeError for
    non-serializable objects) propagate — never a partial or downgraded
    serialization.
    """
    return json.dumps(obj, **CANONICAL_JSON_KWARGS) + "\n"


def write_registry(path, obj):
    """Write `obj` to `path` as canonical registry bytes. The single entry
    point for appending to / updating a declared registry. Encoding and
    serialization errors propagate loudly (see module doc)."""
    Path(path).write_text(canonical_registry_bytes(obj), encoding="utf-8")


def first_diff_line(canonical_text, disk_text):
    """First differing line between canonical and on-disk text, for the lint's
    error message. Pure function.

    Returns None when the texts are identical, else a string
    "line N: canonical=<...> | disk=<...>" with both excerpts (repr-trimmed),
    so the reader sees the style drift rather than a generic mismatch. A
    pure length difference (one text is a prefix of the other) is reported
    against the shorter text's end.
    """
    if canonical_text == disk_text:
        return None
    a = canonical_text.splitlines()
    b = disk_text.splitlines()
    for i in range(max(len(a), len(b))):
        ca = a[i] if i < len(a) else "<EOF>"
        cb = b[i] if i < len(b) else "<EOF>"
        if ca != cb:
            sa = ca if len(ca) <= 80 else ca[:77] + "..."
            sb = cb if len(cb) <= 80 else cb[:77] + "..."
            return "line %d: canonical=%r | disk=%r" % (i + 1, sa, sb)
    # Identical line lists but differing texts: only trailing-newline drift.
    return "line %d: canonical=%r | disk=%r (trailing newline drift)" % (
        max(len(a), len(b)),
        a[-1] if a else "",
        b[-1] if b else "")
