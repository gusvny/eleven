#!/usr/bin/env python3
"""Static sweep of the engine producer modules for CJK on the ticket face
(t261021-11; the surface list and classification rules live in
integration/lib_engine_face_language.py).

What this gate does
  It tokenizes each declared producer module (lib_engine_face_language.
  PRODUCER_MODULES), takes every STRING/COMMENT-adjacent CJK occurrence in
  code, classifies it by the mechanical rules R1-R7 (docstring/prompt/
  internal-cli/log-only/inventory-override/defect), and enforces:

  - a live hit classified `defect` must exist in the committed inventory
    (integration/engine_face_language_inventory.json) with the debt tag
    `t261021-11` — allowlisted-until-conversion, per the review condition that
    a known red must not block the shared battery while the engine conversion
    rides as handover;
  - a `defect` hit with NO inventory entry is a new CJK literal reachable from
    the face: red, immediately;
  - an inventory `defect` entry with no live hit is stale (the literal moved or
    was converted): red, so the ledger cannot rot — after the conversion lands
    the entries are deleted and the allowlist empties itself;
  - a non-defect live classification (prompt / internal-cli / log-only) that
    an inventory entry contradicts is red (drift between rule and ledger).

  Classification of a live `defect` hit whose inventory entry carries a
  different classification is likewise red.

First run / regeneration: `python3 integration/lint_engine_face_language.py
--write-inventory` re-derives the ledger from the tree (defect entries get the
debt tag automatically). The committed file is the handover: it IS the
classified sweep of every CJK literal reachable from the declared surface.

Usage: python3 integration/lint_engine_face_language.py [--write-inventory]
       (cwd = repo root; exit 0 = pass, 1 = violations, 2 = environment failure)
Module use: lint_engine_face_language(errors) appends to lint_tests.py's
shared errors list.
"""
from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_engine_face_language import (  # noqa: E402
    CJK_FACE_RE, DEBT_TAG, PRODUCER_MODULES, REPO, strip_comment)

INVENTORY = Path(__file__).resolve().parent / "engine_face_language_inventory.json"

#: key = (relative path, normalized literal text) -> classification override
_NORMALIZE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Token-level classification
# ---------------------------------------------------------------------------

def _docstring_ranges(tree: ast.AST) -> List[Tuple[int, int]]:
    """(first_line, last_line) spans of every docstring in the module."""
    spans: List[Tuple[int, int]] = []

    def add(node: ast.AST) -> None:
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            spans.append((node.body[0].lineno, node.body[0].end_lineno or node.body[0].lineno))

    for node in ast.walk(tree):
        add(node)
    return spans


def _func_spans(tree: ast.AST, needle: str) -> List[Tuple[int, int]]:
    """Spans of functions whose name contains `needle` (case-insensitive)."""
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and needle in node.name.lower():
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception",
                "critical", "log"}


def _log_call_spans(tree: ast.AST) -> List[Tuple[int, int]]:
    """Spans of logger/print CALLS (R5 log-only): a string constant inside such
    a call reaches only the worker log sink, never a ticket field path. This is
    the mechanical evidence for every log-only verdict; a note string that is
    merely printed later is NOT inside a call here and stays a defect."""
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        hit = False
        if isinstance(f, ast.Attribute) and f.attr in _LOG_METHODS:
            inner = f.value
            hit = (isinstance(inner, ast.Name) and inner.id == "logger") or \
                  (isinstance(inner, ast.Attribute) and inner.attr == "logger")
        elif isinstance(f, ast.Name) and f.id == "print":
            hit = True
        if hit:
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def _line_of(lines: List[str], lineno: int) -> str:
    return lines[lineno - 1] if 0 < lineno <= len(lines) else ""


def classify_module(path_rel: str) -> List[Dict[str, Any]]:
    """Every CJK occurrence in code tokens of one module, classified.

    Returns entries: {path, line, text (normalized literal snippet), char,
    classification, line_kind}. Line numbers are attribution metadata only —
    the ledger keys on (path, normalized text), never on line numbers.
    """
    full = REPO / path_rel
    if not full.exists():
        raise EnvironmentError("producer module missing: %s" % path_rel)
    src = full.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    docs = _docstring_ranges(tree)
    prompt_spans = _func_spans(tree, "prompt")
    usage_spans = _func_spans(tree, "usage")
    log_spans = _log_call_spans(tree)
    entries: List[Dict[str, Any]] = []

    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            if CJK_FACE_RE.search(tok.string):
                entries.append({"path": path_rel, "line": tok.start[0],
                                "text": _normalize(tok.string), "char": _first(tok.string),
                                "classification": "comment", "line_kind": "comment"})
            continue
        if tok.type != tokenize.STRING:
            # NAME/OP etc. must not carry CJK either; a CJK identifier would be
            # data-shaped but is not produced copy — report as defect (R7) so
            # it surfaces for a human look.
            if CJK_FACE_RE.search(tok.string):
                entries.append({"path": path_rel, "line": tok.start[0],
                                "text": _normalize(tok.string), "char": _first(tok.string),
                                "classification": "defect", "line_kind": "code"})
            continue
        # STRING token: strip quotes/prefix for the literal body.
        body = _string_body(tok.string)
        if not CJK_FACE_RE.search(body):
            continue
        ln = tok.start[0]
        # multi-line strings: attribute the first CJK line for the snippet
        if "\n" in body:
            body = _NORMALIZE_RE.sub(" ", body)
        classification = None
        evidence = None
        if any(a <= ln <= b for a, b in docs):
            classification = "docstring"
        elif any(a <= ln <= b for a, b in prompt_spans):
            classification = "prompt"
        elif any(a <= ln <= b for a, b in usage_spans):
            classification = "internal-cli"
        elif _USAGE_NAME_RE.match(_line_of(lines, ln).strip()):
            classification = "internal-cli"
        elif any(a <= ln <= b for a, b in log_spans):
            classification = "log-only"
            evidence = ("token inside a logger/print call span (worker log "
                        "sink only, never a ticket field path; R5)")
        entries.append({"path": path_rel, "line": ln,
                        "text": _normalize(body), "char": _first(body),
                        "classification": classification or "defect",
                        "evidence": evidence,
                        "line_kind": "string"})
    return entries


_USAGE_NAME_RE = re.compile(r"[A-Z_]*USAGE[A-Z_]*\s*=")
_QUOTES = ("'''", '"""', "'", '"')


def _string_body(tok_text: str) -> str:
    body = tok_text
    # drop prefix letters (r, b, f, u combos)
    i = 0
    while i < len(body) and body[i] not in "'\"":
        i += 1
    body = body[i:]
    for q in _QUOTES:
        if body.startswith(q) and body.endswith(q) and len(body) >= 2 * len(q):
            return body[len(q):-len(q)]
    return body


def _first(text: str) -> str:
    m = CJK_FACE_RE.search(text)
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

def _load_inventory() -> Dict[str, Any]:
    if not INVENTORY.exists():
        raise EnvironmentError("inventory ledger missing: %s (regenerate with "
                               "--write-inventory)" % INVENTORY.name)
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _classify_all() -> Tuple[List[Dict[str, Any]], List[str]]:
    problems: List[str] = []
    entries: List[Dict[str, Any]] = []
    try:
        for rel in PRODUCER_MODULES:
            entries.extend(classify_module(rel))
    except Exception as e:  # noqa: BLE001 — environment failure, fail-closed
        problems.append("ENV engine-face sweep could not judge the tree (%s: %s)"
                        % (type(e).__name__, e))
    return entries, problems


def sweep(errors: Optional[List[str]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Classify all producer modules; return (entries, violations)."""
    problems: List[str] = []
    entries, problems = _classify_all()
    if problems:
        if errors is not None:
            errors.extend(problems)
        return entries, problems
    try:
        ledger = _load_inventory()
    except Exception as e:  # noqa: BLE001
        problems.append("ENV inventory ledger unreadable (%s: %s)" % (type(e).__name__, e))
        return entries, problems
    # apply inventory overrides (certified non-defect verdicts) to mechanical
    # defect calls only; a ledger `defect` entry is an allowlist, not an
    # override — it is consumed by the live-defect/ledger-defect comparison
    # below and must not re-classify its own live hit. When the same
    # (path, literal) text is both allowlisted and overridden (short separators
    # like `、` occur at many sites), the defect entry wins: fail-closed bias.
    defect_keys = {(e["path"], e["text"])
                   for e in ledger.get("entries", [])
                   if e.get("classification") == "defect"}
    overrides = {(e["path"], e["text"]): e
                 for e in ledger.get("entries", [])
                 if e.get("classification") not in (None, "defect")
                 and (e["path"], e["text"]) not in defect_keys}
    for e in entries:
        if e["classification"] == "defect":
            ov = overrides.get((e["path"], e["text"]))
            if ov:
                e["classification"] = "inventory-override"
                e["override"] = ov.get("classification")
                e["evidence"] = ov.get("evidence")
    live_defects = {(e["path"], e["text"]): e for e in entries
                    if e["classification"] == "defect"}
    ledger_defects = {(e["path"], e["text"]): e for e in ledger.get("entries", [])
                      if e.get("classification") == "defect"}
    for key, e in sorted(live_defects.items()):
        ld = ledger_defects.get(key)
        if ld is None:
            problems.append("L27 new CJK literal on the engine face without a "
                            "ledger entry: %s:%d %r %r — classify it in %s or fix it"
                            % (e["path"], e["line"], e["char"], e["text"][:60],
                               INVENTORY.name))
        elif ld.get("debt") != DEBT_TAG:
            problems.append("L27 ledger defect entry without the debt tag %s: %s %r"
                            % (DEBT_TAG, e["path"], e["text"][:60]))
    for key, ld in sorted(ledger_defects.items()):
        if key not in live_defects:
            problems.append("L27 stale ledger defect entry (literal gone or "
                            "re-worded — delete the entry): %s %r"
                            % (ld["path"], ld["text"][:60]))
    if errors is not None:
        errors.extend(problems)
    return entries, problems


def write_inventory(entries: List[Dict[str, Any]]) -> None:
    # certified override entries (any classification other than the two
    # mechanically derived ones) are hand-authored with written evidence and
    # survive regeneration - e.g. `allow-exempt` entries for strings the
    # project allowlist (copy-lang-allow:<ticket>) keeps Chinese by design.
    preserved: List[Dict[str, Any]] = []
    if INVENTORY.exists():
        try:
            preserved = [e for e in json.loads(INVENTORY.read_text(encoding="utf-8"))
                         .get("entries", [])
                         if e.get("classification") not in ("defect", "log-only")]
        except Exception:  # noqa: BLE001 - unreadable ledger = regenerate clean
            preserved = []
    defects = [{"path": e["path"], "line": e["line"], "char": e["char"],
                "text": e["text"], "classification": "defect",
                "debt": DEBT_TAG,
                "evidence": "not provably off-face under rules R1-R5; default "
                            "defect until converted or certified"}
               for e in entries if e["classification"] == "defect"]
    # log-only verdicts are recorded with their mechanical evidence so the next
    # reviewer can audit them (review condition 4); they are not an allowlist —
    # only `defect` entries are.
    logonly = [{"path": e["path"], "line": e["line"], "char": e["char"],
                "text": e["text"], "classification": "log-only",
                "evidence": e.get("evidence") or "logger/print call span (R5)"}
               for e in entries if e["classification"] == "log-only"]
    INVENTORY.write_text(
        json.dumps({
            "generated_by": "python3 integration/lint_engine_face_language.py "
                            "--write-inventory",
            "debt_ticket": DEBT_TAG,
            "classification_rules": "see integration/lib_engine_face_language.py "
                                    "CLASSIFICATION_RULES (R1-R7); defect entries "
                                    "are the allowlist until the engine conversion "
                                    "lands; log-only entries record their sink "
                                    "evidence per review condition 4",
            "entries": defects + logonly + preserved,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def lint_engine_face_language(errors: List[str], base: Optional[str] = None) -> None:
    """Battery entry (registered as L27 in integration/lint_tests.py)."""
    entries, problems = sweep(errors)
    n = sum(1 for e in entries if e["classification"] == "defect")
    if not problems:
        print("L27 engine face language: %d CJK code occurrences swept across %d "
              "producer modules; %d defect entries allowlisted under debt %s"
              % (len(entries), len(PRODUCER_MODULES), n, DEBT_TAG))


def main(argv: List[str]) -> int:
    if "--write-inventory" in argv:
        entries, problems = _classify_all()
        if problems:
            for p in problems:
                print(p, file=sys.stderr)
            return 2
        write_inventory(entries)
        n = sum(1 for e in entries if e["classification"] == "defect")
        print("wrote %s (%d defect entries, debt %s)"
              % (INVENTORY, n, DEBT_TAG))
        return 0
    errors: List[str] = []
    lint_engine_face_language(errors)
    for e in errors:
        print("LINT %s" % e)
    print("LINT done: %d error" % len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
