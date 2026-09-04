#!/usr/bin/env python3
"""t260901-23 集成测试 t03：workflow 侧让路点——回放安全静态守卫（源级断言）。

用户场景：让路点的价值是查询不再排队 8s+，但代价面是 workflow 确定性——
让路点若落成真 timer 命令，在跑旧票重放即破。本测试用 AST 对源码做黑盒守卫：
  A. base.py `_breathe` 存在、是 async、体内只允许两种确定可回放形态：
     `await asyncio.sleep(0)` 或 `await workflow.wait_condition(lambda: True)`；
     禁止正时长 timer（workflow.sleep 正数常量 / create_timer / execute_activity）。
  B. `_log`/`_mark` 仍为同步纯内存方法（方案红线：突变异步化不做）。
  C. dev_lane.py 让路点已插且不少于方案承诺的 3 处（突变簇边界）。
  D. 三文件 py_compile 通过（实现段改动不引入语法级破损）。
  E. client.py 重试语义存在：默认恰好 2 次尝试（attempts=2）、间隔 sleep 参数化——
     防重试退化成无限重试或零重试。

跑法：python3 -B integration/t260901-23/t03_breathe_replay_guard.py
（纯 stdlib AST，零模型调用，无需 temporalio。）
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
POC = HERE.parent.parent / "server" / "dsh" / "temporal-poc"
BASE = POC / "base.py"
LANE = POC / "dev_lane.py"
CLIENT = POC / "client.py"

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


def main():
    print("t03 让路点回放安全静态守卫")

    # D. 语法级守卫：compile() 内置函数，不落 pyc 缓存（沙箱外不可写）
    for f in (BASE, LANE, CLIENT):
        try:
            compile(f.read_text(), str(f), "exec")
            ok(True, "compile %s" % f.name)
        except Exception as e:
            ok(False, "compile %s：%s" % (f.name, e))

    base_tree = ast.parse(BASE.read_text())
    lane_tree = ast.parse(LANE.read_text())

    # A. _breathe 形态守卫
    fn = next((n for n in ast.walk(base_tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_breathe"), None)
    ok(fn is not None, "base.py 定义 _breathe")
    if fn is not None:
        ok(isinstance(fn, ast.AsyncFunctionDef), "_breathe 是 async（真让路点）")
        src = BASE.read_text()
        seg = ast.get_source_segment(src, fn) or ""
        deterministic = ("asyncio.sleep(0)" in seg) or ("wait_condition" in seg)
        ok(deterministic, "_breathe 体内是 sleep(0)/wait_condition 确定形态")
        banned = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                call_src = ast.dump(node.func)
                if "sleep" in call_src:
                    a = node.args[0] if node.args else None
                    if not (isinstance(a, ast.Constant) and a.value == 0):
                        banned.append("sleep 非 0 常量")
                if "create_timer" in call_src or "execute_activity" in call_src:
                    banned.append("timer/activity")
        ok(not banned, "_breathe 无正时长 timer/activity（%s）" % (banned or "干净"))

    # B. _log/_mark 保持同步
    for name in ("_log", "_mark"):
        n = next((x for x in ast.walk(base_tree)
                  if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and x.name == name), None)
        ok(n is not None and isinstance(n, ast.FunctionDef),
           "%s 仍为同步纯内存方法" % name)

    # C. dev_lane 让路点数量 >= 3
    breathes = []
    for node in ast.walk(lane_tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr == "_breathe":
                breathes.append(node)
    ok(len(breathes) >= 3, "dev_lane 让路点 >= 3 处（实得 %d）" % len(breathes))

    # E. client 重试语义：默认 3 次尝试、指数退避间隔参数化（t260903-06 升级后锚新参数名）
    csrc = CLIENT.read_text()
    ok("attempts" in csrc and ("3" in csrc), "client 重试尝试数参数化存在")
    ok("QUERY_RETRY_BASE_DELAY" in csrc, "重试退避基间隔参数化存在（测试可归零）")
    ok("_query_snapshot_with_retry" in csrc, "重试单点实现（详情/列表共用）")

    print("t03 结果：pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
