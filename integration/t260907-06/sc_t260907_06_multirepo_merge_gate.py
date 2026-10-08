#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-06 场景②：合并闸逐树判定 + merge 逐仓收口 + 重入幂等（验收①后半，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同）：
- 写集白名单门逐仓重基正确（两向）：
  · 合法分仓改动（写集两条分落两仓）→ 逐树白名单门整体绿——重基漏剥前缀会把
    合法改动误判写集外（假红）；
  · 树内注入写集外文件 → 整体红且 detail 点名该文件——重基不得把门放空（假绿）；
- merge 逐仓收口：两仓 main 各恰多**一个** squash 提交（一单一提交语义逐仓独立
  成立），内容各自正确落回所属仓（错仓落账/多提交=验收红线）；
- 重入幂等（Temporal 重试面）：一仓冲突整体 failed、已成功仓已落账；重试后
  已成功仓提交数不变（不重复落账）、失败仓补齐收口（不漏账）——「无跳过逻辑、
  靠逐仓幂等」的重入语义。

与相邻场景 intent 分界：场景①守旅程前半（归属/两树/复用/settle）；场景③守
fail-closed 拒收面。白名单门的工具语义另有专测（verify_lane 族），本条只守
**多仓重基后调用侧组装**的两向行为。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（全链行为子用例），无 stdlib 替代子用例（本场全靠真链路）。
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260907_06 import (  # noqa: E402
    POC, check, summary, env_fail, temporalio_available,
    git, build_multirepo_project, lane_dirname, call_prepare,
    call_with_supported_fields, CapabilityMissing,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402

WS = ["repo_a/src/a.py", "repo_b/lib/b.py"]


def prepare_and_settle(ticket):
    """夹具推进到「两树各落一笔写集内提交」：建假多仓项目→prepare→两树写合法
    改动→settle。返回 (root, repos, counts) counts={repo_a: main 提交数, ...}。"""
    root, repos = build_multirepo_project(prefix="t260907-06-mg-")
    wname = lane_dirname(ticket)
    container = root / ".lane" / wname
    res = call_prepare(container, ticket, WS, root)
    if not getattr(res, "ok", False):
        raise CapabilityMissing("prepare 多仓分支未落地或失败: %r" % (res,))
    ta = container / "repo_a"
    tb = container / "repo_b"
    (ta / "src" / "a.py").write_text("print('a changed')\n", encoding="utf-8")
    (tb / "lib" / "b.py").write_text("print('b changed')\n", encoding="utf-8")
    import asyncio
    import agent_activities  # noqa: E402
    asyncio.run(agent_activities.settle_lane(
        shared.SettleLaneArgs(ticket_id=ticket, worktree=str(container),
                              stage_id="sc2", gen=0)))
    counts = {k: int(git("rev-list", "--count", "main", cwd=v).strip())
              for k, v in repos.items() if k in ("repo_a", "repo_b")}
    return root, repos, container, counts


def green_run_face(container):
    """t261008-24/KI-217 出口①绿跑面：清单首仓分支真 HEAD（与 merge_check 的
    _gr_sha 同款解析）、ran=1。无面=新检查项恒红 zero_run（永不默认绿），
    G1 的「整体绿」会被无关红污染。解析失败=空 sha（活动侧 fail-closed）。"""
    import subprocess
    mf = shared.multi_manifest_path(container)  # 协调目录解析三规则单点
    sha = ""
    try:
        e0 = json.loads(mf.read_text("utf-8"))[0]
        repo = (container.parent.parent / str(e0.get("repo") or "")).resolve()
        br = str(e0.get("branch") or "")
        p = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", br],
                           capture_output=True, text=True)
        if p.returncode == 0:
            sha = (p.stdout or "").strip()
    except Exception:
        sha = ""
    return {"sha": sha, "ran": 1}


def run_merge_check(container, write_set, ticket):
    import asyncio
    import agent_activities  # noqa: E402
    return asyncio.run(agent_activities.merge_check(
        call_with_supported_fields(
            shared.MergeCheckArgs, ticket_id=ticket, worktree=str(container),
            branch="", base_ref="", write_set=list(write_set),
            last_green_run=green_run_face(container))))


def run_merge(container, ticket):
    import asyncio
    import agent_activities  # noqa: E402
    return asyncio.run(agent_activities.merge(
        call_with_supported_fields(
            shared.MergeArgs, ticket_id=ticket, worktree=str(container),
            branch="", base_ref="", defer_teardown=True)))


def details_of(res):
    import json
    return json.dumps(getattr(res, "checks", []), ensure_ascii=False, default=str)


if not temporalio_available():
    env_fail("temporalio 不可用（本泳道无 venv）：合并闸/逐仓收口/重入行为子用例不可执行——"
             "arbitrate/merge 期 venv 环境必须全绿")
    sys.exit(summary())

# ---------- G1/G2：白名单门重基两向 ----------
try:
    root, repos, container, counts = prepare_and_settle("t26090706mg")
except CapabilityMissing as e:
    check("G1 合法分仓改动过白名单门=绿（重基不假红）", False, str(e))
    check("G2 树内写集外注入→整体红且点名（重基不放空）", False, "同上能力缺失")
    root = None

if root is not None:
    try:
        res = run_merge_check(container, WS, "t26090706mg")
        checks = getattr(res, "checks", [])
        any_red = any(c.get("green") is False for c in checks)
        check("G1 合法分仓改动过白名单门=绿（重基不假红）",
              len(checks) > 0 and not any_red, "checks=%s" % (details_of(res)[:1500],))

        # 注入写集外文件并提交（越界改动，KI-009 自愈不得放行）
        ta = container / "repo_a"
        (ta / "src" / "evil.py").write_text("evil\n", encoding="utf-8")
        git("add", "-A", cwd=ta)
        git("commit", "-m", "lane: 越界注入", cwd=ta)
        res2 = run_merge_check(container, WS, "t26090706mg")
        checks2 = getattr(res2, "checks", [])
        red2 = any(c.get("green") is False for c in checks2)
        det2 = details_of(res2)
        check("G2 树内写集外注入→整体红且点名（重基不放空）",
              red2 and "evil.py" in det2, "checks=%s" % (det2[:1500],))
    finally:
        shutil.rmtree(root, ignore_errors=True)

# ---------- G3：merge 逐仓收口（一单一提交、各归其仓） ----------
try:
    root, repos, container, counts = prepare_and_settle("t26090706mr1")
except CapabilityMissing as e:
    check("G3 merge 逐仓收口：两仓 main 各+1 squash 且内容正确", False, str(e))
    root = None

if root is not None:
    try:
        mres = run_merge(container, "t26090706mr1")
        ca = int(git("rev-list", "--count", "main", cwd=repos["repo_a"]).strip())
        cb = int(git("rev-list", "--count", "main", cwd=repos["repo_b"]).strip())
        fa = git("show", "--name-only", "--format=", "main", cwd=repos["repo_a"])
        fb = git("show", "--name-only", "--format=", "main", cwd=repos["repo_b"])
        content_a = git("show", "main:src/a.py", cwd=repos["repo_a"])
        content_b = git("show", "main:lib/b.py", cwd=repos["repo_b"])
        check("G3a repo_a main 恰多一个 squash 提交（一单一提交）",
              ca == counts["repo_a"] + 1, "before=%d after=%d mres=%r"
              % (counts["repo_a"], ca, mres))
        check("G3b repo_b main 恰多一个 squash 提交（一单一提交）",
              cb == counts["repo_b"] + 1, "before=%d after=%d" % (counts["repo_b"], cb))
        check("G3c 各归其仓：repo_a 收 a.py、不收 b.py",
              "src/a.py" in fa and "lib/b.py" not in fa, "fa=%r" % (fa,))
        check("G3d 各归其仓：repo_b 收 b.py、不收 a.py",
              "lib/b.py" in fb and "src/a.py" not in fb, "fb=%r" % (fb,))
        check("G3e 内容正确落账", "a changed" in content_a and "b changed" in content_b)
    finally:
        shutil.rmtree(root, ignore_errors=True)

# ---------- G4：重入幂等（一仓冲突→failed；重试不重复落账、失败仓补齐） ----------
try:
    root, repos, container, counts = prepare_and_settle("t26090706mr2")
except CapabilityMissing as e:
    check("G4 重入幂等：冲突仓 failed、已收口仓重试不重复落账", False, str(e))
    root = None

if root is not None:
    try:
        # repo_b main 造同文件异改动 → squash 必冲突
        (repos["repo_b"] / "lib" / "b.py").write_text("print('b conflicting')\n", encoding="utf-8")
        git("add", "-A", cwd=repos["repo_b"])
        git("commit", "-m", "main: 他人先行的冲突改动", cwd=repos["repo_b"])
        base_a = counts["repo_a"]
        m1 = run_merge(container, "t26090706mr2")
        ca1 = int(git("rev-list", "--count", "main", cwd=repos["repo_a"]).strip())
        cb1 = int(git("rev-list", "--count", "main", cwd=repos["repo_b"]).strip())
        check("G4a 一仓冲突→整体 failed（不假绿）", getattr(m1, "ok", True) is False,
              "m1=%r" % (m1,))
        check("G4b 已成功仓已落账（repo_a +1）", ca1 == base_a + 1,
              "base=%d ca1=%d" % (base_a, ca1))
        # 口径：cb1 应恰为 counts+1——那 1 笔是本场景自己刚提交的「他人先行冲突
        # 改动」（counts 在其之前取的基线）；merge 收口失败不得再添任何提交。
        check("G4c 冲突仓不落账（repo_b 仅含场景自建冲突提交）",
              cb1 == counts["repo_b"] + 1,
              "counts=%d cb1=%d（差额≠1 即 merge 失败路径多落账）"
              % (counts["repo_b"], cb1))
        # 解堵 repo_b：main 接受同内容（外部消解），重试 merge
        (repos["repo_b"] / "lib" / "b.py").write_text("print('b changed')\n", encoding="utf-8")
        git("add", "-A", cwd=repos["repo_b"])
        git("commit", "-m", "main: 消解后接受本票改动", cwd=repos["repo_b"])
        m2 = run_merge(container, "t26090706mr2")
        ca2 = int(git("rev-list", "--count", "main", cwd=repos["repo_a"]).strip())
        content_b = git("show", "main:lib/b.py", cwd=repos["repo_b"])
        check("G4d 重试：repo_a 不重复落账（提交数不变）", ca2 == base_a + 1,
              "ca1=%d ca2=%d" % (ca1, ca2))
        check("G4e 重试：repo_b 补齐收口（main 含本票改动内容）",
              "b changed" in content_b, "content=%r" % (content_b,))
        check("G4f 重试：整体收口 ok（不卡死不假败）", getattr(m2, "ok", False) is True,
              "m2=%r" % (m2,))
    finally:
        shutil.rmtree(root, ignore_errors=True)

sys.exit(summary())
