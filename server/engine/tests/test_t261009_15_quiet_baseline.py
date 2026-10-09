"""t261009-15 — quiet-baseline verdict for known load-sensitive checks at merge_check.

Unit surface (per plan rev 2 §7):
  T1  canonical_check_name — carrier-independent identity, malformed inputs.
  T2  _red_item_names_from_receipt — structured identity from the verify_lane
      receipt; malformed/absent lines yield NO names (no silent exemption).
  T3  byte-identity — quiet pass never touches existing keys of non-covered items.
  T4  exact-equality matching + roster-entry attribution (near-collision no-match).
  T5  roster error surfaced on the red item (C3), quiet rerun NOT attempted.
  T6  per-round cap; timeout; non-zero rc (incl. pytest 4/5) = quiet-red.
  T7  green quiet run carries red_items + quiet_verdicts(roster_entry, load_context).
  T9  cancellation reaps the spawn and propagates.

All subprocesses are stubs / tmp-dir scripts — no integration entry is executed.
"""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_activities as aa  # noqa: E402
import dev_lane as dl  # noqa: E402

SCENARIO = "integration/t260901-25/t03_reap_process_group.py"
WRAPPER = ("server/engine/tests/test_t260901_25_t03_reap_process_group.py::"
           "test_t260901_25_t03_reap_process_group")
ROSTER_NAME = "t260901-25-t03-reap-process-group"


# ---------------------------------------------------------------- T1 normalizer

def test_t1_carriers_share_identity():
    assert aa.canonical_check_name(SCENARIO) == "t260901_25_t03_reap_process_group"
    assert aa.canonical_check_name(WRAPPER) == \
        aa.canonical_check_name(SCENARIO)
    # roster name shares the key too (booking-side identity)
    assert aa.canonical_check_name(ROSTER_NAME) == \
        aa.canonical_check_name(WRAPPER)


def test_t1_malformed_inputs_never_throw():
    for bad in ("", None, ":::", "...", "///", "a::b::c", 123, {}, "ü\\n×"):
        k = aa.canonical_check_name(bad)
        assert isinstance(k, str) and k  # non-empty junk key, never crashes


def test_t1_idempotent():
    once = aa.canonical_check_name(WRAPPER)
    assert aa.canonical_check_name(once) == once


def test_t1_case_and_node_insensitive():
    assert aa.canonical_check_name(WRAPPER.upper()) == \
        aa.canonical_check_name(WRAPPER)


# ------------------------------------------------------------ T2 name extraction

def _receipt(*details, level="red"):
    return {"checks": [{"check": "ut", "level": level,
                        "items": [{"detail": d} for d in details]}]}


def test_t2_failed_and_error_lines():
    names = aa._red_item_names_from_receipt(_receipt(
        "FAILED " + WRAPPER, "ERROR " + SCENARIO))
    assert names == [WRAPPER, SCENARIO]


def test_t2_malformed_and_absent_lines_yield_no_names():
    assert aa._red_item_names_from_receipt(None) == []
    assert aa._red_item_names_from_receipt({}) == []
    assert aa._red_item_names_from_receipt({"checks": "junk"}) == []
    assert aa._red_item_names_from_receipt({"checks": [None, "str", {}]}) == []
    # detail without a parseable FAILED/ERROR line → no name → never exempted
    assert aa._red_item_names_from_receipt(_receipt("1 failed in 0.01s")) == []
    # green check is not scanned
    assert aa._red_item_names_from_receipt(_receipt("FAILED " + WRAPPER,
                                                    level="green")) == []


def test_t2_dedupes_and_tolerates_plain_strings():
    names = aa._red_item_names_from_receipt({"checks": [
        {"level": "red", "items": ["FAILED " + WRAPPER, "FAILED " + WRAPPER]}]})
    assert names == [WRAPPER]


# ------------------------------------------------- T4/T5/T6/T7 quiet-pass behavior

def _roster_tree(tmp, entries):
    tree = Path(tmp) / "tree"
    (tree / "integration").mkdir(parents=True, exist_ok=True)
    (tree / aa.shared.KNOWN_RED_BASELINE_REL).write_text(
        json.dumps({"meta": {}, "entries": entries}), "utf-8")
    return tree


def _red_item(names):
    # Mirrors the merge_check verify_lane red item shape (labels are structural
    # here; the quiet pass never reads the text, so English stand-ins suffice).
    return {"item": "in-lane verify_lane code green", "green": False,
            "detail": "exit=1 red=1; FAILED " + " ".join(names),
            "id": "verify_lane_code", "reason_code": "verify_red",
            "next_action": "fix the red item from detail, then send retry_qc",
            "red_items": [{"name": n} for n in names]}


def test_t7_green_quiet_run_records_evidence(tmp_path, monkeypatch):
    tree = _roster_tree(tmp_path, [{"name": ROSTER_NAME, "verdict": "isolated",
                                    "booked_sha": "abc123"}])
    item = _red_item([WRAPPER])
    checks = [item]
    seen = []

    async def fake_rerun(name, tree_):
        seen.append(name)
        return True, "exit=0 1 passed"

    monkeypatch.setattr(aa, "_quiet_rerun_green", fake_rerun)
    asyncio.run(aa._apply_quiet_verdicts("t", checks, tree))
    assert seen == [WRAPPER]
    qv = checks[0]["quiet_verdicts"]
    assert len(qv) == 1
    v = qv[0]
    assert v["green"] is True
    assert v["roster_entry"] == {"name": ROSTER_NAME, "verdict": "isolated",
                                 "booked_sha": "abc123"}
    lc = v["load_context"]
    for k in ("at", "inflight_activities", "owned_spawns", "scope_note"):
        assert k in lc
    # existing keys untouched (byte-identity of the text face)
    assert checks[0]["item"] == item["item"]
    assert checks[0]["detail"] == item["detail"]
    assert checks[0]["next_action"] == item["next_action"]
    assert checks[0]["green"] is False  # evidence only — never flipped here
    # routing predicate accepts it
    assert dl.quiet_baseline_covered(checks) is True


def test_t4_near_collision_does_not_match(tmp_path, monkeypatch):
    tree = _roster_tree(tmp_path, [
        {"name": "t260901-25-t03-reap-process-group-extra", "verdict": "isolated",
         "booked_sha": "d1"}])
    calls = []

    async def fake_rerun(name, tree_):
        calls.append(name)
        return True, "exit=0"

    monkeypatch.setattr(aa, "_quiet_rerun_green", fake_rerun)
    checks = [_red_item([WRAPPER])]
    asyncio.run(aa._apply_quiet_verdicts("t", checks, tree))
    assert calls == []  # no quiet rerun for a near-collision name
    assert "quiet_verdicts" not in checks[0]
    assert dl.quiet_baseline_covered(checks) is False  # falls to today's blocked


def test_t5_roster_error_is_surfaced_not_silent(tmp_path, monkeypatch):
    tree = Path(tmp_path) / "tree"
    (tree / "integration").mkdir(parents=True)
    (tree / aa.shared.KNOWN_RED_BASELINE_REL).write_text("{not json", "utf-8")
    calls = []

    async def fake_rerun(name, tree_):
        calls.append(name)
        return True, "exit=0"

    monkeypatch.setattr(aa, "_quiet_rerun_green", fake_rerun)
    checks = [_red_item([WRAPPER])]
    asyncio.run(aa._apply_quiet_verdicts("t", checks, tree))
    assert calls == []                      # fail-closed: no rerun, no exemption
    assert "roster unavailable:" in checks[0]["detail"]  # C3: named on the face
    assert dl.quiet_baseline_covered(checks) is False


def test_t3_items_without_names_are_untouched(tmp_path, monkeypatch):
    tree = _roster_tree(tmp_path, [{"name": ROSTER_NAME, "verdict": "isolated",
                                    "booked_sha": "abc123"}])
    calls = []

    async def fake_rerun(name, tree_):
        calls.append(name)
        return True, "exit=0"

    monkeypatch.setattr(aa, "_quiet_rerun_green", fake_rerun)
    plain = {"item": "x", "green": False, "detail": "verify_lane timed out",
             "id": "verify_lane_code", "reason_code": "verify_red"}
    checks = [dict(plain), _red_item([WRAPPER])]
    asyncio.run(aa._apply_quiet_verdicts("t", checks, tree))
    assert dict(checks[0]) == plain         # no red_items → zero perturbation
    assert len(checks[1]["quiet_verdicts"]) == 1


def test_t6_cap_limits_reruns_per_round(tmp_path, monkeypatch):
    tree = _roster_tree(tmp_path, [
        {"name": "t260901-25-t03-reap-process-group-%d" % i,
         "verdict": "isolated", "booked_sha": "s%d" % i} for i in range(4)])
    calls = []

    async def fake_rerun(name, tree_):
        calls.append(name)
        return True, "exit=0"

    monkeypatch.setattr(aa, "_quiet_rerun_green", fake_rerun)
    names = ["integration/t260901-25/t03_reap_process_group_%d.py" % i
             for i in range(4)]
    checks = [_red_item(names)]
    asyncio.run(aa._apply_quiet_verdicts("t", checks, tree))
    assert len(calls) == aa.MAX_QUIET_RERUNS_PER_ROUND
    qv = checks[0]["quiet_verdicts"]
    assert len(qv) == 4
    assert all(v["green"] for v in qv[:aa.MAX_QUIET_RERUNS_PER_ROUND])
    last = qv[-1]
    assert last["green"] is False and "cap reached" in last["error"]
    assert dl.quiet_baseline_covered(checks) is False  # degraded → today's path


def test_t6_real_subprocess_nonzero_rc_is_quiet_red(tmp_path):
    # scenario-carrier name → `python3 <path>`; missing file → rc != 0 → red
    green, detail = asyncio.run(
        aa._quiet_rerun_green("integration/t260901-25/no_such_scenario.py",
                              Path(tmp_path)))
    assert green is False
    assert detail.startswith("exit=")
    assert aa.owned_spawn_snapshot() == []  # spawn table drained (no leak)


def test_t6_timeout_reaps_and_fails_closed(tmp_path, monkeypatch):
    sleepy = Path(tmp_path) / "sleepy.py"
    sleepy.write_text("import time; time.sleep(5)\n", "utf-8")
    monkeypatch.setattr(aa, "QUIET_RERUN_TIMEOUT_S", 1)
    t0 = time.monotonic()
    green, detail = asyncio.run(aa._quiet_rerun_green(str(sleepy), Path(tmp_path)))
    assert green is False and "timed out" in detail
    assert time.monotonic() - t0 < 4        # killed at ~1s, not 5s
    assert aa.owned_spawn_snapshot() == []


def test_t9_cancellation_reaps_and_propagates(tmp_path):
    sleepy = Path(tmp_path) / "sleepy.py"
    sleepy.write_text("import time; time.sleep(10)\n", "utf-8")
    task = asyncio.run_coroutine_threadsafe  # placeholder to keep flake8 quiet
    del task

    async def go():
        t = asyncio.ensure_future(
            aa._quiet_rerun_green(str(sleepy), Path(tmp_path)))
        await asyncio.sleep(0.5)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(go())
    assert aa.owned_spawn_snapshot() == []  # reap on the cancel path


# ------------------------------------------------------- routing predicate (T8 face)

def test_t8_predicate_fail_closed_shapes():
    assert dl.quiet_baseline_covered([]) is False
    assert dl.quiet_baseline_covered([{"green": True}]) is False  # no reds
    assert dl.quiet_baseline_covered([_red_item([WRAPPER])]) is False
    assert dl.quiet_baseline_covered(
        [_red_item([WRAPPER]) | {"quiet_verdicts":
                                 [{"name": WRAPPER, "green": False,
                                   "detail": "exit=1"}]}]) is False
    assert dl.quiet_baseline_covered(
        [_red_item([WRAPPER]) | {"quiet_verdicts":
                                 [{"name": WRAPPER, "green": True,
                                   "error": "cap reached (3/round)"}]}]) is False
    assert dl.quiet_baseline_covered(
        [_red_item([WRAPPER]) | {"quiet_verdicts":
                                 [{"name": WRAPPER, "green": True}]}]) is True
