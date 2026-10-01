# -*- coding: utf-8 -*-
"""L2 回归（261001 输出通道事故）：进程内工具的 stdout 是**信封**，人话一律 stderr。

事故（t261001-10 第 9 轮实证，见 notes/debts/known-issues.md KI-172）：
  引擎活动跑 `python3 server/admin.py call verify_lane <payload>`，而 `tools_registry.call`
  是**进程内**执行（`tools[name].run(args)`）。于是 `verify_lane` 里的人话备注（`print(...)`）
  与 admin 自己那行 JSON 信封**同流 stdout** ⇒ 引擎 `json.loads(admin_stdout)` 失败 ⇒
  闸回执退化成「no receipt (gate error: verify_lane integ produced no valid output)」。
  实况损失：**那一轮真跑出来的结果整轮被丢**（135 ran / 116 pass / 14 fail / 5 env-red 的
  收据在 `out/integration-report-*.json` 里躺着，票面却写 0 ran —— 而且票会被卡在 blocked）。

本文件的锁：
  ① 行为锁：`verify_lane._note()` 只写 stderr，stdout 一个字节都不落；
  ② 源码锁：进程内工具模块（现为 `server/tools/verify_lane.py`）零「裸 print」——
     复用 lint L13 的判据函数（同一把尺子，不在测试里另写一份）；
  ③ 通道锁（端到端薄壳）：`admin.py call verify_lane` 的 stdout 必须能整体 `json.loads`
     （信封不被任何备注污染）——用最便宜的 `lane=code` 道验管道，不跑场景、不起台。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib_env import clean_narrowing_env  # noqa: E402  (L12：起闸必须走清理单点)

REPO = Path(__file__).resolve().parents[2]
VERIFY_LANE = REPO / "server" / "tools" / "verify_lane.py"


def _run_py(snippet: str, cwd: Path):
    # L12 单点：剥掉继承来的收窄旋钮（本电池验的是通道，不是某个被收窄的面）
    return subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True,
                          cwd=str(cwd), env=clean_narrowing_env())


def test_n1_note_writes_to_stderr_only(tmp_path):
    """① `_note` 只走 stderr：stdout 必须干净（信封通道）。"""
    snippet = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('vl', r'%s')\n"
        "vl = importlib.util.module_from_spec(spec); spec.loader.exec_module(vl)\n"
        "vl._note('HELLO-NOTE')\n" % VERIFY_LANE
    )
    r = _run_py(snippet, tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout == "", "人话落到 stdout = 信封被污染：%r" % r.stdout
    assert "HELLO-NOTE" in r.stderr


def test_n2_inproc_tools_have_no_bare_stdout_print():
    """② 源码锁：复用 lint L13 的判据（同一把尺子），工具模块零裸 print。"""
    sys.path.insert(0, str(REPO / "integration"))
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location(
        "lint_probe", str(REPO / "integration" / "lint_tests.py"))
    lint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lint)
    bare_any = {}
    for rel in lint.L13_INPROC_TOOLS:
        txt = (REPO / rel).read_text(encoding="utf-8")
        bare = lint._l13_bare_stdout_prints(txt)
        if bare:
            bare_any[rel] = bare
    assert bare_any == {}, "进程内工具仍有裸 print（会污染 admin 的 JSON 信封）：%s" % bare_any
    # 判据自证：合成犯例必被抓（防「判据被改宽」的静默失效）
    assert lint._l13_bare_stdout_prints("def f():\n    print('note')\n") == [2]
    assert lint._l13_bare_stdout_prints(
        "def f():\n    print('note',\n          file=sys.stderr)\n") == []


def test_n3_admin_call_envelope_parses_as_json(tmp_path):
    """③ 端到端薄壳：`admin.py call verify_lane` 的 stdout 必须整体是一个 JSON 信封。

    用 `lane=code` 道（读泳道根 verify.yaml 的本地检查：无 yaml 即 fail-closed 判红）——
    不跑场景、不起 docker、不碰 3099；目的是验**通道**（stdout 只有信封），不是验业务。
    """
    payload = json.dumps({"lane": "code", "path": str(tmp_path), "base": "HEAD"})
    r = subprocess.run([sys.executable, str(REPO / "server" / "admin.py"),
                        "call", "verify_lane", payload],
                       capture_output=True, text=True, cwd=str(REPO),
                       env=clean_narrowing_env())
    try:
        env = json.loads(r.stdout)
    except json.JSONDecodeError as e:  # 信封被备注污染 = 本轮结果整轮丢失
        raise AssertionError("admin stdout 不是单个 JSON 信封（%s）：%r" % (e, r.stdout[:400]))
    assert isinstance(env, dict) and "ok" in env, env
