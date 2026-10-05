#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_selfheal_harness — t261005-02 self-heal 场景的共享驱动缝（灰盒 L2/L3）。

复用 t260928-28 的 Watchdog 夹具驱动（前置/基础步骤共享复用是纪律允许且鼓励的）：
同一条「一行 JSON 一命令」stdin/stdout 缝、同一条注入时钟 + 全桩实例。本库只补
self-heal 面需要的缝契约与三态出口，不抄任何产品逻辑。

v3 缝契约（对 developer 的唯一要求——测试缝，不是产品行为；实现落地前场景 FAIL 点名，
TDD 期红属预期，arbitrate/merge 期必须绿）：
  - fixture_config 支持 `self_heal: {enabled, park_minutes}` 覆写（声明配置族，落进
    夹具 watchdog.json；缺省=不写该键=工厂默认分支）；
  - `brief_pending_set {sessionId, pending}`：拨队列镜像桩的 ourBriefPending
    （true=我们的简报仍未消化 / false=已消化 / "null"=镜像不可读 no-signal 形态）；
  - `cancel_log`：回夹具会话服务桩收到的全部 cancel 请求
    （[{sessionId, accepted, at}]）——cancel 是本票新出口，桩必须记录；
  - `cancel_fail_next {error}`：注入下一次 cancel 失败（回执 accepted:false + error）；
  - `alerts_tail`：回夹具 alerts 账的最近行（含 kind 字段）——self_heal_cancel 行判据；
  - 问句注入沿用既有缝：requests_seed / session_face_set（t261004-08 待办交互面）、
    session_text_set（prose 问句标记，t260928-28 缝）。
v3 命令一到位才启用；v1/v2 场景不触发新命令，行为逐字节不变（同 t261004-08 增量纪律）。

三态（integration/README.md 执行契约）：node 缺席=ENV_FAIL exit 2；缝/实现未落地或
断言红=FAIL exit 1；零 docker、零 3099/7233 接触（docs/testing-guide.md 红线）。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
T26092828 = HERE.parent / "t260928-28"
sys.path.insert(0, str(T26092828))

from lib_watchdog_harness import Harness  # noqa: E402  共享夹具（基础步骤复用）


def summary_and_exit(pass_n, fail_n, env_fail_n=0, na_n=0):
    """三态出口：0=全过；1=有 FAIL（含全 N/A）；2=有 ENV_FAIL。"""
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (pass_n, fail_n, env_fail_n, na_n))
    if env_fail_n:
        sys.exit(2)
    sys.exit(1 if fail_n else 0)


def safe_cmd(h, op, **kw):
    """发一条缝命令；缝不可用（未知命令/无回执）→ 抛 NamedSeamError，由场景转 FAIL。"""
    try:
        return h.cmd(op, **kw)
    except Exception as e:  # noqa: BLE001 — 缝层的任何崩法都归「缝未落地」
        raise NamedSeamError("%s: %s" % (op, str(e)[-300:]))


class NamedSeamError(Exception):
    pass


def seam_ready(h):
    """v3 缝在位判定：cancel_log 命令可应答。"""
    try:
        r = safe_cmd(h, "cancel_log")
        return isinstance(r, dict) and r.get("ok") is True
    except NamedSeamError:
        return False
