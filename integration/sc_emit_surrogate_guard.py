#!/usr/bin/env python3
"""坏字符回执契约·回归网（KI-185/KI-186 族，261002 直修批沉淀）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为执行体）：坏字符（lone
surrogate）只许变得可见，不许带走整条回执或整段票史——三个子用例钉死双向契约：
A 入界消毒黑盒：带 lone surrogate 的畸形 op payload 进 ticket.py → 回执必须
  完整（合法 JSON、ok:false）、坏字符以 \\udcXX 可见转义点名、stderr 无
  Traceback、进程受控退出（不崩不 signal）。
B 同一契约在 client.py 入口（未知子命令错误面）同样成立。
C 族面锚（防回退）：server/ 下动态载荷的 print(json.dumps(..., ensure_ascii=
  False)) 出口必须带 backslashreplace 兜底（豁免白名单=固定文案 5 处，见
  ALLOW——新出口不带兜底即红）。锚的是「族面纪律」不是某一行实现：改写成
  别的打印方式可以，但坏字符带走回执不行。

安全红线：A/B 走错误面，零 Temporal、零产品写（只有工具自身 admin.log 审计
追加——与任何一次 ticket.py 调用同形状）。零端口零 docker 零控制台，秒级。
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PY = os.path.join(REPO, "server", "engine", ".venv", "bin", "python")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
BAD = "bad\udcbc\udc89"          # 两个 lone surrogate（t261001-23 实证同款）
VISIBLE = "\\udcbc"              # 出界时应看到的可见转义文本

# 固定文案豁免（261002 族面归类：载荷是 USAGE/常量回执，今日不可达坏字符）。
# 形状=(文件名, 行内锚)；新豁免必须带判词进本白名单，不许静默放行。
ALLOW = {
    ("ticket.py", "_TICKET_CLI_USAGE"),            # 用法文案
    ("admin.py", "tools_registry.schema()"),       # 代码派生 schema
    ("lane_audit.py", '{"dry_run": True}'),        # 常量回执
    ("scan_schedule.py", "_err(USAGE)"),           # 用法文案
    ("review_store.py", "'error': __doc__"),       # 文档串常量
    # t261004-26：statement-level 谓词（lib_emit_anchor）看得见旧子串守卫漏掉的出口，
    # 以下三处是它新抓的——判词如下；修复（加兜底）属产品面欠账，随专门票处置：
    ("admin.py", "调工具 %s"),      # admin 运维工具的人读轮次轨迹 print，非机器回执路径
    ("verify_m6.py", "巡检完成"),   # 离线 M6 验收脚本的人读报告输出，非回执路径
    ("verify_m6.py", "三档计数"),   # 同上（离线验收脚本人读输出）
}

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + ((" | " + str(detail)[:300]) if detail else ""))


def run_json(args_json, script):
    cp = subprocess.run([PY, script, args_json], cwd=REPO, capture_output=True,
                        text=True, timeout=60, errors="backslashreplace")
    return cp


def leg(label, script, args_obj):
    raw = json.dumps(args_obj)     # dumps 把 lone surrogate 编成 \udcXX 转义文本
    cp = run_json(raw, script)
    ok(cp.returncode in (0, 1, 2) and cp.returncode >= 0,
       "%s 进程受控退出（不崩不 signal）" % label, cp.returncode)
    try:
        body = json.loads(cp.stdout)
        parsed = True
    except Exception:
        body, parsed = {}, False
    ok(parsed and body.get("ok") is False,
       "%s 回执完整（合法 JSON 且 ok:false）" % label, cp.stdout[:120])
    ok(VISIBLE in cp.stdout,
       "%s 坏字符以可见转义点名（%s 在场）" % (label, VISIBLE), cp.stdout[-200:])
    ok("Traceback" not in cp.stderr,
       "%s stderr 无 Traceback（坏字符不得带走回执）" % label, cp.stderr[-200:])


def leg_family_anchor():
    """C 族面锚：动态载荷 print(json.dumps(...)) 出口必须带兜底（豁免白名单外）。

    t261004-26（-0013）：判据从子串形状升级为**语句级**（integration/lib_emit_anchor.py
    的 AST 谓词）——旧判据锚 `print(json.dumps(` 字面量 + 3 行窗，一层包裹括号就逃逸
    （-23 修法恰是这种包裹=守卫看不见自己的目标）；AST 天然无视包裹括号，且能看见
    `print("x" + json.dumps(...))` / `print('...' % ..., json.dumps(...))` 等出口。
    语法坏文件 fail-closed 红（点名文件），绝不静默跳过。"""
    import lib_emit_anchor
    viol = []
    for root, dirs, files in os.walk(os.path.join(REPO, "server")):
        dirs[:] = [d for d in dirs if d not in (".venv", "node_modules", "__pycache__")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            lines = text.splitlines()
            for v in lib_emit_anchor.emit_anchor_violations(text, fn):
                # 豁免=（文件名, 语句行内锚）：看违约行±1 行的源码段（可折行语句）。
                lineno_s = v.split(":")[1]
                lineno = int(lineno_s) if lineno_s.isdigit() else 0
                segment = "\n".join(lines[max(0, lineno - 2):lineno + 1])
                if any(a_fn == fn and a_anchor in segment for a_fn, a_anchor in ALLOW):
                    continue
                viol.append(v)
    ok(viol == [], "C 动态载荷出口全带坏字符兜底（语句级判据；豁免仅白名单 8 处）",
       viol)


def main():
    print("[emit-surrogate-guard] 坏字符回执契约·回归网（KI-185/186）")
    leg("A ticket.py", os.path.join("server", "tools", "ticket.py"), {"op": BAD})
    leg("B client.py", os.path.join("server", "engine", "client.py"), {"noop": BAD})
    leg_family_anchor()
    print("SUMMARY pass=%d fail=%d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
