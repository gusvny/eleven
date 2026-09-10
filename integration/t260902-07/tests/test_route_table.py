#!/usr/bin/env python3
"""t260902-07 集成测试 ①：路由表静态校验（stdlib，无 PyYAML 依赖）。

校验对象：server/model-routes.yaml

口径（260910 宿主拍板）：**路由表是运行期可调的配置——谁跑哪个模型不钉死**。
本测试只做「防错」的性质断言，不做角色取值的快照：
- 每个角色/分工都有非空 provider 与 model（字段齐备、格式合法）；
- 所有 provider/model 取值必须出现在表头「可用 ref 核实清单」里（**不许发明
  ref**——这是真错误面）；
- `roles.integration` 角色必须存在（不许整段被删）；
- YAML 最小子集格式自检（无 tab、值裸 token 无引号、缩进 2 空格）；
- 头部「可用 ref 核实清单」含 zai-coding-cn 条目与 ZAI_CODING_CN_API_KEY 标注
  （ref 清单自身的完备性，与具体角色分配无关）；
- M10 注释含「交叉口径让位于配额急救」的如实记录（review R2 采纳项）。
历史沿革：本测试原先钉死 integration=kimi-coding/k3 等角色取值（260907 口径）。
260910 宿主裁定「model-route 本来就应该动态可调，不需要这个断言」后，快照断言
全部移除——改表不再需要同步改守卫；留性质断言防「写错不存在的模型名」「角色
被整段删掉」这类真错误。
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
    header = text.split("roles:")[0]          # 「可用 ref 核实清单」所在的表头区
    header_known = set(re.findall(r"[A-Za-z0-9_.\-]+", header))

    def check_refs(where, entry):
        """性质断言：provider/model 非空 + 取值出现在表头 ref 清单内（不发明 ref）。"""
        p, m = entry.get("provider"), entry.get("model")
        check(bool(p) and bool(m), "%s provider/model 非空（实得 %r/%r）" % (where, p, m))
        for kind, v in (("provider", p), ("model", m)):
            if not v:
                continue
            check(v in header_known,
                  "%s 的 %s=%r 在表头「可用 ref 核实清单」内（不许发明 ref）" % (where, kind, v))

    # 角色面：凡是表里出现的角色，一律过性质断言（不钉具体取值 = 路由可动态调配）
    check("integration" in roles, "roles.integration 角色存在（不许整段删掉）")
    for role, entry in roles.items():
        if role == "product-operation":
            continue  # 其 tasks 子表另行过检
        check_refs("roles.%s" % role, entry if isinstance(entry, dict) else {})

    po_tasks = roles.get("product-operation", {}).get("tasks", {})
    for kind, entry in (po_tasks.items() if isinstance(po_tasks, dict) else []):
        check_refs("roles.product-operation.tasks.%s" % kind,
                   entry if isinstance(entry, dict) else {})

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
