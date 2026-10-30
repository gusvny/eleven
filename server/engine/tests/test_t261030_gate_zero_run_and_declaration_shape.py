"""t261030-18 (KI-424 + KI-423): a narrowed gate round that ran zero cases is
never green, the receipt names WHICH decision produced the zero, and an
`l1_battery` declaration outside `server/engine/tests` is collected through a
named single-file route (or refused by name) instead of being appended to the
engine suite's pytest run.

Two measured holes, one property (the round can be green while resting on
nothing):

KI-424 - a narrowed round was recorded GREEN with `ran=0 / passed=0 / failed=0 /
env_fail=0` (t261030-06 round 4). The receipt's only evidence was the
pool-exclusion line and `ledger: written=0`, while the previous round really ran
the case. The four zeros cannot tell "the declared scope was judged and passed"
from "nothing was judged".

KI-423 - `verify.yaml`'s `test` check is `pytest server/engine/tests -q`, and the
battery mode APPENDED the declared node, so a battery under `integration/tests/`
was collected alongside the engine suite and died on the non-top-level conftest
(`1 ran / 0 passed / 1 failed`), while the same battery was green alone in that
lane and in a fresh clone.

Coverage map:
  A. THE THREE STATES + THE ZERO DECISION (`shared.quick_scope_state`, pure):
     full round / declared scope judged / nothing ran (pool exclusion, retired
     premise, roster skip, registry mismatch) / the declared target was not
     collected; a malformed count reads as zero, never as judged.
  B. THE VERDICT, THE RECEIPT AND THE FACE (KI-424): four zeros on a narrowed
     round are a NAMED red; the receipt carries `scope_state` +
     `zero_run_decision`; the blocked text names the decision and the ways out;
     the SAME four zeros on a full round keep the old caliber (this guard is
     scoped to the narrowing, documented deliberately); a judged narrowed round
     stays green; a real failing case still reds; a pool-excluded round that DID
     run cases still reports the skip and stays green (no loosening).
  C. THE TRANSLATION (check/battery mode): a green battery round carries the
     collection route onto the engine receipt, and a receipt with no row for the
     declared check reads as "the declared target was not collected" (not as a
     silent zero, not as a judged scope).
  D. THE COLLECTION ROUTE (KI-423), real files in a fixture lane: the appended
     shape reproduces the knot (this is the hole, documented), the single-file
     route collects and RUNS the declared battery while the check's own target
     does NOT run, a missing target is refused by name with nothing run, a
     failing battery still reds, and a target with no test in it is named apart
     from a real failure.
  E. THE PROJECT'S OWN DECLARATION: the real `verify.yaml` `test` command is
     rewritten to the single-file route (the declared `server/engine/tests`
     target is dropped, the options and the shell prefix survive).

No network, no real Temporal, no real git. The fixture-lane legs spawn real
pytest on tiny generated files (a few seconds, offline). Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261030_gate_zero_run_and_declaration_shape.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(POC / ".." / "tools"))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402
import verify_lane  # noqa: E402

QMW = dev_lane.QuickmanualLaneWorkflow
CHECK = "test"
CMD = "verify_lane lane=code only_check=test pytest_node=integration/tests/b.py"


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _wf():
    """A QuickmanualLaneWorkflow shell without a Temporal runtime (the verdict,
    receipt and face are pure derivations over the run result)."""
    wf = object.__new__(QMW)
    wf.ticket_id = "t261030-18-ut"
    wf.meta = {}
    wf.gate_runs = []
    wf.results = {}
    wf._detail_face_on = False
    return wf


def _ir(**kw):
    base = dict(ran=3, passed=3, failed=0, env_fail=0, details=[], error="")
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _scope(mode, names):
    return {"mode": mode, "names": list(names)}


def _state(quick_scope, ran, facts=None):
    return shared.quick_scope_state(quick_scope, ran, facts or {})


# ======================================================================
# A. The three states and the zero decision (pure truth table)
# ======================================================================

def test_full_round_is_not_narrowed_and_keeps_its_own_state():
    st = _state(None, 3)
    assert st["state"] == shared.QUICK_SCOPE_STATE_FULL
    assert st["zero_run"] is False and st["zero_decision"] == ""
    # the reserved full-gate token is a FULL round too (nothing was narrowed)
    assert _state(_scope("full", ["integ"]), 0)["state"] == \
        shared.QUICK_SCOPE_STATE_FULL


def test_declared_scope_judged_when_cases_ran():
    for mode in ("scenario", "check", "battery"):
        st = _state(_scope(mode, ["x"]), 2)
        assert st["state"] == shared.QUICK_SCOPE_STATE_JUDGED, mode
        assert st["zero_run"] is False and st["zero_decision"] == ""


def test_nothing_ran_names_the_pool_exclusion_decision():
    st = _state(_scope("scenario", ["sc-a"]), 0,
                {"excluded_pools": ["engine", "exclusive"], "excluded_count": 778,
                 "face_vacuous": True})
    assert st["state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert st["zero_run"] is True
    assert st["zero_decision"] == shared.QUICK_ZERO_POOL
    assert "engine" in st["line"] and "sc-a" in st["line"]


def test_nothing_ran_names_the_retired_premise_decision():
    st = _state(_scope("scenario", ["sc-retired"]), 0,
                {"retired_names": ["sc-retired"],
                 "retired_premise_excluded": [{"name": "sc-retired"}]})
    assert st["state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert st["zero_decision"] == shared.QUICK_ZERO_RETIRED
    assert "retired" in st["line"].lower()


def test_nothing_ran_names_the_roster_skip_decision():
    st = _state(_scope("scenario", ["sc-booked"]), 0,
                {"known_red_names": ["sc-booked"]})
    assert st["state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert st["zero_decision"] == shared.QUICK_ZERO_ROSTER
    assert "sc-booked" in st["line"]


def test_nothing_ran_falls_back_to_the_registry_mismatch_face():
    st = _state(_scope("scenario", ["sc-a", "sc-b"]), 0, {})
    assert st["state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert st["zero_decision"] == shared.QUICK_ZERO_REGISTRY
    assert "sc-a" in st["line"] and "sc-b" in st["line"]
    # a plan that named no scope at all is the declaration's own shape
    assert _state(_scope("check", []), 0)["zero_decision"] == shared.QUICK_ZERO_SHAPE


def test_target_not_collected_is_its_own_state_not_a_silent_zero():
    for mode in ("check", "battery"):
        st = _state(_scope(mode, ["integration/tests/b.py"]), 0,
                    {"collect_route": "pytest_node single-file route: ..."})
        assert st["state"] == shared.QUICK_SCOPE_STATE_NOT_COLLECTED, mode
        assert st["zero_run"] is True
        assert st["zero_decision"] == shared.QUICK_ZERO_SHAPE
        assert "NOT collected" in st["line"]


def test_malformed_counts_read_as_zero_never_as_judged():
    for bad in ("?", None, [], {}):
        st = _state(_scope("scenario", ["sc-a"]), bad)
        assert st["state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN, bad
        assert st["zero_run"] is True


def test_the_three_states_and_the_four_named_decisions_exist():
    assert shared.QUICK_SCOPE_STATES == (
        shared.QUICK_SCOPE_STATE_FULL, shared.QUICK_SCOPE_STATE_JUDGED,
        shared.QUICK_SCOPE_STATE_NOTHING_RAN,
        shared.QUICK_SCOPE_STATE_NOT_COLLECTED)
    # every decision the ticket names is a code (a roster skip is named too,
    # because it is the same family and must never be read as a product red)
    for code in ("pool_exclusion", "retired_premise", "registry_mismatch",
                 "declaration_shape", "roster_skip"):
        assert code in shared.QUICK_ZERO_DECISIONS, code


# ======================================================================
# B. The verdict, the receipt and the face (KI-424)
# ======================================================================

def _zero_run_round(**kw):
    """The measured shape: a narrowed round, four zeros, no receipt error."""
    kw.setdefault("excluded_pools", ["engine", "exclusive"])
    kw.setdefault("excluded_count", 778)
    kw.setdefault("details", [{"name": "__pool_exclude__", "cmd": "", "exit": 0,
                               "output_tail": "pool-exclude receipt: skipped pools=engine,exclusive"
                               " (778 fewer entries)"}])
    return _ir(ran=0, passed=0, failed=0, env_fail=0, **kw)


def test_zero_run_narrowed_round_is_a_named_red():
    wf = _wf()
    scop = _scope("scenario", ["sc-a"])
    ir = _zero_run_round()
    assert wf._quick_gate_verdict(ir, scop) == "red"
    # the counts alone would have said green (the hole this ticket closes)
    assert wf._quick_gate_verdict(ir) == "green", (
        "the pre-ticket caliber must be reproducible on a FULL round: this lock "
        "is scoped to the narrowing, never a loosening of the full-round caliber")
    rec = wf._quick_gate_receipt(ir, 0, scop)
    assert rec["status"] == "failed"
    assert rec["scope_state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert rec["zero_run_decision"] == shared.QUICK_ZERO_POOL
    assert "scope state: nothing_ran" in rec["summary"]
    assert "decision: pool_exclusion" in rec["summary"]


def test_receipt_distinguishes_the_three_states():
    wf = _wf()
    judged = wf._quick_gate_receipt(_ir(ran=2, passed=2), 0,
                                    _scope("scenario", ["sc-a"]))
    zero = wf._quick_gate_receipt(_zero_run_round(), 0, _scope("scenario", ["sc-a"]))
    missing = wf._quick_gate_receipt(
        _ir(ran=0, passed=0, failed=1, error="no row for the declared check",
            collect_route="pytest_node single-file route: ..."), 0,
        _scope("battery", ["integration/tests/b.py"]))
    assert judged["status"] == "ok"
    assert zero["status"] == "failed" and missing["status"] == "failed"
    assert judged["scope_state"] == shared.QUICK_SCOPE_STATE_JUDGED
    assert zero["scope_state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert missing["scope_state"] == shared.QUICK_SCOPE_STATE_NOT_COLLECTED
    # a signer can tell all three apart from the face alone
    assert len({judged["scope_state"], zero["scope_state"],
                missing["scope_state"]}) == 3
    assert missing["collect_route"].startswith("pytest_node single-file route")


def test_blocked_text_names_the_zero_decision_and_the_ways_out():
    wf = _wf()
    scop = _scope("scenario", ["sc-a"])
    text = wf._quick_gate_blocked_text(_zero_run_round(), "quick_gate_zero_run", 1,
                                       scop)
    assert "judged NOTHING" in text
    assert "nothing_ran" in text and "pool_exclusion" in text
    assert "never" in text and "green" in text
    assert "retry_qc" in text and "rework(to_stage=work)" in text
    assert len(text.splitlines()) <= QMW.FACE_MAX_LINES
    assert len(text) <= QMW.FACE_MAX_CHARS


def test_judged_narrowed_round_stays_green():
    wf = _wf()
    ir = _ir(ran=1, passed=1,
             details=[{"name": "sc-a", "cmd": "", "exit": 0, "output_tail": ""}],
             excluded_pools=["engine"], excluded_count=778,
             zero_run_face={"excluded_pools": ["engine"], "excluded_count": 778})
    assert wf._quick_gate_verdict(ir, _scope("scenario", ["sc-a"])) == "green"
    rec = wf._quick_gate_receipt(ir, 0, _scope("scenario", ["sc-a"]))
    assert rec["status"] == "ok"
    assert rec["scope_state"] == shared.QUICK_SCOPE_STATE_JUDGED
    assert rec["zero_run_decision"] == ""


def test_pool_excluded_round_that_ran_cases_still_reports_the_skip():
    # No loosening: a pool exclusion that leaves real cases is a scheduling
    # property, still named on the evidence, still green.
    wf = _wf()
    ir = _ir(ran=2, passed=2,
             details=[{"name": "sc-a", "cmd": "", "exit": 0, "output_tail": ""},
                      {"name": "__pool_exclude__", "cmd": "", "exit": 0,
                       "output_tail": "pool-exclude receipt: skipped pools=engine (778 fewer entries)"}],
             excluded_pools=["engine"], excluded_count=778)
    assert wf._quick_gate_verdict(ir, _scope("scenario", ["sc-a"])) == "green"
    assert any(d.get("name") == "__pool_exclude__" for d in ir.details)
    assert ir.excluded_count == 778


def test_real_failing_case_still_reds_inside_a_narrowed_round():
    wf = _wf()
    ir = _ir(ran=1, passed=0, failed=1,
             details=[{"name": "sc-a", "cmd": "", "exit": 1,
                       "output_tail": "AssertionError: boom"}])
    assert wf._quick_gate_verdict(ir, _scope("scenario", ["sc-a"])) == "red"
    rec = wf._quick_gate_receipt(ir, 0, _scope("scenario", ["sc-a"]))
    assert rec["status"] == "failed" and rec["violations"] == ["sc-a"]
    # and the zero-run reason code never applies to a round that ran a case
    assert rec["scope_state"] == shared.QUICK_SCOPE_STATE_JUDGED


def test_facts_read_the_retired_roster_and_route_faces():
    wf = _wf()
    ir = _ir(ran=0, passed=0, failed=0, env_fail=0,
             collect_route="pytest_node single-file route: x",
             known_red={"skipped": 1, "names": ["sc-roster"]},
             excluded_pools=["engine"], excluded_count=7,
             zero_run_face={
                 "face_vacuous": True,
                 "excluded_pools": ["engine"], "excluded_count": 7,
                 "retired_premise_excluded": [{"name": "sc-retired"}],
                 "retired_premise_pointed_skipped": ["sc-retired2"]})
    facts = wf._quick_scope_facts(ir)
    assert facts["excluded_pools"] == ["engine"]
    assert facts["excluded_count"] == 7
    assert facts["known_red_names"] == ["sc-roster"]
    assert facts["retired_names"] == ["sc-retired", "sc-retired2"]
    assert facts["face_vacuous"] is True
    assert facts["collect_route"].startswith("pytest_node single-file route")
    # the retired entry is never booked as a case: nothing ran, and the red is
    # the zero-run lock, not a fabricated product red
    assert wf._quick_gate_verdict(ir, _scope("scenario", ["sc-retired"])) == "red"
    st = _state(_scope("scenario", ["sc-retired"]), 0, facts)
    assert st["zero_decision"] == shared.QUICK_ZERO_RETIRED
    assert ir.passed == 0 and ir.failed == 0


# ======================================================================
# C. The translation into the engine receipt (check / battery mode)
# ======================================================================

def _wrapped(green, checks, receipt_extra=None, ok=True):
    body = {"lane": "code", "green": green,
            "red_count": sum(1 for c in checks if c.get("level") == "red"),
            "checks": checks}
    body.update(receipt_extra or {})
    return {"ok": ok, "result": body}


def _read(payload, returncode=0, check_id=CHECK):
    return aa._quick_check_receipt(payload, returncode, check_id, CMD,
                                   json.dumps(payload), "stderr tail")


def test_battery_round_carries_the_collection_route_onto_the_receipt():
    route = ("pytest_node single-file route: pytest collects ONLY the declared "
             "target 'integration/tests/b.py'")
    ir = _read(_wrapped(True, [{"check": CHECK, "level": "green", "items": [],
                                "id": CHECK, "note": route}],
                        {"pytest_node_route": route}))
    assert (ir.ran, ir.passed, ir.failed) == (1, 1, 0)
    assert ir.collect_route == route
    assert route in ir.details[0]["output_tail"], (
        "a GREEN battery row must still name how the target was collected")
    wf = _wf()
    scop = _scope("battery", ["integration/tests/b.py"])
    assert wf._quick_gate_verdict(ir, scop) == "green"
    rec = wf._quick_gate_receipt(ir, 0, scop)
    # the gate face names the route too (summary sentence + machine key)
    assert "collection: single-file route" in rec["summary"]
    assert rec["collect_route"] == route
    assert rec["scope_state"] == shared.QUICK_SCOPE_STATE_JUDGED


def test_battery_receipt_with_no_row_reads_as_target_not_collected():
    route = "pytest_node single-file route: x"
    payload = {"ok": True,
               "result": {"lane": "code", "green": True, "red_count": 0,
                          "checks": [], "pytest_node_route": route}}
    ir = _read(payload)
    assert (ir.ran, ir.failed) == (0, 1)
    assert ir.error, "no row for the declared check must stay a named red"
    assert ir.collect_route == route
    st = _state(_scope("battery", ["integration/tests/b.py"]), ir.ran,
                _wf()._quick_scope_facts(ir))
    assert st["state"] == shared.QUICK_SCOPE_STATE_NOT_COLLECTED


# ======================================================================
# D. The collection route (KI-423) - real files in a fixture lane
# ======================================================================

_BATTERY_OK = (
    "import pathlib\n"
    "_MARK = pathlib.Path(__file__).with_name('battery_ran.marker')\n"
    "def test_battery_ok():\n"
    "    _MARK.write_text('ran', encoding='utf-8')\n"
    "    assert True\n")
_BATTERY_RED = ("def test_battery_red():\n    assert False, 'boom'\n")
_BATTERY_EMPTY = ("# a file with no test in it: pytest collects nothing\n"
                  "VALUE = 1\n")


def _lane(tmp_path):
    """A fixture lane shaped like this project: a pytest-form `test` check whose
    command carries its OWN target (`server/engine/tests`), an integration/ tree
    with the `pytest_plugins` conftest that dies on a combined collection, and a
    battery that lives OUTSIDE the engine tests dir."""
    lane = tmp_path / "lane"
    eng = lane / "server" / "engine" / "tests"
    eng.mkdir(parents=True)
    (eng / "conftest.py").write_text("# engine tests conftest\n", encoding="utf-8")
    (eng / "test_engine_probe.py").write_text(
        "import pathlib\n"
        "_MARK = pathlib.Path(__file__).with_name('engine_ran.marker')\n"
        "def test_engine_probe():\n"
        "    _MARK.write_text('ran', encoding='utf-8')\n"
        "    assert True\n", encoding="utf-8")
    integ = lane / "integration" / "tests"
    integ.mkdir(parents=True)
    # the real repo's shape: a root-conftest-only plugin declaration
    (lane / "integration" / "conftest.py").write_text(
        'pytest_plugins = ["conftest_result_protocol"]\n', encoding="utf-8")
    (lane / "integration" / "conftest_result_protocol.py").write_text(
        "def pytest_configure(config):\n    return None\n", encoding="utf-8")
    cmd = '"%s" -m pytest server/engine/tests -q' % sys.executable
    (lane / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/\n"
        "    checks:\n"
        "      - id: %s\n        timeout: 300\n        cmd: %s\n"
        % (CHECK, cmd), encoding="utf-8")
    return lane, eng, integ, cmd


def _run(lane, node):
    return verify_lane.run({"lane": "code", "path": str(lane),
                            "only_check": CHECK, "pytest_node": node})


def test_appended_route_reproduces_the_knot(tmp_path):
    """THE HOLE (KI-423), reproduced: appending the declared node to the check's
    own command collects both roots and dies on the non-top-level conftest. This
    leg is the reason the route below exists."""
    lane, eng, integ, cmd = _lane(tmp_path)
    (integ / "test_battery.py").write_text(_BATTERY_OK, encoding="utf-8")
    p = subprocess.run(["/bin/sh", "-c", "%s integration/tests/test_battery.py" % cmd],
                       cwd=str(lane), capture_output=True, text=True)
    assert p.returncode != 0, ("the appended shape must be the red one; if pytest "
                               "ever accepts it, this route's premise changed")
    blob = (p.stdout or "") + (p.stderr or "")
    assert "pytest_plugins" in blob and "non-top-level conftest" in blob
    assert not (integ / "battery_ran.marker").exists(), "nothing ran"


def test_integration_battery_is_collected_and_run_by_the_single_file_route(tmp_path):
    lane, eng, integ, _cmd = _lane(tmp_path)
    (integ / "test_battery.py").write_text(_BATTERY_OK, encoding="utf-8")
    res = _run(lane, "integration/tests/test_battery.py")
    assert res["green"] is True, res
    # the declared battery really ran (marker on disk, read reader-side) ...
    assert (integ / "battery_ran.marker").is_file()
    # ... and the check's OWN target did not (the route collected the node alone)
    assert not (eng / "engine_ran.marker").exists()
    route = res.get("pytest_node_route") or ""
    assert "single-file route" in route
    assert "integration/tests/test_battery.py" in route
    assert "server/engine/tests" in route      # it names what it replaced
    # the row names the route too (a green row is not silent)
    assert any("single-file route" in str(c.get("note") or "")
               for c in res["checks"])


def test_missing_battery_target_is_refused_by_name_and_nothing_runs(tmp_path):
    lane, eng, integ, _cmd = _lane(tmp_path)
    res = _run(lane, "integration/tests/ghost_battery.py")
    assert res["green"] is False
    detail = json.dumps(res["checks"][-1]["items"])
    assert "does not exist" in detail and "nothing ran" in detail
    assert not (integ / "battery_ran.marker").exists()


def test_failing_battery_case_still_reds(tmp_path):
    lane, eng, integ, _cmd = _lane(tmp_path)
    (integ / "test_battery_red.py").write_text(_BATTERY_RED, encoding="utf-8")
    res = _run(lane, "integration/tests/test_battery_red.py")
    assert res["green"] is False
    detail = json.dumps(res["checks"][-1]["items"])
    assert "rc=1" in detail
    # a real failing case is NOT read as "not collected"
    assert "collected no test" not in detail


def test_target_with_no_test_in_it_is_named_apart_from_a_failure(tmp_path):
    lane, eng, integ, _cmd = _lane(tmp_path)
    (integ / "test_battery_empty.py").write_text(_BATTERY_EMPTY, encoding="utf-8")
    res = _run(lane, "integration/tests/test_battery_empty.py")
    assert res["green"] is False
    detail = json.dumps(res["checks"][-1]["items"])
    assert "collected no test" in detail, (
        "pytest exit 5 (nothing collected) must be named as 'not collected', "
        "never left to read as a failed case")


# ======================================================================
# E. The project's own declaration is collectable through the route
# ======================================================================

def test_real_project_command_is_rewritten_to_the_single_file_route():
    import yaml

    vy = yaml.safe_load((REPO / "verify.yaml").read_text(encoding="utf-8"))
    cmds = {str(c.get("id")): str(c.get("cmd") or "")
            for c in vy["lanes"]["code"]["checks"] if isinstance(c, dict)}
    declared = cmds["test"]
    node = "integration/tests/test_t261030_battery.py"
    new_cmd, dropped, route, err = verify_lane._single_file_route(declared, node)
    assert err == ""
    assert "server/engine/tests" in dropped
    tail = new_cmd.split("-m pytest", 1)[1]
    assert "server/engine/tests" not in tail, tail
    assert node in tail
    assert "-q" in tail
    # the shell prefix survives the rewrite (the interpreter chain is the check's
    # own declaration, not something this route may re-write)
    assert 'PYTHONPYCACHEPREFIX=out/pycache' in new_cmd
    assert new_cmd.startswith("PY=server/engine/.venv/bin/python;")
    assert "single-file route" in route


def test_single_file_route_keeps_option_values_redirections_and_comment():
    cmd = ("py -m pytest server/engine/tests -q -k 'not slow' --maxfail 1 "
           "2>/dev/null  # keep me")
    new_cmd, dropped, _route, err = verify_lane._single_file_route(
        cmd, "integration/tests/t.py")
    assert err == ""
    assert "server/engine/tests" in dropped
    assert "-k 'not slow'" in new_cmd and "--maxfail 1" in new_cmd
    assert "2>/dev/null" in new_cmd
    assert new_cmd.rstrip().endswith("# keep me")
    assert new_cmd.rstrip().split("#")[0].strip().endswith("integration/tests/t.py")
    # a command with no pytest launcher is refused, never guessed at
    _c, _d, _r, err2 = verify_lane._single_file_route("true", "x.py")
    assert err2 and "no pytest launcher" in err2


def test_gate_relays_the_runner_zero_face_from_a_zero_signal_round():
    """The runner's own attribution survives the gate: the zero-signal red carries
    it, so the engine names the decision instead of guessing one."""
    stdout = (
        "INTEG_RETIRED_ONLY every pointed entry sits under a retired premise\n"
        "SCENARIOS ran=0 pass=0 fail=0 env_fail=0 na=0 (0.0s)\n"
        "INTEG_SUMMARY %s\n" % json.dumps({
            "ran": 0, "pass": 0, "fail": 0, "not_checked": 0, "expected": 0,
            "reused": 0,
            "retired_premise_excluded": [{"name": "sc-retired", "premise": "docker"}],
            "retired_premise_count": 1,
            "only_scenarios": ["sc-retired"],
            "unrelated_key": "dropped"}))
    face = verify_lane._zero_run_face_from_summary(
        verify_lane._summary_from_stdout(stdout))
    assert face["retired_premise_count"] == 1
    assert face["only_scenarios"] == ["sc-retired"]
    assert "unrelated_key" not in face, "the relay carries only the named keys"
    # a malformed summary is never guessed at
    assert verify_lane._summary_from_stdout("INTEG_SUMMARY {oops") is None
    retired = [str(r["name"]) for r in face["retired_premise_excluded"]]
    st = _state(_scope("scenario", ["sc-retired"]), 0, {"retired_names": retired})
    assert st["zero_decision"] == shared.QUICK_ZERO_RETIRED


def test_both_receipt_legs_of_the_activity_relay_the_zero_face():
    # structural lock (the activity's two exits are one code path apart): a red leg
    # that dropped the face would leave the engine guessing the decision
    import inspect

    src = inspect.getsource(aa._run_scenarios)
    assert "out_err.zero_run_face" in src
    assert "out.zero_run_face" in src
