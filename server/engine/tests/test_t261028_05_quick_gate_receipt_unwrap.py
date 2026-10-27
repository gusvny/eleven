"""t261028-15 (KI-388) — the quickmanual battery gate parsed the admin WRAPPER
and never its receipt, so a red counts-pair landed as GREEN.

Measured defect: `agent_activities._run_quick_named_check` ran
`python3 server/admin.py call verify_lane ...` and did `res = json.loads(stdout)`
then `res.get("green")` / `res.get("checks")`. admin.py prints
`{"ok": ..., "result": {...}}`, so both reads were always None: the round came
out "1 ran / 0 passed / 1 failed" with no named row, and
`dev_lane._quick_gate_verdict` (which only looked at error / named detail rows /
the env channel) called that green. The ticket's mandatory declared evidence was
never actually run by the gate.

Coverage map (the four faces the ticket names):
  A. UNWRAP — a WRAPPED green payload parses green (control: the old read took
     the wrapper for the receipt and produced failed=1); a WRAPPED red payload is
     red and its named check + detail ride into the receipt (violations and
     evidence).
  B. MALFORMED FACES — `ok: false`, a missing/empty `result`, and an unparseable
     stdout are each a NAMED red: an error string PLUS a detail row. Never a
     counts-only red, never a fallback to the full registry.
  C. ROUTING — the activity hands its stdout to that one reader (fake
     subprocess; no real spawn).
  D. COUNTS LOCK — the verdict may not disagree with the counts: the fabricated
     {ran:1, passed:0, failed:1, details:[]} receipt is RED, {ran:1, passed:1,
     failed:0} stays green, and every pre-existing red/green path is unchanged.

Teeth: face D's fabricated-receipt case must fail against the pre-ticket verdict
(it returned "green" for exactly that receipt, which is how four 261028 battery
tickets recorded a failed gate as green).

No network, no real subprocess, no real git. Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261028_05_quick_gate_receipt_unwrap.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402

QMW = dev_lane.QuickmanualLaneWorkflow
CHECK = "unit_battery"
CMD = "verify_lane lane=code only_check=unit_battery pytest_node=t/t_x.py"


# ----------------------------------------------------------------------
# fixtures / helpers
# ----------------------------------------------------------------------

def _wf():
    """A QuickmanualLaneWorkflow shell without a Temporal runtime (the receipt
    and verdict faces are pure derivations over the run result)."""
    wf = object.__new__(QMW)
    wf.ticket_id = "t261028-15-ut"
    wf.meta = {}
    wf.gate_runs = []
    wf.results = {}
    return wf


def _ir(**kw):
    base = dict(ran=3, passed=3, failed=0, env_fail=0, details=[], error="")
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _wrapped(green, checks, ok=True, extra=None):
    """The exact admin.py envelope shape: the receipt lives under `result`."""
    payload = {"ok": ok,
               "result": {"lane": "code", "green": green,
                          "red_count": sum(1 for c in checks
                                           if c.get("level") == "red"),
                          "checks": checks},
               "run_id": "deadbeef"}
    payload.update(extra or {})
    return payload


GREEN_CHECKS = [{"check": CHECK, "level": "green", "items": [],
                 "id": CHECK, "note": "the declared check passed"}]
RED_CHECKS = [{"check": CHECK, "level": "red",
               "items": [{"detail": "3 tests failed, 0 errors"}]}]


def _read(payload, returncode=0, stdout_text=None, check_id=CHECK):
    """Read one payload through the single-point reader under test."""
    return aa._quick_check_receipt(
        payload, returncode, check_id, CMD,
        stdout_text if stdout_text is not None else json.dumps(payload),
        "stderr tail")


# ----------------------------------------------------------------------
# A. UNWRAP — the wrapper is not the receipt
# ----------------------------------------------------------------------

def test_wrapped_green_payload_parses_green():
    """CONTROL: the same wrapped green payload the old inline read turned into
    failed=1 now parses green (ran=1/passed=1) with its green row carried."""
    ir = _read(_wrapped(True, GREEN_CHECKS))
    assert (ir.ran, ir.passed, ir.failed) == (1, 1, 0), (
        "a wrapped green payload must be a green round; the pre-ticket read "
        "returned 1 ran / 0 passed / 1 failed here (wrapper read as receipt)")
    assert ir.error == ""
    assert [d["name"] for d in ir.details] == [CHECK]
    assert [d["exit"] for d in ir.details] == [0]
    # and the workflow verdict agrees with the counts
    wf = _wf()
    assert wf._quick_gate_verdict(ir) == "green"
    rec = wf._quick_gate_receipt(ir, 0, {"mode": "battery", "names": [CHECK]})
    assert rec["status"] == "ok" and rec["violations"] == []
    assert "1 ran / 1 passed / 0 failed" in rec["summary"]


def test_a_result_level_note_rides_into_the_warnings():
    """The receipt's own note is carried instead of dropped (it is the widest
    human-readable face the code-lane receipt offers)."""
    payload = _wrapped(True, GREEN_CHECKS)
    payload["result"]["note"] = "write_set_whitelist: no base given, unverified"
    assert _read(payload).warnings == [
        "write_set_whitelist: no base given, unverified"]


def test_wrapped_red_payload_is_red_and_names_the_check_and_detail():
    """A red receipt is red, and its named check + detail text ride into the
    workflow receipt (violations for the machine face, evidence for the
    human-readable detail)."""
    ir = _read(_wrapped(False, RED_CHECKS))
    assert (ir.ran, ir.passed, ir.failed) == (1, 0, 1)
    # a receipt red is a PRODUCT red, not a gate error: the detail channel
    # names it and no error string shadows the reason code
    assert ir.error == ""
    assert [d["exit"] for d in ir.details] == [1]
    assert "3 tests failed" in ir.details[0]["output_tail"]
    wf = _wf()
    assert wf._quick_gate_verdict(ir) == "red"
    rec = wf._quick_gate_receipt(ir, 0, {"mode": "battery", "names": [CHECK]})
    assert rec["status"] == "failed"
    assert rec["violations"] == [CHECK], rec["violations"]
    assert "3 tests failed" in rec["evidence"]
    assert "1 ran / 0 passed / 1 failed" in rec["summary"]


def test_receipt_green_but_exit_nonzero_is_labelled_not_silently_green():
    """`shared.gate_verdict` requires ok + receipt green + exit 0. A payload whose
    elements disagree is red AND named (the red row says the elements disagree),
    so it is never a silent green and never a counts-only red."""
    ir = _read(_wrapped(True, GREEN_CHECKS), returncode=3)
    assert (ir.ran, ir.passed, ir.failed) == (1, 0, 1)
    assert ir.details and ir.details[-1]["exit"] == 1
    assert "names no red check" in ir.details[-1]["output_tail"]
    assert _wf()._quick_gate_verdict(ir) == "red"


# ----------------------------------------------------------------------
# B. MALFORMED FACES — named reds with an error string and a detail row
# ----------------------------------------------------------------------

def _assert_named_red(ir, *needles):
    assert ir.error, "a malformed payload must carry an error string"
    assert ir.details, "a malformed payload must carry a detail row"
    row = ir.details[0]
    assert row["exit"] == 1 and row["name"] == CHECK
    low = ir.error.lower()
    for n in needles:
        assert n in low, "the error must name the actual failure: %r" % ir.error
    # never a fallback to the full registry: the round is exactly one named check
    assert ir.only_names == [CHECK]
    assert (ir.ran, ir.failed) == (0, 1)
    assert _wf()._quick_gate_verdict(ir) == "red"


def test_ok_false_is_a_named_red_with_the_tool_error():
    ir = _read({"ok": False, "error": "verify.yaml not found at the lane root"},
               returncode=1)
    _assert_named_red(ir, "ok=false", "verify.yaml not found")
    assert "unit_battery" in ir.error


def test_missing_result_is_a_named_red():
    _assert_named_red(_read({"ok": True}), "no result")


def test_empty_result_is_a_named_red():
    _assert_named_red(_read({"ok": True, "result": {}}), "no result")


def test_unparseable_stdout_is_a_named_red():
    payload = shared.gate_receipt_parse("Traceback (most recent call last):")
    assert payload == {}
    ir = _read(payload, returncode=2, stdout_text="Traceback ... boom")
    _assert_named_red(ir, "no parseable json receipt")
    assert "boom" in ir.error or "Traceback" in ir.details[0]["output_tail"]


def test_leading_diagnostic_line_does_not_hide_the_receipt():
    """The single point tolerates a diagnostic line before the envelope (the
    t260927-16 incident shape); the gate payload is still read."""
    text = ('{"note": "warming the cache"}\n'
            + json.dumps(_wrapped(True, GREEN_CHECKS)))
    ir = _read(shared.gate_receipt_parse(text), returncode=0, stdout_text=text)
    assert (ir.ran, ir.passed, ir.failed) == (1, 1, 0)


# ----------------------------------------------------------------------
# C. ROUTING — the activity reads its stdout through that one reader
# ----------------------------------------------------------------------

class _FakeProc:
    """A stand-in for asyncio's subprocess: communicate() only."""

    def __init__(self, stdout, stderr="", returncode=0):
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self.returncode = returncode
        self.pid = 999999          # bookkeeping only; never a live process

    async def communicate(self):
        return self._stdout, self._stderr


def _drive_activity(monkeypatch, tmp_path, proc):
    seen = {}

    async def _fake_spawn(*a, **kw):
        seen["argv"] = a
        return proc

    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _fake_spawn)
    sc = {"mode": "battery", "check": CHECK, "pytest_node": "t/t_x.py"}
    ir = asyncio.run(aa._run_quick_named_check(tmp_path, SimpleNamespace(), sc))
    return ir, seen


def test_activity_routes_stdout_through_the_single_point(monkeypatch, tmp_path):
    proc = _FakeProc(json.dumps(_wrapped(True, GREEN_CHECKS)))
    ir, seen = _drive_activity(monkeypatch, tmp_path, proc)
    assert (ir.ran, ir.passed, ir.failed) == (1, 1, 0), (
        "the activity must read the envelope, not treat it as the receipt")
    # the owned-spawn registry is clean after the call (no leaked spawn)
    assert 999999 not in [e["pid"] for e in aa.owned_spawn_snapshot()]
    # what it ran is unchanged: exactly the declared check + its pytest target
    argv = seen["argv"]
    assert argv[0] == "python3" and argv[3] == "verify_lane"
    sent = json.loads(argv[4])
    assert sent == {"lane": "code", "path": str(tmp_path),
                    "only_check": CHECK, "pytest_node": "t/t_x.py"}


def test_activity_turns_an_unparseable_run_into_a_named_red(monkeypatch,
                                                           tmp_path):
    proc = _FakeProc("boom\n", stderr="admin.py crashed", returncode=2)
    ir, _seen = _drive_activity(monkeypatch, tmp_path, proc)
    assert ir.error and ir.details and ir.details[0]["exit"] == 1
    assert "admin.py crashed" in ir.details[0]["output_tail"]
    assert _wf()._quick_gate_verdict(ir) == "red"


# ----------------------------------------------------------------------
# D. COUNTS LOCK — the verdict may not disagree with the counts
# ----------------------------------------------------------------------

def test_fabricated_counts_only_red_is_red():
    """THE TEETH: {ran:1, passed:0, failed:1, details:[]} — the exact shape every
    battery round of 261028 recorded — must be red. The pre-ticket verdict
    returned "green" for it (no error, no red rows, no env channel)."""
    wf = _wf()
    ir = _ir(ran=1, passed=0, failed=1, details=[])
    assert wf._tests_red_names(ir) == []
    assert wf._quick_gate_verdict(ir) == "red"
    assert wf._quick_gate_receipt(ir, 0, None)["status"] == "failed"


def test_counts_green_round_stays_green():
    wf = _wf()
    assert wf._quick_gate_verdict(_ir(ran=1, passed=1, failed=0)) == "green"


def test_ran_without_a_single_pass_is_red():
    """A round that ran work and passed nothing can never be green — including
    the all-environment-red shape: named env reds exempt a round that PASSED
    something, never a round that proved nothing."""
    wf = _wf()
    assert wf._quick_gate_verdict(_ir(ran=2, passed=0, failed=0)) == "red"
    assert wf._quick_gate_verdict(
        _ir(ran=2, passed=0, failed=0, env_fail=2,
            env_red=["sc_env_a", "sc_env_b"])) == "red"


def test_zero_run_round_is_not_flipped_by_the_counts_lock():
    """The pre-existing empty-round path stays: nothing ran, nothing failed."""
    wf = _wf()
    assert wf._quick_gate_verdict(_ir(ran=0, passed=0, failed=0)) == "green"


def test_unreadable_counters_are_red_not_green():
    wf = _wf()
    assert wf._quick_gate_verdict(_ir(ran="?", passed="?", failed="?")) == "red"


def test_existing_red_and_green_paths_are_kept():
    """The verdict only ADDS the counts lock: every pre-existing path is intact."""
    wf = _wf()
    assert wf._quick_gate_verdict(_ir(error="verify_lane produced no output")) \
        == "red"
    red_rows = [{"name": "sc_a", "cmd": "", "exit": 1, "output_tail": ""}]
    assert wf._quick_gate_verdict(
        _ir(ran=1, passed=0, failed=1, details=red_rows)) == "red"
    assert wf._quick_gate_verdict(
        _ir(ran=1, passed=1, failed=0, blockers=["sc_blocked"])) == "red"
    assert wf._quick_gate_verdict(_ir(ran=1, passed=1, env_fail=2)) == "red"
    assert wf._quick_gate_verdict(
        _ir(ran=2, passed=1, failed=0, env_fail=1, env_red=["sc_env"])) == "green"


def test_counts_only_red_gets_its_own_reason_code():
    """A counts-only red must not be classified as an environment red it never
    was (error precision: say which check failed)."""
    import inspect
    src = inspect.getsource(QMW._run_quickmanual)
    assert src.index('reason_code = "quick_gate_error"') \
        < src.index('reason_code = "quick_gate_counts_red"') \
        < src.index('reason_code = "quick_gate_env_unnamed"')


# ======================================================================
# E. KI-395 — battery mode must run through a REAL declared check
# ======================================================================
# Second layer of the same incident: `shared.quick_scope_plan` leaves `check`
# empty for `l1_battery` (it only sets `pytest_node`), and the round sent that
# empty string as `only_check`. verify_lane refuses `pytest_node` without
# `only_check`, so the whole call was refused ("pytest_node requires only_check
# ... nothing ran") and the declared target never ran. The faces below pin the
# repair end to end.

BATTERY_PYTEST_CMD = "%s -m pytest" % sys.executable


def _write_lane_fixture(root, checks, batteries):
    """A minimal lane: verify.yaml code-lane checks, a registry stub and the
    battery files. `checks` = [(id, cmd)]; `batteries` = {relpath: source}."""
    for rel, src in batteries.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    (root / "integration").mkdir(parents=True, exist_ok=True)
    (root / "integration" / "run_scenarios.py").write_text(
        '"""Registry stub: the resolver only reads SCENARIOS/own_set_entries."""\n'
        "SCENARIOS = []\n\n\n"
        "def own_set_entries(ticket_id):\n"
        "    return []\n", encoding="utf-8")
    decl = ["schema: v1", "lanes:", "  code:", "    write_allow:",
            "      - server/", "    checks:"]
    for cid, cmd in checks:
        decl += ["      - id: %s" % cid,
                 "        cmd: %s" % cmd.replace(":", "\\:")]
    (root / "verify.yaml").write_text("\n".join(decl) + "\n", encoding="utf-8")


def _resolve(root, kind, names):
    return asyncio.run(aa._quick_scope_resolve_body(
        shared.QuickScopeResolveArgs(ticket_id="t261028-15-ut",
                                     worktree=str(root), kind=kind,
                                     names=list(names))))


def _envelope(res):
    """The admin.py shape for a verify_lane result (ok=true: the tool call ran)."""
    return {"ok": True, "result": res, "run_id": "fixture"}


def test_battery_mode_resolves_the_declared_check_end_to_end(tmp_path):
    """The ONE end-to-end battery case: the plan names the real declared check,
    the call carries only_check + pytest_node, a green target reads green and a
    genuinely red target reads red BY NAME (never counts-only)."""
    import importlib.util
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import verify_lane  # noqa: E402

    _write_lane_fixture(
        tmp_path,
        [("lint", "true"), ("test", BATTERY_PYTEST_CMD)],
        {"battery_ok.py": "def test_ok():\n    assert True\n",
         "battery_red.py": "def test_red():\n    assert False, 'battery red'\n"})

    wf = _wf()

    def _round(node):
        # 1. the plan resolves the declared check that owns the pytest target
        plan = _resolve(tmp_path, "l1_battery", [node])
        assert plan.ok and plan.error == "", plan.error
        assert plan.mode == "battery"
        assert plan.check == "test", (
            "battery mode must name the declared pytest-form check, got %r"
            % plan.check)
        assert plan.pytest_node == node
        # 2. the call the gate makes carries BOTH params (this is the call that
        #    used to send only_check="" and get refused: nothing ran)
        res = verify_lane.run({"lane": "code", "path": str(tmp_path),
                               "only_check": plan.check,
                               "pytest_node": plan.pytest_node})
        return plan, res

    # ---- green target ----
    plan, res = _round("battery_ok.py")
    assert res["green"] is True, res["checks"]
    ir = _read(_envelope(res), returncode=0, stdout_text=json.dumps(res),
               check_id=plan.check)
    assert (ir.ran, ir.passed, ir.failed) == (1, 1, 0), (
        "the declared battery ran and passed; got %s" % (ir,))
    assert ir.error == ""
    assert wf._quick_gate_verdict(ir) == "green"
    rec = wf._quick_gate_receipt(ir, 0, {"mode": "battery",
                                         "names": [plan.pytest_node]})
    assert rec["status"] == "ok" and "1 ran / 1 passed / 0 failed" in rec["summary"]

    # ---- genuinely red target: red BY NAME, not counts-only ----
    plan, res = _round("battery_red.py")
    assert res["green"] is False
    ir = _read(_envelope(res), returncode=0, stdout_text=json.dumps(res),
               check_id=plan.check)
    assert (ir.ran, ir.passed, ir.failed) == (1, 0, 1)
    assert ir.error == "", "a receipt red is a product red, not a gate error"
    assert wf._tests_red_names(ir) == ["test"], (
        "the red target must be NAMED after the declared check, got %s"
        % wf._tests_red_names(ir))
    red_rows = [d for d in ir.details if d["exit"] == 1]
    assert [d["name"] for d in red_rows] == ["test"], ir.details
    assert "'battery red'" in red_rows[0]["output_tail"], (
        "the pytest failure text must ride the named row: %r"
        % red_rows[0]["output_tail"][:200])
    rec = wf._quick_gate_receipt(ir, 0, {"mode": "battery",
                                         "names": [plan.pytest_node]})
    assert rec["status"] == "failed" and rec["violations"] == ["test"]
    # the argv the activity sends is exactly that call
    proc = _FakeProc(json.dumps(_envelope(res)))
    ir2, seen = _drive_activity_with(proc, tmp_path, plan)
    assert json.loads(seen["argv"][4]) == {
        "lane": "code", "path": str(tmp_path), "only_check": "test",
        "pytest_node": "battery_red.py"}, seen["argv"][4]


def _drive_activity_with(proc, wt, plan):
    """Drive the activity with a fixed scope and a fake process (no real spawn)."""
    seen = {}

    async def _fake_spawn(*a, **kw):
        seen["argv"] = a
        return proc

    saved = aa.asyncio.create_subprocess_exec
    aa.asyncio.create_subprocess_exec = _fake_spawn
    try:
        sc = {"mode": plan.mode, "check": plan.check,
              "pytest_node": plan.pytest_node}
        ir = asyncio.run(aa._run_quick_named_check(wt, SimpleNamespace(), sc))
    finally:
        aa.asyncio.create_subprocess_exec = saved
    return ir, seen


def test_battery_mode_without_a_pytest_form_check_is_a_named_refusal(tmp_path):
    """No declared check can run a pytest target: the claim is refused BY NAME
    (quick_scope_unresolved) — never an empty only_check call."""
    _write_lane_fixture(tmp_path, [("lint", "true")],
                        {"battery_ok.py": "def test_ok():\n    assert True\n"})
    plan = _resolve(tmp_path, "l1_battery", ["battery_ok.py"])
    assert plan.ok is False
    assert plan.error.startswith("quick_scope_unresolved"), plan.error
    assert "runs pytest" in plan.error and "lint" in plan.error
    assert plan.check == "" and plan.mode == ""
    # and the activity refuses such a scope WITHOUT spawning anything
    called = {"spawned": False}

    async def _boom(*a, **kw):
        called["spawned"] = True
        raise AssertionError("a no-check-id scope must never spawn")

    saved = aa.asyncio.create_subprocess_exec
    aa.asyncio.create_subprocess_exec = _boom
    try:
        ir = asyncio.run(aa._run_quick_named_check(
            tmp_path, SimpleNamespace(),
            {"mode": "battery", "check": "", "pytest_node": "battery_ok.py"}))
    finally:
        aa.asyncio.create_subprocess_exec = saved
    assert called["spawned"] is False
    assert (ir.ran, ir.passed, ir.failed) == (0, 0, 1), (
        "nothing ran, so ran must be 0 (the hardcoded ran=1 was the lie)")
    assert "no check id" in ir.error
    assert ir.details and ir.details[0]["name"] == "quick_scope_no_check_id"
    assert _wf()._quick_gate_verdict(ir) == "red"


def test_battery_mode_with_two_pytest_checks_is_an_ambiguous_refusal(tmp_path):
    """Two declared checks run pytest: the owner is ambiguous, so the claim is
    refused BY NAME naming both candidates — never a guessed pick."""
    _write_lane_fixture(
        tmp_path,
        [("test_a", BATTERY_PYTEST_CMD), ("test_b", BATTERY_PYTEST_CMD)],
        {"battery_ok.py": "def test_ok():\n    assert True\n"})
    plan = _resolve(tmp_path, "l1_battery", ["battery_ok.py"])
    assert plan.ok is False
    assert plan.error.startswith("quick_scope_unresolved"), plan.error
    assert "ambiguous" in plan.error
    assert "test_a" in plan.error and "test_b" in plan.error
    assert plan.check == ""


def test_check_mode_still_resolves_the_declared_id(tmp_path):
    """The plan face for `check` declarations is untouched by the battery fix."""
    _write_lane_fixture(tmp_path, [("lint", "true")], {})
    plan = _resolve(tmp_path, "check", ["lint"])
    assert plan.ok is True and plan.mode == "check" and plan.check == "lint"
    assert plan.pytest_node == ""


def test_receipt_without_the_declared_check_row_is_not_a_run():
    """The KI-395 refusal shape (a receipt that ran nothing for the declared
    check) is read as ran=0 with the receipt's own words — never as a run."""
    refusal = _wrapped(False, [
        {"check": "pytest_node", "level": "red",
         "items": [{"detail": "pytest_node requires only_check (one declaration, "
                              "one named check) — nothing ran"}]}])
    ir = _read(refusal, returncode=0, stdout_text=json.dumps(refusal),
               check_id="test")
    assert (ir.ran, ir.passed, ir.failed) == (0, 0, 1)
    assert "no row for the declared check" in ir.error
    assert "nothing ran" in ir.error, "the receipt's own words must be carried"
    assert ir.details and ir.details[0]["exit"] == 1
    assert _wf()._quick_gate_verdict(ir) == "red"


def test_green_receipt_without_the_declared_check_row_proves_nothing():
    """A green receipt that never mentions the declared check is a named red:
    a round that cannot name its own run is not evidence."""
    ir = _read(_wrapped(True, [{"check": "write_set_whitelist", "level": "green",
                                "items": []}]))
    assert (ir.ran, ir.passed, ir.failed) == (0, 0, 1)
    assert "nothing ran for it" in ir.error
    assert _wf()._quick_gate_verdict(ir) == "red"


def test_reader_refuses_a_round_with_no_check_id_at_all():
    """The reader is honest on its own: a payload read without a check id can
    never claim a run (ran=0, named), even when the receipt looks green."""
    ir = _read(_wrapped(True, GREEN_CHECKS), stdout_text="{}")
    assert ir.ran == 1  # the check id was given here: one executed target
    ir2 = aa._quick_check_receipt(_wrapped(True, GREEN_CHECKS), 0, "", CMD,
                                 "{}", "")
    assert (ir2.ran, ir2.failed) == (0, 1)
    assert "declared no check id" in ir2.error
