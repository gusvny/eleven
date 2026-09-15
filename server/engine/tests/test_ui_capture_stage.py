# -*- coding: utf-8 -*-
"""ui_capture_stage 单元测试（t260915-18）：引擎单所有者台原语的 L1 电池。

全部外部交互经 runner 注入（假 runner：参数记录 + 固定回执/退出码/超时异常），
零 docker、零 node、零网络——外部输入（回执 JSON/旋钮 env/票号）的畸形用例
按工程惯例桩化复现（不靠真外部源）。覆盖：
- attempt→project 映射（归一/哈希截断/畸形票红）；
- 回执校验（四类畸形 + bool 陷阱）；
- up/down 分档语义（env=降级 / contract=直红）+ 全终态回收（down 永不 raise）；
- 旋钮三态（缺省/覆盖/畸形 usage 红）；
- 死台点名词匹配（capture-lane 契约）。

跑法：仓库根 `server/engine/.venv/bin/python -m pytest server/engine/tests/test_ui_capture_stage.py -q`
（venv 缺失用任一装有 pytest 的解释器）。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ui_capture_stage as uis  # noqa: E402


class FakeRunner:
    """假 runner：记录 (cmd, cap, env_extra)，按脚本回放 (rc, out, err)；
    raise_exc 非空时直接抛（模拟默认 runner 的超上限 UiStageEnvError）。"""

    def __init__(self, rc=0, out="", err="", raise_exc=None):
        self.script = dict(rc=rc, out=out, err=err, raise_exc=raise_exc)
        self.calls = []

    def __call__(self, cmd, cap, env_extra):
        self.calls.append({"cmd": list(cmd), "cap": cap, "env": dict(env_extra or {})})
        if self.script["raise_exc"] is not None:
            raise self.script["raise_exc"]
        return self.script["rc"], self.script["out"], self.script["err"]


GOOD_RECEIPT = json.dumps({"project": "ui-shot-x-g0", "ports": {"console": 21000},
                           "temporal": 21001, "ui": 21002})


@pytest.fixture(autouse=True)
def _clean_knobs():
    """旋钮 env 进出清理（R3 纪律：注入缝隙必须自清除，防跨用例污染）。"""
    saved = {k: os.environ.get(k) for k in (
        "SANDBAR_CAPTURE_STAGE_UP_CAP_S", "SANDBAR_CAPTURE_STAGE_DOWN_CAP_S")}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---- attempt→project 映射 ----------------------------------------------------

def test_capture_stage_project_mapping():
    assert uis.capture_stage_project("t260915-18", 0) == "ui-shot-t260915-18-g0"
    assert uis.capture_stage_project("T260915_18 X/gen2", 3) == "ui-shot-t260915-18-x-gen2-g3"


def test_capture_stage_project_long_ticket_hashed():
    long_ticket = "t" + "x" * 200
    name = uis.capture_stage_project(long_ticket, 1)
    assert name.startswith("ui-shot-") and name.endswith("-g1")
    assert len(name) <= 45, "超长票必须哈希截断（project 闸 ≤40 主体）"
    assert uis.capture_stage_project(long_ticket, 1) == name, "同一票哈希稳定（可追踪）"


@pytest.mark.parametrize("bad", ["", "   ", "///", "-"])
def test_capture_stage_project_malformed_rejected(bad):
    with pytest.raises(uis.UiStageError):
        uis.capture_stage_project(bad, 0)


def test_capture_stage_project_negative_gen_clamped():
    assert uis.capture_stage_project("t1", -5) == "ui-shot-t1-g0", "负 gen 钳 0（不红）"


# ---- 回执校验（写盘前自证；capture-lane 对畸形=ENV_FAIL 不回落） --------------

def test_validate_stage_receipt_ok():
    r = uis.validate_stage_receipt("noise lines\n[stage] 起台中…\n" + GOOD_RECEIPT)
    assert r["project"] == "ui-shot-x-g0"
    assert r["ports"]["console"] == 21000


@pytest.mark.parametrize("bad", ["", "\n  \n", "not json", "[]",
                                 '{"ports": {"console": 1}}',
                                 '{"project": ""} ',
                                 '{"project": "p", "ports": {"console": 0}}',
                                 '{"project": "p", "ports": {"console": -3}}',
                                 '{"project": "p", "ports": {"console": "21000"}}',
                                 '{"project": "p", "ports": {"console": true}}'])
def test_validate_stage_receipt_malformed_rejected(bad):
    with pytest.raises(uis.UiStageError):
        uis.validate_stage_receipt(bad)


def test_stage_dead_marker():
    assert uis.stage_dead_marker("ENV_FAIL: 外部舞台已死（console 127.0.0.1:21000 不可达）")
    assert not uis.stage_dead_marker("ENV_FAIL: stage JSON 不可读")
    assert not uis.stage_dead_marker("")
    assert not uis.stage_dead_marker(None), "None/非串不炸（消费外部 stderr 面）"


# ---- 旋钮三态（缺省/覆盖/畸形 usage 红） ---------------------------------------

def test_knob_defaults_and_overrides():
    assert uis.up_cap_s() == 180
    assert uis.down_cap_s() == 150
    os.environ["SANDBAR_CAPTURE_STAGE_UP_CAP_S"] = "240.5"
    os.environ["SANDBAR_CAPTURE_STAGE_DOWN_CAP_S"] = "90"
    assert uis.up_cap_s() == 240.5
    assert uis.down_cap_s() == 90.0


@pytest.mark.parametrize("key,val", [("SANDBAR_CAPTURE_STAGE_UP_CAP_S", "abc"),
                                     ("SANDBAR_CAPTURE_STAGE_UP_CAP_S", "0"),
                                     ("SANDBAR_CAPTURE_STAGE_UP_CAP_S", "-10"),
                                     ("SANDBAR_CAPTURE_STAGE_UP_CAP_S", "1e999"),
                                     ("SANDBAR_CAPTURE_STAGE_DOWN_CAP_S", "nan"),
                                     ("SANDBAR_CAPTURE_STAGE_DOWN_CAP_S", "1..2")])
def test_knob_malformed_usage_red(key, val):
    os.environ[key] = val
    with pytest.raises(uis.UiStageError, match="usage 红"):
        (uis.up_cap_s if key.endswith("UP_CAP_S") else uis.down_cap_s)()


def test_knob_blank_means_default():
    os.environ["SANDBAR_CAPTURE_STAGE_UP_CAP_S"] = "  "
    assert uis.up_cap_s() == 180, "空白=缺省语义（与 stage_docker 旋钮同口径）"


@pytest.fixture
def fake_repo(tmp_path):
    """哑仓根：integration/stage_docker.py 以空桩存在（FakeRunner 不真跑，
    stage_cli_path 只做 isfile 检查）。"""
    d = tmp_path / "integration"
    d.mkdir()
    (d / "stage_docker.py").write_text("# stub\n", encoding="utf-8")
    return str(tmp_path)


def test_stage_cli_path_missing_envfail(tmp_path):
    with pytest.raises(uis.UiStageEnvError):
        uis.stage_cli_path(repo_root=str(tmp_path)), "缺 CLI=环境面（降级不直红）"


# ---- up_stage 分档语义 --------------------------------------------------------

def test_up_stage_ok_and_command_shape(fake_repo):
    fr = FakeRunner(rc=0, out=GOOD_RECEIPT + "\n")
    r = uis.up_stage("ui-shot-x-g0", repo_root=fake_repo, up_cap=111,
                     env_extra={"SANDBAR_STAGE_TICKET": "t1/gen0"}, runner=fr)
    assert r["project"] == "ui-shot-x-g0"
    cmd = fr.calls[0]["cmd"]
    assert cmd[:3] == ["python3", str(Path(fake_repo) / "integration" / "stage_docker.py"),
                       "up"]
    assert cmd[3] == "--project"
    assert "--services" in cmd and cmd[cmd.index("--services") + 1] == "full"
    assert cmd[cmd.index("--timeout") + 1] == "111", "上限透传给 stage up 预算"
    assert fr.calls[0]["env"].get("SANDBAR_STAGE_TICKET") == "t1/gen0", "attempt 映射进租约"


def test_up_stage_env_fail_degradable(fake_repo):
    fr = FakeRunner(rc=2, err="[stage-up] ENV_FAIL: docker 不可用")
    with pytest.raises(uis.UiStageEnvError, match="ENV_FAIL"):
        uis.up_stage("p", repo_root=fake_repo, runner=fr)


def test_up_stage_unknown_rc_contract_red(fake_repo):
    fr = FakeRunner(rc=1, err="STAGE_FAIL: [up] 起台半途失败")
    with pytest.raises(uis.UiStageError, match="STAGE_FAIL"):
        uis.up_stage("p", repo_root=fake_repo, runner=fr)


def test_up_stage_malformed_receipt_contract_red(fake_repo):
    fr = FakeRunner(rc=0, out="garbage not json")
    with pytest.raises(uis.UiStageError, match="回执"):
        uis.up_stage("p", repo_root=fake_repo, runner=fr)


def test_up_stage_timeout_env_degradable(fake_repo):
    fr = FakeRunner(raise_exc=uis.UiStageEnvError("stage 子进程超上限 111s 被杀"))
    with pytest.raises(uis.UiStageEnvError):
        uis.up_stage("p", repo_root=fake_repo, up_cap=111, runner=fr)


def test_up_stage_runner_rc_garbage(fake_repo):
    fr = FakeRunner(rc=None, out=GOOD_RECEIPT)   # 畸形 rc（桩不智障假设）
    with pytest.raises(uis.UiStageError):
        uis.up_stage("p", repo_root=fake_repo, runner=fr)


# ---- down_stage：幂等、绝不 raise、失败响亮 -------------------------------------

def test_down_stage_ok(fake_repo):
    fr = FakeRunner(rc=0, out='{"residue": []}\n')
    r = uis.down_stage("p", repo_root=fake_repo, runner=fr)
    assert r["ok"] is True
    assert fr.calls[0]["cmd"][2:4] == ["down", "--project"], "down 走 stage CLI"


def test_down_stage_failure_loud_not_raising(fake_repo):
    fr = FakeRunner(rc=1, err="STAGE_FAIL: [down] 孤儿台回收失败（x：boom）")
    r = uis.down_stage("p", repo_root=fake_repo, runner=fr)
    assert r["ok"] is False
    assert "STAGE_FAIL" in r["detail"], "失败必须点名（不可见=泄漏复发土壤）"


def test_down_stage_timeout_never_raises(fake_repo):
    fr = FakeRunner(raise_exc=uis.UiStageEnvError("拆台超上限"))
    r = uis.down_stage("p", repo_root=fake_repo, runner=fr)
    assert r["ok"] is False and "超上限" in r["detail"]


def test_down_stage_missing_cli_never_raises(tmp_path):
    r = uis.down_stage("p", repo_root=str(tmp_path))   # CLI 缺失也只响亮不炸
    assert r["ok"] is False and "stage_docker" in r["detail"]


def test_down_stage_empty_project_usage(fake_repo):
    r = uis.down_stage("  ", repo_root=fake_repo, runner=FakeRunner())
    assert r["ok"] is False and "usage 红" in r["detail"]
    r2 = uis.down_stage(None, repo_root=fake_repo, runner=FakeRunner())
    assert r2["ok"] is False


def test_down_stage_runner_garbage_rc_not_ok(fake_repo):
    fr = FakeRunner(rc=None, out="\x00 binary")
    r = uis.down_stage("p", repo_root=fake_repo, runner=fr)
    assert r["ok"] is False, "畸形 rc≠0 → 响亮不静默 ok"


# ---- run_capture_stage 编排协程（up/down 打桩，capture 用真短进程桩） ---------

def _patch_stage(monkeypatch, up=None, down=None):
    up_calls, down_calls = [], []

    def fake_up(project, **kw):
        up_calls.append({"project": project, **kw})
        if isinstance(up, Exception):
            raise up
        return up if up is not None else {"project": project,
                                          "ports": {"console": 21000}}

    def fake_down(project, **kw):
        down_calls.append(project)
        if down is not None:
            return down
        return {"ok": True, "detail": "已拆"}

    monkeypatch.setattr(uis, "up_stage", fake_up)
    monkeypatch.setattr(uis, "down_stage", fake_down)
    return up_calls, down_calls


def test_run_capture_stage_success_downs_stage(monkeypatch, tmp_path):
    up_calls, down_calls = _patch_stage(monkeypatch)
    r = asyncio.run(uis.run_capture_stage(
        project="ui-shot-x-g0", services="temporal",
        capture_cmd=[sys.executable, "-c", "pass"],
        capture_timeout_s=30, stage_up_timeout_s=60, repo_root=str(tmp_path)))
    assert r["ok"] is True and r["reclaimed"] is True
    assert len(down_calls) == 1 and down_calls[0] == "ui-shot-x-g0"
    assert up_calls[0]["services"] == "temporal", "services 透传 up"
    assert up_calls[0]["up_cap"] == 60, "起台帽透传"
    assert up_calls[0]["repo_root"] == str(tmp_path)


def test_run_capture_stage_appends_stage_json(monkeypatch, tmp_path):
    _patch_stage(monkeypatch)
    seen = {}

    def cap(cmd, timeout):
        seen["args"] = list(cmd)
        return 0

    orig = uis.asyncio.create_subprocess_exec

    async def fake_exec(*cmd, **kw):
        seen["args"] = list(cmd)

        class _P:
            returncode = 0
            async def communicate(self_inner):
                return b"{}", b""
        return _P()

    monkeypatch.setattr(uis.asyncio, "create_subprocess_exec", fake_exec)
    r = asyncio.run(uis.run_capture_stage(
        project="p", capture_cmd=["node", "capture-lane.mjs"],
        capture_timeout_s=5, stage_up_timeout_s=5, repo_root=str(tmp_path)))
    assert "--stage-json" in seen["args"], "stage-json 追加给消费者"
    assert r["ok"] is True


def test_run_capture_stage_timeout_names_and_downs(monkeypatch, tmp_path):
    _, down_calls = _patch_stage(monkeypatch)
    r = asyncio.run(uis.run_capture_stage(
        project="p", capture_cmd=[sys.executable, "-c", "import time; time.sleep(30)"],
        capture_timeout_s=0.6, stage_up_timeout_s=10, repo_root=str(tmp_path)))
    assert r["ok"] is False and r["timed_out"] is True
    assert "超时" in r["detail"], "fail-visible：超时必须点名"
    assert down_calls == ["p"], "超时路拆台"


def test_run_capture_stage_capture_failure_downs(monkeypatch, tmp_path):
    _, down_calls = _patch_stage(monkeypatch)
    r = asyncio.run(uis.run_capture_stage(
        project="p", capture_cmd=[sys.executable, "-c", "raise SystemExit(3)"],
        capture_timeout_s=30, stage_up_timeout_s=10, repo_root=str(tmp_path)))
    assert r["ok"] is False and r["timed_out"] is False
    assert r["capture_rc"] == 3
    assert down_calls == ["p"], "失败路拆台（四终态之三）"


def test_run_capture_stage_cancel_downs_then_raises(monkeypatch, tmp_path):
    _, down_calls = _patch_stage(monkeypatch)

    async def slow_exec(*cmd, **kw):
        class _P:
            returncode = None
            async def communicate(self):
                await asyncio.sleep(60)   # capture 桩长眠，等取消打进来
                return b"", b""
            def kill(self):
                self.returncode = -9
            def terminate(self):
                self.returncode = -15
            async def wait(self):
                return 0
        return _P()

    monkeypatch.setattr(uis.asyncio, "create_subprocess_exec", slow_exec)

    async def driver():
        task = asyncio.ensure_future(uis.run_capture_stage(
            project="p", capture_cmd=["x"], capture_timeout_s=60,
            stage_up_timeout_s=10, repo_root=str(tmp_path)))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(driver())
    assert down_calls == ["p"], "取消不是免拆台牌照"


def test_run_capture_stage_up_envfail_propagates_no_down(monkeypatch, tmp_path):
    up_calls, down_calls = _patch_stage(
        monkeypatch, up=uis.UiStageEnvError("docker 不可用"))
    with pytest.raises(uis.UiStageEnvError):
        asyncio.run(uis.run_capture_stage(
            project="p", capture_cmd=[sys.executable, "-c", "pass"],
            capture_timeout_s=5, stage_up_timeout_s=5, repo_root=str(tmp_path)))
    assert down_calls == [], "起台失败无台可拆（清理归 stage_docker 自身失败腿）"
    assert up_calls and up_calls[0]["project"] == "p"


def test_run_capture_stage_up_contract_red_propagates(monkeypatch, tmp_path):
    _patch_stage(monkeypatch, up=uis.UiStageError("回执畸形"))
    with pytest.raises(uis.UiStageError):
        asyncio.run(uis.run_capture_stage(
            project="p", capture_cmd=[sys.executable, "-c", "pass"],
            capture_timeout_s=5, stage_up_timeout_s=5, repo_root=str(tmp_path)))


# ---- services 感知回执校验（场景①腿 A 实证：temporal 精简台无 console） ------

def test_receipt_temporal_only_passes_without_console():
    r = uis.validate_stage_receipt(json.dumps({
        "project": "p", "services": ["temporal"],
        "ports": {"temporal": 27071, "ui": 27072}}), services=["temporal"])
    assert r["project"] == "p"


def test_receipt_temporal_missing_own_port_red():
    with pytest.raises(uis.UiStageError) as ei:
        uis.validate_stage_receipt(json.dumps({
            "project": "p", "services": ["temporal"], "ports": {}}),
            services=["temporal"])
    assert "ports.temporal" in str(ei.value)


def test_receipt_legacy_no_services_requires_console():
    with pytest.raises(uis.UiStageError):
        uis.validate_stage_receipt(json.dumps({
            "project": "p", "ports": {"temporal": 1}}))


def test_run_capture_stage_up_contract_red_downs_before_raise(monkeypatch, tmp_path):
    """up rc=0 但回执畸形=台在场：契约红必须先补拆再重抛（260915 实证缝）。"""
    _, down_calls = _patch_stage(monkeypatch, up=uis.UiStageError("回执畸形"))
    with pytest.raises(uis.UiStageError):
        asyncio.run(uis.run_capture_stage(
            project="p", capture_cmd=[sys.executable, "-c", "pass"],
            capture_timeout_s=5, stage_up_timeout_s=5, repo_root=str(tmp_path)))
    assert down_calls == ["p"], "契约红=台大概率在场，幂等补刀 down"
