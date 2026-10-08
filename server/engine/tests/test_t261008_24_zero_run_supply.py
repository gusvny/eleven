"""KI-220 (t261008-24) unit truth tables: the gate zero-run supply shape is a named
BLOCKER (never a green pass), the round stays exempt (budget untouched), and the
merge gate requires one green run of the ticket's scenarios on this tree
(KI-217 exit (1) — ONE mechanism).

Layers pinned here:
  ① classifier (shared.gate_zero_run_supply_blocker) — supply signature + ran=0 +
    empty blockers => blocker; real scenario red / legal zero-run (empty error) /
    malformed fields => None (fail closed to the previous behaviour); env_fail>0 =>
    None; each SUPPLY signature variant fires individually (T6).
  ② route override (shared.supply_stop_route) — blocked text names the supply face
    AND both exits (fix the supply, retry_qc); non-firing receipts => "".
  ③ face selection (shared.green_run_face) — full green rounds only; targeted-only,
    red, supply-red, malformed => None; legal zero-scenarios green => the named
    no_scenarios face.
  ④ merge_check item (shared.green_run_check_item) — missing face => red zero-run;
    stale sha => red stale; no_scenarios face => green named; malformed face /
    unknown HEAD => red fail-closed; well-formed matching face => green.
  ⑤ wiring — dev_lane inserts stop/record at the three receipt points (main run +
    two closing-run branches), light_lane at its gate round and its merge_check
    args; the helpers are patch-gated (KI220_ZERO_RUN_PATCH_ID); the round budget
    is untouched (tests_round_step counted=False on the env-side-red path).
  ⑥ workflow helpers (dev_lane._ki220_supply_zero_run_stop /
    _ki220_record_green_run) driven with a stubbed workflow facade — blocked text
    names face + exits, blocked_detail pinned, face recorded/absent per the
    activity result (fail-closed).

Run: server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t261008_24_zero_run_supply.py -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import shared  # noqa: E402

SIG = ("SUPPLY_ASSEMBLY_FAILED: supply assembly failed (need=docker test stage "
       "... exit=2): STAGE_WAIT ... docker info timed out ... SUPPLY_SIDE_RED")
SIG_TIMEOUT = ("SUPPLY_ASSEMBLY_TIMEOUT: supply assembly timed out "
               "(need=docker test stage) ... SUPPLY_SIDE_RED")
SIG_STAGE = ("SUPPLY_STAGE_TIMEOUT: stage budget exceeded (need=docker test stage) "
             "... SUPPLY_SIDE_RED")


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 0)
        self.passed = kw.get("passed", 0)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


def _supply_receipt(**kw):
    return _Receipt(error=SIG, **kw)


# ---------------- ① classifier ----------------

def test_t1_supply_shape_fires():
    b = shared.gate_zero_run_supply_blocker(_supply_receipt())
    assert b is not None
    assert b["name"] == shared.SUPPLY_ZERO_RUN_BLOCKER_NAME
    assert b["reason_code"] == "supply_zero_run"
    assert "SUPPLY_SIDE_RED" in b["text"]


def test_t2_real_red_receipt_does_not_fire():
    assert shared.gate_zero_run_supply_blocker(_supply_receipt(failed=2)) is None
    assert shared.gate_zero_run_supply_blocker(
        _supply_receipt(blockers=["t261008-07-detail-single-column"])) is None


def test_t3_legal_zero_run_does_not_fire():
    # empty registry / probe-only round: zero counts, empty error
    assert shared.gate_zero_run_supply_blocker(_Receipt()) is None


def test_t4_malformed_fields_fail_closed():
    r = _supply_receipt()
    r.ran = "x"
    assert shared.gate_zero_run_supply_blocker(r) is None
    r2 = _supply_receipt()
    r2.blockers = None          # absent/unknown blockers face: previous behaviour
    assert shared.gate_zero_run_supply_blocker(r2) is None
    assert shared.gate_zero_run_supply_blocker(None) is None
    # plain dict receipt (activity-layer shape) reads the same keys
    assert shared.gate_zero_run_supply_blocker(
        {"ran": 0, "failed": 0, "env_fail": 0, "blockers": [], "error": SIG}) is not None
    assert shared.gate_zero_run_supply_blocker({"ran": "x", "blockers": []}) is None


def test_t5_env_fail_positive_is_not_this_shape():
    assert shared.gate_zero_run_supply_blocker(_supply_receipt(env_fail=3)) is None


def test_t6_each_signature_variant_fires_individually():
    for sig in (SIG, SIG_TIMEOUT, SIG_STAGE):
        assert shared.gate_zero_run_supply_blocker(_Receipt(error=sig)) is not None, sig
    # the side token alone is not enough (single-token miss stays a miss)
    assert shared.gate_zero_run_supply_blocker(
        _Receipt(error="SUPPLY_ASSEMBLY_FAILED only, no side token")) is None


# ---------------- ② route override ----------------

def test_route_names_face_and_exits():
    route = shared.supply_stop_route(_supply_receipt())
    assert route.startswith("blocked:")
    assert "SUPPLY_SIDE_RED" in route                      # face quoted, not silenced
    assert "retry_qc" in route                             # exit 1
    assert "fix the supply" in route                       # exit 2
    assert "ZERO scenarios" in route


def test_route_empty_for_non_firing_receipts():
    assert shared.supply_stop_route(_Receipt()) == ""                    # legal zero-run
    assert shared.supply_stop_route(_supply_receipt(failed=1)) == ""     # real red
    assert shared.supply_stop_route(None) == ""


# ---------------- ③ face selection ----------------

def test_green_face_full_green_round():
    assert shared.green_run_face(3, 0, "", [], False) == {"ran": 3}


def test_green_face_legal_zero_scenarios():
    assert shared.green_run_face(0, 0, "", [], False) == {"ran": 0, "no_scenarios": True}


def test_green_face_rejects_red_targeted_and_malformed():
    assert shared.green_run_face(3, 1, "", [], False) is None            # failed>0
    assert shared.green_run_face(3, 0, "", ["b"], False) is None         # blockers
    assert shared.green_run_face(0, 0, "boom", [], False) is None        # startup error
    assert shared.green_run_face(3, 0, "", [], True) is None             # targeted-only
    assert shared.green_run_face("x", 0, "", [], False) is None          # malformed
    assert shared.green_run_face(3, 0, "", None, False) is None          # blockers face absent


# ---------------- ④ merge_check item ----------------

SHA = "0123456789abcdef0123456789abcdef01234567"


def _item(**kw):
    return shared.green_run_check_item(kw.pop("face", None), kw.pop("head", SHA), **kw)


def test_item_missing_face_is_red_zero_run():
    it = _item()
    assert it["green"] is False and it["reason_code"] == "zero_run"
    assert "KI-220" in it["detail"]
    assert it["id"] == shared.GREEN_RUN_CHECK_ID


def test_item_matching_green_face_is_green():
    it = _item(face={"sha": SHA, "ran": 3, "at": 1})
    assert it["green"] is True and it["reason_code"] == "ok"
    assert "3 scenario(s)" in it["detail"]


def test_item_stale_sha_is_red_named():
    it = _item(face={"sha": "f" * 40, "ran": 3})
    assert it["green"] is False and it["reason_code"] == "stale"
    assert "stale" in it["detail"]


def test_item_no_scenarios_face_is_green_named():
    it = _item(face={"sha": SHA, "ran": 0, "no_scenarios": True})
    assert it["green"] is True and it["reason_code"] == "no_scenarios"


def test_item_ran0_without_mark_fails_closed():
    it = _item(face={"sha": SHA, "ran": 0})
    assert it["green"] is False


def test_item_malformed_face_and_unknown_head_fail_closed():
    assert _item(face={"ran": 3})["green"] is False                 # sha missing
    assert _item(face={"sha": SHA, "ran": "x"})["green"] is False   # ran unreadable
    assert _item(head="")["green"] is False                         # HEAD query failed
    assert _item(face=[("sha", SHA)])["green"] is False             # wrong shape


def test_item_defaulted_args_field_is_empty_red():
    # the MergeCheckArgs default (old replays) must read as red, never green
    args = shared.MergeCheckArgs(ticket_id="t")
    assert args.last_green_run == {}
    assert shared.green_run_check_item(args.last_green_run, SHA)["green"] is False


# ---------------- ⑤ wiring pins ----------------

def _src(name):
    return (POC / name).read_text(encoding="utf-8")


def test_dev_lane_wires_stop_and_record_at_three_receipt_points():
    src = _src("dev_lane.py")
    assert src.count("_ki220_supply_zero_run_stop(") == 4   # 1 def + 3 call sites
    assert src.count("_ki220_record_green_run(") == 4       # 1 def + 3 call sites
    assert "KI220_ZERO_RUN_PATCH_ID" in src
    # the stop sits BEFORE the closing-run new-red check (a supply-red closing must
    # block, not void the pass into an arbitrate re-judgement spin)
    stop_at = src.index("if await self._ki220_supply_zero_run_stop(closing):")
    newred_at = src.index("_new_red = list(getattr(closing")
    assert stop_at < newred_at


def test_light_lane_wires_stop_record_and_args():
    src = _src("light_lane.py")
    assert src.count("_ki220_supply_zero_run_stop(") == 1
    assert src.count("_ki220_record_green_run(") == 1
    assert "last_green_run=dict(" in src


def test_merge_check_consumes_the_item_and_keeps_rehearsal_last():
    src = _src("agent_activities.py")
    assert "shared.green_run_check_item(args.last_green_run, _gr_sha)" in src
    insert_at = src.index("shared.green_run_check_item(args.last_green_run")
    rehearsal_at = src.index("green = all(c[\"green\"] for c in checks)", insert_at)
    assert insert_at < rehearsal_at
    assert "insert(max(len(checks) - 1, 0)" in src          # rehearsal keeps checks[-1]


# ---------------- ⑥ round budget untouched ----------------

def test_supply_round_is_exempt_not_counted():
    nr, ne, counted, note = shared.tests_round_step(
        "tests-fault", 2, 0, env_side_red=True)
    assert (nr, ne, counted) == (2, 1, False)


def test_dev_lane_round_account_keeps_supply_shape_exempt(monkeypatch):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {}
    monkeypatch.setattr(dev_lane.DevLaneWorkflow, "_tests_env_red_names",
                        lambda self, r: ([], False), raising=False)
    nr, ne, counted, note = asyncio.run(
        wf._tests_round_account(1, 0, _supply_receipt()))
    assert counted is False
    assert "not counted" in note and "supply" in note


# ---------------- ⑦ workflow helpers (stubbed facade) ----------------

class _StubWf:
    flag = True
    result = {"ok": True, "sha": SHA}

    @staticmethod
    def patched(_pid):
        return _StubWf.flag

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        res = _StubWf.result
        if isinstance(res, Exception):
            raise res
        return res


def _stub_self(meta=None, blocked=None):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = meta if meta is not None else {}
    wf._blocked_sink = blocked if blocked is not None else []

    async def _blocked(step_id, why):
        wf._blocked_sink.append((step_id, why))

    wf._blocked = _blocked
    wf.ticket_id = "t261008-24"
    wf._log = lambda *a, **k: None
    wf._now_epoch = lambda: 1234
    return wf


@pytest.fixture
def gated_true(monkeypatch):
    monkeypatch.setattr(dev_lane, "workflow", _StubWf)
    yield


@pytest.fixture
def gated_false(monkeypatch):
    monkeypatch.setattr(dev_lane, "workflow", _StubWf)
    _StubWf.flag = False
    yield
    _StubWf.flag = True


def test_stop_blocks_with_named_face_and_exits(gated_true):
    sink = []
    wf = _stub_self(blocked=sink)
    fired = asyncio.run(wf._ki220_supply_zero_run_stop(_supply_receipt()))
    assert fired is True
    step_id, why = sink[0]
    assert step_id == "run_integration_tests"
    assert why.startswith("supply-side red (zero run):")
    assert "SUPPLY_SIDE_RED" in why and "retry_qc" in why and "fix the supply" in why
    assert wf.meta["blocked_detail"]["reason_code"] == "supply_zero_run"


def test_stop_is_inert_without_patch_or_other_shapes(gated_true):
    wf = _stub_self()
    assert asyncio.run(wf._ki220_supply_zero_run_stop(_Receipt())) is False
    assert asyncio.run(wf._ki220_supply_zero_run_stop(
        _supply_receipt(failed=1))) is False
    assert wf._blocked_sink == []
    _StubWf.flag = False
    try:
        assert asyncio.run(wf._ki220_supply_zero_run_stop(_supply_receipt())) is False
    finally:
        _StubWf.flag = True
    assert wf._blocked_sink == []


def test_record_writes_face_on_green_full_round(gated_true):
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"})
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    face = wf.meta["last_green_run"]
    assert face["sha"] == SHA and face["ran"] == 4 and face["at"] == 1234


def test_record_skips_red_targeted_and_failed_head(gated_true):
    wf = _stub_self()
    asyncio.run(wf._ki220_record_green_run(_supply_receipt(), False))
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=2), True))   # targeted-only
    assert "last_green_run" not in wf.meta
    _StubWf.result = {"ok": False, "sha": "", "error": "rev-parse boom"}
    try:
        wf2 = _stub_self()
        asyncio.run(wf._ki220_record_green_run(_Receipt(ran=2), False))
        asyncio.run(wf2._ki220_record_green_run(_Receipt(ran=2), False))
    finally:
        _StubWf.result = {"ok": True, "sha": SHA}
    assert "last_green_run" not in wf.meta
    assert "last_green_run" not in wf2.meta


def test_record_legal_zero_scenarios_face(gated_true):
    wf = _stub_self()
    asyncio.run(wf._ki220_record_green_run(_Receipt(), False))
    face = wf.meta["last_green_run"]
    assert face["ran"] == 0 and face["no_scenarios"] is True


# ---------------- ⑧ write-set scoping (gen10 guard, pinned at L1) ----------------

def _mk_solo_repo(tmp_path):
    import subprocess
    root = tmp_path / "solo"
    root.mkdir(parents=True, exist_ok=True)
    def g(*a):
        subprocess.run(["git", "-C", str(root)] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q", "-b", "main")
    g("config", "user.email", "ut@example.com")
    g("config", "user.name", "ut")
    (root / "f.txt").write_text("base\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("worktree", "add", "-b", "lane/tkt", str(root / ".lane" / "tkt"))
    return root / ".lane" / "tkt"


def _stub_scope_green(monkeypatch):
    async def stub(args, sc, lane_root, multi):
        return {"checks": [{"item": "stub green", "green": True, "detail": "",
                            "id": "lane_commits"}],
                "rehearsal_green": True, "conflict_files": [],
                "merge_tree_excerpt": "", "lane_commits": 1}
    monkeypatch.setattr(dev_lane.__dict__["__name__"] and __import__("agent_activities"),
                        "_merge_check_one_scope", stub)


def test_merge_check_empty_write_set_suppresses_the_item(tmp_path, monkeypatch):
    """gen10 guard pinned at L1: an empty write set (legacy in-flight / nothing to
    verify) emits NO green-run item — the shape acceptance round 5/6 caught."""
    import agent_activities as aa
    from shared import MergeCheckArgs
    lane = _mk_solo_repo(tmp_path)

    async def stub(args, sc, lane_root, multi):
        return {"checks": [{"item": "stub green", "green": True, "detail": "",
                            "id": "lane_commits"}],
                "rehearsal_green": True, "conflict_files": [],
                "merge_tree_excerpt": "", "lane_commits": 1}
    monkeypatch.setattr(aa, "_merge_check_one_scope", stub)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t", worktree=str(lane), branch="lane/tkt",
        base_ref="basesha", write_set=[])))
    assert not [c for c in res.checks if c.get("id") == shared.GREEN_RUN_CHECK_ID]
    assert res.green is True


def test_merge_check_write_set_carries_the_item_even_without_a_face(tmp_path, monkeypatch):
    """The KI-220 incident shape (a real write set, no face) keeps the item ON and
    red zero_run — the guard must never silently narrow past the incident."""
    import agent_activities as aa
    from shared import MergeCheckArgs
    lane = _mk_solo_repo(tmp_path)

    async def stub(args, sc, lane_root, multi):
        return {"checks": [{"item": "stub green", "green": True, "detail": "",
                            "id": "lane_commits"}],
                "rehearsal_green": True, "conflict_files": [],
                "merge_tree_excerpt": "", "lane_commits": 1}
    monkeypatch.setattr(aa, "_merge_check_one_scope", stub)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t", worktree=str(lane), branch="lane/tkt",
        base_ref="basesha", write_set=["f.txt"])))
    items = [c for c in res.checks if c.get("id") == shared.GREEN_RUN_CHECK_ID]
    assert len(items) == 1 and items[0]["green"] is False
    assert items[0]["reason_code"] == "zero_run"
    assert res.green is False
