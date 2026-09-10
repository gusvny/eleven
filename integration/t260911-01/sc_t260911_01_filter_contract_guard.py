#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260911-01 场景②：过程物过滤口径单一真源契约护栏（灰盒 L2，读源断言）。

intent（守护的契约）：workbench diff 面的过程物过滤表（changes.ts
PROCESS_ARTIFACT_DIRS）与引擎侧协调目录排除口径（agent_activities.SETTLE_PATHSPEC、
verify_lane.RUNTIME_PREFIXES）跨语言无法 import 真源——本场景锁反向包含
「workbench 表 ⊇ 引擎两表现有排除」：workbench 白名单将来怎么扩都行，**不得丢掉
.dsh/.sandbar/.suyou 已有覆盖**（丢了=引擎自管过程物回流人审 diff 面，2b 复发形态；naming-compat：断言面提及 legacy 泳道目录名，非消费面）。

挂账面（可判定，不是注释）：engine 侧 SETTLE_PATHSPEC 现缺 out/__pycache__/
node_modules/.venv 覆盖（out/pycache 误代落盘实案根因，dengzhufpv 260910）——根修
属引擎写集、本票挂账另票。本场景每次运行把「workbench 有而引擎表没有」的差集打成
LEDGER 行（场景输出可见、转正时可判定：根修落地后 LEDGER 差集收空），不判红——
红绿只由反向包含、派发白名单与 handler 透传三条闸决定。

与场景①（sc_t260911_01_multirepo_diff_faces，行为面）intent 不同层：彼锁用户可见
清单形态，本条锁三处口径表的漂移。纯 stdlib 读源，零环境依赖（无 ENV_FAIL 腿）；
被读文件缺失=产品红（真源文件被移走本护栏就该红）。
"""
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHANGES_TS = REPO / "server" / "plugins" / "workbench" / "src" / "host" / "changes.ts"
AGENT_ACT = REPO / "server" / "engine" / "agent_activities.py"
VERIFY_LANE = REPO / "server" / "tools" / "verify_lane.py"

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def norm(name: str) -> str:
    """口径名归一：':!.dsh' / ':!out/' / ':!**/__pycache__/' / '.sandbar/' → '.dsh'/'out'/'__pycache__'/'.sandbar'。"""
    n = name.strip()
    if n.startswith(":!"):
        n = n[2:]
    if n.startswith("./"):
        n = n[2:]
    if n.startswith("**/"):
        n = n[3:]
    return n.rstrip("/")


def read_table_changes_ts() -> list:
    """从 changes.ts 抠 PROCESS_ARTIFACT_DIRS 字符串字面量表（形状漂移=红，点名现状）。"""
    m = re.search(r"const PROCESS_ARTIFACT_DIRS\s*=\s*\[([^\]]*)\]", CHANGES_TS.read_text(encoding="utf-8"))
    if not m:
        return []
    return [norm(x) for x in re.findall(r"'([^']+)'|\"([^\"]+)\"", m.group(1)) for x in [x[0] or x[1]] if norm(x[0] or x[1])]


def read_py_literal(path: Path, var: str):
    """ast 抠 python 模块级字面量赋值（列表/元组），坏形状返回 None。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == var for t in node.targets):
                return ast.literal_eval(node.value)
    return None


def main() -> int:
    for f in (CHANGES_TS, AGENT_ACT, VERIFY_LANE):
        check("真源文件在场 %s" % f.relative_to(REPO), f.is_file())

    wb = read_table_changes_ts()
    check("workbench 过滤表可解析且非空（PROCESS_ARTIFACT_DIRS）", bool(wb), "实得 %r" % wb)

    settle = read_py_literal(AGENT_ACT, "SETTLE_PATHSPEC")
    check("SETTLE_PATHSPEC 可解析（ast 字面量）", isinstance(settle, list), "实得 %r" % settle)
    runtime = read_py_literal(VERIFY_LANE, "RUNTIME_PREFIXES")
    check("RUNTIME_PREFIXES 可解析（ast 字面量）", isinstance(runtime, tuple), "实得 %r" % (runtime,))

    engine = set()
    if isinstance(settle, list):
        # "."=「全量」pathspec 令牌（非排除名），跳过
        engine |= {norm(s) for s in settle if norm(s) and norm(s) != "."}
    if isinstance(runtime, tuple):
        engine |= {norm(s) for s in runtime if norm(s)}
    wb_set = set(wb)

    # 闸1（核心，反向包含）：引擎两表现有排除 ⊆ workbench 表——丢覆盖即红（2b 复发形态）。
    missing = sorted(engine - wb_set)
    check("闸1 workbench 表 ⊇ 引擎两表现有排除（.dsh/.sandbar/.suyou 不得丢）",  # naming-compat 断言面提及 legacy 目录名，非消费面
          bool(wb) and not missing, "缺 %r" % missing)

    # 闸2（派发规格 ②白名单）：本票点名的引擎自管过程物目录必须在 workbench 表。
    need = {".sandbar", ".dsh", "out", "__pycache__", "node_modules"}
    check("闸2 派发白名单五目录 ⊆ workbench 表", need <= wb_set, "缺 %r" % sorted(need - wb_set))

    # 闸3（透传一跳护栏，t260908-01 同族断点防线）：host diff handler 从 ticket show
    # 结果显式挑字段构造 TicketForDiff，是「票面明细→diff 计算」唯一收口——漏挑
    # repo_worktrees = 场景①（直驱契约）全绿而 UI diff 面全瞎（testing-guide 260910
    # 「断点：host 未透传字段→场景全绿、界面无按钮」骨架）。读源锚 computeTicketDiff
    # 调用参数含透传（调用形状漂移=红，与上方过滤表「形状漂移=红」同哲学）。
    node_ts = REPO / "server" / "plugins" / "workbench" / "node.ts"
    src_node = node_ts.read_text(encoding="utf-8") if node_ts.is_file() else ""
    m_call = re.search(r"computeTicketDiff\([^)]*\)", src_node, re.S)
    check("闸3 diff handler 透传 repo_worktrees 进 computeTicketDiff（t260908-01 断点防线）",
          bool(m_call) and "repo_worktrees" in m_call.group(0),
          "node.ts 的 computeTicketDiff 调用未透传 repo_worktrees（实得 %s）"
          % (m_call.group(0)[:100].replace("\n", " ") if m_call else "调用不在文"))

    # 挂账面（可判定、不判红）：workbench 有而引擎表没有的差集逐行打 LEDGER——
    # 根修（engine SETTLE_PATHSPEC 收口 out/pycache 族）落地后本差集应收空，转正即可判定。
    uncovered = sorted(wb_set - engine)
    if uncovered:
        print("LEDGER: 以下目录 workbench diff 面已过滤、引擎代落盘侧（SETTLE_PATHSPEC/RUNTIME_PREFIXES）尚未排除——"
              "根修属引擎写集，本票挂账另票（dengzhufpv 260910 out/pycache 误代落盘同族）：")
        for u in uncovered:
            print("LEDGER:   - %s" % u)
    else:
        print("LEDGER: 差集为空——引擎侧根修已落地（挂账可销）。")

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
