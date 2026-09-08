#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_env_compat_bridge.py — SUYOU_*/SANDBAR_* 环境变量过渡契约（t260907-04 正文①）。

intent（用户可感知契约，锚 shared.py 头注记载的 env 契约而非实现）：
  1. 仅旧名（SUYOU_*）的环境：引擎解析到值——过渡期旧环境（存量脚本/文档/用户
     shell）不炸（读侧兼容「先读新名再回落旧名」的回落半边）；
  2. 仅新名（SANDBAR_*）：正常生效；
  3. 新旧同名冲突：新名优先（覆盖语义，不留歧义）；
  4. 新名为空串：回落旧名（falsy 语义与现行 `or` 缺省链一致，畸形值不静默改义）；
  5. apply_env_compat 桥幂等：重复调用不二次改写环境（import 时序之外的显式重跑
     通路，UT monkeypatch/运行期注入路径依赖它）。

灰盒：经子进程在 engine 目录内 import 引擎共享模块读解析结果，锚公开 env
契约不锚内部函数；畸形输入（空值）在腿 4。
Hermetic：零网络零舞台（TARGET_HOST 只被解析不被连接）。
**implement 落地前腿 2/3/5 红属预期（TDD 信号），arbitrate/merge 期必须全绿。**
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

# 家族变量名（父环境净化用：本机/闸级可能已导出 SUYOU_*/SANDBAR_*，逐腿清场）
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
         if not (k.startswith("SUYOU_") or k.startswith("SANDBAR_"))}
    e.update(kv)
    return e


def main():
    # 父环境净化（t260907-11 仲裁实锤修复）：lib_naming.tp_eval 的 env_extra 是
    # **叠加**语义（dict(os.environ) | env_extra），env_of 返回的「已剥离家族变量
    # 的完整环境」被叠加后，父环境的 SUYOU_*/SANDBAR_* 原样漏进子进程——闸内泳道
    # 上下文导出 SANDBAR_TASK_QUEUE=sandbar-ticket-<泳道>（t260907-04 过闸时引擎
    # 尚未导出该名，故当时绿、更名后翻红），「仅旧名/仅新名/桥幂等」腿的前提
    # 被污染。在本进程入口先自净，叠加即从净环境出发，env_of 语义才成立。
    for k in [k for k in os.environ if k.startswith(("SUYOU_", "SANDBAR_"))]:
        del os.environ[k]
    r = lib_naming.Rec()

    print("== 腿1 仅旧名环境 → 引擎解析到旧名值（在飞环境不炸）")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SUYOU_TASK_QUEUE="q-legacy",
                                                     SUYOU_TARGET_HOST="h-legacy:1",
                                                     SUYOU_NAMESPACE="n-legacy"))
    if res[0] is None:
        r.env_fail("引擎共享模块求值失败：%s" % res[3][-160:])
    else:
        obj = res[0]
        r.check(obj.get("q") == "q-legacy" and obj.get("h") == "h-legacy:1"
                and obj.get("n") == "n-legacy",
                "TASK_QUEUE/TARGET_HOST/NAMESPACE 全部落旧名值（得 %s）" % obj)

    print("== 腿2 仅新名环境 → 生效")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SANDBAR_TASK_QUEUE="q-new",
                                                     SANDBAR_TARGET_HOST="h-new:1"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        obj = res[0]
        r.check(obj.get("q") == "q-new" and obj.get("h") == "h-new:1",
                "新名单独生效（得 %s）" % obj)

    print("== 腿3 新旧冲突 → 新名优先")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SUYOU_TASK_QUEUE="q-old",
                                                     SANDBAR_TASK_QUEUE="q-win"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        r.check(res[0].get("q") == "q-win", "冲突取新名（得 %s）" % res[0].get("q"))

    print("== 腿4 新名空串 → 回落旧名（falsy 语义，畸形值不改义）")
    res = lib_naming.tp_json(PROBE, env_replace=True, env_extra=env_of(SANDBAR_TASK_QUEUE="",
                                                     SUYOU_TASK_QUEUE="q-fallback"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        r.check(res[0].get("q") == "q-fallback", "空串新名回落旧名（得 %s）" % res[0].get("q"))

    print("== 腿5 apply_env_compat 桥幂等（显式重跑通路）")
    res = lib_naming.tp_json(BRIDGE, env_replace=True, env_extra=env_of(SUYOU_TASK_QUEUE="q-bridge"))
    if res[0] is None:
        r.env_fail("求值失败：%s" % res[3][-160:])
    else:
        obj = res[0]
        if not obj.get("bridge"):
            r.check(False, "apply_env_compat 缺失（桥未落地）")
        else:
            r.check(obj.get("first") == "q-bridge" and obj.get("second") == "q-bridge",
                    "旧名经桥可见且两次调用幂等（得 %s）" % obj)

    r.finish()


if __name__ == "__main__":
    main()
