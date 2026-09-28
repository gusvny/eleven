#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_watchdog_status_surface.py — 守望者只读面契约（t260928-28，灰盒 L3，离线秒级零 docker）。

intent（用户可感知行为=面板下一票要消费的承诺面，锚方案 §4 键集，不锚实现）：
- A 未声明项目零行为且显式声明：status 回 `declared:false`（不冒充有数据）——
  「未声明 = 零行为」的可判定锚；
- B 已声明项目 status 键集恰含面板契约全集：declared/enabled/heartbeat/
  ledger/liveness{engine,executor}/self_lock/reconcile/wakes/alerts/notify/
  config_provenance——面板消费面缺键=面板无法显式呈现=不静默降级红线（scope 9）；
- C heartbeat/liveness/self_lock/reconcile 每个状态都带时间戳（checked_at /
  last_beat / since / last_progress_at）——「显式可见状态」必须可问「什么时候」；
- D 非 GET 拒绝刚性（405 形状面：harness 层回 not-allowed，方法不是 GET）；
- E 配置溯源：config_provenance.file 指向声明文件，且至少一个键的来源可答
  「哪个文件哪条键 or factory-default」（KI-148/149 教训的落法）。

intent 分工：developer L1 单测守模块内部真值表；本场景只锁公开 status 面的
键集/时间戳/未声明显式/溯源四件用户可感承诺。与其他四条 watchdog 场景
intent 不同面（本条只锁「读什么」；行为面归各自场景）。
三态：node 缺席=ENV_FAIL exit 2；harness 缺席=FAIL exit 1 点名（TDD 期红属
预期，arbitrate/merge 期必须绿）。
Run directly: python3 integration/t260928-28/sc_watchdog_status_surface.py（cwd=仓根）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib_watchdog_harness import Harness, PASS, FAIL, ok  # noqa: E402

REQUIRED_KEYS = {
    "declared", "enabled", "heartbeat", "ledger", "liveness",
    "self_lock", "reconcile", "wakes", "alerts", "notify", "config_provenance",
}
TIMESTAMPED = {
    "heartbeat": {"last_beat"},
    "liveness": {"checked_at"},   # engine/executor 子对象逐个查
    "self_lock": {"since"},
    "reconcile": {"since"},
}


def main():
    h = Harness()
    h.start()
    try:
        # A 未声明项目：无 watchdog.json = declared:false 显式（非消失非装死）
        r = h.cmd("status", project="undeclared-proj")
        ok(r.get("ok"), "status 可应答", r)
        st = r.get("status") or {}
        ok(st.get("declared") is False, "A 未声明项目 declared:false 显式", st)

        # B/C 已声明项目：键集恰含契约全集 + 状态带时间戳
        h.cmd("start", project="p1", config=h.fixture_config("p1"), now="2026-09-28T10:00:00+08:00")
        st = h.cmd("status", project="p1")["status"]
        missing = REQUIRED_KEYS - set(st)
        ok(not missing, "B status 键集含面板契约全集", "missing=%s" % missing)
        for face, keys in TIMESTAMPED.items():
            sub = st.get(face) or {}
            for k in keys:
                if face == "liveness":
                    ok(bool((sub.get("engine") or {}).get("checked_at"))
                       and bool((sub.get("executor") or {}).get("checked_at", sub.get("last_progress_at"))),
                       "C liveness 引擎与执行器状态带时间戳", sub)
                else:
                    ok(bool(sub.get(k)), "C %s.%s 时间戳在位" % (face, k), sub)

        # D 非 GET 刚性拒绝
        r = h.cmd("status_method_probe", project="p1", method="POST")
        ok(r.get("rejected") and r.get("code") == 405, "D 非 GET 405 刚性", r)

        # E 配置溯源
        cp = st.get("config_provenance") or {}
        ok(bool(cp.get("file")), "E 溯源答「哪个文件」", cp)
        keys = cp.get("keys") or {}
        ok(bool(keys) and any(("factory-default" in str(v)) or (".json" in str(v) or "#" in str(v))
                              for v in keys.values()),
           "E 逐键来源可答（文件#键 或 factory-default）", keys)
    finally:
        h.finish()


if __name__ == "__main__":
    main()
