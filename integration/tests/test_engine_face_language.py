# -*- coding: utf-8 -*-
"""UT for the engine ticket-face language contract (t261021-11).

The declared surface list, the predicate and the classified sweep live in
integration/lib_engine_face_language.py and integration/lint_engine_face_language.py;
the adversarial produced-face journeys (gate refusal / blocked detail /
executor refusal / note builders / data passthrough) are the scenario
integration/t261021-11/sc_t26102111_engine_face_english.py, which imports
NEITHER of those modules on purpose. This file is the developer side: it tests
the contract mechanics (surface list, predicate, malformed inputs, ASCII
fail-closed fixtures, inventory gate bite) so a regression here is red in
seconds, offline.

Debt (review condition 1): the two named engine sources are still Chinese and
the conversion rides as handover (write set of this ticket is integration/
only). The fixture tests that target them carry xfail(strict=True) with the
debt tag t261021-11 in the reason; when the conversion lands they XPASS, the
strict marker turns that into a loud failure, and the converter must delete
the marker in the same change. Everything else fails loudly on any NEW CJK.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "server" / "engine"))

import lib_engine_face_language as lib  # noqa: E402
import lint_engine_face_language as lint  # noqa: E402
import path_gates  # noqa: E402

DEBT = "t261021-11"

ALL_REASON_CODES = ["protected_path", "unknown_stage", "write_set_missing",
                    "ui_dirs_missing", "status_failed", "unauthorized_path"]

REQUIRED_FIELD_PATHS = [
    "log[].note",
    "blocked_detail.check_id", "blocked_detail.item",
    "blocked_detail.reason_code", "blocked_detail.next_action",
    "blocked_detail.evidence",
    "pending[].note",
    "executor_request.question", "executor_request.detail",
    "console_labels.identifiers",
]


# ---------------------------------------------------------------------------
# Surface list + predicate
# ---------------------------------------------------------------------------

def test_surface_list_declares_every_scoped_field_path():
    missing = [p for p in REQUIRED_FIELD_PATHS if not lib.is_face_string(p)]
    assert not missing, "declared surface list is missing scoped paths: %s" % missing


def test_predicate_answers_false_off_surface_and_on_malformed_input():
    assert not lib.is_face_string("log[].notes")          # near-miss path
    assert not lib.is_face_string("")
    assert not lib.is_face_string(None)
    assert not lib.is_face_string(123)
    assert not lib.is_face_string(["log[].note"])


def test_console_labels_item_declares_its_reason():
    # review condition 3: the item is covered by declaration, not left vague
    entry = lib.FACE_FIELD_PATHS["console_labels.identifiers"]
    text = json.dumps(entry, ensure_ascii=False)
    assert "already-English" in text or "identifier" in text
    assert any("STAGE_PATH_RULES" in p for p in entry["producers"])


# ---------------------------------------------------------------------------
# Character predicate + malformed inputs (house hook)
# ---------------------------------------------------------------------------

def test_find_cjk_counts_separators_and_fullwidth_forms():
    offs = dict(lib.find_cjk("only 甲、乙"))
    assert "、" in set(offs.values())          # CJK punctuation U+3001
    assert "甲" in set(offs.values())          # ideograph
    assert lib.find_cjk("only a, b") == []
    assert "；" in set(dict(lib.find_cjk("a；b")).values())
    assert "％" in set(dict(lib.find_cjk("a％b")).values())   # fullwidth


def test_find_cjk_and_face_violations_survive_malformed_input():
    assert lib.find_cjk(None) == []
    assert lib.find_cjk(b"bytes") == []
    assert lib.find_cjk(123) == []
    assert lib.face_violations(None) == []
    assert lib.face_violations("") == []
    assert len(lib.face_violations("a、b", what="note")) == 1


def test_producer_location_degrades_without_asserting_layout():
    loc = lib.producer_location(path_gates.gate_refusal_note)
    assert loc and "path_gates" in loc          # attribution, never a line pin
    assert lib.producer_location(len)            # builtin degrades, no raise


# ---------------------------------------------------------------------------
# Produced-face fixtures (real producers, ASCII-only data)
# ---------------------------------------------------------------------------

def _gate_note(stage_id, violations, reason):
    return path_gates.gate_refusal_note(stage_id, violations, reason)


@pytest.mark.parametrize("reason", ALL_REASON_CODES)
def test_gate_refusal_note_ascii_for_ascii_data(reason):
    note = _gate_note("arbitrate", ["integration/x.py"], reason)
    assert lib.face_violations(
        note, what="gate refusal note",
        producer=lib.producer_location(path_gates.gate_refusal_note)) == []


def test_gate_refusal_note_two_prefix_list_ascii():
    # the separator only surfaces when the join has 2+ elements; no declared
    # stage ships a multi-element prefixes rule, so synthesize one (fixture)
    # xfail(strict=True) debt marker REMOVED (re-plan gen1 step 4): the
    # protected-path conversion landed on main as 8f40ce3a and is merged into
    # this lane, so the assertion is enforced, not tolerated.
    original = dict(path_gates.STAGE_PATH_RULES)
    try:
        path_gates.STAGE_PATH_RULES["t26102111_fixture"] = {
            "kind": "prefixes", "prefixes": ("integration", "notes")}
        note = _gate_note("t26102111_fixture", ["server/x.py"], "unauthorized_path")
        assert lib.face_violations(note, what="gate refusal note") == []
    finally:
        path_gates.STAGE_PATH_RULES.clear()
        path_gates.STAGE_PATH_RULES.update(original)


@pytest.mark.parametrize("reason", ALL_REASON_CODES)
def test_blocked_detail_structured_fields_ascii(reason):
    detail = path_gates.gate_red_detail("arbitrate", ["integration/x.py"],
                                        reason, "note text")
    for field in ("check_id", "item", "reason_code", "next_action"):
        assert lib.face_violations(str(detail[field]),
                                   what="blocked_detail.%s" % field) == []


def test_blocked_detail_evidence_is_verbatim_note_not_translated():
    # data stays as written: the CJK chars in evidence are exactly the data's
    data = "用户笔记.md"
    detail = path_gates.gate_red_detail("arbitrate", [data],
                                        "unauthorized_path", "refused: %s" % data)
    out_cjk = [c for _, c in lib.find_cjk(str(detail["evidence"]))]
    assert out_cjk == [c for _, c in lib.find_cjk(data)]


def test_data_passthrough_verbatim_in_gate_refusal_note():
    data = "会话档.md"
    note = _gate_note("arbitrate", [data], "protected_path")
    assert data in note
    assert [c for _, c in lib.find_cjk(note)] == [c for _, c in lib.find_cjk(data)]


def test_blocked_detail_malformed_inputs_fail_visible_not_crash():
    detail = path_gates.gate_red_detail("", [], "", None)
    assert detail["check_id"] == "path_gate@unknown_stage"
    assert detail["evidence"] == ""
    assert detail["files"] == []
    assert lib.face_violations(str(detail["evidence"])) == []


# ---------------------------------------------------------------------------
# The second named source (agent_activities trailers) — source-anchored xfail
# ---------------------------------------------------------------------------

def _trailer_literals():
    """String literals carrying the auto-quarantine wording, bound by the
    surviving Chinese text (never by line numbers — review condition 2)."""
    src = (REPO / "server/engine/agent_activities.py").read_text(encoding="utf-8")
    import ast
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and "本轮已自动处置" in node.value:
            out.append(node.value)
    return out


def test_auto_quarantine_trailer_literals_ascii():
    bad = [lit for lit in _trailer_literals() if lib.find_cjk(lit)]
    assert bad == [], ("CJK trailer literals: %r" % bad[:3])


# ---------------------------------------------------------------------------
# Inventory gate mechanics
# ---------------------------------------------------------------------------

def test_committed_inventory_gate_is_green():
    errors: list = []
    entries, problems = lint.sweep(errors)
    assert not problems, problems
    assert entries
    lint.lint_engine_face_language(errors)
    assert errors == []


def test_inventory_defect_entries_all_carry_debt_tag():
    ledger = json.loads(lint.INVENTORY.read_text(encoding="utf-8"))
    defects = [e for e in ledger["entries"] if e["classification"] == "defect"]
    assert defects, "ledger lost its defect sweep"
    assert all(e.get("debt") == DEBT for e in defects)
    # the two named sources are in the sweep as defects
    named = [(e["path"], e["text"]) for e in defects]
    # the :838 separator join inside gate_refusal_note: one `、` site remains
    # (the docstring-side join at ~line 799, still debt); the converted one is gone
    assert ("server/engine/path_gates.py", "、") in named
    # the converted named source must have left the defect ledger
    assert ("server/engine/agent_activities.py", "；本轮已自动处置：%s") not in named


def test_inventory_logonly_entries_record_evidence():
    ledger = json.loads(lint.INVENTORY.read_text(encoding="utf-8"))
    logonly = [e for e in ledger["entries"] if e["classification"] == "log-only"]
    assert logonly, "log-only verdicts vanished from the ledger"
    assert all(e.get("evidence") for e in logonly)


def test_gate_bites_on_new_cjk_and_on_stale_entry():
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / lint.INVENTORY.name
        ledger = json.loads(lint.INVENTORY.read_text(encoding="utf-8"))
        # 1) drop the named separator -> it becomes a new unclassified defect
        pruned = dict(ledger)
        pruned["entries"] = [e for e in ledger["entries"]
                             if not (e["path"].endswith("path_gates.py")
                                     and e["text"] == "、")]
        copy.write_text(json.dumps(pruned, ensure_ascii=False), encoding="utf-8")
        saved = lint.INVENTORY
        lint.INVENTORY = copy
        try:
            errors: list = []
            _, problems = lint.sweep(errors)
            assert any("without a ledger entry" in p for p in problems), problems
            assert problems == errors
            # 2) a defect entry whose literal is gone -> stale red (no rot)
            stale = dict(ledger)
            stale["entries"] = list(stale["entries"]) + [
                {"path": "server/engine/path_gates.py", "line": 1, "char": "残",
                 "text": "残", "classification": "defect", "debt": DEBT,
                 "evidence": "planted stale entry"}]
            copy.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
            _, problems = lint.sweep(None)
            assert any("stale ledger defect entry" in p for p in problems), problems
            # 3) a defect entry without the debt tag -> red
            nodebt = dict(ledger)
            nodebt["entries"] = [dict(e, debt=None) if e["classification"] == "defect"
                                 else e for e in nodebt["entries"]]
            copy.write_text(json.dumps(nodebt, ensure_ascii=False), encoding="utf-8")
            _, problems = lint.sweep(None)
            assert any("without the debt tag" in p for p in problems), problems
        finally:
            lint.INVENTORY = saved


def test_write_inventory_shape_round_trip():
    entries, problems = lint._classify_all()
    assert not problems
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "inv.json"
        saved = lint.INVENTORY
        lint.INVENTORY = target
        try:
            lint.write_inventory(entries)
            ledger = json.loads(target.read_text(encoding="utf-8"))
        finally:
            lint.INVENTORY = saved
        assert ledger["debt_ticket"] == DEBT
        assert ledger["entries"]
        assert all("evidence" in e for e in ledger["entries"])
