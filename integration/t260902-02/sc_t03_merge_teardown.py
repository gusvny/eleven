#!/usr/bin/env python3
"""t03 —— dev-lane 三段收口的 git 侧实证 + MergeArgs 负载兼容 + 接线源码锁。

1) _squash_merge defer_teardown 双语义（git fixture 真跑）：False（缺省=旧历史
   语义）落账后内联拆 worktree+删分支；True 落账后泳道原样保留（交 teardown_lane）。
2) MergeArgs 旧 payload 缺 defer_teardown 键 → temporalio 反序列化回落默认 False
   （真 temporalio 实证；环境无 SDK 则该子用例记 ENV_FAIL——三态契约定稿 §7.3）。
3) teardown_lane：defer 后的泳道由它拆（幂等重跑 ok）；非法 branch 回执 ok=False
   点名环节（不抛）。
4) dev_lane.py 接线源码锁：ARCHIVE_PATCH_ID 门 + archive→teardown 顺序 +
   defer_teardown=archive_on 传入 + 归档失败转 blocked 泳道保留。

跑法：python3 integration/t260902-02/t03_merge_teardown.py（cwd=泳道根，需 git）
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "engine"

# —— SDK 面（t260904-12 乙段）：顶层无 temporalio 则 re-exec 进 poc venv（同 t05
# ensure_sdk 制式），让「MergeArgs 缺字段解码」真 temporalio 腿在本机可跑，
# 消掉此前恒 ENV_FAIL 的环境红。venv 也没有 SDK 时 _SDK_ERR 非空，腿 4 记
# ENV_FAIL（环境红），文案精确到两面：无模型面，纯 SDK/工具面缺失。
sys.path.insert(0, str(HERE / "lib"))
import fixture as fx  # noqa: E402

_SDK_ERR = fx.ensure_sdk()[1]

try:
    import temporalio  # noqa: F401
    _HAVE_TIO = True
except ImportError:
    _HAVE_TIO = False

if not _HAVE_TIO:
    _tmod = types.ModuleType("temporalio")
    _amod = types.ModuleType("temporalio.activity")

    class _ActivityStub:
        logger = logging.getLogger("temporalio-stub-t03")

        def defn(self, fn=None, **kw):
            return (lambda f: f) if fn is None else fn

        def heartbeat(self, *a, **kw):
            pass

    _amod.activity = _ActivityStub()
    _tmod.activity = _ActivityStub()
    sys.modules.setdefault("temporalio", _tmod)
    sys.modules.setdefault("temporalio.activity", _amod)
sys.path.insert(0, str(POC))

from shared import MergeArgs  # noqa: E402
import agent_activities as aa  # noqa: E402

PASS = FAIL = ENV_FAIL = 0  # 三态契约：0=PASS、1=FAIL（产品红）、2=ENV_FAIL（环境红）


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def env_fail(label):
    """缺依赖（环境红）：计入 env_fail，绝不 exit 0。"""
    global ENV_FAIL
    ENV_FAIL += 1
    print("ENV_FAIL: %s" % label)


def git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True)
    return p


def make_repo_with_lane(tag):
    """tmp 真 git 仓库：main 一提交 + lane 分支一提交 + worktree 挂出。"""
    base = Path(tempfile.mkdtemp(prefix="t03-%s-" % tag))
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("main v1", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "main base")
    lane_dir = base / "lane-wt"
    git(repo, "worktree", "add", "-q", str(lane_dir), "-b", "lane/t03-" + tag)
    (lane_dir / "feat.txt").write_text("feat %s" % tag, encoding="utf-8")
    git(repo, "-C", str(lane_dir), "add", ".")
    git(repo, "-C", str(lane_dir), "commit", "-qm", "feat")
    return repo, lane_dir, "lane/t03-" + tag


def lane_intact(repo, lane_dir, branch):
    return lane_dir.is_dir() and \
        git(repo, "rev-parse", "--verify", "--quiet", branch).returncode == 0


def main():
    # ---- 1) defer_teardown=False（旧语义）：内联拆泳道 ----
    repo, lane_dir, branch = make_repo_with_lane("old")
    res = aa._squash_merge(repo, lane_dir, branch, "t03-old", defer_teardown=False)
    ok(res.ok and res.action == "merged" and res.merge_commit, "defer=False：squash 落账成功")
    ok(not lane_intact(repo, lane_dir, branch),
       "defer=False：worktree+分支内联拆除（=旧行为，存量历史语义不变）")

    # ---- 2) defer_teardown=True（新三段收口）：泳道保留 ----
    repo2, lane2, branch2 = make_repo_with_lane("defer")
    res2 = aa._squash_merge(repo2, lane2, branch2, "t03-defer", defer_teardown=True)
    ok(res2.ok, "defer=True：squash 落账成功（不内联清理）")
    ok(lane_intact(repo2, lane2, branch2), "defer=True：泳道原样保留（等 teardown_lane）")

    # ---- 3) teardown_lane：拆 defer 后的泳道 + 幂等 + 非法 branch ----
    # teardown_lane 走模块级 REPO_ROOT（生产=真仓库根）；测试指向 fixture 仓库。
    saved_root = aa.REPO_ROOT
    aa.REPO_ROOT = repo2
    try:
        tres = asyncio.run(getattr(aa.teardown_lane, "fn", aa.teardown_lane)(
            MergeArgs(ticket_id="t03-defer", worktree=str(lane2), branch=branch2)))
        ok(tres.ok and not lane_intact(repo2, lane2, branch2),
           "teardown_lane：拆除 defer 后的泳道")
        tres2 = asyncio.run(getattr(aa.teardown_lane, "fn", aa.teardown_lane)(
            MergeArgs(ticket_id="t03-defer", worktree=str(lane2), branch=branch2)))
        ok(tres2.ok, "teardown_lane 幂等重跑 ok（已拆再拆不炸）")
        bad = asyncio.run(getattr(aa.teardown_lane, "fn", aa.teardown_lane)(
            MergeArgs(ticket_id="t03-x", worktree="/tmp/none", branch="-bad")))
        ok((not bad.ok) and "非法" in (bad.error or ""), "非法 branch 回执 ok=False 点名（不抛）")
    finally:
        aa.REPO_ROOT = saved_root

    # ---- 4) MergeArgs 旧 payload 缺字段解码回落默认（真 temporalio）----
    try:
        from temporalio.api.common.v1 import Payload
        from temporalio.converter import DataConverter
    except ImportError:
        env_fail("MergeArgs 缺字段解码（temporalio SDK 不可用：%s；本场景无模型面，"
                 "缺的是 SDK/工具面）" % (_SDK_ERR or "顶层与 poc venv 均无"))
    else:
        pc = DataConverter.default.payload_converter
        old_payload = Payload(metadata={"encoding": b"json/plain"},
                              data=json.dumps({"ticket_id": "t1", "branch": "lane/t1",
                                               "worktree": ".worktrees/t1",
                                               "base_ref": "main"}).encode())
        (back,) = pc.from_payloads([old_payload], [MergeArgs])
        ok(back.defer_teardown is False, "旧 payload 无 defer_teardown 键 → 默认 False（旧清理语义）")
        new_payload = pc.to_payloads([MergeArgs(ticket_id="t2", branch="b",
                                                defer_teardown=True)])[0]
        (back2,) = pc.from_payloads([new_payload], [MergeArgs])
        ok(back2.defer_teardown is True, "新 payload 显式 True 往返无损")

    # ---- 5) dev_lane 接线源码锁 ----
    src = (POC / "dev_lane.py").read_text(encoding="utf-8")
    ok('ARCHIVE_PATCH_ID = "dev-lane-archive-ticket"' in src, "ARCHIVE_PATCH_ID 常量在场")
    ok("workflow.patched(ARCHIVE_PATCH_ID)" in src, "merge 步 patched 门消费")
    ok("defer_teardown=archive_on" in src, "merge 入参 defer_teardown=archive_on（新票三段）")
    a_pos = src.index("archive_ticket,")
    t_pos = src.index("teardown_lane,")
    m_pos = src.index("merge,\n", src.index("archive_ticket"))
    ok(a_pos < t_pos, "workflow 侧 archive 在 teardown 之前编排（顺序锁）")
    ok("archive_ticket," in src and "teardown_lane," in src
       and "from agent_activities import" in src, "archive_ticket/teardown_lane 已 import 进 dev_lane")
    act_src = (POC / "agent_activities.py").read_text(encoding="utf-8")
    ok("archive_ticket, teardown_lane," in act_src
       or ("archive_ticket" in act_src and "teardown_lane" in act_src
           and "ALL_AGENT_ACTIVITIES" in act_src),
       "archive_ticket/teardown_lane 注册进 ALL_AGENT_ACTIVITIES")
    ok("await self._blocked(" in src and "归档失败（fail-closed，泳道保留不拆）" in src,
       "归档失败转 blocked、泳道保留（fail-closed 接线）")

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, FAIL, ENV_FAIL))
    if ENV_FAIL:
        return 2
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
