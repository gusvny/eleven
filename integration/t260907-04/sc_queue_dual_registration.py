#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_queue_dual_registration.py — worker 队列注册契约（t260907-04 验收②，终切翻面）。

intent（用户可感知契约，260908 终切后语义——空库重建窗口零兼容负担）：
  1. 缺省启动：worker **单名 poll 新队列（sandbar）**，旧队列（suyou-poc）不再
     双 poll（终切撤双 poll 的负向守卫——双 poll 悄悄复活即红）；
  2. 工单专属 worker（新名列表 env SANDBAR_TASK_QUEUES）：env 显式给出的队列名
     照单全收（多队列列表是显式声明面，非默认推导）；
  3. 旧名单值 env（SANDBAR_TASK_QUEUE=suyou-ticket-<id>）：env 显式声明的旧名
     队列仍被服务（显式声明≠默认推导；默认推导不再产旧前缀）。

舞台：stage_docker 单点搭台（docker 缺席/镜像缺席/起台不健康=ENV_FAIL exit 2，
点名缺什么）；temporalio SDK 走 poc venv（缺=ENV_FAIL，KI-020③ 族）。
红线：只连舞台 temporal，不触 3099/生产 7233。
**本场景自过渡双注册契约翻面（260908 终切撤双 poll）；腿1 红=双 poll 复活。**
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

PROJECT = "t26090704-queue"


def clean_env(**kv):
    e = {k: v for k, v in os.environ.items()
         if not (k.startswith("SANDBAR_") or k.startswith("SUYOU_"))}
    e.update(kv)
    return e


# 子进程 env 必须走 SANDBAR_ 前缀名：shared.py 只认这两个名字；裸 TARGET_HOST 键
# 是无效赋值，worker 会静默落到缺省生产 127.0.0.1:7233/default（260908 实锤踩过）
def stage_env(host, ns, **kv):
    e = clean_env()
    e["SANDBAR_TARGET_HOST"] = host
    e["SANDBAR_NAMESPACE"] = ns
    e.update(kv)
    return e


def boot_worker(env_extra, seconds=8.0):
    """短命起 worker 收日志：超时杀进程，返回 stdout+stderr 文本。"""
    py = lib_naming.poc_python()
    p = subprocess.Popen([py, "worker.py"], cwd=lib_naming.TP,
                         env=clean_env(**env_extra),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = ""
    try:
        out, _ = p.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            out, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
    return out or "", p.returncode


def main():
    r = lib_naming.Rec()
    info = None
    try:
        info, errmsg = lib_naming.stage_ensure(PROJECT, services="temporal")
    finally:
        pass
    if info is None:
        r.env_fail("测试台不在位（stage_docker ensure 失败）：%s" % errmsg)
        r.finish()
        return
    host, ns = lib_naming.stage_endpoint(info)
    if not host:
        r.env_fail("舞台未回报 temporal 端点：%s" % info)
        r.finish()
        return

    print("== 腿1 缺省启动 → 单名 poll sandbar，suyou-poc 不双 poll（终切负向守卫）")
    out, rc = boot_worker(stage_env(host, ns))
    started = "worker 起来了" in out
    if not started and ("connect" in out.lower() or "rpc" in out.lower()):
        r.env_fail("worker 连不上舞台 temporal：%s" % out[-200:])
    else:
        r.check(started and "sandbar" in out and "suyou-poc" not in out,
                "启动行在且单名 sandbar（sandbar=%s suyou-poc 不 poll=%s）"
                % ("sandbar" in out, "suyou-poc" not in out))

    print("== 腿2 工单专属 worker 显式列表 env → 声明队列名照单全收")
    out, rc = boot_worker(stage_env(
        host, ns,
        SANDBAR_TASK_QUEUES="sandbar-ticket-t26090704a,suyou-ticket-t26090704a"))
    r.check("sandbar-ticket-t26090704a" in out and "suyou-ticket-t26090704a" in out,
            "日志含双前缀队列（显式声明面；new=%s legacy=%s）"
            % ("sandbar-ticket-t26090704a" in out, "suyou-ticket-t26090704a" in out))

    print("== 腿3 旧名单值 env（显式声明旧名队列）→ 服务旧前缀队列")
    out, rc = boot_worker(stage_env(
        host, ns, SANDBAR_TASK_QUEUE="suyou-ticket-t26090704old"))
    r.check("suyou-ticket-t26090704old" in out,
            "旧名单值 env 下 worker poll 旧前缀队列（%s）"
            % ("suyou-ticket-t26090704old" in out))

    lib_naming.stage_down(PROJECT)
    r.finish()


if __name__ == "__main__":
    main()
