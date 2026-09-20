#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-02 集成场景（板面半张）：历史票三态降级可见性契约（真 docker 台）。

intent（登记于 run_scenarios.py，名 t260916-02-board-legacy-three-state）：
  票号 t 形化 + 板面白名单改两路查询（SA 查询路径 + legacy 查询路径）之后，工单板面对三代票的
  用户可感知契约（口径⑤：老票显式降级可辨，不许静默丢失或误归项目）：
  ① 20 前老票（旧形 id，无任何项目 SA）：经 legacy 查询路径仍上板——行 project 空且显式
    点名「历史票·无项目身份」（legacy_unowned 面），绝不静默丢弃；
  ② 20 后迁移前旧形票（旧形 id，有 ProjectKey 无实例/期 SA）：legacy 查询路径收进，行标
    legacy_id 面、project==SA 值（不误归他项目）、match_via=legacy_id 可观测；
  ③ 白名单判定走聚合声明（零 env 覆盖层）：旧形票实例在册才上板——不在册旧形 id
    （僵尸形态）两种形态都不上板（R2 防僵尸收益在 legacy 查询路径保持）；
  ④ 合并可观测：行带 match_via（sa|legacy_id），SA 查询路径新票与 legacy 查询路径旧票在同一板面
    合并呈现（两路查询+合并的承接面）。

分工（防 intent 级重复）：
  · t260915-08-board-rows 守巡检行形状契约（快照注入对拍、R8 闭合窗）——彼时票全旧
    形无 SA、行 project 恒空，不在其断言面；本条守三态降级与两路合并可见性；
  · t260916-02-relocation-realchain 守新票（t 形+全 SA）链路与板面归板；本条只造历史
    票夹具（直发旧形 id），不重测新票链路；
  · 真值表全组合（新/20后/20前 × 在册/僵尸 × 窗口）的离线对拍归 developer L1；本条
    守用户可见的板面行为；
  · t260915-20-project-identity-realchain 的无主票守卫（直发旧 payload 被 patched
    worker 判 blocked）守的是「起票面」，本条守「板面读面」，不同维。

三态：PASS exit 0 / FAIL exit 1（产品红，缺什么点名什么）/ ENV_FAIL exit 2
（docker 测试台/temporal CLI/temporalio 缺件=环境红点名，不假红不假绿）。
实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260916-02/sc_inspection_board_legacy_rows.py
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260916-02"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

import lib_relocation as lr  # noqa: E402
from lib_inspection import (  # noqa: E402
    cleanup_tickets, die_env, die_fail, note_started_ticket, run_client,
)

try:
    import temporalio  # noqa: F401——SDK 直发需要；缺席=环境红
except Exception:  # noqa: BLE001
    die_env("temporalio SDK 缺席（server/engine/.venv 不可用）——真链路子用例无法执行")

STATS = {"pass": 0, "fail": 0}
FAILS = []
PID = os.getpid()
KEY_A = "bla%d" % PID
INST_A = "bla-ins-%d" % PID
L1_ID = "inspection-%s-20260101" % INST_A    # 20 前：无任何 SA
L2_ID = "inspection-%s-20260102" % INST_A    # 20 后迁移前：仅 ProjectKey
L3_ID = "inspection-bla-zzz-20260103"        # 僵尸形态：实例不在册
ENV = {}


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


def start_legacy(queue, wid, with_project_key):
    """直发旧形 id 的历史票夹具（workerless RUNNING：板面行来自列表面，不依赖快照）。

    L2 盖 ProjectKey SA（t260915-20 语义）；L1 零 SA（20 前形态）。SA 参数名在
    temporalio 各代有 typed/plain 两形态——两形态依序回退（客户端公开面，非内部桩）。"""
    from inspection_flow import InspectionPeriodicInput

    async def _start():
        from temporalio.client import Client
        client = await Client.connect(lr.TEST_TARGET_HOST, namespace=lr.TEST_NAMESPACE)
        kwargs = dict(id=wid, task_queue=queue)
        if with_project_key:
            from temporalio.common import SearchAttributeKey, SearchAttributePair, \
                TypedSearchAttributes
            sa = TypedSearchAttributes([SearchAttributePair(
                SearchAttributeKey.for_keyword(lr.SA_PROJECT), KEY_A)])
            try:
                await client.start_workflow(
                    "InspectionPeriodicWorkflow",
                    InspectionPeriodicInput(instance_id=INST_A, period="20260102",
                                            face="test"),
                    search_attributes=sa, **kwargs)
                return
            except TypeError:
                pass
            await client.start_workflow(
                "InspectionPeriodicWorkflow",
                InspectionPeriodicInput(instance_id=INST_A, period="20260102",
                                        face="test"),
                typed_search_attributes=sa, **kwargs)
            return
        await client.start_workflow(
            "InspectionPeriodicWorkflow",
            InspectionPeriodicInput(instance_id=INST_A, period="20260101", face="test"),
            **kwargs)

    try:
        asyncio.run(_start())
    except Exception as e:  # noqa: BLE001——AlreadyStarted（上轮残留）=隔离台内去重，可继续判读
        if "already started" not in str(e).lower():
            check("夹具直发旧形票 %s" % wid, False, "%s: %s" % (type(e).__name__, e))
            return False
    note_started_ticket(wid)
    return True


def board_blob():
    _, parsed = run_client("ticket-list", {"kind": "inspection"}, env=dict(ENV))
    return parsed if isinstance(parsed, dict) else {}, \
        json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else ""


def row_of(parsed, tid):
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    rows = (res or {}).get("tickets") if isinstance(res, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("id") == tid:
            return r
    return None


def main() -> int:
    lr.precheck_stage()

    tmp = tempfile.mkdtemp(prefix="sandbar-t26091602b-")
    reg_root = os.path.join(tmp, "projects")
    os.makedirs(reg_root, exist_ok=True)
    try:
        # 白名单真源=聚合声明（零 env 覆盖层）：PA 仓根声明在册实例 INST_A
        lr.write_registry(reg_root, KEY_A, "LegacyA", [os.path.join(tmp, "wa")])
        lr.write_file(os.path.join(tmp, "wa", "inspection.yaml"),
                      lr.decl_yaml([(INST_A, KEY_A, lr.RARE_CRON, "test")]))

        queue = "sandbar-ticket-insbl-%d" % PID
        ENV.update({"SANDBAR_PROJECTS_DIR": reg_root, "SANDBAR_TASK_QUEUE": queue})
        try:
            ok1 = start_legacy(queue, L1_ID, with_project_key=False)
            ok2 = start_legacy(queue, L2_ID, with_project_key=True)
            ok3 = start_legacy(queue, L3_ID, with_project_key=False)
            parsed, blob = board_blob()
            row1, row2, row3 = row_of(parsed, L1_ID), row_of(parsed, L2_ID), row_of(parsed, L3_ID)

            check("B1a 20 前老票（无 SA）仍上板（不许静默丢失）",
                  ok1 and row1 is not None,
                  "夹具=%s 行在场=%s" % (ok1, row1 is not None))
            r1 = json.dumps(row1, ensure_ascii=False) if row1 else ""
            check("B1b 20 前老票显式点名「历史票·无项目身份」且 project 空（不误归）",
                  (row1 or {}).get("legacy_unowned") is True
                  or ("无项目身份" in r1 and "历史票" in r1),
                  "legacy_unowned=%r 行=%s"
                  % ((row1 or {}).get("legacy_unowned"), r1[:160]))
            check("B1c 20 前老票 project 空（绝不误归项目）",
                  str((row1 or {}).get("project") or "") == "",
                  "project=%r" % (row1 or {}).get("project"))

            check("B2a 20 后旧形票（有 ProjectKey）legacy 查询路径上板",
                  ok2 and row2 is not None,
                  "夹具=%s 行在场=%s" % (ok2, row2 is not None))
            check("B2b 20 后旧形票标 legacy_id 且 project==SA 值（不误归）",
                  (row2 or {}).get("legacy_id") is True
                  and str((row2 or {}).get("project") or "") == KEY_A,
                  "legacy_id=%r project=%r"
                  % ((row2 or {}).get("legacy_id"), (row2 or {}).get("project")))
            check("B2c 合并可观测：行带 match_via=legacy_id",
                  str((row2 or {}).get("match_via") or "") == "legacy_id",
                  "match_via=%r" % (row2 or {}).get("match_via"))

            check("B3 僵尸旧形 id（实例不在册）不上板（R2 两路都保）",
                  ok3 and row3 is None, "夹具=%s 行在场=%s" % (ok3, row3 is not None))
            check("B4 白名单真源=聚合声明（零 env 覆盖层可得）",
                  parsed.get("ok") is True and row1 is not None and row3 is None,
                  "同一渲染内在册旧形上板/僵尸不上板=聚合白名单生效")
        finally:
            ENV.clear()
    finally:
        try:
            cleanup_tickets()
        except Exception as e:  # noqa: BLE001——自清失败不炸退出路径
            print("WARN: 退出自清异常（%s）" % e, flush=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (STATS["pass"], STATS["fail"], 0, 0), flush=True)
    if FAILS:
        print("FAIL_REASON: %s" % "；".join(FAILS), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001——意外异常=产品红点名，不静默不假绿
        die_fail("场景异常退出：%s: %s" % (type(e).__name__, e))
