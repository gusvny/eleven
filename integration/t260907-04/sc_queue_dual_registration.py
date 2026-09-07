#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_queue_dual_registration.py — worker 双队列过渡注册可证（t260907-04 验收②）。

intent（用户可感知契约：改名不弃旧，老 workflow 自然流干）：
  1. 缺省启动：worker 同进程同时 poll 新队列（sandbar）与旧队列（suyou-poc）——
     验收②「worker 日志两队列」的正面证据；
  2. 工单专属 worker（新名列表 env SANDBAR_TASK_QUEUES）：同 tid 双前缀队列
     （sandbar-ticket-* + suyou-ticket-*）同 poll——在飞旧工单专属 worker 死后
     重启不搁浅（review gen0 缺口1 的正面回归）；
  3. 仅旧名单值 env（SUYOU_TASK_QUEUE=suyou-ticket-<在飞id>）：旧世界重启路径
     仍可服务（读侧兼容落到队列面）。

舞台：stage_docker 单点搭台（docker 缺席/镜像缺席/起台不健康=ENV_FAIL exit 2，
点名缺什么）；temporalio SDK 走 poc venv（缺=ENV_FAIL，KI-020③ 族）。
红线：只连舞台 temporal，不触 3099/生产 7233。
**implement 落地前三腿红属预期，arbitrate/merge 期必须全绿。**
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
         if not (k.startswith("SUYOU_") or k.startswith("SANDBAR_"))}
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

    print("== 腿1 缺省启动 → 日志双队列（sandbar + suyou-poc）")
    out, rc = boot_worker({"TARGET_HOST": host, "NAMESPACE": ns})
    started = "worker 起来了" in out
    if not started and ("connect" in out.lower() or "rpc" in out.lower()):
        r.env_fail("worker 连不上舞台 temporal：%s" % out[-200:])
    else:
        r.check(started and "sandbar" in out and "suyou-poc" in out,
                "启动行在且两队列名在日志（sandbar=%s suyou-poc=%s）"
                % ("sandbar" in out, "suyou-poc" in out))

    print("== 腿2 工单专属 worker 新名列表 env → 同 tid 双前缀同 poll")
    out, rc = boot_worker({
        "TARGET_HOST": host, "NAMESPACE": ns,
        "SANDBAR_TASK_QUEUES": "sandbar-ticket-t26090704a,suyou-ticket-t26090704a"})
    r.check("sandbar-ticket-t26090704a" in out and "suyou-ticket-t26090704a" in out,
            "日志含双前缀队列（new=%s legacy=%s）"
            % ("sandbar-ticket-t26090704a" in out, "suyou-ticket-t26090704a" in out))

    print("== 腿3 仅旧名单值 env（在飞旧工单重启路径）→ 服务旧前缀队列")
    out, rc = boot_worker({
        "TARGET_HOST": host, "NAMESPACE": ns,
        "SUYOU_TASK_QUEUE": "suyou-ticket-t26090704old"})
    r.check("suyou-ticket-t26090704old" in out,
            "旧名单值 env 下 worker poll 旧前缀队列（%s）"
            % ("suyou-ticket-t26090704old" in out))

    lib_naming.stage_down(PROJECT)
    r.finish()


if __name__ == "__main__":
    main()
