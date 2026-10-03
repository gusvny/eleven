#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261002-10：merge_check 重跑（retry_qc 在 merge_check 唤醒）前重并 main 的 UT。

事故（KI-189 / t261001-20）：main 上的红在票过闸之后被修掉（20:27，f546329）；
票在 20:31 retry_qc 重跑 merge_check 仍撞**修复前**的同一红（泳道最后一次并 main
停在 19:40）——主同步此前只存在于闸轮相位，merge_check 相位入口没有同步点，
开票之后落进 main 的修复永远到不了停在 merge_check 的票。

覆盖：
- A 活动级（真 git 临时仓，离线零 Temporal/零模型；形态仿 test_t260922_18_main_sync）：
  主同步活动（prepare_conflict_resolution，workflow 层两个机器段共用的那条唯一实现）
  把「票停在 merge_check 期间落进 main 的修复」在一轮同步内带进泳道树（合并提交、
  修复是 lane HEAD 的祖先、工作区净、回执带 target_sha/lane_head）；第二次调用=已追平
  快路径零动作幂等；冲突/不可达=具名错误（点名校验失败面），绝不裸 not green。
- B 结构锚（源文本 grep 稳定）：dev-lane 与 light-lane 的 merge_check 相位块都在
  merge_check 活动**之前**调共享 helper、各自在 patch 门内（在飞老历史回放=逐字旧行为）；
  helper 带 step_id 参数（缺省=闸相位原值，闸调用点零变化）；两个车道的 STAGES
  merge_check 文案与 ticket.py retry_qc 帮助文本都写明「重跑前重并 main」——
  文档与行为在**两个机器段**一致（票面验收③）。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
from shared import ConflictPrepArgs, ConflictPrepResult  # noqa: E402

DL_SRC = (POC / "dev_lane.py").read_text("utf-8")
LL_SRC = (POC / "light_lane.py").read_text("utf-8")
TK_SRC = (REPO / "server" / "tools" / "ticket.py").read_text("utf-8")


# ---------- 夹具（真 git 临时仓：origin=main 侧，lane worktree=停在 merge_check 的票） ----------

def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return (p.stdout or "").strip()


def _commit_file(repo, name, text, msg):
    f = repo / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)


def _parked_lane(tmp_path):
    """origin(main) + lane worktree，分叉点=当前 main HEAD（票刚过闸的时点）。
    返回 (origin, lane)——此后 main 上落修复=「票过闸后 main 的修复」。"""
    origin = tmp_path / "origin"
    origin.mkdir(parents=True)
    _git("init", "-b", "main", cwd=origin)
    _git("config", "user.email", "ut@example.com", cwd=origin)
    _git("config", "user.name", "ut", cwd=origin)
    _commit_file(origin, "base.txt", "base\n", "c0")
    _git("branch", "lane", cwd=origin)
    lane = tmp_path / "lane"
    _git("worktree", "add", str(lane), "lane", cwd=origin)
    return origin, lane


def _prep(worktree, base_ref="main"):
    return asyncio.run(aa.prepare_conflict_resolution(
        ConflictPrepArgs(ticket_id="t261002-10", worktree=str(worktree),
                         branch="lane", base_ref=base_ref)))


# ---------- A：活动级（真 git） ----------

def test_resync_brings_post_gate_main_fix_into_parked_lane(tmp_path):
    """验收①：票停在 merge_check 期间落进 main 的修复，一轮同步即进泳道树。"""
    origin, lane = _parked_lane(tmp_path)
    _commit_file(origin, "fix.txt", "the fix\n", "main-side fix after the gate")
    fix_sha = _git("rev-parse", "main", cwd=origin)
    r = _prep(lane)
    assert isinstance(r, ConflictPrepResult) and r.ok
    assert not r.up_to_date and r.conflict_files == []
    assert _git("merge-base", "--is-ancestor", fix_sha, "HEAD", cwd=lane) is not None
    assert _git("status", "--porcelain", cwd=lane) == ""
    assert r.target_sha == fix_sha and r.lane_head


def test_second_resync_is_zero_action_up_to_date(tmp_path):
    """已追平快路径幂等：merge_check 每次入口都同步也不产生第二笔合并提交。"""
    origin, lane = _parked_lane(tmp_path)
    _commit_file(origin, "fix.txt", "the fix\n", "main-side fix")
    assert _prep(lane).ok
    head = _git("rev-parse", "HEAD", cwd=lane)
    r2 = _prep(lane)
    assert r2.ok and r2.up_to_date
    assert _git("rev-parse", "HEAD", cwd=lane) == head


def test_resync_conflict_is_named_not_bare(tmp_path):
    """重并冲突=具名现场（冲突文件点名 + MERGE_HEAD 在场），不是一张裸 not green。"""
    origin, lane = _parked_lane(tmp_path)
    _commit_file(lane, "base.txt", "lane edit\n", "lane change while parked")
    _commit_file(origin, "base.txt", "main edit\n", "conflicting main change")
    head = _git("rev-parse", "HEAD", cwd=lane)
    r = _prep(lane)
    assert r.ok and r.conflict_files == ["base.txt"]
    assert (lane / ".git").exists()  # worktree 形态；MERGE_HEAD 在 gitdir 下
    gitdir = Path(_git("rev-parse", "--git-dir", cwd=lane))
    assert (gitdir / "MERGE_HEAD").exists()
    assert _git("rev-parse", "HEAD", cwd=lane) == head  # 消解前 lane HEAD 不动
    _git("merge", "--abort", cwd=lane)


def test_resync_unreachable_main_names_the_ref(tmp_path):
    """main 不可达=响亮具名失败（error 点名缺失 ref），绝不静默跳过同步继续检查。"""
    origin, lane = _parked_lane(tmp_path)
    r = _prep(lane, base_ref="no-such-ref")
    assert not r.ok
    assert "no-such-ref" in (r.error or "")


# ---------- B：结构锚（merge_check 相位：同步先于检查；文档两段一致） ----------

def _mc_block(src):
    i = src.index('if phase == "merge_check":')
    return src[i:i + 4000]


def test_dev_lane_merge_check_phase_syncs_before_the_check():
    block = _mc_block(DL_SRC)
    assert 'workflow.patched(MAIN_SYNC_AT_MERGE_CHECK_PATCH_ID)' in block
    assert 'step_id="merge_check"' in block
    assert block.index("self._main_sync_before_gate(") < block.index("merge_check,")
    assert 'if _ms.get("stop"):\n                        continue' in block
    assert DL_SRC.count('MAIN_SYNC_AT_MERGE_CHECK_PATCH_ID = '
                        '"t261002-10-merge-check-resync"') == 1


def test_light_lane_merge_check_phase_syncs_before_the_check():
    block = _mc_block(LL_SRC)
    assert "workflow.patched(MAIN_SYNC_AT_MERGE_CHECK_PATCH_ID)" in block
    assert "texts=self.LIGHT_MAIN_SYNC_TEXTS" in block
    assert 'step_id="merge_check"' in block
    assert block.index("self._main_sync_before_gate(") < block.index(
        "self._light_merge_check()")
    # 轻道零第二份实现：只有调用点（闸 + merge_check 两处）
    assert LL_SRC.count("await self._main_sync_before_gate(") == 2


def test_helper_step_id_defaults_to_the_gate_phase_value():
    """step_id 参数化：缺省=闸相位原值 ⇒ 闸调用点与老历史回放零变化。"""
    start = DL_SRC.index("async def _main_sync_before_gate(")
    sig = DL_SRC[start:DL_SRC.index(") -> Dict[str, Any]:", start)]
    assert 'step_id: str = "run_integration_tests"' in sig
    # helper 的响亮出口用 step_id 点名（哪个检查失败具名，绝不裸 not green）
    body = DL_SRC[start:DL_SRC.index("    @workflow.run", start)]
    assert 'fallback=step_id' in body
    assert 'await self._blocked(\n                    step_id,' in body
    assert 'await self._blocked(step_id,\n' in body


def test_docs_agree_at_both_machine_stages():
    """验收③：两个车道的 merge_check 段文案 + ticket.py retry_qc 帮助都写明重并 main。"""
    assert "重并 main" in DL_SRC[DL_SRC.index('id="merge_check"'):
                                  DL_SRC.index('id="merge"')]
    ll_desc_i = LL_SRC.index('id="merge_check"')
    assert "re-merges main" in LL_SRC[ll_desc_i:LL_SRC.index('id="merge"', ll_desc_i)]
    tq_i = TK_SRC.index("retry_qc {id, by(who)}")
    assert "重并进泳道" in TK_SRC[tq_i:TK_SRC.index("cancel {id,", tq_i)]
    assert "merge_check" in TK_SRC[tq_i:tq_i + 600]


def test_incident_anchor_named_in_source():
    """t261001-20 时间线留在源码注释（文档漂移观测点：修因必留名）。"""
    assert "t261001-20" in DL_SRC and "t261002-10-merge-check-resync" in DL_SRC
    assert "t261001-20" in LL_SRC
