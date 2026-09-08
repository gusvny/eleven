#!/usr/bin/env python3
"""t260902-10 集成场景③：本票根 verify.yaml 的 test 声明端到端（真实泳道环境）。

黑盒口径：读泳道根 verify.yaml——若本票声明了 checks.test，就按引擎同款语义
（cwd=声明目录、/bin/sh -c 执行、exit==0 绿）亲自执行该命令断言可跑绿；
声明缺失（泳道无 verify.yaml / 未声明 checks.test）与 venv 未引导均归**环境红
ENV_FAIL（exit 2）**：病因归「测试供给未就位」，修复=补声明/引导供给（乙段 supply
通道），非产品代码问题——按定稿 §7.3「2=病因归环境（修=按声明补供给）」路由，
闸给「供给修复」注记而非打回代码。
"""
import re
import subprocess
import sys
from pathlib import Path

LANE = Path.cwd()


def find_test_decl(text):
    """从最小 YAML 子集里定位 lanes.code.checks.test 的 cwd/cmd（够本场景用）。"""
    lines = text.splitlines()
    # v2 列表命令制（t260904-12）：checks=[{id, cmd, cwd?, timeout?}]——定位 "- id: test"
    # 条目，取其 cmd（与同条目 cwd）。旧键式 "  test:" 兼容保留（存量声明两态都认）。
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*-\s+id:\s*test\s*$", ln)
        if m:
            base_indent = len(ln) - len(ln.lstrip())
            cwd_rel, cmd = ".", None
            for ln2 in lines[i + 1:]:
                if not ln2.strip() or ln2.lstrip().startswith("#"):
                    continue
                ind = len(ln2) - len(ln2.lstrip())
                if ind <= base_indent:
                    break
                k, _, v = ln2.strip().partition(":")
                v = v.strip()
                if k == "cwd" and v:
                    cwd_rel = v
                elif k == "cmd" and v:
                    cmd = v
            if cmd:
                return (cwd_rel, cmd)
    test_i = None
    for i, ln in enumerate(lines):
        if re.match(r"^ {4}test:\s*$", ln):
            test_i = i
            break
    if test_i is None:
        return None
    cwd_rel, cmd, base_indent = ".", None, len(lines[test_i]) - len(lines[test_i].lstrip())
    for ln in lines[test_i + 1:]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= base_indent:
            break
        k, _, v = ln.strip().partition(":")
        v = v.strip()
        if k == "cwd" and v:
            cwd_rel = v
        elif k == "cmd" and v:
            cmd = v
    return (cwd_rel, cmd) if cmd else None


def main():
    vy = LANE / "verify.yaml"
    if not vy.is_file():
        print("ENV_FAIL: 泳道根无 verify.yaml（测试声明未供给；修复=补声明，供给面非代码面）")
        return 2
    decl = find_test_decl(vy.read_text("utf-8"))
    if decl is None:
        print("ENV_FAIL: 根 verify.yaml 未声明 checks.test（测试声明未供给；修复=补声明，供给面非代码面）")
        return 2
    cwd_rel, cmd = decl
    cwd_dir = (LANE / cwd_rel).resolve()
    if not cwd_dir.is_dir():
        print("FAIL 声明 cwd 不存在: %s" % cwd_dir)
        print("SUMMARY: 失败")
        return 1
    p = subprocess.run(["/bin/sh", "-c", cmd], cwd=str(cwd_dir), capture_output=True, text=True)
    if p.returncode == 0:
        print("PASS 根 verify.yaml test 声明按引擎语义跑绿（cwd=%s）" % cwd_rel)
        print("SUMMARY: 1/1 PASS")
        return 0
    # 环境前提缺失（venv/pytest 未引导）= 环境红：fail-closed 是引擎正确行为，此处记 ENV_FAIL
    tail = ((p.stdout or "") + (p.stderr or ""))[-200:].strip().replace("\n", " | ")
    if ".venv" in cmd and not (LANE / "server/engine/.venv/bin/python").exists():
        print("ENV_FAIL: test 声明在位但泳道 venv 未引导（引擎正确 fail-closed；环境前提项）：%s" % tail)
        return 2
    print("FAIL test 声明命令非零（rc=%d）: %s" % (p.returncode, tail))
    print("SUMMARY: 失败")
    return 1


if __name__ == "__main__":
    sys.exit(main())
