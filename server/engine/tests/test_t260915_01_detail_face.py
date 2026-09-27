"""t260915-01 详情数据面单测：①blocked 当前态清空 ②结构化红灯明细 ③gen/phase 维度。

覆盖口径（=create_plan gen1 方案【4】+ review_plan C-4/C-5 执行项）：
  A. ①门两态：门 True→_blocked wake 后 blocked_reason==''/blocked_detail is None 且
     timeline 的 blocked 历史条目仍在（审计留痕机械断言）；门 False（在途重放态）→
     字段原样；_enter 清 detail（清点②）；无键防御。
  B. ②结构化明细：path_gates 三纯函数矩阵（含畸形输入必测——岗位说明书纪律）、
     _apply_settle_note 挂载/反用例、三个 _pin 消费点、dataclass 缺省（重放安全）。
  C. ③gen/phase：set_parallel_stages 三态（C5 写死）、_mark/_handoff 门两态、
     snapshot.gens 拷贝+门关无键、@query 内零 workflow.patched（R1 源码锁）。
  D. 门语义：FakeMemoGate 镜像 temporalio SDK 三条语义（_patches_memoized 首评固化/
     首评 not is_replaying or id in notified/use_patch marker 入 history）——C9 取舍：
     与真门漂移风险由 server/engine/replay_check.py 真回放兜底（docker 在场时执行）。
  E. 接线/结构性源码锁（R3 反「测试在场≠接线生效」KI-046/049）。

C-4 降级声明：两条「真路径壳驱动」（merge_check 冲突自动消解、仲裁格式纠正轮）按
review_plan C-4 预留口径降级为「叶级不变式组合矩阵（B5-B7 写点 × A1/A1b 清点的
组合断言）+ 结构性源码锁（A4 三调用点紧邻 _blocked）」——_mk_wf 壳族仓内先例只驱动
叶方法，run() 主循环壳驱动需桩全部活动面（仓内无先例、成本/收益不成比例）；真链路
由 L2 场景（integration/t260915-01，直调 settle）与既有 ki061/pause 场景守。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：主树 venv `.../engine/.venv/bin/python -m pytest server/engine/tests/test_t260915_01_detail_face.py -q`。
"""
from __future__ import annotations

import asyncio
import datetime
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import path_gates  # noqa: E402
import shared  # noqa: E402
from shared import SettleLaneResult, StageResult  # noqa: E402

NOW_DT = datetime.datetime(2026, 9, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)


# ---------- 壳与门 ----------

async def _wake_immediately(cond) -> None:  # wait_condition 桩：恒醒（retry_qc/rework 两出路等价覆盖）
    return None


def _mk_wf(detail_face: bool = True, meta: dict | None = None,
           gens: dict | None = None):
    """免 Temporal 运行时的 DevLaneWorkflow 壳（_mk_wf 族同款套路）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = dict(gens or {})
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t-ut"
    wf._detail_face_on = detail_face
    wf.engine_version = 2
    return wf


class FakeMemoGate:
    """逐语义镜像 temporalio SDK workflow_patch（C9 声明的三条：
    memo 命中即返回；首评 `not is_replaying or id in notified` 并固化；
    use_patch=True 发 marker 命令且 marker 事件重放时 id 进 notified）。"""

    def __init__(self, is_replaying: bool):
        self.memo: dict = {}
        self.notified: set = set()
        self.is_replaying = is_replaying
        self.commands: list = []

    def patched(self, pid: str) -> bool:
        if pid in self.memo:
            return self.memo[pid]
        use = (not self.is_replaying) or (pid in self.notified)
        self.memo[pid] = use
        if use:
            self.commands.append(pid)
            self.notified.add(pid)
        return use


# ---------- A. ① blocked 当前态清空 ----------

def test_blocked_wake_clears_fields_gate_on_and_keeps_timeline():
    wf = _mk_wf(True, meta={"blocked_reason": "旧原因", "blocked_detail": {"reason_code": "x"}})
    asyncio.run(dev_lane.DevLaneWorkflow._blocked(wf, "implement", "本轮受阻原因"))
    assert wf.meta["blocked_reason"] == ""
    assert wf.meta["blocked_detail"] is None
    # 审计留痕机械断言：timeline 的 blocked 历史条目仍在（_mark 不动）
    blocked_entries = [e for e in wf.timeline if e.get("state") == "blocked"]
    assert len(blocked_entries) == 1
    assert blocked_entries[0]["stage"] == "implement"
    assert blocked_entries[0]["reason"] == "本轮受阻原因"


def test_blocked_wake_gate_off_entry_write_unchanged_never_cleared():
    wf = _mk_wf(False, meta={"blocked_reason": "旧原因", "blocked_detail": {"reason_code": "x"}})
    asyncio.run(dev_lane.DevLaneWorkflow._blocked(wf, "implement", "本轮受阻原因"))
    # 门关：入口写点（ki048 锁定的无条件写）照旧写 why，wake 后不清=旧分支逐字
    assert wf.meta["blocked_reason"] == "本轮受阻原因"
    assert wf.meta["blocked_detail"] == {"reason_code": "x"}


def test_blocked_wake_missing_keys_no_crash():
    wf = _mk_wf(True)  # meta 无两键
    asyncio.run(dev_lane.DevLaneWorkflow._blocked(wf, "merge", "原因"))
    assert wf.meta["blocked_reason"] == ""
    assert wf.meta["blocked_detail"] is None


def test_enter_clears_detail_gate_on_only():
    wf = _mk_wf(True, meta={"blocked_detail": {"reason_code": "x"}, "write_set": []})
    dev_lane.DevLaneWorkflow._enter(wf, "implement")
    assert wf.meta["blocked_detail"] is None           # 清点②：非 blocked 推进恒空
    wf2 = _mk_wf(False, meta={"blocked_detail": {"reason_code": "x"}, "write_set": []})
    wf2.meta["stage"] = "review_plan"
    dev_lane.DevLaneWorkflow._enter(wf2, "implement")
    assert wf2.meta["blocked_detail"] == {"reason_code": "x"}  # 门关：逐字不变


def test_leaf_invariant_matrix_write_points_x_clear_points():
    """C-4 降级口径的叶级不变式组合矩阵：写点（B5/B6/B7）×清点（清点①/②）组合下
    「非 blocked 期 blocked_detail 恒空」成立。"""
    refusal = {"check_id": "path_gate@implement", "reason_code": "unauthorized_path",
               "files": ["server/x.py"]}
    for detail_on in (True, False):
        wf = _mk_wf(detail_on)
        wf._pin_agent_refusal(StageResult(status="failed", summary="拒绝", gate_refusal=dict(refusal)))
        pinned = wf.meta.get("blocked_detail")
        dev_lane.DevLaneWorkflow._enter(wf, "implement")     # 清点②
        assert wf.meta.get("blocked_detail") is None
        asyncio.run(dev_lane.DevLaneWorkflow._blocked(wf, "implement", "why"))  # 清点①
        assert wf.meta.get("blocked_reason") == ("" if detail_on else "why")
        if detail_on:
            assert pinned == refusal or (isinstance(pinned, dict) and pinned["reason_code"] == "unauthorized_path")


# ---------- B. ② 结构化红灯明细 ----------

def test_gate_red_detail_full_files_and_note_verbatim():
    files = ["a.py", "b.py", "c.py", "d.py", "e.py"]  # >3 项：结构化面不截断
    note = "阶段路径闸拒绝落盘（path_gate_reason=unauthorized_path）：……"
    d = path_gates.gate_red_detail("implement", files, "unauthorized_path", note)
    assert d["check_id"] == "path_gate@implement"
    assert d["item"] == "段×允许面路径闸"
    assert d["red"] is True
    assert d["files"] == files                         # 全量逐字，不经 _fmt_files cap
    assert d["evidence"] == note                       # 与 worker 日志同一字符串
    assert isinstance(d["next_action"], str) and d["next_action"]


def test_gate_red_detail_protected_and_malformed_inputs():
    d = path_gates.gate_red_detail("arbitrate", ["x"], "protected_path", "note")
    assert d["item"] == "受保护路径闸" and d["reason_code"] == "protected_path"
    for bad in (None, 42, "a.py", {"f": 1}):           # 畸形 violations → files=[] 不抛
        assert path_gates.gate_red_detail("implement", bad, "unauthorized_path", "n")["files"] == []
    assert path_gates.gate_red_detail("implement", [1, None, "ok.py"], "unauthorized_path", "n")["files"] == ["ok.py"]
    assert path_gates.gate_red_detail("implement", [], "", "n")["reason_code"] == "gate_refusal_unknown"


def test_next_action_hint_known_and_unknown():
    assert path_gates.next_action_hint("protected_path") != path_gates.next_action_hint("status_failed")
    assert path_gates.next_action_hint("no_such_code")   # 未知码也给可读兜底
    assert path_gates.next_action_hint("") == path_gates.next_action_hint("no_such_code")


def test_sanitize_gate_refusal_matrix():
    assert path_gates.sanitize_gate_refusal(None) is None
    assert path_gates.sanitize_gate_refusal("x") is None
    assert path_gates.sanitize_gate_refusal(42) is None
    assert path_gates.sanitize_gate_refusal({"files": []}) is None          # 缺 reason_code
    assert path_gates.sanitize_gate_refusal({"reason_code": "  "}) is None  # 空白码
    ok = path_gates.sanitize_gate_refusal({"reason_code": "protected_path", "files": ["a"], "extra": 1})
    assert ok == {"reason_code": "protected_path", "files": ["a"], "extra": 1}
    assert path_gates.sanitize_gate_refusal({"reason_code": "r"})["files"] == []  # 缺 files→[]
    degraded = path_gates.sanitize_gate_refusal({"reason_code": "r", "files": "a.py"})
    assert degraded["reason_code"] == "gate_refusal_malformed" and degraded["files"] == []
    assert path_gates.sanitize_gate_refusal({"reason_code": "r", "files": [1, "a", None]})["files"] == ["1", "a"]


def test_apply_settle_note_mounts_refusal_and_negative_leg():
    note = "阶段路径闸拒绝落盘（path_gate_reason=unauthorized_path）：……"
    ref = {"check_id": "path_gate@implement", "reason_code": "unauthorized_path", "files": ["x"]}
    from agent_activities import _apply_settle_note
    res = StageResult(status="ok", summary="s")
    out = _apply_settle_note(res, note, refusal=dict(ref))
    assert out.status == "failed" and out.summary == note
    assert out.gate_refusal == ref
    res2 = StageResult(status="ok", summary="s")
    out2 = _apply_settle_note(res2, note)              # 缺省 None：不挂（老直调逐字）
    assert out2.status == "failed" and out2.gate_refusal is None
    res3 = StageResult(status="ok", summary="s")
    out3 = _apply_settle_note(res3, "普通 note")       # 反用例：非闸拒绝不挂
    assert out3.status == "ok" and out3.gate_refusal is None
    assert "[worker settle] 普通 note" in out3.evidence
    res4 = StageResult(status="ok", summary="s")
    out4 = _apply_settle_note(res4, "")                # note 空：原样
    assert out4.status == "ok" and out4.evidence == ""


def test_pin_agent_refusal_gate_and_shape():
    wf = _mk_wf(True)
    wf._pin_agent_refusal(StageResult(status="failed", summary="拒绝",
                                      gate_refusal={"reason_code": "unauthorized_path", "files": ["x"]}))
    assert wf.meta["blocked_detail"]["reason_code"] == "unauthorized_path"
    wf2 = _mk_wf(True)
    wf2._pin_agent_refusal(StageResult(status="failed", summary="失败"))       # 无 refusal→不写
    assert "blocked_detail" not in wf2.meta
    wf2._pin_agent_refusal(StageResult(status="ok", summary="好",
                                       gate_refusal={"reason_code": "r"}))     # ok→不写
    assert "blocked_detail" not in wf2.meta
    wf3 = _mk_wf(True)
    wf3._pin_agent_refusal(StageResult(status="failed", summary="失败",
                                       gate_refusal="畸形"))                   # 畸形→sanitize None→不写
    assert "blocked_detail" not in wf3.meta
    wf4 = _mk_wf(False)
    wf4._pin_agent_refusal(StageResult(status="failed", summary="失败",
                                       gate_refusal={"reason_code": "r"}))     # 门关→零写
    assert "blocked_detail" not in wf4.meta


def test_pin_settle_refusal_tolerates_missing_attr():
    wf = _mk_wf(True)
    wf._pin_settle_refusal(SettleLaneResult(note="n", error="e"))   # 老回执形状（无键）
    assert "blocked_detail" not in wf.meta
    wf._pin_settle_refusal(SettleLaneResult(note="n", error="e",
                                            gate_refusal={"reason_code": "protected_path", "files": ["docs/x"]}))
    assert wf.meta["blocked_detail"]["reason_code"] == "protected_path"


def test_pin_merge_red_detail_lists_all_reds_with_class_and_disposition():
    """260927 宿主实报⑥可见性半边：**全部**红项逐条结构化（红类 + 各自处置），
    且既有键（首红那套）逐字节不变——blocked_detail 被 6 个测试文件 41 处引用，
    「只加不改」是硬约束。"""
    checks = [
        {"item": "泳道分支有 commit", "green": True, "detail": "2 个 commit", "id": "lane_commits"},
        {"item": "工作区干净", "green": False, "detail": "未提交：a.py", "id": "worktree_clean",
         "reason_code": "worktree_dirty", "files": ["a.py"], "next_action": "提交或暂存"},
        {"item": "泳道内 verify_lane code 绿灯", "green": False, "detail": "red=1", "id": "verify_lane_code",
         "reason_code": "verify_red", "next_action": "按红灯项修复后 retry_qc"},
        {"item": "merge 预演无冲突", "green": False, "detail": "冲突：x.py", "id": "merge_rehearsal",
         "reason_code": "merge_conflict", "files": ["x.py"], "next_action": "自动打回 implement 消解"},
    ]
    wf = _mk_wf(True)
    wf._pin_merge_red_detail(checks, disposition="本轮=非冲突红 → blocked 等人")
    d = wf.meta["blocked_detail"]
    # 既有键（首红）逐字节不变
    assert d["check_id"] == "worktree_clean" and d["reason_code"] == "worktree_dirty"
    assert d["files"] == ["a.py"] and d["next_action"] == "提交或暂存" and d["red"] is True
    # 加法键：逐条红 + 红类 + 处置
    assert [r["check_id"] for r in d["reds"]] == ["worktree_clean", "verify_lane_code", "merge_rehearsal"]
    assert [r["class"] for r in d["reds"]] == ["human", "human", "auto_conflict"]
    assert d["reds"][0]["next_action"] == "提交或暂存"
    assert d["reds"][0]["files"] == ["a.py"] and d["reds"][2]["files"] == ["x.py"]
    assert d["disposition"] == "本轮=非冲突红 → blocked 等人"
    # 无红项：不塞空 reds（老形状零变化）
    wf2 = _mk_wf(True)
    wf2._pin_merge_red_detail([{"item": "x", "green": True, "id": "ok"}], ["c1"])
    assert "reds" not in wf2.meta["blocked_detail"]
    assert wf2.meta["blocked_detail"]["reason_code"] == "merge_conflict"


def test_pin_merge_red_detail_first_red_and_fallback():
    checks = [
        {"item": "泳道分支有 commit", "green": True, "detail": "2 个 commit", "id": "lane_commits"},
        {"item": "工作区干净", "green": False, "detail": "未提交：a.py", "id": "worktree_clean",
         "reason_code": "worktree_dirty", "files": ["a.py", "b.py"],
         "next_action": "收回写集内"},
    ]
    wf = _mk_wf(True)
    wf._pin_merge_red_detail(checks)
    d = wf.meta["blocked_detail"]
    assert d["check_id"] == "worktree_clean" and d["reason_code"] == "worktree_dirty"
    assert d["files"] == ["a.py", "b.py"] and d["evidence"] == "未提交：a.py"
    assert d["next_action"] == "收回写集内" and d["red"] is True
    # 无红项+conflict_files 兜底（conflict 类转人工）
    wf2 = _mk_wf(True)
    wf2._pin_merge_red_detail([{"item": "x", "green": True, "id": "ok"}], ["c1", "c2"])
    assert wf2.meta["blocked_detail"]["reason_code"] == "merge_conflict"
    assert wf2.meta["blocked_detail"]["files"] == ["c1", "c2"]
    # 无红项无 fallback → 零写
    wf3 = _mk_wf(True)
    wf3._pin_merge_red_detail([{"item": "x", "green": True}])
    assert "blocked_detail" not in wf3.meta
    # 门关 → 零写
    wf4 = _mk_wf(False)
    wf4._pin_merge_red_detail(checks)
    assert "blocked_detail" not in wf4.meta
    # checks 畸形（非列表）→ 不抛
    wf5 = _mk_wf(True)
    wf5._pin_merge_red_detail("垃圾")
    assert "blocked_detail" not in wf5.meta


def test_pin_merge_red_detail_inner_gate_refusal_wins():
    checks = [{"item": "工作区干净", "green": False, "detail": "…[auto-settle] 拒绝",
               "id": "worktree_clean",
               "gate_refusal": {"reason_code": "protected_path", "files": ["verify.yaml"]}}]
    wf = _mk_wf(True)
    wf._pin_merge_red_detail(checks)
    assert wf.meta["blocked_detail"]["reason_code"] == "protected_path"


def test_result_dataclasses_default_none_replay_safe():
    assert StageResult().gate_refusal is None
    assert SettleLaneResult().gate_refusal is None


# ---------- C. ③ gen/phase ----------

def test_set_parallel_stages_phase_three_states():
    meta = {"stage": "design_integration_tests"}
    dev_lane.set_parallel_stages(meta, ["implement", "design_integration_tests"],
                                 phase="parallel_impl_design")
    assert meta["parallel_stages"] == ["implement", "design_integration_tests"]
    assert meta["parallel_phase"] == "parallel_impl_design"
    # 摘失败边：phase 缺省 → 相位保持现值（C5）
    dev_lane.set_parallel_stages(meta, ["design_integration_tests"])
    assert meta["parallel_phase"] == "parallel_impl_design"
    assert meta["parallel_stages"] == ["design_integration_tests"]
    # 离场：两键同删
    dev_lane.set_parallel_stages(meta, [])
    assert "parallel_stages" not in meta and "parallel_phase" not in meta
    # 缺省 phase 且此前无相位：不产生键
    meta2 = {}
    dev_lane.set_parallel_stages(meta2, ["implement"])
    assert "parallel_phase" not in meta2


def test_mark_gate_on_adds_gen_and_phase_gate_off_verbatim_four_keys():
    wf = _mk_wf(True, gens={"implement": 2}, meta={"parallel_phase": "arb_acc_parallel"})
    dev_lane.DevLaneWorkflow._mark(wf, "implement", "running", "进入本步（第 2 次）")
    e = wf.timeline[-1]
    assert e["gen"] == 2 and e["phase"] == "arb_acc_parallel"
    assert set(e) == {"at", "stage", "state", "reason", "gen", "phase"}
    wf2 = _mk_wf(True, gens={"implement": 1})          # 无相位 → 无 phase 键
    dev_lane.DevLaneWorkflow._mark(wf2, "implement", "done", "x")
    assert set(wf2.timeline[-1]) == {"at", "stage", "state", "reason", "gen"}
    wf3 = _mk_wf(False, gens={"implement": 2})         # 门关：旧 4 键逐字
    dev_lane.DevLaneWorkflow._mark(wf3, "implement", "running", "r")
    assert set(wf3.timeline[-1]) == {"at", "stage", "state", "reason"}


def test_handoff_carries_gen_gate_on_only():
    wf = _mk_wf(True, gens={"implement": 3})
    dev_lane.DevLaneWorkflow._handoff(wf, "implement", "实现完成", artifacts=["a"])
    h = wf.meta["handoffs"][-1]
    assert h["gen"] == 3 and h["summary"] == "实现完成"
    wf2 = _mk_wf(False)
    dev_lane.DevLaneWorkflow._handoff(wf2, "implement", "x")
    assert "gen" not in wf2.meta["handoffs"][-1]


def test_snapshot_gates_gens_copy_and_missing_attr_safe():
    wf = _mk_wf(True, gens={"implement": 2, "arbitrate": 1})
    wf.signatures, wf.gate_runs, wf.refused, wf.human_context = {}, [], [], {}
    snap = dev_lane.DevLaneWorkflow.snapshot(wf)
    assert snap["gens"] == {"implement": 2, "arbitrate": 1}
    assert snap["gens"] is not wf._gens                # 拷贝：查询不改内部态
    wf2 = _mk_wf(False, gens={"implement": 1})
    wf2.signatures, wf2.gate_runs, wf2.refused, wf2.human_context = {}, [], [], {}
    snap2 = dev_lane.DevLaneWorkflow.snapshot(wf2)
    assert "gens" not in snap2                         # 门关：无新段
    wf3 = object.__new__(dev_lane.DevLaneWorkflow)     # UT 壳未置位：getattr 防御不炸
    wf3.ticket_id = "t-ut"
    wf3._gens = {}
    wf3.meta = {"blocked_reason": "", "blocked_detail": None}
    wf3.timeline = []
    wf3.signatures, wf3.gate_runs, wf3.refused, wf3.human_context = {}, [], [], {}
    wf3.results = {}
    wf3._retry_token = 0
    snap3 = dev_lane.DevLaneWorkflow.snapshot(wf3)
    assert "gens" not in snap3


# ---------- D. 门语义（FakeMemoGate） ----------

def test_gate_inflight_replay_false_frozen_zero_marker():
    gate = FakeMemoGate(is_replaying=True)
    assert gate.patched(dev_lane.DETAIL_FACE_PATCH_ID) is False
    assert gate.commands == []                          # 零 marker 命令（旧分支逐字）
    gate.is_replaying = False                           # 后续 live 段不翻案（memo 固化）
    assert gate.patched(dev_lane.DETAIL_FACE_PATCH_ID) is False


def test_gate_new_instance_true_and_replay_stable():
    gate = FakeMemoGate(is_replaying=False)
    assert gate.patched(dev_lane.DETAIL_FACE_PATCH_ID) is True
    assert gate.commands == [dev_lane.DETAIL_FACE_PATCH_ID]
    replay = FakeMemoGate(is_replaying=True)
    replay.notified.update(gate.notified)               # marker 已入 history
    assert replay.patched(dev_lane.DETAIL_FACE_PATCH_ID) is True


def test_init_evaluates_gate_cache_bit():
    """_init 的门缓存位：门开→True；门关（patched 恒 False）→False（在途重放形态）。"""
    for flag, expected in ((True, True), (False, False)):
        dev_lane.workflow = SimpleNamespace(
            patched=lambda pid, _flag=flag: _flag,
            now=lambda: NOW_DT,
            logger=SimpleNamespace(info=lambda *a, **k: None))
        wf = object.__new__(dev_lane.DevLaneWorkflow)
        wf.timeline = []
        wf._gens = {}
        wf.engine_version = 2
        inp = SimpleNamespace(
            ticket_id="t-ut", template_id="tpl", project="p", title="t", lane="",
            workspace="", worktree="", branch="", base_ref="", proposal_id="",
            book_path="", epic="", write_set=[], deliverables=[], spec="",
            user_request="u", body="u", created=0, acceptance_extra=[],
            no_file_changes=False, path_gate=False, repo_worktrees=[])
        dev_lane.DevLaneWorkflow._init(wf, inp)
        assert wf._detail_face_on is expected


# ---------- E. 接线/结构性源码锁（R3/KI-046/049 反「测试在场≠接线生效」） ----------

def _read(name: str) -> str:
    return (POC / name).read_text("utf-8")


def test_source_query_has_no_patched_call():
    src = _read("dev_lane.py")
    fn = src.split("def snapshot(self)", 1)[1].split("def sign_face", 1)[0]
    assert "patched" not in fn, "R1：@query 内禁止 workflow.patched（SDK 只读约束）"


def test_source_wiring_locks_apply_settle_note_chain():
    aa = _read("agent_activities.py")
    # 三参形状（缺省 None=老直调逐字）
    assert "def _apply_settle_note(res: StageResult, note: str," in aa
    assert "refusal: Optional[Dict[str, Any]] = None" in aa
    assert aa.count("_apply_settle_note(") >= 5         # 定义 + 四调用点
    # t260916-19 ④：_settle_with_gate 内透传带 face="agent"（ refusal 后置逗号）
    assert "refusal=refusal,\n        face=\"agent\")" in aa
    for token in ("refusal=refusal2)", "refusal=refusal3)", "refusal=refusal4)"):
        assert token in aa, f"调用点缺接线：{token}"
    assert aa.count("_settle_worktree_lane(") >= 4
    assert "refusal=sc_refusal,\n                                        face=\"join\")" in aa  # settle_lane 收集口
    assert "refusal=heal_refusal,\n                        face=\"heal\")" in aa              # merge_check 自愈
    assert "gate_refusal=(dict(sc_refusal) or None)" in aa
    assert "res.gate_refusal = dict(refusal)" in aa      # 挂载点


def test_source_wiring_locks_dev_lane_consumers():
    src = _read("dev_lane.py")
    assert "import path_gates" in src                    # C-2：imports 块内
    assert "self._pin_agent_refusal(res)" in src         # A2 单点覆盖
    assert "self._pin_settle_refusal(s)" in src          # A3 两 join 点
    assert src.count('self._pin_settle_refusal(s)') == 2
    assert "gate_refusal=raw.get(\"gate_refusal\")" in src  # dict 重建透传
    assert "self._detail_face_on = workflow.patched(DETAIL_FACE_PATCH_ID)" in src  # 唯一求值点（契约锚形状）
    assert src.count("workflow.patched(DETAIL_FACE_PATCH_ID)") == 1
    assert 'self.meta["blocked_detail"] = None' in src   # 清点①②
    assert src.count('self.meta["blocked_detail"] = None') == 2


def test_source_a4_pins_adjacent_to_blocked():
    """C-4 结构性断言：三个 _pin_merge_red_detail 调用点全部紧邻（<8 行）其后首个
    _blocked(\"merge_check\"——「写点必然进 blocked」的机械形状锁。"""
    src = _read("dev_lane.py")
    lines = src.splitlines()
    pin_lines = [i for i, ln in enumerate(lines) if "_pin_merge_red_detail(" in ln and "def " not in ln]
    assert len(pin_lines) == 3
    for i in pin_lines:
        window = "\n".join(lines[i:i + 8])
        assert 'self._blocked("merge_check"' in window or 'await self._blocked(' in window, \
            "A4 写点未紧邻 _blocked（违反 R2 生命周期口径）"
