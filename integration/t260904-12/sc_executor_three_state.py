#!/usr/bin/env python3
"""执行器三态退出码与输出契约（t260904-12，定稿 §7.3「闸内无 SKIP」）。

intent：集成闸的机械语义钉在执行器出口——场景级只有 PASS / FAIL / ENV_FAIL，
退出码 0/1/2 分家，汇总行与明细双向净。注入假场景表驱动 run_scenarios.main()
（黑盒出口断言：退出码、输出行形状、SUMMARY 计数），覆盖：

- 全过 → exit 0；
- 有 FAIL → exit 1（产品红）；
- fail=0 且 env_fail>0 → exit 2，且输出 `ENV_FAIL [名] exit=2` 行 + 四空格缩进
  尾段点名缺什么（环境红可归因）；
- FAIL 与 ENV_FAIL 并存 → 产品红优先 exit 1（C7：环境红不稀释产品红）；
- 未定义退出码（如 exit 3）→ 落 FAIL 不放行、不归环境（退出码封闭性，防新
  码被静默吞成 pass/env）；
- 全部子用例 N/A 场景经 lib_env.fail_if_all_na 折算为产品红 exit 1（C9：无可验对象
  =设计/覆盖问题，修场景不补环境）；
- SUMMARY 五计数形状 + 双向净不变式 ran=pass+fail+env_fail；
- lib_env 共享助手契约：env_fail()=exit 2、fail_if_all_na()=exit 1。

安全红线：全部假场景落临时目录，不触真仓库状态；本场景自身零环境依赖。
"""
import contextlib
import importlib.util
import io
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("rs_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

sys.path.insert(0, str(REPO / "integration"))

pass_n = fail_n = 0
_results = []


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)
    _results.append("pass" if cond else "fail")


def drive(entries):
    """注入假场景表跑执行器，返回 (退出码, stdout)。条目=(场景名, 脚本文本)。"""
    with tempfile.TemporaryDirectory(prefix="t12tri-") as td:
        td_path = Path(td)
        table = []
        for i, (name, script) in enumerate(entries):
            p = td_path / ("s%d.py" % i)
            p.write_text(script)
            table.append((name, "假场景（t260904-12 注入）", "python3 %s" % p))
        rs.SCENARIOS = table
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rs.main()
        return rc, buf.getvalue()


ENV_SCRIPT = ("import sys; sys.path.insert(0, %r); import lib_env; "
              "print('playwright-core 未装配（隔离台缺位）'); "
              "lib_env.env_fail('playwright-core 未装配')" % str(REPO / "integration"))
ALL_NA_SCRIPT = ("import sys; sys.path.insert(0, %r); import lib_env; "
                 "lib_env.na('feature flag 未启用，该子用例无对象'); "
                 "lib_env.na('系统态无该功能，该子用例无对象'); "
                 "lib_env.fail_if_all_na(2, 2)" % str(REPO / "integration"))

SUMMARY_RE = re.compile(
    r"^SCENARIOS ran=(\d+) pass=(\d+) fail=(\d+) env_fail=(\d+) na=(\d+) \(\d+s\)$",
    re.M)


def summary_of(out):
    m = SUMMARY_RE.search(out)
    return None if not m else dict(
        ran=int(m.group(1)), passed=int(m.group(2)), failed=int(m.group(3)),
        env_fail=int(m.group(4)), na=int(m.group(5)))


def detail_counts(out):
    """汇总行之前的明细行计数（双向净比对对象）。"""
    head = out.split("SCENARIOS ran=")[0]
    return dict(
        fail=len(re.findall(r"^FAIL \[", head, re.M)),
        env_fail=len(re.findall(r"^ENV_FAIL \[", head, re.M)),
        passed=len(re.findall(r"^PASS \[", head, re.M)))


def check_invariant(label, out):
    """双向净不变式：ran=pass+fail+env_fail，且汇总计数与明细行一致。"""
    s = summary_of(out)
    d = detail_counts(out)
    ok(s is not None, label + "：SUMMARY 五计数形状在场")
    if s:
        ok(s["ran"] == s["passed"] + s["failed"] + s["env_fail"],
           label + "：ran=pass+fail+env_fail（双向净不变式）")
        ok(s["env_fail"] == d["env_fail"] and s["failed"] == d["fail"]
           and s["passed"] == d["passed"], label + "：汇总计数与明细行一致（不谎报）")


# ---- A. 全过 → 0 ----
rc, out = drive([("t12-全过", "print('ok')\n")])
ok(rc == 0, "A1 全过 exit 0")
ok("PASS [t12-全过]" in out, "A2 PASS 行形状")
check_invariant("A3", out)

# ---- B. 有 FAIL → 1，尾段缩进点名 ----
rc, out = drive([("t12-断言红", "print('断言不符：期望 X 实得 Y')\nimport sys\nsys.exit(1)\n")])
ok(rc == 1, "B1 有 FAIL exit 1（产品红）")
ok("FAIL [t12-断言红] exit=1" in out, "B2 FAIL 行形状带 exit")
ok("    断言不符：期望 X 实得 Y" in out, "B3 尾段四空格缩进收进")
check_invariant("B4", out)

# ---- C. 环境红 → 2，ENV_FAIL 行 + 尾段点名缺什么 ----
rc, out = drive([("t12-环境缺", ENV_SCRIPT)])
ok(rc == 2, "C1 fail=0 且 env_fail>0 exit 2（环境红）")
ok("ENV_FAIL [t12-环境缺] exit=2" in out, "C2 ENV_FAIL 行字符级形状")
ok("    playwright-core 未装配" in out, "C3 缩进尾段点名缺什么（环境红可归因）")
check_invariant("C4", out)

# ---- D. FAIL 与 ENV_FAIL 并存 → 产品红优先 exit 1（C7） ----
rc, out = drive([("t12-并存-产品", "import sys\nsys.exit(1)\n"),
                 ("t12-并存-环境", ENV_SCRIPT)])
ok(rc == 1, "D1 FAIL 与 ENV_FAIL 并存 → exit 1（产品红优先，C7）")
ok("FAIL [t12-并存-产品] exit=1" in out and "ENV_FAIL [t12-并存-环境] exit=2" in out,
   "D2 两类红行并存各自在案（不互相吞）")
check_invariant("D3", out)

# ---- E. 未定义退出码 → FAIL（退出码封闭性） ----
rc, out = drive([("t12-野码", "import sys\nsys.exit(3)\n")])
ok(rc == 1, "E1 未定义退出码 exit 3 → 整道产品红（不放行、不归环境）")
ok("FAIL [t12-野码] exit=3" in out and "ENV_FAIL [t12-野码]" not in out,
   "E2 野码落 FAIL 行而非 ENV_FAIL/PASS（封闭性归产品红）")
check_invariant("E3", out)

# ---- F. 全部子用例 N/A → 产品红（C9，经 lib_env 折算） ----
rc, out = drive([("t12-全NA", ALL_NA_SCRIPT)])
ok(rc == 1, "F1 全部子用例 N/A 场景 → exit 1（产品红：无可验对象=设计/覆盖问题，C9）")
ok("FAIL [t12-全NA] exit=1" in out, "F2 全 N/A 落 FAIL 行（不假绿不归环境）")
check_invariant("F3", out)

# ---- G. lib_env 助手契约（环境缺失绝不 exit 0） ----
import lib_env  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        lib_env.env_fail("探针：依赖缺失")
        got = None
    except SystemExit as e:
        got = e.code
ok(got == 2 and "ENV_FAIL: 探针：依赖缺失" in buf.getvalue(),
   "G1 lib_env.env_fail 打印点名缺什么并 exit 2")
with contextlib.redirect_stdout(buf):
    try:
        lib_env.fail_if_all_na(1, 1)
        got = None
    except SystemExit as e:
        got = e.code
ok(got == 1, "G2 lib_env.fail_if_all_na 全部子用例 N/A exit 1（产品红收口）")
with contextlib.redirect_stdout(buf):
    try:
        lib_env.fail_if_all_na(2, 1)
        got = None
    except SystemExit as e:
        got = e.code
ok(got is None, "G3 部分子用例 N/A 不触发全 N/A 红（na 仅系统状态子用例的合法形态）")

# ---- 执行契约：SUMMARY + FAIL>0 → exit 1 ----
env_fail_n = _results.count("env_fail")
print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (pass_n, fail_n, env_fail_n))
sys.exit(1 if fail_n > 0 else 0)
