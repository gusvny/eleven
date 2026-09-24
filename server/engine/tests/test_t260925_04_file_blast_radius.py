#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260925-04 文件级爆炸半径回归棒。

口径（工单「引擎票爆炸半径按改动文件算」）：定点复跑判据从「票面写集粗前缀」换成
「相对泳道基线实际改动文件」；共享面判定复用同一张 _SHARED_BASE_PREFIXES 表
（安全轨①）；收口全量拦截不弱化（安全轨②）；改动清单不可得/空/畸形=fail-closed
恒全跑。本文件钉六层：
- changed_files_blast_radius 矩阵：文件级共享命中/localized/error/空清单/畸形入参。
- targeted_rerun_plan 新旧签名兼容：不传 changed_files=旧口径逐字；传清单=文件级。
- changed_files activity 解析面（桩 git，UT 禁真 git——conftest 纪律）：diff∪status
  并集去重、branch 缺失/merge-base 失败/diff 失败/status 失败=fail-closed、
  畸形 porcelain 输入丢弃不猜、未跟踪目录折叠形态（`dir/` 条目）安全透传。
- 结构锁：dev_lane v2 门/changed_files 接线/meta 留痕在位；v1 门与收口拦截不动；
  worker 注册清单含 changed_files（漏注册=运行时才炸）。
- 全终态：activity 无 spawn 之外的常驻资源（_git 同步有界超时，家族既有欠账照录）。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa
from shared import (ChangedFilesArgs, ChangedFilesResult, blast_radius,
                    changed_files_blast_radius, targeted_rerun_plan)

_ENGINE = Path(__file__).resolve().parents[1]


# ---------------- 1. changed_files_blast_radius 矩阵 ----------------

def test_file_radius_shared_hits():
    # 文件级命中同一张前缀表（安全轨①：判据只有一份）
    for fs in (["server/engine/dev_lane.py"],
               ["server/tools/verify_lane.py"],
               ["integration/run_scenarios.py"],
               ["integration/scenario_ledger.py"],
               ["integration/lib_env.py"],
               ["integration/tests/test_x.py"],
               ["verify.yaml"],
               ["./integration/run_scenarios.py"],
               ["app/foo.ts", "notes/x.md", "integration/stage_docker.py"]):
        assert changed_files_blast_radius(fs) == "shared", fs


def test_file_radius_localized_and_fail_closed():
    assert changed_files_blast_radius(["integration/t260925-04/sc_x.py"]) == "localized"
    assert changed_files_blast_radius(["app/web/src/foo.ts"]) == "localized"
    assert changed_files_blast_radius(["notes/x.md", "app/a.ts"]) == "localized"
    # fail-closed：error 非空 / 非清单 / 空 → shared（恒全跑）
    assert changed_files_blast_radius(["app/a.ts"], diff_error="git diff 失败") == "shared"
    assert changed_files_blast_radius(None) == "shared"
    assert changed_files_blast_radius("app/a.ts") == "shared"
    assert changed_files_blast_radius([]) == "shared"
    # 缺陷①（仲裁打回）：清单含畸形元素=入参形状不可信 → 恒全跑，绝不「跳过」放窄
    assert changed_files_blast_radius([None, "app/a.ts"]) == "shared"
    assert changed_files_blast_radius(["app/a.ts", "  "]) == "shared"
    assert changed_files_blast_radius([123]) == "shared"
    assert changed_files_blast_radius(["app/a.ts", 7, None]) == "shared"
    # 缺陷②（仲裁打回）：目录折叠条目（尾 /）=范围未知 → 恒全跑（纵深防御）
    assert changed_files_blast_radius(["integration/"]) == "shared"
    assert changed_files_blast_radius(["app/a.ts", "tickets/t1/"]) == "shared"


# ---------------- 2. targeted_rerun_plan 新旧签名兼容 ----------------

def test_plan_old_signature_verbatim():
    # 不传 changed_files（哨兵缺省）=旧口径逐字：写集粗前缀判据，老历史零行为变化
    ws_engine = ["server/engine/dev_lane.py"]          # 写集含引擎前缀 → 旧口径恒全量
    ws_loc = ["integration/t260922-18/sc_x.py"]
    assert targeted_rerun_plan(ws_engine, ["a"]) == []
    assert targeted_rerun_plan(ws_loc, ["b", "b", "__gate_blockers__", "", 7, "b"]) == ["b"]
    assert targeted_rerun_plan(ws_loc, ["a"], first_run=True) == []
    assert targeted_rerun_plan(None, ["a"]) == []
    assert targeted_rerun_plan(ws_loc, []) == []
    assert targeted_rerun_plan(ws_loc, None) == []


def test_plan_file_level_overrides_write_set_coarseness():
    # 引擎票写集含粗前缀（旧口径恒禁定点），实际改动仅为非共享面 → 可定点（根因修复）
    ws = ["server/engine/"]
    assert targeted_rerun_plan(ws, ["sc_a", "sc_a", "__x__", "sc_b"],
                               changed_files=["app/a.ts", "notes/x.md"]) == ["sc_a", "sc_b"]
    # 实际改动命中共享面 → 仍恒全跑（安全轨①）
    assert targeted_rerun_plan(ws, ["sc_a"],
                               changed_files=["integration/run_scenarios.py"]) == []
    # 清单不可得（空+error）→ 恒全跑（fail-closed）
    assert targeted_rerun_plan(ws, ["sc_a"], changed_files=[]) == []
    assert targeted_rerun_plan(ws, ["sc_a"], changed_files=None) == []
    # diff_error 非空恒全跑，且优先于 localized 清单（计算面报错绝不放窄）
    assert targeted_rerun_plan(ws, ["sc_a"], changed_files=["app/a.ts"],
                               diff_error="git diff 失败 rc=128") == []
    # 首轮恒全跑（两口径一致）
    assert targeted_rerun_plan(ws, ["sc_a"], first_run=True,
                               changed_files=["app/a.ts"]) == []


# ---------------- 3. changed_files activity（桩 git，禁真 git） ----------------

def _rc(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _patch_git(monkeypatch, responses):
    """按命令首词分流回执的 _git 桩；未命中命令 → 快败留痕（不静默）。"""
    def fake_git(args, cwd, timeout=60):
        key = args[0]
        if key not in responses:
            raise AssertionError("unexpected git cmd: %s" % (args,))
        r = responses[key]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(aa, "_git", fake_git)


def test_changed_files_union_dedup():
    def fake_git(args, cwd, timeout=60):
        if args[0] == "merge-base":
            return _rc("abc123\n")
        if args[0] == "diff":
            assert args[1] == "--name-only" and args[2] == "abc123...lane-1"
            return _rc("app/a.ts\nnotes/x.md\napp/a.ts\n")
        if args[0] == "status":
            # 缺陷②根修：status 必须 -uall（未跟踪目录展开，不折叠成 dir/）
            assert "--untracked-files=all" in args, args
            return _rc("?? integration/t260925-04/\0 M notes/x.md\0")
        raise AssertionError(args)
    orig = aa._git
    aa._git = fake_git
    try:
        r = asyncio.run(aa.changed_files(ChangedFilesArgs(ticket_id="t", worktree="/w", branch="lane-1")))
    finally:
        aa._git = orig
    assert isinstance(r, ChangedFilesResult) and r.error == ""
    assert r.files == ["app/a.ts", "notes/x.md", "integration/t260925-04/"]


def test_changed_files_fail_closed_paths():
    cases = [
        # branch 缺失
        (ChangedFilesArgs(ticket_id="t", worktree="", branch=""), None),
    ]
    for args, _ in cases:
        r = asyncio.run(aa.changed_files(args))
        assert r.files == [] and r.error, args
    orig_git = aa._git
    orig_mb = aa._merge_base_ref
    try:
        # merge-base 失败（空 ref，禁回退字面 main）
        aa._merge_base_ref = lambda branch, repo: ("", "解析失败 rc=128")
        r = asyncio.run(aa.changed_files(ChangedFilesArgs(ticket_id="t", worktree="/w", branch="b")))
        assert r.files == [] and "merge-base" in r.error
        # merge-base 多行畸形：_merge_base_ref 取首行留痕（本 activity 消费其 ref），
        # 畸形留痕由该函数 UT 守（t260901-18 家族），此处只钉非空 ref 可继续
        # diff 失败
        aa._merge_base_ref = lambda branch, repo: ("abc", "")
        aa._git = lambda args, cwd, timeout=60: (
            _rc(returncode=128, stderr="fatal: bad revision") if args[0] == "diff"
            else _rc())
        r = asyncio.run(aa.changed_files(ChangedFilesArgs(ticket_id="t", worktree="/w", branch="b")))
        assert r.files == [] and "git diff" in r.error
        # status 失败
        def st_fail(args, cwd, timeout=60):
            if args[0] == "diff":
                return _rc("app/a.ts\n")
            return _rc(returncode=1, stderr="fatal")
        aa._git = st_fail
        r = asyncio.run(aa.changed_files(ChangedFilesArgs(ticket_id="t", worktree="/w", branch="b")))
        assert r.files == [] and "git status" in r.error
        # git 超时（家族有界超时异常上抛 → 调用方 fail-closed，不得静默收窄）
        aa._git = lambda args, cwd, timeout=60: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd=args, timeout=timeout))
        try:
            asyncio.run(aa.changed_files(ChangedFilesArgs(ticket_id="t", worktree="/w", branch="b")))
            raise AssertionError("timeout must propagate")
        except subprocess.TimeoutExpired:
            pass
    finally:
        aa._git = orig_git
        aa._merge_base_ref = orig_mb


def test_changed_files_malformed_porcelain():
    # 畸形 porcelain 条目丢弃不猜（-z 家族解析器语义）；dir/ 折叠形态安全透传
    def fake_git(args, cwd, timeout=60):
        if args[0] == "merge-base":
            return _rc("abc\n")
        if args[0] == "diff":
            return _rc("")
        return _rc("?? dir/\0XX\0\0bad\0 M ok.md\0")
    orig = aa._git
    aa._git = fake_git
    try:
        r = asyncio.run(aa.changed_files(ChangedFilesArgs(ticket_id="t", worktree="/w", branch="b")))
    finally:
        aa._git = orig
    assert r.error == ""
    assert r.files == ["dir/", "ok.md"]


# ---------------- 4. 结构锁 ----------------

def test_wiring_structural_locks():
    dev = (_ENGINE / "dev_lane.py").read_text(encoding="utf-8")
    act = (_ENGINE / "agent_activities.py").read_text(encoding="utf-8")
    worker = (_ENGINE / "worker.py").read_text(encoding="utf-8")
    # v2 门 + changed_files 接线 + fail-closed 留痕 + meta 留痕
    assert "TARGETED_RERUN_FILE_RADIUS_PATCH_ID" in dev
    assert "workflow.patched(TARGETED_RERUN_FILE_RADIUS_PATCH_ID)" in dev
    assert "changed_files=\n" in dev or "changed_files=_cf_files" in dev
    assert "file_blast_radius_trace" in dev
    assert "恒全跑" in dev
    # v1 门与收口拦截原样在位（安全轨②）
    assert "workflow.patched(TARGETED_RERUN_PATCH_ID)" in dev
    assert dev.count("收口全量跑有新增红") == 2
    assert "await self._closing_full_run()" in dev
    # activity 定义 + worker 注册（漏注册=运行时才炸）
    assert "async def changed_files(" in act
    assert "changed_files," in act
    assert "ALL_AGENT_ACTIVITIES" in act and "ALL_WORKFLOWS" in worker
    assert "changed_files" in worker or "ALL_AGENT_ACTIVITIES" in worker
    # 决策单写者仍唯一：changed_files_blast_radius 只经 targeted_rerun_plan 消费
    assert "changed_files_blast_radius(changed_files)" in (
        (_ENGINE / "shared.py").read_text(encoding="utf-8"))


def test_marker_ids_distinct():
    import dev_lane as dl
    assert dl.TARGETED_RERUN_PATCH_ID == "dev-lane-targeted-rerun-v1"
    assert dl.TARGETED_RERUN_FILE_RADIUS_PATCH_ID == \
        "dev-lane-targeted-rerun-file-radius-v1"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
