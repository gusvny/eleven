#!/usr/bin/env python3
"""i03_lane_merge_scope.py —— KI-006 改动范围守卫（t260901-26，integration 侧）。

用户故事：拍板只说「收口进 main 改 squash」；泳道内的小步提交、主干合并进泳道、
冲突消解在泳道内以合并提交落账——这些服务冲突消解的回路一个字都不能动（设计
文档 Nongoal 的同一条）。本测试把这条范围边界机械化：全文件扫「--squash」只许
出现在收口路径；泳道内消解回路必须还在用真合并（MERGE_HEAD 语义）。

黑盒手法：ast 解析真源 agent_activities.py，不做文本巧合判断（注释里提到
--squash 不算数，只看字符串常量出现在哪些函数体里）。

断言：
  1. 全文件 "--squash" 字符串常量只出现在收口路径体内：merge()、_squash_merge()
     与 _squash_merge_core()（t261011-24：squash 配方抽成两目的地共享核——main
     收口 + develop 线落——核心就是收口实现本体，不算越界；泳道内消解回路仍禁）；
  2. merge() 壳体内转调 _squash_merge（dev_lane 调用点零改动的承诺）；
  3. settle_conflict_resolution（泳道内冲突消解落盘）体内引用 MERGE_HEAD——
     真合并回路还在；
  4. prepare_conflict_resolution / settle_conflict_resolution /
     merge_check 体内不出现 "--squash"。

直跑：python3 integration/t260901-26/i03_lane_merge_scope.py
末行 SUMMARY pass=<n> fail=<k>；fail>0 exit 1。
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = REPO / "server" / "engine" / "agent_activities.py"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def squash_sites(tree):
    """返回每个 '--squash' 字符串常量所在的函数名列表（模块级出现为 None）。"""
    sites = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Constant(self, node):
            if node.value == "--squash":
                sites.append(self.stack[-1] if self.stack else None)

    V().visit(tree)
    return sites


def body_of(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    return None


def main():
    src = SRC.read_text("utf-8")
    tree = ast.parse(src)

    print("== 1. --squash 只许在收口路径 ==")
    sites = squash_sites(tree)
    ok(len(sites) > 0, "存在 --squash 收口实现（一个都没有 = 本单没落地）")
    bad = [s for s in sites if s not in ("merge", "_squash_merge",
                                         "_squash_merge_core")]
    ok(not bad, "--squash 全部在收口路径体内 merge/_squash_merge/"
                "_squash_merge_core（越界: %s）" % bad)

    print("== 2. merge() 壳转调 _squash_merge ==")
    merge_fn = body_of(tree, "merge")
    ok(merge_fn is not None, "merge() activity 在位")
    if merge_fn is not None:
        called = {n.func.id for n in ast.walk(merge_fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        ok("_squash_merge" in called, "merge() 体内转调 _squash_merge")

    print("== 3. 泳道内冲突消解回路仍是真合并 ==")
    settle = body_of(tree, "settle_conflict_resolution")
    ok(settle is not None, "settle_conflict_resolution 在位")
    if settle is not None:
        names = {n.value for n in ast.walk(settle)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        ok(any("MERGE_HEAD" in v for v in names),
           "settle 体内引用 MERGE_HEAD（真合并落盘语义）")

    print("== 4. 泳道内回路与 merge_check 不沾 --squash ==")
    for fn_name in ("prepare_conflict_resolution",
                    "settle_conflict_resolution", "merge_check"):
        fn = body_of(tree, fn_name)
        ok(fn is not None, "%s 在位" % fn_name)
        if fn is not None:
            consts = {n.value for n in ast.walk(fn)
                      if isinstance(n, ast.Constant) and n.value == "--squash"}
            ok(not consts, "%s 体内无 --squash" % fn_name)

    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
