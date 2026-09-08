#!/usr/bin/env python3
"""t11-format-args-pairing（KI-013 / t260902-11）

静态配对检查：agent_activities.py 里所有「字面格式串」的 logger 调用，
占位符数必须等于实参数。KI-013 即此类手误（3 占位符 2 实参，logging
每次打点自吞 TypeError 打 traceback）。修复后此件必须绿；再犯同类手误
（任何行）也会在此被拦。
"""
import ast
import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "server/engine/agent_activities.py"
LEVELS = ("debug", "info", "warning", "error", "critical", "exception")
PH_RE = re.compile(r"%[-#0 +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa]")


def root_name(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def placeholders(fmt: str) -> int:
    # %% 是字面百分号，不算占位符
    return len(PH_RE.findall(fmt.replace("%%", "\x00")))


def main() -> int:
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    bad, scanned = [], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in LEVELS):
            continue
        if root_name(fn.value) not in ("logger", "activity", "log"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) \
                or not isinstance(node.args[0].value, str):
            continue
        scanned += 1
        if any(isinstance(a, ast.Starred) for a in node.args[1:]):
            continue  # *args 展开个数静态不可知，放过
        n_ph, n_args = placeholders(node.args[0].value), len(node.args) - 1
        if n_ph != n_args:
            bad.append((node.lineno, fn.attr, n_ph, n_args, node.args[0].value[:60]))
    if bad:
        for lineno, level, n_ph, n_args, fmt in bad:
            print(f"FAIL {TARGET.name}:{lineno} {level} 占位符{n_ph} 实参{n_args}: {fmt}")
        print(f"SUMMARY scanned={scanned} mismatch={len(bad)}")
        return 1
    print(f"OK 全部 {scanned} 处字面格式串 logger 调用占位符/实参配对一致")
    print(f"SUMMARY scanned={scanned} mismatch=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
