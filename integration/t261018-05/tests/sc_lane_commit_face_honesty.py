#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261018-05 场景：泳道 commit 闸项「不可判定红」诚实化（灰盒 L2.5，离线秒级）。

工单 t261018-05 用户场景（t261008-24 线上红灯实案）：merge_check 的「泳道分支有
commit」项在 base_ref 未记录/查询失败时产出**不可判定**的红——detail 断言「实现未
落盘」、出路是「人工检查分支位点」。票被楔死，人拿不到任何可执行出路。契约：
  A. 空写集缺口不应产生无名词的红——每个红必须点名「哪个检查失败」与「下一步做什么」；
  B. 「inspect the branch target manually」不是出路，全族禁绝；
  C. 查询失败（git 故障/空基点）与「实现未落盘」严格分叉：报错必须与事实同向，
     不得在脏面查询失败时断言改动不存在；
  D. 合法终态（真零改动 / 正常带 commit）不因诚实化而变红（旧路径零回归）。
用户可感知面 = merge_check 回执里的检查项文本（detail / next_action / reason_code），
不是私有函数真值表——developer L1（test_t261018_05_lane_commit_face_honesty.py）
锁函数级真值表，本场景锁公开回执面与文案契约，两者不同层不重复。

驱动形态：真 git 夹具仓直驱真 merge_check activity（t261008-24
sc_supply_zero_run_blocker 同款：temporalio 缺席装 _stub_temporalio 桩后离线直驱，
函数体零 workflow 调用）。纯离线秒级，零 docker 依赖。
实现落地前 A–C 段红属预期（TDD 信号），arbitrate/merge 期必须绿。
跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B \
  integration/t261018-05/tests/sc_lane_commit_face_honesty.py
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "integration"))

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


# ---------- 引擎侧装载（真 agent_activities + 真 shared，t261008-24 同款） ----------

def _engine_modules():
    sys.path.insert(0, str(REPO / "integration" / "t260901-23"))
    import importlib.util
    if importlib.util.find_spec("temporalio") is None:
        import _stub_temporalio
        _stub_temporalio.install()
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import shared
    import agent_activities
    return shared, agent_activities


SHARED, AGENT = _engine_modules()

BANNED_REMEDY = "inspect the branch target manually"
NOT_PERSISTED = "implementation not persisted"


def make_git_fixture(ticket_id="t261018-05"):
    """git 夹具仓：main 首 commit（=base）+ lane 分支（默认零 commit，与 base 同点）。
    泳道树按 <repo>/.lane/<id> 落（merge_check 的 scope 单点锚，t261008-24 同款）。"""
    td = tempfile.mkdtemp(prefix="t26101805-")
    outer = Path(td) / "repo"
    wt = outer / ".lane" / ticket_id
    wt.mkdir(parents=True)

    def g(*a):
        subprocess.run(["git", "-C", str(outer)] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q", "-b", "main")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    (outer / "README.md").write_text("fixture\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "init")
    base = subprocess.run(["git", "-C", str(outer), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    g("checkout", "-qb", "lane/t261018-05")
    return str(outer), str(wt), base, "lane/t261018-05"


def run_merge_check(lane_dir, base_ref, branch, write_set=("docs/",)):
    """离线直驱真 merge_check，取 lane_commits 检查项（id=lane_commits）。
    worktree 必须传**泳道目录**（<repo>/.lane/<id>）——单仓锚由该路径约定反推
    repo 根（_lane_repo_root），传仓根会回落引擎 REPO_ROOT、git 查的是别人的仓。"""
    args = SHARED.MergeCheckArgs(
        ticket_id="t261018-05", worktree=lane_dir, branch=branch,
        base_ref=base_ref, last_green_run=None, write_set=list(write_set))
    mc = asyncio.run(AGENT.merge_check(args))
    items = mc.checks if hasattr(mc, "checks") else (
        mc.get("checks") if isinstance(mc, dict) else [])
    for c in items or []:
        if (c.get("id") if isinstance(c, dict) else getattr(c, "id", "")) == "lane_commits":
            return c
    return None


def item_text(c):
    return json.dumps(c, ensure_ascii=False) if c else ""


def assert_named_red(c, want_reason, label):
    """每个红都必须：fail（或指名绿例外）、reason_code 具名、带 retry_qc 出路、
    不含禁绝的人工检查话术。"""
    ok(c is not None, label + " lane_commits 项在场")
    if c is None:
        return
    t = item_text(c)
    ok(c.get("green") is False, label + " 红")
    ok(c.get("reason_code") == want_reason,
       label + " reason_code=%s（got=%s）" % (want_reason, c.get("reason_code")))
    ok("retry_qc" in t, label + " 出路 retry_qc 在场")
    ok(BANNED_REMEDY not in t, label + " 无「人工检查分支位点」话术")


def main():
    print("== t261018-05 泳道 commit 闸项诚实化（灰盒 L2.5 离线） ==")

    # ---- A. 空 base_ref + 干净树：不可判定 ⇒ fail-closed 红，点名基点缺失 + 出路 ----
    repo, wt, base, branch = make_git_fixture()
    try:
        c = run_merge_check(wt, "", branch)
        assert_named_red(c, "commit_query_failed", "A1 空基点/干净树")
        if c:
            t = item_text(c)
            ok("base_ref" in t, "A2 点名 base_ref 缺失（开票基点未记录）")
            ok(NOT_PERSISTED not in t, "A3 不断言「实现未落盘」（树干净，断言与事实相反）")
    finally:
        shutil.rmtree(str(Path(repo).parent), ignore_errors=True)

    # ---- B. 空 base_ref + 脏树（写集内改动就在工作区）：查询失败 ≠ 改动不存在 ----
    repo, wt, base, branch = make_git_fixture()
    try:
        (Path(wt) / "docs").mkdir(parents=True, exist_ok=True)
        (Path(wt) / "docs" / "ticket-notes.md").write_text("judge me\n", encoding="utf-8")
        c = run_merge_check(wt, "", branch)
        assert_named_red(c, "commit_query_failed", "B1 空基点/脏树")
        if c:
            ok(NOT_PERSISTED not in item_text(c),
               "B2 脏面不可判时不得断言「实现未落盘」（文件明明在工作区）")
    finally:
        shutil.rmtree(str(Path(repo).parent), ignore_errors=True)

    # ---- C. 基点已记录 + 脏文件 + 0 commit：红必须点名改动与该落盘的段 ----
    repo, wt, base, branch = make_git_fixture()
    try:
        (Path(wt) / "docs").mkdir(parents=True, exist_ok=True)
        (Path(wt) / "docs" / "ticket-notes.md").write_text("judge me\n", encoding="utf-8")
        c = run_merge_check(wt, base, branch)
        assert_named_red(c, "no_commits", "C1 有改动未入轨")
        if c:
            t = item_text(c)
            ok("docs/ticket-notes.md" in t, "C2 点名改动文件（%s）" % "docs/ticket-notes.md")
            ok(NOT_PERSISTED in t, "C3 该形态可断言实现未落盘（脏面确证在场）")
    finally:
        shutil.rmtree(str(Path(repo).parent), ignore_errors=True)

    # ---- D. 基点已记录 + 真零改动：合法终态绿且点名可见（诚实化不造假红） ----
    repo, wt, base, branch = make_git_fixture()
    try:
        c = run_merge_check(wt, base, branch)
        ok(c is not None and c.get("green") is True,
           "D1 真零改动=绿（旧路径零回归）")
        if c:
            ok("no_changes_no_diff" == c.get("reason_code") or "zero-change" in item_text(c),
               "D2 绿项点名「确证零改动」可见（不静默）")
    finally:
        shutil.rmtree(str(Path(repo).parent), ignore_errors=True)

    # ---- E. 基点已记录 + lane 一笔 commit：绿（旧契约不变） ----
    repo, wt, base, branch = make_git_fixture()
    try:
        def g(*a):
            subprocess.run(["git", "-C", repo] + list(a), check=True,
                           capture_output=True, text=True)
        (Path(wt) / "docs").mkdir(parents=True, exist_ok=True)
        (Path(wt) / "docs" / "ticket-notes.md").write_text("judged\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-qm", "lane work")
        c = run_merge_check(wt, base, branch)
        ok(c is not None and c.get("green") is True, "E1 带 commit 泳道=绿（旧契约不变）")
    finally:
        shutil.rmtree(str(Path(repo).parent), ignore_errors=True)

    # ---- F. 畸形输入：base_ref 指向不存在的 sha（git 查询失败）⇒ fail-closed 红 ----
    repo, wt, base, branch = make_git_fixture()
    try:
        c = run_merge_check(wt, "0" * 40, branch)
        assert_named_red(c, "commit_query_failed", "F1 畸形基点 sha")
        if c:
            ok(NOT_PERSISTED not in item_text(c),
               "F2 查询失败不断言「实现未落盘」")
    finally:
        shutil.rmtree(str(Path(repo).parent), ignore_errors=True)

    print("PASS t261018-05 lane-commit-face-honesty pass=%d fail=%d"
          % (pass_n, fail_n))
    sys.exit(0 if fail_n == 0 else 1)


if __name__ == "__main__":
    main()
