#!/usr/bin/env python3
"""角色报告英文化·双载体一致面（t260925-21，registry: t260925-21-report-language-face）。

意图（灰盒 L2/L1 级静态契约，ro 池离线秒级，零 docker 零网络）：
宿主令 260925＝developer/integration 角色的 stage report 内容一律英文，同时
260904「对用户回复用平实中文」不变。工单可感知交付物是**文案纪律面**（agent 段
行为由派活文案与 charter 注入引导），本场景守两条工程承诺：

- 「不留两个口径不一致的源」：规则文案单源（shared.py 常量）+ 三个消费面
  （FLOW_BRIEF 六段、build_stage_prompt 注入、session_charter.md 条目）——
  任何一处不消费同源文案、或 charter 侧规则缺席/口径漂移即红；
- 边界不回潮：260904 聊天中文条目必须原样在场且位于英文条目**之前**（两条并存
  可见）——本票若顺手删弱了聊天中文规则=产品红。

intent 分工（防 intent 级重复）：developer 的 L1 单元测试（server/engine/tests/
test_t260925_21_*，随本票交付）守「注入行为正确性」（含 unknown/empty role 边界
与 charter 顺序）；本场景守 **跨载体一致性**（常量单源被三个消费面同源消费 +
FLOW_BRIEF key 全集漂移守卫 + 260904 条目不回潮），锚语义标记与常量消费关系，
不锚 prompt 整句排版。

实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。无 ENV 子用例
（全部为受控资产静态读，资产缺席=产品红非环境红）。
"""
import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
CONST = "ROLE_REPORT_ENGLISH_CLAUSE"
SIX = ("create_plan", "review_plan", "implement",
       "design_integration_tests", "arbitrate", "acceptance_walkthrough")

PASS = 0
FAIL = 0


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def section(title: str) -> None:
    print("\n=== %s ===" % title)


def read(p: pathlib.Path) -> str:
    if not p.is_file():
        return ""
    return p.read_text("utf-8")


def main():
    charter_p = REPO / "server/session_charter.md"
    shared_p = REPO / "server/engine/shared.py"
    lane_p = REPO / "server/engine/dev_lane.py"
    charter = read(charter_p)
    shared_src = read(shared_p)
    lane_src = read(lane_p)
    for p, blob in ((charter_p, charter), (shared_p, shared_src), (lane_p, lane_src)):
        ok(bool(blob), "受控资产在场：%s" % p.relative_to(REPO))
    if not (charter and shared_src and lane_src):
        print("\n=== 结果: PASS=%d FAIL=%d ===" % (PASS, FAIL))
        sys.exit(EXIT_FAIL)

    # ---- A. charter 载体：两条规则并存、聊天中文不回潮 ----
    section("A. charter 双规则并存（260904 聊天中文 × 260925 报告英文）")
    # 261004 宿主令把 260904 条目口径从「一律平实中文」改为「跟随用户的语言」
    # （英语按 STE 8 条、中文按受控中文 8 条）。宿主令是真源，判据随口径移动：
    # 本断言守的是「260904 聊天条目在场」，新旧两种措辞任一在场即算在场。
    ok("必须说人话" in charter and ("跟随用户的语言" in charter or "平实中文" in charter),
       "A1 260904 聊天规则条目在场（新口径「跟随用户的语言」或旧口径「平实中文」；本票不得删弱）")
    i_904 = charter.find("必须说人话")
    i_925 = charter.find("260925")
    ok(i_925 > i_904 >= 0,
       "A2 260925 报告英文条目在场且位于 260904 条目之后（并存可见）")
    win = charter[i_925:i_925 + 600] if i_925 >= 0 else ""
    ok("英文" in win and ("中文" in win),
       "A3 英文条目自身写清双口径（报告英文 + 聊天仍中文，范围不靠推断）")
    ok(("developer" in win and "integration" in win) or ("developer/integration" in win),
       "A4 英文条目点名适用角色（developer/integration，不含其他角色）")

    # ---- B. 常量单源 + FLOW_BRIEF 六段消费 ----
    section("B. shared.py 常量单源 + dev_lane FLOW_BRIEF 同源消费")
    const_val = None
    try:
        tree = ast.parse(shared_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == CONST for t in node.targets):
                const_val = ast.literal_eval(node.value)
    except SyntaxError:
        pass
    ok(isinstance(const_val, str) and const_val.strip() != "",
       "B1 shared.py 定义 %s（单源文案常量，非空）" % CONST)
    ok(bool(const_val) and "英文" in const_val and "260925" in const_val,
       "B2 常量内容点名 260925 令 + 英文要求（口径可追溯）")

    lane_keys, entry_src = [], {}
    try:
        lane_tree = ast.parse(lane_src)
        for node in ast.walk(lane_tree):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "FLOW_BRIEF" for t in node.targets):
                if isinstance(node.value, ast.Dict):
                    lane_keys = [ast.literal_eval(k) for k in node.value.keys]
                    entry_src = {ast.literal_eval(k): ast.get_source_segment(lane_src, v)
                                 for k, v in zip(node.value.keys, node.value.values)}
    except SyntaxError:
        pass
    ok(sorted(lane_keys) == sorted(SIX),
       "B3 FLOW_BRIEF key 全集恰为六个角色报告段（新增/缺失段即红，防漂移漏盖）")
    missing = [k for k in SIX if CONST not in (entry_src.get(k) or "")]
    ok(not missing, "B4 六段全部消费同一常量（缺=%s；逐段复制=漂移源，也判红）" % missing)

    # ---- C. build_stage_prompt 注入门控 ----
    section("C. build_stage_prompt 注入与角色门控")
    fn_src = ""
    try:
        for node in ast.walk(ast.parse(shared_src)):
            if isinstance(node, ast.FunctionDef) and node.name == "build_stage_prompt":
                fn_src = ast.get_source_segment(shared_src, node) or ""
    except SyntaxError:
        pass
    ok(CONST in fn_src, "C1 build_stage_prompt 消费同一常量（第二消费点同源）")
    roles_m = re.search(r"ROLE_REPORT_ENGLISH_ROLES\s*=\s*\(([^)]*)\)", shared_src)
    roles_lit = roles_m.group(1) if roles_m else ""
    ok(bool(roles_lit) and '"developer"' in roles_lit and '"integration"' in roles_lit,
       "C2 注入按角色门控（门控角色集含 developer/integration；缺失=其他角色报告被误改）")
    ok(CONST in fn_src and "ROLE_REPORT_ENGLISH_ROLES" in fn_src,
       "C3 注入点实际消费门控角色集（门控声明而不消费=摆设）")
    # 门控的**行为面**（developer/integration 段含注入、其他角色零变化、
    # unknown/empty role 边界）归 developer 的 L1 单元测试（intent 分工见头注），
    # 本场景只守门控字面在场（C2）与消费同源（C1）。

    # ---- D. 双载体口径一致（charter 与常量同令同口径） ----
    section("D. 跨载体口径一致（不留两个说法不一的源）")
    ok(i_925 >= 0 and "260925" in (const_val or ""),
       "D1 charter 条目与常量同锚 260925 宿主令（可共同追溯同一令源）")
    ok(bool(const_val) and "中文" in (const_val or ""),
       "D2 常量自身写明与中文规则并存不冲突（与 charter A3 同口径）")

    print("\n=== 结果: PASS=%d FAIL=%d ===" % (PASS, FAIL))
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(EXIT_PASS if FAIL == 0 else EXIT_FAIL)


if __name__ == "__main__":
    main()
