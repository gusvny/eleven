#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_epic_cli_ticket_start.py — 开票入口 epic 校验项目感知用户路径（t260907-07 验收①②）。

intent（用户可感知行为）：外部项目 ticket-start 关联**其自己主目录**的立项单成功
（改造前误报「立项代号不存在」）；引擎桶项目行为不变（同名+异名照常关联）；
负路径连接前拒收——epic 确缺时红因文案带该项目实际查询目录（诊断信息）、
未知/缺 project 拒收文案互辨（KI-032 硬闸面回归）。

负路径子用例零 Temporal 依赖可真跑（校验单点在 connect 之前——client.py:418 在
_connect 之前的既定闸序）；正路径子用例经 docker 测试台（t260904-19 单点搭台纪律，
复用 t260904-02/lib_gate）：被测 env 显式清 SANDBAR_EPICS_DIR（防宿主 env 泄漏
改判锚点），显式 SANDBAR_TARGET_HOST 指台（建票类测试绝不连生产，README 红线）。

Run: python3 integration/t260907-07/sc_epic_cli_ticket_start.py（cwd=仓库根）
三态：末行 SUMMARY 四计数；exit 0/1/2（docker/镜像/SDK/隔离台库缺席=ENV_FAIL exit 2）。
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)                                   # epic_fixture
sys.path.insert(0, os.path.join(_REPO, "integration"))      # stage_docker
sys.path.insert(0, os.path.join(_REPO, "integration", "t260904-02"))  # lib_gate

import epic_fixture as fx  # noqa: E402
from lib_gate import (Fail, cleanup, parse_out_json, poc_python,  # noqa: E402
                      require_bench, require_stage, run_poc_client,
                      stage_down, wait_port_released)

passed, failed, env_failed = 0, 0, 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label, flush=True)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, " — " + str(detail)[:240] if detail else ""), flush=True)
    return cond


def client_env(reg, stage=None):
    """被测 client 子进程 env：注册表指夹具；epics/legacy env 必清（防宿主泄漏改判锚）。"""
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = reg
    env.pop("SANDBAR_EPICS_DIR", None)
    env.pop("SANDBAR_PROJECTS_YAML", None)
    if stage:
        env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
        env["SANDBAR_NAMESPACE"] = stage["namespace"]
    else:
        env.pop("SANDBAR_TARGET_HOST", None)
        env.pop("SANDBAR_NAMESPACE", None)
    return env


def start_ticket(py, env, tid, project, epic):
    args = {"ticket_id": tid, "template_id": "dev-lane", "project": project,
            "title": "t260907-07 epic 项目感知场景票", "write_set": ["integration/"],
            "epic": epic}
    rc, out = run_poc_client(py, "ticket-start", args, env)
    try:
        payload = parse_out_json(out)
    except Exception:
        payload = {}
    return rc, payload, out


def main():
    print("== t260907-07 ③开票入口 epic 校验项目感知（验收①②用户路径）")
    fail = Fail("t260907-07 epic-cli-ticket-start")
    try:
        bench = require_bench(fail)
    except SystemExit:
        print("SUMMARY pass=%d fail=%d env_fail=1 na=0" % (passed, failed), flush=True)
        return 2
    py = poc_python(bench)
    reg = tempfile.mkdtemp(prefix="t26090707-cli-reg-")
    eng = fx.make_project(reg, "engine")
    ext = fx.make_project(reg, "external")
    fx.write_epic(eng, "gap-b")
    fx.write_epic(ext, "gap-b")
    fx.write_epic(eng, "engine-only")
    fx.write_epic(ext, "external-only")
    ext_epics = str(ext / "notes" / "epics")
    eng_epics = str(eng / "notes" / "epics")
    stage = None
    try:
        # ---- N 负路径（连接前拒收，零 Temporal 依赖）----
        # 契约口径：client 对结构化失败进程退出码 0，失败面=payload ok:false+error
        # （runAdminCli「成功/结构化失败原样透传」），断言锚 payload 不锚 rc。
        env0 = client_env(reg)
        rc, payload, out = start_ticket(py, env0, "t26090707-cli-n1", "external", "missing-code")
        check(payload.get("ok") is False and "立项代号不存在" in out and ext_epics in out,
              "N1 external 确缺 epic：连接前拒收且文案带 external 实际目录", out[-240:])
        rc, payload, out = start_ticket(py, env0, "t26090707-cli-n2", "external", "engine-only")
        check(payload.get("ok") is False and eng_epics not in out,
              "N2 不串桶：engine 异名对 external 拒收且不误指 engine 目录", out[-240:])
        rc, payload, out = start_ticket(py, env0, "t26090707-cli-n3", "no-such-project", "")
        check(payload.get("ok") is False and "拒收" in out and "no-such-project" in out,
              "N3 未知 project 拒收（KI-032 硬闸面回归）", out[-240:])

        # ---- S 正路径（docker 测试台） ----
        tag = str(os.getpid())
        try:
            stage_mod, stage_state = require_stage(fail, "t26090707-epic-cli-%s" % tag,
                                                   "t26090707-epic-cli-%s" % tag)
        except SystemExit:
            print("SUMMARY pass=%d fail=%d env_fail=1 na=0" % (passed, failed), flush=True)
            return 2
        stage = stage_state
        env_s = client_env(reg, stage=stage_state)
        for tid, key, epic, label in (
                ("t26090707-cli-s1", "external", "gap-b",
                 "S1 验收①：external 关联自己主目录同名立项单开票成功"),
                ("t26090707-cli-s2", "external", "external-only",
                 "S2 external 异名自桶开票成功"),
                ("t26090707-cli-s3", "engine", "gap-b",
                 "S3 验收②：engine 同名开票成功（行为不变）"),
                ("t26090707-cli-s4", "engine", "engine-only",
                 "S4 engine 异名自桶开票成功（行为不变）")):
            rc, payload, out = start_ticket(py, env_s, tid, key, epic)
            check(rc == 0 and payload.get("ok") is True, label, out[-240:])
    finally:
        if stage is not None:
            stage_down(stage_mod, stage["project"])
            try:
                wait_port_released(stage["ports"]["temporal"])
            except Exception as e:
                check(False, "teardown 端口释放", str(e)[:160])
        cleanup(reg)

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed), flush=True)
    if failed:
        print("FAIL  t260907-07 epic-cli-ticket-start：%d 项断言未过" % failed, flush=True)
        return 1
    print("PASS  t260907-07 epic-cli-ticket-start", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
