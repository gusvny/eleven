#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-13 集成测试共享夹具：临时仓复现「粗粒度声明 × 实际 UI diff」判定面（KI-044）。

造仓形态（黑盒，对齐 t260904-05 实证——写集只声明 server/dsh/workbench/ 父目录、
实际改的是会话区 UI 产物，旧声明口径前缀匹配不命中 → 判「非 UI 票」全绿直过）：
  main 初始 commit A（建票锚点）→ lane 分支提交本票改动（可参数化）→
  main 侧他人改 UI（模拟泳道并入 main 的他人文件，t260901-16 同族）。
定稿口径的 diff 源 = `git diff --name-only <merge-base(main,lane)>...lane` 三点口径，
本夹具直接产出该路径清单供场景断言（夹具自证 diff 源，与被测实现无关）。

环境适配：系统 python3 可 import shared（纯标准库依赖面）；temporalio 在泳道
worktree 不可用（t260901-16 t05 同族结论），activity/workflow 接线面以源码契约
结构锁落地（本目录场景文件，宽容正则不锚行号）。

本文件不带 sc_ 前缀 = 共享夹具代码，不进 SCENARIOS 清单（run_scenarios.py 约定）。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]          # integration/t260904-13 → 仓库根
POC = REPO / "server" / "dsh" / "temporal-poc"

sys.path.insert(0, str(POC))


def _git(*args, cwd):
    """跑 git（core.quotepath=false 锁非 ASCII 文件名不转义，t260901-16 同款）。"""
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr[-300:])
    return p.stdout


def build_lane_repo(lane_files, main_files=None):
    """建临时仓：main 锚点 commit A + lane 本票改动 + main 侧他人改动。

    lane_files / main_files: {相对路径: 文本内容}；返回
    (repo_path, merge_base_sha, lane_diff_paths)——lane_diff_paths 即定稿口径的
    三点 diff 路径清单（merge-base(main,lane)...lane），夹具自证供场景断言。
    用完由调用方 shutil.rmtree。
    """
    tmp = Path(tempfile.mkdtemp(prefix="t260904-13-itest-"))

    def g(*a):
        return _git(*a, cwd=tmp)

    g("init", "-b", "main")
    g("config", "user.email", "itest@example.com")
    g("config", "user.name", "itest")
    (tmp / "base.txt").write_text("base\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "A: 建票锚点")

    # lane 分支：本票实际改动（「实际写面」——KI-044 判定源的真身）
    g("checkout", "-b", "lane")
    for rel, text in (lane_files or {}).items():
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "lane: 本票改动")

    # main 侧他人改动（泳道之外——三点 diff 必须看不见）
    if main_files:
        g("checkout", "main")
        for rel, text in main_files.items():
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        g("add", "-A")
        g("commit", "-m", "main: 他人改动")
        g("checkout", "lane")

    merge_base = g("merge-base", "main", "lane").strip()
    diff_out = g("diff", "--name-only", "%s...lane" % merge_base)
    lane_diff_paths = [ln.strip() for ln in diff_out.splitlines() if ln.strip()]
    return tmp, merge_base, lane_diff_paths


def summary(passed, failed):
    """套件输出约定（t260901-16 同款）：SUMMARY 行 + exit 码。"""
    print("SUMMARY pass=%d skip=0 fail=%d" % (passed, failed))
    return 0 if failed == 0 else 1
