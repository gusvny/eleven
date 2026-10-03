# -*- coding: utf-8 -*-
"""t261003-05 — 引擎依赖场景的注册表 venv-fallback shim（回归钉）。

t261002-13-tmp-alarm-owner-receipt 真扫引擎 activities.scan_tmp_fixture_dirs
（需 temporalio），注册表却用裸 python3 调它 → 每个闸轮 0.1s 内 ENV_FAIL
（幻影 env-red，场景断言从未执行）。本测试锁三面：

  1. 注册表面：该条目的 cmd 用项目标准 venv-fallback shim（先引擎 venv，
     缺席回退 python3），绝不再退回裸 python3 形态；
  2. shim 语义面：同一 shell 形态在 venv 存在时解析到引擎 venv 解释器、
     venv 路径不存在时回退 python3、路径存在但不可执行也回退——
     桩路径复现，不靠真外部源之外的任何东西；
  3. 场景资产面：cmd 指向的脚本在树内真实存在（防改名漂移成哑条目）。

三态契约不在本测试重复验证（跑场景脚本属集成禁跑面）：venv 真缺席时
场景自身仍 ENV_FAIL exit 2，由场景文件的三态 docstring 与集成闸轮承接。
"""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RUN_SCENARIOS = REPO / "integration" / "run_scenarios.py"
SCENARIO = REPO / "integration" / "t261002-13" / "sc_tmp_alarm_owner_receipt.py"
ENTRY = "t261002-13-tmp-alarm-owner-receipt"
VENV_PY = "server/engine/.venv/bin/python"

# 项目标准 shim 前缀（先 venv、-x 才用、缺席回退 python3），其他引擎依赖条目同形
SHIM = 'PY=%s; [ -x "$PY" ] || PY=python3; "$PY" -B ' % VENV_PY


def _registry_cmds():
    """从被测树注册表机械取册（防手抄漂移），返回 {name: cmd}。

    用 ast 只取 SCENARIOS 字面三元组，不 exec 模块体（其模块级代码依赖
    其余 import 面，exec 进来会炸出与本票无关的 NameError）。
    """
    import ast
    tree = ast.parse(RUN_SCENARIOS.read_text(encoding="utf-8"))
    rows = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "SCENARIOS" for t in node.targets
        ):
            rows = ast.literal_eval(node.value)
            break
    assert rows is not None, "SCENARIOS table not found in run_scenarios.py"
    return {row[0]: row[2] for row in rows}


def test_registry_entry_uses_venv_fallback_shim():
    cmd = _registry_cmds()[ENTRY]
    assert cmd.startswith(SHIM), "registry entry must use the venv-fallback shim, got: %r" % cmd
    assert SCENARIO.name in cmd
    assert "|| PY=python3" in cmd, "fallback to python3 must stay (honest ENV_FAIL when venv absent)"
    # 不许悄悄退回裸 python3 形态（本票缺陷原形）
    assert not cmd.startswith("python3 "), "bare python3 is the defect being pinned"


def test_scenario_file_exists():
    assert SCENARIO.is_file(), "cmd points at a missing scenario file (dumb entry)"


def _shim_stdout(venv_path):
    """用桩脚本驱动 shim 的解析逻辑：打印最终选中的解释器路径。"""
    shim = 'PY=%s; [ -x "$PY" ] || PY=python3; "$PY" -c "import sys; print(sys.executable)"' % venv_path
    r = subprocess.run(["sh", "-c", shim], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_shim_prefers_engine_venv_when_present():
    if not (REPO / VENV_PY).is_file():
        import pytest
        pytest.skip("engine venv absent in this tree")
    out = _shim_stdout(VENV_PY)
    assert out.endswith(VENV_PY)


def test_shim_falls_back_when_path_missing():
    out = _shim_stdout("server/engine/.venv/definitely-not-here/python")
    assert os.path.basename(out) == "python3"


def test_shim_falls_back_when_not_executable(tmp_path):
    stub = tmp_path / "python"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o644)  # 存在但不可执行 → -x 判假，必须回退
    out = _shim_stdout(str(stub))
    assert os.path.basename(out) == "python3"
