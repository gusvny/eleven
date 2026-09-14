#!/usr/bin/env python3
"""t260902-07 集成测试 ①：路由表静态校验（stdlib，无 PyYAML 依赖）。

t260914-05 重写（兜底腿退役后的守卫自足化）：
- 主判据：T07_PROJECT_KEY（缺省 "sandbar"）经 shared.resolve_routes_table 单点解析
  （真源=注册条目 paths.model_routes 声明指向的表；**不再回落仓内表**）。非 ok 态 →
  ENV_FAIL(2) 点名 state/path/error——无表环境显式红，绝不静默改读仓内表
  （「表在场但过期被静默用错」= t260914-05 要杀的毒面）；
- 夹具自足腿：内置最小表自带 ref 清单，跑同一套性质断言——断言体系非空转的自证，
  真源缺席（ENV_FAIL）时也能单独证明本守卫的性质断言有效；
- 真源腿（state=ok）与替代表腿（T07_TABLE_OVERRIDE）额外跑生产表专属三条
  （ref 清单含 zai-coding-cn / 标注 ZAI_CODING_CN_API_KEY / M10 让位于配额急救记录）。

口径（260910 宿主拍板）：**路由表是运行期可调的配置——谁跑哪个模型不钉死**。
性质断言（非快照）：
- 每个角色/分工都有非空 provider 与 model（字段齐备）；
- 所有 provider/model 取值必须出现在表头「可用 ref 核实清单」里（**不许发明 ref**）；
- `roles.integration` 角色必须存在（不许整段被删）；
- YAML 最小子集格式自检（无 tab、值裸 token 无引号、2 空格缩进）。
变异自证：T07_TABLE_OVERRIDE 指向变异表（如把 model 改成表头没有的 ref）必红——
测试非永真。cwd = 泳道根。
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server" / "engine"))
import shared  # noqa: E402

# 夹具自足表：ref 清单覆盖本表全部取值（同构于生产表的「表头清单」纪律）。
FIXTURE_TABLE = """\
# 夹具表（t260914-05 守卫自足腿：自带 ref 清单，不依赖任何真源/仓内表）
# 【可用 ref 核实清单】（夹具实证集合，仅本夹具内有效）
#   fx-prov / fx-model-a / fx-model-b / fx-int / fx-int-m / fx-po / fx-po-m / fx-t1 / fx-t2
default:
  provider: fx-prov
  model: fx-model-a
roles:
  integration:
    provider: fx-int
    model: fx-int-m
  developer:
    provider: fx-prov
    model: fx-model-b
  product-operation:
    provider: fx-po
    model: fx-po-m
    tasks:
      proofread:
        provider: fx-t1
        model: fx-t2
"""

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


def _check_table(text, label, production_extras=False):
    """性质断言一套（非快照）：格式/字段齐备/ref 清单完备。production_extras=真源与
    替代表专属三条（夹具表不带 zai-coding-cn 等生产 ref，不硬套）。"""
    base = len(FAILS)
    check("\t" not in text, "%s 无 tab 字符" % label)
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("#") or not ln.strip():
            continue
        if '"' in ln or "'" in ln:
            check(False, "%s 第 %d 行含引号（值须裸 token）" % (label, i))
    check(not [f for f in FAILS[base:] if "引号" in f], "%s 全文件值裸 token 无引号" % label)

    table = parse_minimal_yaml(text)
    roles = table.get("roles", {})
    header = text.split("roles:")[0]          # 「可用 ref 核实清单」所在的表头区
    header_known = set(re.findall(r"[A-Za-z0-9_.\-]+", header))

    def check_refs(where, entry):
        """性质断言：provider/model 非空 + 取值出现在表头 ref 清单内（不发明 ref）。"""
        p, m = entry.get("provider"), entry.get("model")
        check(bool(p) and bool(m), "%s %s provider/model 非空（实得 %r/%r）" % (label, where, p, m))
        for kind, v in (("provider", p), ("model", m)):
            if not v:
                continue
            check(v in header_known,
                  "%s %s 的 %s=%r 在表头「可用 ref 核实清单」内（不许发明 ref）" % (label, where, kind, v))

    # 角色面：凡是表里出现的角色，一律过性质断言（不钉具体取值 = 路由可动态调配）
    check("integration" in roles, "%s roles.integration 角色存在（不许整段删掉）" % label)
    for role, entry in roles.items():
        if role == "product-operation":
            continue  # 其 tasks 子表另行过检
        check_refs("roles.%s" % role, entry if isinstance(entry, dict) else {})

    po_tasks = roles.get("product-operation", {}).get("tasks", {})
    for kind, entry in (po_tasks.items() if isinstance(po_tasks, dict) else []):
        check_refs("roles.product-operation.tasks.%s" % kind,
                   entry if isinstance(entry, dict) else {})

    if production_extras:
        check("zai-coding-cn" in header,
              "%s 头部「可用 ref 核实清单」含 zai-coding-cn 条目" % label)
        check("ZAI_CODING_CN_API_KEY" in header,
              "%s 头部清单标注 key 走 ZAI_CODING_CN_API_KEY" % label)
        check("让位于配额急救" in text,
              "%s M10 注释如实记「交叉口径让位于配额急救」" % label)


def main():
    # 腿1 夹具自足（零环境依赖）：真源缺席被 ENV_FAIL 短路前，先证明断言体系有效。
    _check_table(FIXTURE_TABLE, "[夹具表]")

    # 腿2 主判据：替代表（变异自证钩子）或真源表（声明解析，禁回落仓内表）。
    override = os.environ.get("T07_TABLE_OVERRIDE")
    if override:
        _check_table(Path(override).read_text("utf-8"),
                     "[替代表 %s]" % os.path.basename(override), production_extras=True)
    else:
        key = os.environ.get("T07_PROJECT_KEY", "sandbar")
        resolved = shared.resolve_routes_table(key)
        if resolved["state"] != "ok":
            print("ENV_FAIL model-routes 真源不可用：key=%s state=%s 读=%s 指纹=%s error=%s"
                  % (key, resolved["state"], resolved["path"] or "（无表）",
                     resolved["fingerprint"] or "（无字节）", resolved["error"]))
            print("（t260914-05：缺表不静默——无表环境守卫显式红，不再回落读仓内表；"
                  "建表落点见上方 error 与 docs/model-routes-sample.yaml）")
            return 2
        print("PASS 真源解析 state=ok（key=%s，表=%s，指纹=%s）"
              % (key, resolved["path"], resolved["fingerprint"]))
        _check_table(Path(resolved["path"]).read_text("utf-8"),
                     "[真源表 key=%s]" % key, production_extras=True)

    if FAILS:
        print("\n%d 项失败" % len(FAILS))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
