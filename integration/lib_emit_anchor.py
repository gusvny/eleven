#!/usr/bin/env python3
"""Statement-level predicate for the bad-char (lone surrogate) emit contract
(t261004-26 B3a, request -0013; consumer = integration/sc_emit_surrogate_guard.py
leg C, unit battery = integration/test_lib_emit_anchor.py).

Why this lib exists: the old family anchor matched the literal source shape
`print(json.dumps(` in a 3-line window — a single extra pair of wrapping
parentheses escaped it, and the -23 fix WAS exactly such a wrapping. A guard
that cannot see its own target trains nobody. This predicate PARSES the source
(AST), so wrapping parentheses are invisible by construction and the judgement
is statement-level, not substring-level.

Contract (pure function, no IO, no globals):
  emit_anchor_violations(text, filename) -> list[str]   # [] = clean
  - a `print` call (plain name or `<expr>.print` attribute) whose argument
    subtree contains a `json.dumps(..., ensure_ascii=False)` call MUST also
    carry the visible-escape fallback: a string constant containing
    "backslashreplace" anywhere inside the same print call;
  - `ensure_ascii=True` (the default) escapes non-ASCII by construction and is
    out of scope (same face as the old guard);
  - a file that does not parse is fail-closed RED naming the filename — never
    a silent skip (a malformed input must not buy a green);
  - violations are "filename:lineno: reason" so the consumer can key its
    reviewer-visible exemption table on (filename, statement line span).

Discipline note: this module deliberately contains exactly ONE two-argument
function — the guard-chain scenario (integration/t261004-26/
sc_guard_statement_level_faces.py) locates the predicate by that shape, so any
second two-arg callable here breaks that discovery contract.
"""
import ast

_FALLBACK_MARK = "backslashreplace"


def _is_json_dumps(node):
    """`json.dumps` (attribute) or a direct `dumps` import (name)."""
    if isinstance(node, ast.Attribute):
        return node.attr == "dumps"
    return isinstance(node, ast.Name) and node.id == "dumps"


def _ensure_ascii_false(call):
    for kw in call.keywords:
        if kw.arg == "ensure_ascii":
            return isinstance(kw.value, ast.Constant) and kw.value.value is False
    return False


def _dumps_unsafe_calls(print_call):
    """All `json.dumps(..., ensure_ascii=False)` calls inside the print args."""
    out = []
    for arg in list(print_call.args) + [kw.value for kw in print_call.keywords]:
        for sub in ast.walk(arg):
            if (isinstance(sub, ast.Call) and _is_json_dumps(sub.func)
                    and _ensure_ascii_false(sub)):
                out.append(sub)
    return out


def _has_fallback(print_call):
    """A string constant containing the fallback mark inside the print call."""
    for node in ast.walk(print_call):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _FALLBACK_MARK in node.value:
                return True
    return False


def _is_print_call(node):
    if isinstance(node, ast.Name):
        return node.id == "print"
    if isinstance(node, ast.Attribute):
        return node.attr == "print"
    return False


def emit_anchor_violations(text, filename):
    """Statement-level emit-contract predicate. [] = clean (see module doc)."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return ["%s:%s: source does not parse — fail-closed (never a silent "
                "skip): %s" % (filename, exc.lineno or "?", exc.msg)]
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_print_call(node.func)):
            continue
        if not _dumps_unsafe_calls(node):
            continue
        if not _has_fallback(node):
            out.append("%s:%d: print(json.dumps(..., ensure_ascii=False)) "
                       "without a %s fallback — a lone surrogate can take the "
                       "whole receipt down" % (filename, node.lineno,
                                               _FALLBACK_MARK))
    return out
