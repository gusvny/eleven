#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_lane_identity_guard.py —— 泳道落盘身份依赖守卫回归（t260905-10 场景③，池=ro）。

intent（守护的用户可感知行为，灰盒 L3，260906 worker-02·03·05 settle 身份崩）：
- git 身份全缺（user.name/user.email 都没有）→ prepare_workspace 开工前 fail-fast：
  ok=False/action=failed，红字点名缺的是哪个键（报错必须精确）；
- 半缺（只有 user.name）→ 红字点名 user.email——「点名缺哪个」的精确性用半缺腿钉死；
- 身份在位（GLOBAL 提供）→ 复用不受扰（reused 正常）；
- repo 级补救：GLOBAL 空、身份在仓库 local config → 照样放行（探针锚在泳道
  worktree，天然覆盖 worktree 共享主仓 config 的补救承诺）；
- dir 型工作区无 commit → 不查身份，缺环境也放行（ensured）；
- created 路径缺失 → 失败且泳道不落半成品（fail-fast 在 worktree add 之前）；
- LANE_DEP_SYMLINKS 含 server/dsh/temporal-poc/.venv：泳道自动软链在位、解析到
  主仓、幂等不重复链（260825「泳道无消费方」拍板被 260906 19 号闸实测推翻，
  260824-12 依赖盲区闭合的陪伴断言）。

夹具：全部在 tmp 仓（git init + worktree add），身份用 GIT_CONFIG_GLOBAL/
GIT_CONFIG_NOSYSTEM 环境隔离（不碰真 HOME/系统配置）；deps 腿把引擎模块的
REPO_ROOT 指向 tmp 主仓（模拟「泳道属于本仓」，断言面仍是 prepare_workspace
回执与文件系统结果）。断言面=活动回执（ok/action/error）+ 泳道文件系统结果。

实现段落地前红属预期（TDD 信号）：守卫缺席 → 缺失腿照旧放行 → 场景红；
arbitrate/merge 期必须绿。

直跑：python3 integration/t260905-10/sc_lane_identity_guard.py（cwd=仓库根；
进程内夹具零网络零 docker；temporalio 缺席走回落链重执行）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_lane import (EXIT_ENV, Fail, ensure_poc_python, env_guard,  # noqa: E402
                      git_available, run_git, tmp_dir)

ensure_poc_python()

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/dsh/temporal-poc"))
import agent_activities  # noqa: E402
from shared import WorkspacePrep  # noqa: E402

GLOBAL_BOTH = "[user]\n\tname = 溯游值守\n\temail = duty@example.invalid\n"
GLOBAL_NAME_ONLY = "[user]\n\tname = 溯游值守\n"
GLOBAL_EMPTY = ""


def setup_main_repo(root: Path, name: str) -> Path:
    """建 tmp 主仓（initial commit 用 setup 专用 GLOBAL 身份；仓 local config 保持干净）。"""
    repo = root / name
    repo.mkdir(parents=True)
    run_git(["init", "-q"], repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    with env_guard(GIT_CONFIG_GLOBAL=str(_write_cfg(root, "setup.cfg", GLOBAL_BOTH)),
                   GIT_CONFIG_NOSYSTEM="1"):
        run_git(["add", "."], repo)
        run_git(["commit", "-q", "-m", "init"], repo)
    return repo


def add_worktree(repo: Path, lane: Path) -> None:
    with env_guard(GIT_CONFIG_GLOBAL=str(_write_cfg(repo.parent, "setup2.cfg", GLOBAL_BOTH)),
                   GIT_CONFIG_NOSYSTEM="1"):
        run_git(["worktree", "add", "-q", "-b", "lane/" + lane.name, str(lane)], repo)


def _write_cfg(root: Path, name: str, content: str) -> Path:
    p = root / name
    p.write_text(content, encoding="utf-8")
    return p


def prep(lane: Path, ws_type: str = "worktree", repo: Path = None):
    ws = None if ws_type is None else {"type": ws_type, "path": str(lane)}
    return asyncio.run(agent_activities.prepare_workspace(
        WorkspacePrep(ticket_id="t26090510-sc3", workspace=ws,
                      branch="lane/" + lane.name, base_ref="")))


def is_registered_worktree(repo: Path, lane: Path) -> bool:
    p = run_git(["worktree", "list", "--porcelain"], repo)
    return ("worktree %s" % lane) in p.stdout


def _missing_names(error: str) -> set:
    """从红字文案解析点名括注（「git 身份缺失（user.name、user.email）」）。
    处置句恒提 user.name/user.email 两键名，故必须解析点名括注才是「点名缺哪个」
    的精确断言面；解析不出=空集（断言会红，报错文案失去点名能力也是产品红）。"""
    marker = "git 身份缺失（"
    i = error.find(marker)
    if i < 0:
        return set()
    j = error.find("）", i)
    if j < 0:
        return set()
    return {x.strip() for x in error[i + len(marker):j].split("、") if x.strip()}


def main() -> int:
    f = Fail("t260905-10 场景③ 泳道落盘身份依赖守卫")
    if not git_available():
        print("ENV_FAIL: git CLI 缺席（身份守卫与泳道落盘都依赖 git，环境缺供）")
        return EXIT_ENV
    work = tmp_dir("sc-t26090510-id-")
    try:
        missing = {"GIT_CONFIG_GLOBAL": str(work / "empty.cfg"), "GIT_CONFIG_NOSYSTEM": "1"}
        (work / "empty.cfg").write_text(GLOBAL_EMPTY, encoding="utf-8")
        name_only = {"GIT_CONFIG_GLOBAL": str(_write_cfg(work, "name-only.cfg", GLOBAL_NAME_ONLY)),
                     "GIT_CONFIG_NOSYSTEM": "1"}
        both = {"GIT_CONFIG_GLOBAL": str(_write_cfg(work, "both.cfg", GLOBAL_BOTH)),
                "GIT_CONFIG_NOSYSTEM": "1"}

        repoA = setup_main_repo(work, "mainA")
        laneA = repoA / ".lane" / "sc3"
        add_worktree(repoA, laneA)  # 复用腿的既有泳道

        # ---- A 全缺：fail-fast 红字点名两个键 ----
        with env_guard(**missing):
            r = prep(laneA)
        f.check(r is not None and not r.ok and r.action == "failed",
                "A 身份全缺 → ok=False/action=failed（开工前点名，不是落盘才炸）")
        named_a = _missing_names(r.error if r is not None else "")
        f.check(named_a == {"user.name", "user.email"},
                "A 红字点名恰为缺的两个键（实得 %s）" % sorted(named_a))

        # ---- B 半缺：只缺 email，红字精确点名 user.email（处置句恒提两键名，
        #      子串断言吹不了精确性，必须解析点名括注）----
        with env_guard(**name_only):
            r2 = prep(laneA)
        named_b = _missing_names(r2.error if r2 is not None else "")
        f.check(named_b == {"user.email"},
                "B 半缺（只有 name）→ 红字精确点名 user.email（实得 %s）" % sorted(named_b))

        # ---- C 身份在位：复用不受扰 ----
        with env_guard(**both):
            r3 = prep(laneA)
        f.check(r3 is not None and r3.ok and r3.action.startswith("reused"),
                "C 身份在位 → 复用放行不受扰（action=reused）")

        # ---- D repo 级补救：GLOBAL 空但仓 local config 有身份 ----
        run_git(["config", "user.name", "溯游值守"], repoA)
        run_git(["config", "user.email", "duty@example.invalid"], repoA)
        with env_guard(**missing):
            r4 = prep(laneA)
        f.check(r4 is not None and r4.ok,
                "D GLOBAL 空但 repo 级 config 有身份 → 放行（探针锚泳道，覆盖共享 config）")
        run_git(["config", "--unset", "user.name"], repoA)
        run_git(["config", "--unset", "user.email"], repoA)

        # ---- E dir 型工作区不查身份 ----
        dirws = work / "dirws"
        dirws.mkdir(parents=True, exist_ok=True)
        with env_guard(**missing):
            r5 = prep(dirws, ws_type="dir")
        f.check(r5 is not None and r5.ok and r5.action == "ensured",
                "E dir 型工作区无 commit → 不查身份照常 ensured")

        # ---- F created 路径缺失：失败且泳道不落半成品 ----
        repoB = setup_main_repo(work, "mainB")
        laneB = repoB / ".lane" / "sc3new"
        with env_guard(**missing):
            r6 = prep(laneB)
        f.check(r6 is not None and not r6.ok and r6.action == "failed",
                "F created 路径身份缺失 → failed")
        f.check(not is_registered_worktree(repoB, laneB),
                "F 泳道未落半成品（worktree 未注册=fail-fast 在 add 之前）")

        # ---- G deps 软链：LANE_DEP_SYMLINKS 含 temporal-poc/.venv，幂等 ----
        venv_src = repoA / "server" / "dsh" / "temporal-poc" / ".venv"
        (venv_src / "bin").mkdir(parents=True, exist_ok=True)
        (venv_src / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        # 依赖目录链在真实仓库是 tracked 目录（随 checkout 出现在泳道）；fixture 仓
        # 只有 README，泳道内没有目录链 → symlink ENOENT。补链=还原真实形态。
        (laneA / "server" / "dsh" / "temporal-poc").mkdir(parents=True, exist_ok=True)
        (laneA / "app").mkdir(parents=True, exist_ok=True)
        link = laneA / "server" / "dsh" / "temporal-poc" / ".venv"
        saved_root = agent_activities.REPO_ROOT
        try:
            agent_activities.REPO_ROOT = repoA
            with env_guard(**both):
                r7 = prep(laneA)
            f.check(r7 is not None and "+deps:server/dsh/temporal-poc/.venv" in (r7.action or ""),
                    "G prepare_workspace 回执含 deps:temporal-poc/.venv（泳道自动软链）")
            f.check(link.is_symlink() and (link / "bin" / "python").exists(),
                    "G 软链在位且解析到主仓（marker 经链可读）")
            with env_guard(**both):
                r8 = prep(laneA)
            f.check(r8 is not None and r8.ok and "+deps:" not in (r8.action or ""),
                    "G 再跑幂等：已链接不重复（回执不带 +deps）")
        finally:
            agent_activities.REPO_ROOT = saved_root
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    return f.exit_code()


if __name__ == "__main__":
    sys.exit(main())
