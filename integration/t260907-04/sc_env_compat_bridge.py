#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_env_compat_bridge.py — 单名时代 env 契约守卫（t260907-04 正文①，260908 终切翻面）。

intent（用户可感知契约，锚 shared.py 头注记载的 env 契约而非实现）：
  终切（260908）撤 apply_env_compat 双向桥（KI-058 病根）——过渡期结束、空库重建
  窗口零兼容负担，引擎只认新名 SANDBAR_*。本场景自过渡契约**翻面为终切契约
  负向守卫**：
  1. 仅旧名（SUYOU_*）环境：引擎**不解析**出旧名值——回落缺省常量，旧脚本显式
     失效，不静默回落（读侧语义与撤桥决策一致）；
  2. 仅新名（SANDBAR_*）：正常生效；
  3. 新旧冲突：新名独源、旧名被忽略（桥已撤=无歧义面）；
  4. 新名为空串：回落缺省常量（falsy 语义），**不**回落旧名（桥已撤）；
  5. apply_env_compat 缺席在案：负向守卫——桥函数悄悄复活即红
     （KI-058 病根不复发；shared.py 退役账#6 收口承诺的机械看守）。

灰盒：经子进程在 engine 目录内 import 引擎共享模块读解析结果，锚公开 env
契约不锚内部函数；畸形输入（空值）在腿 4。
Hermetic：零网络零舞台（TARGET_HOST 只被解析不被连接）。
**桥若被加回（腿5 红）或旧名重新生效（腿1/3/4 红）= KI-058 复发信号。**
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

# 家族变量名（父环境净化用：本机/闸级可能已导出 SANDBAR_*/SUYOU_*，逐腿清场）
FAMILY = ("SUYOU_TASK_QUEUE", "SANDBAR_TASK_QUEUE",
          "SUYOU_TARGET_HOST", "SANDBAR_TARGET_HOST",
          "SUYOU_NAMESPACE", "SANDBAR_NAMESPACE")

PROBE = """
import json
import shared
print(json.dumps({"q": shared.TASK_QUEUE, "h": shared.TARGET_HOST, "n": shared.NAMESPACE}))
"""

BRIDGE = """
import json, os
import shared
if not hasattr(shared, "apply_env_compat"):
    print(json.dumps({"bridge": False}))
    raise SystemExit
q0 = os.environ.get("SANDBAR_TASK_QUEUE")
shared.apply_env_compat()
first = os.environ.get("SANDBAR_TASK_QUEUE")
shared.apply_env_compat()
second = os.environ.get("SANDBAR_TASK_QUEUE")
print(json.dumps({"bridge": True, "q0": q0, "first": first, "second": second}))
"""


def env_of(**kv):
    e = {k: v for k, v in os.environ.items()
         if not (k.startswith("SANDBAR_") or k.startswith("SUYOU_"))}
    e.update(kv)
    return e


def main():
    # 父环境净化（t260907-11 仲裁实锤修复）：lib_naming.tp_eval 的 env_extra 是
    # **叠加**语义（dict(os.environ) | env_extra），env_of 返回的「已剥离家族变量
    # 的完整环境」被叠加后，父环境的 SANDBAR_*/SANDBAR_* 原样漏进子进程——闸内泳道
    # 上下文导出 SANDBAR_TASK_QUEUE=sandbar-ticket-<泳道>（t260907-04 过闸时引擎
    # 尚未导出该名，故当时绿、更名后翻红），「仅旧名/仅新名/桥幂等」腿的前提
    # 被污染。在本进程入口先自净，叠加即从净环境出发，env_of 语义才成立。
    for k in [k for k in os.environ if k.startswith(("SANDBAR_", "SANDBAR_"))]:
        del os.environ[k]
    r = lib_naming.Rec()

    print("== 腿1 仅旧名环境 → 不解析旧名（回落缺省常量，桥已撤）")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SUYOU_TASK_QUEUE="q-legacy",
                                                     SUYOU_TARGET_HOST="h-legacy:1",
                                                     SUYOU_NAMESPACE="n-legacy"))
    if res[0] is None:
        r.env_fail("引擎共享模块求值失败：%s" % res[3][-160:])
    else:
        obj = res[0]
        r.check(obj.get("q") == "sandbar" and obj.get("h") == "127.0.0.1:7233"
                and obj.get("n") == "default",
                "TASK_QUEUE/TARGET_HOST/NAMESPACE 回落缺省（旧名不得解析；得 %s）" % obj)

    print("== 腿2 仅新名环境 → 生效")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SANDBAR_TASK_QUEUE="q-new",
                                                     SANDBAR_TARGET_HOST="h-new:1"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        obj = res[0]
        r.check(obj.get("q") == "q-new" and obj.get("h") == "h-new:1",
                "新名单独生效（得 %s）" % obj)

    print("== 腿3 新旧冲突 → 新名独源，旧名被忽略（桥已撤=无歧义面）")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SUYOU_TASK_QUEUE="q-old",
                                                     SANDBAR_TASK_QUEUE="q-win"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        r.check(res[0].get("q") == "q-win", "冲突取新名、旧名忽略（得 %s）" % res[0].get("q"))

    print("== 腿4 新名空串 → 回落缺省常量（falsy 语义，不回落旧名）")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SANDBAR_TASK_QUEUE="",
                                                     SUYOU_TASK_QUEUE="q-fallback"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        r.check(res[0].get("q") == "sandbar", "空串新名回落缺省（得 %s）" % res[0].get("q"))

    print("== 腿5 apply_env_compat 缺席在案（桥复活即红，KI-058 负向守卫）")
    res = lib_naming.tp_json(BRIDGE, env_replace=True, env_extra=env_of(SANDBAR_TASK_QUEUE="q-bridge"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        obj = res[0]
        r.check(obj.get("bridge") is False,
                "apply_env_compat 缺席（桥未复活；得 %s）" % obj)

    r.finish()


if __name__ == "__main__":
    main()
