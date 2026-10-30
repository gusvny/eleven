#!/usr/bin/env python3
"""t261031-04 (KI-435) L1: a narrowed gate round's scope is STABLE inside one
attempt, the zero decision names the pool AND the decider, and a scenario the
ticket declared inside its own write set is never peeled out of its round.

The measured defect (t261031-01, quickmanual, declaration
`scenario=t261011-15-dismiss-prompt-visible-long-list`, registry pool
`browser-free`):

  round 1 of the attempt: ran=1 passed=1, the case took 26.1 s, and the report
      said `reused=0` with `reuse_zero_reason = "no green row under the same
      commit+env_fp+width"`;
  round 2 of the SAME attempt: ran=0 in 1.9 s, and the report said
      `reused=1`, `reused_names=[that case]` — the width had flipped 4 -> 3, so
      the ledger row written at width 3 (by the session's own earlier local run)
      now matched the reuse key;
  round 4 (after retry_qc): identical, because the commit never moved.

So what differed between the two rounds was NOT the declaration (immutable) and
NOT a pool exclusion (the gate only ever excludes engine/exclusive, and this
case lives in browser-free): the round's concurrency width moved, and the
result-ledger reuse peel (t260930-01) took the declared case out of the round.
The receipt called that `pool_exclusion`, because the pool facts it read said
"engine,exclusive were excluded" and nothing on the receipt said who really
decided. One word was not a diagnosis.

Coverage map (every case below is one requirement of the ticket):
  A. THE KEEP FACE (pure): `shared.path_inside_write_set` / `quick_scope_protect`
     / `quick_scope_keep_names` — a declared name inside the write set is
     protected, one outside it is not, a name with no readable registry path is
     not (and nothing raises on malformed input).
  B. THE NAMED DECISION (pure): the MEASURED receipt shape decides
     `ledger_reuse` (not `pool_exclusion`), names the case and the reuse key in
     its detail, and a pool decision names the pools, the decider and whether
     that pool actually covered the declared case; a keep-face peel, a fast-set
     round and an explicit caller narrowing each name themselves; the pre-ticket
     faces (retired / roster / judged / registry mismatch) keep their behavior.
  C. TWO ROUNDS OF ONE ATTEMPT (the shell): the same scope produces the same
     `only_names` and the same keep face in both rounds; the scope pin names a
     difference instead of hiding it; the MUTATION — a round 2 that strips the
     declared case — is red BY NAME (the case is a named violation and the
     blocked face says "Declared but NOT judged"), never a silent zero-run, and
     the same holds for the widened shape (the round ran OTHER cases).
  D. THE REAL RUNNER (fixture registry, real pool exclusion, real own face,
     seconds): the declared case in an excluded pool RUNS with the keep face and
     RUNS AGAIN on the second round (stable scope); with the keep face stripped
     (the mutation) it does not run, and the round that ran the widened face is
     red by name at the gate.
  E. THE RELAY (source locks): the runner's summary carries the reuse/drop/keep
     faces, verify_lane relays them, the resolver derives the keep face from the
     write set, and the runner's own exemption is wired into the reuse peel.

Offline, no Temporal, no docker, no browser, never touches 3099/7233. The
fixture rounds spawn only tiny `python3` stub scripts (seconds).
Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261031_narrowed_scope_stability.py -q
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
REPO = ENGINE.parents[1]
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, os.path.join(str(REPO), "integration"))

import dev_lane  # noqa: E402
import shared  # noqa: E402

#: The measured incident's declared scenario and its registry pool. Kept verbatim
#: on purpose: every face below is judged against the report of that round.
CASE = "t261011-15-dismiss-prompt-visible-long-list"
CASE_POOL = "browser-free"
GATE_POOLS = ["engine", "exclusive"]

#: The lane's write set for that ticket (integration/t261011-15/ + integration/).
WRITE_SET = ["integration/t261011-15/", "integration/"]


def _rs():
    """The lane runner, imported in-process (module import builds the registry,
    runs nothing) — the same stance the t260922-12 / t261025-02 batteries take."""
    spec = importlib.util.spec_from_file_location(
        "rs_t261031_04", REPO / "integration" / "run_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wf():
    """The quickmanual shell without a Temporal runtime (the round, verdict,
    receipt and face are pure derivations over the run result)."""
    wf = object.__new__(dev_lane.QuickmanualLaneWorkflow)
    wf.ticket_id = "t261031-04-ut"
    wf.meta = {"worktree": "/tmp/t261031-04", "stage": "run_integration_tests",
               "workspace": {}, "base_ref": "deadbeef"}
    wf.gate_runs = []
    wf.results = {}
    wf._detail_face_on = False
    wf._gens = {}
    return wf


def _ir(**kw):
    base = dict(ran=1, passed=1, failed=0, env_fail=0, error="",
                details=[{"name": CASE, "cmd": "", "exit": 0,
                          "output_tail": ""}])
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _scope(**kw):
    sc = {"mode": "scenario", "names": [CASE], "only_names": [CASE],
          "own_names": [CASE], "name_pools": {CASE: CASE_POOL}}
    sc.update(kw)
    return sc


#: The measured round-2 receipt, verbatim in its decision-relevant faces: a zero
#: round, the gate's own pool exclusion in force, and the reuse peel that really
#: took the case (names + key) — all read off the incident's report JSON.
INCIDENT_ZERO = dict(
    ran=0, passed=0, failed=0, env_fail=0, error="",
    details=[{"name": "__pool_exclude__", "cmd": "", "exit": 0,
              "output_tail": "pools=engine,exclusive (91 fewer entries)"}],
    excluded_pools=list(GATE_POOLS), excluded_count=91,
    zero_run_face={
        "reuse_names": [CASE],
        "reuse_judged_by": {"commit": "d5d1c141e8fa070f46119c0d570744158aa7accb",
                            "env_fp": "e0422266cbe348328c6c60b8c37eb522"
                                      "8f60d2be2c678d2bf64b6c347dffbd4b",
                            "conc_width": 3,
                            "ledger": "/tmp/scenario-results.jsonl"},
        "excluded_pools": list(GATE_POOLS), "excluded_count": 91,
        "only_scenarios": [CASE]},
)


# ======================================================================
# A. The keep face: declared AND inside the write set
# ======================================================================

def test_path_inside_write_set_matches_the_lane_prefix_rule():
    assert shared.path_inside_write_set("integration/t261011-15/x.py",
                                        ["integration/t261011-15/"])
    assert shared.path_inside_write_set("integration/t261011-15/x.py",
                                        ["integration"])
    assert shared.path_inside_write_set("integration/x.py", ["integration/"])
    assert not shared.path_inside_write_set("integration/t1/x.py",
                                            ["integration/t261011-15/"])
    assert not shared.path_inside_write_set("docs/x.md", ["integration/"])
    # malformed entries never match and nothing raises
    for bad in (None, [], [None], ["   "], [3]):
        assert shared.path_inside_write_set("integration/x.py", bad) is False
    assert shared.path_inside_write_set("", ["integration/"]) is False


def test_declared_name_inside_the_write_set_is_protected():
    # the registry carries a COMMAND LINE; the touched file is a token of it.
    paths = {CASE: "node integration/t261011-15/sc_x.mjs",
             "other-case": "node integration/t261999-01/sc_y.mjs"}
    # a narrow write set protects exactly the declared case that lives in it
    assert shared.quick_scope_protect([CASE, "other-case"], paths,
                                      ["integration/t261011-15/"]) == [CASE]
    # the wide form (the lane's own `integration/` entry) covers both - the
    # protection follows the declared write set, it is never narrowed by guess
    assert shared.quick_scope_protect([CASE, "other-case"], paths,
                                      WRITE_SET) == [CASE, "other-case"]
    # nothing declared -> nothing protected
    assert shared.quick_scope_protect([], paths, WRITE_SET) == []
    # no write set -> nothing protected (the pre-ticket behavior, byte-identical)
    assert shared.quick_scope_protect([CASE], paths, []) == []


def test_protection_never_guesses_from_a_missing_path():
    # a name with no readable registry command path is NOT protected: the keep
    # face is derived, never assumed (and the zero decision then names the gap).
    assert shared.quick_scope_protect([CASE], {}, WRITE_SET) == []
    assert shared.quick_scope_protect([CASE], {CASE: ""}, WRITE_SET) == []
    # malformed inputs are dropped item-wise, never raised (external input)
    assert shared.quick_scope_protect([None, 3, "  ", CASE],
                                      {CASE: "integration/x.py"},
                                      WRITE_SET) == [CASE]
    assert shared.quick_scope_protect([CASE], "not-a-dict", WRITE_SET) == []


def test_keep_face_is_the_own_set_union_the_protected_set():
    keep = shared.quick_scope_keep_names(["own-a"], [CASE, "own-a"])
    assert keep == ["own-a", CASE]          # order stable, de-duplicated
    assert shared.quick_scope_keep_names([], []) == []
    assert shared.quick_scope_keep_names(None, [CASE]) == [CASE]
    assert shared.quick_scope_keep_names(["  "], [None, "  "]) == []


# ======================================================================
# B. The zero decision names the pool AND who decided
# ======================================================================

def test_measured_incident_zero_names_the_reuse_not_the_pool():
    wf = _wf()
    ir = _ir(**INCIDENT_ZERO)
    facts = wf._quick_scope_facts(ir, _scope())
    st = shared.quick_scope_state(_scope(), 0, facts)
    assert st["state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert st["zero_run"] is True
    # the one word was `pool_exclusion`; the truth is the ledger reuse peel:
    assert st["zero_decision"] == shared.QUICK_ZERO_REUSE
    assert st["decided_by"] == "result_ledger_reuse"
    # the diagnosis names the case, the key it was judged on, and the keep face
    assert CASE in st["detail"] and "conc_width=3" in st["detail"]
    assert "d5d1c141" in st["detail"]
    # the decision is NOT the pool one (the pools are reported by the receipt's
    # pool face, but this line must not blame them for the zero)
    assert st["zero_decision"] != shared.QUICK_ZERO_POOL
    assert "pool-exclusion decision was in force" not in st["line"]
    assert "nothing was verified" in st["line"]


def test_pool_decision_names_the_pools_and_the_decider():
    wf = _wf()
    ir = _ir(ran=0, passed=0, details=[], excluded_pools=list(GATE_POOLS),
             excluded_count=91,
             zero_run_face={"excluded_pools": list(GATE_POOLS),
                            "excluded_count": 91,
                            "dropped_by_pool": {"engine-case": "engine"}})
    # the declared case lives in an excluded pool -> the decision claims it and
    # says which pool and who declared the exclusion
    sc = _scope(names=["engine-case"], only_names=["engine-case"],
                own_names=[], name_pools={"engine-case": "engine"})
    st = shared.quick_scope_state(sc, 0, wf._quick_scope_facts(ir, sc))
    assert st["zero_decision"] == shared.QUICK_ZERO_POOL
    assert st["decided_by"] == "lane_pool_declaration"
    assert "engine" in st["line"] and "verify.yaml" in st["detail"]
    assert "engine-case" in st["line"]


def test_pool_decision_says_so_when_it_never_covered_the_declared_case():
    wf = _wf()
    # no reuse fact this time (an old runner), only the pool facts: the decision
    # must NOT claim the pool dropped a case whose pool was never excluded.
    ir = _ir(ran=0, passed=0, details=[], excluded_pools=list(GATE_POOLS),
             excluded_count=91,
             zero_run_face={"excluded_pools": list(GATE_POOLS),
                            "excluded_count": 91})
    sc = _scope(own_names=[])          # no keep face: the pool is the only fact
    st = shared.quick_scope_state(sc, 0, wf._quick_scope_facts(ir, sc))
    assert st["zero_decision"] == shared.QUICK_ZERO_POOL
    assert st["decided_by"] == "lane_pool_declaration"
    assert "did NOT drop them" in st["detail"]
    assert "does not explain the zero" in st["detail"]
    assert CASE_POOL in st["line"]


def test_keep_face_peel_names_the_own_decision():
    wf = _wf()
    ir = _ir(ran=0, passed=0, details=[])
    st = shared.quick_scope_state(_scope(), 0, wf._quick_scope_facts(ir, _scope()))
    assert st["zero_decision"] == shared.QUICK_ZERO_OWN
    assert st["decided_by"] == "write_set_derivation"
    assert CASE in st["line"]


def test_fast_set_and_caller_flag_name_themselves():
    wf = _wf()
    fast = _ir(ran=0, passed=0, details=[], zero_run_face={"fast_set": True})
    st = shared.quick_scope_state(_scope(), 0, wf._quick_scope_facts(fast,
                                                                    _scope()))
    assert st["zero_decision"] == shared.QUICK_ZERO_FAST
    assert st["decided_by"] == "fast_set_declaration"
    caller = _ir(ran=0, passed=0, details=[])
    sc = _scope(caller_narrowed=True)
    st = shared.quick_scope_state(sc, 0, wf._quick_scope_facts(caller, sc))
    assert st["zero_decision"] == shared.QUICK_ZERO_FLAG
    assert st["decided_by"] == "caller_flag"
    # the vocabulary the ticket names is all present and code-shaped
    for code in (shared.QUICK_ZERO_REUSE, shared.QUICK_ZERO_OWN,
                 shared.QUICK_ZERO_FAST, shared.QUICK_ZERO_FLAG):
        assert code in shared.QUICK_ZERO_DECISIONS


def test_existing_faces_keep_their_behavior():
    wf = _wf()
    # a retired-premise entry still books nothing, and is not a product red
    retired = _ir(ran=0, passed=0, details=[],
                  zero_run_face={"retired_premise_excluded": [{"name": CASE}]})
    sc = _scope()
    st = shared.quick_scope_state(sc, 0, wf._quick_scope_facts(retired, sc))
    assert st["zero_decision"] == shared.QUICK_ZERO_RETIRED
    assert retired.passed == 0 and retired.failed == 0
    # a genuinely excluded case keeps its own vocabulary
    roster = _ir(ran=0, passed=0, details=[],
                 known_red={"skipped": 1, "names": [CASE]})
    st = shared.quick_scope_state(sc, 0, wf._quick_scope_facts(roster, sc))
    assert st["zero_decision"] == shared.QUICK_ZERO_ROSTER
    # a judged narrow round stays green, and a pool skip reported next to a real
    # run is still green (no loosening of the pre-ticket caliber)
    judged = _ir()
    assert wf._quick_gate_verdict(judged, sc) == "green"
    skipped = _ir(ran=2, passed=2,
                  details=[{"name": CASE, "cmd": "", "exit": 0},
                           {"name": "sc-other", "cmd": "", "exit": 0},
                           {"name": "__pool_exclude__", "cmd": "", "exit": 0}],
                  excluded_pools=list(GATE_POOLS), excluded_count=91)
    assert wf._quick_gate_verdict(skipped, sc) == "green"
    rec = wf._quick_gate_receipt(skipped, 0, sc)
    assert any(d.get("name") == "__pool_exclude__" for d in skipped.details)
    assert rec["status"] == "ok"
    # a real failure still reds, and names the case
    failed = _ir(ran=1, passed=0, failed=1,
                 details=[{"name": CASE, "cmd": "", "exit": 1,
                           "output_tail": "AssertionError: boom"}])
    assert wf._quick_gate_verdict(failed, sc) == "red"
    assert wf._quick_gate_receipt(failed, 0, sc)["violations"] == [CASE]


# ======================================================================
# C. Two rounds of one attempt: the same scope, and the mutation
# ======================================================================

class _StubWorkflow:
    """The activity shell of the round: records the args, returns queued
    results. Round N's result is what the witness hands back."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    @staticmethod
    def patched(_pid, *a, **k):
        return False

    async def execute_activity(self, _fn, args, **_kw):
        self.calls.append(args)
        return self.results[len(self.calls) - 1]


def _run(coro):
    """Run one coroutine on a PRIVATE event loop. Never `get_event_loop()`: an
    earlier test in the same process may have closed the ambient loop, and a
    battery must not depend on suite order."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _drive_rounds(wf, results, scope):
    stub = _StubWorkflow(results)
    saved = dev_lane.workflow
    dev_lane.workflow = stub
    try:
        out = []
        for _ in results:
            out.append(_run(wf._quick_gate_round(scope)))
        return out, stub.calls
    finally:
        dev_lane.workflow = saved


def test_two_rounds_of_one_attempt_run_the_same_scope():
    wf = _wf()
    scope = _scope()
    ran = _ir()
    irs, calls = _drive_rounds(wf, [ran, ran], scope)
    # the same pointed scope and the same keep face in BOTH rounds: the runner's
    # own exemption (pool / roster / reuse) therefore applies to both, which is
    # what makes the narrowed scope stable inside one attempt
    assert [c.only_names for c in calls] == [[CASE], [CASE]]
    assert [c.own_names for c in calls] == [[CASE], [CASE]]
    assert all(c.quick_scope.get("mode") == "scenario" for c in calls)
    assert wf._quick_gate_verdict(irs[0], scope) == "green"
    assert wf._quick_gate_verdict(irs[1], scope) == "green"


def test_mutation_round_two_strips_the_case_and_the_gate_reds_by_name():
    wf = _wf()
    scope = _scope()
    ran = _ir()
    stripped = shared.IntegrationRunResult(**INCIDENT_ZERO)
    irs, _calls = _drive_rounds(wf, [ran, stripped], scope)
    assert wf._quick_gate_verdict(irs[0], scope) == "green"
    assert wf._quick_gate_verdict(irs[1], scope) == "red"
    rec = wf._quick_gate_receipt(irs[1], 1, scope)
    assert rec["status"] == "failed"
    assert rec["scope_state"] == shared.QUICK_SCOPE_STATE_NOTHING_RAN
    assert rec["zero_run_decision"] == shared.QUICK_ZERO_REUSE
    # BY NAME, never a silent zero-run
    assert CASE in rec["violations"]
    assert rec["scope_unjudged"] == [CASE]
    text = wf._quick_gate_blocked_text(irs[1], "quick_gate_zero_run", 2, scope)
    assert "Declared but NOT judged" in text and CASE in text
    assert "ledger_reuse" in text and "NOTHING" in text
    # the round-1 truth is not rewritten: its receipt still says judged
    assert wf._quick_gate_receipt(irs[0], 0, scope)["status"] == "ok"


def test_mutation_widened_round_that_ran_other_cases_reds_by_name():
    # the other shape of the same strip: the runner widened to the full registry,
    # so counts look healthy (ran=1) while the DECLARED case never ran.
    wf = _wf()
    scope = _scope()
    widened = _ir(ran=1, passed=1,
                  details=[{"name": "some-other-case", "cmd": "", "exit": 0}],
                  excluded_pools=list(GATE_POOLS), excluded_count=91,
                  zero_run_face={"excluded_pools": list(GATE_POOLS),
                                 "excluded_count": 91,
                                 "narrowed_face_empty": True})
    assert wf._quick_scope_unjudged_names(widened, scope) == [CASE]
    assert wf._quick_gate_verdict(widened, scope) == "red"
    rec = wf._quick_gate_receipt(widened, 0, scope)
    assert CASE in rec["violations"] and rec["scope_unjudged"] == [CASE]
    text = wf._quick_gate_blocked_text(widened, "quick_gate_scope_unjudged", 1,
                                       scope)
    assert CASE in text and "Declared but NOT judged" in text
    assert len(text.splitlines()) <= dev_lane.QuickmanualLaneWorkflow.FACE_MAX_LINES


def test_receipt_that_carries_no_row_face_is_not_invented_into_a_red():
    # an absent execution face is not evidence that the case did not run: the
    # pre-ticket caliber stands there (the zero-run and counts locks cover the
    # shapes that really are a zero).
    wf = _wf()
    scope = _scope()
    assert wf._quick_scope_unjudged_names(_ir(ran=2, details=[]), scope) == []
    assert wf._quick_gate_verdict(_ir(ran=2, passed=2, details=[]), scope) == \
        "green"


def test_scope_pin_names_a_change_instead_of_hiding_it():
    same = shared.quick_scope_pin([CASE], [CASE])
    assert same["changed"] is False and same["line"] == ""
    moved = shared.quick_scope_pin([CASE], [CASE, "another-case"])
    assert moved["changed"] is True and moved["added"] == ["another-case"]
    assert "CHANGED" in moved["line"] and "another-case" in moved["line"]
    gone = shared.quick_scope_pin([CASE], [])
    assert gone["changed"] is True and gone["dropped"] == [CASE]
    # malformed input never raises and never reports a phantom change
    assert shared.quick_scope_pin(None, None)["changed"] is False
    assert shared.quick_scope_pin("nonsense", [CASE])["changed"] is False
    # the receipt carries the pin it was judged with
    wf = _wf()
    sc = _scope(scope_pin=dict(moved))
    rec = wf._quick_gate_receipt(_ir(), 0, sc)
    assert rec["scope_pin"]["changed"] is True
    assert rec["own_source"] == {}


# ======================================================================
# D. The real runner: the declared case stays in an excluded pool's round
# ======================================================================

@contextlib.contextmanager
def _env_stub(extra):
    saved = {k: os.environ.get(k) for k in extra}
    for k, v in extra.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _Runner:
    """Drive the REAL runner's main() over an injected mini registry whose
    declared case lives in an EXCLUDED pool (the gate's own engine/exclusive
    vocabulary). Stub scripts leave a marker on disk: 'it really ran'."""

    def __init__(self, rs):
        self.rs = rs

    def drive(self, keep_env="__unset__", only_env="__unset__",
              exclude="engine"):
        with tempfile.TemporaryDirectory(prefix="t261031-04-") as td:
            td_path = Path(td)
            table, markers = [], {}
            for i, (name, pool) in enumerate(
                    [(CASE, "engine"), ("t261031-04-fixture-other", "main")]):
                script = td_path / ("s%d.py" % i)
                marker = td_path / ("marker-%s" % name)
                script.write_text("from pathlib import Path\n"
                                  "Path(%r).write_text('ran')\n" % str(marker))
                table.append((name, "mini fixture (t261031-04)", "python3 %s"
                              % script, pool))
                markers[name] = marker
            saved = (self.rs.SCENARIOS, self.rs._sweep_residue_stages,
                     self.rs._docker_hygiene)
            saved_pre = (self.rs.batch_preboot, self.rs.batch_teardown)
            self.rs.SCENARIOS = table
            self.rs._sweep_residue_stages = lambda: None
            self.rs._docker_hygiene = lambda: None
            self.rs.batch_preboot = lambda consumers: True
            self.rs.batch_teardown = lambda: None
            env = {"SANDBAR_POOL_CONC": "1", "SANDBAR_CONC_POOLS": "",
                   "SANDBAR_SCENARIO_ONLY": CASE if only_env == "__unset__"
                   else only_env,
                   "SANDBAR_SCENARIO_OWN": None if keep_env == "__unset__"
                   else keep_env,
                   "SANDBAR_SCENARIO_EXCLUDE_POOLS": exclude,
                   "SANDBAR_KNOWN_RED_EXCLUDE": None,
                   # never write (or read) the real store from a unit battery
                   "SANDBAR_SCENARIO_LEDGER_DIR": str(td_path / "ledger"),
                   "SANDBAR_LEDGER_REUSE": "0"}
            cwd = os.getcwd()
            buf = io.StringIO()
            try:
                os.chdir(td_path)
                os.makedirs(td_path / "ledger", exist_ok=True)
                with _env_stub(env):
                    with contextlib.redirect_stdout(buf):
                        rc = self.rs.main(only_scenarios=only_env
                                          if only_env != "__unset__" else None)
            finally:
                (self.rs.SCENARIOS, self.rs._sweep_residue_stages,
                 self.rs._docker_hygiene) = saved
                (self.rs.batch_preboot, self.rs.batch_teardown) = saved_pre
                os.chdir(cwd)
            out = buf.getvalue()
            markers = {n: p.exists() for n, p in markers.items()}
            summary = {}
            for line in out.splitlines():
                if line.startswith("INTEG_SUMMARY "):
                    with contextlib.suppress(ValueError):
                        summary = json.loads(line[len("INTEG_SUMMARY "):])
            return rc, out, markers, summary


@pytest.fixture(scope="module")
def runner():
    return _Runner(_rs())


def test_declared_case_in_an_excluded_pool_runs_with_the_keep_face(runner):
    rc, out, markers, summary = runner.drive(keep_env=CASE)
    assert rc == 0, out[-800:]
    assert markers[CASE] is True, "the declared case must really run"
    assert "INTEG_OWN_KEPT" in out
    assert summary.get("ran") == 1 and summary.get("expected") == 1
    assert summary.get("excluded_pools") == ["engine"]


def test_the_same_scope_runs_again_on_the_second_round(runner):
    # the stability requirement, measured on the real runner: the same declaration
    # and the same keep face produce the same judged scope on a later round.
    rc1, out1, markers1, summary1 = runner.drive(keep_env=CASE)
    rc2, out2, markers2, summary2 = runner.drive(keep_env=CASE)
    assert (rc1, rc2) == (0, 0)
    assert markers1[CASE] is True and markers2[CASE] is True
    assert summary1.get("ran") == summary2.get("ran") == 1
    assert summary1.get("only_scenarios") == summary2.get("only_scenarios") \
        == [CASE]
    assert summary1.get("own_names") == summary2.get("own_names") == [CASE]


def test_mutation_without_the_keep_face_the_case_is_peeled(runner):
    # THE MUTATION: force the round to strip the declared case (empty keep face,
    # the case lives in the excluded pool). The case must NOT run - and that is
    # exactly the receipt the gate must red BY NAME.
    rc, out, markers, summary = runner.drive(keep_env="")
    assert markers[CASE] is False, "the mutation must actually peel the case"
    assert "INTEG_OWN_KEPT" not in out
    # the widened face ran the other case instead (empty = wider, not narrower)
    assert markers["t261031-04-fixture-other"] is True
    assert summary.get("narrowed_face_empty") is True
    assert CASE in (summary.get("only_scenarios") or [])
    # feed that receipt to the gate: red, and the case is NAMED
    wf = _wf()
    scope = _scope()
    details = [{"name": "t261031-04-fixture-other", "cmd": "", "exit": 0}]
    ir = shared.IntegrationRunResult(
        ran=int(summary.get("ran") or 0), passed=int(summary.get("pass") or 0),
        failed=0, env_fail=0, details=details,
        excluded_pools=list(summary.get("excluded_pools") or []),
        excluded_count=int(summary.get("excluded_count") or 0),
        zero_run_face={"narrowed_face_empty": True})
    assert wf._quick_gate_verdict(ir, scope) == "red"
    rec = wf._quick_gate_receipt(ir, 1, scope)
    assert rec["scope_unjudged"] == [CASE]
    assert CASE in rec["violations"]


def test_reuse_exemption_is_what_protects_the_keep_face():
    # The measured mechanism: a green row under the same commit+env_fp+width WOULD
    # cover the case (round 1 wrote exactly that row for round 2). The keep-face
    # exemption is what stops a green row from substituting for the proof.
    rs = _rs()
    rows = [{"scenario": CASE, "commit": "d5d1c141", "env_fp": "fp",
             "conc_width": 3, "verdict": "pass"}]
    covered = rs.reusable_names(rows, "d5d1c141", "fp", 3, candidates={CASE})
    assert covered == [CASE], "the incident's reuse key really does cover it"
    reused, own_rerun = rs.own_exempt_reuse(covered, {CASE})
    assert reused == [] and own_rerun == [CASE]
    # ... and a name outside the keep face keeps the old reuse economy
    reused2, own_rerun2 = rs.own_exempt_reuse(covered, {"some-own"})
    assert reused2 == [CASE] and own_rerun2 == []


# ======================================================================
# E. The relay: the runner, the gate and the resolver name the same facts
# ======================================================================

_RS_SRC = (REPO / "integration" / "run_scenarios.py").read_text(encoding="utf-8")
_VL_SRC = (REPO / "server" / "tools" / "verify_lane.py").read_text(
    encoding="utf-8")
_AA_SRC = (ENGINE / "agent_activities.py").read_text(encoding="utf-8")
_DL_SRC = (ENGINE / "dev_lane.py").read_text(encoding="utf-8")


def test_runner_summary_carries_the_reuse_and_drop_faces():
    assert '_summary["reuse_names"]' in _RS_SRC
    assert '_summary["reuse_judged_by"]' in _RS_SRC
    assert '_summary["dropped_by_pool"]' in _RS_SRC
    assert '_summary["own_names"]' in _RS_SRC
    assert '_summary["own_kept"]' in _RS_SRC
    # the widening vacuity is decided at the widening step, not re-derived after
    # the reuse peel (the false "the widened face was empty too" face)
    assert "widened_face_vacuous = True" in _RS_SRC
    assert "if narrowed_face_empty and widened_face_vacuous:" in _RS_SRC
    assert '_summary["pointed_face_reuse_empty"] = True' in _RS_SRC


def test_gate_relays_the_new_zero_faces_verbatim():
    for key in ("reuse_names", "reuse_judged_by", "dropped_by_pool",
                "own_names", "own_kept", "own_rerun", "fast_set"):
        assert "'%s'" % key in _VL_SRC, key


def test_resolver_derives_the_keep_face_from_the_write_set():
    assert "shared.quick_scope_protect(" in _AA_SRC
    assert "out.protected_names" in _AA_SRC
    assert "'cmds'" in _AA_SRC and "'pools'" in _AA_SRC
    # the engine hands the write set to the resolution and threads the union
    assert "write_set=list(self._effective_write_set() or [])" in _DL_SRC
    assert "shared.quick_scope_keep_names(" in _DL_SRC
    # the gate's own face carries the decision detail and the unjudged names
    assert '"zero_run_decided_by"' in _DL_SRC
    assert '"scope_unjudged"' in _DL_SRC
    assert '"quick_gate_scope_unjudged"' in _DL_SRC
