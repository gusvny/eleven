#!/usr/bin/env python3
"""t260903-04 集成测试 t01：并行期快照 meta.parallel_stages 生命周期契约（KI-024① 引擎半）。

用户场景（KI-024 实案 t260903-01）：并行分叉期 implement∥design_integration_tests 与
arbitrate∥acceptance_walkthrough 各边同写 meta["stage"]，后写者赢——工单台详情只能
看到一边，值守把正在办案的票误读成停滞。收口后引擎在并行期往 meta 写 parallel_stages
列表（工单钦定契约字段），工单台据此双显；单 stage 字段保留向后兼容。

断言（锚公开契约与用户可感知行为，不锚行号/私有实现）：
  A. 结构守卫（文本级，恒跑）：两处并行分叉段（parallel_impl_design / arb_acc_parallel）
     各自写入 parallel_stages；汇合清空点在案；meta["stage"] 单字段写入仍在（向后兼容）。
  B. 行为契约（模块级纯函数，stub 导入恒跑）：词表内 id 写入、词表外/非字符串条目清洗、
     重复去重、空列表删键不残留、幂等稳定。

跑法：python3 -B integration/t260903-04/sc_t01_parallel_stages_meta.py
（纯 stdlib + temporalio 导入桩 _stub_temporalio，零 Temporal/网络依赖；恒跑无环境腿。）
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "dsh" / "temporal-poc"
SRC = POC / "dev_lane.py"

sys.path.insert(0, str(HERE))
import _stub_temporalio  # noqa: E402  # 必须先于 dev_lane 导入
_stub_temporalio.install()

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


def section(t):
    print("\n== %s ==" % t)


# ---------------------------------------------------------------- A. 结构守卫
section("A 并行分叉段结构守卫（文本级）")
text = SRC.read_text(encoding="utf-8")

FORKS = ["parallel_impl_design", "arb_acc_parallel"]


def _phase_block(phase):
    """取 `if phase == "<phase>":` 起到下一个同级 `if phase ==` 的源码段。"""
    m = re.search(r'if phase == "%s":' % phase, text)
    if not m:
        return None
    rest = text[m.start():]
    nxt = re.search(r'\n            if phase == "', rest[1:])
    return rest[:nxt.start() + 1] if nxt else rest


for ph in FORKS:
    block = _phase_block(ph)
    ok(block is not None, "分叉段在案：%s" % ph)
    if block is not None:
        ok("parallel_stages" in block,
           "%s 段写入 parallel_stages（分叉期列表在案）" % ph)

ok(text.count("parallel_stages") >= 5,
   "parallel_stages 出现 ≥5 处（定义+两分叉+清空点，汇合清空在案）")
ok('self.meta["stage"] = step_id' in text,
   'meta["stage"] 单字段写入保留（向后兼容锚：旧 workbench/旧票零回归）')

# ------------------------------------------------------- B. 行为契约（纯函数）
section("B parallel_stages 清洗与生命周期行为（模块级纯函数）")
sys.path.insert(0, str(POC))
import dev_lane  # noqa: E402

# 方案承诺：模块级纯函数 set_parallel_stages(meta, stages)。探测式取用——
# 名字精确命中优先；否则取模块级名含 parallel_stages 的唯一 callable（实现换名不误伤，
# 缺失或多候选才 FAIL，FAIL 信息点名方案契约）。
fn = getattr(dev_lane, "set_parallel_stages", None)
if fn is None:
    cands = [n for n, v in vars(dev_lane).items()
             if "parallel_stages" in n.lower() and callable(v)]
    fn = getattr(dev_lane, cands[0]) if len(cands) == 1 else None
ok(fn is not None,
   "模块级 parallel_stages 清洗函数在案（create_plan 方案承诺的公开缝；缺失=实现欠账）")

if fn is not None:
    vocab = {s.id for s in dev_lane.DevLaneWorkflow.STAGES}
    ok("implement" in vocab and "arbitrate" in vocab and "acceptance_walkthrough" in vocab,
       "STAGES 词表含两组并行位 id（implement/design_integration_tests/arbitrate/acceptance_walkthrough）"
       if all(x in vocab for x in ("implement", "design_integration_tests",
                                   "arbitrate", "acceptance_walkthrough"))
       else "STAGES 词表缺并行位 id：actual=%s" % sorted(vocab))

    meta = {}
    fn(meta, ["implement", "design_integration_tests"])
    ok(meta.get("parallel_stages") == ["implement", "design_integration_tests"],
       "B1 词表内双 id 原序写入")

    meta = {}
    fn(meta, ["implement", "bogus_stage", "design_integration_tests"])
    ok(meta.get("parallel_stages") == ["implement", "design_integration_tests"],
       "B2 词表外 id 丢弃（不清洗=模板外 id 泄漏进快照）")

    meta = {"parallel_stages": ["arbitrate"]}
    fn(meta, ["nope1", "nope2"])
    ok("parallel_stages" not in meta,
       "B3 全词表外清洗为空 → 键删除（不残留陈旧列表）")

    meta = {}
    fn(meta, ["arbitrate", "arbitrate", "acceptance_walkthrough"])
    ok(meta.get("parallel_stages") == ["arbitrate", "acceptance_walkthrough"],
       "B4 重复 id 去重")

    meta = {}
    fn(meta, [None, 123, "arbitrate"])
    ok(meta.get("parallel_stages") == ["arbitrate"],
       "B5 非字符串条目跳过（外部输入不可信纪律）")

    meta = {"parallel_stages": ["implement", "design_integration_tests"]}
    fn(meta, [])
    ok("parallel_stages" not in meta,
       "B6 空列表显式清键（汇合后不残留旧列表——残留则 UI 永远双显假并行）")

    meta = {}
    fn(meta, ["arbitrate", "acceptance_walkthrough"])
    once = dict(meta)
    fn(meta, ["arbitrate", "acceptance_walkthrough"])
    ok(meta == once, "B7 幂等：同输入重写结果稳定")

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
