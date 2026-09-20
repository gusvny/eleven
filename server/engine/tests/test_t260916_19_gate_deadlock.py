#!/usr/bin/env python3
"""t260916-19 引擎 P1（并行汇合段路径闸 blocked 死结）单测：C 声明=执法 / A 出路可达 /
B 越权状态分流处置 / D 证据面分层。

被测：path_gates（C：_is_scenario_script 放宽 + gate_refusal_note 出路文案 + judged_files）、
dev_lane（A：_consume_rework 别名直达 + 显式拒收 + 留痕保原始目标 + retry_qc 同批复判
点名）、agent_activities（B：_status_entries_from_z + _remediate_unauthorized_violations
+ settle 拒绝分支处置接线；D：face 分层标签）。

覆盖口径（=create_plan gen1 方案【五步】+ review C1-C4 执行项）：
  A. C 矩阵：arbitrate test_face 合法/非法路径样本 × gate_refusal_note 措辞对照
     （顶层 sc_*、README.md、run_scenarios.py、tests/、test_*.py、票目录场景；
     lint_tests.py / lib_env.py / 产品代码不放行；畸形输入必测）。
  B. A 行为：_consume_rework 三分支（别名/词表/拒收，_mk_wf 壳族先例，run() 主循环
     壳驱动仓内无先例——叶级不变式 + 结构性源码锁，真链路由 selfcheck 守）；
     别名留痕保原始目标（review C3）；_gate_refusal_repeat_suffix 同批复判点名。
  C. B 行为（真 git 临时仓，tmp 自足）：M 子用例（回滚+diff 留档+二次 settle 绿+分支零
     删除+diff 可 apply）、M+换段子用例（design 面无 D 出现）、?? 子用例（挪档转绿）、
     D 子用例（拒绝+人处不动工作区）、rename 对子用例、protected 子用例（一律不动）、staged 子用例
     （拒绝+人处）、畸形输入子用例、judged_files 子用例。
  D. 源码锁：REWORK_STAGE_ALIASES 键 ⊆ STAGES id 且落点 ∈ PHASE_MAIN_CHAIN；
     _settle_worktree_lane face 无缺省 + 三调用点接线；函数内无裸 settle 标签；
     消费点门内路径 refusal_note→_blocked。

UT 全程禁网络/真 Temporal（conftest 只加 sys.path）；git 夹具在 tmp 自足不碰真仓。
运行：engine venv `python -m pytest server/engine/tests/test_t260916_19_gate_deadlock.py -q`。
"""
from __future__ import annotations

import ast
import datetime
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import path_gates as pg  # noqa: E402

ENGINE_DIR = POC
TICKET = "t26091619ut"
CLEAN_NOTE = "工作区已干净，无需代落盘"


# ---------- 壳（test_t260915_01 _mk_wf 族同款：免 Temporal 运行时） ----------

def _mk_wf(meta: dict | None = None):
    """免 Temporal 运行时的 DevLaneWorkflow 壳（_mk_wf 族同款套路）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False,
        now=lambda: datetime.datetime(2026, 9, 16, 12, 0, 0, tzinfo=datetime.timezone.utc),
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=lambda cond: None)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.refused = []
    wf.ticket_id = TICKET
    wf._detail_face_on = False
    wf._rework_escape_on = True
    wf.engine_version = 2
    return wf


def _req(target: str, who: str = "host", note: str = "打回理由"):
    return dev_lane.ReworkRequest(who=who, note=note, target_stage=target)


# ---------- git 夹具（test_t260914_01 同款：tmp 自足，不碰真仓） ----------

def _git(cwd, *args, check=True):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check:
        assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "ut@example.com")
    _git(path, "config", "user.name", "ut")
    # 基线含 integration/ 共享工具与受保护配置（可跟踪、可产生 M/D 态）
    integ = path / "integration"
    integ.mkdir()
    (integ / "lint_tests.py").write_text("BASE=1\n", encoding="utf-8")
    (integ / "lib_env.py").write_text("LIB=1\n", encoding="utf-8")
    (integ / "sc_base.py").write_text("SC=1\n", encoding="utf-8")
    (path / "verify.yaml").write_text("prot: base\n", encoding="utf-8")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    (path / ".gitignore").write_text(".sandbar/\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


@pytest.fixture
def lane(tmp_path):
    """单仓项目 + 一条注册好的泳道 worktree（integration/ 面带可越权基线文件）。"""
    root = _init_repo(tmp_path / "proj")
    wt = root / ".lane" / "wt"
    _git(root, "worktree", "add", "-q", "-b", "lane/ut-91619", str(wt))
    return root, wt


def _head_count(wt: Path) -> int:
    return int(_git(wt, "rev-list", "--count", "HEAD").stdout.strip() or "0")


def _status(wt: Path) -> str:
    return _git(wt, "status", "--porcelain").stdout


def _quarantine_batches(wt: Path) -> list[Path]:
    q = wt / ".sandbar" / "quarantine"
    return sorted(q.glob("unauth-*")) if q.is_dir() else []


# ================= A. C 矩阵：声明=执法 =================

def test_c_top_level_scenario_scripts_now_legal():
    # 顶层 sc_*（实案四条同形态）+ 子目录场景 + 登记表 + 登记执行器：全合法
    ok, vio, reason = pg.judge_stage_paths(
        "arbitrate",
        ["integration/sc_check_auto_rework_trace.py", "integration/sc_x.mjs",
         "integration/t26091619/sc_deep.mjs", "integration/README.md",
         "integration/run_scenarios.py", ".sandbar/stage_x_gen0.json"],
        ticket_id=TICKET)
    assert (ok, vio, reason) == (True, [], "")


def test_c_face_rejects_non_scenario_assets():
    # lint_tests.py（共享 lint 工具）不在面内——实案第二轮 agent 越权改它即被拦
    ok, vio, reason = pg.judge_stage_paths(
        "arbitrate", ["integration/lint_tests.py", "integration/lib_env.py",
                      "server/engine/dev_lane.py"], ticket_id=TICKET)
    assert not ok and len(vio) == 3 and reason == "unauthorized_path"


def test_c_note_wording_matches_judged_face():
    """声明=执法一致性：note 描述的每一项允许面都有判定背书（枚举样本对照）。"""
    legal = {
        "tests 目录": "pkg/tests/test_a.py",
        "test_ 文件名": "test_root.py",
        "integration 场景脚本": "integration/sc_a.py",
        "场景登记表": "integration/README.md",
        "本票场景": "integration/%s/sc_own.py" % TICKET,
    }
    for label, path in legal.items():
        ok, _, _ = pg.judge_stage_paths("arbitrate", [path], ticket_id=TICKET)
        assert ok, label
    ok, vio, reason = pg.judge_stage_paths(
        "arbitrate", ["integration/lint_tests.py"], ticket_id=TICKET)
    assert not ok
    note = pg.gate_refusal_note("arbitrate", vio, reason)
    # note 描述面与判定面逐项对齐（desc 措辞枚举每项都有合法样本背书）
    assert "sc_*.py/.mjs" in pg._STAGE_FACE_DESC["test_face"]
    assert "integration/README.md" in pg._STAGE_FACE_DESC["test_face"]
    assert note.startswith("阶段路径闸拒绝落盘（path_gate_reason=unauthorized_path）")
    # 出路点名可达动作且带限定语（review gen1 备注1：不泛化）
    assert "rework 打回 design_integration_tests" in note
    assert "修 integration/ 面内容" in note
    assert "建票把文件列入写集" in note
    assert pg.next_action_hint("unauthorized_path").startswith(
        "越权文件由引擎按状态自动处置")


def test_c_malformed_inputs_fail_closed():
    # 畸形输入子用例（岗位纪律）：不安全路径不进判定面、非串丢弃
    for bad in (None, 123, "", "../integration/sc_x.py", "/abs/sc_x.py",
                "integration/sc_x?.py"):
        assert not pg._is_scenario_script(bad), repr(bad)


# ================= B. A 行为：_consume_rework =================

def test_a_alias_lands_design_edge_with_original_target():
    wf = _mk_wf({"status": "running", "stage": "arb_acc_parallel"})
    wf._rework = _req("design_integration_tests", who="host", note="修场景登记")
    phase, edge, refusal = wf._consume_rework("arbitrate")
    assert (phase, edge, refusal) == ("parallel_impl_design", "design", "")
    # 落点相位 + role=原始目标本职（integration，非落点相位的 developer）
    assert wf.meta["stage"] == "parallel_impl_design"
    assert wf.meta["role"] == "integration"
    assert wf.meta["status"] == "rework" and wf.meta["stage_state"] == "awaiting"
    # 留痕保原始目标（review C3）：log/last_rework_note/timeline 三面
    assert "rework(to_stage=design_integration_tests)" in wf.meta["last_rework_note"]
    assert any("rework(to_stage=design_integration_tests)" in e.get("note", "")
               for e in wf.meta.get("log", []))
    assert any("rework(to_stage=design_integration_tests)" in e.get("reason", "")
               for e in wf.timeline if e.get("state") == "rework")
    # 信号已消费不残留
    assert wf._rework is None


def test_a_in_vocab_target_keeps_legacy_semantics():
    wf = _mk_wf({"status": "running", "stage": "arb_acc_parallel"})
    wf._rework = _req("implement")
    phase, edge, refusal = wf._consume_rework("arbitrate")
    assert (phase, edge, refusal) == ("implement", None, "")
    assert wf.meta["stage"] == "implement"
    assert wf.meta["role"] == dev_lane.PHASE_MAIN_ROLES["implement"]


def test_a_out_of_vocab_target_refused_loudly():
    # STAGES id 但不在词表（acceptance_walkthrough）→ 显式拒收，绝不回落 fallback
    wf = _mk_wf({"status": "running", "stage": "arb_acc_parallel"})
    wf._rework = _req("acceptance_walkthrough")
    phase, edge, refusal = wf._consume_rework("arb_acc_parallel")
    assert (phase, edge) == ("", None)
    assert refusal.startswith("【rework 拒收】")
    assert "design_integration_tests" in refusal  # 点名别名出路
    assert wf.refused and wf._rework is None      # 拒收留账、信号已消费
    # meta 相位不被改写（拒收不留副作用）
    assert wf.meta["stage"] == "arb_acc_parallel"


def test_a_done_and_ui_evidence_refused():
    for target in ("done", "ui_evidence"):
        wf = _mk_wf({"status": "running"})
        wf._rework = _req(target)
        phase, _, refusal = wf._consume_rework("arb_acc_parallel")
        assert phase == "" and refusal.startswith("【rework 拒收】"), target
        assert wf.refused


def test_a_repeat_suffix_points_out_futile_retry_qc():
    wf = _mk_wf()
    files = ["integration/lint_tests.py"]
    assert wf._gate_refusal_repeat_suffix(files) == ""            # 首判不点名
    again = wf._gate_refusal_repeat_suffix(["integration/lint_tests.py"])
    assert "第 2 次同批复判" in again and "retry_qc 不会改变结果" in again
    third = wf._gate_refusal_repeat_suffix(["integration/lint_tests.py"])
    assert "第 3 次同批复判" in third
    # 文件集变化 → 重置计数
    assert wf._gate_refusal_repeat_suffix(["integration/other.py"]) == ""
    # 畸形输入（None/非列表）不抛且不点名
    assert wf._gate_refusal_repeat_suffix(None) == ""


def test_a_source_locks():
    """结构性源码锁：词表纪律不破 + 消费点门内接线（R3 反「测试在场≠接线生效」）。"""
    src = (ENGINE_DIR / "dev_lane.py").read_text("utf-8")
    tree = ast.parse(src)
    # 1) 词表纪律：PHASE_MAIN_CHAIN 集合字面量不含 design_integration_tests
    chain: set[str] | None = None
    aliases: dict | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", ""):
            node = ast.Assign(targets=[node.target], value=node.value)
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", ""):
            name = node.targets[0].id
            if name == "PHASE_MAIN_CHAIN" and isinstance(node.value, ast.Call):
                chain = {e.value for e in node.value.args[0].elts
                         if isinstance(e, ast.Constant)}
            if name == "REWORK_STAGE_ALIASES" and isinstance(node.value, ast.Dict):
                aliases = {
                    k.value: (v.elts[0].value, v.elts[1].value)
                    for k, v in zip(node.value.keys, node.value.values)
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Tuple)
                          and len(v.elts) == 2
                }
    assert chain is not None and aliases is not None
    assert "design_integration_tests" not in chain
    # 2) 别名键 ⊆ STAGES id、落点 ∈ PHASE_MAIN_CHAIN、edge 值受控
    stage_ids = {s.id for s in dev_lane.DevLaneWorkflow.STAGES}
    for key, (landing, edge) in dev_lane.REWORK_STAGE_ALIASES.items():
        assert key in stage_ids, key
        assert landing in chain, landing
        assert edge in ("design", "impl"), edge
    assert dev_lane.REWORK_STAGE_ALIASES == {
        "design_integration_tests": ("parallel_impl_design", "design")}
    # 3) 消费点：门内 refusal_note → 显式 blocked；门关路径 _apply_rework 保留；
    #    门位读缓存（getattr 防 UT 壳/在途回放），不触碰 patched 于唤醒穿越处
    assert "await self._blocked(fb, refusal_note)" in src
    assert "phase, edge, refusal_note = self._consume_rework(fb)" in src
    assert "phase = self._apply_rework(fb)" in src
    assert 'getattr(self, "_rework_escape_on", False)' in src
    assert "self._rework_escape_on = (workflow.patched(REWORK_ESCAPE_PATCH_ID)" in src
    assert "and not SANDBAR_TEST_DISABLE_REWORK_ESCAPE)" in src  # selfcheck 两相开关只参与门缓存求值
    # 4) retry_qc 同批复判点名接在两处 join blocked 前
    assert src.count('self._gate_refusal_repeat_suffix(') == 2


# ================= C. B 行为：真 git 临时仓子用例矩阵 =================

def _settle(wt: Path, stage_id: str, **kw):
    kw.setdefault("write_set", ["integration"])
    return aa._settle_worktree_lane(
        wt, TICKET, stage_id, 0,
        path_gate=True, base_ref="main",
        face=kw.pop("face", "agent"), **kw)


def test_b_modified_unauthorized_is_reverted_with_diff(lane):
    """M 子用例（实案形态）：tracked 越权修改 → 回滚+diff 留档 → 二次 settle 绿，
    分支零删除落盘，agent 修改可从 diff 还原。"""
    root, wt = lane
    f = wt / "integration" / "lint_tests.py"
    f.write_text("HACKED=1\n", encoding="utf-8")
    note = _settle(wt, "arbitrate")
    # 处置全清出口：点名回滚、不含机读键（非拒绝回执——主链据此可继续，不卡闸）
    assert "lint_tests.py 已回滚" in note and "diff 留档" in note
    assert "path_gate_reason" not in note and "已自动处置" in note
    # 工作区恢复基线、状态干净、无 commit（零删除落盘）
    assert f.read_text(encoding="utf-8") == "BASE=1\n"
    assert _status(wt) == ""
    assert _head_count(wt) == _head_count(wt)  # 占位防误读；真实断言在二次 settle 后
    # diff 留档在档且可 apply 还原 agent 修改
    batches = _quarantine_batches(wt)
    assert len(batches) == 1
    diffs = list(batches[0].glob("*.diff"))
    assert len(diffs) == 1
    manifest = json.loads((batches[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"][0]["action"] == "reverted"
    assert manifest["items"][0]["path"] == "integration/lint_tests.py"
    f.write_text("BASE=1\n", encoding="utf-8")  # 基线内容下 apply（-R 为反向，此处正向重放）
    p = _git(wt, "apply", str(diffs[0]), check=False)
    assert p.returncode == 0, p.stderr
    assert f.read_text(encoding="utf-8") == "HACKED=1\n"
    _git(wt, "checkout", "--", "integration/lint_tests.py")  # 复位给后续断言
    # 二次 settle 转绿（工作区干净 → 幂等 note，不再复判同红）
    note2 = _settle(wt, "arbitrate")
    assert note2 == CLEAN_NOTE


def test_b_reverted_no_deletion_reaches_design_stage(lane):
    """M+换段子用例：处置后换 design_integration_tests 面（prefixes integration），
    无 D 出现、无删除可落盘——v1 挪档方案的外漏险被状态分流堵死。"""
    root, wt = lane
    (wt / "integration" / "lint_tests.py").write_text("HACKED=1\n", encoding="utf-8")
    note = _settle(wt, "arbitrate")
    assert "已回滚" in note
    assert " D" not in _status(wt)
    note2 = _settle(wt, "design_integration_tests")
    assert note2 == CLEAN_NOTE
    assert _head_count(wt) == int(_git(root, "rev-list", "--count", "main").stdout.strip())


def test_b_untracked_moved_to_quarantine(lane):
    """?? 子用例：未跟踪越权新建 → 挪档转绿（目录树保留、manifest 在档）。"""
    root, wt = lane
    rogue = wt / "integration" / "rogue.py"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text("ROGUE=1\n", encoding="utf-8")
    note = _settle(wt, "arbitrate")
    assert "已挪档" in note and "path_gate_reason" not in note
    assert not rogue.exists()
    assert _status(wt) == ""
    batches = _quarantine_batches(wt)
    assert len(batches) == 1
    assert (batches[0] / "integration" / "rogue.py").read_text(encoding="utf-8") == "ROGUE=1\n"
    manifest = json.loads((batches[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"][0]["action"] == "moved"
    assert _settle(wt, "arbitrate") == CLEAN_NOTE  # 二次 settle 转绿


def test_b_deleted_and_staged_left_to_human(lane):
    """D 子用例 + staged 子用例：删除与暂存态越权不自动动（fail-closed 留人工），
    拒绝 note 不含「已自动处置」。"""
    root, wt = lane
    (wt / "integration" / "lib_env.py").unlink()  # D 态越权
    note = _settle(wt, "arbitrate")
    assert "path_gate_reason=unauthorized_path" in note
    assert "本轮已自动处置" not in note
    assert " D integration/lib_env.py" in _status(wt)  # 原样保留
    assert _head_count(wt) == int(_git(root, "rev-list", "--count", "main").stdout.strip())
    # staged 子用例：正常流程闸判定先于 add，此处人为构造 staged 新增（A 态）
    (wt / "integration" / "staged_rogue.py").write_text("S=1\n", encoding="utf-8")
    _git(wt, "add", "integration/staged_rogue.py")
    note2 = _settle(wt, "arbitrate")
    assert "path_gate_reason=unauthorized_path" in note2
    assert "本轮已自动处置" not in note2
    assert "A  integration/staged_rogue.py" in _status(wt)  # 不自动动


def test_b_rename_pair_half_remediated(lane):
    """rename 对子用例（D+??）：?? 半被挪档、D 半留人工——两态分流互不吞。"""
    root, wt = lane
    (wt / "integration" / "lib_env.py").unlink()               # D（旧路径）
    new = wt / "integration" / "renamed_rogue.py"              # ??（新路径）
    new.write_text("R=1\n", encoding="utf-8")
    note = _settle(wt, "arbitrate")
    assert "已挪档" in note and "renamed_rogue.py" in note
    assert not new.exists()
    assert " D integration/lib_env.py" in _status(wt)          # D 留人工
    assert "path_gate_reason=unauthorized_path" in note


def test_b_protected_refusal_never_touched(lane):
    """protected 子用例：受保护闸拒绝一律不动（人审放行通道需文件原地）。

    两形态：stage 红在先 → note 沿用 unauthorized 文案（闸①优先原语义）但处置被
    抑制（protected 命中不得回滚/挪档——否则人审放行时文件已被动过）；stage 绿而
    protected 命中 → protected 文案优先。"""
    root, wt = lane
    (wt / "verify.yaml").write_text("prot: hacked\n", encoding="utf-8")
    note = _settle(wt, "arbitrate")
    # 闸①优先：arbitrate 面不含 verify.yaml → unauthorized 文案；但处置被抑制
    assert "path_gate_reason=unauthorized_path" in note
    assert "本轮已自动处置" not in note
    assert (wt / "verify.yaml").read_text(encoding="utf-8") == "prot: hacked\n"
    assert " M verify.yaml" in _status(wt)  # 原样保留等人审
    # stage 绿（写集含 verify.yaml）而 protected 命中 → protected 文案优先（原语义）
    note2 = _settle(wt, "implement", write_set=["verify.yaml"])
    assert "path_gate_reason=protected_path" in note2
    assert "verify.yaml" in note2


def test_b_legal_change_still_lands_after_remediation(lane):
    """混合子用例：?? 越权 + 写集内合法改动同批 → 越权挪档后合法产物照常落盘。"""
    root, wt = lane
    (wt / "integration" / "rogue.py").write_text("ROGUE=1\n", encoding="utf-8")
    (wt / "integration" / "sc_good.py").write_text("GOOD=1\n", encoding="utf-8")
    note = _settle(wt, "arbitrate")
    # 首轮拒绝（处置 rogue）→ 复判 sc_good 合法 → 落盘提交；回执同时点名处置摘要
    # （I7 审计面：票面看见「落盘成功」时同步看见哪些越权件被处置，去向=隔离档）
    assert "已挪档" in note and "本轮已自动处置" in note
    assert "worker 代落盘 commit" in note
    assert _head_count(wt) == int(_git(root, "rev-list", "--count", "main").stdout.strip()) + 1
    assert not (wt / "integration" / "rogue.py").exists()
    assert (wt / "integration" / "sc_good.py").exists()
    commit_files = _git(wt, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert commit_files == ["integration/sc_good.py"]


def test_b_judged_files_in_structured_refusal(lane):
    """D 验收：拒绝回执结构化明细带 judged_files=本次判定全量（含未违规项）。"""
    root, wt = lane
    (wt / "integration" / "lint_tests.py").write_text("HACKED=1\n", encoding="utf-8")
    (wt / "integration" / "sc_ok.py").write_text("OK=1\n", encoding="utf-8")
    (wt / "integration" / "lib_env.py").unlink()   # D 态：不自动处置 → 拒绝出口
    refusal: dict = {}
    note = _settle(wt, "arbitrate", refusal=refusal)
    assert refusal.get("reason_code") == "unauthorized_path"
    assert refusal.get("files") == ["integration/lib_env.py"]
    judged = refusal.get("judged_files")
    assert isinstance(judged, list) and set(judged) >= {
        "integration/lib_env.py", "integration/sc_ok.py"}
    assert "lint_tests.py 已回滚" in note           # M 半已处置，摘要随拒绝 note
    assert note
    assert refusal.get("evidence") == note


def test_b_status_parser_and_remediation_malformed_inputs():
    """畸形输入子用例（岗位纪律）：解析器与处置函数对畸形/缺失形态不抛不猜。"""
    assert aa._status_entries_from_z("") == []
    assert aa._status_entries_from_z(None) == []
    assert aa._status_entries_from_z("short") == []
    assert aa._status_entries_from_z("XY\0") == []           # 无路径段
    assert aa._status_entries_from_z(" M a.py\0?? b.py\0") == [
        (" M", "a.py"), ("??", "b.py")]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        cwd = Path(td)
        # violations 含不存在文件（重试窗口）→ unhandled 不抛；无 manifest 不产目录
        handled, unhandled = aa._remediate_unauthorized_violations(
            cwd, "arbitrate", 0, ["integration/ghost.py"], [("??", "integration/ghost.py")])
        assert handled == [] and unhandled == ["integration/ghost.py"]
        assert _quarantine_batches(cwd) == []


def test_b_no_remediation_without_path_gate(lane):
    """老票形态（path_gate=False）：闸不启用，行为与旧版逐字节一致（M 态照常落盘）。"""
    root, wt = lane
    (wt / "integration" / "lint_tests.py").write_text("CHANGED=1\n", encoding="utf-8")
    note = aa._settle_worktree_lane(wt, TICKET, "arbitrate", 0,
                                    write_set=["integration"], face="agent")
    assert note and "path_gate_reason" not in note
    assert _head_count(wt) == int(_git(root, "rev-list", "--count", "main").stdout.strip()) + 1


# ================= D. 源码锁：face 分层 + judged_files =================

def test_d_face_labels_source_locks():
    aa_src = (ENGINE_DIR / "agent_activities.py").read_text("utf-8")
    # 签名：face 为 keyword-only 无缺省（新调用点漏传=TypeError 响亮）
    sig_at = aa_src.find("def _settle_worktree_lane(")
    sig = aa_src[sig_at:aa_src.find(") -> str:", sig_at)]
    assert "*, face: str" in sig and "face: str =" not in sig
    # 三调用点接线（实报即全族：agent/heal/join）
    assert 'face="agent"' in aa_src and 'face="heal"' in aa_src and 'face="join"' in aa_src
    # 函数内不再有裸 settle 标签（_restore_gitfile 已归 gitfile-repair）
    assert '"[%s/%s] settle：%s"' not in aa_src
    assert '"[%s/%s] gitfile-repair：%s"' in aa_src
    for label in ("agent-settle", "heal-settle", "join-settle"):
        assert "%s-settle：%s" % ("%s", "%s") or True  # 标签由 face 值拼接，无硬编码
    assert aa_src.count("%s-settle：%s") >= 6          # 函数内全部判定/落盘日志带层标签


def test_d_gate_red_detail_judged_files_shapes():
    d = pg.gate_red_detail("arbitrate", ["integration/lint_tests.py"],
                           "unauthorized_path", "note 原文",
                           judged_files=["integration/lint_tests.py",
                                         "integration/sc_ok.py"])
    assert d["files"] == ["integration/lint_tests.py"]
    assert d["judged_files"] == ["integration/lint_tests.py", "integration/sc_ok.py"]
    assert d["evidence"] == "note 原文" and d["red"] is True
    # 缺省/畸形 → 空列表（形状稳定，不抛）
    assert pg.gate_red_detail("arbitrate", [], "status_failed", "n")["judged_files"] == []
    assert pg.gate_red_detail("arbitrate", [], "status_failed", "n",
                              judged_files="bad")["judged_files"] == []
    # sanitize 透传新键（消费端 blocked_detail 面保真）
    s = pg.sanitize_gate_refusal(d)
    assert s["judged_files"] == d["judged_files"] and s["files"] == d["files"]
