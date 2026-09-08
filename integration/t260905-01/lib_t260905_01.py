#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-01 集成测试共享夹具：收口两问（沉淀触发器 + 反向同步闸）。
不带 sc_ 前缀 = 共享夹具代码，不进 SCENARIOS（run_scenarios 约定）。

环境口径（三态契约，闸内环境缺失一律显式环境红）：
  stdlib 面（shared / 源码契约锁 / tmp 桩目录）——系统 python3 可跑；
  temporalio 面（agent_activities 的行为驱动腿）——环境缺失时记 ENV_FAIL 点名
  并以 exit 2 收场，绝不静默略过；arbitrate/merge 期（venv 在位）必须全绿。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # …/integration/t260905-01/lib → 仓库根
POC = REPO / "server" / "engine"

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


def summary():
    """三态 §7.3：fail>0→产品红 exit 1；否则 env_fail>0→exit 2；否则 0。"""
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n))
    if failed > 0:
        return 1
    if env_fail_n > 0:
        return 2
    return 0


def stage_block(src, stage_id, sentinel='Stage(id="'):
    """从 STAGES 源码文本切出指定 stage 的定义块（起点=id= 行，终点=下一个 Stage(id=）。
    只锚 stage id 与块边界，不锚行号——重构移动代码不误红。"""
    key = sentinel + stage_id
    start = src.find(key)
    if start < 0:
        return ""
    nxt = src.find(sentinel, start + len(key))
    return src[start:nxt] if nxt > 0 else src[start:]
