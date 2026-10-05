# -*- coding: utf-8 -*-
"""t260925-08 调用方身份注入与翻严——单测（KI-119 收口）。

覆盖（方案验收口径逐条）：
- undeclared_policy()：缺省=refuse（翻严锚）；旋钮合法值两形；畸形值（大小写/空白/
  任意串/非字符串）=点名 raise（外部输入畸形用例必带）；
- judge_caller undeclared：缺省拒收 why 点名 SANDBAR_CALLER_PROJECT；旋钮 record=旧
  B 策略逐字节语义；
- cross_project_judge 缺省参数翻严 + 畸形旋钮 fail-closed refuse+人话 why（N3 两路径
  均不静默）；
- ENV_ALLOWLIST 含身份注入两键，且与 shared 常量等值（agent_runtime 禁 import shared，
  字面量漂移由本测试机械锁）；exec_agent env 白名单合并行为（fake docker 桩，不真跑）；
- _prepare_agent_spawn 注入：合法 project → env 带 caller key+SURFACE 标签；空/形状
  非法（大写/空格/路径穿越串）不注入；
- identity_receipt injected_by：尽力面标签值域（env+SURFACE=lane-agent / env 无
  SURFACE=external-env / arg 与 none 来源不带键）。
全程零 Temporal/零网络/零 docker（conftest 已把引擎目录挂进 sys.path）。
"""
import os

import pytest

import agent_activities  # noqa: E402
import agent_runtime
import caller_gate
import shared


# ---------- undeclared_policy()（策略解析单点） ----------

def test_policy_default_is_refuse(monkeypatch):
    monkeypatch.delenv(shared.UNDECLARED_POLICY_ENV, raising=False)
    assert shared.undeclared_policy() == "refuse"
    assert shared.UNDECLARED_POLICY == "refuse"


def test_policy_env_valid_values(monkeypatch):
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")
    assert shared.undeclared_policy() == "record"
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "refuse")
    assert shared.undeclared_policy() == "refuse"


@pytest.mark.parametrize("bad", ["RECORD", " record", "record ", "allow", "refuse;record",
                                 "yolo", "r e c o r d"])
def test_policy_malformed_raises(monkeypatch, bad):
    """畸形值=点名 raise（不静默回落缺省——fail-closed，外部输入畸形用例族）。
    严格等值语义：带空白包边=误配显式暴露，不 strip 纠偏。"""
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, bad)
    with pytest.raises(ValueError) as ei:
        shared.undeclared_policy()
    assert shared.UNDECLARED_POLICY_ENV in str(ei.value)


def test_policy_blank_falls_to_default(monkeypatch):
    """空串/纯空白=unset 语义（回落缺省 refuse），不误伤空 env 注入。"""
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "   ")
    assert shared.undeclared_policy() == "refuse"
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "")
    assert shared.undeclared_policy() == "refuse"


def test_policy_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")
    assert shared.undeclared_policy("refuse") == "refuse"
    with pytest.raises(ValueError):
        shared.undeclared_policy("bogus")


# ---------- judge_caller（client 侧） ----------

def _ident(value="", iclass="undeclared", src="none"):
    return {"value": value, "src": src, "identity_class": iclass}


def test_judge_undeclared_default_refuse_names_missing_identity(monkeypatch):
    monkeypatch.delenv(shared.UNDECLARED_POLICY_ENV, raising=False)
    v = caller_gate.judge_caller(_ident(), "sandbar", None)
    assert v["decision"] == "refuse"
    assert shared.CALLER_PROJECT_ENV in v["why"]      # 点名缺失身份的 env 名
    assert v["stamp"] == "" and h_signals_absent(v)


def h_signals_absent(verdict):
    return verdict["override_used"] is False


def test_judge_undeclared_record_via_knob(monkeypatch):
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")
    v = caller_gate.judge_caller(_ident(), "sandbar", None)
    assert v["decision"] == "record_undeclared"
    assert v["stamp"] == shared.CALLER_UNDECLARED_MARK
    assert "undeclared" in v["notice"]


def test_judge_undeclared_targetless_pass_zero_regression(monkeypatch):
    """引擎件（target=""）零回归：undeclared 恒 pass（哨兵 stamp 保留身份面）。"""
    monkeypatch.delenv(shared.UNDECLARED_POLICY_ENV, raising=False)
    v = caller_gate.judge_caller(_ident(), "", None)
    assert v["decision"] == "pass" and v["stamp"] == shared.CALLER_UNDECLARED_MARK


def test_judge_same_project_unchanged(monkeypatch):
    """验收④：同项目写零行为变化（与策略无关）。"""
    for pol in (None, "record", "refuse"):
        if pol:
            monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, pol)
        else:
            monkeypatch.delenv(shared.UNDECLARED_POLICY_ENV, raising=False)
        v = caller_gate.judge_caller(_ident("sandbar", "declared", "env"), "sandbar", None)
        assert v["decision"] == "pass" and v["stamp"] == "sandbar"


# ---------- cross_project_judge（workflow 侧第二道，缺省参数自动翻严） ----------

def test_wf_judge_default_refuse_and_knob_record(monkeypatch):
    monkeypatch.delenv(shared.UNDECLARED_POLICY_ENV, raising=False)
    assert shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "sandbar", "")["action"] \
        == "refuse"
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "record")
    g = shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "sandbar", "")
    assert g["action"] == "allow_record"


def test_wf_judge_malformed_knob_refuse_with_reason(monkeypatch):
    monkeypatch.setenv(shared.UNDECLARED_POLICY_ENV, "bogus")
    g = shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "sandbar", "")
    assert g["action"] == "refuse" and "bogus" in g["why"]  # N3：workflow 侧也不静默


# ---------- ENV_ALLOWLIST（字面量等值锁 + 合并行为） ----------

def test_allowlist_carries_identity_keys_literal_equality():
    """agent_runtime 禁 import shared（字面量就地复制）——漂移由本测试机械锁。"""
    assert "SANDBAR_CALLER_PROJECT" in agent_runtime.ENV_ALLOWLIST
    assert "SANDBAR_CALLER_SURFACE" in agent_runtime.ENV_ALLOWLIST
    assert shared.CALLER_PROJECT_ENV in agent_runtime.ENV_ALLOWLIST
    assert shared.CALLER_SURFACE_ENV in agent_runtime.ENV_ALLOWLIST


def test_exec_agent_merges_identity_env(tmp_path, monkeypatch):
    """docker 形态 exec env 只带白名单：身份两键在场即透传（fake docker 桩，不真跑）。"""
    calls = {}

    def fake_popen(argv, **kw):
        calls["argv"] = argv

        class P:
            pass

        p = P()
        p.pid = 4242
        return p

    monkeypatch.setattr(agent_runtime, "docker_bin", lambda: "/bin/true")
    monkeypatch.setattr(agent_runtime.subprocess, "Popen", fake_popen)
    env = {shared.CALLER_PROJECT_ENV: "sandbar",
           shared.CALLER_SURFACE_ENV: shared.CALLER_SURFACE_LANE_AGENT,
           "SANDBAR_SECRET": "must-not-pass"}
    proc = agent_runtime.exec_agent("c1", tmp_path, ["dsh"], env, None, "t")
    assert proc.mode == "docker"
    argv = calls["argv"]
    joined = " ".join(argv)
    assert "-e SANDBAR_CALLER_PROJECT=sandbar" in joined
    assert "-e SANDBAR_CALLER_SURFACE=lane-agent" in joined
    assert "SANDBAR_SECRET" not in joined  # 白名单外绝不透传（红线 C）


# ---------- _prepare_agent_spawn 注入（直接调用，test_t260916_22 同款形态） ----------

def _prepare(tmp_path, project):
    cwd = tmp_path / "ws"
    cwd.mkdir(exist_ok=True)
    arts = tmp_path / "artifacts"
    arts.mkdir(exist_ok=True)
    return agent_activities._prepare_agent_spawn(
        cwd=cwd, role="dev", kind="", ticket_id="t1", artifacts_dir=arts,
        tag="gen0", project=project)


def test_prepare_spawn_injects_identity(tmp_path, monkeypatch):
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    monkeypatch.delenv(shared.CALLER_SURFACE_ENV, raising=False)
    _, env = _prepare(tmp_path, "sandbar")
    assert env[shared.CALLER_PROJECT_ENV] == "sandbar"
    assert env[shared.CALLER_SURFACE_ENV] == shared.CALLER_SURFACE_LANE_AGENT


@pytest.mark.parametrize("bad_project", ["", "Sandbar", "sand bar", "../evil",
                                         "sandbar;rm", "项目"])
def test_prepare_spawn_malformed_project_not_injected(tmp_path, monkeypatch, bad_project):
    """形状非法/空 project 不注入（不在注入处静默纠偏——消费外部输入畸形用例族）。"""
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    monkeypatch.delenv(shared.CALLER_SURFACE_ENV, raising=False)
    _, env = _prepare(tmp_path, bad_project)
    assert shared.CALLER_PROJECT_ENV not in env
    assert shared.CALLER_SURFACE_ENV not in env


# ---------- identity_receipt：injected_by 尽力面标签 ----------

def _verdict(stamp="", override=False):
    return {"decision": "pass", "stamp": stamp, "notice": "", "override_used": override}


def test_receipt_env_with_lane_surface_label(monkeypatch):
    monkeypatch.setenv(shared.CALLER_SURFACE_ENV, shared.CALLER_SURFACE_LANE_AGENT)
    k = caller_gate.identity_receipt(_ident("sandbar", "declared", "env"), _verdict("sandbar"))
    assert k["injected_by"] == "lane-agent"


def test_receipt_env_without_surface_is_external(monkeypatch):
    """手工旁路设 env（无 SURFACE 标签）=external-env（标签非安全断言，R3/N2）。"""
    monkeypatch.delenv(shared.CALLER_SURFACE_ENV, raising=False)
    k = caller_gate.identity_receipt(_ident("sandbar", "declared", "env"), _verdict("sandbar"))
    assert k["injected_by"] == "external-env"


def test_receipt_bogus_surface_is_external(monkeypatch):
    monkeypatch.setenv(shared.CALLER_SURFACE_ENV, "something-else")
    k = caller_gate.identity_receipt(_ident("sandbar", "declared", "env"), _verdict("sandbar"))
    assert k["injected_by"] == "external-env"


@pytest.mark.parametrize("src", ["arg", "cwd", "none"])
def test_receipt_non_env_src_has_no_injected_by(monkeypatch, src):
    monkeypatch.setenv(shared.CALLER_SURFACE_ENV, shared.CALLER_SURFACE_LANE_AGENT)
    k = caller_gate.identity_receipt(_ident("sandbar", "declared", src), _verdict("sandbar"))
    assert "injected_by" not in k
