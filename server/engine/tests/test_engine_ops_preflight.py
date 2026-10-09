"""t261009-48: engine_ops restart pre-flight / refusal / handover-record UT.

Intent (the user-visible behaviour guarded): a worker handover must LOOK before it
kills — report what is in flight, refuse by name when a TERM would destroy work, and
record the decision. KI-01M4GF5R8NHQNATH7WD7SKF94X (orphaned STARTED workflow task)
and KI-01M4H1DN2Z10J973DD6PBMPB4W (handover landing on an in-flight round).

Coverage (pure/decidable faces only; real Temporal faces stay in the L3 scenario):
  1. parsers of the describe payload (pending workflow task, pending activities,
     malformed inputs degrade to named unknowns, never fabricated values);
  2. handover_blockers classification + refusal_message naming
     (ticket/stage/gen/elapsed — provenance per plan review item 1);
  3. decide_handover precedence (--force wins over wait; default is refuse);
  4. wait_for_round_boundary (bounded, injectable clock, clear/timeout faces);
  5. handover record writer (append-only single-line O_APPEND, garbage-tolerant,
     aborted_a_round only on forced-with-blockers, absolute path);
  6. cmd_restart refusal path signals nothing (no os.kill call) and still writes the
     record; force path proceeds and records aborted_a_round=true.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import tempfile
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

POC = pathlib.Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(REPO / "server" / "tools"))

import engine_ops as eo  # noqa: E402


def _proto_ts(epoch: float):
    """A proto-Timestamp-shaped stand-in (only ToDatetime is consumed)."""
    import datetime
    d = datetime.datetime.fromtimestamp(epoch)

    class _TS:
        def ToDatetime(self):
            return d
    return _TS()


def _fake_raw(*, pending_wf_task=None, pending_activities=(), history_length=12,
              status_name="RUNNING"):
    """DescribeWorkflowExecutionResponse stand-in (HasField discipline honoured)."""
    fields = {"workflow_execution_info": SimpleNamespace(
        status=SimpleNamespace(name=status_name)),
        "history_length": history_length, "history_size_bytes": history_length * 100}
    if pending_wf_task is not None:
        fields["pending_workflow_task"] = pending_wf_task

    class _Raw:
        def __init__(self):
            self.__dict__.update(fields)
            self.pending_activities = list(pending_activities)

        def HasField(self, name):
            return name in fields
    return _Raw()


def _fake_act(name="arbitrate", state="STARTED", attempt=2, started_epoch=None,
              identity="123@host"):
    return SimpleNamespace(
        activity_type=SimpleNamespace(name=name), state=SimpleNamespace(name=state),
        attempt=attempt, last_started_time=_proto_ts(started_epoch or time.time() - 90),
        last_worker_identity=identity)


def _preflight_with(*, wf_task=None, activities=(), stage="arbitrate", gen=3,
                    history=8000):
    return {"ticket": "t1", "available": True, "workflow_status": "RUNNING",
            "pending_workflow_task": wf_task or {"present": False, "state": "",
                                                 "attempt": 0, "started_at": "",
                                                 "running_s": None},
            "pending_activities": [_pending_row(a) for a in activities],
            "stage_face": {"available": True, "stage": stage, "stage_state": "running",
                           "gen": gen, "note": ""},
            "history": {"event_count": history, "size_bytes": history * 100},
            "worker": {"pid": 1, "state": "live", "started_at": "", "tree": "",
                       "stamp": {"available": True, "stale": False}},
            "note": ""}


def _pending_row(a):
    return {"activity_type": a.activity_type.name, "state": a.state.name.lower(),
            "attempt": a.attempt,
            "last_worker_identity": a.last_worker_identity,
            "last_started_at": "2026-10-10T00:00:00", "running_s": 90}


class WorkflowTaskFaceTest(unittest.TestCase):
    def test_present_when_hasfield_true(self):
        pwt = SimpleNamespace(state=SimpleNamespace(name="STARTED"), attempt=1,
                              started_time=_proto_ts(time.time() - 30))
        face = eo._workflow_task_face(_fake_raw(pending_wf_task=pwt), now=time.time())
        self.assertTrue(face["present"])
        self.assertEqual(face["state"], "started")
        self.assertEqual(face["attempt"], 1)
        self.assertGreaterEqual(face["running_s"], 25)

    def test_absent_when_hasfield_false(self):
        face = eo._workflow_task_face(_fake_raw(), now=time.time())
        self.assertFalse(face["present"])

    def test_malformed_raw_degrades_to_absent(self):
        # object without HasField and without the attribute: named absent, no raise
        face = eo._workflow_task_face(SimpleNamespace(pending_activities=[]))
        self.assertFalse(face["present"])
        self.assertEqual(face["running_s"], None)


class PendingActivityRowsTest(unittest.TestCase):
    def test_rows_carry_attempt_and_elapsed(self):
        rows = eo._pending_activity_rows([_fake_act()], now=time.time())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["activity_type"], "arbitrate")
        self.assertEqual(rows[0]["state"], "started")
        self.assertEqual(rows[0]["attempt"], 2)
        self.assertEqual(rows[0]["running_s"], 90)

    def test_malformed_time_and_missing_fields(self):
        row = eo._pending_activity_rows([SimpleNamespace(
            activity_type=None, state=None, attempt=None, last_started_time="garbage",
            last_worker_identity=None)], now=0)
        self.assertEqual(row[0]["activity_type"], "")
        self.assertIsNone(row[0]["running_s"])  # unknown, never fabricated

    def test_empty_and_none(self):
        self.assertEqual(eo._pending_activity_rows(None), [])
        self.assertEqual(eo._pending_activity_rows([]), [])


class BlockersAndRefusalTest(unittest.TestCase):
    def test_started_workflow_task_is_a_blocker(self):
        pre = _preflight_with(wf_task={"present": True, "state": "started", "attempt": 1,
                                       "started_at": "2026-10-10T00:00:00", "running_s": 30})
        b = eo.handover_blockers(pre)
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["kind"], "started_workflow_task")

    def test_in_flight_activity_is_a_blocker(self):
        pre = _preflight_with(activities=[_fake_act()])
        b = eo.handover_blockers(pre)
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["kind"], "in_flight_activity")
        self.assertEqual(b[0]["activity"], "arbitrate")

    def test_clear_when_nothing_pending(self):
        self.assertEqual(eo.handover_blockers(_preflight_with()), [])

    def test_refusal_names_ticket_stage_gen_elapsed(self):
        pre = _preflight_with(activities=[_fake_act()])
        b = eo.handover_blockers(pre)
        msg = eo.refusal_message("t1", b, pre["stage_face"])
        self.assertIn("t1", msg)
        self.assertIn("stage=arbitrate", msg)
        self.assertIn("gen=3", msg)
        self.assertIn("running=90s", msg)

    def test_unavailable_stage_is_named_not_fabricated(self):
        pre = _preflight_with()
        pre["stage_face"] = {"available": False, "stage": None, "stage_state": None,
                             "gen": None, "note": "unavailable: snapshot query failed"}
        msg = eo.refusal_message("t1", eo.handover_blockers(
            _preflight_with(wf_task={"present": True, "state": "started", "attempt": 1,
                                     "started_at": "", "running_s": 5})), pre["stage_face"])
        self.assertIn("stage=unavailable", msg)
        self.assertIn("gen=unavailable", msg)


class DecideHandoverTest(unittest.TestCase):
    def test_clear_when_no_blockers(self):
        self.assertEqual(eo.decide_handover([], False, "refuse"), "clear")
        self.assertEqual(eo.decide_handover([], True, "refuse"), "clear")

    def test_default_is_refuse(self):
        self.assertEqual(eo.decide_handover([{"kind": "x"}], False, "refuse"), "refused")

    def test_force_wins_over_wait(self):
        self.assertEqual(eo.decide_handover([{"kind": "x"}], True, "wait"), "forced")

    def test_wait_policy(self):
        self.assertEqual(eo.decide_handover([{"kind": "x"}], False, "wait"), "wait")


class RoundBoundaryWaitTest(unittest.TestCase):
    def test_clears_on_boundary(self):
        faces = [_preflight_with(activities=[_fake_act()]), _preflight_with()]
        out = eo.wait_for_round_boundary(lambda: faces.pop(0), wait_s=60, poll_s=0,
                                         sleep=lambda s: None)
        self.assertTrue(out["cleared"])

    def test_timeout_is_named_refusal_with_last_blockers(self):
        out = eo.wait_for_round_boundary(lambda: _preflight_with(activities=[_fake_act()]),
                                         wait_s=5, poll_s=0, sleep=lambda s: None)
        self.assertFalse(out["cleared"])
        self.assertEqual(len(out["last_blockers"]), 1)

    def test_malformed_fetch_raises_only_into_named_face(self):
        # fetch returning a dict without the faces must degrade to "no blockers"
        out = eo.wait_for_round_boundary(lambda: {}, wait_s=5, poll_s=0,
                                         sleep=lambda s: None)
        self.assertTrue(out["cleared"])


class HandoverRecordTest(unittest.TestCase):
    def setUp(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp(prefix="eo-preflight-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._old_data = eo.DATA
        eo.DATA = self._tmp

    def tearDown(self):
        eo.DATA = self._old_data

    def test_absolute_path_and_line_json(self):
        rec = eo.build_handover_record(scope="lane:t1", tid="t1", reason="engine fix",
                                       policy="refuse", preflight=_preflight_with(),
                                       blockers=[], disposition="refused", outcome="refused")
        face = eo.append_handover_record(rec)
        self.assertTrue(face["written"])
        self.assertTrue(pathlib.Path(face["path"]).is_absolute())
        lines = pathlib.Path(face["path"]).read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["disposition"], "refused")
        self.assertFalse(parsed["aborted_a_round"])
        self.assertIn("reason", parsed)
        self.assertIn("requested_by", parsed)

    def test_aborted_round_only_on_forced_with_blockers(self):
        blockers = [{"kind": "in_flight_activity", "activity": "arbitrate", "attempt": 2,
                     "running_s": 90, "risk": "r"}]
        forced = eo.build_handover_record(scope="lane:t1", tid="t1", reason="", policy="refuse",
                                          preflight=_preflight_with(), blockers=blockers,
                                          disposition="forced", outcome="handover_ok")
        self.assertTrue(forced["aborted_a_round"])
        refused = eo.build_handover_record(scope="lane:t1", tid="t1", reason="", policy="refuse",
                                           preflight=_preflight_with(), blockers=blockers,
                                           disposition="refused", outcome="refused")
        self.assertFalse(refused["aborted_a_round"])
        waited = eo.build_handover_record(scope="lane:t1", tid="t1", reason="", policy="wait",
                                          preflight=_preflight_with(), blockers=[],
                                          disposition="waited", outcome="handover_ok")
        self.assertFalse(waited["aborted_a_round"])

    def test_appends_and_survives_garbage_file(self):
        p = eo.handover_record_path()
        p.write_text("not json at all\n", encoding="utf-8")
        rec = eo.build_handover_record(scope="central", tid="", reason="", policy="refuse",
                                       preflight=_preflight_with(), blockers=[],
                                       disposition="clear", outcome="handover_ok")
        eo.append_handover_record(rec)
        lines = p.read_text().strip().splitlines()
        self.assertEqual(lines[0], "not json at all")
        self.assertEqual(json.loads(lines[1])["disposition"], "clear")

    def test_unwritable_path_is_named_not_raised(self):
        eo.DATA = pathlib.Path("/proc/nonexistent-xyz")
        rec = eo.build_handover_record(scope="central", tid="", reason="", policy="refuse",
                                       preflight=_preflight_with(), blockers=[],
                                       disposition="clear", outcome="handover_ok")
        face = eo.append_handover_record(rec)
        self.assertFalse(face["written"])
        self.assertIn("failed", face["note"])


def _restart_args(**kw):
    base = dict(host="", ns="", scope="lane:t1", wait=1.0, old_drain=1.0,
                inflight_policy="refuse", inflight_wait=300.0, force=False, reason="why",
                replace=False)
    base.update(kw)
    return argparse.Namespace(**base)


_PREFLIGHT_WITH_BLOCKERS = None


class CmdRestartRefusalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp(prefix="eo-preflight-"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._old = (eo.DATA, eo._PREFLIGHT_FETCH)
        eo.DATA = self._tmp

    def tearDown(self):
        eo.DATA, eo._PREFLIGHT_FETCH = self._old

    def test_refusal_signals_nothing_but_writes_record(self):
        kills = []
        pre = _preflight_with(activities=[_fake_act()])
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: pre), \
             mock.patch.object(eo.os, "kill", lambda *a, **k: kills.append(a)), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn",
                               lambda *a, **k: (_ for _ in ()).throw(
                                   AssertionError("kill path must not run on refusal"))):
            out = eo.cmd_restart(_restart_args())
        self.assertEqual(kills, [])
        self.assertFalse(out["ok"])
        self.assertEqual(out["result"]["disposition"], "refused")
        self.assertIn("stage=arbitrate", out["error"])
        self.assertTrue(pathlib.Path(out["result"]["record_path"]).exists())
        lines = pathlib.Path(out["result"]["record_path"]).read_text().strip().splitlines()
        self.assertEqual(json.loads(lines[0])["disposition"], "refused")

    def test_unavailable_preflight_with_no_blockers_proceeds_named(self):
        # describe failed → named unavailable face; nothing flagged in flight → the
        # limitation is carried in preflight_note, the handover itself proceeds.
        pre = _preflight_with()
        pre["available"] = False
        pre["note"] = "unavailable: describe failed"
        res = {"error": "", "phases": []}
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: pre), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn", lambda *a, **k: res):
            out = eo.cmd_restart(_restart_args())
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["disposition"], "clear")
        self.assertIn("unavailable", out["result"]["preflight"]["note"])

    def test_force_proceeds_and_records_aborted_round(self):
        pre = _preflight_with(activities=[_fake_act()])
        res = {"error": "", "phases": []}
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: pre), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn", lambda *a, **k: res):
            out = eo.cmd_restart(_restart_args(force=True))
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["disposition"], "forced")
        self.assertTrue(out["result"]["aborted_a_round"])
        rec = json.loads(pathlib.Path(out["result"]["record_path"])
                         .read_text().strip().splitlines()[0])
        self.assertEqual(rec["disposition"], "forced")
        self.assertTrue(rec["aborted_a_round"])
        self.assertEqual(rec["reason"], "why")
        self.assertIn("requested_by", rec)

    def test_wait_policy_clears_then_proceeds(self):
        faces = [_preflight_with(activities=[_fake_act()]), _preflight_with()]
        res = {"error": "", "phases": []}
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: faces.pop(0)), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn", lambda *a, **k: res), \
             mock.patch.object(eo.time, "sleep", lambda s: None):
            out = eo.cmd_restart(_restart_args(inflight_policy="wait", inflight_wait=60))
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["disposition"], "waited")

    def test_wait_timeout_ends_in_refusal_not_kill(self):
        pre = _preflight_with(activities=[_fake_act()])
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: pre), \
             mock.patch.object(eo.os, "kill", lambda *a, **k: (_ for _ in ()).throw(
                 AssertionError("timeout must not kill"))), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn",
                               lambda *a, **k: (_ for _ in ()).throw(AssertionError("no kill"))):
            out = eo.cmd_restart(_restart_args(inflight_policy="wait", inflight_wait=1))
        self.assertFalse(out["ok"])
        self.assertEqual(out["result"]["disposition"], "refused")

    def test_bad_policy_is_named_error(self):
        out = eo.cmd_restart(_restart_args(inflight_policy="yolo"))
        self.assertEqual(out.get("exit"), eo.ENV_EXIT)
        self.assertIn("refuse | wait", out["error"])

    def test_long_history_names_continue_as_new_hint(self):
        pre = _preflight_with(history=12000)
        res = {"error": "", "phases": []}
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: pre), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn", lambda *a, **k: res):
            out = eo.cmd_restart(_restart_args())
        self.assertIn("continue-as-new", out["result"]["hint"])

    def test_short_history_has_no_continue_as_new_hint(self):
        pre = _preflight_with(history=100)
        res = {"error": "", "phases": []}
        with mock.patch.object(eo, "_PREFLIGHT_FETCH", lambda *a, **k: pre), \
             mock.patch.object(eo, "_kill_and_wait_for_respawn", lambda *a, **k: res):
            out = eo.cmd_restart(_restart_args())
        self.assertNotIn("continue-as-new", out["result"]["hint"])


if __name__ == "__main__":
    unittest.main()
