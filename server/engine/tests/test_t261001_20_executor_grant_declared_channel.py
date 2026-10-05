# -*- coding: utf-8 -*-
"""t261001-20 执行器授权闸判据重定（受信会话身份）——单测。

gen0 教训（集测 6 红实证）：按「声明了 caller_project」设闸会把集成场景夹具项目
（seedws/proj-a 的 create/cancel）与 light-lane 规范调用整档误闸——通道形状≠执行器
身份。gen2 判据单点=executor_grants.is_executor_channel：受闸只认受信会话身份——
  a) cwd 推导（watchdog 代建执行器会话；零授予=拒收，t260930-14 原语义不变）；
  b) 声明点名：调用方会话 id（env DSH_SESSION_ID > DSH_HEADLESS_SESSION）被项目
     声明 executor_sessions 点名——宿主在面板点名「谁算本项目执行器」，
     会话 id 由 dsh 工具链注入（调用方 prompt 改不了注入链）。
豁免（零回归）：lane-agent 注入（env+surface）、未声明、声明了 caller_project 但
会话未被点名（夹具/light-lane/普通 CLI）。

本组行为断言：
- 判据点全矩阵（含畸形 lane surface fail-closed、会话读口优先级）；
- 声明点名会话 + 零授予 = 拒收 + 审计行（工单原始缺陷在此判据下收口）；
- 夹具形调用（arg 声明 + 无点名会话）create/cancel 一律不闸（集测回归杆）；
- cwd 通道零授予=拒收（t260930-14 原语义零回归）；
- 声明 schema 新字段 executor_sessions（形状族含畸形输入；与面板 TS 侧镜像）；
- judge() 端到端（surface/会话 id 随进程 env 消费、声明单次装载）；
- client 闸端到端（夹具形放行零键 / 点名会话结构化拒收 / 授予后带溯源键）；
- save_declaration 反锁=执行器身份（cwd 或被点名会话），普通声明通道不背反锁；
- 元权限反锁只对执行器身份生效。

全程零 Temporal/零网络/零 git；声明根经 SANDBAR_PROJECTS_DIR 注入临时目录。
"""
import asyncio
import json
import os

import pytest

import client as cl  # noqa: E402
import executor_grants as eg  # noqa: E402
import shared  # noqa: E402

SESSION_ENV = "DSH_SESSION_ID"


@pytest.fixture
def grants_root(tmp_path, monkeypatch):
    """声明根注入（隔离台：SANDBAR_PROJECTS_DIR 指临时目录，零真实 ~/.sandbar）。"""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def _clean_caller_env(monkeypatch):
    """逐用例清场：lane-agent 标签与会话 id 只在显式设定的用例内生效。"""
    monkeypatch.delenv(shared.CALLER_SURFACE_ENV, raising=False)
    for env_name in eg.CALLER_SESSION_ENVS:
        monkeypatch.delenv(env_name, raising=False)


def _write_decl(root, key, doc):
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    (d / eg.DECL_FILE).write_text(json.dumps(doc), encoding="utf-8")


def _audit_rows(root, key):
    f = root / key / eg.AUDIT_FILE
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------- 判据单点：is_executor_channel ----------

def test_cwd_channel_always_gated():
    """cwd 推导恒受闸（t260930-14 原语义零回归，与声明/会话无关）。"""
    assert eg.is_executor_channel("cwd") is True
    assert eg.is_executor_channel("cwd", "", (), "") is True


def test_declared_channel_gated_only_when_session_declared():
    """声明通道：仅当会话 id 被点名才受闸——未点名=豁免（夹具/light-lane 零回归）。"""
    assert eg.is_executor_channel("arg", "", ("s-1", "s-2"), "s-1") is True
    assert eg.is_executor_channel("env", "external-env", ("s-1",), "s-1") is True
    assert eg.is_executor_channel("arg", "", ("s-1",), "s-9") is False
    assert eg.is_executor_channel("arg", "", ("s-1",), "") is False
    assert eg.is_executor_channel("arg", "", (), "s-1") is False
    assert eg.is_executor_channel("env", "", None, "s-1") is False


def test_exempt_channels_zero_regression():
    """lane-agent 注入与未声明=豁免（零回归红线：泳道 agent / 宿主控制台）。"""
    assert eg.is_executor_channel("env", shared.CALLER_SURFACE_LANE_AGENT,
                                  ("s-1",), "s-1") is False
    assert eg.is_executor_channel("none") is False
    assert eg.is_executor_channel("") is False
    assert eg.is_executor_channel(None) is False


@pytest.mark.parametrize("surface", [
    "",                                  # env 注入但无标签=external-env
    "Lane-Agent",                        # 大小写漂移：不当 lane-agent（不白拿豁免）
    "lane-agent\x00",                    # 杂值/畸形：不当 lane-agent
    "something-else",                    # t260925_08 既有杂值族
])
def test_malformed_lane_surface_treated_as_external(surface):
    assert eg.is_executor_channel("env", surface, ("s-1",), "s-1") is True


def test_lane_surface_surrounding_blank_still_matches_spawn_value():
    """spawn 链写精确值；strip 后全值比对（identity_receipt 同口径）。"""
    assert eg.is_executor_channel("env", " lane-agent ", ("s-1",), "s-1") is False


def test_caller_session_id_read_order(monkeypatch):
    """会话 id 读口：DSH_SESSION_ID > DSH_HEADLESS_SESSION；都缺席=空串。"""
    monkeypatch.setenv("DSH_SESSION_ID", " sess-a ")
    monkeypatch.setenv("DSH_HEADLESS_SESSION", "sess-b")
    assert eg.caller_session_id() == "sess-a"
    monkeypatch.delenv("DSH_SESSION_ID")
    assert eg.caller_session_id() == "sess-b"
    monkeypatch.delenv("DSH_HEADLESS_SESSION")
    assert eg.caller_session_id() == ""


# ---------- 声明 schema：executor_sessions（Python 侧） ----------

def test_validate_sessions_ok_normalized():
    doc, err = eg.validate_declaration({"version": 1, "grants": {},
                                        "executor_sessions": [" s-1 ", "s-1", "s-2"]})
    assert err is None and doc["executor_sessions"] == ["s-1", "s-2"]  # strip+去重保序


def test_validate_sessions_absent_omitted():
    doc, err = eg.validate_declaration({"version": 1, "grants": {"sign": True}})
    assert err is None and "executor_sessions" not in doc


@pytest.mark.parametrize("sessions", [
    "s-1",                 # 非数组
    [" "],                 # 空白项
    [1],                   # 非字符串项
    ["x" * 129],           # 超 128 字符
    ["s-%d" % i for i in range(9)],  # 超 8 个
])
def test_validate_sessions_malformed_refused(sessions):
    _, err = eg.validate_declaration({"version": 1, "grants": {},
                                      "executor_sessions": sessions})
    assert err and "executor_sessions" in err


def test_validate_empty_sessions_list_pruned():
    doc, err = eg.validate_declaration({"version": 1, "grants": {}, "executor_sessions": []})
    assert err is None and "executor_sessions" not in doc


def test_load_declaration_returns_sessions(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["s-1"]})
    r = eg.load_declaration("sandbar")
    assert r["ok"] is True and r["executor_sessions"] == ["s-1"]


# ---------- 判定核：会话点名受闸 / 夹具形调用豁免 ----------

def test_declared_executor_session_zero_grants_refused_and_audited(grants_root):
    """工单原始缺陷在此判据下收口：被点名的执行器会话（即使走 arg 声明通道）
    零授予=拒收+审计行——「谁算执行器」由宿主点名，自设 caller_project 不构成身份。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["session-825896f9"]})
    v = eg.judge_core("arg", "sign", "sandbar", eg.load_declaration, 1_000,
                      declared_sessions=("session-825896f9",), caller_session="session-825896f9")
    assert v["allowed"] is False and v["grant_op"] == "sign"
    assert eg.DECL_FILE in v["why"] and "grants.sign" in v["why"]
    rows = _audit_rows(grants_root, "sandbar")
    assert len(rows) == 1 and rows[0]["action"] == "refuse" and rows[0]["op"] == "sign"


def test_declared_executor_session_with_grant_passes(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {"sign": True},
                                         "executor_sessions": ["s-1"]})
    v = eg.judge_core("arg", "sign", "sandbar", eg.load_declaration, 1_000,
                      declared_sessions=("s-1",), caller_session="s-1")
    assert v["allowed"] is True and v["enforced"] is True
    assert "grants.sign" in v["provenance"]["keys"]["sign"]


def test_fixture_like_calls_never_gated(grants_root):
    """集测回归杆（gen0 6 红的形状）：夹具项目 create/cancel（arg 声明、无点名会话）
    在零授予/声明缺席/畸形声明下全部不闸、零审计行。"""
    for setup in ("absent", "zero-grants", "malformed"):
        key = "proj-a"
        d = grants_root / key
        if d.exists():
            (d / eg.DECL_FILE).unlink()
        if setup == "zero-grants":
            _write_decl(grants_root, key, {"version": 1, "grants": {}})
        elif setup == "malformed":
            d.mkdir(parents=True, exist_ok=True)
            (d / eg.DECL_FILE).write_text("{bad json", encoding="utf-8")
        for op in ("ticket-start", "cancel"):
            v = eg.judge_core("arg", op, key, eg.load_declaration, 1_000)
            assert v["allowed"] is True and v["enforced"] is False, (setup, op)
        assert _audit_rows(grants_root, key) == []


def test_cwd_channel_zero_grants_refused(grants_root):
    """零授予执行器会话（cwd 通道）=拒收（t260930-14 原语义，rework 回归杆②）。"""
    v = eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 1_000)
    assert v["allowed"] is False and "zero grants" in v["why"]


def test_cwd_channel_with_grant_passes(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {"sign": True}})
    v = eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 1_000)
    assert v["allowed"] is True and v["enforced"] is True


def test_unlisted_session_same_project_not_gated(grants_root):
    """同项目里未被点名的另一会话：豁免（点名=白名单语义，不是黑名单）。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["s-1"]})
    v = eg.judge_core("arg", "sign", "sandbar", eg.load_declaration, 1_000,
                      declared_sessions=("s-1",), caller_session="s-rogue")
    assert v["allowed"] is True and v["enforced"] is False


def test_lane_agent_channel_never_gated_even_if_session_listed(grants_root):
    """零回归红线：lane-agent 注入优先豁免——spawn 链身份不因声明点名被误闸。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["s-1"]})
    v = eg.judge_core("env", "sign", "sandbar", eg.load_declaration, 1_000,
                      lane_surface=shared.CALLER_SURFACE_LANE_AGENT,
                      declared_sessions=("s-1",), caller_session="s-1")
    assert v["allowed"] is True and v["enforced"] is False
    assert _audit_rows(grants_root, "sandbar") == []


# ---------- judge() 端到端（env 消费 + 声明单次装载） ----------

def test_judge_end_to_end_session_scoped(grants_root, monkeypatch):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["sess-exec"]})
    monkeypatch.setenv(shared.CALLER_IDENTITY_SRC_ENV, "arg")
    # 未点名会话（夹具形）：不闸
    v1 = eg.judge({"value": "sandbar", "src": "arg", "channel_src": "arg"},
                  "sign", "sandbar", now_ms=1_000)
    assert v1["allowed"] is True and v1["enforced"] is False
    # 被点名会话：受闸
    monkeypatch.setenv("DSH_SESSION_ID", "sess-exec")
    v2 = eg.judge({"value": "sandbar", "src": "arg", "channel_src": "arg"},
                  "sign", "sandbar", now_ms=1_000)
    assert v2["allowed"] is False
    rows = _audit_rows(grants_root, "sandbar")
    assert len(rows) == 1 and rows[0]["action"] == "refuse"


def test_judge_cwd_end_to_end_unchanged(grants_root, monkeypatch):
    monkeypatch.setenv(shared.CALLER_IDENTITY_SRC_ENV, "cwd")
    v = eg.judge({"value": "sandbar", "src": "cwd", "channel_src": "cwd"},
                 "sign", "sandbar", now_ms=1_000)
    assert v["allowed"] is False  # 零授予执行器会话照拒


# ---------- client 闸端到端 ----------

def test_client_gate_session_scoped(grants_root, monkeypatch):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["sess-exec"]})
    # 夹具形（arg + 未点名会话）：放行零键
    g = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": "arg", "channel_src": "arg"},
                                "sign", "sandbar"))
    assert g["err"] is None and g["keys"] == {}
    # 点名会话：结构化拒收
    monkeypatch.setenv("DSH_SESSION_ID", "sess-exec")
    g2 = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": "arg", "channel_src": "arg"},
                                 "sign", "sandbar"))
    assert g2["err"] is not None and g2["err"]["kind"] == "executor_grant_refused"
    assert not g2["keys"]
    # 授予后放行并带溯源键
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {"sign": True},
                                         "executor_sessions": ["sess-exec"]})
    g3 = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": "arg", "channel_src": "arg"},
                                 "sign", "sandbar"))
    assert g3["err"] is None
    assert g3["keys"]["executor_grant_op"] == "sign"
    assert "grants.sign" in g3["keys"]["executor_grant_source"]


# ---------- 元权限反锁（只对执行器身份） ----------

def test_meta_op_locked_for_executor_identities(grants_root):
    """manage-grants 对 cwd 通道与被点名会话恒拒收（先于声明读取）。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {"sign": True},
                                         "executor_sessions": ["s-1"]})
    v1 = eg.judge_core("cwd", eg.META_OP, "sandbar", eg.load_declaration, 1_000)
    assert v1["allowed"] is False and "meta-permission lock" in v1["why"]
    v2 = eg.judge_core("arg", eg.META_OP, "sandbar", eg.load_declaration, 1_000,
                       declared_sessions=("s-1",), caller_session="s-1")
    assert v2["allowed"] is False and "meta-permission lock" in v2["why"]


def test_meta_op_not_locked_for_non_executor_callers(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {}})
    v = eg.judge_core("arg", eg.META_OP, "sandbar", eg.load_declaration, 1_000)
    assert v["allowed"] is True and v["enforced"] is False


# ---------- save_declaration 反锁（执行器身份，非通道形状） ----------

def test_save_declaration_locked_for_executor_identities(grants_root, monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ID", "s-1")
    # cwd 通道：拒收
    r1 = eg.save_declaration("sandbar", {"sign": True}, "executor", 1_000, caller_channel="cwd")
    assert r1["saved"] is False and "meta-permission lock" in r1["reason"]
    # 被点名会话（arg 通道）：拒收
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "executor_sessions": ["s-1"]})
    r2 = eg.save_declaration("sandbar", {"sign": True}, "executor", 1_000, caller_channel="arg")
    assert r2["saved"] is False and "meta-permission lock" in r2["reason"]
    # 盘上只有测试自写的点名声明，反锁未落新文件（mtime/内容由 saved=False 保证）


def test_save_declaration_allows_non_executor_callers(grants_root, monkeypatch):
    """未被点名的声明通道（宿主 CLI/集成面）可写声明——gen0 的整档反锁收回。"""
    r = eg.save_declaration("sandbar", {"sign": True}, "host", 1_000, caller_channel="arg")
    assert r["saved"] is True and r["resolved"]["grants"] == {"sign": True}


def test_save_declaration_roundtrip_keeps_sessions(grants_root):
    """声明写面保真：executor_sessions 写读回环（宿主点名的落盘通道）。"""
    r = eg.save_declaration("sandbar", {"sign": True}, "host", 1_000,
                            executor_sessions=["s-1", "s-2"])
    assert r["saved"] is True and r["resolved"]["executor_sessions"] == ["s-1", "s-2"]
    back = eg.load_declaration("sandbar")
    assert back["executor_sessions"] == ["s-1", "s-2"]


def test_save_declaration_sessions_malformed_refused(grants_root):
    r = eg.save_declaration("sandbar", {"sign": True}, "host", 1_000,
                            executor_sessions=["x" * 200])
    assert r["saved"] is False and "executor_sessions" in r["reason"]
    assert not (grants_root / "sandbar" / eg.DECL_FILE).exists()


# ---------- 工具/夹具路径零接触（rework 回归杆：engine_ops worker start 不受闸） ----------

def test_engine_ops_worker_start_path_is_gate_free():
    """gen2→gen3 集测红点误判面（sc_engine_ops_offline L6）：engine_ops（worker
    start/restart 换手）整条路径不经过工单写闸——工具直连 Temporal/进程面，与
    executor_grants 零耦合。本杆锁：engine_ops 模块源不引用执行器闸任何入口；
    未来有人把闸接进工具路径会在此点名变红。"""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                            "server", "tools", "engine_ops.py"), encoding="utf-8").read()
    for marker in ("executor_grants", "_executor_grant_gate", "KIND_EXECUTOR_GRANT_REFUSED",
                   "is_executor_channel"):
        assert marker not in src, marker
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "server", "tools", "engine_ops.py")
    spec = importlib.util.spec_from_file_location("t20_probe_engine_ops", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 零闸依赖下可独立加载（不炸即过）
    assert callable(mod.cmd_workers)


def test_fixture_calls_not_gated_under_harness_session_env(grants_root):
    """端到端回归杆：harness 会话 env（DSH_SESSION_ID 在场、未被点名）下的夹具形
    create/cancel/sign 一律不闸——闸只对「cwd 通道」与「被点名会话」生效。"""
    _write_decl(grants_root, "proj-a", {"version": 1, "grants": {},
                                        "executor_sessions": ["some-other-session"]})
    monkey_env_back = os.environ.get("DSH_SESSION_ID")
    os.environ["DSH_SESSION_ID"] = "integration-harness-session"
    try:
        for channel in ("arg", "env"):
            for op in ("ticket-start", "cancel", "sign", "pause"):
                v = eg.judge_core(channel, op, "proj-a", eg.load_declaration, 1_000,
                                  declared_sessions=("some-other-session",),
                                  caller_session="integration-harness-session")
                assert v["allowed"] is True and v["enforced"] is False, (channel, op)
        assert _audit_rows(grants_root, "proj-a") == []
    finally:
        if monkey_env_back is None:
            os.environ.pop("DSH_SESSION_ID", None)
        else:
            os.environ["DSH_SESSION_ID"] = monkey_env_back


@pytest.fixture(autouse=True)
def _engine_submit_stub(monkeypatch):
    """t261005-12: gate recording now runs in the ENGINE process — install the
    in-process engine stand-in per test (production perform_delivery dispatch,
    rows land via the real record_from_gate; zero Temporal). Single source:
    test_t261005_12_gate_engine_recording.install_fake_engine."""
    from test_t261005_12_gate_engine_recording import install_fake_engine
    install_fake_engine(monkeypatch)
