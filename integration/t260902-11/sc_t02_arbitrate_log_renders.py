#!/usr/bin/env python3
"""t11-arbitrate-log-renders（KI-013 / t260902-11）

黑盒验收①：从源码 AST 提取 arbitrate 里 spawn 打点的真实格式串（不复制
粘贴、防行号漂移），用真 logging handler 以修复后的实参形态
（ticket_id, gen, str(cwd)）渲染。断言：
  1. 该调用实参数 ≥ 3（占位符数对齐）；
  2. 渲染输出含泳道 cwd；
  3. stderr 无 "--- Logging error ---"（KI-013 现象消失）。
"""
import ast
import io
import logging
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "server/engine/agent_activities.py"


def find_arbitrate_call():
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    hits = []
    for fn in ast.walk(tree):
        if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == "arbitrate"):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "info" \
                    and isinstance(node.args[0], ast.Constant) \
                    and "arbitrate] spawn" in str(node.args[0].value):
                hits.append(node)
    return hits


def render(fmt: str, args: tuple):
    err, out = io.StringIO(), io.StringIO()
    h_err, h_out = logging.StreamHandler(err), logging.StreamHandler(out)
    log = logging.getLogger("t11.arbitrate")
    log.handlers, log.level = [h_err, h_out], logging.INFO
    log.info(fmt, *args)
    for h in (h_err, h_out):
        log.removeHandler(h)
        h.flush()
    return out.getvalue(), err.getvalue()


def main() -> int:
    hits = find_arbitrate_call()
    if len(hits) != 1:
        print(f"FAIL arbitrate spawn 打点应恰好 1 处，实际 {len(hits)} 处")
        return 1
    node = hits[0]
    fmt = node.args[0].value
    n_args = len(node.args) - 1
    if n_args < 3:
        print(f"FAIL 实参数 {n_args} < 3（cwd 未补上）")
        return 1

    cwd = "/tmp/ws/t260902-11"          # 泳道形态的绝对路径
    rendered, errout = render(fmt, ("t260902-11", 0, str(cwd)))
    fails = []
    if cwd not in rendered:
        fails.append(f"渲染输出不含 cwd：{rendered!r}")
    if "Logging error" in errout:
        fails.append(f"stderr 出现 logging error：{errout.splitlines()[:6]}")
    if fails:
        for f in fails:
            print(f"FAIL {f}")
        return 1
    print(f"OK 渲染无 logging error 且含 cwd：{rendered.strip()}")
    print("SUMMARY rendered=1 cwd=yes logging_error=no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
