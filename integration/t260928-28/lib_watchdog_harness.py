#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_watchdog_harness — t260928-28 watchdog 集成场景的公共驱动缝（灰盒 L2/L3）。

本库是 t260928-28 五条场景（sc_watchdog_*.py）共享的夹具驱动面：以**一行 JSON
一命令**的 stdin/stdout 协议驱动被测守望者（watchdog 插件），全部隔离在 tmp
目录，零 docker、零 3099/7233 接触（docs/testing-guide.md 红线）。

缝的契约（对 developer 的唯一要求——这是测试缝，不是产品行为）：
  插件包须提供 `server/plugins/watchdog/harness.mjs`，行为如下：
    - 启动后从 stdin 逐行读 JSON 命令，逐命令回一行 JSON（含 "ok": true/false）；
    - start：在 fixture 目录布置 watchdog.json（SANDBAR_WATCHDOG_DIR 缝）与
      事件账目录（SANDBAR_EVENT_LEDGER_DIR 缝），以**注入时钟**启动一个守望者
      实例（不连任何真引擎/会话——board 走夹具可见性列表桩、待办交互面走夹具桩、
      wake 投递进夹具会话服务桩被记录）；
    - tick：推进注入时钟 N 秒并泵完到期的轮询/对账周期；
    - restart：dispose 当前实例（清全部 timer/fd）后同一时钟重启——水位线只在
      内存、重启即弃，去重态从 alerts 账重放重建（工单 scope 2/7）；可携
      config 覆写（换配置重启=开关面用）；
    - status：回守望者只读面（GET /sandbar-watchdog/api/status）会返回的**同一
      个对象**（键集=方案 §4 / panel 契约）；
    - delivered_wakes：回夹具会话服务桩收到的全部投递（mode/content/accepted）；
    - 辅助夹具桩：board_set/board_fail（可见性列表与故障注入）、
      session_face_set（待办交互面桩，含 unreadable 注入）、session_digest/
      session_progress/engine_fail/clock_set/append_ledger/rotate_ledger、
      force_alert（按 kind 直接触发一类判据，供夜间/开关面打点）。

灰盒纪律：场景只断协议面与 status 公开键集，不 import 插件内部模块、不锚私有
命名；断言锚=工单 scope 1-9 与方案 §4 键集（面板下一票要消费的承诺面）。

三态：node 缺席=ENV_FAIL exit 2；harness/实现未落地=FAIL exit 1 且点名
（实现未落地段红属预期 TDD 信号，arbitrate/merge 期必须绿）。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
HARNESS = REPO / "server" / "plugins" / "watchdog" / "harness.mjs"

PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (label, detail))


class Harness:
    """守望者夹具驱动：一行 JSON 一命令。"""

    def __init__(self):
        self.proc = None
        self.tmp = tempfile.mkdtemp(prefix="wd-it-")
        self._reclaimed = False

    # ---- lifecycle ----
    def start(self):
        if not shutil.which("node"):
            print("ENV_FAIL: node 不在 PATH（harness.mjs 是 node 缝）")
            sys.exit(2)
        if not HARNESS.is_file():
            print(
                "FAIL: 实现未落地——测试缝缺席 %s（场景锚 harness 协议，"
                "见 lib_watchdog_harness.py 头注；TDD 期红属预期）" % HARNESS
            )
            sys.exit(1)
        self.proc = subprocess.Popen(
            ["node", str(HARNESS)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO),
        )

    def cmd(self, op, **kw):
        kw["op"] = op
        self.proc.stdin.write(json.dumps(kw) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line.strip():
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError("harness 无回执（op=%s）stderr=%s" % (op, err[-500:]))
        return json.loads(line)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"op": "exit"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
        self.reclaim()

    def reclaim(self):
        if not self._reclaimed:
            shutil.rmtree(self.tmp, ignore_errors=True)  # L8 tmp 纪律
            self._reclaimed = True

    # ---- fixture helpers ----
    def fixture_config(self, project, overrides=None):
        """缺省 factory 配置 + overrides；harness 在 start 时落盘。"""
        cfg = {
            "enabled": True,
            "executor_session": "executor-" + project,
            "stall_minutes": 15,
            "reconcile_seconds": 60,
            "alerts": {
                "enabled": True,
                "sound": True,
                "desktop": True,
                "night": {"start": "23:00", "end": "07:30", "policy": "redline-only"},
                "redline": [
                    "reconcile_mismatch",
                    "ledger_unreadable",
                    "engine_down",
                    "self_lock",
                    "stall",
                ],
                "keep_days": 14,
            },
        }
        if overrides:
            for k, v in overrides.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        return cfg

    def finish(self):
        self.stop()
        print("PASS=%d FAIL=%d" % (PASS, FAIL))
        sys.exit(1 if FAIL else 0)


def ledger_row(project, ticket, seq, stage_state, stage="implement", reason="", run_id="r1"):
    """真实 event-ledger-v1 行形状（对齐 server/engine/event_ledger.py 落盘字段：
    v/ts/idem/stage/stage_state；幂等键 idem=project|ticket|run_id|seq）。"""
    return {
        "v": "event-ledger-v1", "project": project, "ticket": ticket,
        "run_id": run_id, "seq": seq, "stage": stage, "stage_state": stage_state,
        "reason": reason, "ts": "2026-09-28T10:00:00+08:00",
        "idem": "%s|%s|%s|%d" % (project, ticket, run_id, seq),
    }


def noise_row(project, ticket, seq):
    """非状态迁移行（纯 kind 话注记，无 stage/stage_state）——worth-waking 过滤的负例。"""
    return {
        "v": "event-ledger-v1", "project": project, "ticket": ticket,
        "run_id": "r1", "seq": seq, "kind": "log-note",
        "ts": "2026-09-28T10:00:00+08:00",
        "idem": "%s|%s|r1|%d" % (project, ticket, seq),
    }


def summary_and_exit(pass_n, fail_n):
    print("PASS=%d FAIL=%d" % (pass_n, fail_n))
    sys.exit(1 if fail_n else 0)
