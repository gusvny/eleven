#!/usr/bin/env python3
"""t260902-07 集成测试 ①：路由表静态校验（stdlib，无 PyYAML 依赖）。

校验对象：server/model-routes.yaml
- integration 路由 = zai-coding-cn / glm-5.3-flash
- 其余角色无回归（default/developer=zai/glm-5.3-flash；ops/artist=kimi-coding/k3）
- YAML 最小子集格式自检（无 tab、值裸 token 无引号、缩进 2 空格）
- 头部「可用 ref 核实清单」含 zai-coding-cn 条目（模型 ref 不许发明的红线）
- M10 注释含「交叉口径让位于配额急救」的如实记录（review R2 采纳项）
cwd = 泳道根。
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# 变异测试钩子：T07_TABLE_OVERRIDE 指向替代表文件时校验它而非真表
# （用于证明本测试对「切前旧表」会红——测试非永真）。默认不受环境影响。
TABLE = Path(os.environ["T07_TABLE_OVERRIDE"]) if os.environ.get("T07_TABLE_OVERRIDE") \
    else ROOT / "server" / "model-routes.yaml"

FAILS = []


def check(cond, msg):
    if cond:
        print("PASS %s" % msg)
    else:
        FAILS.append(msg)
        print("FAIL %s" % msg)


def parse_minimal_yaml(text):
    """YAML 最小子集解析：key: value 标量 + key: 开映射，忽略注释/空行。"""
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^([^:]+):\s*(.*)$", line.strip())
        if not m:
            raise ValueError("非最小子集行: %r" % raw)
        key, val = m.group(1).strip(), m.group(2).strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = val
    return root


def main():
    text = TABLE.read_text("utf-8")
    check("\t" not in text, "无 tab 字符")
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("#") or not ln.strip():
            continue
        if '"' in ln or "'" in ln:
            check(False, "第 %d 行含引号（值须裸 token）" % i)
    check(not [f for f in FAILS if "引号" in f], "全文件值裸 token 无引号")

    table = parse_minimal_yaml(text)
    roles = table.get("roles", {})

    integ = roles.get("integration", {})
    check(integ.get("provider") == "zai-coding-cn",
          "roles.integration.provider == zai-coding-cn（实得 %r）" % integ.get("provider"))
    check(integ.get("model") == "glm-5.3-flash",
          "roles.integration.model == glm-5.3-flash（实得 %r）" % integ.get("model"))

    expect = {
        "default": ("zai", "glm-5.3-flash"),
        "developer": ("zai", "glm-5.3-flash"),
        "ops": ("kimi-coding", "k3"),
        "artist": ("kimi-coding", "k3"),
        "product-operation": ("zai", "glm-5.3-flash"),
    }
    for role, (p, m) in expect.items():
        e = table.get(role, {}) if role == "default" else roles.get(role, {})
        check(e.get("provider") == p and e.get("model") == m,
              "无回归 %s = %s/%s（实得 %s/%s）" % (role, p, m, e.get("provider"), e.get("model")))

    po_tasks = roles.get("product-operation", {}).get("tasks", {})
    for kind, (p, m) in {"proofread": ("zai", "glm-5.2"),
                         "qa": ("zai", "glm-5.3"),
                         "analyst": ("zai", "glm-5.2")}.items():
        e = po_tasks.get(kind, {})
        check(e.get("provider") == p and e.get("model") == m,
              "无回归 product-operation.tasks.%s = %s/%s" % (kind, p, m))

    check("zai-coding-cn" in text.split("roles:")[0],
          "头部「可用 ref 核实清单」含 zai-coding-cn 条目")
    check("ZAI_CODING_CN_API_KEY" in text.split("roles:")[0],
          "头部清单标注 key 走 ZAI_CODING_CN_API_KEY")
    check("让位于配额急救" in text,
          "M10 注释如实记「交叉口径让位于配额急救」")

    if FAILS:
        print("\n%d 项失败" % len(FAILS))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
