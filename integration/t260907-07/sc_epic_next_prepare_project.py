#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_epic_next_prepare_project.py — 立项预跑读档案项目感知接线（t260907-07 同票接线面）。

intent（用户可感知行为）：merge 收口的立项下一单预跑（prepare_epic_next）不再对外部
项目静默跳过——带 project 时读到**该项目主目录**的立项全文（exists=True+全文匹配）；
不串桶（engine 异名对 external 档案缺失 exists=False）；project 空=引擎锚兜底（在飞
工单旧载荷兼容，真仓只读可验）且 env SUYOU_EPICS_DIR 优先于兜底命中（自测语义）；
档案缺失/代号形状非法 exists=False 软失败不炸（防穿回归）。

与 selfcheck E 段（env 夹具单点自测）intent 不同面：本场景守 activity 入口×项目感知
接线×不串桶。查 Temporal 的 _epic_ticket_rows 以 monkeypatch 桩替（workflow 边界，
selfcheck E 同款先例，不入其 intent）。temporalio SDK 缺席=ENV_FAIL exit 2。
Run: python3 integration/t260907-07/sc_epic_next_prepare_project.py（cwd=仓库根）
三态：末行 SUMMARY 四计数；exit 0/1/2。
"""
import asyncio
import dataclasses
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "server", "dsh", "temporal-poc"))
sys.path.insert(0, _HERE)

import epic_fixture as fx  # noqa: E402

passed, failed, env_failed = 0, 0, 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label, flush=True)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, " — " + str(detail)[:200] if detail else ""), flush=True)
    return cond


EPIC_MD = "# 立项单 gap-b\n\n外部项目主目录立项全文（场景专用体）。\n"
ENV_MD = "# 立项单 env-only\n\nenv 夹具立项全文。\n"


async def _fake_rows(epic):
    return [{"id": "t26090707-p-fake", "status": "closed", "closed": True}]


def main():
    print("== t260907-07 ④立项预跑读档案项目感知接线")
    try:
        import temporalio  # noqa: F401
    except ImportError:
        # 供给自升级（仲裁 gen0：闸内 system python3 缺 SDK=环境红）：SDK 在引擎
        # venv 时换解释器重入（与 verify.yaml test check 的 venv 回落同款口径）。
        # 防递归用 env 标记而非 realpath 比对——venv python 常是共享二进制的符号链
        # （venv 语义靠调用路径+pyvenv.cfg 生效），realpath 会误判成同一解释器。
        venv = os.path.join(_REPO, "server", "dsh", "temporal-poc", ".venv", "bin", "python")
        if os.path.isfile(venv) and not os.environ.get("T26090707_VENV_REENTRY"):
            os.execve(venv, [venv, os.path.abspath(__file__)],
                      dict(os.environ, T26090707_VENV_REENTRY="1"))
        print("  ENV_FAIL: temporalio SDK 缺失（优先 server/dsh/temporal-poc/.venv/bin/python）",
              flush=True)
        print("SUMMARY pass=%d fail=%d env_fail=1 na=0" % (passed, failed), flush=True)
        return 2
    import agent_activities
    from shared import EpicNextPrepArgs

    if "project" not in {f.name for f in dataclasses.fields(EpicNextPrepArgs)}:
        print("  FAIL EpicNextPrepArgs.project 未落地（实现未合入，TDD 预期红）", flush=True)
        print("SUMMARY pass=0 fail=1 env_fail=0 na=0", flush=True)
        return 1

    orig_rows = agent_activities._epic_ticket_rows
    agent_activities._epic_ticket_rows = _fake_rows
    env_root = tempfile.mkdtemp(prefix="t26090707-prep-env-")
    env_dir = os.path.join(env_root, "notes", "epics")
    os.makedirs(env_dir)
    with open(os.path.join(env_dir, "env-only.md"), "w") as f:
        f.write(ENV_MD)
    saved_env = os.environ.get("SUYOU_EPICS_DIR")
    try:
        with fx.RegistryEnv() as reg:
            ext = fx.make_project(reg.root, "external")
            fx.write_epic(ext, "gap-b", EPIC_MD)
            eng = fx.make_project(reg.root, "engine")
            fx.write_epic(eng, "engine-only")

            def prep(project, epic):
                return asyncio.run(agent_activities.prepare_epic_next(
                    EpicNextPrepArgs(ticket_id="t26090707-p", epic=epic, project=project)))

            # ---- A 外部项目：读到其主目录立项全文（验收核心接线面） ----
            r = prep("external", "gap-b")
            check(r.exists and r.epic_markdown == EPIC_MD,
                  "A external 预跑读到其主目录立项全文", "exists=%s" % r.exists)
            check(r.state_key != "", "A2 state_key 仍可算（关联行桩在）")

            # ---- B 不串桶 ----
            r = prep("external", "engine-only")
            check(r.exists is False, "B engine 异名对 external 档案缺失 exists=False（不串桶）")

            # ---- C project 空：引擎锚兜底（真仓只读，缺档 exists=False 不炸） ----
            os.environ.pop("SUYOU_EPICS_DIR", None)
            r = prep("", "absent-code-no-such")
            check(r.exists is False, "C project 空=引擎锚兜底可达且缺档软失败（只读）")

            # ---- D env 优先于兜底：project 空 + env 夹具 → env 桶命中 ----
            os.environ["SUYOU_EPICS_DIR"] = env_dir
            r = prep("", "env-only")
            check(r.exists and r.epic_markdown == ENV_MD,
                  "D project 空 + env 覆盖：env 桶命中（优先于引擎锚兜底）")

            # ---- E 档案缺失 / 形状非法：软失败防穿 ----
            r = prep("external", "nope-code")
            check(r.exists is False, "E1 external 档案缺失 exists=False（软失败总则）")
            r = prep("external", "../etc")
            check(r.exists is False, "E2 代号形状非法 exists=False（防穿回归）")
    finally:
        agent_activities._epic_ticket_rows = orig_rows
        if saved_env is None:
            os.environ.pop("SUYOU_EPICS_DIR", None)
        else:
            os.environ["SUYOU_EPICS_DIR"] = saved_env

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
