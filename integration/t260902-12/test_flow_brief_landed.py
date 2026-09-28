#!/usr/bin/env python3
"""t260902-12 集成测试 B：dev_lane.py FLOW_BRIEF design_integration_tests 条款落地检测。

不 import 模块（避开 temporalio 等运行时依赖）：py 语法用 compile()，FLOW_BRIEF 结构用
ast 抽取 Assign 后读值——literal_eval 优先（纯字面量），含单点渲染调用（t260921-04
声明=执法同源形态）时回退字面部分静态求值，短语断言语义不变。断言绑定公开契约
（FLOW_BRIEF: Dict[str, str] 的内容），绑定浅：先剥空白再比对，任何源码折行变化不
影响判定。失败 => 非零退出。
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

# 结构契约：FLOW_BRIEF 仍是 Dict[str, str]，且全部条目健在。
# t260921-04 修向（守卫改读法不变契约，t260917-01 修向④先例）：FLOW_BRIEF 值允许
# 「字面量 + 单点渲染调用」形态（integration_discipline.prompt_clause()——宿主令
# 260921 的声明=执法单点真源，方案定稿形态）。读法：literal_eval 优先（纯字面量
# 老形态逐值读回）；非纯字面量时回退「字面部分静态求值」（Constant/BinOp-Add 保留
# 拼接序，渲染调用跳过）——短语断言语义不变（字面部分跨行拼接不裂），渲染产物
# 的内容契约由 integration_discipline 自身 UT 与 t260921-04-discipline-clause-contract
# 场景守，本守卫不重复。
tree = ast.parse(source)
brief = None
computed = False


def _literal_part(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_part(node.left), _literal_part(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Call):
        return ""  # 单点渲染调用：字面部分之外的渲染产物，本守卫不读
    # 260928 修（本守卫在 main 上长红的真因）：若干条目尾部除渲染调用外还拼了**模块级
    # 常量**（形如 `+ ROLE_REPORT_ENGLISH_CLAUSE`）。旧读法对 Name 返回 None ⇒ 整条
    # 表达式判「读不出」⇒ 该条目的字面部分变空串 ⇒ 条款断言全红（票面英文化同批引入）。
    # 意图不变（读回字面部分、跳过非字面拼接件）→ Name/Attribute 与 Call 同口径按空串
    # 跳过，字面部分照旧逐字读回。
    if isinstance(node, (ast.Name, ast.Attribute)):
        return ""
    return None


for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "FLOW_BRIEF" for t in node.targets
    ):
        try:
            brief = ast.literal_eval(node.value)
        except ValueError:
            print("[t260921-04][brief] NOTE: FLOW_BRIEF 含单点渲染调用"
                  "（声明=执法同源，t260921-04 形态）——按字面部分静态求值读回，"
                  "短语断言语义不变（守卫改读法不变契约，t260917-01 先例）")
            if isinstance(node.value, ast.Dict):
                brief = {}
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        part = _literal_part(v)
                        brief[k.value] = part if part is not None else ""
            break
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

# 既有条目不动（裁定二：既有段归票④，本票不得顺手改）。
# t260917-01 修向④（工单派发规格授权）：arbitrate 条目的 tests-fault 迭代邀请由
# 「直接迭代 integration/ 里的测试集」收窄为「红项落在测试面内才就地迭代；共享资产/
# 受保护真源等不允许面如实出 verdict 点名转人工」——原逐字锚「integration/里的」随
# 授权变更退役，守卫改锁不变契约：三态 verdict= 标记仍在 + 收窄语义「不允许面」仍在
# （若有人回退收窄或删三态契约，此处照红=防悄悄回退语义保留）。
arb = strip(brief.get("arbitrate", "")) if brief else ""
check("arbitrate 三态契约在 + 迭代面收窄语义在（t260917-01 修向④授权收窄）",
      "verdict=" in arb and "不允许面" in arb)
cp = strip(brief.get("create_plan", "")) if brief else ""
check("既有 create_plan 条目不动", "本步只出方案" in cp)

print(f"[t260902-12][brief] RESULT: {'PASS' if not failures else 'FAIL'}（失败 {len(failures)} 项）")
sys.exit(0 if not failures else 1)
