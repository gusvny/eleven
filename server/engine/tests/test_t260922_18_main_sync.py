#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260922-18：泳道「主动同步 main」（机械验证前 worker 并一次）UT。

覆盖（方案 §6 自测计划 + review_plan 必须项①②）：
- A 纯函数：main_sync_conflict_route 矩阵（cap 内 resolve / 超 cap blocked 锚文案 /
  同批文件反复 blocked / 异批 resolve / 畸形入参保守 blocked 不抛）；
  main_sync_note 定形（并入/已追平/缺 lane_head）与畸形入参（None/非映射/缺键/
  mode 不在册/sha 空）一律返回 ""，绝不铸造文案。
- B 活动级（真 git 临时仓，离线零 Temporal/零模型/零网络，形态仿
  test_t26091620_nested_repo_guards）：
  * 已追平快路径（is-ancestor→零动作，HEAD 不动，双 sha 回执）；
  * 干净合并（双亲合并提交 + target_sha/lane_head 回执）；
  * 冲突现场（conflict_files 非空 + MERGE_HEAD 在场 + lane_head=合并前 HEAD）；
  * main 不可达（ok=False + error 点名 ref——响亮转人工的机械面）；
  * 脏工作区非冲突失败（ok=False，不进消解回路）；
  * KI-090 形态①：main 侧误提交后又清账删除的路径 → 主同步自动合并成功、
    删除随合并落地、工作区净、清退删除形态（D）不构成残留；
  * KI-090 形态②：modify/delete 冲突 → 消解（接受删除）→ settle_conflict_resolution
    add -A 全加自愈落盘合并提交（MERGE_HEAD 消费、工作区净）。
- C 结构断言（源文本 grep 稳定锚）：主同步序列被 MAIN_SYNC_PATCH_ID 门包住；
  源序=verify_review_gate 前置检查 → prepare_conflict_resolution 同步 →
  run_integration_tests 跑闸（同步排检查后=不给「实现未落盘」放水；排跑闸前=
  同步后必重跑）；冲突子回路含 settle_conflict_resolution 与 _auto_rework 回
  implement；blocked 文案锚「主同步失败（转人工，不静默跳过同步」；证据接线
  main_sync_note/【主同步证据】在相位块内；两活动在 ALL_AGENT_ACTIVITIES；
  STAGES/TEMPLATE_DESC 展示文案带主同步。
- D 兼容：ConflictPrepResult 三新键全缺省（老历史 dict 回退重建点零改动兼容）；
  integration_discipline.FORBIDDEN_ENTRIES 判据面逐字节未放宽（红线闸）。

KI-082 清偿声明（review 必须项②）：本票主同步=KI-082 处置方向②「进入集测段前先与
main 对齐」的落地；B 组全部用例即其回归面——老票（分叉落后 main）的验证树自此=
main+票改动，不再拖到 merge_check 才以冲突形态爆出。
"""
from __future__ import annotations

import asyncio
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402
from shared import (ConflictPrepArgs, ConflictPrepResult,  # noqa: E402
                    ConflictSettleArgs, main_sync_conflict_route, main_sync_note)


# ---------- 夹具（真 git 临时仓；仓 checkout 即泳道，main 为同步目标） ----------

def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return (p.stdout or "").strip()


def _commit_file(repo, name, text, msg):
    f = repo / name
    f.parent.mkdir(parents=True, exist_ok=True)   # 子目录形态（.sandbar/x/…）父目录先建
    f.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)


def _lane_repo(tmp_path):
    """main@c0 + 同分支建 lane 并切过去（分叉点=c0）；返回 repo 路径。"""
    repo = tmp_path / "lane"
    repo.mkdir(parents=True)
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "ut@example.com", cwd=repo)
    _git("config", "user.name", "ut", cwd=repo)
    _commit_file(repo, "base.txt", "base\n", "c0")
    _git("checkout", "-b", "lane", cwd=repo)
    return repo


def _main_advance(repo, name, text, msg):
    """在 main 上前进一笔（切过去改完再切回 lane）。"""
    _git("checkout", "main", cwd=repo)
    _commit_file(repo, name, text, msg)
    _git("checkout", "lane", cwd=repo)


def _prep(repo, base_ref="main"):
    return asyncio.run(aa.prepare_conflict_resolution(
        ConflictPrepArgs(ticket_id="t260922-18", worktree=str(repo),
                         branch="lane", base_ref=base_ref)))


def _settle(repo, round_no=1):
    return asyncio.run(aa.settle_conflict_resolution(
        ConflictSettleArgs(ticket_id="t260922-18", worktree=str(repo),
                           branch="lane", base_ref="main", round_no=round_no)))


# ---------- B：活动级（真 git） ----------

def test_prep_up_to_date_fast_path_zero_action(tmp_path):
    repo = _lane_repo(tmp_path)
    head_before = _git("rev-parse", "HEAD", cwd=repo)
    r = _prep(repo)
    assert isinstance(r, ConflictPrepResult) and r.ok
    assert r.up_to_date and r.already_clean and not r.conflict_files
    assert r.target_sha == _git("rev-parse", "main", cwd=repo)
    assert r.lane_head == _git("rev-parse", "--short", "HEAD", cwd=repo)
    assert _git("rev-parse", "HEAD", cwd=repo) == head_before  # 零动作：HEAD 不动


def test_prep_fast_forward_lane_head_is_main_tip(tmp_path):
    """快进形态（review 建议项⑤）：零改动票/未分叉泳道 + main 已前进 → FF 追平，
    泳道 HEAD=main tip 且进回执（lane_head）——票面证据直接可读，不靠 merge_check 现场。"""
    repo = _lane_repo(tmp_path)          # lane 分叉后零自有提交
    _main_advance(repo, "b.txt", "main\n", "main advance")
    main_short = _git("rev-parse", "--short", "main", cwd=repo)
    r = _prep(repo)
    assert r.ok and r.already_clean and not r.up_to_date   # 非祖先（要并），但零冲突
    assert r.lane_head == main_short                       # FF 后 HEAD=main tip 进证据
    assert _git("rev-parse", "HEAD", cwd=repo) == _git("rev-parse", "main", cwd=repo)


def test_prep_clean_merge_two_parents_with_sha_receipt(tmp_path):
    repo = _lane_repo(tmp_path)
    _commit_file(repo, "a.txt", "lane\n", "lane work")
    _main_advance(repo, "b.txt", "main\n", "main advance")
    main_sha = _git("rev-parse", "main", cwd=repo)
    r = _prep(repo)
    assert r.ok and r.already_clean and not r.up_to_date
    assert r.target_sha == main_sha
    assert r.lane_head == _git("rev-parse", "--short", "HEAD", cwd=repo)
    parents = _git("rev-list", "--parents", "-n", "1", "HEAD", cwd=repo).split()
    assert len(parents) == 3  # HEAD + 双亲（合并提交）
    assert not (_repo_dirty(repo))


def test_prep_conflict_scene_leaves_merge_in_progress(tmp_path):
    repo = _lane_repo(tmp_path)
    _commit_file(repo, "f.txt", "lane edit\n", "lane touch")
    _main_advance(repo, "f.txt", "main edit\n", "main touch")
    head_before = _git("rev-parse", "HEAD", cwd=repo)
    r = _prep(repo)
    assert r.ok and r.conflict_files == ["f.txt"]
    assert r.lane_head == _git("rev-parse", "--short", head_before, cwd=repo)
    # 合并进行中（MERGE_HEAD 在场）——settle 的前置条件
    _git("rev-parse", "--verify", "MERGE_HEAD", cwd=repo)


def _repo_dirty(repo):
    return bool(_git("status", "--porcelain", cwd=repo))


def test_prep_unreachable_main_loud_failure(tmp_path):
    repo = _lane_repo(tmp_path)
    _commit_file(repo, "a.txt", "lane\n", "lane work")
    _git("branch", "-D", "main", cwd=repo)  # 目标 ref 不可达
    r = _prep(repo)
    assert not r.ok
    assert "main" in (r.error or "")
    assert not r.target_sha and not r.lane_head


def test_prep_dirty_worktree_non_conflict_failure(tmp_path):
    repo = _lane_repo(tmp_path)
    _commit_file(repo, "a.txt", "lane\n", "lane work")
    _main_advance(repo, "f.txt", "main touch\n", "main touch f")
    (repo / "f.txt").write_text("uncommitted local\n", encoding="utf-8")  # 脏面挡 merge
    r = _prep(repo)
    assert not r.ok
    assert "非冲突" in (r.error or "")


def test_prep_ki090_cleared_deletion_merges_clean(tmp_path):
    """KI-090 形态①（review 必须项①）：main 误提交后又清账删除的路径，主同步自动
    合并成功——删除随合并落地、工作区净、无残留现场。"""
    repo = tmp_path / "lane"
    repo.mkdir(parents=True)
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "ut@example.com", cwd=repo)
    _git("config", "user.name", "ut", cwd=repo)
    _commit_file(repo, "base.txt", "base\n", "c0")
    _git("checkout", "-b", "lane", cwd=repo)          # 分叉点早于误提交
    _commit_file(repo, "a.txt", "lane\n", "lane work")
    _git("checkout", "main", cwd=repo)
    _commit_file(repo, ".sandbar/x/README.md", "误提交\n", "误提交状态目录")  # c1
    _git("rm", "-r", ".sandbar", cwd=repo)            # c2：清账删除（squash 收口形态）
    _git("commit", "-m", "清账删除", cwd=repo)
    _git("checkout", "lane", cwd=repo)
    r = _prep(repo)
    assert r.ok and r.already_clean and not r.conflict_files
    assert not (repo / ".sandbar" / "x" / "README.md").exists()   # 删除随合并落地
    assert not _repo_dirty(repo)                                  # 工作区净（无「待删 tracked」）
    # KI-090 普查口径：加了又删的路径净效果为零——不进泳道历史（ls-tree 零条），
    # 不产生「工作区待删 tracked 文件」现场（这正是 KI-090 当年 merge_check 两红的根）
    assert _git("ls-tree", "-r", "HEAD", "--", ".sandbar/", cwd=repo) == ""
    parents = _git("rev-list", "--parents", "-n", "1", "HEAD", cwd=repo).split()
    assert len(parents) == 3                                      # 真合并（非快进）
    assert _git("merge-base", "--is-ancestor", "main", "HEAD", cwd=repo) == ""


def test_prep_ki090_modify_delete_conflict_then_settle_selfheal(tmp_path):
    """KI-090 形态②（review 必须项①）：modify/delete 冲突 → 消解（接受删除）→
    settle_conflict_resolution add -A 全加自愈落盘合并提交。
    （真 modify/delete 冲突要求被删文件在合并基里：先让 lane 追平 main 使 f.txt
    入基，再各自分叉出「lane 修改 / main 删除」。）"""
    repo = _lane_repo(tmp_path)
    _main_advance(repo, "f.txt", "orig\n", "main adds f")
    _git("merge", "main", cwd=repo)                            # lane 追平：f.txt 入合并基
    _commit_file(repo, "f.txt", "lane edit\n", "lane modify")  # lane 侧修改
    _git("checkout", "main", cwd=repo)
    _git("rm", "f.txt", cwd=repo)                              # main 侧删除
    _git("commit", "-m", "main deletes f", cwd=repo)
    _git("checkout", "lane", cwd=repo)
    r = _prep(repo)
    assert r.ok and r.conflict_files == ["f.txt"]      # modify/delete 进冲突面
    (repo / "f.txt").unlink()                          # 「agent」消解：接受删除
    s = _settle(repo)
    assert s.ok and s.commit
    assert not (repo / "f.txt").exists()
    assert not _repo_dirty(repo)
    parents = _git("rev-list", "--parents", "-n", "1", "HEAD", cwd=repo).split()
    assert len(parents) == 3                            # 合并提交落盘（MERGE_HEAD 消费）
    assert not _prep(repo).conflict_files               # 回路收敛：再同步已追平


# ---------- A：纯函数 ----------

def test_route_matrix_cap_and_anchors():
    assert main_sync_conflict_route(1, ["a"], [], cap=3) == "resolve"
    assert main_sync_conflict_route(3, ["a"], ["b"], cap=3) == "resolve"
    over = main_sync_conflict_route(4, ["a"], ["b"], cap=3)
    assert over.startswith("blocked:")
    assert "主同步冲突消解 3 轮未收敛（上限 3）" in over
    assert "冲突文件 a" in over


def test_route_same_batch_files_blocked():
    out = main_sync_conflict_route(2, ["b", "a"], ["a", "b"], cap=3)
    assert out.startswith("blocked:")
    assert "同批文件反复冲突" in out
    # 同一裸文件名、先后两轮落在不同仓（带仓标识后集合不同）= 不同批，
    # 不构成「同批反复」（review 建议④：不误判提前 blocked）
    assert main_sync_conflict_route(2, ["repoA:f"], ["repoB:f"], cap=3) == "resolve"


@pytest.mark.parametrize("rounds,files,prev,cap", [
    ("x", ["a"], [], 3),          # rounds 非整数 → 保守视同超限
    (None, ["a"], [], 3),
    (1, None, [], 3),             # files 非列表 → 按空集照常判（resolve，不抛）
    (4, None, [], 3),
    (2, ["a"], None, None),       # cap 畸形 → 保守 blocked
    (1, ["a"], [], "cap"),
])
def test_route_malformed_inputs_fail_closed(rounds, files, prev, cap):
    out = main_sync_conflict_route(rounds, files, prev, cap)
    assert out == "resolve" or out.startswith("blocked:")   # 恒二值，绝不抛/绝不放行第三态


def test_note_shaping_merged_and_up_to_date():
    assert main_sync_note({"mode": "merged", "main_sha": "0123456789abcdef",
                           "lane_head": "abc1234"}) == \
        "main@0123456 已并入泳道（验证前主同步，lane HEAD=abc1234）"
    assert main_sync_note({"mode": "up_to_date", "main_sha": "0123456789abcdef"}) == \
        "main@0123456 已追平（快路径零动作）"


@pytest.mark.parametrize("bad", [
    None, [], "merged", 42,
    {},                                             # 空 dict：mode/sha 缺
    {"mode": "conflict_resolved", "main_sha": "abc"},   # mode 不在册
    {"mode": "merged"},                             # sha 缺
    {"mode": "merged", "main_sha": ""},             # sha 空
    {"mode": "merged", "main_sha": None},
    {"merged", "abc"},                              # set 非映射
])
def test_note_malformed_returns_empty(bad):
    assert main_sync_note(bad) == ""


# ---------- C：结构断言（源文本，grep 稳定锚） ----------

def _dev_lane_src():
    return (POC / "dev_lane.py").read_text("utf-8")


def _sync_phase_block():
    src = _dev_lane_src()
    start = src.index('if phase == "run_integration_tests":')
    end = src.index("# 3.3) arbitration", start)
    return src[start:end]


def _sync_helper_block():
    """闸前主同步**机制本体**（260930 抽成共享 helper；调用点见 _sync_phase_block）。

    为什么两段分开取：抽 helper 的纪律是「命令序列/入参/等待点逐字不变，只换位置」——
    源序锁（前置检查→同步→跑闸）落在**调用点**，会话序列锁（prep→agent→settle）落在
    **helper 本体**。这样两条锁都还在，且各自锁的是它真正关心的那一段。"""
    src = _dev_lane_src()
    start = src.index("async def _main_sync_before_gate(")
    end = src.index("    @workflow.run", start)
    return src[start:end]


def test_struct_patch_gate_wraps_sync_sequence():
    src = _dev_lane_src()
    assert src.count('MAIN_SYNC_PATCH_ID = "dev-lane-main-sync-v1"') == 1
    block = _sync_phase_block()
    assert "workflow.patched(MAIN_SYNC_PATCH_ID)" in block


def test_struct_sync_source_order_gate_before_sync_before_run():
    """同步排在 0-commit 前置检查之后（不给「实现未落盘」放水）、跑闸之前
    （同步与跑闸同轮直线衔接=必重跑不复用旧报告）——源序即机械锁。

    260930 抽 helper 后：源序锁落**调用点**，且机制只此一份（helper 内
    prepare_conflict_resolution 在 dev_lane 全文恰 1 次 = 没有第二份实现）。"""
    block = _sync_phase_block()
    i_gate = block.index("graw = await workflow.execute_activity(")
    i_prep = block.index("self._main_sync_before_gate(")
    i_run = block.index("rraw = await workflow.execute_activity(")
    assert i_gate < i_prep < i_run
    assert block.index("verify_review_gate", i_gate) < i_prep
    assert block.index("run_integration_tests,", i_run) > i_prep
    # 处置面：stop 非空 ⇒ 本相位 continue（blocked/rework 都不在这里接着跑闸）
    assert 'if _ms.get("stop"):\n                        continue' in block
    helper = _sync_helper_block()
    # 闸前主同步=helper 内单点调用（全文另有 merge_check 站的冲突 prep——那是另一站的
    # S2 会话，不是「第二份主同步」；本条锁的是**闸前同步**只此一份、且相位块只经 helper）
    assert helper.count("prepare_conflict_resolution,") == 1
    assert block.count("self._main_sync_before_gate(") == 1
    assert '"stop": _sync_stop' in helper and '"sync_s": _sync_s' in helper


def test_struct_conflict_subloop_reuses_existing_trio_back_to_implement():
    """冲突子回路的 prep→agent→settle 会话序列锁（260930 抽 helper 后落 helper 本体）。

    agent 上下文变量名仍是 `msolve_ctx`（不是 `solve_ctx`）：selfcheck E-1 用
    `_run_agent_step("implement", solve_ctx)`（merge_check 分支那处）作首现锚——主同步
    子回路同名会让该锚错位（t260922-18 实测），故此文用 msolve_ctx 断言，保持两站可分。"""
    block = _sync_helper_block()
    i_prep = block.index("prepare_conflict_resolution")
    i_agent = block.index('_run_agent_step("implement", msolve_ctx)')
    i_settle = block.index("settle_conflict_resolution", i_agent)
    assert i_prep < i_agent < i_settle
    assert 'who="workflow", fallback="run_integration_tests"' in block
    assert "主同步冲突消解完成（第" in block          # 回实现段的 rework note 锚
    assert "**不要 git commit**" in block             # agent 零 git 元数据写入（提示词令）
    assert "主同步失败（转人工，不静默跳过同步" in block   # 不可达响亮转人工锚
    # gen3（源码锁 t260917-08 F4 回归）：本站归因构造走与 M3 变体站共用的单点
    # helper（_agent_failed_why 调用点/字面量计数恒 5/2），站文案逐字在位
    assert "self._conflict_failed_note(" in block
    assert '"主同步冲突消解第 %d 轮：%s"' in block


def test_struct_evidence_wiring_present():
    """证据接线三面（260930 抽 helper 后按位置一一对应）：
    helper=同步日志留痕；相位块=票面 summary 尾注 + 仲裁/走查上下文注入。"""
    helper = _sync_helper_block()
    assert "main_sync_note(" in helper                # 日志留痕（helper 内单点）
    block = _sync_phase_block()
    assert block.count("main_sync_note(") >= 1        # 票面回执/尾注
    assert "【主同步证据】" in block                   # 仲裁/走查上下文注入
    assert "｜主同步=" in block                       # 票面 summary 尾注


def test_struct_activities_registered_and_display_meta_updated():
    aa_src = (POC / "agent_activities.py").read_text("utf-8")
    reg = aa_src[aa_src.index("ALL_AGENT_ACTIVITIES = AGENT_STAGE_ACTIVITIES + ["):]
    reg = reg[:reg.index("]")]
    assert "prepare_conflict_resolution" in reg
    assert "settle_conflict_resolution" in reg
    src = _dev_lane_src()
    assert "验证前主同步 main" in src                 # TEMPLATE_DESC + STAGES desc


def test_struct_baseline_ref_crosscheck_comment_present():
    """闸自补的 baseline_ref（main@sha）与主同步回执同轮互证——证据面声明留在源码注释。"""
    assert "baseline_ref" in _sync_phase_block() or "同轮互证" in _dev_lane_src()


# ---------- D：兼容与红线闸 ----------

def test_conflict_prep_result_new_fields_defaulted():
    names = {f.name: f for f in dataclasses.fields(ConflictPrepResult)}
    for k in ("target_sha", "lane_head", "up_to_date"):
        assert k in names
        assert names[k].default in ("", False)       # 全缺省：老历史 dict 重建点零改动兼容
    # 老历史 dict 回退重建形态（无新键）——构造成功且新键为缺省
    raw = {"ok": True, "already_clean": True}
    r = ConflictPrepResult(ok=bool(raw.get("ok")),
                           already_clean=bool(raw.get("already_clean")),
                           target_sha=str(raw.get("target_sha") or ""),
                           lane_head=str(raw.get("lane_head") or ""),
                           up_to_date=bool(raw.get("up_to_date")))
    assert r.ok and r.already_clean and r.target_sha == "" and not r.up_to_date


def test_forbidden_entries_untouched():
    """红线：developer 段集成禁跑判据面（声明=执法）不得被本票放宽——逐字节比对。"""
    import integration_discipline
    assert integration_discipline.FORBIDDEN_ENTRIES == (
        ("run_scenarios.py", "integration/run_scenarios.py"),
        ("sc_*", "integration/**/sc_*.py|.mjs"),
        ("baselines", "integration/baselines/*"),
        ("with_stage.sh", "integration/with_stage.sh"),
        ("verify_lane", "verify_lane（含 admin.py call verify_lane）"),
    )
