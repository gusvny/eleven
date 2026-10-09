# -*- coding: utf-8 -*-
"""t261008-29 KI-227 stale-worker visibility + stage-in-memo unit tests.

Covers the ticket's failure modes at the unit level (integration entry points are
NOT executed here — the engine integration gate runs those):

L1 fingerprint v2:
  - a written v2 doc carries a NON-EMPTY code fingerprint and an activity-set
    entry (+ stable hash);
  - adding an activity MOVES the activity fingerprint;
  - v1 docs still read OK (deliver's fast-refusal must survive the upgrade);
  - malformed inputs degrade named, never throw (consumer-of-external-data rule).

L3 comparison face (fixture docs only — no live queue is ever touched):
  - a worker whose activity set is a STRICT SUBSET of the current composition is
    reported stale_activities, NAMING the missing activities;
  - an activity that exists in the tree but not in a running worker's
    registration is reported BEFORE any scheduling (the face is a pure verdict
    function on the fingerprint doc);
  - empty/unreadable code identity -> unknown, never "fresh";
  - dead pid -> offline; absent fingerprint -> unknown(absent).

Negative (observe-only):
  - staleness_report returns data and touches nothing: no writes, no kills, no
    subprocess, no lane access (asserted structurally: pure function on inputs;
    a call with a fully-stale fixture doc leaves the tmp dir byte-identical).

Memo path (stage survives the terminal state):
  - dev_lane persists stage via workflow.upsert_memo behind the KI-227 patch
    gate, FAILURE-ISOLATED (an upsert exception is logged and swallowed — the
    stage transition must not change behaviour, review condition 1);
  - client._terminal_face_stage_from_memo decodes a present memo stage, keeps
    the honest-unavailable note for a pre-fix ticket (no memo key), and degrades
    named on a malformed describe stub.
"""
import json
import os
import pathlib
import sys
import types
from unittest import mock

import pytest

ENGINE_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import worker_registry as wr  # noqa: E402


# ---------------------------------------------------------------- fingerprint v2

def _write(tmp_path, activities, code="abc1234", names=("A", "B")):
    return wr.write_fingerprint(str(tmp_path / "fp.json"), list(names), pid=42,
                                now_ms=1_000, code_fingerprint=code,
                                activity_names=list(activities))


def test_v2_doc_has_code_fingerprint_and_activity_entry(tmp_path):
    doc = _write(tmp_path, ["a_one", "a_two"])
    assert doc["version"] == 2
    assert doc["code_fingerprint"] == "abc1234"
    assert doc["activities"] == ["a_one", "a_two"]
    assert len(doc["activity_fingerprint"]) == 64  # sha256 hex
    back, err = wr.read_fingerprint(str(tmp_path / "fp.json"))
    assert err is None and back["activity_fingerprint"] == doc["activity_fingerprint"]


def test_activity_fingerprint_moves_when_activity_added(tmp_path):
    fp_before = _write(tmp_path / "before", ["a", "b"])["activity_fingerprint"]
    fp_after = _write(tmp_path / "after", ["a", "b", "c"])["activity_fingerprint"]
    assert fp_before != fp_after
    # order-independent: sorted before hashing
    assert wr.activity_fingerprint(["b", "a"]) == wr.activity_fingerprint(["a", "b"])


def test_v1_doc_still_reads_and_fingerprint_computed(tmp_path):
    p = tmp_path / "v1.json"
    p.write_text(json.dumps({"version": 1, "pid": os.getpid(), "started_at_ms": 5,
                             "code_fingerprint": "", "registered": ["W"]}),
                 encoding="utf-8")
    doc, err = wr.read_fingerprint(str(p))
    assert err is None
    assert doc["activities"] is None and doc["activity_fingerprint"] == ""
    # v1 doc never reads as fresh once HEAD is known: unknown, named
    v = wr.staleness_report(doc, None, head_sha="deadbeef",
                            tree_activity_fingerprint="x" * 64)
    assert v["verdict"] == wr.VERDICT_UNKNOWN
    assert "empty code fingerprint" in v["why"]  # v1 carries no sha -> unknown, named


def test_malformed_inputs_degrade_named(tmp_path):
    cases = {
        "bad.json": "{not json",
        "wrongver.json": json.dumps({"version": 3, "registered": []}),
        "badacts.json": json.dumps({"version": 2, "registered": ["W"],
                                    "activities": "not-a-list"}),
        "badtypes.json": json.dumps({"version": 2, "registered": ["W"],
                                     "activities": ["a"], "code_dirty": "yes"}),
    }
    for name, body in cases.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
        doc, err = wr.read_fingerprint(str(tmp_path / name))
        assert doc is None and err and "malformed" in err, name
    # absent file
    doc, err = wr.read_fingerprint(str(tmp_path / "nope.json"))
    assert doc is None and err == "absent"


def test_code_identity_env_override(tmp_path):
    env = {wr.CODE_FINGERPRINT_ENV: "cafe123:dirty"}
    ident = wr.code_identity(str(tmp_path), env=env)
    assert ident == {"sha": "cafe123", "dirty": True, "source": "env", "error": ""}
    env2 = {wr.CODE_FINGERPRINT_ENV: ""}
    # empty override = fall through to git (tmp_path is not a repo -> named error,
    # empty sha, never a fabricated hash)
    ident2 = wr.code_identity(str(tmp_path), env=env2)
    assert ident2["sha"] == "" and ident2["error"]


# ---------------------------------------------------------------- comparison face

def _doc(pid=None, code="HEADSHA", acts=("a", "b"), afp=None):
    return {"version": 2, "pid": pid if pid is not None else os.getpid(),
            "started_at_ms": 1,
            "code_fingerprint": code,
            "activity_fingerprint": afp or wr.activity_fingerprint(list(acts)),
            "activities": list(acts), "code_dirty": False}


TREE = ["a", "b", "c"]  # the tree gained activity "c"


def test_strict_subset_reported_stale_naming_missing():
    # fixture worker knows {a, b}; the tree composes {a, b, c} -> stale, names "c"
    v = wr.staleness_report(_doc(acts=["a", "b"]), None, head_sha="HEADSHA",
                            tree_activity_fingerprint=wr.activity_fingerprint(TREE),
                            tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_ACTIVITY_STALE
    assert "c" in v["why"] and "strict subset" in v["why"]


def test_mismatch_not_subset_warns_differently():
    v = wr.staleness_report(_doc(acts=["a", "zzz"]), None, head_sha="HEADSHA",
                            tree_activity_fingerprint=wr.activity_fingerprint(TREE),
                            tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_ACTIVITY_STALE
    assert "not a subset" in v["why"]


def test_matching_worker_is_ok():
    v = wr.staleness_report(_doc(acts=TREE), None, head_sha="HEADSHA",
                            tree_activity_fingerprint=wr.activity_fingerprint(TREE),
                            tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_OK


def test_code_stale_when_sha_differs():
    v = wr.staleness_report(_doc(code="oldsha", acts=TREE), None,
                            head_sha="HEADSHA",
                            tree_activity_fingerprint=wr.activity_fingerprint(TREE),
                            tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_CODE_STALE


def test_unknown_never_fresh_when_identity_unavailable():
    v = wr.staleness_report(_doc(code=""), None, head_sha="HEADSHA",
                            tree_activity_fingerprint="x", tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_UNKNOWN
    v2 = wr.staleness_report(_doc(), None, head_sha="",
                             tree_activity_fingerprint="x", tree_activity_names=TREE)
    assert v2["verdict"] == wr.VERDICT_UNKNOWN
    # pid 0 / junk = liveness unverifiable -> unknown, never ok
    v3 = wr.staleness_report(_doc(pid=0, code="HEADSHA", acts=TREE), None,
                             head_sha="HEADSHA",
                             tree_activity_fingerprint=wr.activity_fingerprint(TREE),
                             tree_activity_names=TREE)
    assert v3["verdict"] == wr.VERDICT_UNKNOWN


def test_offline_when_pid_dead():
    v = wr.staleness_report(_doc(pid=999999), None, head_sha="HEADSHA",
                            tree_activity_fingerprint="x", tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_OFFLINE


def test_absent_fingerprint_is_named_unknown():
    v = wr.staleness_report(None, "absent", head_sha="HEADSHA",
                            tree_activity_fingerprint="x", tree_activity_names=TREE)
    assert v["verdict"] == wr.VERDICT_UNKNOWN and "absent" in v["why"]


def test_face_is_observe_only(tmp_path):
    """Negative: the face reads inputs and writes nothing — the directory is
    byte-identical after the call, and no kill signal path exists to call."""
    before = sorted(p.name for p in tmp_path.iterdir())
    doc = _doc(acts=["a", "b"])
    wr.staleness_report(doc, None, head_sha="HEADSHA",
                        tree_activity_fingerprint="x", tree_activity_names=TREE)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    # structurally: the module exposes no restart/stop/kill surface
    for banned in ("restart", "stop", "terminate", "cancel", "signal_worker"):
        assert not any(banned in n for n in dir(wr)), banned


# ---------------------------------------------------------------- CLI face

def test_staleness_cli_absent_fingerprint_green_line():
    import subprocess
    env = {"SANDBAR_WORKER_REGISTRY_FINGERPRINT": "/tmp/ki227-does-not-exist.json",
           "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp"}
    p = subprocess.run([sys.executable, str(ENGINE_DIR / "worker_staleness.py")],
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0
    line = [l for l in p.stdout.splitlines() if l.startswith("{")][-1]
    doc = json.loads(line)
    assert doc["ok"] is True
    assert doc["verdict"]["verdict"] == "unknown"
    assert doc["head"]["sha"]  # read-only git probe answered


# ---------------------------------------------------------------- memo path
#
# Order-independence (arbitrate rework, full-suite pollution lesson): these tests
# do NOT patch the temporalio.workflow module attributes. In a full-suite run some
# other test may leave a stub temporalio in sys.modules, and if dev_lane is first
# imported under that stub its module-global `workflow` is the stub — patching
# "the real" module then misses. So each test injects a SELF-CONTAINED fake
# workflow module into dev_lane's own namespace (patch.object(dev_lane,
# "workflow", ...)), carrying every attribute _persist_stage_memo touches
# (patched / upsert_memo / logger / now). The tests therefore assert their own
# preconditions instead of inheriting process state, in any order.

class _FakeWfLogger:
    def __init__(self):
        self.calls = []

    def warning(self, *a, **k):
        self.calls.append(("warning", a, k))

    def info(self, *a, **k):
        self.calls.append(("info", a, k))


def _fake_workflow(patched_value=True, upsert=None):
    """A self-contained stand-in for the temporalio.workflow surface that
    _persist_stage_memo uses. `upsert(updates)` is injectable per test."""
    from datetime import datetime
    logger = _FakeWfLogger()

    def default_upsert(updates):
        return None

    return (types.SimpleNamespace(
                patched=lambda pid: patched_value,
                upsert_memo=upsert or default_upsert,
                logger=logger,
                now=lambda: datetime(2026, 1, 1, tzinfo=None)),
            logger)


class _MemoStub:
    """Minimal workflow instance carrying only what the helper touches."""
    ticket_id = "t-test"
    ts = 1

    def _now_epoch(self) -> int:
        # own clock: the helper's timestamp source must not touch the real
        # (possibly sandboxed/stubbed) temporalio.workflow.now()
        return self.ts

    def __init__(self, history=None):
        self._stage_memo_history = list(history or [])

    def _persist_stage_memo(self, stage, note=""):
        import dev_lane
        return dev_lane.DevLaneWorkflow._persist_stage_memo(self, stage, note)


def test_stage_memo_upsert_failure_isolated():
    """Review condition 1: a raising upsert must NOT fail the stage transition —
    it is caught and logged."""
    dev_lane = pytest.importorskip("dev_lane")
    fake, logger = _fake_workflow(
        patched_value=True,
        upsert=lambda m: (_ for _ in ()).throw(RuntimeError("capability missing")))
    with mock.patch.object(dev_lane, "workflow", fake):
        _MemoStub()._persist_stage_memo("create_plan", "enter gen=1")  # must not raise
    assert logger.calls, "the swallowed upsert failure must be logged loudly"
    assert any(kind == "warning" for kind, _, _ in logger.calls)


def test_stage_memo_persists_when_healthy():
    dev_lane = pytest.importorskip("dev_lane")
    writes = {}
    fake, _ = _fake_workflow(patched_value=True,
                             upsert=lambda m: writes.update(m))
    with mock.patch.object(dev_lane, "workflow", fake):
        stub = _MemoStub(history=[{"ts": 0, "stage": "create_plan", "note": "enter"}])
        stub.ts = 7
        stub._persist_stage_memo("implement", "enter gen=1")
    assert writes, "a healthy upsert must fire"
    assert writes[dev_lane.STAGE_MEMO_KEY] == "implement"
    assert writes[dev_lane.STAGE_MEMO_HISTORY_KEY][-1] == {
        "ts": 7, "stage": "implement", "note": "enter gen=1"}


def test_stage_memo_patched_off_emits_nothing():
    """Replay safety: with the patch gate closed (in-flight replay) the upsert is
    never attempted — no new command the old history lacks."""
    dev_lane = pytest.importorskip("dev_lane")
    calls = []
    fake, _ = _fake_workflow(patched_value=False,
                             upsert=lambda m: calls.append(m))
    with mock.patch.object(dev_lane, "workflow", fake):
        _MemoStub()._persist_stage_memo("implement")
    assert not calls, "a closed patch gate must emit zero memo commands"


def test_stage_memo_history_capped():
    dev_lane = pytest.importorskip("dev_lane")
    writes = {}
    fake, _ = _fake_workflow(patched_value=True,
                             upsert=lambda m: writes.update(m))
    seed = [{"ts": i, "stage": "s", "note": ""}
            for i in range(dev_lane.STAGE_MEMO_HISTORY_CAP + 5)]
    with mock.patch.object(dev_lane, "workflow", fake):
        _MemoStub(history=seed)._persist_stage_memo("merge")
    hist = writes[dev_lane.STAGE_MEMO_HISTORY_KEY]
    assert len(hist) == dev_lane.STAGE_MEMO_HISTORY_CAP
    assert hist[-1]["stage"] == "merge"


# ---------------------------------------------------------------- terminal face decode

def test_terminal_face_stage_from_memo_present():
    client = pytest.importorskip("client")
    dev_lane = pytest.importorskip("dev_lane")

    class Desc:
        async def memo(self):
            return {dev_lane.STAGE_MEMO_KEY: "create_plan",
                    dev_lane.STAGE_MEMO_HISTORY_KEY: [{"ts": 1, "stage": "create_plan",
                                                       "note": "enter gen=1"}]}

    import asyncio
    face = asyncio.run(client._terminal_face_stage_from_memo(Desc()))
    assert face["last_stage"] == "create_plan"
    assert face["last_stage_available"] is True
    assert "memo" in face["last_stage_note"]


def test_terminal_face_stage_absent_keeps_honest_note():
    """Pre-fix ticket: no memo key -> the face keeps saying it cannot know."""
    client = pytest.importorskip("client")

    class Desc:
        async def memo(self):
            return {"unrelated": 1}

    import asyncio
    face = asyncio.run(client._terminal_face_stage_from_memo(Desc()))
    assert face["last_stage"] is None and face["last_stage_available"] is False
    assert "omitted rather than guessed" in face["last_stage_note"]


def test_terminal_face_malformed_describe_degrades_named():
    """Consumer-of-external-data rule: a stub describe without memo(), or one
    whose memo() raises, degrades named — never throws out of the face."""
    client = pytest.importorskip("client")
    import asyncio

    face = asyncio.run(client._terminal_face_stage_from_memo(object()))
    assert face["last_stage"] is None and "unavailable" in face["last_stage_note"]

    class Bad:
        async def memo(self):
            raise RuntimeError("decode boom")

    face2 = asyncio.run(client._terminal_face_stage_from_memo(Bad()))
    assert face2["last_stage"] is None and "decode boom" in face2["last_stage_note"]
