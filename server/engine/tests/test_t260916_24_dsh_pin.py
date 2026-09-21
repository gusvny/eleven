"""t260916-24（dsh-upgrade epic T4）钉路径/版本面 UT。

覆盖方案步骤1 用例表：①显式 SANDBAR_AGENT_CMD 生效；②缺省不破现状；③期望版本
比对三态；④STRICT 硬闸/缺省告警；⑤`--version` 探测失败四态（缺文件/非零/超时/
输出畸形）+ 全终态回收；⑥meta 增列读侧兼容；⑦畸形 env 显式点名；⑧docker tag
提取；⑨face 形状 + 源码锚防接线漂移。

全程零网络/真 dsh（版本探测用临时桩脚本）；禁真 Temporal/真 git（conftest 纪律）。
"""
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

import dsh_pin

REPO = Path(__file__).resolve().parents[3]
ENGINE = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """四个旋钮逐用例隔离：缺省分支测试不得被外层 env 污染。"""
    for k in (dsh_pin.ENV_AGENT_CMD, dsh_pin.ENV_EXPECTED, dsh_pin.ENV_STRICT,
              dsh_pin.ENV_RUNTIME, dsh_pin.ENV_AGENT_IMAGE):
        monkeypatch.delenv(k, raising=False)


def _stub(tmp_path, body, name="stub_dsh.py"):
    """可执行桩脚本（探子按 `<cmd0> --version` 直接执行，需 shebang+chmod，同真二进制）。"""
    p = tmp_path / name
    if not body.startswith("#!"):
        body = "#!/usr/bin/env python3\n" + body
    p.write_text(body, "utf-8")
    p.chmod(0o755)
    return str(p)


# ---- ①显式路径生效 ----------------------------------------------------------

def test_resolve_explicit_env(tmp_path):
    r = dsh_pin.resolve_dsh_cmd(env={"SANDBAR_AGENT_CMD": "/opt/dsh-versions/0.1.5-rc.2/bin/dsh --profile sandbar-headless"})
    assert r["cmd"][0] == "/opt/dsh-versions/0.1.5-rc.2/bin/dsh"
    assert r["cmd"][1:] == ["--profile", "sandbar-headless"]
    assert r["source"] == "env"


# ---- ②缺省不破现状 ----------------------------------------------------------

def test_resolve_default_matches_legacy_constant():
    r = dsh_pin.resolve_dsh_cmd(env={})
    assert r["source"] == "default"
    assert r["cmd"] == shlex.split("dsh --profile sandbar-headless")


def test_default_equal_to_agent_activities_dsh_cmd():
    """缺省输出与 agent_activities.DSH_CMD 常量逐元素等值（现状保底）。"""
    import agent_activities  # noqa: PLC0415 - 重量 import 只在本用例
    assert dsh_pin.resolve_dsh_cmd(env={})["cmd"] == list(agent_activities.DSH_CMD)


def test_spawn_wiring_uses_resolver_source_anchor():
    """源码锚：_prepare_agent_spawn 的 cmd 组装走声明钉解析单点 _dsh_resolved
    （t260921-14 接线翻新：resolve_dsh_cmd 的声明入参经 _dsh_resolved 进入，防接线
    漂移回退到 env-only 旧锚），且 DSH_CMD 缺省别名仍在（import 现状保底）。"""
    src = (ENGINE / "agent_activities.py").read_text("utf-8")
    assert "resolved_dsh = _dsh_resolved(project)" in src
    assert 'pin_file = artifacts_dir / ("dsh_pin_%s.json" % tag)' in src
    assert "DSH_CMD = shlex.split(" in src


# ---- ⑦畸形 env 显式点名 -----------------------------------------------------

def test_resolve_malformed_shlex_raises_named():
    with pytest.raises(dsh_pin.DshPinError) as ei:
        dsh_pin.resolve_dsh_cmd(env={"SANDBAR_AGENT_CMD": "dsh --profile 'unclosed"})
    assert "SANDBAR_AGENT_CMD" in str(ei.value)
    assert "unclosed" in str(ei.value)  # 原文在场


def test_resolve_empty_env_falls_back_to_default():
    assert dsh_pin.resolve_dsh_cmd(env={"SANDBAR_AGENT_CMD": ""})["source"] == "default"


# ---- ③期望版本比对三态 ------------------------------------------------------

def test_expected_state_three_states():
    assert dsh_pin.expected_state_of("0.1.5-rc.2", env={}) == "unset"
    assert dsh_pin.expected_state_of(
        "0.1.5-rc.2", env={"SANDBAR_DSH_EXPECTED_VERSION": "0.1.5-rc.2"}) == "match"
    assert dsh_pin.expected_state_of(
        "0.1.1-rc.2", env={"SANDBAR_DSH_EXPECTED_VERSION": "0.1.5-rc.2"}) == "mismatch"


def test_face_carries_expected_state():
    face = dsh_pin.dsh_face_payload(mode="docker", env={"SANDBAR_AGENT_IMAGE": "sandbar-agent:dsh-0.1.5-rc.2-s1",
                                                        "SANDBAR_DSH_EXPECTED_VERSION": "0.1.1-rc.2"},
                                    probe=False)
    assert face["expected"] == "0.1.1-rc.2"
    assert face["expected_state"] == "mismatch"


# ---- ④STRICT 硬闸 / 缺省告警 ------------------------------------------------

def _mismatch_face():
    return {"mode": "host", "version": "0.1.1-rc.2", "expected_state": "mismatch",
            "cmd": ["dsh"], "cmd_source": "default", "bin": "dsh", "real_bin": None,
            "image": None, "image_source": None, "expected": "0.1.5-rc.2",
            "version_state": "ok", "version_detail": "", "ts": 0}


def test_enforce_strict_mismatch_raises():
    with pytest.raises(dsh_pin.DshPinError) as ei:
        dsh_pin.enforce_expected(_mismatch_face(), env={"SANDBAR_DSH_STRICT": "1",
                                                        "SANDBAR_DSH_EXPECTED_VERSION": "0.1.5-rc.2"})
    assert "硬闸" in str(ei.value)
    assert "0.1.1-rc.2" in str(ei.value) and "0.1.5-rc.2" in str(ei.value)


def test_enforce_default_mismatch_warns_not_raises():
    note = dsh_pin.enforce_expected(_mismatch_face(), env={"SANDBAR_DSH_EXPECTED_VERSION": "0.1.5-rc.2"})
    assert "mismatch" in note and "0.1.5-rc.2" in note


def test_enforce_match_and_unset_plain_note():
    ok = dict(_mismatch_face(), version="0.1.5-rc.2", expected_state="match")
    assert "mismatch" not in dsh_pin.enforce_expected(ok, env={"SANDBAR_DSH_EXPECTED_VERSION": "0.1.5-rc.2"})
    unset = dict(_mismatch_face(), expected_state="unset")
    assert dsh_pin.enforce_expected(unset, env={}) == dsh_pin.face_note(unset)


# ---- ⑤版本探测失败四态 + 全终态回收 -----------------------------------------

def test_probe_version_ok(tmp_path):
    stub = _stub(tmp_path, "#!/usr/bin/env python3\nprint('0.1.1-rc.2')\n")
    pv = dsh_pin.probe_dsh_version(stub, timeout=10)
    assert pv["state"] == "ok" and pv["version"] == "0.1.1-rc.2"


def test_probe_version_missing_binary():
    pv = dsh_pin.probe_dsh_version("/nonexistent/dsh/bin", timeout=5)
    assert pv["state"] == "error" and "起不了" in pv["detail"]


def test_probe_version_nonzero_exit(tmp_path):
    stub = _stub(tmp_path, "import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n")
    pv = dsh_pin.probe_dsh_version(stub, timeout=10)
    assert pv["state"] == "error" and "3" in pv["detail"]


def test_probe_version_timeout_reaps(tmp_path):
    stub = _stub(tmp_path, "import time\ntime.sleep(30)\n")
    t0 = time.monotonic()
    pv = dsh_pin.probe_dsh_version(stub, timeout=0.6)
    elapsed = time.monotonic() - t0
    assert pv["state"] == "error" and "超时" in pv["detail"]
    assert elapsed < 10  # 超时路径必须快速返回（进程组已收割，不留挂尸）


def test_probe_version_malformed_output(tmp_path):
    cases = {
        "empty": "print('')\n",
        "multiline": "print('dsh 0.1.1-rc.2')\nprint('build 42')\n",
        "non_version": "print('version: unknown')\n",
    }
    for name, body in cases.items():
        stub = _stub(tmp_path, body, name="stub_%s.py" % name)
        pv = dsh_pin.probe_dsh_version(stub, timeout=10)
        assert pv["state"] == "error", name
        assert "非单行版本样" in pv["detail"], name


def test_probe_version_orphan_reaped(tmp_path):
    """超时后桩进程（含其子进程组）确被收割：桩 fork 的孙进程同组，killpg 全灭。"""
    marker = tmp_path / "alive.txt"
    stub = _stub(tmp_path, (
        "import subprocess, sys, time\n"
        "subprocess.Popen([%r, '-c', 'import time; time.sleep(30)'], start_new_session=False)\n"
        "open(%r, 'w').write('x')\n"
        "time.sleep(30)\n" % (sys.executable, str(marker))))
    pv = dsh_pin.probe_dsh_version(stub, timeout=0.6)
    assert pv["state"] == "error"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        out = subprocess.run(["pgrep", "-f", "time.sleep(30)"], capture_output=True)
        if out.returncode != 0:
            break
        time.sleep(0.2)
    else:
        raise AssertionError("超时收割后仍存活 sleep 子进程——进程组未全灭")


# ---- ⑥meta 增列读侧兼容 -----------------------------------------------------

def test_meta_payload_dsh_column_additive():
    import shared
    face = {"mode": "host", "version": "0.1.1-rc.2"}
    p = shared.worker_meta_payload(repo_root="/tmp", pid=7, dsh_face=face)
    assert p["dsh"] == face and p["pid"] == 7
    legacy = shared.worker_meta_payload(repo_root="/tmp", pid=7)
    assert "dsh" not in legacy  # 不传=既有形状逐字节不变


def test_meta_write_read_roundtrip_with_dsh(tmp_path):
    import shared
    face = {"mode": "docker", "version": "0.1.5-rc.2", "image": "sandbar-agent:dsh-0.1.5-rc.2-s1"}
    path = tmp_path / "w.meta"
    payload = shared.write_worker_meta(str(path), repo_root="/tmp", pid=9, dsh_face=face)
    assert payload["dsh"] == face
    meta, state, detail = shared.read_worker_meta_state(str(path))
    assert state == "ok", detail
    assert meta["dsh"]["version"] == "0.1.5-rc.2"


# ---- ⑧docker tag 提取 -------------------------------------------------------

def test_image_tag_version_extraction():
    ok = dsh_pin.image_tag_version("sandbar-agent:dsh-0.1.5-rc.2-s1")
    assert ok["state"] == "ok" and ok["version"] == "0.1.5-rc.2"
    ok2 = dsh_pin.image_tag_version("sandbar-agent:dsh-0.1.1-rc.2-s3")
    assert ok2["state"] == "ok" and ok2["version"] == "0.1.1-rc.2"
    weird = dsh_pin.image_tag_version("weird:latest")
    assert weird["state"] == "unknown" and weird["version"] is None
    empty = dsh_pin.image_tag_version("sandbar-agent:dsh--s1")
    assert empty["state"] == "unknown"


# ---- ⑨face 形状 -------------------------------------------------------------

def test_face_host_with_stub_probe(tmp_path):
    stub = _stub(tmp_path, "print('0.1.1-rc.2')\n")
    face = dsh_pin.dsh_face_payload(mode="host", env={"SANDBAR_AGENT_CMD": "%s --profile x" % stub},
                                    probe_timeout=10)
    assert face["mode"] == "host" and face["cmd_source"] == "env"
    assert face["bin"] == stub
    assert face["real_bin"] == str(Path(stub).resolve())
    assert face["version"] == "0.1.1-rc.2" and face["version_state"] == "ok"


def test_face_docker_image_precedence_and_tag_derived():
    face = dsh_pin.dsh_face_payload(mode="docker",
                                    env={"SANDBAR_AGENT_IMAGE": "sandbar-agent:dsh-0.1.5-rc.2-s2"},
                                    default_image="sandbar-agent:dsh-0.1.1-rc.2-s1", probe=False)
    assert face["image"] == "sandbar-agent:dsh-0.1.5-rc.2-s2" and face["image_source"] == "env"
    assert face["version"] == "0.1.5-rc.2"
    assert "tag-derived" in face["version_detail"]  # 非实证标注（C5②）
    face2 = dsh_pin.dsh_face_payload(mode="docker", env={}, probe=False,
                                     default_image="sandbar-agent:dsh-0.1.1-rc.2-s1")
    assert face2["image_source"] == "default" and face2["version"] == "0.1.1-rc.2"


def test_face_unknown_mode_never_raises():
    face = dsh_pin.dsh_face_payload(mode="garbage", env={}, probe=False)
    assert face["mode"] == "unknown" and face["version_state"] == "not-probed"


def test_face_bad_cmd_degrades_to_error_face():
    """face 入口遇到坏 shlex 响亮抛（对齐旧 import 行为）；_dsh_face_once 的降级形状
    由 agent_activities 源码锚覆盖（本文件 test_spawn_wiring_uses_resolver_source_anchor）。"""
    with pytest.raises(dsh_pin.DshPinError):
        dsh_pin.dsh_face_payload(mode="host", env={"SANDBAR_AGENT_CMD": "a ' b"}, probe=False)


def test_face_note_single_line_with_fields():
    note = dsh_pin.face_note(_mismatch_face())
    assert "\n" not in note
    for token in ("mode=host", "版本=0.1.1-rc.2", "期望="):
        assert token in note, token
