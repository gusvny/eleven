#!/usr/bin/env python3
"""sc_event_ledger_projection.py — integration scenario for t260928-13
(per-project append-only event ledger of ticket stage-state transitions).

Grey-box L2/L3, offline, seconds-scale, zero docker, zero console contact.
Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3
  PYTHONPYCACHEPREFIX=out/pycache "$PY" -B integration/t260928-13/sc_event_ledger_projection.py

Three-exit contract: PASS=0 / FAIL=1 / ENV_FAIL=2 (no SKIP).
The behavior half imports the real server/engine/event_ledger.py in the engine
venv (temporalio importable). temporalio missing => ENV_FAIL exit 2 (named);
event_ledger.py or its contract surface missing => FAIL (TDD red until the
implement stage lands — expected and correct before implement).

Intent (what this locks, from the USER-perceivable contract, not internals):
- exactly one durable ledger line per stage-state transition, per project,
  with the declared field set (schema v, project, scope, ticket, workflow,
  template, stage, state, reason, gen, ts, seq, idem, engine stamp);
- at-least-once activity delivery dedupes on the idempotency key: the same
  event NEVER yields a second line, including from a cold process
  (restart/second worker) whose in-memory cache is empty;
- a fresh run_id for the same ticket never collides with the old run's keys
  (no wrongful suppression);
- a write failure never breaks the caller (fail-open) but is LOUD: named
  stderr line + counter + detectable gap record — never a silent success;
- undeclared/disabled project => zero file behaviour;
- malformed inputs (non-dict payload, missing keys, oversized/non-string
  reason, torn last line) never crash the writer;
- rotation: archives honour the keep window, the active file is never
  dropped, config comes from a per-project `event_ledger:` declaration with
  documented default 14d, malformed values fall back per-key;
- rebuild proves the ledger is a derived projection: regenerating one
  ticket's lines from its timeline restores missing lines exactly once and
  REPORTS duplicate-idem lines without duplicating repairs;
- wiring face: mixin exists in base.py, gated so old RUNNING instances
  replay with zero change; wired into DevLaneWorkflow ONLY (inspection
  family stays untouched — out-of-scope negative lock); the rebuild entry
  point lives in the client op surface and resolves project from the ticket
  snapshot, not from caller args.

Distinct from the developer L1 unit tests (server/engine/tests/): this
scenario additionally locks the wiring/source face (dev_lane/client/
inspection non-wiring) and drives the module through its public entry
points against real files on disk. No other registered scenario covers the
event ledger (grep of the SCENARIOS registry: first ticket on this surface).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EL = ROOT / "server/engine/event_ledger.py"
BASE = ROOT / "server/engine/base.py"
DL = ROOT / "server/engine/dev_lane.py"
CLIENT = ROOT / "server/engine/client.py"

PASS = 0
FAIL = 0
ENV = 0


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title: str) -> None:
    print("\n%s" % title)


def env_fail(msg: str) -> None:
    global ENV
    ENV += 1
    print("ENV_FAIL: %s" % msg)


# ===========================================================================
# Part A — source locks (stdlib only, always runnable)
# ===========================================================================
el_src = EL.read_text("utf-8") if EL.exists() else ""
base_src = BASE.read_text("utf-8") if BASE.exists() else ""
dl_src = DL.read_text("utf-8") if DL.exists() else ""
client_src = CLIENT.read_text("utf-8") if CLIENT.exists() else ""

section("A1 event_ledger.py writer contract (source plane)")
ok(EL.exists(), "event_ledger.py 在仓（本票新增模块）")
if el_src:
    ok("O_APPEND" in el_src, "追加写走 O_APPEND 单次写（追加-only 的机械面）")
    ok("SANDBAR_EVENT_LEDGER_DIR" in el_src, "测试隔离 env 覆盖在位")
    ok("gaps" in el_src, "gap 记录面在位（写失败可检测，非静默成功）")
    ok("keep_days" in el_src and "14" in el_src, "保留窗声明键+14d 内置缺省在位")
    ok("max_mb" in el_src, "顺切阈值声明键在位（admin_log 同形声明）")
    ok("ledger_rebuild" in el_src or "rebuild_ticket_lines" in el_src,
       "rebuild 入口函数在位（派生投影证明面）")
    ok("4096" in el_src or "4 * 1024" in el_src or "4KB" in el_src,
       "单行 <4KB 上界在位（reason 截断面）")
    for field in ("project", "scope", "stage", "state", "reason", "idem",
                  "run_id" if "run_id" in el_src else "seq"):
        ok(field in el_src, "行字段面含 %s" % field)

section("A2 幂等键契约（run_id 进键=跨 run 不撞号）")
if el_src:
    ok("idem" in el_src and ("run_id" in el_src),
       "idem 键含 run_id 维度（同票新 run 的 seq=1 不误吞旧 run 键）")

section("A3 fail-open + LOUD（三面都有）")
if el_src:
    ok("WRITE_FAILURES" in el_src or "write_failures" in el_src,
       "写失败计数器在位")
    ok("stderr" in el_src, "点名 stderr 在位")
    ok(re.search(r"raise\s", el_src.split("def rebuild")[-1]) is None
       if "def rebuild" in el_src else True,
       "rebuild 体不主动 raise（fail-open 面）")

section("A4 mixin 与接线面（base/dev_lane 源码锁）")
ok("TicketEventLedgerMixin" in base_src, "base.py 定义 TicketEventLedgerMixin（与 Pause/CrossProject 同辈）")
ok("EVENT_LEDGER" in base_src.upper() or "EVENT_LEDGER" in base_src,
   "独立 patch id 在位（老 RUNNING 实例重放零变化）")
ok("TicketEventLedgerMixin" in dl_src, "dev_lane 接入 mixin（用户可感知：转移产生台账行）")
ok("_ledger_flush" in dl_src or "_ledger_enqueue" in dl_src,
   "接线不止挂名：enqueue/flush 消费点在 dev_lane")
inspection_files = sorted((ROOT / "server/engine").glob("inspection_*.py"))
insp_hits = [p.name for p in inspection_files
             if "EventLedger" in p.read_text("utf-8")]
ok(not insp_hits, "inspection 家族零接线（out-of-scope 负面锁）：%s" % (insp_hits or "无引用"))

section("A5 rebuild op 面（client.py，project 从快照取不从调用方参数取）")
ok("ledger_rebuild" in client_src, "client.py 注册 ledger_rebuild op（写集内 op/CLI 面）")
m_reb = re.search(r"op == \"ledger_rebuild\".*?(?=\n    if op ==|\n    # |\Z)",
                  client_src, re.S)
ok(m_reb is not None, "ledger_rebuild 分支可定位")
if m_reb:
    body = m_reb.group(0)
    ok("snapshot" in body, "op 从快照取票面（project/ticket_id 不自认 caller 参数——防改写他项目台账）")
ok("ledger_rebuild" in dl_src or "ledger_rebuild" in client_src,
   "cmd_ticket docstring/op 清单点名（防 op 面文档漂移）")

# ===========================================================================
# Part B — behavior half (engine venv, real files, real module entry points)
# ===========================================================================
def find_engine_python() -> str | None:
    for cand in ("server/engine/.venv/bin/python",
                 "server/dsh/temporal-poc/.venv/bin/python"):
        p = ROOT / cand
        if p.exists():
            return str(p)
    return None


section("B0 行为半供给判定")
ENGINE_PY = find_engine_python()
BEHAVIOR_SRC = (ROOT / "integration/t260928-13"
                / "behavior_probe.py")
behavior = None
if EL.exists() and ENGINE_PY:
    # Drive the real module in a child process so the in-process cache state
    # is per-probe (cold-cache case needs a fresh process anyway).
    r = subprocess.run(
        [ENGINE_PY, "-B", str(BEHAVIOR_SRC)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPYCACHEPREFIX": str(ROOT / "out/pycache")})
    print(r.stdout)
    if r.returncode == 2:
        env_fail("引擎 venv temporalio 缺失（行为半）：%s" %
                 (r.stderr.strip().splitlines() or ["<no stderr>"])[-1][:200])
    elif r.returncode != 0:
        # probe failed = real reds, already printed by the child
        FAIL += 1
        print("  ✗ 行为半探针非零退出（见上方逐条）：%s" %
              (r.stderr.strip().splitlines() or ["<no stderr>"])[-1][:200])
    else:
        m = re.search(r"^BEHAVIOR_PASS=(\d+)$", r.stdout, re.M)
        mf = re.search(r"^BEHAVIOR_FAIL=(\d+)$", r.stdout, re.M)
        if m and mf:
            ok(int(mf.group(1)) == 0,
               "行为半 %d/%d 绿（real-module 契约面）" %
               (int(m.group(1)), int(m.group(1)) + int(mf.group(1))))
        else:
            ok(False, "行为半回执缺 BEHAVIOR_PASS/FAIL 行（探针被改坏）")
elif not EL.exists():
    ok(False, "event_ledger.py 缺席：行为半未跑（TDD 红属预期，实现段落地后须绿）")
else:
    env_fail("引擎 venv 缺失且系统 python 无 temporalio：行为半无法驱动（源码锁半照跑）")

# ===========================================================================
# Verdict
# ===========================================================================
print("\n==== summary: PASS=%d FAIL=%d ENV_FAIL=%d" % (PASS, FAIL, ENV))
if ENV:
    sys.exit(2)
sys.exit(1 if FAIL else 0)
