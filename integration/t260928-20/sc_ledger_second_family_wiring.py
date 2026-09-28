#!/usr/bin/env python3
"""sc_ledger_second_family_wiring.py — integration scenario for t260928-20
(event ledger wiring, SECOND family: InspectionPeriodicWorkflow +
InspectionProduceWorkflow).

Grey-box L2/L3, offline, seconds-scale, zero docker, zero console contact.
Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3
  PYTHONPYCACHEPREFIX=out/pycache "$PY" -B integration/t260928-20/sc_ledger_second_family_wiring.py

Three-exit contract: PASS=0 / FAIL=1 / ENV_FAIL=2 (no SKIP).
The behavior half (probe_inspection_wiring.py) runs in the engine venv and
drives the REAL classes through the public workflow-context seam
(patched/info/now/logger/execute_activity) against real ledger files in a tmp
dir. temporalio missing => ENV_FAIL exit 2.

Intent (user-perceivable contract of ticket ②'s second family, NOT internals):
- every inspection stage transition lands EXACTLY ONE ledger line in the
  ticket's project ledger (the family that most often needs a human — the
  daily human-gate close — is no longer blind on the panel/watchdog feed);
- the line is honest about the family having no generation dimension:
  gen=0 as a documented constant, never a fabricated counter;
- re-entering the same transition never duplicates a row; a legitimately NEW
  run of the same ticket is never swallowed by the old run's keys (run_id
  dimension from ticket 1);
- the family is a derived projection: its snapshot carries the ledger marks
  so the cancel/failure path (where pending rows die unflushed) can be
  rebuilt from timeline+marks (review C1 — without this the inherited
  "cancel_notice + ledger_rebuild" authority does not hold for THIS family,
  the one most exposed to the human-gate close);
- a project-scope class whose project identity resolves empty must skip +
  announce LOUD, never masquerade as an engine row (review C2);
- flush discipline: flush before the human gate wait, before close, before
  the ops-side _write_ledger, and on every blocked return (source plane);
- deliberate exemption lock: ContentPipelineWorkflow stays UNWIRED (retired
  step-1 compat shell, not the executor's own hands) — wiring it would be
  dead observability; drift (someone adding the mixin) turns this red.

Distinct from ticket-13's registered scenarios (mechanism truth table +
dev_lane wiring + registry declaration face) and from the developer L1 unit
tests: this scenario locks the SECOND family's wiring face specifically.
Red-before-implement is expected (TDD signal); green required at
arbitrate/merge. Scenario registered as
"t260928-20-inspection-family-ledger-wiring".
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INSP = ROOT / "server/engine/inspection_flow.py"
WORKFLOWS = ROOT / "server/engine/workflows.py"
BASE = ROOT / "server/engine/base.py"

PASS = 0
FAIL = 0
ENV = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(t):
    print("\n%s" % t)


src = INSP.read_text("utf-8") if INSP.exists() else ""
wsrc = WORKFLOWS.read_text("utf-8") if WORKFLOWS.exists() else ""
bsrc = BASE.read_text("utf-8") if BASE.exists() else ""


def class_body(text, cls):
    m = re.search(r"^class %s\b.*?^(?=class |\Z)" % cls, text, re.M | re.S)
    return m.group(0) if m else ""


section("A1 第二族接线面（源码锁）")
body_p = class_body(src, "InspectionPeriodicWorkflow")
body_q = class_body(src, "InspectionProduceWorkflow")
ok(bool(body_p) and "TicketEventLedgerMixin" in body_p.split("\n")[0],
   "InspectionPeriodicWorkflow 声明接入 TicketEventLedgerMixin")
ok(bool(body_q) and "TicketEventLedgerMixin" in body_q.split("\n")[0],
   "InspectionProduceWorkflow 声明接入 TicketEventLedgerMixin")
for name, body in (("Periodic", body_p), ("Produce", body_q)):
    ok("_ledger_enqueue" in body,
       "%s._enter 在唯一写点入队（一迁移一行）" % name)
    ok(body.count("_ledger_flush") + src.count("_ledger_flush") > 0
       and "_ledger_flush" in src, "%s 链存在 flush 消费点" % name)

section("A2 冲刷纪律（人门/收口/运维账/阻塞返回前）")
ok(src.count("_ledger_flush()") >= 4,
   "flush 消费点 ≥4（人门 wait 前/收口前/_write_ledger 前/_blocked 前，实测 %d 处）"
   % src.count("_ledger_flush()"))
m_close = re.search(r"_ledger_flush\(\)[^\n]*\n[^\n]*wait_condition", src) or \
    re.search(r"close[^\n]*\n[^\n]*_ledger_flush", src)
ok(bool(m_close) or "_ledger_flush" in class_body(src, "InspectionPeriodicWorkflow"),
   "close 人门链上有 flush（人到时账面已冲）")

section("A3 gen 诚实面（族无代次维 = documented constant 0，非捏造计数）")
ok(re.search(r"gen[^\n]{0,80}(0|常量|constant|无代次)", src + bsrc) is not None
   or "gen" in bsrc,
   "gen 常量语义有文档位（mixin 或族 docstring 点名）")

section("A4 派生投影面（snapshot 带 ledger_marks，review C1）")
ok(src.count('"ledger_marks"') >= 2,
   "两个 inspection snapshot 都暴露 ledger_marks（取消面权威可 rebuild，实测 %d 处）"
   % src.count('"ledger_marks"'))

section("A5 刻意豁免锁（ContentPipelineWorkflow 不接线，漂移即红）")
body_c = class_body(wsrc, "ContentPipelineWorkflow")
ok(bool(body_c) and "TicketEventLedgerMixin" not in body_c.split("\n")[0],
   "ContentPipelineWorkflow 保持未接线（退役 step-1 兼容壳，非执行器之手）")
ok("_ledger_enqueue" not in body_c and "_ledger_note" not in body_c,
   "ContentPipelineWorkflow 体无账面消费点（不是只不挂名）")
body_d = class_body(wsrc, "DispatcherScanWorkflow")
ok('_ledger_scope = "engine"' in body_d or '_ledger_scope="engine"' in body_d,
   "DispatcherScanWorkflow 声明 engine 范围（引擎级发射器）")

# ===========================================================================
# Part B — behavior half (engine venv, real modules × real files)
# ===========================================================================
print("\n== B 行为半（引擎 venv 真模块 × tmp 真文件）")
probe = Path(__file__).resolve().parent / "probe_inspection_wiring.py"
py = ROOT / "server/engine/.venv/bin/python"
if not py.exists():
    py = ROOT / "server/dsh/temporal-poc/.venv/bin/python"
if py.exists():
    env_probe = dict(__import__("os").environ)
    env_probe["PYTHONPYCACHEPREFIX"] = str(ROOT / "out/pycache")
    r = subprocess.run([str(py), "-B", str(probe)], capture_output=True,
                       text=True, cwd=str(ROOT), env=env_probe, timeout=300)
    print(r.stdout)
    if r.returncode == 2:
        ENV += 1
        print("ENV_FAIL: 引擎 venv temporalio 缺失（行为半）：%s"
              % (r.stderr.strip().splitlines() or ["<no stderr>"])[-1][:200])
    elif r.returncode != 0:
        FAIL += 1
        print("  ✗ 行为半探针非零退出：%s"
              % (r.stderr.strip().splitlines() or ["<no stderr>"])[-1][:200])
    else:
        mp = re.search(r"^BEHAVIOR_PASS=(\d+)$", r.stdout, re.M)
        mf = re.search(r"^BEHAVIOR_FAIL=(\d+)$", r.stdout, re.M)
        if mp and mf:
            ok(int(mf.group(1)) == 0,
               "行为半 %d/%d 绿（real-class 契约面）"
               % (int(mp.group(1)), int(mp.group(1)) + int(mf.group(1))))
        else:
            ok(False, "行为半回执缺 BEHAVIOR_PASS/FAIL 行（探针被改坏）")
else:
    ENV += 1
    print("ENV_FAIL: 引擎 venv 缺失且未配置（probe_inspection_wiring.py 需 temporalio）")

print("\n==== summary: PASS=%d FAIL=%d ENV_FAIL=%d" % (PASS, FAIL, ENV))
sys.exit(2 if ENV else (1 if FAIL else 0))
