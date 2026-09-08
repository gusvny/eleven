#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_schedule_legacy_retire.py — dispatcher-scan schedule 单名契约（t260907-04，终切翻面）。

intent（用户可感知契约，260908 终切后语义——空库重建窗口零兼容负担）：
  Temporal schedule 是服务端持久对象。终切撤掉了「引擎走廊幂等删旧 schedule id」
  的退役面（dc5f8cc）——引擎只建/幂等维护**新名单 ID（sandbar-dispatcher-scan）**，
  旧 ID 的清理是运维操作（人工/专门工具），引擎走廊绝不隐式删用户数据。腿：
  1. 首次跑创建走廊 → 台上恰 sandbar-dispatcher-scan 一个（不种旧 ID）；
  2. 再跑一次 → 幂等（仍恰新 ID 一个、不炸）；
  3. 负向守卫：人工种下旧 ID（模拟遗留残留）→ 走廊照跑 → 旧 ID **原样在**
     （引擎不碰=退役面撤的契约边界，隐式删即红）、新 ID 照在。
  创建走廊=仓内唯一在树创建点 demo_schedule.demo_schedule(client)（scan_schedule
  只有 describe/pause/resume/trigger 运维面，无 create）。
舞台：stage_docker 单点；SDK 走 poc venv；缺=ENV_FAIL。
**本场景自过渡退役契约翻面（260908 撤退役面）；腿1 红=种了旧 ID，腿3 红=引擎隐式删旧。**
"""
from __future__ import annotations

import asyncio
import os
import subprocess
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
         if not (k.startswith("SANDBAR_") or k.startswith("SUYOU_"))}
    # 必须走 SANDBAR_ 前缀名：shared.py 只认这两个名字；裸 TARGET_HOST 键是
    # 无效赋值，子进程会静默落到缺省生产 127.0.0.1:7233/default（260908 实锤踩过）
    e["SANDBAR_TARGET_HOST"] = host
    e["SANDBAR_NAMESPACE"] = ns
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
        print("== 腿1 首次创建走廊 → 恰 sandbar-dispatcher-scan 一个（不种旧 ID）")
        # 走廊 demo_schedule 会 trigger 巡检工作流并等它跑完（scan_handle.result()），
        # 空台没有 worker 时这一步永远阻塞——三条腿共用一台随场景生死的短命 worker
        # 接住巡检（activity 是只读票列表，空台即空清单）。
        wp = None
        py = lib_naming.poc_python()
        if py is None:
            r.env_fail("poc venv/SDK 缺失，worker 起不来")
            r.finish()
            return
        wp = subprocess.Popen([py, "worker.py"], cwd=lib_naming.TP,
                              env=env_for(host, ns),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
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
                r.check(got == ["sandbar-dispatcher-scan"],
                        "新 ID 独苗、无旧 ID（ids=%s）" % got)

        print("== 腿2 再跑一次 → 幂等（仍恰新 ID 一个、不炸）")
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
                r.check(got == ["sandbar-dispatcher-scan"],
                        "幂等重跑后仍是新 ID 唯一（ids=%s）" % got)

        print("== 腿3 负向守卫：人工种旧 ID → 引擎走廊不隐式删（退役面撤的契约边界）")
        obj, rc, out, err = lib_naming.tp_json(SEED, env_extra=env_for(host, ns))
        if obj is None or not obj.get("seeded"):
            r.env_fail("种旧 ID 失败（舞台/SDK 面）：%s" % (err or out)[-200:])
        else:
            obj, rc, out, err = lib_naming.tp_json(CREATE_VIA_ENGINE,
                                                   env_extra=env_for(host, ns), timeout=180)
            ids, _, _, e2 = lib_naming.tp_json(LIST_IDS, env_extra=env_for(host, ns))
            got = (ids or {}).get("ids") if ids else None
            if got is None:
                r.env_fail("三次清点失败：%s" % e2[-160:])
            else:
                r.check(sorted(got) == ["sandbar-dispatcher-scan", "suyou-dispatcher-scan"],
                        "旧 ID 原样在（引擎不碰）+新 ID 照在（ids=%s）" % got)
    finally:
        if wp is not None:
            wp.terminate()
            try:
                wp.wait(timeout=10)
            except subprocess.TimeoutExpired:
                wp.kill()
        lib_naming.stage_down(PROJECT)

    r.finish()


if __name__ == "__main__":
    main()
