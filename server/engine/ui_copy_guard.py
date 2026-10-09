# -*- coding: utf-8 -*-
"""UI-copy CJK guard (t261008-47, host report 261008).

Engine-authored strings that reach a ticket face (timeline reasons, blocked/wake
texts, handoff summaries, stage acceptance items, the settle commit subject) must
be English (host orders 260924/260925). This module is the mechanical guard:
a narrow, AST-based scan that reports CJK in exactly those emission positions.

Narrowness by construction:
- Only listed call anchors are scanned, and only the copy-bearing argument of
  each anchor (data arguments such as `_mark(step, state, ...)`'s state, or
  `_auto_rework`'s who/fallback, are skipped).
- `_log(...)`, `refused` texts, agent prompt bodies, comments and docstrings are
  structurally out — they are operator/log surfaces or prompts, not ticket-face
  copy (t261008-47 plan §1b/§1c, review-accepted).
- Stage declarations: only the `acceptance=` and `desc=` keywords. `id=`/`name=`
  are machine/display keys the console maps from — never translated.
- agent_activities.py: the single settle commit subject is anchored by the
  the `git commit -m` message builders — anchored by per-function dataflow
  (`msg = ...` feeding `_git([..., "-m", msg])`), so every writer site is
  covered by construction (the engine authors subjects at the settle, the
  join-settle and the squash close-out).

Exemptions are an explicit named list (`EXEMPTIONS`: (file, line, kind) tuples),
never a pattern; the default list is empty.

Pure functions, stdlib only, zero IO beyond reading the given paths.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Sequence, Tuple

# Ideographs (incl. ext A) + kana + CJK punctuation/fullwidth forms: English
# ticket-face copy carries none of them (aligned with the integration-side
# scanner for t261008-47, which uses the same wide character classes).
CJK = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]")

# (file basename, function/anchor name, positions or keywords) — see module doc.
CALL_ANCHORS: Dict[str, Dict[str, Any]] = {
    # fn: {"pos": {arg_index: kind}, "kw": {keyword: kind}}
    "_mark": {"pos": {2: "reason"}, "kw": {"reason": "reason"}},
    "_finish": {"pos": {2: "evidence"}, "kw": {"evidence": "evidence"}},
    "_blocked": {"pos": {1: "why"}, "kw": {"why": "why"}},
    "_handoff": {"pos": {1: "summary"}, "kw": {"summary": "summary", "report": "report"}},
    "_auto_rework": {"pos": {1: "note"}, "kw": {"note": "note"}},
    "Stage": {"pos": {}, "kw": {"acceptance": "acceptance", "desc": "desc"}},
}

# Commit subjects are anchored by dataflow (`msg=` feeding `git commit -m`
# through _git, per function) — no hand-named function list, so a new writer
# site is covered by construction.

# Named exemptions: {(file_basename, line, kind, literal_prefix)} — keep empty
# unless a string genuinely cannot be translated; every entry needs a reason in
# the ticket, never a wildcard.
EXEMPTIONS: set = set()


def _iter_string_constants(node: ast.AST) -> List[Tuple[int, str]]:
    """(line, literal) for every str constant reachable in the expression,
    including %-format templates and implicit concatenation."""
    out: List[Tuple[int, str]] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append((getattr(sub, "lineno", 0), sub.value))
    return out


def _func_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _scan_call(call: ast.Call, findings: List[Dict[str, str]], path: str) -> None:
    rule = CALL_ANCHORS.get(_func_name(call))
    if not rule:
        return
    positions = [call.args[i] for i in sorted(rule["pos"]) if i < len(call.args)]
    for kw in call.keywords:
        if kw.arg in rule["kw"]:
            positions.append(kw.value)
    for expr in positions:
        for line, lit in _iter_string_constants(expr):
            if CJK.search(lit):
                findings.append({"file": path, "line": line,
                                 "kind": rule["pos"].get(
                                     _arg_index(call, expr), rule["kw"].get(
                                         _kw_name(call, expr), "copy")),
                                 "literal": lit.strip()[:120]})


def _arg_index(call: ast.Call, expr: ast.AST) -> int:
    for i, a in enumerate(call.args):
        if a is expr:
            return i
    return -1


def _kw_name(call: ast.Call, expr: ast.AST) -> str:
    for kw in call.keywords:
        if kw.value is expr:
            return kw.arg or ""
    return ""


def _git_m_targets(fn: ast.FunctionDef) -> set:
    """Names fed as a `git commit -m <var>` message inside this function
    (per-function dataflow: assignment -> -m argument). Covers every place the
    engine authors a commit subject, not just one hand-named site."""
    names = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or _func_name(node) != "_git":
            continue
        # _git takes a single argv list: _git(["commit", "-m", msg], cwd)
        for a in node.args:
            if not isinstance(a, ast.List):
                continue
            elems = a.elts
            for i, e in enumerate(elems):
                if (isinstance(e, ast.Constant) and e.value == "-m"
                        and i + 1 < len(elems) and isinstance(elems[i + 1], ast.Name)):
                    names.add(elems[i + 1].id)
    return names


def _scan_commit_subject(tree: ast.AST, findings: List[Dict[str, str]],
                         path: str) -> None:
    """Anchor: any function that passes a variable to `git commit -m` via _git —
    the string constants feeding that variable are the authored subject."""
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        targets = _git_m_targets(fn)
        if not targets:
            continue
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            tgt = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(t, ast.Name) and t.id in targets for t in tgt):
                continue
            for line, lit in _iter_string_constants(node.value):
                if CJK.search(lit):
                    findings.append({"file": path, "line": line,
                                     "kind": "commit-subject",
                                     "literal": lit.strip()[:120]})


def scan_source(source: str, path: str) -> List[Dict[str, str]]:
    """Scan one module's source. Unparseable source is a named finding, never a
    raise (consumed-input fail-closed discipline)."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        return [{"file": path, "line": e.lineno or 0, "kind": "unparseable",
                 "literal": str(e.msg)[:120]}]
    findings: List[Dict[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            _scan_call(node, findings, path)
    _scan_commit_subject(tree, findings, path)
    return [f for f in findings
            if (f["file"].rsplit("/", 1)[-1], f["line"], f["kind"],
                f["literal"][:40]) not in EXEMPTIONS]


def scan_paths(paths: Sequence[str]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            findings.extend(scan_source(fh.read(), p))
    return findings


def format_finding(f: Dict[str, str]) -> str:
    return "%s:%d [%s] CJK in UI-destined copy: %r" % (
        f["file"], f["line"], f["kind"], f["literal"])
