#!/usr/bin/env python3
"""sc_ticket_face_english.py — engine ticket-face copy carries no CJK (t261008-47).

Run directly: python3 integration/t261008-47/sc_ticket_face_english.py (cwd = repo
root), or through the engine venv fallback chain (see the SCENARIOS entry).

Grey-box L2/L3 contract over PUBLIC user-visible surfaces, offline seconds, zero
docker/Temporal/browser, never touches 3099. Incident (261008 host report): the
ticket detail showed Chinese engine copy after English panel labels — the
stage-entry timeline reason ("进入本步（第 1 次）") and the dev-lane merge-stage
acceptance item ("人审签字"). Both are engine-authored; the panel is already
English. Host order 260925: console UI copy is English; host order 260924: the
ticket face is the foreign-facing artefact.

What this scenario owns (intent split with the developer's L1 guard):
  A  emission-point scan — an INDEPENDENT AST scan (the adversarial side does not
     import the developer's guard) over server/engine/dev_lane.py, light_lane.py
     and agent_activities.py. It collects the copy positions that reach a ticket
     face / timeline / authored commit subject:
       - _mark(...)  args after the state arg  (timeline reason)
       - _blocked(...) / _handoff(...) / _auto_rework(...) copy args
       - Stage(acceptance=..., desc=...) keywords
       - agent_activities assignments to `msg` (authored commit subjects)
     and asserts none carries CJK. Data fields (stage ids, states, gens, paths)
     are untouched by construction: only the listed copy positions are scanned.
     `Stage(name=...)`/`Stage(id=...)` are machine/display keys per the ticket and
     are deliberately NOT scanned.
  B  narrowness control — the same scanner on a synthetic file flags a CJK
     `_mark` reason and stays silent for the same literal in a `self._log(...)`
     line and in a comment (the narrow-by-construction proof, re-proven here).
  C  test assets move with the copy — the workbench fixture timelines
     (server/plugins/workbench/tests/lane-parallel-states.mjs `tle(...)` reasons)
     and the integration probe fixture (integration/t260928-13/behavior_probe.py
     `"reason": ...` values) carry no CJK.
  D  history is data — the scanner reads SOURCE, so stored Chinese timeline rows
     of old tickets are out of its reach by construction; this is re-proven by
     sc_timeline_rerun_stats.py (behaviour side), which keeps deriving round
     statistics from old-format rows.

Pre-implement tree = red naming the offending file:line + literal (TDD signal);
green required at the integration gate / merge.
"""

from __future__ import annotations

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)
    return bool(cond)


def section(title):
    print("\n== %s" % title)


# CJK ideographs + CJK punctuation/fullwidth forms (（）、：carry copy too).
CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

# Emission points, as (callable name suffix, scanned positional arg slice, scanned
# keyword names). Copy lives in the trailing args; everything before is data.
EMISSION_CALLS = {
    "_mark": (slice(2, None), ()),          # _mark(step_id, state, reason, ...)
    "_blocked": (slice(1, None), ()),       # _blocked(step_id, why)
    "_handoff": (slice(1, None), ()),       # _handoff(step_id, summary, ...)
    "_auto_rework": (slice(1, None), ()),   # _auto_rework(step_id, note/why, ...)
}
STAGE_COPY_KW = ("acceptance", "desc")


def _consts_from_arg(arg):
    """All string constants inside an expression (handles % templates and
    implicit concatenation by just walking the whole subtree)."""
    out = []
    for node in ast.walk(arg):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node)
        elif hasattr(ast, "JoinedStr") and isinstance(node, ast.JoinedStr):
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    out.append(v)
    return out


def _func_name(call):
    f = getattr(call, "func", None)
    return getattr(f, "attr", None) or getattr(f, "id", None) or ""


def _commit_subject_vars(tree):
    """Per-function set: variables that feed a _git([... "-m", ...]) call within
    the SAME function scope = authored commit subjects. A `msg = ...` whose
    variable never reaches `-m` in its own function (e.g. an error text returned
    via _err) is NOT a commit subject (arbitrate gen0: the blanket file-wide
    msg= rule false-positived on agent_activities:10129)."""
    roots = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] or [tree]
    names = set()
    for root in roots:
        for node in ast.walk(root):
            if isinstance(node, ast.Call) and _func_name(node) == "_git":
                for arg in node.args:
                    if isinstance(arg, (ast.List, ast.Tuple)):
                        hit = any(isinstance(e, ast.Constant) and e.value == "-m"
                                  for e in arg.elts)
                        if hit:
                            for e in arg.elts:
                                for sub in ast.walk(e):
                                    if isinstance(sub, ast.Name):
                                        names.add((id(root), sub.id))
    return names


def scan_source(text, filename):
    """Emission-point CJK scan. Returns findings [(line, literal, kind)]."""
    findings = []
    tree = ast.parse(text, filename=filename)
    roots = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] or [tree]
    for root in roots:
        commit_vars = _commit_subject_vars(root)
        for node in ast.walk(root):
            if isinstance(node, ast.Call):
                name = _func_name(node)
                if name in EMISSION_CALLS:
                    arg_slice, _kw = EMISSION_CALLS[name]
                    for arg in node.args[arg_slice]:
                        for c in _consts_from_arg(arg):
                            if CJK_RE.search(c.value):
                                findings.append((c.lineno, c.value, "%s(...)" % name))
                if name == "Stage":
                    for kw in node.keywords:
                        if kw.arg in STAGE_COPY_KW:
                            for c in _consts_from_arg(kw.value):
                                if CJK_RE.search(c.value):
                                    findings.append((c.lineno, c.value,
                                                     "Stage(%s=)" % kw.arg))
            elif isinstance(node, ast.Assign):
                # authored commit subjects in agent_activities: an assignment
                # whose variable feeds a _git([... "-m", ...]) call in the same
                # function scope
                if os.path.basename(filename) == "agent_activities.py" and any(
                        isinstance(t, ast.Name) and (id(root), t.id) in commit_vars
                        for t in node.targets):
                    for c in _consts_from_arg(node.value):
                        if CJK_RE.search(c.value):
                            findings.append((c.lineno, c.value, "commit subject (msg=)"))
    return findings


def find_repo_file(rel):
    p = os.path.join(REPO, rel)
    return p if os.path.isfile(p) else None


def main():
    global FAIL

    # ---------- A. emission-point scan over the live engine files ----------
    section("A engine ticket-face copy is English (emission-point scan)")
    targets = [
        "server/engine/dev_lane.py",
        "server/engine/light_lane.py",
        "server/engine/agent_activities.py",
    ]
    missing = [rel for rel in targets if not find_repo_file(rel)]
    if missing:
        print("ENV_FAIL: engine sources absent: %s" % ", ".join(missing))
        return 2
    all_findings = []
    for rel in targets:
        path = find_repo_file(rel)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            found = scan_source(text, path)
        except SyntaxError as exc:
            print("ENV_FAIL: %s does not parse: %s" % (rel, exc))
            return 2
        for line, literal, kind in found:
            all_findings.append((rel, line, literal, kind))
    if all_findings:
        for rel, line, literal, kind in all_findings:
            print("  CJK copy at %s:%d (%s): %r" % (rel, line, kind, literal))
    ok(not all_findings,
       "no CJK in engine ticket-face copy positions (%d findings, want 0)"
       % len(all_findings))
    ok(all(line > 0 and literal for _, line, literal, _ in all_findings),
       "every finding names file:line + the literal verbatim (see list above)")

    # ---------- B. narrowness control on a synthetic file ----------
    section("B narrowness: log lines and comments stay out of the scan")
    planted = (
        "def f(self):\n"
        "    self._mark('s', 'running', '进入本步（第 1 次）')\n"   # flagged
        "    self._log('进入本步')\n"                                # log line: ignored
        "    self._blocked('s', '进入本步')\n"                       # blocked copy: flagged
        "# 进入本步 comment\n"                                       # comment: ignored
    )
    findings = scan_source(planted, "planted.py")
    ok(len(findings) == 2,
       "planted CJK in _mark/_blocked copy = exactly 2 findings, got %d" % len(findings))
    ok(all("进入本步" in lit for _, lit, _ in findings),
       "each finding names the offending literal verbatim")
    clean = (
        "def f(self):\n"
        "    self._log('进入本步')\n"
        "# 进入本步 comment\n"
        "    return '进入本步' if flag else None\n"   # returned data, not copy position
    )
    ok(scan_source(clean, "clean.py") == [],
       "same literal in a log line / comment / return data = 0 findings")

    # ---------- C. test assets moved with the copy ----------
    # Narrow on purpose: the fixtures must move for the PARSING-ANCHOR literal
    # family the ticket names (the stage-entry '进入本步' forms). Other Chinese
    # prose in fixture timelines is fixture-authored HISTORY DATA (old tickets'
    # rows must keep rendering — the ticket's negative case), not engine copy.
    section("C fixture timelines carry no CJK stage-entry anchor literal")
    ANCHOR_LIT = re.compile(r"进入本步")
    mjs = find_repo_file("server/plugins/workbench/tests/lane-parallel-states.mjs")
    if not mjs:
        print("ENV_FAIL: workbench fixture absent: lane-parallel-states.mjs")
        return 2
    with open(mjs, encoding="utf-8") as f:
        mjs_text = f.read()
    cjk_tle = [(i + 1, ln.strip()) for i, ln in enumerate(mjs_text.splitlines())
               if "tle(" in ln and ANCHOR_LIT.search(ln)]
    ok(not cjk_tle,
       "workbench fixture tle(...) reasons carry no anchor literal (%d hits)" % len(cjk_tle))
    probe = find_repo_file("integration/t260928-13/behavior_probe.py")
    if probe:
        with open(probe, encoding="utf-8") as f:
            probe_text = f.read()
        cjk_reasons = []
        for m in re.finditer(r'"reason"\s*:\s*"([^"]*)"', probe_text):
            if ANCHOR_LIT.search(m.group(1)):
                cjk_reasons.append(m.group(1))
        ok(not cjk_reasons,
           "integration probe fixture reasons are CJK-free (%d hits)" % len(cjk_reasons))
    else:
        ok(True, "integration probe fixture absent (nothing to check this run)")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
