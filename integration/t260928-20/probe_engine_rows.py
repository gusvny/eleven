#!/usr/bin/env python3
"""probe_engine_rows.py — child probe of sc_ledger_engine_scope_rows
(t260928-20, engine-scope ledger rows).

Runs INSIDE the engine venv. Drives the REAL server/engine/event_ledger.py
through its public entry points (append_event / _engine_project_key /
expected_lines) against a FAKE registry (tmp SANDBAR_PROJECTS_DIR) and a real
tmp ledger dir (SANDBAR_EVENT_LEDGER_DIR). Prints per-assertion ✓/✗ and ends
with BEHAVIOR_PASS=<n> / BEHAVIOR_FAIL=<n>. Exit 0 always; exit 2 only when
temporalio itself is missing.

The fake engine-owner entry mirrors the REAL declaration shape (the machine
registry uses ~/.sandbar/projects/<key>/project.yaml with a project: entry
whose dirs cover the engine repo root, plus the top-level event_ledger:
block — KI-149's face gains NO new key here, which the parent source-locks).
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

try:
    import temporalio  # noqa: F401
except Exception as exc:  # pragma: no cover
    print("ENV_FAIL: temporalio 不可导入：%r" % (exc,))
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server/engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


TMP = Path(tempfile.mkdtemp(prefix="t260928-20-engine-probe-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)   # L8：全终态回收
LEDGER = TMP / "ledger"
LEDGER.mkdir(parents=True, exist_ok=True)
PROJ = TMP / "projects"
ENGINE_ENTRY = PROJ / "engowner"
ENGINE_ENTRY.mkdir(parents=True, exist_ok=True)

ENGINE_REPO = (ROOT / "server").resolve().parent   # 引擎仓根（与模块内推导同值）

YAML_ENABLED = (
    "# fake registry fixture (t260928-20 probe; real declaration shape)\n"
    "project:\n"
    "  - key: engine-owner-test\n"
    "    name: engine owner fixture\n"
    "    dirs:\n"
    "      - %s\n"
    "      - %s\n"
    "event_ledger:\n"
    "  enabled: true\n"
    "  keep_days: 14\n" % (ENGINE_ENTRY.resolve(), ENGINE_REPO))
YAML_DISABLED = (
    "project:\n"
    "  - key: engine-owner-test\n"
    "    dirs:\n"
    "      - %s\n"
    "event_ledger:\n"
    "  enabled: false\n" % ENGINE_REPO)


def set_registry(text):
    (ENGINE_ENTRY / "project.yaml").write_text(text, encoding="utf-8")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(PROJ)
    el.reset_config_for_test()
    el.reset_engine_project_for_test()


def lines_of(project):
    p = LEDGER / ("%s.jsonl" % project)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


os.environ["SANDBAR_EVENT_LEDGER_DIR"] = str(LEDGER)

import event_ledger as el  # noqa: E402

set_registry(YAML_ENABLED)

print("\n== E1 引擎所属项目解析（既有 dirs-覆盖-仓根规则，不新造概念）")
key = el._engine_project_key()
ok(key == "engine-owner-test", "dirs 覆盖引擎仓根的条目被解析为落账目标（key=%r）" % key)
cfg = el.event_ledger_config()
ok(cfg.get("enabled") is True, "同一份声明的 enabled 闸生效（配置闸与落账目标同源）")

print("\n== E2 engine 行落引擎所属项目的账（无第二文件）")
r = el.append_event({
    "scope": "engine", "project": "", "ticket": "eng-scan-1",
    "workflow": "DispatcherScanWorkflow", "template": "",
    "stage": "scan", "state": "done", "reason": "dispatch scan finished",
    "run_id": "run-E1", "seq": 1, "idem": "eng-scan-1|run-E1|1",
})
ok(bool(r.get("emitted")), "engine 行被接收（emitted=True）")
rows = lines_of("engine-owner-test")
ok(len(rows) == 1, "行落引擎所属项目账本（一个项目一个文件，无第二账本）")
if rows:
    ok(rows[0].get("scope") == "engine", "行 scope=engine（执行器自己的手）")
    ok(rows[0].get("project") == "engine-owner-test",
       "行 project=解析出的引擎所属键（非空、非幻影）")
    ok(rows[0].get("ticket") == "eng-scan-1", "行带引擎活动标识（ticket=引擎活动面）")
ok(not (LEDGER / ".jsonl").exists(), "账本目录无畸形 `.jsonl` 文件（well-formed 面）")
ok(all(p.name == "engine-owner-test.jsonl" for p in LEDGER.glob("*.jsonl")),
   "未出现第二个账本文件（no new engine ledger concept）")

print("\n== E3 解析失败：fail-open + LOUD，绝不炸主流程、绝不落畸形行")
empty = TMP / "empty-registry"
empty.mkdir(exist_ok=True)
os.environ["SANDBAR_PROJECTS_DIR"] = str(empty)
el.reset_config_for_test()
el.reset_engine_project_for_test()
try:
    r2 = el.append_event({
        "scope": "engine", "project": "", "ticket": "eng-scan-2",
        "stage": "spawn", "state": "running", "run_id": "run-E2",
        "seq": 1, "idem": "eng-scan-2|run-E2|1",
    })
    ok(r2.get("emitted") is False, "解析失败 → 行未落账（emitted=False）")
    ok("why" in r2, "回执带 why（报错精确：哪个检查失败）")
except Exception as e:  # noqa: BLE001
    ok(False, "解析失败面炸出异常（fail-open 被破坏）：%s: %s" % (type(e).__name__, e))
ok(not [p for p in LEDGER.glob("*.jsonl") if p.name != "engine-owner-test.jsonl"],
   "解析失败零新增文件（announce-only，无幻影项目文件）")
ok(len(lines_of("engine-owner-test")) == 1, "解析失败零新增行（E2 的 1 行未被污染）")

print("\n== E4 project 族空身份绝不冒充 engine 行（review C2）")
set_registry(YAML_ENABLED)
el._SEEN.clear()
r3 = el.append_event({
    "scope": "project", "project": "", "ticket": "proj-orphan-1",
    "stage": "setup", "state": "running", "run_id": "run-E3",
    "seq": 1, "idem": "proj-orphan-1|run-E3|1",
})
rows = lines_of("engine-owner-test")
ok(not any(x.get("idem") == "proj-orphan-1|run-E3|1" for x in rows),
   "空身份 project 行不落引擎所属账（跳过+点名，不静默写错地方）")
ok(not any(x.get("scope") == "engine" and "orphan" in str(x.get("ticket"))
           for x in rows),
   "project 族空身份不冒充 engine 行（C2）")
ok(not (LEDGER / ".jsonl").exists(), "空身份 project 载荷不产生畸形 `.jsonl` 文件")

print("\n== E4b 停用闸：undeclared/disabled ⇒ 引擎行同样零落账")
set_registry(YAML_DISABLED)
el._SEEN.clear()
before = len(lines_of("engine-owner-test"))
el.append_event({
    "scope": "engine", "project": "", "ticket": "eng-scan-3",
    "stage": "scan", "state": "running", "run_id": "run-E4",
    "seq": 1, "idem": "eng-scan-3|run-E4|1",
})
ok(len(lines_of("engine-owner-test")) == before, "停用 ⇒ 零新行（零行为变化面）")
set_registry(YAML_ENABLED)
el._SEEN.clear()

print("\n== E5 幂等 × 新 run（去重/不误吞，引擎行同口径）")
p1 = {"scope": "engine", "project": "", "ticket": "eng-watch-1",
      "workflow": "InspectionTicketCountWatcherWorkflow", "stage": "watch",
      "state": "running", "reason": "count below threshold",
      "run_id": "run-E5", "seq": 1,
      # idem 同 mixin 形（project|ticket|run_id|seq，t260928-13 键面）
      "idem": "engine-owner-test|eng-watch-1|run-E5|1"}
el.append_event(p1)
el.append_event(dict(p1))                       # at-least-once 重投
ok(len([x for x in lines_of("engine-owner-test")
        if x["ticket"] == "eng-watch-1"]) == 1, "同 idem 重投仍一行")
el.append_event(dict(p1, run_id="run-E6",
                     idem="engine-owner-test|eng-watch-1|run-E6|1"))
ok(len([x for x in lines_of("engine-owner-test")
        if x["ticket"] == "eng-watch-1"]) == 2, "新 run 出新行（不误吞）")

print("\n== E6 行形状面（schema 完整 + <4KB + marks 可重导出）")
rows = lines_of("engine-owner-test")
need = ("v", "project", "scope", "ticket", "workflow", "template", "stage",
        "state", "reason", "gen", "ts", "seq", "run_id", "idem", "engine")
ok(bool(rows) and all(all(k in r for k in need) for r in rows),
   "声明字段集逐行全在位")
raw = (LEDGER / "engine-owner-test.jsonl").read_bytes().splitlines()
ok(all(len(x) < 4096 for x in raw), "行 <4KB")
exp = el.expected_lines(
    [{"stage": r["stage"], "state": r["state"], "reason": r["reason"]}
     for r in rows], "engine-owner-test", ticket="eng-watch-1",
    workflow_class="engine-scope",
    marks=[{"i": i, "seq": r["seq"], "run": r["run_id"]}
           for i, r in enumerate(rows) if r["ticket"] == "eng-watch-1"])
ok(bool(exp) and all(e["idem"] in {x["idem"] for x in rows} for e in exp),
   "marks 轨可重导出引擎行（观测面可对账）")

print("BEHAVIOR_PASS=%d" % PASS)
print("BEHAVIOR_FAIL=%d" % FAIL)
sys.exit(0)
