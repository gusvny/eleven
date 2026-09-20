"""t260916-28 泳道 .dsh 缺件静默失效单测：候选链回落 / 预检拒绝 / 六使用点分流 / 门语义。

覆盖口径（=create_plan 方案 v3 验收映射；review 附条件意见 C1/C2/C3 采办）：
  A. helper 层候选链：src 存在→拷贝含 symlink（U1）；DSH_HOME 在但缺 profile→回落
     真实 home（U2，t260916-26 形态主用例）；候选全空→helper 静默跳过（不抛=直调夹具
     契约）+ 预检拒绝文案可辨（U3）；目标已存在→不覆盖（U4，既有语义零回归）。
  B. 畸形输入必测（岗位纪律）：DSH_HOME 指向文件/空串/未设/与 home 重合、空 cmd、
     非 dsh 前缀桩命令、gate_refusal files 非列表、None 回执（U5/U10）。
  C. settings 档位：src 缺→settings_missing 拒绝；src 在→拷贝 + _pin_default_model
     不回归（U6）；profile 缺而 settings 在→profile_missing 优先（U6）。
  D. 触发条件：桩命令（首词非 dsh）→预检不触发（U7，recorder 场景零波及的机械证明）；
     stub 短路先于预检接线（U8 源码锁）。
  E. workflow 六使用点分流：判定纯函数矩阵（U10）+ blocked 落点行为（U11，_mk_wf 壳族
     先例，t260915-01 同款）+ 门语义两态（U12，FakeMemoGate 三条 SDK 语义镜像）+
     结构性源码锁（U13：六处同形、先于计数/done 赋值；锁结构形态不锁行号——C2/C3
     采办；附 i02 钉复述，钉实位=integration/t260901-21/i02_spawn_wiring.py:46）。

降级声明（t260915-01 C-4 同款口径）：run() 主循环壳驱动仓内无先例——「不进格式纠正
计数 / 不触发打回 implement / 不置 done 假完成」以 U11 叶级行为 + U13 源码锁机械等价，
真链路由 L2 场景（integration/t260916-28，真起 workflow 三分支）兜底；U9 activity 级桩测
降级为纯函数主面（U3/U5/U6/U7）+ L2 覆盖（activity.logger/heartbeat 的 Temporal 活动
上下文依赖在 UT 进程内不可靠，不硬造）。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：`server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260916_28_lane_dsh_profile.py -q`。
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities  # noqa: E402
import dev_lane  # noqa: E402
import path_gates  # noqa: E402

PROFILE = "sandbar-headless"
NOW_DT = datetime.datetime(2026, 9, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _patch_home(monkeypatch, real: Path) -> None:
    # Path.home 是 pathlib.Path 的 classmethod；必须 patch 在 Path 本尊（ PosixPath
    # 子类不承接 Path.home 的调用解析），staticmethod 形态对齐 classmethod 槽位。
    monkeypatch.setattr(Path, "home", staticmethod(lambda: real))


# ---------- 壳与夹具 ----------

async def _wake_immediately(cond) -> None:  # wait_condition 桩：恒醒
    return None


def _mk_wf(detail_face: bool = True, meta: dict | None = None):
    """免 Temporal 运行时的 DevLaneWorkflow 壳（_mk_wf 族同款套路，t260915-01 先例）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.LANE_DSH_BLOCK_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t260916-28-ut"
    wf._detail_face_on = detail_face
    wf.engine_version = 2
    return wf


def _mk_src_home(root: Path, name: str, *, profile: bool = True,
                 settings: bool = False, profile_name: str = PROFILE) -> Path:
    home = root / name
    home.mkdir(parents=True, exist_ok=True)
    if profile:
        pdir = home / "profiles" / profile_name
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "marker.txt").write_text("src", encoding="utf-8")
        (pdir / "real.txt").write_text("R", encoding="utf-8")
        (pdir / "link.txt").symlink_to(pdir / "real.txt")
    if settings:
        (home / "settings.yaml").write_text("providers: {}\n", encoding="utf-8")
    return home


def _mk_lane(root: Path, name: str = "lane-dsh", *, with_profile: bool = False,
             with_settings: bool = False, profile_name: str = PROFILE) -> Path:
    lane_dsh = root / name
    lane_dsh.mkdir(parents=True, exist_ok=True)
    if with_profile:
        pdir = lane_dsh / "profiles" / profile_name
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "marker.txt").write_text("dst", encoding="utf-8")
    if with_settings:
        (lane_dsh / "settings.yaml").write_text("providers: {}\n", encoding="utf-8")
    return lane_dsh


def _res(status: str = "failed", refusal=None, summary: str = ""):
    return SimpleNamespace(status=status, gate_refusal=refusal, summary=summary)


PROFILE_REFUSAL = {"reason_code": "lane_dsh_profile_missing",
                   "files": ["/lane/.dsh"], "candidates": ["/h1", "/h2"],
                   "next_action": "补 profile 后 retry_qc 自愈",
                   "evidence": "泳道 .dsh 缺 sandbar-headless profile（t260916-28）"}


# ---------- A. helper 层候选链 ----------

def test_u1_src_exists_copies_with_symlinks(tmp_path, monkeypatch):
    src = _mk_src_home(tmp_path, "src-home")
    monkeypatch.setenv("DSH_HOME", str(src))
    lane_dsh = _mk_lane(tmp_path)
    agent_activities._copy_profile(lane_dsh)
    dst = lane_dsh / "profiles" / PROFILE
    assert (dst / "marker.txt").read_text("utf-8") == "src"
    assert os.path.islink(str(dst / "link.txt"))  # symlinks=True 保留


def test_u2_dsh_home_without_profile_falls_back_to_real_home(tmp_path, monkeypatch):
    # t260916-26 形态主用例：DSH_HOME 在（目录存在）但里面没有 profile。
    empty = tmp_path / "empty-home"
    empty.mkdir()
    monkeypatch.setenv("DSH_HOME", str(empty))
    real = tmp_path / "real-home"
    real.mkdir()
    _mk_src_home(real, ".dsh")  # 真实 home 的 .dsh 才是候选链第二项
    _patch_home(monkeypatch, real)
    lane_dsh = _mk_lane(tmp_path)
    agent_activities._copy_profile(lane_dsh)
    assert (lane_dsh / "profiles" / PROFILE / "marker.txt").is_file()
    # 候选链单源：同一函数被 settings 拷贝消费（回落语义一致）
    _mk_src_home(real, ".dsh", profile=False, settings=True)
    agent_activities._copy_settings(lane_dsh)
    assert (lane_dsh / "settings.yaml").is_file()


def test_u3_all_candidates_empty_helper_silent_preflight_loud(tmp_path, monkeypatch, caplog):
    empty1 = tmp_path / "h1"
    empty1.mkdir()
    monkeypatch.setenv("DSH_HOME", str(empty1))
    empty2 = tmp_path / "h2"
    empty2.mkdir()
    _patch_home(monkeypatch, empty2)
    lane_dsh = _mk_lane(tmp_path)
    # helper 不抛（直调夹具契约：sc_it02 S4 / selfcheck G），dst 无 profile
    with caplog.at_level(logging.WARNING):
        agent_activities._copy_profile(lane_dsh)
    assert not (lane_dsh / "profiles").exists()
    agent_activities._copy_settings(lane_dsh)
    assert not (lane_dsh / "settings.yaml").exists()
    # 响亮面=预检拒绝：文案三要素（泳道 .dsh 缺 / 解析路径 / 候选链）
    cmd = ["dsh", "--profile", PROFILE]
    refusal = agent_activities._lane_dsh_preflight(
        cmd, lane_dsh, agent_activities._dsh_home_candidates())
    assert refusal is not None
    assert refusal["reason_code"] == "lane_dsh_profile_missing"
    ev = refusal["evidence"]
    assert "泳道 .dsh 缺" in ev and PROFILE in ev
    assert str(empty1) in ev and str(empty2) in ev          # 候选链逐候选在文案
    assert str(lane_dsh / "profiles" / PROFILE) in ev       # 解析出的 lane 路径
    assert "retry_qc" in refusal["next_action"]
    # warning 留痕（caplog 经 root logger 传播；temporalio logger 不可达时此腿降级为
    # 行为断言，上面的行为断言已独立成立）
    assert any("候选链" in r.message or "sandbar-headless" in r.getMessage()
               for r in caplog.records)


def test_u4_existing_dst_profile_never_overwritten(tmp_path, monkeypatch):
    src = _mk_src_home(tmp_path, "src-home")
    monkeypatch.setenv("DSH_HOME", str(src))
    lane_dsh = _mk_lane(tmp_path, with_profile=True)  # dst 已有 marker=dst
    agent_activities._copy_profile(lane_dsh)
    dst_marker = lane_dsh / "profiles" / PROFILE / "marker.txt"
    assert dst_marker.read_text("utf-8") == "dst"  # 既有语义零回归：不覆盖
    assert not (lane_dsh / "profiles" / PROFILE / "real.txt").exists()


# ---------- B/C. 预检纯函数：畸形输入与档位 ----------

def test_u5_malformed_inputs(tmp_path, monkeypatch):
    # DSH_HOME 指向文件（非目录）→ 候选链收缩到真实 home
    bogus = tmp_path / "bogus-file"
    bogus.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(bogus))
    home = tmp_path / "home"
    home.mkdir()
    _patch_home(monkeypatch, home)
    cands = agent_activities._dsh_home_candidates()
    assert cands == [home / ".dsh"]  # 第二候选=真实 home 的 .dsh
    monkeypatch.setenv("DSH_HOME", "")          # 空串 → 跳过
    assert agent_activities._dsh_home_candidates() == [home / ".dsh"]
    monkeypatch.delenv("DSH_HOME", raising=False)  # 未设 → 同
    assert agent_activities._dsh_home_candidates() == [home / ".dsh"]
    monkeypatch.setenv("DSH_HOME", str(home))   # 与 home 重合 → 去重
    assert agent_activities._dsh_home_candidates() == [home, home / ".dsh"]
    # 桩命令 / 空 cmd → 预检不触发
    lane_dsh = _mk_lane(tmp_path)
    assert agent_activities._lane_dsh_preflight(["python3", "stub.py"], lane_dsh, cands) is None
    assert agent_activities._lane_dsh_preflight([], lane_dsh, cands) is None
    # 无 --profile → 缺省 profile 名
    refusal = agent_activities._lane_dsh_preflight(["dsh"], lane_dsh, cands)
    assert refusal is not None and refusal["profile"] == PROFILE
    # --profile 自定义名：lane 有 custom profile+settings（自洽）→ 放行
    lane2 = _mk_lane(tmp_path, "lane-custom", with_profile=True,
                     with_settings=True, profile_name="custom")
    assert agent_activities._lane_dsh_preflight(["dsh", "--profile", "custom"],
                                                lane2, cands) is None
    # gate_refusal files 非列表 → sanitize 降级可辨（C7 校形）
    out = path_gates.sanitize_gate_refusal(
        {"reason_code": "lane_dsh_profile_missing", "files": "not-a-list"})
    assert out is not None and out["reason_code"] == "gate_refusal_malformed"
    # 合法明细原样透传（reason_code 保留）
    out2 = path_gates.sanitize_gate_refusal(dict(PROFILE_REFUSAL))
    assert out2["reason_code"] == "lane_dsh_profile_missing"
    assert out2["next_action"] == PROFILE_REFUSAL["next_action"]


def test_u6_settings_gate_and_copy_pin_regression(tmp_path, monkeypatch):
    # lane 有 profile、缺 settings → settings_missing（profile 在场时不误报 profile）
    src = _mk_src_home(tmp_path, "src-home")
    monkeypatch.setenv("DSH_HOME", str(src))
    lane_dsh = _mk_lane(tmp_path, with_profile=True)
    cands = agent_activities._dsh_home_candidates()
    refusal = agent_activities._lane_dsh_preflight(["dsh"], lane_dsh, cands)
    assert refusal is not None
    assert refusal["reason_code"] == "lane_dsh_settings_missing"
    # lane 缺 profile、有 settings → profile_missing 优先（主因）
    lane2 = _mk_lane(tmp_path, "lane-settings", with_settings=True)
    refusal2 = agent_activities._lane_dsh_preflight(["dsh"], lane2, cands)
    assert refusal2["reason_code"] == "lane_dsh_profile_missing"
    # src settings 在 → 拷贝；route pin 写 user 层（既有语义零回归）
    home = tmp_path / "home-s"
    home.mkdir()
    _mk_src_home(home, ".dsh", profile=False, settings=True)
    _patch_home(monkeypatch, home)
    agent_activities._copy_settings(lane_dsh)
    agent_activities._pin_default_model(
        lane_dsh, {"provider": "kimi-coding", "model": "m1"})
    txt = (lane_dsh / "settings.yaml").read_text("utf-8")
    assert "agent-default-model:" in txt and "kimi-coding" in txt


def test_u7_stub_command_never_triggers_preflight(tmp_path):
    # recorder/selftest 桩（首词非 dsh）即使泳道残缺也零波及
    lane_dsh = _mk_lane(tmp_path)  # 全缺
    assert agent_activities._lane_dsh_preflight(
        ["python3", "/tmp/recorder.py", "x"], lane_dsh, []) is None
    assert agent_activities._lane_dsh_preflight(
        ["/bin/sh", "-c", "x"], lane_dsh, []) is None


# ---------- D/E. workflow 六使用点分流 ----------

SRC_AA = (POC / "agent_activities.py").read_text("utf-8")
SRC_DL = (POC / "dev_lane.py").read_text("utf-8")


def test_u8_stub_short_circuit_precedes_preflight():
    # stub 分支（SANDBAR_AGENT_STUB=1）在源码序上先于预检接线（结构性锁，不锁行号）
    assert SRC_AA.index("SANDBAR_AGENT_STUB") < SRC_AA.index("_lane_dsh_preflight(")


def test_u10_predicate_matrix():
    wf = _mk_wf()
    assert wf._lane_dsh_refusal(_res("failed", dict(PROFILE_REFUSAL))) is True
    assert wf._lane_dsh_refusal(
        _res("failed", {"reason_code": "lane_dsh_settings_missing"})) is True
    assert wf._lane_dsh_refusal(_res("ok", dict(PROFILE_REFUSAL))) is False
    assert wf._lane_dsh_refusal(_res("failed", None)) is False
    assert wf._lane_dsh_refusal(_res("failed", "not-a-dict")) is False
    assert wf._lane_dsh_refusal(_res("failed", {})) is False
    assert wf._lane_dsh_refusal(_res("failed", {"reason_code": ""})) is False
    assert wf._lane_dsh_refusal(
        _res("failed", {"reason_code": "gate_refusal_malformed"})) is False
    assert wf._lane_dsh_refusal(
        _res("failed", {"reason_code": "path_gate_denied"})) is False
    assert wf._lane_dsh_refusal(None) is False  # 畸形输入：None 回执不炸


def test_u11_block_agent_failed_lands_blocked_and_pinned():
    wf = _mk_wf(True)
    res = _res("failed", dict(PROFILE_REFUSAL),
               # 裸人话（activity 侧 summary 不带前缀——前缀由落点统一拼，防双前缀）
               summary="泳道 .dsh 缺 sandbar-headless profile（t260916-28）")
    # 真实时序：_run_agent_step 内 pin（写 blocked_detail）→ 站点分支 blocked →
    # 唤醒后引擎既有语义（t260915-01 ①）清空当前态两字段——blocked 期间票面可读、
    # 醒后清空；可观测面=timeline 条目 reason。
    wf._pin_agent_refusal(res)
    assert (wf.meta.get("blocked_detail") or {}).get(
        "reason_code") == "lane_dsh_profile_missing"
    asyncio.run(wf._block_agent_failed("arbitrate", res))
    blocked = [e for e in wf.timeline if e.get("state") == "blocked"]
    assert len(blocked) == 1 and blocked[0]["stage"] == "arbitrate"
    assert blocked[0]["reason"].startswith(
        "agent 报失败：泳道 .dsh 缺 sandbar-headless profile")
    # 唤醒后清空（既有①语义不被本票破坏；blocked 期间的可见性由上方 pin 时序保证）
    assert wf.meta.get("blocked_reason") == ""
    assert wf.meta.get("blocked_detail") is None


def test_u11b_block_agent_failed_all_lane_dsh_step_ids():
    # 六使用点的 step_id 全集：blocked 条目按站点名落（helper 单点，站名由调用方给）
    for step_id in ("implement", "design_integration_tests",
                    "arbitrate", "acceptance_walkthrough"):
        wf = _mk_wf(True)
        res = _res("failed", dict(PROFILE_REFUSAL), summary="泳道 .dsh 缺件")
        asyncio.run(wf._block_agent_failed(step_id, res))
        blocked = [e for e in wf.timeline if e.get("state") == "blocked"]
        assert len(blocked) == 1 and blocked[0]["stage"] == step_id


def test_u11c_pin_gate_off_writes_nothing():
    # 门关（_detail_face_on=False）→ pin 零写（在途重放态逐字不变，t260915-01 ①同款）
    wf = _mk_wf(False, meta={"blocked_reason": "旧原因"})
    res = _res("failed", dict(PROFILE_REFUSAL), summary="x")
    wf._pin_agent_refusal(res)
    assert "blocked_detail" not in wf.meta
    assert wf.meta["blocked_reason"] == "旧原因"


class FakeMemoGate:
    """逐语义镜像 temporalio SDK workflow_patch（t260915-01 C9 三条：memo 命中即返回；
    首评 `not is_replaying or id in notified` 并固化；use=True 发 marker 且 id 进
    notified）。"""

    def __init__(self, is_replaying: bool):
        self.memo: dict = {}
        self.notified: set = set()
        self.is_replaying = is_replaying

    def patched(self, pid: str) -> bool:
        if pid in self.memo:
            return self.memo[pid]
        use = (not self.is_replaying) or (pid in self.notified)
        self.memo[pid] = use
        if use:
            self.notified.add(pid)
        return use


def test_u12_gate_semantics_two_states():
    # parked 旧实例重放：新门无 marker → False（走旧分支，命令序与旧代码一致）
    parked = FakeMemoGate(is_replaying=True)
    assert parked.patched(dev_lane.LANE_DSH_BLOCK_PATCH_ID) is False
    # live 实例：首评 True 并固化；同 id 二次求值 memo 命中
    live = FakeMemoGate(is_replaying=False)
    assert live.patched(dev_lane.LANE_DSH_BLOCK_PATCH_ID) is True
    assert live.patched(dev_lane.LANE_DSH_BLOCK_PATCH_ID) is True
    assert dev_lane.LANE_DSH_BLOCK_PATCH_ID in live.notified


# ---------- U13 结构性源码锁（六使用点；锁结构形态不锁行号） ----------

def _all(hay: str, needle: str) -> list:
    out, i = [], 0
    while True:
        i = hay.find(needle, i)
        if i < 0:
            return out
        out.append(i)
        i += len(needle)


def test_u13_constant_count_and_i02_pin():
    assert 'LANE_DSH_BLOCK_PATCH_ID = "dev-lane-lane-dsh-block-v1"' in SRC_DL
    # 六使用点（注释里不得出现该调用文本——计数即证据）
    assert SRC_DL.count("workflow.patched(LANE_DSH_BLOCK_PATCH_ID)") == 6
    # i02 钉复述（钉实位=integration/t260901-21/i02_spawn_wiring.py:46；两钉同源同值）
    # t260916-22：巡检 inspect 段 run_inspection_inspect 新增第 4 调用点（1 定义 + 4 调用
    # =5），i02 普查已同步 4→5——本钉随改（merge 双方全保留时的连带更新）。
    assert SRC_AA.count("_prepare_agent_spawn(") == 5


def _branch_head(src: str, anchor: int) -> int:
    # 门分支头（workflow.patched 行）在 blocked 锚之前——窗口须从分支头起才含完整同形块
    return src.rindex("workflow.patched(LANE_DSH_BLOCK_PATCH_ID)", 0, anchor)


def test_u13_site1_serial_arbitrate_before_format_counter():
    a = SRC_DL.index('_block_agent_failed("arbitrate", res)')
    head = _branch_head(SRC_DL, a)
    until = SRC_DL.index("arb_format_rounds += 1", a)
    window = SRC_DL[head:until]
    assert "self._lane_dsh_refusal(res)" in window
    assert "verdict = parse_arbitration_summary(res.summary)" in window


def test_u13_site2_parallel_mainline_resets_fork_bookkeeping():
    a = SRC_DL.index('_block_agent_failed("arbitrate", arb_res)')
    head = _branch_head(SRC_DL, a)
    until = SRC_DL.index("verdict = parse_arbitration_summary(arb_res.summary)", a)
    window = SRC_DL[head:until]
    assert "self._lane_dsh_refusal(arb_res)" in window
    assert "arb_done = False" in window and "arb_res = None" in window


def test_u13_site3_format_correction_rerun_before_done_assignment():
    a = SRC_DL.index('_block_agent_failed("arbitrate", rraw)')
    head = _branch_head(SRC_DL, a)
    until = SRC_DL.index("arb_done = True", a)
    window = SRC_DL[head:until]
    assert "self._lane_dsh_refusal(rraw)" in window


def test_u13_site4_serial_acceptance_before_sendback_counter():
    a = SRC_DL.index('_block_agent_failed("acceptance_walkthrough", res)')
    head = _branch_head(SRC_DL, a)
    until = SRC_DL.index("acc_rounds += 1", a)
    window = SRC_DL[head:until]
    assert "self._lane_dsh_refusal(res)" in window


def test_u13_site5_parallel_acceptance_resets_walkthrough_bookkeeping():
    a = SRC_DL.index('_block_agent_failed("acceptance_walkthrough", acc_res)')
    head = _branch_head(SRC_DL, a)
    until = SRC_DL.index("acc_rounds += 1", a)
    window = SRC_DL[head:until]
    assert "self._lane_dsh_refusal(acc_res)" in window
    assert "acc_done = False" in window and "acc_res = None" in window


def test_u13_site6_impl_join_same_loop_as_exception_branch_before_done():
    # C2 采办：门 6 与 isinstance(r, Exception) 同循环并列、先于任何 done 赋值；
    # 窗口内含同形簿记（剔边+break+置 failed），不含 done 赋值/_finish。
    exc = SRC_DL.index("if isinstance(r, Exception):")
    a = SRC_DL.index('_block_agent_failed(name, r)', exc)
    head = _branch_head(SRC_DL, a)
    until = SRC_DL.index("impl_done = True", a)
    window = SRC_DL[head:until]
    assert "self._lane_dsh_refusal(r)" in window
    assert "set_parallel_stages(" in window and "break" in window
    assert "failed = True" in window
    assert "_finish(" not in window and "_handoff(" not in window
    assert "impl_done = True" not in window and "design_done = True" not in window
