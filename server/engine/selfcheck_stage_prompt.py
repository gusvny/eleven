#!/usr/bin/env python3
"""build_stage_prompt 自测（t260828-04 回归）：previous_context 注入守卫 + gen 展示基制。

**零 Temporal server / 零模型 / 零 IO**（纯函数断言；import dev_lane 只为纯函数 _prompt_next_no）。

背景（t260828-04 实锤）：build_stage_prompt 曾用 `gen > 1` 当注入守卫，而 dev_lane 的
gen 是 0 基（_enter 前取值）——第一次打回重进 gen=1，守卫为假，评审意见/打回原因
静默不进 prompt，agent 收到「无返工项」做幂等确认。修复口径：
  - 注入守卫只看 previous_context 非空（调用方只在本段重跑时才传非空）；
  - gen 仅作「第 N 次进本段」展示值，基制由调用方定（base 传 1 基 / dev_lane 传 gen+1）；
  - dev_lane 的 FLOW_BRIEF 补述尾号改为动态接排（注入后通用指令尾号到 9，硬编码 9 撞号）。

覆盖：
  A. 0 基引擎第一次打回（gen=1 + 非空 previous_context）→ prompt 含「上次运行上下文」节；
  B. 首跑（空 previous_context）→ 不注入（首跑行为不变）；
  C. 0 基首跑带上下文（冲突消解第 1 轮场景，gen=0 + 非空）→ 注入；
  D. 展示基制：base 传法 gen=2 显示「第 2 次」；dev_lane 传法 gen+1 不再出现「第 0 次」；
  E. 序号自适应：注入后工作目录/交付契约/落盘口径从 7/8/9 起；
  F. dev_lane FLOW_BRIEF 接尾号动态化（源码文本断言 + _prompt_next_no 纯函数断言）。

退出码 0=全绿；非 0=有红灯（stderr 打明细）。
"""

from __future__ import annotations

import sys
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

from shared import Stage, build_stage_prompt  # noqa: E402

from selfcheck_common import Selfcheck  # noqa: E402  t261001-04：ok/section 收敛到唯一定义，输出格式逐字不变

_rep = Selfcheck(track_failures=True)
ok = _rep.ok
section = _rep.section


ST = Stage(id="implement", name="实现", role="developer",
           acceptance=("改动落在写集内",))
META = {"title": "自测工单", "workspace": None}      # workspace 空 → 走 /tmp 隔离目录兜底
HANDOFFS = [{"stage": "review_plan", "summary": "方案审读通过"}]
RFILE = "/tmp/sandbar-selfcheck/stage_implement_gen9.json"
REWORK_NOTE = "【方案审读打回（第 1 轮）】review comments：\n1. 输入必须检查"


def build(gen: int, prev_ctx: str = "") -> str:
    return build_stage_prompt("t-selfcheck", META, ST, HANDOFFS, RFILE, gen, prev_ctx)


section("A 0 基第一次打回（gen=1 + 非空 previous_context）——t260828-04 回归主案")
p = build(1, REWORK_NOTE)
ok("6. 上次运行上下文" in p, "注入「上次运行上下文」节（gen=1 不再被守卫吞掉）")
ok("【方案审读打回（第 1 轮）】" in p, "打回原因原文进 prompt")
ok("review comments：\n   1. 输入必须检查" in p, "多行意见逐行缩进进 prompt")

section("B 首跑（空 previous_context）——首跑行为不变")
p0 = build(0)
p1 = build(1)
ok("上次运行上下文" not in p0 and "上次运行上下文" not in p1,
   "空 prev 不注入（守卫只看非空，不看 gen）")
ok("6. 工作目录：" in p0, "不注入时工作目录从 6 起")

section("C 0 基首跑带上下文（冲突消解第 1 轮场景，gen=0 + 非空）")
p = build(0, "【冲突消解轮 gen1/上限3】解掉冲突标记")
ok("6. 上次运行上下文" in p, "非空 prev 恒注入（0 基 gen=0 也不吞）")

section("D gen 展示基制（base 1 基 / dev_lane 传 gen+1）")
ok("第 2 次进本段" in build(2), "base 传法：1 基 gen=2（第一次打回重进）→ 第 2 次")
ok("第 2 次进本段" in build(1 + 1), "dev_lane 传法：0 基 gen=1 打回重进传 gen+1 → 第 2 次")
ok("第 1 次进本段" in build(0 + 1), "dev_lane 传法：0 基 gen=0 首跑传 gen+1 → 第 1 次")
src = (POC / "dev_lane.py").read_text("utf-8")
ok("previous_context)" in src and "gen + 1," in src,
   "dev_lane 源码给 build_stage_prompt 传 gen+1（0 基 gen 不再直传展示位）")

section("E 序号自适应（注入后后续条目整体后移）")
p = build(1, REWORK_NOTE)
ok("7. 工作目录：" in p and "8. 交付契约" in p and "9. 落盘口径" in p,
   "注入后工作目录/交付契约/落盘口径从 7/8/9 起")

section("F dev_lane FLOW_BRIEF 接尾号动态化")
from dev_lane import _prompt_next_no  # noqa: E402
ok(_prompt_next_no(build(1, REWORK_NOTE)) == 10, "注入后（尾号 9）补述接 10")
ok(_prompt_next_no(build(0)) == 9, "未注入（尾号 8）补述接 9（与原硬编码一致）")
ok(_prompt_next_no("无编号文本") == 1, "无编号 prompt 兜底 1")
ok(_prompt_next_no("6. 工作目录\n   9. 缩进行不算顶层编号") == 7,
   "缩进行（注入的意见原文）不参与编号统计")
src = (POC / "dev_lane.py").read_text("utf-8")
ok('"\\n9. 本步契约' not in src and '_prompt_next_no(prompt)' in src,
   "dev_lane 源码不再硬编码 9 号，补述尾号走 _prompt_next_no")

section("G 交付契约三层口径（summary / report / evidence 各喂各的读者）")
p = build(0)
ok('"report":"人读进展报告"' in p, "契约含 report 字段")
ok("≤40 字" in p, "summary 台面一句话口径在契约里")
ok("做了什么 / 怎么验证的" in p, "report 固定小节在契约里")
ok("evidence：机器口径原始证据" in p, "evidence 机器口径在契约里")

section("H 前段交接渲染 report（下一棒 agent 是报告第一读者）")


def build_with(handoffs) -> str:
    return build_stage_prompt("t-selfcheck", META, ST, handoffs, RFILE, 0, "")


ph = build_with([{"stage": "implement", "summary": "一句话",
                  "report": "## 做了什么\n改了 A。"}])
ok("[implement] ## 做了什么" in ph, "交接段渲染前段 report 正文")
ok("[implement] 一句话" not in ph, "有 report 时不再显示 summary（不吃压缩长句）")
ps = build_with([{"stage": "implement", "summary": "旧格式一句话"}])
ok("[implement] 旧格式一句话" in ps, "无 report 回退 summary（旧交接条目兼容）")
ok(build_with([{"stage": "s", "report": "x" * 2000}]).count("x" * 100) >= 11,
   "report 截断护栏放宽到 1200（2000 字入交接被截）")

section("I _read_result 归一 report（旧结果文件兼容）")
import json as _json  # noqa: E402
import tempfile as _tf  # noqa: E402
from pathlib import Path as _P  # noqa: E402
from agent_activities import _read_result  # noqa: E402
_d = _P(_tf.mkdtemp(prefix="sandbar-selfcheck-sr-"))
_new = _d / "new.json"
_new.write_text(_json.dumps({"status": "ok", "summary": "s", "report": "## 做了什么\nx",
                             "evidence": "e"}), "utf-8")
ok(_read_result(_new).report == "## 做了什么\nx", "新结果文件 report 读入")
_old = _d / "old.json"
_old.write_text(_json.dumps({"status": "ok", "summary": "s", "evidence": "e"}), "utf-8")
r = _read_result(_old)
ok(r.report == "" and r.summary == "s", "旧结果文件无 report → report 空串（回落不炸）")

print("\n%d passed, %d failed" % (_rep.passes, _rep.fails))
if _rep.failures:
    print("_rep.failures:", file=sys.stderr)
    for f in _rep.failures:
        print("  - %s" % f, file=sys.stderr)
sys.exit(0 if _rep.fails == 0 else 1)
