#!/usr/bin/env python3
"""测试资产 lint（t260902 宿主令新增）——秒级静态检查，写完即红，不等跑套件。

覆盖（今晚四类实锤事故的反面）：
  L1 语法：integration/**/*.py 与 workbench/tests/*.mjs 全部编译/语法检查
        （连字符函数名、括号错配在此刻红，不到 pytest 收集时才炸）
  L2 收集：temporal-poc/tests pytest --collect-only（import 错误、fixture 缺失）
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
WB_TESTS = REPO / "server/dsh/workbench/tests"          # ← 项目参数（抄走改这里）
TP_TESTS = REPO / "server/dsh/temporal-poc/tests"          # ← 项目参数
VENV_PY = REPO / "server/dsh/temporal-poc/.venv/bin/python"  # ← 项目参数
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
    ok("L1 语法：py %d / mjs %d 通过" % (n_py, n_mjs))


# L2 pytest 收集
def lint_collect():
    td = TP_TESTS
    if not td.is_dir():
        return
    venv_py = VENV_PY
    py = str(venv_py) if venv_py.exists() else sys.executable
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
    orphans = [str(f.relative_to(REPO)) for f in INTEG.rglob("sc_*")
               if f.is_file() and f.resolve() not in registered]
    if orphans:
        err("L5 孤儿场景（sc_ 未登记）：%s" % orphans[:6])
    else:
        ok("L5 无孤儿（非 sc_ 文件视为共享代码，不检查）")


def main():
    lint_syntax()
    lint_collect()
    lint_mjs_imports()
    lint_registry()
    n_e, n_w = len(errors), len(warns)
    print("LINT done: %d error / %d warn" % (n_e, n_w))
    return 1 if n_e else 0


if __name__ == "__main__":
    sys.exit(main())
