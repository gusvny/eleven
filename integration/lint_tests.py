#!/usr/bin/env python3
"""测试资产 lint（t260902 宿主令新增）——秒级静态检查，写完即红，不等跑套件。

覆盖（今晚四类实锤事故的反面）：
  L1 语法：integration/**/*.py 与 workbench/tests/*.mjs 全部编译/语法检查
        （连字符函数名、括号错配在此刻红，不到 pytest 收集时才炸）
  L2 收集：engine/tests pytest --collect-only（import 错误、fixture 缺失）
  L3 路径：workbench/tests/*.mjs 相对 import 的目标文件必须存在（深度算错即刻红）
  L4 清单：SCENARIOS 三元组结构完整——name 唯一、intent 非空、cmd 引用的脚本存在
  L5 孤儿：integration/**/ 下测试形态文件未登记 SCENARIOS 且不在豁免表 → 警告

用法：python3 integration/lint_tests.py（仓库根为 cwd；exit 0=过）
"""
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INTEG = REPO / "integration"
WB_TESTS = REPO / "server/plugins/workbench/tests"          # ← 项目参数（抄走改这里）
TP_TESTS = REPO / "server/engine/tests"          # ← 项目参数
VENV_PY = REPO / "server/engine/.venv/bin/python"  # ← 项目参数
PYC = tempfile.mkdtemp(prefix="lint-pyc-")

errors, warns = [], []


def err(msg):
    errors.append(msg)
    print("ERROR " + msg, flush=True)


def warn(msg):
    warns.append(msg)
    print("WARN  " + msg, flush=True)


def ok(msg):
    print("ok    " + msg, flush=True)


# L1 语法
def lint_syntax():
    n_py = n_mjs = 0
    for f in INTEG.rglob("*.py"):
        try:
            py_compile.compile(str(f), cfile=str(Path(PYC) / (f.name + ".pyc")), doraise=True)
            n_py += 1
        except py_compile.PyCompileError as e:
            err("L1 语法 %s: %s" % (f.relative_to(REPO), str(e).splitlines()[-1][:120]))
    if WB_TESTS.is_dir():
        for f in WB_TESTS.glob("*.mjs"):
            p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            if p.returncode != 0:
                err("L1 语法 %s: %s" % (f.relative_to(REPO), (p.stderr or "").splitlines()[-1][:120]))
            else:
                n_mjs += 1
    # integration/**/*.mjs 语法（t260907-04 arbitrate 实锤：机械清扫把 python 式
    # `# naming-compat` 追加进 mjs→SyntaxError 只能在套件执行时才炸，秒级 lint
    # 本应兜住——L1 原先只查 workbench/tests 的 mjs 是盲区）
    for f in INTEG.rglob("*.mjs"):
        p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        if p.returncode != 0:
            err("L1 语法 %s: %s" % (f.relative_to(REPO), (p.stderr or "").splitlines()[-1][:120]))
        else:
            n_mjs += 1
    ok("L1 语法：py %d / mjs %d 通过" % (n_py, n_mjs))


# L2 pytest 收集
def lint_collect():
    td = TP_TESTS
    if not td.is_dir():
        return
    venv_py = VENV_PY
    py = str(venv_py) if venv_py.exists() else sys.executable
    # 工具面先行分态（t260903-11）：pytest 本身缺席=工具面缺失（可见 WARN），
    # 不得谎报成「收集失败」——报错必须精确说哪个检查失败。
    probe = subprocess.run([py, "-c", "import pytest"], capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        warn("L2 pytest 不可用（%s 无 pytest）：收集检查无法执行——工具面缺失，非收集失败"
             % ("venv" if venv_py.exists() else "系统解释器"))
        return
    p = subprocess.run([py, "-m", "pytest", str(td), "-q", "--collect-only"],
                       capture_output=True, text=True, timeout=180)
    m = re.search(r"(\d+) errors?", p.stdout)
    if p.returncode != 0 and (m is None or int(m.group(1)) > 0):
        first = next((l for l in p.stdout.splitlines() if l.startswith("E ")), "")
        err("L2 pytest 收集失败：%s" % (first[:140] or p.stdout[-140:]))
    else:
        cnt = re.search(r"(\d+) tests? collected", p.stdout)
        ok("L2 pytest 收集：%s 条" % (cnt.group(1) if cnt else "?"))


# L3 mjs 相对 import 解析
def lint_mjs_imports():
    if not WB_TESTS.is_dir():
        return
    bad = 0
    for f in WB_TESTS.glob("*.mjs"):
        text = f.read_text()
        for m in re.finditer(r"""(?:from\s+|import\s*\(\s*)['"](\.\.?/[^'"]+)['"]""", text):
            tgt = (f.parent / m.group(1)).resolve()
            if not tgt.exists():
                err("L3 import 悬空 %s → %s" % (f.name, m.group(1)))
                bad += 1
    if bad == 0:
        ok("L3 mjs 相对 import 全部可解析")


# L4/L5 SCENARIOS 清单
EXEMPT = {
    "conftest.py", "fixture.py", "fixture.mjs", "lib.mjs", "cases.json",
    "golden.mjs", "reconcile-tokens.mjs", "build-info.mjs", "lib",
    # t260901-20：聚合入口已登记，t0*.mjs 为其子检查
    "t01_gate_shape.mjs", "t01_params_cache.mjs", "t02_cache_lifecycle.mjs",
    "t03_views_e2e.mjs", "t04_cli_door.mjs", "t05_dual_door.mjs",
    "t07_acceptance_walkthrough.mjs", "t06_results_doc.mjs",
    "registry-loader.py", "README.md", "check.sh", "smoke-realdata-report.md",
}
TEST_SHAPE = re.compile(r"^sc_")


def lint_registry():
    sys.path.insert(0, str(INTEG))
    import run_scenarios as rs  # noqa: E402
    names = [e[0] for e in rs.SCENARIOS]
    if len(names) != len(set(names)):
        dup = [n for n in set(names) if names.count(n) > 1]
        err("L4 清单重名：%s" % dup)
    missing_intent = [e[0] for e in rs.SCENARIOS if len(e) < 2 or not str(e[1]).strip()]
    if missing_intent:
        err("L4 intent 缺失：%s" % missing_intent)
    bad_cmd = []
    for entry in rs.SCENARIOS:
        name, intent, cmd = entry[0], entry[1], entry[2]
        script = next((p for p in str(cmd).split() if p.startswith("integration/")), None)
        if script and not (REPO / script).exists():
            bad_cmd.append("%s → %s" % (name, script))
    if bad_cmd:
        err("L4 cmd 脚本悬空：%s" % "; ".join(bad_cmd[:5]))
    if not errors:
        ok("L4 清单：%d 条三元组完整" % len(names))
    # L5 孤儿（纯模式匹配）：sc_* 未登记即红；非 sc_ = 共享代码，合法
    registered = set()
    for entry in rs.SCENARIOS:
        name, intent, cmd = entry[0], entry[1], entry[2]
        for p in str(cmd).split():
            if p.startswith("integration/"):
                registered.add((REPO / p).resolve())
    # t260904-12 移册白名单（定稿 §7.3「真跑不进闸」通道；文件在案供主库人工清单，
    # 不入 SCENARIOS——移册依据链见 README 已知限制 ticket-lifecycle 条）
    DEREGISTERED = {INTEG / "baselines" / "sc_ticket_lifecycle.mjs"}
    orphans = [str(f.relative_to(REPO)) for f in INTEG.rglob("sc_*")
               if f.is_file() and f.resolve() not in registered
               and f.resolve() not in DEREGISTERED]
    if orphans:
        err("L5 孤儿场景（sc_ 未登记）：%s" % orphans[:6])
    else:
        ok("L5 无孤儿（非 sc_ 文件视为共享代码，不检查）")


# L6 三态契约（t260904-12：闸内无 SKIP，定稿 §7.3）——锚真实形态，不锚 [SKIP] 字面
# （运行时模板串 `[$ {status.toUpperCase()}]` 源码 grep 不到，字面口径恒真化）。
SKIP_STATE = re.compile(r"""['"`]skip['"`]""")            # mjs/py 里 skip 状态值实参
SKIP_SUMMARY = re.compile(r"skip=\{|\bskip=%d|skip=\$\{|SUMMARY[^\n]*\bskip=")
ENV0_COMBO = re.compile(                                   # 缺环境→exit 0 语义组合
    r"ENV_FAIL[^\n]*\n[^\n]*exit\(0\)|skip[^\n]*\n[^\n]*exit\(0\)", re.I)
# 注释行与「退役」注记不参与（历史提及合法；行为面由 summarize 形状守卫与守卫场景钉）
RETIRED = re.compile("退役")


def _code_lines(text):
    for ln in text.splitlines():
        st = ln.strip()
        if RETIRED.search(ln) or st.startswith("//") or st.startswith("#") or st.startswith("*"):
            continue
        yield ln
SKIP_WHITELIST = {  # 注释性历史提及白名单（按文件名，记录残留由结算 evidence 核对）
    "bench.py",        # 变更记录表叙述旧口径
    "run_scenarios.py",  # docstring 对旧语义的退役注记
}


def lint_three_state():
    bad_state, bad_sum, bad_combo = [], [], []
    for f in list(INTEG.rglob("*.mjs")) + list(INTEG.rglob("*.py")):
        if f.name in SKIP_WHITELIST or f.name == "lint_tests.py":
            continue
        text = f.read_text(errors="replace")
        rel = f.relative_to(REPO)
        for i, ln in enumerate(_code_lines(text), 1):
            if SKIP_STATE.search(ln):
                bad_state.append("%s:%d" % (rel, i))
            if SKIP_SUMMARY.search(ln):
                bad_sum.append("%s:%d" % (rel, i))
        if ENV0_COMBO.search("\n".join(_code_lines(text))):
            bad_combo.append(str(rel))
    if bad_state:
        err("L6 skip 状态值残留（词表只认 pass/fail/env_fail/na）：%s" % bad_state[:8])
    else:
        ok("L6 无 skip 状态值残留")
    if bad_sum:
        err("L6 SUMMARY 旧形状 skip= 计数残留：%s" % bad_sum[:8])
    else:
        ok("L6 SUMMARY 无 skip 计数")
    if bad_combo:
        err("L6 「skip→exit 0」语义组合残留（缺环境必须 exit 2）：%s" % bad_combo[:8])
    else:
        ok("L6 无 skip→exit0 语义组合")
    # makeResults/summarize 形状守卫：mjs 里自定义 summarize 必须是三态退出码
    for f in INTEG.rglob("*.mjs"):
        text = f.read_text(errors="replace")
        if "function summarize" in text or "summarize()" in text and "process.exit" in text:
            if re.search(r"process\.exit\(f > 0 \? 1 : 0\)", text):
                err("L6 %s summarize 仍旧二态退出码（须 f>0||allNa?1:(e>0?2:0)）" % f.relative_to(REPO))
                break
    else:
        ok("L6 summarize 退出码形状合规")


def main():
    lint_syntax()
    lint_collect()
    lint_mjs_imports()
    lint_registry()
    lint_three_state()
    n_e, n_w = len(errors), len(warns)
    print("LINT done: %d error / %d warn" % (n_e, n_w))
    return 1 if n_e else 0


if __name__ == "__main__":
    sys.exit(main())
