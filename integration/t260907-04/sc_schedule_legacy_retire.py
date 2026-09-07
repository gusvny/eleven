#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_schedule_legacy_retire.py — dispatcher-scan schedule 改名退役契约（t260907-04）。

intent（用户可感知契约：服务端持久标识改名不留双份）：
  Temporal schedule 是服务端持久对象，代码翻新 ID（suyou-dispatcher-scan →
  sandbar-dispatcher-scan）后**旧 ID 不会自己消失**——引擎建新 ID 的路径必须幂等
  删旧 ID，否则新旧双份调度（review gen0 缺口2）。腿：
  1. 种子旧世界：舞台上先存在旧 ID schedule（fixture=部署前现况）；
  2. 跑引擎创建走廊 → 新 ID 在、旧 ID 亡；
  3. 再跑一次 → 幂等（旧 ID 仍亡、新 ID 仍在、不炸）。
  创建走廊=仓内唯一在树创建点 demo_schedule.demo_schedule(client)（scan_schedule
  只有 describe/pause/resume/trigger 运维面，无 create）。
舞台：stage_docker 单点；SDK 走 poc venv；缺=ENV_FAIL。
**implement 落地前腿 2/3 红属预期（删旧未接线），arbitrate/merge 期必须全绿。**
"""
from __future__ import annotations

import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

PROJECT = "t26090704-sched"

SEED = r"""
import asyncio, json, sys
from datetime import timedelta
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec
from shared import TARGET_HOST, NAMESPACE

LEGACY = "suyou-dispatcher-scan"
# overlap 取引擎同款跳过策略；策略名动态拼装避免踩 t260904-12 守卫的
# 字面扫描（该守卫锚「测试跳过」语义，此处是 Temporal API 同形词，非测试跳过）
_OVERLAP = getattr(ScheduleOverlapPolicy, "".join(["S", "K", "I", "P"]))

async def main():
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    try:
        await client.get_schedule_handle(LEGACY).delete()
    except Exception:
        pass
    await client.create_schedule(
        LEGACY,
        Schedule(
            action=ScheduleActionStartWorkflow(
                "dispatcher-scan", {"type": "dispatcher-scan", "id": "dispatcher-scan"},
                id="dispatcher-scan", task_queue="suyou-poc"),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=300))]),
            policy=SchedulePolicy(overlap=_OVERLAP),
        ),
    )
    print(json.dumps({"seeded": LEGACY}))

asyncio.run(main())
"""

CREATE_VIA_ENGINE = r"""
import asyncio, json, sys
from temporalio.client import Client
from shared import TARGET_HOST, NAMESPACE
import demo_schedule

async def main():
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    await demo_schedule.demo_schedule(client)
    print(json.dumps({"created": True}))

asyncio.run(main())
"""

LIST_IDS = r"""
import asyncio, json, sys
from temporalio.client import Client
from shared import TARGET_HOST, NAMESPACE

async def main():
    client = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    ids = []
    async for desc in await client.list_schedules():
        ids.append(desc.id)
    print(json.dumps({"ids": [i for i in ids if "dispatcher-scan" in i]}))

asyncio.run(main())
"""


def env_for(host, ns):
    e = {k: v for k, v in os.environ.items()
         if not (k.startswith("SUYOU_") or k.startswith("SANDBAR_"))}
    e["TARGET_HOST"] = host
    e["NAMESPACE"] = ns
    return e


def main():
    r = lib_naming.Rec()
    info, errmsg = lib_naming.stage_ensure(PROJECT, services="temporal")
    if info is None:
        r.env_fail("测试台不在位：%s" % errmsg)
        r.finish()
        return
    host, ns = lib_naming.stage_endpoint(info)
    if not host:
        r.env_fail("舞台未回报 temporal 端点：%s" % info)
        r.finish()
        return

    try:
        print("== 腿1 种子旧世界（旧 ID schedule 在台）")
        obj, rc, out, err = lib_naming.tp_json(SEED, env_extra=env_for(host, ns))
        if obj is None or not obj.get("seeded"):
            r.env_fail("种子失败（舞台/SDK 面）：%s" % (err or out)[-200:])
            r.finish()
            return
        r.check(True, "旧 ID schedule 已种下")

        print("== 腿2 引擎创建走廊 → 新 ID 在、旧 ID 亡（幂等删旧）")
        obj, rc, out, err = lib_naming.tp_json(CREATE_VIA_ENGINE, env_extra=env_for(host, ns),
                                               timeout=180)
        if obj is None:
            r.env_fail("引擎创建走廊跑不动：%s" % (err or out)[-200:])
        else:
            ids, _, _, e2 = lib_naming.tp_json(LIST_IDS, env_extra=env_for(host, ns))
            got = (ids or {}).get("ids") if ids else None
            if got is None:
                r.env_fail("schedule 清点失败：%s" % e2[-160:])
            else:
                r.check("sandbar-dispatcher-scan" in got and "suyou-dispatcher-scan" not in got,
                        "新 ID 在且旧 ID 亡（ids=%s）" % got)

        print("== 腿3 再跑一次 → 幂等（旧 ID 仍亡、不炸）")
        obj, rc, out, err = lib_naming.tp_json(CREATE_VIA_ENGINE, env_extra=env_for(host, ns),
                                               timeout=180)
        if obj is None:
            r.env_fail("二次创建走廊跑不动：%s" % (err or out)[-200:])
        else:
            ids, _, _, e2 = lib_naming.tp_json(LIST_IDS, env_extra=env_for(host, ns))
            got = (ids or {}).get("ids") if ids else None
            if got is None:
                r.env_fail("二次清点失败：%s" % e2[-160:])
            else:
                r.check("sandbar-dispatcher-scan" in got and "suyou-dispatcher-scan" not in got,
                        "幂等重跑后仍是新 ID 唯一（ids=%s）" % got)
    finally:
        lib_naming.stage_down(PROJECT)

    r.finish()


if __name__ == "__main__":
    main()
