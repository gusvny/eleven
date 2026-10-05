#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_refusal_copy_english.py — engine refusal/receipt copy an operator
reads is English, and stays precise (t261004-36, gray-box L2/L3, offline
seconds, zero docker/ports/git).

intent (user-perceivable): host order 261004 makes console-visible copy
English; engine refusal and receipt strings land on the ticket face and in
admin call results the operator reads. This scenario locks the FAMILY-WIDE
language property — every operator-readable refusal/receipt string the engine
produces is English (no CJK ideographs, no kana) — while refusing decisions do
not move: same booleans, same machine-read tokens (the path-gate receipt key
that is_gate_refusal consumes stays byte-identical). A refusal must stay
actionable: the offending op/key/path is still echoed into the text.

Two legs:
- Behavioral (public API, subprocess-isolated): executor_grants declaration
  validation errors, the executor-grant judge refusals (meta-permission
  lock-out, unmapped op, absent declaration) and path_gates gate refusal
  notes. Decision values asserted verbatim; refusal text asserted CJK-free
  with the offending token echoed.
- Static AST sweep: in every server/engine/*.py, CJK string constants are
  forbidden in the operator-readable refusal/receipt positions — arguments of
  ValueError(...) calls and dict-literal values under the keys reason / why /
  detail / problems / suggestion / red_line / note — except the declared
  machine-token tuple SCAN_SUGGESTIONS (its keys are consumed by plugin-side
  code; renaming them is a cross-write-set contract change, tracked by the
  implement handover). Docstrings and comments are not inspected; prompt
  template data lives in other dict keys and is deliberately out of this
  ticket (declared-left list lives in the plan/handover).

intent split: exact English wording and per-message substring asserts belong
to developer L1 (unit tests, including the carried t261004-28 tests); the
per-diff mechanical gate is t261004-24's scenario; the marker retirement
guard is t261004-36-no-data-marker. This entry locks only "the operator
reads English and the refusal still names its cause".

Three states: python3 or server/engine missing = ENV_FAIL exit 2; assertions
FAIL = exit 1 (TDD red expected until implement lands; arbitrate/merge must
be green).
Run directly: python3 integration/t261004-36/sc_engine_refusal_copy_english.py (cwd=repo root).
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"

CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

# Dict keys whose string values are operator-readable refusal/receipt copy.
RECEIPT_KEYS = {"reason", "why", "detail", "problems", "suggestion",
                "red_line", "note"}
# Machine-read token family (shared.py SCAN_SUGGESTIONS) whose KEYS are
# consumed outside this ticket's write set (workbench scan-report smoke);
# deliberately left until the cross-write-set contract moves.
TOKEN_TARGETS = {"SCAN_SUGGESTIONS"}


def probe() -> int:
    """In-process behavioral leg; printed as PASS/FAIL lines + SUMMARY."""
    import executor_grants as eg  # noqa: E402
    import path_gates  # noqa: E402

    failures: list[str] = []

    def check(name, cond, detail=""):
        if cond:
            print("PASS %s" % name)
        else:
            print("FAIL %s: %s" % (name, detail))
            failures.append(name)

    def no_cjk(s):
        return isinstance(s, str) and s.strip() != "" and not CJK_RE.search(s)

    # --- declaration validation errors (public, pure) ---
    _, err = eg.validate_declaration({})
    check("validate_declaration empty doc refusal english",
          no_cjk(err), "err=%r" % (err,))
    _, err = eg.validate_declaration({"grants": {"sign": True}})
    check("validate_declaration missing version names field",
          no_cjk(err) and "version" in (err or ""), "err=%r" % (err,))
    _, err = eg.validate_declaration({"version": 1, "grants": {"bogus.op": True}})
    check("validate_declaration unknown grant op names op",
          no_cjk(err) and "bogus.op" in (err or ""), "err=%r" % (err,))

    # --- judge_core refusals (IO-injected pure core, declared channel) ---
    common = dict(channel="arg", key="sandbar", now_ms=1,
                  declared_sessions=("s1",), caller_session="s1")

    v = eg.judge_core(op=eg.META_OP, load_face=lambda k: {"ok": True},
                      audit_sink=lambda *a, **kw: None, **common)
    check("meta-permission lockout refusal english and names op",
          v.get("allowed") is False and no_cjk(v.get("why"))
          and eg.META_OP in v.get("why", ""), "v=%r" % (v,))
    check("meta-permission lockout decision unchanged (enforced face)",
          v.get("grant_op") == eg.META_OP, "v=%r" % (v,))

    v = eg.judge_core(op="bogus.op", load_face=lambda k: {"ok": True},
                      audit_sink=lambda *a, **kw: None, **common)
    check("unmapped op refusal english and echoes op",
          v.get("allowed") is False and no_cjk(v.get("why"))
          and "bogus.op" in v.get("why", ""), "v=%r" % (v,))

    v = eg.judge_core(op="sign",
                      load_face=lambda k: {"ok": False, "declared": True,
                                           "file": "g.json",
                                           "kind": "absent",
                                           "reason": "declaration absent"},
                      audit_sink=lambda *a, **kw: None, **common)
    check("absent-declaration refusal english, names key and grant",
          v.get("allowed") is False and no_cjk(v.get("why"))
          and "sandbar" in v.get("why", "") and "sign" in v.get("why", ""),
          "v=%r" % (v,))

    # --- path gate refusal receipt (public note builder) ---
    note = path_gates.gate_refusal_note("implement",
                                        ["app/somewhere/x.py"],
                                        "unauthorized_path")
    check("path gate refusal note english and names file",
          no_cjk(note) and "app/somewhere/x.py" in note, "note=%r" % (note,))
    check("path gate machine-read receipt key unchanged",
          path_gates.is_gate_refusal(note), "note=%r" % (note,))
    note = path_gates.gate_refusal_note("create_plan", ["a.py"],
                                        "unknown_stage")
    check("unknown-stage refusal note english and names stage",
          no_cjk(note) and "create_plan" in note, "note=%r" % (note,))

    print("SUMMARY leg=behavioral fail=%d" % len(failures))
    return 1 if failures else 0


def docstring_nodes(tree):
    firsts = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                firsts.add(id(body[0]))
    return firsts


def static_leg():
    """AST sweep: no CJK constants in operator-readable refusal positions."""
    failures: list[str] = []
    for py in sorted(ENGINE.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        skip = docstring_nodes(tree)
        for node in ast.walk(tree):
            # assignment-target exemption: declared machine-token tuples
            if isinstance(node, ast.Assign):
                names = {t.id for t in node.targets
                         if isinstance(t, ast.Name)}
                if names & TOKEN_TARGETS:
                    continue
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Name) and node.func.id == "ValueError":
                for arg in node.args:
                    for c in _consts(arg):
                        if id(c) in skip:
                            continue
                        if CJK_RE.search(str(c.value)):
                            failures.append("%s ValueError arg %r"
                                            % (py.name, str(c.value)[:60]))
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and \
                            str(k.value) in RECEIPT_KEYS:
                        for c in _consts(v):
                            if id(c) in skip:
                                continue
                            if CJK_RE.search(str(c.value)):
                                failures.append("%s dict[%s]=%r"
                                                % (py.name, k.value,
                                                   str(c.value)[:60]))
    for f in sorted(set(failures)):
        print("FAIL static: %s" % f)
    print("SUMMARY leg=static fail=%d" % len(failures))
    return 1 if failures else 0


def _consts(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n
        # %-format and f-string refusal text: the constant pieces are the copy
        if isinstance(n, ast.BinOp):
            for c in _consts(n.left):
                yield c
            for c in _consts(n.right):
                yield c


def main():
    if not ENGINE.is_dir():
        print("ENV_FAIL: engine tree missing: %s" % ENGINE)
        return 2
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        sys.path.insert(0, str(ENGINE))
        try:
            rc = probe()
        except ImportError as e:
            print("ENV_FAIL: engine module import failed: %s" % e)
            return 2
        return rc
    p = subprocess.run([sys.executable, __file__, "--probe"],
                       capture_output=True, text=True, cwd=str(REPO),
                       timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-4000:])
    if "ENV_FAIL" in out or p.returncode == 2:
        print("FAIL/ENV: behavioral leg could not run")
        return 2
    rc = 0 if p.returncode == 0 else 1
    rc |= static_leg()
    print("PASS=t261004-36-refusal-copy-english" if rc == 0
          else "FAIL=t261004-36-refusal-copy-english")
    return rc


if __name__ == "__main__":
    sys.exit(main())
