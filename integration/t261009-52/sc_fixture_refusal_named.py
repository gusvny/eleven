#!/usr/bin/env python3
"""t261009-52 L3: the committing path refuses a fixture by name; lint says
'leftover fixture', not product red.

KI-222 261010 incident: the leaked 54-byte fixture entered t261009-47's commit
00886185 (an add-everything settle) and stopped that ticket at merge_check with
`LINT done: 2 error / 1 warn` — both findings the fixture's, neither the
ticket's. Contract (grey-box; real lint subprocess + the shared registry
module + source-text wiring anchors, same face as t261004-34 B2):
  R1 lint keeps its teeth AND says what it is: with the fixture present as an
     unregistered leak, lint is still red (no exemption, no tooth filed) but
     names the fixture file and says 'fault-injection fixture from
     t261004-20-test-anchor-brakes'; after removal the naming face is gone and
     the clean tree never names the fixture (delta face).
  R2 integration/lib_fault_injection.py is the ONE recognition place: it names
     the owning scenario, an ordinary path is no leak anywhere (non-gating,
     spec §2), and malformed inputs (None, bytes, empty, .. traversal,
     absolute escape, non-str) are total — never an exception, never a
     recognition. refusal_note names file + reason.
  R3 both add-everything settle sites in server/engine/agent_activities.py
     (_settle_worktree_lane and the shared _settle_merge_core behind
     settle_conflict_resolution) consult the shared refusal BEFORE
     `git add -A`, with no hard-coded fixture copy in the engine — a site that
     stops routing through the registry turns red here instead of silently
     disarming the advertised refusal.

The leak lifecycle (interruption, pre-flight report) is
t261009-52-fixture-leak-brakes; registry truth tables are developer L1
(server/engine/tests/test_fault_injection_registry.py). Lint not running to
its summary line = ENV_FAIL exit 2.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "server" / "engine" / "tests" / "test_zz_t26100420_planted_anchor_case.py"
FIXTURE_REL = "server/engine/tests/test_zz_t26100420_planted_anchor_case.py"
SCENARIO = "t261004-20-test-anchor-brakes"
LIB = REPO / "integration" / "lib_fault_injection.py"
ENGINE = REPO / "server" / "engine" / "agent_activities.py"
NAME = "t261009-52-fixture-refusal-named"
LEAK_BODY = 'BAD = "/home/xingu/Documents/sandbar/inspection.yaml"\n'  # the exact KI-222 residue (the /home shape)

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish


def run_lint():
    r = subprocess.run(["python3", "integration/lint_tests.py"], cwd=str(REPO),
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def main():
    # ---- R2: the one recognition place (truth table, total on malformed input)
    if not LIB.exists():
        print("ENV_FAIL: shared registry module missing: %s" % LIB, flush=True)
        sys.exit(2)
    import importlib.util
    spec = importlib.util.spec_from_file_location("lib_fault_injection", LIB)
    lfi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lfi)
    ok(lfi.fixture_scenario(FIXTURE_REL) == SCENARIO,
       "R2: the registry names the owning scenario", FIXTURE_REL)
    for bad in (None, b"x", 7, "", "/abs/path", "a/../" + FIXTURE_REL,
                "back\\slash", [], {}):
        try:
            ok(lfi.fixture_scenario(bad) == "",
               "R2: malformed input is total (%r)" % (bad,),
               "recognised or raised on %r" % (bad,))
        except Exception as e:  # noqa: BLE001
            ok(False, "R2: malformed input is total (%r)" % (bad,), repr(e))
    ok(lfi.fixture_scenario("server/engine/agent_activities.py") == "",
       "R2: ordinary paths are not gated (non-gating, spec §2)", FIXTURE_REL)
    note = lfi.refusal_note([(FIXTURE_REL, SCENARIO)])
    ok(FIXTURE_REL in note and "fault-injection fixture from %s" % SCENARIO in note,
       "R2: refusal_note names file + reason", note[:200])

    # ---- R1: lint keeps its teeth AND says what it is
    # manual-plant window rides the same exclusive planting lock as the brake
    # scenario (acceptance rework: concurrent same-tree planting collides)
    lock_fh = lfi.acquire_planting_lock(REPO)
    FIXTURE.write_text(LEAK_BODY, encoding="utf-8")
    try:
        rc, out = run_lint()
        ok("LINT done" in out, "R1: lint runs to its summary line",
           "no 'LINT done' in output; head=%s" % out[:200])
        if "LINT done" not in out:
            print("ENV_FAIL: lint did not reach its summary line", flush=True)
            sys.exit(2)
        ok(rc != 0, "R1: lint stays red over the leak (teeth kept)",
           "lint exited %d over the fixture (expected red)" % rc)
        ok(FIXTURE.name in out, "R1: lint names the fixture file", out[-300:])
        ok("fault-injection fixture from %s" % SCENARIO in out,
           "R1: lint says 'fault-injection fixture from <scenario>'",
           "naming line missing from lint output")
    finally:
        FIXTURE.unlink(missing_ok=True)
        lock_fh.close()
    rc, out = run_lint()
    ok(FIXTURE.name not in out, "R1 delta: the clean tree never names the fixture",
       "fixture still named after removal: %s" % out[-200:])

    # ---- R3: both add-everything sites route through the registry, before add
    eng = ENGINE.read_text(encoding="utf-8")
    ok("_load_fixture_registry" in eng and "fixture_leaks" in eng,
       "R3: the engine consults the shared registry", ENGINE.name)
    a = eng.index("def _settle_worktree_lane")
    ok(a < eng.index("_fixture_leak_refuse(ticket_id, stage_id, leaks", a)
       < eng.index('"add", "-A", "--", "."], cwd)', a),
       "R3: main settle refuses BEFORE git add -A", ENGINE.name)
    c = eng.index("def _settle_merge_core")
    ok(a < c and c < eng.index("fi.fixture_leaks(_fi_dirty)", c)
       < eng.index('"add", "-A", "--", "."], wt)', c),
       "R3: conflict-settle core refuses BEFORE git add -A", ENGINE.name)
    ok("test_zz_t26100420_planted" not in eng,
       "R3: no hard-coded fixture copy in the engine (one declaration)",
       ENGINE.name)

    finish(NAME)


if __name__ == "__main__":
    main()
