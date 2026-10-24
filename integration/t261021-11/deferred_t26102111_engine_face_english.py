#!/usr/bin/env python3
"""sc_t26102111_engine_face_english.py — produced engine faces are ASCII
(t261021-11).

Run directly: python3 integration/t261021-11/sc_t26102111_engine_face_english.py
(cwd = repo root). Offline seconds, stdlib only, zero docker/Temporal/browser,
never touches 3099.

Incident (t261021-05): the stage arbitrate block detail rendered half English
half Chinese — the path-gate refusal joined the allowed-prefix list with the
CJK enumeration comma `、` (path_gates.py:838) and the auto-quarantine settle
notes carried the trailer `；本轮已自动处置：%s` (agent_activities.py:3668/:3782).
Host orders 260924/260925: ticket-face text is English; data is NOT translated.

Intent split (no intent-level duplication):
  - t261008-47-ticket-face-english owns the static AST scan of dev_lane /
    light_lane / agent_activities COPY positions (_mark/_blocked/_handoff/
    _auto_rework args, Stage acceptance/desc, msg commit subjects). It does NOT
    scan path_gates, executor_requests, or the note/notes builders.
  - The developer's lib+lint (lib_engine_face_language.py +
    lint_engine_face_language.py, planned in this ticket) owns the declared
    surface list, the predicate, and the classified full-surface inventory.
    This scenario is the ADVERSARIAL side: it imports NEITHER of those, calls
    the real producers over ASCII-only inputs, and judges the produced strings.
  - This entry owns: produced-face journeys (gate refusal, blocked detail,
    executor-request refusal, settle-note builders) + data-passthrough +
    narrowness controls. Pre-implementation tree red naming module:line is the
    TDD signal; green required at the integration gate / merge.

Legs:
  A  gate refusal notes — path_gates.gate_refusal_note over EVERY declared
     stage of STAGE_PATH_RULES (prefixes kind included, so the :838 join runs)
     with ASCII-only violation names: the produced note carries no CJK
     ideograph, CJK punctuation (U+3000–303F) or fullwidth form (FF00–FFEF).
     Separators count.
  B  blocked detail — path_gates.gate_red_detail for the unauthorized_path
     reason with ASCII evidence: every produced field (check_id, evidence,
     disposition text) is CJK-free.
  C  executor request refusal face — executor_requests.validate_request with
     malformed/ASCII bodies: the produced question/detail/error strings are
     CJK-free.
  D  settle-note builders — agent_activities is NOT importable offline
     (Temporal-coupled), so an INDEPENDENT AST scan collects the string
     literals concatenated or appended into `note`/`notes` (augassign and
     .append calls) — the log[].note producer expressions — and asserts none
     carries CJK, naming file:line + literal verbatim.
  E  data passthrough — a CJK violation name (a Chinese path written by an
     agent) passed through gate_refusal_note must come through VERBATIM (the
     engine never translates data); the check records template-side and
     data-side characters separately so leg A's ASCII assertion is judged only
     on template-produced text.
  F  narrowness control — the same scanner of leg D on a synthetic module
     flags a CJK `note += "…"` literal and stays silent for the same literal
     inside a comment, a docstring, a prompt variable, and a plain logger call.
"""

from __future__ import annotations

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

#: CJK ideographs + CJK punctuation + fullwidth forms. Separators count.
CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

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


def section(title):
    print("\n== %s ==" % title)


def engine_src(rel):
    path = os.path.join(ENGINE, rel)
    with open(path, "r", encoding="utf-8") as fh:
        return path, fh.read()


def note_builder_findings(rel, source):
    """AST scan: CJK string constants concatenated/appended into note/notes.

    Certified allowlist exemptions are honored: a literal whose source line
    carries the project marker `copy-lang-allow:<ticket>` is a certified
    surviving copy (operator ruling; t261016-21 precedent) and is not a
    finding — the inline marker is the written evidence and the L26 ledger
    carries the same certification as `allow-exempt`.
    """
    src_lines = source.splitlines()
    findings = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "append" and node.args
              and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))
              and isinstance(node.func.value, ast.Name)):
            targets = [node.func.value.id]
        if not targets or targets[0] not in ("note", "notes"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                    and CJK_RE.search(sub.value):
                line = src_lines[sub.lineno - 1] \
                    if 0 < sub.lineno <= len(src_lines) else ""
                if "copy-lang-allow:" in line:
                    continue  # certified surviving copy, marker = evidence
                findings.append((rel, sub.lineno, sub.value))
    return findings


def main():
    if not os.path.isdir(ENGINE):
        print("ENV_FAIL: engine tree missing: %s" % ENGINE)
        return 2
    sys.path.insert(0, ENGINE)
    import path_gates
    import executor_requests

    # ---- A: gate refusal note over every declared stage ----
    section("A gate_refusal_note is CJK-free for ASCII violations, all stages")
    findings_a = []
    stages = sorted(getattr(path_gates, "STAGE_PATH_RULES", {}).items())
    ok(len(stages) > 0, "STAGE_PATH_RULES non-empty (%d stages)" % len(stages))
    for stage_id, rule in stages:
        note = path_gates.gate_refusal_note(
            stage_id, ["integration/probe_file.py"], "unauthorized_path")
        m = CJK_RE.search(note)
        if m:
            findings_a.append((stage_id, m.group(0), note))
    for stage_id, ch, note in findings_a:
        print("  CJK in refusal for %s: %r in %r" % (stage_id, ch, note[:120]))
    ok(not findings_a, "gate_refusal_note CJK-free across %d stages" % len(stages))
    # the named sample: a prefixes-kind stage must produce the allowed-face
    # list with an ASCII separator, never `、`
    prefix_stages = [s for s, r in stages if r.get("kind") == "prefixes"]
    ok(bool(prefix_stages), "a prefixes-kind stage exists to exercise the join")
    if prefix_stages:
        note = path_gates.gate_refusal_note(
            prefix_stages[0], ["integration/probe_file.py"], "unauthorized_path")
        ok(not CJK_RE.search(note),
           "prefixes-join note is CJK-free incl. separator (%s)" % prefix_stages[0])
    # the separator only shows when the join has TWO or more elements — the
    # declared rules happen to carry single-prefix stages, so synthesize one
    # (in-process module-dict injection; the producer is a pure function)
    staged_rules = dict(path_gates.STAGE_PATH_RULES)
    staged_rules["integration/probe_multi_prefix"] = {
        "kind": "prefixes", "prefixes": ("integration", "server")}
    saved = path_gates.STAGE_PATH_RULES
    path_gates.STAGE_PATH_RULES = staged_rules
    try:
        note = path_gates.gate_refusal_note(
            "integration/probe_multi_prefix", ["docs/x.md"], "unauthorized_path")
    finally:
        path_gates.STAGE_RULES = saved
        path_gates.STAGE_PATH_RULES = saved
    ok(not CJK_RE.search(note),
       "multi-prefix join note is CJK-free — separator counted%s"
       % ("" if not CJK_RE.search(note) else " in %r" % note[:160]))

    # ---- B: blocked detail ----
    section("B gate_red_detail is CJK-free for ASCII evidence")
    det = path_gates.gate_red_detail(
        prefix_stages[0] if prefix_stages else "arbitrate",
        ["integration/probe_file.py"], "unauthorized_path",
        "seed refusal note")
    det_text = det if isinstance(det, str) else repr(det)
    m = CJK_RE.search(det_text)
    ok(m is None, "gate_red_detail carries no CJK%s"
       % ("" if m is None else " (%r)" % m.group(0)))

    # ---- C: executor request refusal face ----
    section("C validate_request refusal strings are CJK-free")
    refusals = []
    for body in ({}, {"project": ""},
                 {"project": "p", "question": "ok?", "detail": ""},
                 {"project": "p", "question": "", "detail": "d"}):
        res = executor_requests.validate_request(body)
        text = res if isinstance(res, str) else repr(res)
        m = CJK_RE.search(text)
        if m:
            refusals.append((body, m.group(0)))
    for body, ch in refusals:
        print("  CJK in refusal for %r: %r" % (body, ch))
    ok(not refusals, "validate_request refusal faces CJK-free")

    # ---- D: settle-note builders in agent_activities ----
    section("D note/notes builder literals in agent_activities are CJK-free")
    path, src = engine_src("agent_activities.py")
    findings_d = note_builder_findings("agent_activities.py", src)
    for rel, line, lit in findings_d:
        print("  CJK note literal at %s:%d: %r" % (rel, line, lit))
    ok(not findings_d,
       "no CJK in note/notes builder literals (%d findings, want 0)" % len(findings_d))
    path_pg, src_pg = engine_src("path_gates.py")
    findings_pg = note_builder_findings("path_gates.py", src_pg)
    for rel, line, lit in findings_pg:
        print("  CJK note literal at %s:%d: %r" % (rel, line, lit))
    ok(not findings_pg, "no CJK in path_gates note builder literals")

    # ---- E: data passthrough ----
    section("E data is never translated")
    cjk_name = "集成/探针文件.py"
    note = path_gates.gate_refusal_note(
        prefix_stages[0] if prefix_stages else "arbitrate",
        [cjk_name], "unauthorized_path")
    ok(cjk_name in note, "CJK violation name passes through verbatim")
    stripped = CJK_RE.sub("", note.replace(cjk_name, ""))
    ok(not CJK_RE.search(stripped),
       "template-side text around CJK data is CJK-free")

    # ---- F: narrowness control ----
    section("F narrowness control on a synthetic module")
    synthetic = (
        "# 注释里的 CJK 不算\n"
        'PROMPT = "提示词发给模型，不上票面"\n'
        'import logging\n'
        'logging.info("日志行不上面")\n'
        'note = ""\n'
        'note += "；缺陷字面"\n'
    )
    fnd = note_builder_findings("synthetic.py", synthetic)
    ok(len(fnd) == 1, "synthetic: exactly 1 finding (the note += literal), got %d"
       % len(fnd))

    # ---- G: console copy mirrors travel with the engine copy ----
    # The workbench capped-list tail is a COPY FORK of the engine note tail
    # `（等共 %d 条）` (agent_activities note builder; re-plan gen1 file 7).
    # If the engine copy converts and the mirror does not, the console tail
    # forks from the ticket-face wording (host order 260925: console copy
    # English). The contract pinned here is the forked tail literal itself —
    # NOT a whole-file CJK ban (smoke labels and internal test copy are out of
    # the ticket's scope; comments are out of scope by the scope clause).
    section("G workbench mirrors carry no forked engine tail literal")
    TAIL_LIT = "等共"
    mirrors = [
        "server/plugins/workbench/src/host/agent-usage.ts",
        "server/plugins/workbench/src/host/agent-live.ts",
        "server/plugins/workbench/smoke/agent-usage.mjs",
    ]
    findings_g = []
    for rel in mirrors:
        path_w = os.path.join(REPO, rel)
        if not os.path.exists(path_w):
            print("  missing mirror (not counted): %s" % rel)
            continue
        with open(path_w, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                code = line.split("//", 1)[0]  # comments out of scope
                if TAIL_LIT in code:
                    findings_g.append((rel, lineno, line.strip()[:100]))
    for rel, lineno, text in findings_g:
        print("  forked tail literal at %s:%d: %s" % (rel, lineno, text))
    ok(os.path.exists(os.path.join(REPO, mirrors[0])),
       "workbench mirror tree present")
    ok(not findings_g,
       "workbench mirrors CJK-tail-free (%d findings, want 0)" % len(findings_g))

    print("\nSCENARIOS: sc_t26102111_engine_face_english passed=%d failed=%d"
          % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
