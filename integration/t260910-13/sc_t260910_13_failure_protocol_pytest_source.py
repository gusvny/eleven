#!/usr/bin/env python3
"""失败分类协议 pytest 生产端映射（t260910-13，灰盒 L2 缝守卫）。

intent：工单锚⑤——不引 junit/第三方，conftest 原生钩子
（pytest_runtest_logreport）把 pytest 结果直接产出规范行：
ERROR→not-checked、FAILED→fail、PASSED→pass。本场景以微型真 pytest
跑（非 mock）钉死映射契约与「一行=一个用例」不变式：

  - 相位合并（方案 C7）：setup ERROR → not-checked；call FAILED → fail；
    PASSED → pass；teardown ERROR 不翻转已判 case（一个用例恒一行，
    证据附记不改状态）；同名去重。
  - 规范行字段完备：dur_s/started/git_sha 等最小字段在场，evidence 单行
    （无内嵌换行）。
  - 加载缝（方案 K5）：以 `-p conftest_result_protocol` 显式装配、cwd=integration/
    （模块可导入面），不依赖 pytest_plugins 在非根 conftest 的版本敏感行为。

pytest 缺失（venv 与系统均无）=ENV_FAIL exit 2 点名（三态契约，环境缺失红不假绿）；
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
与 developer L1（钩子单测）不同层：本条锁真 pytest 进程的生产端输出缝
（KI-049 同族：mock 单测覆盖不到的缝）。
安全红线：微型测试文件落系统临时目录，零真仓写入、零端口、3099/7233 零接触。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
if str(INTEG) not in sys.path:          # 集成侧回收 helper（同目录树根）
    sys.path.insert(0, str(INTEG))
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


MICRO = "\n".join([
    "import pytest",
    "",
    "def _boom():",
    "    raise RuntimeError('setup exploded')",
    "",
    "@pytest.fixture",
    "def broken():",
    "    _boom()",
    "    yield",
    "",
    "@pytest.fixture",
    "def noisy_teardown():",
    "    yield",
    "    raise RuntimeError('teardown noise')",
    "",
    "def test_setup_error(broken):",
    "    assert True",
    "",
    "def test_assert_fail():",
    "    assert 1 == 2",
    "",
    "def test_clean_pass():",
    "    assert True",
    "",
    "def test_teardown_does_not_flip(noisy_teardown):",
    "    assert True",
    "",
])


def find_pytest():
    for cand in ("server/engine/.venv/bin/python", sys.executable):
        p = str(Path(cand)) if os.path.isabs(cand) else str(REPO / cand)
        if os.path.exists(p) and subprocess.run(
                [p, "-c", "import pytest"], capture_output=True).returncode == 0:
            return p
    return None


py = find_pytest()
if py is None:
    print("ENV_FAIL: pytest 缺失（server/engine/.venv 与系统解释器均无）——"
          "pytest 生产端映射不可验（exit 2）")
    sys.exit(2)

# 夹具回收（260927 全族整治）：`t26091013-pytest-*` 同族存量在册，改走注册表。
td = str(mkdtemp_reclaimed("t26091013-pytest-"))
micro = Path(td) / "test_micro_protocol.py"
micro.write_text(MICRO)

try:
    p = subprocess.run(
        [py, "-m", "pytest", str(micro), "-q", "-p", "no:cacheprovider",
         "-p", "conftest_result_protocol"],
        cwd=str(INTEG), capture_output=True, text=True, timeout=300)
except subprocess.TimeoutExpired:
    print("  FAIL 微型 pytest 超时")
    sys.exit(1)
except OSError as e:
    print("ENV_FAIL: pytest 进程不可起：%s（exit 2）" % e)
    sys.exit(2)

rows = {}
for line in (p.stdout or "").splitlines():
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        ok(False, "P0 规范行可解析（坏行：%s）" % line[:60])
        continue
    name = str(d.get("name", ""))
    rows[name] = d  # 同名后写覆盖——出现两行即违反一行不变式，另断言

ok(p.returncode in (0, 1), "P0 微型 pytest 进程正常收场（rc=%s）" % p.returncode)
ok(len(rows) > 0, "P0 规范行在场（生产端真吐行）")


def find_row(fn_name):
    for name, d in rows.items():
        if fn_name in name:
            return d
    return None


r = find_row("test_setup_error")
ok(r is not None and r.get("status") == "not-checked",
   "P1 setup ERROR → not-checked（未跑到断言）")
ok(r is not None and str(r.get("evidence", "")).find("setup exploded") >= 0,
   "P1 ERROR 证据在案（点名炸点）")
r = find_row("test_assert_fail")
ok(r is not None and r.get("status") == "fail",
   "P2 call FAILED → fail")
r = find_row("test_clean_pass")
ok(r is not None and r.get("status") == "pass", "P3 PASSED → pass")
r = find_row("test_teardown_does_not_flip")
ok(r is not None and r.get("status") == "pass",
   "P4 teardown ERROR 不翻转已判 case（仍 pass）")
ok(r is not None and str(r.get("evidence", "")).find("teardown") >= 0,
   "P4 teardown 噪声附记证据（不静默吞）")
for fn in ("test_setup_error", "test_assert_fail", "test_clean_pass",
           "test_teardown_does_not_flip"):
    n = sum(1 for name in rows if fn in name)
    ok(n == 1, "P5 %s 恰一行（一行=一用例不变式，实得 %d）" % (fn, n))
allr = list(rows.values())
ok(all(isinstance(d.get("dur_s"), (int, float)) for d in allr),
   "P6 dur_s 数值在场（巡检 B 面耗时趋势数据源）")
ok(all("started" in d and "git_sha" in d and "suite" in d for d in allr),
   "P6 started/git_sha/suite 最小字段完备")
ok(all("\n" not in str(d.get("evidence", "")) for d in allr),
   "P6 evidence 单行（无内嵌换行）")

print("== 结果：%d ok / %d FAIL" % (pass_n, fail_n))
sys.exit(1 if fail_n else 0)
