#!/usr/bin/env python3
"""check_inspection_produce_chain.py — 产出型巡检链离线源码锁+纯函数回放
（t260925-01；temporalio 不可导入环境既定模式，sc_check_auto_rework_trace 同款）。

锁面（工单验收 A1–A6 的离线锚）：
  A 声明面：mode/docs_root 两键在实例词表、mode 词表、docs_root 缺省=docs（A6 引擎
    默认无 sandbar 硬编码）、WIRED_WORKFLOWS 收 InspectionProduceWorkflow；
  B 契约面：inspection_produce 围栏强 schema（畸形输入回放 fail-closed——消费外部
    输入钩子）、写集闸越界点名（A2）、保护面点名不硬失败（A3）、零 change 显式（A5）、
    受限可写 pin=workspace-write 形态且区别于只读钉（A4 对照面）；
  C 活动面：run_inspection_produce 注册进 ALL_AGENT_ACTIVITIES、桩注入缝
    （SANDBAR_PRODUCE_STUB/_FILE）、差分真源=git（diff/status 双路在源）；
  D workflow 面：InspectionProduceWorkflow 独立 @workflow.defn、STAGES 无 dev-lane
    段位（implement/arbitrate/design_integration_tests 零命中）、独立 gate id、
    approve 红灯闸（_approve_blockers 引用三态键）、merge/teardown 收口接线；
  E 起票面：open_period_ticket per_ticket_queue 参数（KI-113：produce 不落共享队列）、
    inspection_trigger trigger-produce 子命令、queue=per-ticket 回执键。

Run directly: python3 integration/sc_check_inspection_produce_chain.py（cwd=仓根）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

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


def section(title):
    print("\n%s" % title)


import inspection_decl as decl  # noqa: E402
import inspection_produce as prod  # noqa: E402

ACT_SRC = (ROOT / "server/engine/agent_activities.py").read_text("utf-8")
FLOW_SRC = (ROOT / "server/engine/inspection_flow.py").read_text("utf-8")
TICK_SRC = (ROOT / "server/engine/inspection_ticketing.py").read_text("utf-8")
TRIG_SRC = (ROOT / "server/engine/inspection_trigger.py").read_text("utf-8")
WF_SRC = (ROOT / "server/engine/workflows.py").read_text("utf-8")

# ---------- A 声明面 ----------
section("A 声明面（A6）")
ok(decl.WIRED_MODES == ("report", "produce"), "mode 词表=report|produce")
ok(decl.DEFAULT_MODE == "report", "mode 缺省=report（未声明零行为）")
ok(decl.DEFAULT_DOCS_ROOT == "docs", "docs_root 引擎缺省=docs（A6）")
ok("InspectionProduceWorkflow" in decl.WIRED_WORKFLOWS,
   "WIRED_WORKFLOWS 收产出型 workflow")
ok("mode" in (ROOT / "server/engine/inspection_decl.py").read_text("utf-8"),
   "decl 源含 mode 键解析")
for bad in ("/abs", "a/../b", "docs/"):
    try:
        decl.validate_docs_root("t", bad)
        ok(False, "docs_root 拒 %r" % bad)
    except decl.DeclError:
        ok(True, "docs_root 拒 %r" % bad)

# ---------- B 契约面 ----------
section("B 契约面（A2/A3/A4/A5）")
good = ('```json\n{"changes": [{"path": "docs/a.md", "action": "modify",'
        ' "summary": "s"}], "zero_change": false, "evidence": []}\n```')
ok(prod.parse_agent_changes(good)["changes"][0]["path"] == "docs/a.md",
   "围栏强 schema 正例过闸")
for bad_text in ("no fence", "```json\n{}\n```", "```json\nbad\n```",
                 '```json\n{"changes": [], "zero_change": 1}\n```'):
    try:
        prod.parse_agent_changes(bad_text)
        ok(False, "畸形围栏拒收")
    except prod.ProduceParseError:
        ok(True, "畸形围栏拒收（fail-closed）")
hits = prod.check_write_set(["docs/a.md", "server/x.py"], "docs")
ok(len(hits) == 1 and hits[0]["path"] == "server/x.py",
   "写集闸越界点名（A2）")
ok(prod.check_write_set(["docs/a.md"], "docs") == [], "写集闸根内放行")
ov = prod.check_protected_overlap(["docs/design/x.md"], ["docs/design"])
ok(ov == ["docs/design", "docs/design/x.md"], "保护面点名不硬失败（A3）")
ok("evidence" in prod.check_zero_change([], True, []),
   "零 change 缺证据判红（A5）")
ok("造假" in prod.check_zero_change([{"path": "docs/a.md"}], True, ["e"]),
   "零 change 与 changes 并存判红（A5）")
pin = prod.produce_write_pin_patch("docs")
ok("workspace-write" in pin and "read-only" not in pin,
   "produce pin=受限可写，非只读钉（A4 对照）")
ro_pin = __import__("inspection_inspect").readonly_pin_patch()
ok("read-only" in ro_pin, "报告链只读钉不动（A4）")

# ---------- C 活动面 ----------
section("C 活动面")
ok("async def run_inspection_produce(" in ACT_SRC, "produce 活动在位")
ok("run_inspection_produce" in ACT_SRC.split("ALL_AGENT_ACTIVITIES")[1],
   "produce 活动已注册进 ALL_AGENT_ACTIVITIES")
ok("SANDBAR_PRODUCE_STUB" in ACT_SRC and "SANDBAR_PRODUCE_STUB_FILE" in ACT_SRC,
   "桩注入缝（UT/场景与真进程同链）")
ok('"git", "-C", str(base), "diff"' in ACT_SRC
   and '"git", "-C", str(base), "status"' in ACT_SRC,
   "差分真源=git（diff/status 双路）")
ok("check_write_set" in ACT_SRC and "check_protected_overlap" in ACT_SRC
   and "check_zero_change" in ACT_SRC and "doc_selfcheck" in ACT_SRC,
   "四闸全接线（写集/保护面/零change/文档自检）")
ok("readonly_pin_patch()" not in ACT_SRC.split("run_inspection_produce")[1]
   .split("ALL_AGENT_ACTIVITIES")[0].replace("produce_write_pin_patch", ""),
   "produce 段不误用只读钉（A4）")

# ---------- D workflow 面 ----------
section("D workflow 面（A1）")
ok("@workflow.defn\nclass InspectionProduceWorkflow" in FLOW_SRC,
   "InspectionProduceWorkflow 独立 defn（与 dev-lane 分链）")
produce_cls_src = FLOW_SRC.split("class InspectionProduceWorkflow")[1]
ok(not any(tok in produce_cls_src for tok in
           ("design_integration_tests", "arbitrate", "review_plan")),
   "无 dev-lane 段位（工单要点1）")
ok('gate=PRODUCE_CLOSE_GATE_ID' in produce_cls_src.replace(
    'expected_gate=PRODUCE_CLOSE_GATE_ID', 'gate=PRODUCE_CLOSE_GATE_ID'),
   "人审门用 produce gate id（不带旧字面值）")
ok("validate_authorize_payload" in produce_cls_src
   and "_approve_blockers" in produce_cls_src,
   "authorize 门 + approve 红灯闸在位（A3）")
ok("defer_teardown=True" in produce_cls_src and "teardown_lane" in produce_cls_src,
   "approve=merge（defer teardown）/ reject=discard 收口接线（A1）")
# F-1 回归锁（验收 gen0 打回点）：授权复跑必须有消费点——门等待位=签字或 _rerun_paths，
# 且 produce 活动对 focus=授权清单真执行（非单趟 break 假循环）。
ok("_close_sig is not None or bool(self._rerun_paths)" in produce_cls_src,
   "门等待位含授权复跑请求（wait_condition 双条件）")
ok('"focus": rerun_paths' in produce_cls_src
   and produce_cls_src.count('run_inspection_produce') >= 2,
   "授权复跑：produce 活动以 focus=授权清单真执行（≥2 个调用点）")
ok("_rerun_paths = []" in produce_cls_src.replace(
    "self._rerun_paths: List[str] = []", ""),
   "复跑请求消费后即清位（防重复复跑）")
ok("InspectionProduceWorkflow" in WF_SRC, "workflows.py 注册表收录")

# ---------- E 起票面（KI-113） ----------
section("E 起票面（per-ticket 队列）")
ok("per_ticket_queue: bool = False" in TICK_SRC, "open_period_ticket 新参数在位")
ok("ticket_task_queue(ticket_id) if per_ticket_queue" in TICK_SRC,
   "队列选择单点：per_ticket=True→ticket_task_queue")
ok('add_parser("trigger-produce"' in TRIG_SRC
   and "cmd_trigger_produce" in TRIG_SRC,
   "trigger-produce CLI 子命令接线")
ok('"queue": "per-ticket"' in TRIG_SRC, "回执带队列口径键")

# ---------- 收尾 ----------
print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
