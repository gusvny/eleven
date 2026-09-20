#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-20 场景：泳道内从零建成员仓的四道守卫（灰盒 L2，真 git 夹具+直调 activity）。

intent（守护的用户可感知行为/合同；nusuyou t260916-08 实案=600 文件静默丢失）：
- settle 双站点（主 settle + 冲突消解 settle）遇嵌套仓（untracked 目录折叠形态 ×
  .git 在场，或暂存区 160000 gitlink）→ fail-closed 拒绝代落盘，人话点名嵌套仓、
  现场保留（不 commit、不 reset、不删除），重试同拒（幂等红灯）；
- 冲突消解旁路站点（MERGE_HEAD 在场=主 settle 整体跳过时的唯一 settle 通道）同拒
  ——R2 覆盖洞回归形态；
- merge_check 对泳道差集 gitlink → 红灯点名（reason_code=gitlink_present），且
  非 conflict 类（不进自动消解回路，KI-047 位置契约）；
- squash 前置红灯：merge --squash 前判 160000 → failed(gitlink_present)、主树未动；
- 拆道守卫：teardown 前扫出未注册嵌套仓 → blocked 点名，一物不拆，对象库完好
  （`git -C <嵌套仓> rev-parse HEAD` 前后一致）；守卫自身 IO 故障 → 同样 failed
  点名（绝不静默放拆）；无嵌套仓的干净泳道拆道照旧（旧语义零回归）；
- 负控子用例：无嵌套仓的正常冲突消解照常落合并提交（守卫不误伤冲突流）；
  `.git` 为文件（worktree 形态）的嵌套仓同样 blocked 点名（两形态一个立场）。
- 内联清理（defer_teardown=False 老票唯一拆道通道）同口径：落账完成后停拆、
  泳道保留=对象库可抢救。

与相邻场景的 intent 分界（防 intent 级重复）：
- t260911-04-multirepo-fullchain-landing（全链 L3 回归锚）：守成功路径逐仓落仓+
  拆道零残留；本条守「泳道内从零建仓」失败路径的四道闸行为（L2 直调，秒级）；
- t260913-05-teardown-scope-contract：守多仓拆道回执契约与三态取源；本条守拆道
  前的嵌套仓守卫（单仓形态即可触发，事故现场即单仓泳道）；
- UT（server/engine/tests/test_t26091620_nested_repo_guards.py）：同判定源的桩级
  真值/畸形输入面；本条是活动级行为面（真 git 全站点点火）。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
引擎 venv/temporalio 缺席 = ENV_FAIL exit 2 点名（本场景无 stdlib 替代子用例：直调 activity）。
"""
import asyncio
import inspect
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path


def _settle(lane, *a, **kw):
    """settle 直调单点（c184e62 同款防御）：t260916-19 D 把 face 定为 keyword-only
    必填分层标签——探测签名，有则传（新树），无则不传（老树两侧可跑）。"""
    import agent_activities as _aa
    try:
        params = inspect.signature(_aa._settle_worktree_lane).parameters
    except (TypeError, ValueError):
        params = {}
    if "face" in params:
        kw.setdefault("face", "agent")
    return _aa._settle_worktree_lane(lane, *a, **kw)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# 红线桩：先钉不可达 host 再 import 引擎模块（shared 在 import 期读 TARGET_HOST），
# 本场景全程零 Temporal 连接。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "server" / "engine"))

_PASS, _FAIL = [], []


def check(name, ok, detail=""):
    (_PASS if ok else _FAIL).append(name)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       ("" if ok else " ｜ %s" % detail)), flush=True)


def env_fail(why):
    print("ENV_FAIL %s" % why, flush=True)
    print("SUMMARY pass=0 fail=0 env_fail=1", flush=True)
    return 2


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=0" % (len(_PASS), len(_FAIL)), flush=True)
    return 0 if not _FAIL else 1


def engine_modules():
    try:
        import agent_activities  # noqa: F401
        import shared  # noqa: F401
        return True, ""
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:200])


def _git(*args, cwd, check_rc=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check_rc:
        assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p


def _init_repo(path, fname="f.txt"):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "sc@example.com", cwd=path)
    _git("config", "user.name", "sc", cwd=path)
    (path / fname).write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _make_lane(root, tid="t26091620sc"):
    lane = root / ".lane" / tid
    _git("worktree", "add", "-b", "lane/%s" % tid, str(lane), cwd=root)
    return lane


def _nested_repo(path, committed):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "sc@example.com", cwd=path)
    _git("config", "user.name", "sc", cwd=path)
    if committed:
        (path / "data.txt").write_text("nested\n", encoding="utf-8")
        _git("add", "-A", cwd=path)
        _git("commit", "-m", "nested base", cwd=path)
    return path


def _lane_head(lane):
    return _git("rev-parse", "HEAD", cwd=lane).stdout.strip()


def _nested_head(path):
    return _git("rev-parse", "HEAD", cwd=path).stdout.strip()


def _stage_result(res, name_prefix, expect):
    ok = res.ok is expect[0]
    check(name_prefix + " 回执 ok=%s" % expect[0], ok,
          "ok=%r error=%r" % (getattr(res, "ok", None), getattr(res, "error", "")))


def leg_settle_untracked(tmp):
    """验收①：0 提交嵌套仓 → 主 settle 拒绝代落盘（拒绝被吞成普通文件的错形入库）。"""
    import agent_activities as aa
    root = _init_repo(tmp / "sa")
    lane = _make_lane(root)
    _nested_repo(lane / "content", committed=False)
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    head0 = _lane_head(lane)
    refusal = {}
    note = _settle(lane, "t26091620sc", "implement", 0,
                   repo=root, refusal=refusal)
    check("SA1 拒绝回执人话点名嵌套仓（机器键内嵌）",
          "path_gate_reason=gitlink_nested_repo" in note and "content" in note, note[:200])
    check("SA2 结构化 refusal（reason_code/files）",
          refusal.get("reason_code") == "gitlink_nested_repo"
          and refusal.get("files") == ["content"], repr(refusal)[:200])
    check("SA3 现场保留：无 commit", _lane_head(lane) == head0,
          "head=%s vs %s" % (_lane_head(lane), head0))
    check("SA4 现场保留：嵌套仓未被动", (lane / "content" / ".git").is_dir())
    dirty_after = _git("status", "--porcelain", "-z", cwd=lane, check_rc=False).stdout
    check("SA6 现场保留：脏态原样（未 reset 未吞文件）",
          "content/" in dirty_after and "code.py" in dirty_after,
          repr(dirty_after)[:160])
    note2 = _settle(lane, "t26091620sc", "implement", 0, repo=root)
    check("SA5 幂等红灯：重试同拒", note2 == note, note2[:120])


def leg_settle_staged_gitlink(tmp):
    """验收①第二形态：gitlink 已入暂存区 → 主 settle (b) 闸拒绝。"""
    import agent_activities as aa
    root = _init_repo(tmp / "sb")
    lane = _make_lane(root)
    _nested_repo(lane / "content", committed=True)
    _git("add", "content", cwd=lane)
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    head0 = _lane_head(lane)
    note = _settle(lane, "t26091620sc", "implement", 0, repo=root)
    check("SB1 暂存 gitlink 被拒（人话点名）",
          "gitlink_nested_repo" in note and "content" in note, note[:200])
    check("SB2 现场保留：无 commit 且 gitlink 仍在暂存区",
          _lane_head(lane) == head0
          and aa.staged_gitlinks(_git("-c", "core.quotepath=false", "diff",
                                      "--cached", "--raw", cwd=lane).stdout) == ["content"])


def leg_conflict_bypass(tmp):
    """R2 回归形态：MERGE_HEAD 在场（主 settle 跳过的旁路站点）× 0 提交嵌套仓 → 冲突
    消解 settle 拒绝，MERGE_HEAD 现场保留、不落合并提交。"""
    import agent_activities as aa
    from shared import ConflictSettleArgs
    root = _init_repo(tmp / "sc", "f.txt")
    lane = _make_lane(root)
    (lane / "f.txt").write_text("line1\nline2\nLANE\nline3\n", encoding="utf-8")
    _git("commit", "-qam", "lane side", cwd=lane)
    (root / "f.txt").write_text("line1\nline2\nMAIN\nline3\n", encoding="utf-8")
    _git("commit", "-qam", "main side", cwd=root)
    p = _git("merge", "main", cwd=lane, check_rc=False)
    check("SC0 夹具前置：冲突态成立（MERGE_HEAD 在场）",
          p.returncode == 1 and "CONFLICT" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[:160])
    _nested_repo(lane / "content", committed=False)
    head0 = _lane_head(lane)
    res = asyncio.run(aa.settle_conflict_resolution(ConflictSettleArgs(
        ticket_id="t26091620sc", worktree=str(lane), branch="lane/t26091620sc",
        round_no=1)))
    check("SC1 冲突消解拒绝落盘（人话点名嵌套仓）",
          res.ok is False and "content" in (res.error or "")
          and "嵌套仓" in (res.error or ""), repr(res.error)[:200])
    check("SC2 现场保留：无合并提交且 MERGE_HEAD 原样",
          _lane_head(lane) == head0
          and _git("rev-parse", "--verify", "MERGE_HEAD", cwd=lane,
                   check_rc=False).returncode == 0)


def leg_conflict_clean(tmp):
    """负控子用例（守卫不误伤）：无嵌套仓的正常冲突消解照常落合并提交——若守卫把
    正常冲突流也拒掉，等于堵死消解回路（KI-047 家族反面）。"""
    import agent_activities as aa
    from shared import ConflictSettleArgs
    root = _init_repo(tmp / "scl", "f.txt")
    lane = _make_lane(root)
    (lane / "f.txt").write_text("line1\nline2\nLANE\nline3\n", encoding="utf-8")
    _git("commit", "-qam", "lane side", cwd=lane)
    (root / "f.txt").write_text("line1\nline2\nMAIN\nline3\n", encoding="utf-8")
    _git("commit", "-qam", "main side", cwd=root)
    p = _git("merge", "main", cwd=lane, check_rc=False)
    check("SL0 夹具前置：冲突态成立（MERGE_HEAD 在场）",
          p.returncode == 1 and "CONFLICT" in (p.stdout + p.stderr),
          (p.stdout + p.stderr)[:160])
    head0 = _lane_head(lane)
    # agent 解冲突（清标记），settle 只管代落盘
    (lane / "f.txt").write_text("line1\nline2\nRESOLVED\nline3\n", encoding="utf-8")
    res = asyncio.run(aa.settle_conflict_resolution(ConflictSettleArgs(
        ticket_id="t26091620sc", worktree=str(lane), branch="lane/t26091620sc",
        round_no=1)))
    check("SL1 正常冲突消解照常落盘（守卫零误伤）",
          res.ok is True and bool(res.commit) and _lane_head(lane) != head0,
          "ok=%r commit=%r" % (res.ok, getattr(res, "commit", "")))
    check("SL2 合并收口：MERGE_HEAD 已清",
          _git("rev-parse", "--verify", "MERGE_HEAD", cwd=lane,
               check_rc=False).returncode != 0)


def leg_merge_check_red(tmp):
    """验收④：泳道分支含 gitlink commit → merge_check 红灯点名且非 conflict 类。"""
    import agent_activities as aa
    from shared import MergeCheckArgs
    root = _init_repo(tmp / "md")
    lane = _make_lane(root)
    (lane / "code.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "work", cwd=lane)
    _nested_repo(lane / "content", committed=True)
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "accident: gitlink", cwd=lane)
    res = asyncio.run(aa.merge_check(MergeCheckArgs(
        ticket_id="t26091620sc", worktree=str(lane), branch="lane/t26091620sc",
        base_ref=_git("rev-parse", "main", cwd=root).stdout.strip(),
        write_set=["content/"])))
    red = [c for c in res.checks if c.get("reason_code") == "gitlink_present"]
    check("MD1 merge_check 红灯点名 gitlink", bool(red) and red[0].get("files") == ["content"],
          repr([c.get("item") for c in res.checks])[:300])
    check("MD2 非 conflict 类（blocked 交人工，不进自动消解回路）",
          res.green is False and res.conflict is False,
          "green=%r conflict=%r" % (res.green, res.conflict))
    idx_red = res.checks.index(red[0]) if red else -1
    check("MD3 位次在 checks[:-1]（不与 rehearsal 尾项混淆）",
          0 <= idx_red < len(res.checks) - 1, "idx=%d n=%d" % (idx_red, len(res.checks)))


def leg_squash_red(tmp):
    """验收④背闸：squash 前置红灯，主树未动。"""
    import agent_activities as aa
    root = _init_repo(tmp / "sq")
    lane = _make_lane(root)
    (lane / "code.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "work", cwd=lane)
    _nested_repo(lane / "content", committed=True)
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "accident: gitlink", cwd=lane)
    head0 = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
    res = aa._squash_merge(root, lane, "lane/t26091620sc", "t26091620sc")
    check("SQ1 squash 红灯 failed(gitlink_present) 点名",
          res.ok is False and res.reason == "gitlink_present" and res.files == ["content"],
          "ok=%r reason=%r files=%r" % (res.ok, res.reason, res.files))
    check("SQ2 主树未动", _git("rev-parse", "HEAD", cwd=root).stdout.strip() == head0)
    check("SQ3 泳道保留：容器与 lane 分支仍在（取舍 b：失败路径不拆道不删支）",
          lane.is_dir()
          and _git("branch", "--list", "lane/t26091620sc",
                   cwd=root).stdout.strip() != "")


def leg_teardown_blocked(tmp):
    """验收③：拆道守卫 blocked 点名，一物不拆，对象库完好。"""
    import agent_activities as aa
    from shared import MergeArgs
    root = _init_repo(tmp / "td")
    lane = _make_lane(root)
    _nested_repo(lane / "content", committed=True)
    nested0 = _nested_head(lane / "content")
    res = asyncio.run(aa.teardown_lane(MergeArgs(ticket_id="t26091620sc", worktree=str(lane),
                                     branch="lane/t26091620sc")))
    check("TD1 拆道 blocked 点名未注册嵌套仓",
          res.ok is False and res.action == "failed"
          and "拆除守卫" in (res.error or "") and "content" in (res.error or ""),
          repr(res.error)[:240])
    check("TD3 一物不拆：泳道容器仍在", lane.is_dir())
    check("TD4 对象库完好：嵌套仓 HEAD 前后一致",
          _nested_head(lane / "content") == nested0)
    # 守卫自身故障：不可读目录 → failed 点名（绝不静默放拆）
    dark = lane / "dark"
    dark.mkdir()
    os.chmod(dark, 0o000)
    try:
        res2 = asyncio.run(aa.teardown_lane(MergeArgs(ticket_id="t26091620sc", worktree=str(lane),
                                          branch="lane/t26091620sc")))
    finally:
        os.chmod(dark, 0o755)
    check("TD5 守卫自身故障=fail-closed failed 点名",
          res2.ok is False and "守卫自身故障" in (res2.error or ""), repr(res2.error)[:200])
    check("TD6 故障子用例同样零拆除", lane.is_dir())


def leg_teardown_worktree_form(tmp):
    """.git 为**文件**的嵌套仓（worktree 形态，对象库在外部仓）→ 拆道守卫同样
    blocked 点名（未注册=不可拆，两形态一个立场；一物不拆同子用例）。"""
    import agent_activities as aa
    from shared import MergeArgs
    root = _init_repo(tmp / "tw")
    outer = _init_repo(tmp / "tw-outer", "outer.txt")
    _git("branch", "linked-branch", cwd=outer)
    lane = _make_lane(root)
    _git("worktree", "add", str(lane / "linked"), "linked-branch", cwd=outer)
    res = asyncio.run(aa.teardown_lane(MergeArgs(
        ticket_id="t26091620sc", worktree=str(lane), branch="lane/t26091620sc")))
    check("TW1 worktree 形态嵌套仓同样 blocked 点名",
          res.ok is False and res.action == "failed" and "linked" in (res.error or ""),
          repr(res.error)[:240])
    check("TW2 一物不拆：泳道容器与链接仓 .git 文件仍在",
          lane.is_dir() and (lane / "linked" / ".git").is_file())
    # 回收注入（容忍态）：外部仓的 linked worktree 注册随手清掉
    _git("worktree", "remove", "--force", str(lane / "linked"), cwd=outer)


def leg_inline_teardown_stop(tmp):
    """老票（defer_teardown=False）内联清理：落账完成后停拆，泳道保留可抢救。"""
    import agent_activities as aa
    root = _init_repo(tmp / "il")
    lane = _make_lane(root)
    (lane / "code.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-qm", "work", cwd=lane)
    _nested_repo(lane / "content", committed=False)  # 未注册嵌套仓（不进 diff、不进 squash）
    head0 = _git("rev-parse", "HEAD", cwd=root).stdout.strip()
    res = aa._squash_merge(root, lane, "lane/t26091620sc", "t26091620sc",
                           defer_teardown=False)
    check("IL1 落账后停拆：回执 failed(teardown_guard) 点名",
          res.ok is False and res.reason == "teardown_guard" and res.files == ["content"],
          "ok=%r reason=%r" % (res.ok, res.reason))
    check("IL2 落账已完成（主树 +1 squash）",
          _git("rev-parse", "HEAD", cwd=root).stdout.strip() != head0)
    check("IL3 泳道保留=对象库可抢救", lane.is_dir() and (lane / "content" / ".git").is_dir())


def leg_clean_lane_regression(tmp):
    """零回归用例：无嵌套仓的干净泳道，settle/merge/squash/teardown 照旧。"""
    import agent_activities as aa
    from shared import MergeArgs
    root = _init_repo(tmp / "cl")
    lane = _make_lane(root)
    (lane / "code.py").write_text("work\n", encoding="utf-8")
    note = _settle(lane, "t26091620sc", "implement", 0, repo=root)
    check("CL1 无嵌套仓 settle 照常代落盘（不误伤）", "代落盘" in note, note[:160])
    res = asyncio.run(aa.teardown_lane(MergeArgs(ticket_id="t26091620sc", worktree=str(lane),
                                     branch="lane/t26091620sc")))
    check("CL2 无嵌套仓拆道照旧（旧语义零回归）",
          res.ok is True and res.action == "teardown" and not lane.exists(),
          "ok=%r error=%r lane_exists=%s" % (res.ok, res.error, lane.exists()))


def main():
    mods, why = engine_modules()
    if not mods:
        return env_fail("引擎模块不可用（直调 activity 需引擎 venv/temporalio）：%s" % why)
    tmp = Path(tempfile.mkdtemp(prefix="t260916-20-l2-"))
    try:
        legs = (leg_settle_untracked, leg_settle_staged_gitlink, leg_conflict_bypass,
                leg_conflict_clean, leg_merge_check_red, leg_squash_red,
                leg_teardown_blocked, leg_teardown_worktree_form,
                leg_inline_teardown_stop, leg_clean_lane_regression)
        for leg in legs:
            try:
                leg(tmp)
            except Exception as e:  # 单子用例自身炸掉=该子用例红，不拖垮其余子用例
                check("%s 子用例自身异常收敛（不得以 traceback 炸掉场景）" % leg.__name__,
                      False, "%s: %s" % (type(e).__name__, str(e)[:240]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
