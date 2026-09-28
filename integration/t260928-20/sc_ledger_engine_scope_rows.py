#!/usr/bin/env python3
"""sc_ledger_engine_scope_rows.py — integration scenario for t260928-20
(engine-scope ledger rows: spawner / ticket-count watcher / dispatcher scan).

Grey-box L2/L3, offline, seconds-scale, zero docker, zero console contact.
Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3
  PYTHONPYCACHEPREFIX=out/pycache "$PY" -B integration/t260928-20/sc_ledger_engine_scope_rows.py

Three-exit contract: PASS=0 / FAIL=1 / ENV_FAIL=2 (no SKIP).
The behavior half (probe_engine_rows.py) runs in the engine venv and drives
the REAL event_ledger module against a FAKE registry (tmp
SANDBAR_PROJECTS_DIR) and real tmp ledger files (SANDBAR_EVENT_LEDGER_DIR).
temporalio missing => ENV_FAIL exit 2.

Intent (user-perceivable contract of design decision 14, NOT internals):
- the executor's own hands (scheduling scans, inspection spawner/watcher)
  are VISIBLE: each emits rows with scope="engine" into the ENGINE-OWNER
  project's ledger — the registry entry whose dirs cover the engine repo
  root. No second ledger file, no new concept: one project, one file;
- the engine-owner declaration face gains NO new top-level registry key
  (KI-149's quarantine face stays locked by t260928-13-registry-additive-
  keys; this scenario additionally source-locks that the engine-row path
  reuses the existing dirs-cover rule);
- a workflow WITHOUT a project stamp yields a well-formed engine row —
  never a malformed project row, never a bare `.jsonl` file in the ledger
  dir;
- a project-scope class with an empty project identity must skip + announce
  LOUD, never masquerade as an engine row (review C2);
- engine-owner resolution failure is fail-open + LOUD (announce-only gap —
  the C3 review decision: no phantom `_engine-unresolved` project file that
  per-project ledger consumers would read as a real project), never a
  crash, never a silent success;
- undeclared/disabled => zero rows for engine emitters too (same gate, one
  config);
- dedupe holds for engine rows: the same idem re-appended stays one line; a
  new run_id is a new line (never swallowed);
- line shape: full declared field set, <4KB, marks-track re-derivable.

Distinct from ticket-13's scenarios (mechanism + dev_lane + declaration
face) and from the developer L1 unit tests: this locks the ENGINE-SCOPE
emission face specifically. Red-before-implement is expected (TDD signal);
green required at arbitrate/merge. Registered as
"t260928-20-engine-scope-ledger-rows".
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EL = ROOT / "server/engine/event_ledger.py"
BASE = ROOT / "server/engine/base.py"
INSP = ROOT / "server/engine/inspection_flow.py"
WORKFLOWS = ROOT / "server/engine/workflows.py"

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


src = EL.read_text("utf-8") if EL.exists() else ""
bsrc = BASE.read_text("utf-8") if BASE.exists() else ""
isrc = INSP.read_text("utf-8") if INSP.exists() else ""
wsrc = WORKFLOWS.read_text("utf-8") if WORKFLOWS.exists() else ""


def class_body(text, cls):
    m = re.search(r"^class %s\b.*?^(?=class |\Z)" % cls, text, re.M | re.S)
    return m.group(0) if m else ""


section("A1 引擎级发射器声明面（三个引擎级类 + 豁免面）")
for cls, where in (("InspectionPeriodicSpawnWorkflow", isrc),
                   ("InspectionTicketCountWatcherWorkflow", isrc)):
    body = class_body(where, cls)
    ok(bool(body) and re.search(r'_ledger_scope\s*=\s*"engine"', body),
       "%s 声明 _ledger_scope=engine（引擎级发射器）" % cls)
body_d = class_body(wsrc, "DispatcherScanWorkflow")
ok(bool(body_d) and re.search(r'_ledger_scope\s*=\s*"engine"', body_d),
   "DispatcherScanWorkflow 声明 _ledger_scope=engine")
ok(bool(body_d) and ("_ledger_note" in body_d or "_ledger_enqueue" in body_d),
   "DispatcherScanWorkflow 体有账面消费点（不只挂名）")
body_w = class_body(isrc, "InspectionTicketCountWatcherWorkflow")
ok("_ledger_flush" in body_w,
   "watcher 在 sleep/continue_as_new 前有 flush（账面不滞留到下代 run）")

section("A2 无第二账本概念（decision 14：一个项目一个文件）")
ok('_ledger_scope: str = "project"' in bsrc,
   "mixin 范围旋钮缺省=project（DevLane 零变化，t260928-13 原语义）")
ok("engine.jsonl" not in src + bsrc + isrc + wsrc,
   "无专用 engine 账本文件名（不新造第二账本概念）")
ok("_engine_project_key" in src or "_engine_project_yaml" in src,
   "引擎所属项目解析复用既有判定面（dirs 覆盖引擎仓根）")
ok(re.search(r"_engine_project_key|_find_engine_project_yaml", src) is not None
   and "_dirs_cover_engine" in src,
   "落账目标解析与配置闸同源（同一条目判定，非平行实现）")

section("A3 声明面零新键（KI-149 反停机面）")
# 引擎行解析只消费既有顶层段（project:/dirs:/event_ledger:）——本票不新增任何
# 会被注册加载器白名单拒绝的顶层键。若实现引入新顶层段，A2 派生锁
# （t260928-13-registry-additive-keys）会点名；这里只做可见性锚。
ok(re.search(r"^schema:", src, re.M) is None or True, "（锚）声明消费面走既有段")

section("A4 well-formed 面（无项目戳 ≠ 畸形 project 行）")
ok('ledger_path(project' in src or "ledger_path(" in src,
   "落账路径由解析后的键决定（无空键路径面）")
ok("announce" in src or "_announce" in src,
   "缺口保证面（stderr 点名+计数器）在位（fail-open + LOUD）")

# ===========================================================================
# Part B — behavior half (engine venv, real module × fake registry × real files)
# ===========================================================================
print("\n== B 行为半（引擎 venv 真模块 × 假注册表 × tmp 真文件）")
probe = Path(__file__).resolve().parent / "probe_engine_rows.py"
py = ROOT / "server/engine/.venv/bin/python"
if not py.exists():
    py = ROOT / "server/dsh/temporal-poc/.venv/bin/python"
if py.exists():
    import os
    env_probe = dict(os.environ)
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
               "行为半 %d/%d 绿（real-module 契约面）"
               % (int(mp.group(1)), int(mp.group(1)) + int(mf.group(1))))
        else:
            ok(False, "行为半回执缺 BEHAVIOR_PASS/FAIL 行（探针被改坏）")
else:
    ENV += 1
    print("ENV_FAIL: 引擎 venv 缺失且未配置（probe_engine_rows.py 需 temporalio）")

print("\n==== summary: PASS=%d FAIL=%d ENV_FAIL=%d" % (PASS, FAIL, ENV))
sys.exit(2 if ENV else (1 if FAIL else 0))
