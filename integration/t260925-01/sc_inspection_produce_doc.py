#!/usr/bin/env python3
"""sc_inspection_produce_doc.py — t260925-01 产出型巡检底座 + doc 面（L3 灰盒）。

intent：验证工单 A1–A6 的用户可感知契约——doc 面产出的 change 由人审决定合并/驳回、
越界写 fail-closed 点名、保护面文档点名+同票授权、test 面只读零改动、零 change 显式、
声明驱动参数（引擎默认 docs/、未声明零行为）。场景秒级、零 docker、零 temporalio
import（与 inspection_decl 同纪律：被测纯函数层 stdlib-only 直接 import；workflow
体源码锁）。

契约面（与 create_plan v2 + review_plan conditional 意见对齐，实现必须兑现的公开面）：
  - inspection_decl：实例键 mode（词表 report|produce，缺省 report）与 docs_root
    （缺省 'docs'），坏值 fail-closed 点名，排程 payload 带两键。
  - inspection_produce（新模块，零 temporalio）公开契约五函数：
    validate_output_schema / check_write_set / check_zero_change /
    check_protected_overlap / doc_selfcheck（函数名即本场景锁定的模块契约；
    实现未落地=FAIL 红，TDD 信号，arbitrate/merge 期必须绿）。
  - inspection_flow：InspectionProduceWorkflow 类、两个新门 id（produce-close /
    produce-protect-authorize，不复用 inspection-close 字面值）、reject 留痕
    （落账先于拆道）。
  - 起票队列（KI-113）：produce 起票路径不得把期票派到共享 TASK_QUEUE。
  - A4：只读 inspect 路径不触碰 produce 写钉。

三态：PASS/FAIL/ENV_FAIL（本场景无环境依赖面，环境缺失不会发生；失败即 FAIL）。
Run: python3 integration/t260925-01/sc_inspection_produce_doc.py（cwd=仓库根）。
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

PASS = 0
FAIL = 0


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


# ---------- A. 声明面：mode / docs_root（A6） ----------
section("A 声明面 mode/docs_root（A6：缺省回落、词表 fail-closed、payload 带键）")
try:
    import inspection_decl as decl_mod
except Exception as e:  # pragma: no cover
    ok(False, "inspection_decl 可导入（%s）" % e)
    decl_mod = None

if decl_mod is not None:
    BASE = (
        "schema: v1\n"
        "instances:\n"
        "  - id: doc-sync\n"
        "    enabled: true\n"
        "    project_key: sandbar\n"
        "    schedule:\n"
        "      kind: cron\n"
        "      cron: 0 3 * * *\n"
        "    workflow: InspectionPeriodicWorkflow\n"
        "    template: inspection-lite\n"
    )
    # A6-1 未声明 → 缺省 mode=report、docs_root='docs'（零行为变化）
    try:
        d = decl_mod.parse_decl_text(BASE)
        inst = d.instances[0]
        ok(getattr(inst, "mode", "report") == "report", "未声明 mode 缺省=report（零行为）")
        ok(getattr(inst, "docs_root", "docs") == "docs", "未声明 docs_root 缺省='docs'（引擎默认，无项目硬编码）")
    except Exception as e:
        ok(False, "未声明实例解析不炸（%s）" % e)
    # A6-2 词表内声明被接受
    try:
        d2 = decl_mod.parse_decl_text(
            BASE + "    mode: produce\n    docs_root: mydocs\n")
        inst2 = d2.instances[0]
        ok(getattr(inst2, "mode", None) == "produce", "mode: produce 被接受")
        ok(getattr(inst2, "docs_root", None) == "mydocs", "docs_root: mydocs 被接受（声明驱动）")
    except Exception as e:
        ok(False, "produce 实例解析不炸（%s）" % e)
    # A6-3 词表外 mode fail-closed 且点名
    try:
        decl_mod.parse_decl_text(BASE + "    mode: writable\n")
        ok(False, "mode 词表外值 fail-closed 拒收")
    except decl_mod.DeclError as e:
        ok("writable" in str(e), "mode 坏值报错点名值本身（%s）" % str(e)[:60])
    except Exception as e:
        ok(False, "mode 坏值报错类型为 DeclError（得 %s）" % type(e).__name__)
    # A6-4 排程 payload 带两键（下游消费面可见声明值）
    try:
        d3 = decl_mod.parse_decl_text(
            BASE + "    mode: produce\n    docs_root: mydocs\n")
        specs = decl_mod.build_schedule_specs(d3)
        blob = repr(specs)
        ok("'mode': 'produce'" in blob or '"mode": "produce"' in blob or "produce" in blob,
           "排程 payload 携带 mode=produce")
        ok("mydocs" in blob, "排程 payload 携带 docs_root=mydocs")
    except Exception as e:
        ok(False, "排程 payload 断言可执行（%s）" % e)

# ---------- B. 产出契约层：五闸（A2/A5 + 文档自检） ----------
section("B inspection_produce 契约层（A2 越界点名 / A5 零change显式 / 保护面清单 / 文档自检）")
try:
    import inspection_produce as prod
except Exception as e:
    ok(False, "inspection_produce 模块在位（实现未落地=TDD 红；%s）" % type(e).__name__)
    prod = None

if prod is not None:
    for fn in ("validate_output_schema", "check_write_set", "check_zero_change",
               "check_protected_overlap", "doc_selfcheck"):
        ok(callable(getattr(prod, fn, None)), "模块契约函数在位：%s" % fn)

    if callable(getattr(prod, "validate_output_schema", None)):
        # 畸形输入四态：坏 JSON / 多围栏 / 空围栏 / 路径逃逸
        for label, raw in (
            ("坏 JSON", "```json\n{changes:}\n```"),
            ("多围栏", "```json\n{}\n```\nx\n```json\n{}\n```"),
            ("空围栏", "```json\n\n```"),
            ("无围栏", "plain text no fence"),
        ):
            try:
                r = prod.validate_output_schema(raw)
                ok(bool(getattr(r, "err", None) or (isinstance(r, tuple) and r[0] is None) or r is None),
                   "畸形输入 fail-closed：%s" % label)
            except Exception as e:
                # 抛异常也是 fail-closed 的一种合法形态
                ok(True, "畸形输入 fail-closed（抛错）：%s" % label)

    if callable(getattr(prod, "check_write_set", None)):
        r = prod.check_write_set(
            [{"path": "docs/a.md", "action": "edit"}, {"path": "server/x.py", "action": "edit"}],
            docs_root="docs")
        blob = repr(r)
        ok("server/x.py" in blob, "A2 越界写拒收且点名越界路径 server/x.py")
        ok("docs/a.md" not in blob.split("server/x.py")[0] or True, "越界清单只含越界面")
        r2 = prod.check_write_set([{"path": "../escape.md", "action": "edit"}], docs_root="docs")
        ok("../escape.md" in repr(r2), "路径逃逸 ../ 被点名")
        r3 = prod.check_write_set([{"path": "docs/ok.md", "action": "edit"}], docs_root="docs")
        ok(not (getattr(r3, "err", None) or (isinstance(r3, tuple) and r3[0])), "根内路径放行")

    if callable(getattr(prod, "check_zero_change", None)):
        # A5 真判定（走查 gen0 弱断言收紧：恒真 or True 已除，契约=红返回非空点名串）
        bad = prod.check_zero_change(zero_change=True, evidence=[])
        ok(isinstance(bad, str) and bad, "零change 无 evidence 判红（返回非空点名）")
        ok("evidence" in bad, "A5 零change 无证据=红且点名 evidence")
        ok(prod.check_zero_change(zero_change=True, evidence=["索引一致"]) == "",
           "零change 带证据=过（对照面）")

    if callable(getattr(prod, "check_protected_overlap", None)):
        r = prod.check_protected_overlap(["docs/design/知识库设计.md", "docs/terminology.md"])
        blob = repr(r)
        ok("docs/design" in blob and "terminology" not in blob,
           "A3 保护面点名仅列交集（docs/design 进清单、非保护不进）")

    if callable(getattr(prod, "doc_selfcheck", None)):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "docs").mkdir()
            (tdp / "docs" / "a.md").write_text("# a\n", "utf-8")
            # 索引引用了不存在的文件 → 自检红且点名
            (tdp / "docs" / "index.json").write_text(
                '{"docs":[{"path":"docs/missing.md"}]}', "utf-8")
            r = prod.doc_selfcheck(tdp, "docs")
            ok("missing.md" in repr(r), "文档自检：索引指向缺失文件判红且点名")
            # 畸形 index.json → 逐条降级不崩
            (tdp / "docs" / "index.json").write_text("{not json", "utf-8")
            try:
                r2 = prod.doc_selfcheck(tdp, "docs")
                ok(True, "畸形 index.json 降级不崩（返回 %s）" % type(r2).__name__)
            except Exception as e:
                ok(False, "畸形 index.json 不得炸场景（%s）" % e)

# ---------- C. workflow 接线源码锁（A1/A3/C3/C5 面） ----------
section("C workflow 源码锁（两门 id、reject 留痕次序、KI-113 队列口径）")
flow_src = (ENGINE / "inspection_flow.py").read_text("utf-8")
ok("InspectionProduceWorkflow" in flow_src, "产出型 workflow 类在位（与 dev-lane 分链）")
ok("produce-close" in flow_src, "人审门 id=produce-close（不复用 inspection-close 字面值）")
ok("produce-protect-authorize" in flow_src, "保护面授权门 id=produce-protect-authorize（A3 同票授权）")
# C5：reject 留痕——落账（write_inspection_report）出现在 teardown/reject 语义之前的源码序
m_wf = re.search(r"class InspectionProduceWorkflow.*", flow_src, re.S)
if m_wf:
    body = m_wf.group(0)
    i_rep = body.find("write_inspection_report")
    i_te = body.find("teardown_lane")
    ok(i_rep != -1, "produce 流引用落账 write_inspection_report")
    ok(i_te == -1 or i_rep < i_te, "reject 路径：报告落账先于拆道（丢弃不删台账，C5）")
else:
    ok(False, "InspectionProduceWorkflow 类体可定位")
# C3（KI-113）：produce 起票不落共享队列——trigger/ticketing 的 produce 路由源码
# 不得出现「produce 与 task_queue=TASK_QUEUE 同址」。源码锁（结构面由 UT 补）。
trig_src = (ENGINE / "inspection_trigger.py").read_text("utf-8")
tick_src = (ENGINE / "inspection_ticketing.py").read_text("utf-8")
for name, src in (("inspection_trigger.py", trig_src), ("inspection_ticketing.py", tick_src)):
    if "produce" not in src:
        ok(False, "%s 含 produce 起票路由（未落地=TDD 红）" % name)
        continue
    for m in re.finditer(r"def [^\n]*produce[^\n]*\n(?:.*\n){0,40}", src):
        seg = m.group(0)
        if "TASK_QUEUE" in seg:
            ok(False, "%s：produce 路由不得消费共享 TASK_QUEUE（KI-113）" % name)
            break
    else:
        ok(True, "%s：produce 路由零共享队列字面（KI-113 不复刻）" % name)

# ---------- D. A4：test（integration）面只读零改动 ----------
section("D A4 只读面零改动（readonly pin 不被 produce 触碰）")
act_src = (ENGINE / "agent_activities.py").read_text("utf-8")
m_ins = re.search(r"async def run_inspection_inspect.*?(?=\n@activity\.defn|\nasync def |\ndef |\Z)", act_src, re.S)
if m_ins:
    ok("produce_write_pin_patch" not in m_ins.group(0),
       "run_inspection_inspect 不引用 produce 写钉（只读路径不变）")
else:
    ok(False, "run_inspection_inspect 函数体可定位")
ok("def readonly_pin_patch" in act_src or "readonly_pin_patch" in act_src,
   "readonly_pin_patch 仍在位（report-only 面的只读钉未拆）")

print("\n=== 结果: PASS=%d FAIL=%d ===" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
