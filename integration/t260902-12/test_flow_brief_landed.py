#!/usr/bin/env python3
"""t260902-12 集成测试 B：dev_lane.py FLOW_BRIEF design_integration_tests 条款落地检测。

不 import 模块（避开 temporalio 等运行时依赖）：py 语法用 compile()，FLOW_BRIEF 结构用
ast 抽取 Assign 后 literal_eval。断言绑定公开契约（FLOW_BRIEF: Dict[str, str] 的内容），
绑定浅：先剥空白再比对，任何源码折行变化不影响判定。失败 => 非零退出。
运行：python3 integration/t260902-12/test_flow_brief_landed.py（cwd 不限，路径按脚本定位）。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "server" / "engine" / "dev_lane.py"

failures = []


def check(name, ok):
    print(f"[t260902-12][brief] CHECK {name}: {'PASS' if ok else 'FAIL'}")
    if not ok:
        failures.append(name)


strip = lambda s: "".join(str(s).split())  # noqa: E731

source = SRC.read_text(encoding="utf-8")

# 语法契约：整文件可编译
try:
    compile(source, str(SRC), "exec")
    check("dev_lane.py 语法可编译", True)
except SyntaxError as e:
    print(f"[t260902-12][brief] SETUP FAIL: 语法错误：{e}")
    sys.exit(1)

# 结构契约：FLOW_BRIEF 仍是 Dict[str, str]，且全部条目健在
tree = ast.parse(source)
brief = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "FLOW_BRIEF" for t in node.targets
    ):
        brief = ast.literal_eval(node.value)
        break
check("FLOW_BRIEF 可静态求值为 dict", isinstance(brief, dict))
expected_keys = {
    "create_plan", "review_plan", "implement",
    "design_integration_tests", "arbitrate", "acceptance_walkthrough"}
check("FLOW_BRIEF 六个条目齐全", brief is not None and expected_keys <= set(brief))
check("FLOW_BRIEF 值均为字符串", brief is not None and all(isinstance(v, str) for v in brief.values()))

d = strip(brief.get("design_integration_tests", "")) if brief else ""

# ⑤ 条款：用例设计依据三依据穷尽（现行草案术语）+ 裁定一（第三项=对外契约与行为规格）
check("④ 三依据穷尽条款存在", "④用例设计依据三依据穷尽" in d)
check("④ 第一依据=原始 user_request+验收口径", "工单原始user_request与用户验收口径" in d)
check("④ 第二依据=KI 未闭合项", "项目已知问题清单（KI）中本票改动触及的未闭合项" in d)
check("④ 第三依据=对外契约与行为规格（裁定一，非「方案」）",
      "→组件对外契约与行为规格（锚定承诺而非实现，实现细节不作依据）" in d and "命中项、方案" not in d)
check("④ 防重复核对+路径见项目测试声明",
      "设计用例前核对项目声明的全局用例清单防intent级重复" in d and "见项目测试声明" in d)
check("④ 用 → 连接（无嵌套第二套编号）", "→" in d and "①工单原始" not in d and "②项目声明" not in d)

# lead 灰盒校正（裁定落文：去「黑盒」字样，保留对抗面本意）
check("lead 灰盒视角（对抗面而非复核面）", "（灰盒视角：developer的对抗面而非复核面，不逐行审代码细节）" in d)
check("lead 无「黑盒」残留", "黑盒" not in d)

# 裁决注释行落在源码里
check("裁决注释行存在", "用例设计依据第三项=组件对外契约与行为规格" in source and "# t260902-12" in source)

# 既有条目不动（裁定二：既有段归票④，本票不得顺手改）
arb = strip(brief.get("arbitrate", "")) if brief else ""
check("既有 arbitrate 三态契约不动", "verdict=" in arb and "integration/里的" in arb)
cp = strip(brief.get("create_plan", "")) if brief else ""
check("既有 create_plan 条目不动", "本步只出方案" in cp)

print(f"[t260902-12][brief] RESULT: {'PASS' if not failures else 'FAIL'}（失败 {len(failures)} 项）")
sys.exit(0 if not failures else 1)
