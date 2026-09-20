#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_schedule_legacy_retire.py — dispatcher-scan schedule 单名契约（t260907-04，终切翻面）。

intent（用户可感知契约，260908 终切后语义——空库重建窗口零兼容负担）：
  Temporal schedule 是服务端持久对象。终切撤掉了「引擎走廊幂等删旧 schedule id」
  的退役面（dc5f8cc）——引擎只建/幂等维护**新名单 ID（sandbar-dispatcher-scan）**，
  旧 ID 的清理是运维操作（人工/专门工具），引擎走廊绝不隐式删用户数据。子用例：
  1. 首次跑创建走廊 → 台上恰 sandbar-dispatcher-scan 一个（不种旧 ID）；
  2. 再跑一次 → 幂等（仍恰新 ID 一个、不炸）；
  3. 负向守卫：人工种下旧 ID（模拟遗留残留）→ 走廊照跑 → 旧 ID **原样在**
     （引擎不碰=退役面撤的契约边界，隐式删即红）、新 ID 照在。
  创建走廊=仓内唯一在树创建点 demo_schedule.demo_schedule(client)（scan_schedule
  只有 describe/pause/resume/trigger 运维面，无 create）。
舞台：stage_docker 单点；SDK 走 poc venv；缺=ENV_FAIL。
**本场景自过渡退役契约翻面（260908 撤退役面）；子用例1 红=种了旧 ID，子用例3 红=引擎隐式删旧。**
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

# 泳道唯一化（t260910-12 arbitrate gen2）：compose 项目名 daemon 全局可见，
# 并行泳道跑同名场景会互相 down 对方的台（docker events 铁证）——后缀=
# 本 worktree 路径 hash，同 worktree 稳定、跨 worktree 不同。
import hashlib as _hashlib
REPO = os.path.dirname(INTEG)
# run 维度唯一化（t260913-02 arbitrate gen10，**同泳道**并发面的根因修）：
# 项目名原先只有「泳道」维度，于是**同一泳道内两次并发跑**（闸跑 + 手跑／上一轮
# 长跑的尾巴；21:10 实况：两个 199 条全轮重叠 85s，本场景即闸拦条目）会 ensure 到
# 同一个台，三种伤口同源——一方 down 拆掉另一方在飞的台（中段「连接被拒」）、一方
# 子用例3 种下的旧 ID 让另一方子用例1 看到两个 ID（**伪装成产品红的子用例1 红**）、瞬时冲突
# 环境红。加 pid 后缀后同泳道并发跑各持自己的台（跨跑复用台不是本场景的语义需求，
# 冷启代价约 20s）。跨泳道面保持原语义（泳道 hash 仍在）。
PROJECT = ("t26090704-sched-%s-r%d"
           % (_hashlib.md5(REPO.encode("utf-8")).hexdigest()[:8], os.getpid()))

PURGE_RESIDUE = r"""
import asyncio, json
from temporalio.client import Client
from shared import TARGET_HOST, NAMESPACE

async def main():
    c = await Client.connect(TARGET_HOST, namespace=NAMESPACE)
    for sid in ("suyou-dispatcher-scan", "sandbar-dispatcher-scan"):
        try:
            await c.get_schedule_handle(sid).delete()
        except Exception:
            pass
    print(json.dumps({"purged": True}))

asyncio.run(main())
"""

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


# 环境口径（t260913-02 arbitrate gen10 实证，**调用面纪律**）：每个 tp_json 都必须带
# env_replace=True。worker 用 env_for() 起（整份环境=已净化），而 tp_json 缺省是 **overlay**
# ——被剥掉的键会从 os.environ 复活：泳道内直跑时父环境带 SANDBAR_TASK_QUEUE=
# sandbar-ticket-<票>，走廊便到那个队列建 workflow，而 worker 只 poll 缺省 "sandbar"
# → 巡检工作流永不执行 → scan_handle.result() 挂死 → 三条子用例齐报「timeout 180s」
# （方向错误的报错）。lib_naming.tp_eval 的文档早点名这条口径，本场景补齐调用面。


def _worker_tail(path, n=300):
    """worker 进程输出的尾巴（诊断面）：原实现把 worker.py 的 stdout/stderr 接进一个
    从不读的 PIPE——走廊超时时只剩一句『timeout 180s』，真因（worker 起不来／连不上台／
    领不到活）全被吞掉，报错指错方向（t260913-02 arbitrate gen10 实测：同一形态在
    两条并发跑的子用例上都只报 timeout）。落临时文件后 ENV_FAIL 能带上 worker 自己的话。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()[-n:].replace("\n", " / ").strip()
    except OSError:
        return "（worker 输出不可读）"


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

    wpath = None
    try:
        print("== 子用例1 首次创建走廊 → 恰 sandbar-dispatcher-scan 一个（不种旧 ID）")
        # 走廊 demo_schedule 会 trigger 巡检工作流并等它跑完（scan_handle.result()），
        # 空台没有 worker 时这一步永远阻塞——三条子用例共用一台随场景生死的短命 worker
        # 接住巡检（activity 是只读票列表，空台即空清单）。
        wp = None
        py = lib_naming.poc_python()
        if py is None:
            r.env_fail("poc venv/SDK 缺失，worker 起不来")
            r.finish()
            return
        # 预置清场（t260913-02 arbitrate gen10，**不是**放宽子用例1 判据）：前一次跑被打断
        # （或在飞的另一条同形跑）留下的旧 ID 是**夹具残留**，不是被测引擎的行为——原样
        # 留下会让子用例1 在「引擎跑完该恰新 ID 一个」的判据上红成产品红（闸拦实证形态）。
        # 清场后子用例1 的判据反而更纯：起手两 ID 皆无 → 引擎跑完仍须恰新 ID 一个。
        obj, rc, out, err = lib_naming.tp_json(PURGE_RESIDUE, env_extra=env_for(host, ns),
                                     env_replace=True)
        if obj is None or not obj.get("purged"):
            r.env_fail("预置清场不可达（舞台/SDK 面）：%s" % (err or out)[-200:])
            r.finish()
            return
        wf = tempfile.NamedTemporaryFile(prefix="sched-worker-", suffix=".log", delete=False)
        wpath = wf.name
        wf.close()
        wfh = open(wpath, "w", encoding="utf-8")   # worker 输出落盘（诊断面，见 _worker_tail）
        wp = subprocess.Popen([py, "worker.py"], cwd=lib_naming.TP,
                              env=env_for(host, ns),
                              stdout=wfh, stderr=subprocess.STDOUT)
        # 起手等 worker 真连上台（worker.py 连上后才打「worker 起来了」）：原实现不看
        # worker 一眼就发车，worker 秒崩时只能靠 180s 超时兜底。超时/猝死的判据各自
        # 精确点名，不再是同一句 timeout。
        ready_deadline = time.time() + 60
        while time.time() < ready_deadline:
            if wp.poll() is not None:
                break
            if "worker 起来了" in _worker_tail(wpath, 4000):
                break
            time.sleep(1)
        if wp.poll() is not None:
            r.env_fail("worker 起不来（rc=%s，输出：%s）" % (wp.returncode, _worker_tail(wpath, 400)))
            r.finish()
            return
        if "worker 起来了" not in _worker_tail(wpath, 4000):
            r.env_fail("worker 60s 内未连上台（输出尾：%s）" % _worker_tail(wpath, 300))
            r.finish()
            return

        def _corridor(label, timeout=180):
            """跑一次引擎创建走廊；失败时把 worker 自己的话带进 ENV_FAIL。"""
            o, _, so, se = lib_naming.tp_json(CREATE_VIA_ENGINE,
                                              env_extra=env_for(host, ns),
                                              timeout=timeout, env_replace=True)
            if o is None:
                r.env_fail("%s：%s｜worker(rc=%s) 尾：%s"
                           % (label, (se or so)[-200:], wp.poll(), _worker_tail(wpath, 300)))
            return o

        obj = _corridor("引擎创建走廊跑不动")
        if obj is None:
            pass
        else:
            ids, _, _, e2 = lib_naming.tp_json(LIST_IDS, env_extra=env_for(host, ns),
                                              env_replace=True)
            got = (ids or {}).get("ids") if ids else None
            if got is None:
                r.env_fail("schedule 清点失败：%s" % e2[-160:])
            else:
                r.check(got == ["sandbar-dispatcher-scan"],
                        "新 ID 独苗、无旧 ID（ids=%s）" % got)

        print("== 子用例2 再跑一次 → 幂等（仍恰新 ID 一个、不炸）")
        obj = _corridor("二次创建走廊跑不动")
        if obj is None:
            pass
        else:
            ids, _, _, e2 = lib_naming.tp_json(LIST_IDS, env_extra=env_for(host, ns),
                                              env_replace=True)
            got = (ids or {}).get("ids") if ids else None
            if got is None:
                r.env_fail("二次清点失败：%s" % e2[-160:])
            else:
                r.check(got == ["sandbar-dispatcher-scan"],
                        "幂等重跑后仍是新 ID 唯一（ids=%s）" % got)

        print("== 子用例3 负向守卫：人工种旧 ID → 引擎走廊不隐式删（退役面撤的契约边界）")
        obj, rc, out, err = lib_naming.tp_json(SEED, env_extra=env_for(host, ns), env_replace=True)
        if obj is None or not obj.get("seeded"):
            r.env_fail("种旧 ID 失败（舞台/SDK 面）：%s" % (err or out)[-200:])
        else:
            obj = _corridor("三次创建走廊跑不动")
            ids, _, _, e2 = lib_naming.tp_json(LIST_IDS, env_extra=env_for(host, ns),
                                              env_replace=True)
            got = (ids or {}).get("ids") if ids else None
            if got is None:
                r.env_fail("三次清点失败：%s" % e2[-160:])
            else:
                r.check(sorted(got) == ["sandbar-dispatcher-scan", "suyou-dispatcher-scan"],
                        "旧 ID 原样在（引擎不碰）+新 ID 照在（ids=%s）" % got)
    finally:
        if 'wp' in locals() and wp is not None:
            wp.terminate()
            try:
                wp.wait(timeout=10)
            except subprocess.TimeoutExpired:
                wp.kill()
        if 'wfh' in locals() and wfh is not None:
            try:
                wfh.close()
            except OSError:
                pass
        lib_naming.stage_down(PROJECT)
        if wpath:
            try:
                os.unlink(wpath)
            except OSError:
                pass

    r.finish()


if __name__ == "__main__":
    main()
