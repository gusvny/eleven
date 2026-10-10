#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-52: the fault-injection fixture registry UT.

Failure record (KI-222, 261008 + 261010): the brake scenario's planted fixture
outlived an interrupted run and an add-everything settle committed it into a
ticket's lane, where merge_check went red on L16/L17 findings that were the
fixture's, not the ticket's. This UT locks the developer L1 face:

- A registry truth table: exactly one recognition place
  (integration/lib_fault_injection.py); known fixture -> owning scenario;
  ordinary paths and malformed inputs (None, bytes, int, empty, absolute,
  `..` traversal, backslash) are TOTAL — never an exception, never a
  recognition (spec §2: not a gate on ordinary files).
- B note wording: refusal_note names file + reason
  'fault-injection fixture from <scenario>'; lint_fixture_note says
  'leftover fault-injection fixture from <scenario>' and answers "" for
  ordinary files (spec §5).
- C engine wiring: both add-everything settle sites in agent_activities.py
  consult the shared refusal strictly BEFORE `git add -A`, and the engine
  carries NO hard-coded fixture copy (a site that stops routing through the
  registry turns red here instead of silently disarming the advertised
  refusal). The loader degrades with a NAMED diagnostic on a broken registry,
  never a silent pass (zero-silent-degradation discipline).
- D scenario-side anchors (source-text, same face as t261004-34 B2): the brake
  scenario self-checks its registry entry, runs a pre-flight leak check, and
  wires reclaim to SIGINT/SIGTERM/atexit. The EXECUTABLE interrupt face (real
  SIGINT/SIGTERM against a running brake scenario) is the registered L3 case
  integration/t261009-52/sc_fixture_leak_brakes.py — an engine unit test must
  not spawn integration entries (the 260921 tier discipline), so the two faces
  split by tier exactly as the registry entry's intent declares.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
REPO = POC.parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402

FIXTURE = "server/engine/tests/test_zz_t26100420_planted_anchor_case.py"
SCENARIO = "t261004-20-test-anchor-brakes"
LIB = REPO / "integration" / "lib_fault_injection.py"


def _load_lib():
    """Import the shared registry module by path (same load stance as the
    engine's settle-time loader — no cross-tree package import)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("lib_fault_injection", LIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lfi = _load_lib()


# ---- A: registry truth table ------------------------------------------------

def test_known_fixture_recognised():
    assert lfi.fixture_scenario(FIXTURE) == SCENARIO


def test_ordinary_paths_are_not_gated():
    for p in ("server/engine/agent_activities.py", "integration/lint_tests.py",
              "server/engine/tests/test_fault_injection_registry.py", "a.py"):
        assert lfi.fixture_scenario(p) == ""


def test_malformed_inputs_are_total():
    # never raises, never recognises (spec §2; review-plan condition)
    bad = [None, b"server/x", 7, 3.5, [], {}, "", "/abs/path",
           "a/../" + FIXTURE, "../escape", "back\\slash", "dir/", "..",
           "a/..", True]
    for p in bad:
        assert lfi.fixture_scenario(p) == "", repr(p)


def test_fixture_leaks_reports_all_hits_in_order():
    leaks = lfi.fixture_leaks(["a.py", FIXTURE, "b.py", FIXTURE])
    assert leaks == [(FIXTURE, SCENARIO), (FIXTURE, SCENARIO)]


def test_fixture_leaks_non_list_is_empty():
    assert lfi.fixture_leaks(None) == []
    assert lfi.fixture_leaks(FIXTURE) == []  # a bare string is not a list
    assert lfi.fixture_leaks({"a": 1}) == []


# ---- B: note wording --------------------------------------------------------

def test_refusal_note_names_file_and_scenario():
    note = lfi.refusal_note([(FIXTURE, SCENARIO)])
    assert FIXTURE in note
    assert "fault-injection fixture from %s" % SCENARIO in note
    assert "re-settle" in note  # the reader-facing way out


def test_lint_note_says_leftover_fixture():
    note = lfi.lint_fixture_note(FIXTURE)
    assert "leftover fault-injection fixture from %s" % SCENARIO in note
    assert "not product code" in note


def test_lint_note_empty_for_ordinary_files():
    assert lfi.lint_fixture_note("server/engine/agent_activities.py") == ""
    assert lfi.lint_fixture_note(None) == ""


# ---- C: engine wiring -------------------------------------------------------

ENG = (POC / "agent_activities.py").read_text(encoding="utf-8")


def test_loader_degrades_named_not_silent():
    with tempfile.TemporaryDirectory() as td:
        mod, diag = aa._load_fixture_registry(Path(td))
        assert mod is None
        assert "lib_fault_injection" in diag
        assert "disarmed" in diag  # the refusal gap is stated, never silent


def test_loader_on_real_checkout_recognises():
    mod, diag = aa._load_fixture_registry(REPO)
    assert diag == ""
    assert mod is not None and hasattr(mod, "fixture_leaks")
    assert mod.fixture_leaks([FIXTURE]) == [(FIXTURE, SCENARIO)]


def test_main_settle_site_refuses_before_add():
    a = ENG.index("def _settle_worktree_lane")
    refuse = ENG.index("_fixture_leak_refuse(ticket_id, stage_id, leaks", a)
    add = ENG.index('"add", "-A", "--", "."], cwd)', a)
    assert a < refuse < add


def test_merge_core_site_refuses_before_add():
    a = ENG.index("def _settle_merge_core")
    refuse = ENG.index("fi.fixture_leaks(_fi_dirty)", a)
    add = ENG.index('"add", "-A", "--", "."], wt)', a)
    assert a < refuse < add


def test_both_add_sites_route_through_the_registry():
    assert ENG.count("_load_fixture_registry(") >= 3  # def + two call sites


def test_engine_has_no_hardcoded_fixture_copy():
    assert FIXTURE not in ENG
    assert "test_zz_t26100420_planted" not in ENG


# ---- D: scenario-side anchors (source-text; executable face is the L3 case) --

SC_SRC = (REPO / "integration" / "t261004-20" / "sc_test_anchor_brakes.py"
          ).read_text(encoding="utf-8")


def test_scenario_registry_self_check_present():
    assert "check_registry_self" in SC_SRC
    assert "lib_fault_injection.fixture_scenario" in SC_SRC


def test_scenario_preflight_leak_check_present():
    assert "preflight_leak_check" in SC_SRC
    assert "leaked" in SC_SRC
    assert "PLANTED.unlink" in SC_SRC.split("def preflight_leak_check")[1][:600]


def test_scenario_reclaim_wired_to_signals_and_atexit():
    guards = SC_SRC[SC_SRC.index("def install_reclaim_guards"):]
    assert "atexit.register" in guards
    assert "signal.SIGINT" in guards
    assert "signal.SIGTERM" in guards


# ---- E: exclusive same-tree planting lock (acceptance-rework faces) ---------

def test_planting_lock_is_exclusive_and_named_on_refusal():
    import pytest
    with tempfile.TemporaryDirectory() as td:
        fh = lfi.acquire_planting_lock(td)
        try:
            with pytest.raises(SystemExit) as ei:
                lfi.acquire_planting_lock(td)
            assert "refused" in str(ei.value)
            assert "t26100420_brakes.lock" in str(ei.value)
        finally:
            fh.close()
        # release = close; the next acquirer wins
        fh2 = lfi.acquire_planting_lock(td)
        fh2.close()


def test_planting_lock_lives_under_gitignored_evidence_area():
    pth = str(lfi.planting_lock_path("/repo"))
    assert pth == "/repo/.sandbar/t26100420_brakes.lock"


def test_scenario_uses_shared_lock_and_canonical_writer():
    assert "acquire_planting_lock" in SC_SRC
    assert "lib_registry.write_registry" in SC_SRC  # no more indent=1 drift
    assert "indent=1" not in SC_SRC


def test_l3_manual_plant_windows_ride_the_same_lock():
    src_a = (REPO / "integration" / "t261009-52" / "sc_fixture_leak_brakes.py"
             ).read_text(encoding="utf-8")
    src_b = (REPO / "integration" / "t261009-52" / "sc_fixture_refusal_named.py"
             ).read_text(encoding="utf-8")
    assert "acquire_planting_lock" in src_a
    assert "acquire_planting_lock" in src_b


def test_scenario_planted_path_matches_registry_key():
    assert ('"server" / "engine" / "tests" / "%s"' % Path(FIXTURE).name) in SC_SRC
