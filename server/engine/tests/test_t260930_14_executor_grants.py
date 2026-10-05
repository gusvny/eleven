# -*- coding: utf-8 -*-
"""t260930-14 执行器授权声明与引擎判定——单测。

覆盖（工单验收杆逐条）：
- 反锁杆：无授予的操作，执行器身份（channel=cwd）写=拒收，拒收点名声明文件与缺项；
- 正面杆：声明授予后同一写放行，回执带溯源键；
- 元权限反锁：manage-grants 恒拒收（声明缺席/畸形/夜间档均不解锁）；
- fail-closed：声明缺席/不可读/畸形/未知操作=拒收不静默；
- 零回归杆：arg/env/none 通道（泳道 agent=env 注入、宿主=显式或仓树内不推导）
  恒放行不设闸——lane agent / worker / 宿主控制台行为一个字节不变；
- 夜间档：时间盒内放行（溯源 night_tier）、过期拒收、畸形拒收；
- 审计：每次拒收与每次授予变更各一行；
- 声明写面：缺 by 拒收、执行器通道反锁拒收、写时回读校验、失败原文件逐字节不动；
- client 侧接线：_executor_grant_gate 仅 cwd 通道设闸 + 新拒收 kind
  （本组用例对 pre-fix 代码=红：executor_grants 模块与 kind 均不存在——反证杆）；
- ticket.py 通道透传：_caller_env 纯函数（畸形 caller/空 src 用例）。

全程零 Temporal/零网络/零 git；声明根经 SANDBAR_PROJECTS_DIR 注入临时目录。
"""
import asyncio
import json
import os

import pytest

import client as cl  # noqa: E402
import executor_grants as eg  # noqa: E402
import shared  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")


@pytest.fixture()
def ticket_mod(monkeypatch, tmp_path):
    """载入 server/tools/ticket.py（无包结构，importlib；日志指 tmp，不桩 _poc）。"""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("ticket_mod_t260930_14", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_t260930_14"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def grants_root(tmp_path, monkeypatch):
    """声明根注入（隔离台：SANDBAR_PROJECTS_DIR 指临时目录，零真实 ~/.sandbar）。"""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root


def _write_decl(root, key, doc):
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    (d / eg.DECL_FILE).write_text(json.dumps(doc), encoding="utf-8")


def _audit_rows(root, key):
    f = root / key / eg.AUDIT_FILE
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


SINK = []


def _sink(key, row):
    SINK.append((key, row))


# ---------- validate_declaration（形状校验单点，含畸形输入族） ----------

def test_validate_ok_minimal():
    doc, err = eg.validate_declaration({"version": 1, "grants": {"sign": True}})
    assert err is None and doc["grants"] == {"sign": True}


def test_validate_false_keys_pruned():
    doc, err = eg.validate_declaration({"version": 1, "grants": {"sign": False, "rerun": True}})
    assert err is None and doc["grants"] == {"rerun": True}


@pytest.mark.parametrize("doc", [
    {},                                       # 缺 version
    {"version": 2, "grants": {}},             # version 漂移
    {"version": 1, "grants": []},             # grants 非对象
    {"version": 1, "grants": {"fly": True}},  # 未知操作键
    {"version": 1, "grants": {"sign": "yes"}},  # 非 bool
    {"version": 1, "grants": {}, "night_tier": True},               # night_tier 非对象
    {"version": 1, "grants": {}, "night_tier": {"enabled": 1}},     # 缺 until
    {"version": 1, "grants": {}, "night_tier": {"enabled": True, "until": "soon"}},  # until 非数
    {"version": 1, "grants": {}, "night_tier": {"enabled": True, "until": 5, "note": 9}},  # note 非串
])
def test_validate_malformed_refused(grants_root, doc):
    _, err = eg.validate_declaration(doc)
    assert err and ("version" in err or "grants" in err or "night_tier" in err)


def test_validate_top_level_not_object():
    _, err = eg.validate_declaration([1, 2])
    assert err and "JSON object" in err


# ---------- load_declaration：absent / malformed / unreadable / ok ----------

def test_load_absent_is_absent_not_empty(grants_root):
    r = eg.load_declaration("sandbar")
    assert r["ok"] is False and r["kind"] == "absent" and r["declared"] is False
    assert r["file"].endswith(eg.DECL_FILE) and "executor-grants.json" in r["reason"]


def test_load_malformed_json(grants_root):
    d = grants_root / "sandbar"
    d.mkdir(parents=True)
    (d / eg.DECL_FILE).write_text("{not json", encoding="utf-8")
    r = eg.load_declaration("sandbar")
    assert r["ok"] is False and r["kind"] == "malformed" and "JSON" in r["reason"]


def test_load_unreadable(grants_root, monkeypatch):
    d = grants_root / "sandbar"
    d.mkdir(parents=True)
    (d / eg.DECL_FILE).write_text(json.dumps({"version": 1, "grants": {}}), encoding="utf-8")
    import builtins
    real_open = builtins.open

    def broken(path, *a, **k):
        if str(path).endswith(eg.DECL_FILE):
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **k)
    monkeypatch.setattr(builtins, "open", broken)
    r = eg.load_declaration("sandbar")
    assert r["ok"] is False and r["kind"] == "unreadable" and "PermissionError" in r["reason"]


def test_load_schema_error_is_malformed(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {"fly": True}})
    r = eg.load_declaration("sandbar")
    assert r["ok"] is False and r["kind"] == "malformed" and "fly" in r["reason"]


# ---------- judge_core 判定矩阵 ----------

def _full_decl(night=None):
    doc = {"version": 1, "grants": {op: True for op in eg.GRANT_OPS}}
    if night:
        doc["night_tier"] = night
    return doc


def test_non_executor_channels_never_gated(grants_root):
    """零回归杆（t261001-20 gen2 判据）：arg/env/none 通道无会话点名=恒放行
    （lane agent / 宿主 / 集成夹具 / light-lane 不设闸）；会话被声明点名的杆见
    test_t261001_20_executor_grant_declared_channel.py。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {}})
    for channel in ("arg", "env", "none", ""):
        v = eg.judge_core(channel, "sign", "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
        assert v["allowed"] is True and v.get("enforced") is False, channel
    v = eg.judge_core("env", "sign", "sandbar", eg.load_declaration, 1_000,
                      audit_sink=_sink, lane_surface=shared.CALLER_SURFACE_LANE_AGENT)
    assert v["allowed"] is True and v.get("enforced") is False


def test_reverse_lock_manage_grants(grants_root):
    """元权限反锁杆：声明全授予+夜间档在盒内，manage-grants 仍拒收。"""
    _write_decl(grants_root, "sandbar", _full_decl(night={"enabled": True, "until": 9_999}))
    v = eg.judge_core("cwd", "manage-grants", "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
    assert v["allowed"] is False and "meta-permission lock" in v["why"]
    assert any(r[1]["op"] == "manage-grants" for r in SINK)
    SINK.clear()


def test_refuse_names_declaration_and_item_and_how_to_grant(grants_root):
    """反锁杆（acceptance rod 1）：无授予=拒收，点名声明与缺项+授予路径。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {}})
    v = eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
    assert v["allowed"] is False
    assert eg.DECL_FILE in v["why"] and "grants.sign" in v["why"] and "Grants" in v["why"]
    SINK.clear()


def test_absent_declaration_refused_with_path(grants_root):
    v = eg.judge_core("cwd", "rerun", "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
    assert v["allowed"] is False and eg.DECL_FILE in v["why"] and "zero grants" in v["why"]
    SINK.clear()


def test_malformed_declaration_fail_closed(grants_root):
    d = grants_root / "sandbar"
    d.mkdir(parents=True)
    (d / eg.DECL_FILE).write_text("{bad", encoding="utf-8")
    v = eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
    assert v["allowed"] is False and "fail-closed" in v["why"]


@pytest.mark.parametrize("op,grant", [
    ("sign", "sign"), ("authorize", "sign"), ("rework", "send-back"),
    ("retry_qc", "rerun"), ("ticket-start", "open-ticket"),
    ("pause", "pause-resume"), ("resume", "pause-resume"),
    ("cancel", "cleanup"), ("ticket-cancel", "cleanup"),
])
def test_positive_grant_per_op(grants_root, op, grant):
    """正面杆：声明授予后放行，且 op→授予面映射正确。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {grant: True}})
    v = eg.judge_core("cwd", op, "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
    assert v["allowed"] is True and v["grant_op"] == grant
    assert "grants.%s" % grant in v["provenance"]["keys"][grant]


def test_host_only_ops_refused_for_executor(grants_root):
    _write_decl(grants_root, "sandbar", _full_decl())
    for op in ("update", "ruling", "ledger_rebuild"):
        v = eg.judge_core("cwd", op, "sandbar", eg.load_declaration, 1_000, audit_sink=_sink)
        assert v["allowed"] is False and op in v["why"]
    SINK.clear()


def test_night_tier_active_and_expired(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {},
                                         "night_tier": {"enabled": True, "until": 5_000}})
    v = eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 4_999, audit_sink=_sink)
    assert v["allowed"] is True and "night_tier" in v["provenance"]["keys"]["sign"]
    v2 = eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 5_001, audit_sink=_sink)
    assert v2["allowed"] is False and "grants.sign" in v2["why"]  # 过期=回到逐项声明，未授予照拒
    SINK.clear()


def test_refusal_writes_audit_row(grants_root):
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {}})
    eg.judge_core("cwd", "sign", "sandbar", eg.load_declaration, 1_000)  # 缺省 sink=真文件
    rows = _audit_rows(grants_root, "sandbar")
    assert len(rows) == 1 and rows[0]["action"] == "refuse" and rows[0]["op"] == "sign"


# ---------- save_declaration 写面 ----------

def test_save_requires_by(grants_root):
    r = eg.save_declaration("sandbar", {"sign": True}, "", 1_000)
    assert r["saved"] is False and "by" in r["reason"]
    assert not (grants_root / "sandbar" / eg.DECL_FILE).exists()


def test_save_reverse_lock_executor_channel(grants_root):
    r = eg.save_declaration("sandbar", {"sign": True}, "executor", 1_000, caller_channel="cwd")
    assert r["saved"] is False and "meta-permission lock" in r["reason"]
    assert not (grants_root / "sandbar" / eg.DECL_FILE).exists()


def test_save_roundtrip_and_audit(grants_root):
    r = eg.save_declaration("sandbar", {"sign": True}, "host", 1_000, audit_sink=_sink)
    assert r["saved"] is True
    back = json.loads((grants_root / "sandbar" / eg.DECL_FILE).read_text(encoding="utf-8"))
    assert back["grants"] == {"sign": True} and back["updated_by"] == "host"
    r2 = eg.save_declaration("sandbar", {"sign": True, "rerun": True}, "host", 2_000, audit_sink=_sink)
    assert r2["saved"] is True
    assert SINK[-1][1]["action"] == "grant-change"
    assert SINK[-1][1]["from"] == {"sign": True} and SINK[-1][1]["to"] == {"sign": True, "rerun": True}
    SINK.clear()


def test_save_invalid_leaves_file_byte_identical(grants_root):
    eg.save_declaration("sandbar", {"sign": True}, "host", 1_000)
    before = (grants_root / "sandbar" / eg.DECL_FILE).read_bytes()
    r = eg.save_declaration("sandbar", {"fly": True}, "host", 2_000)
    assert r["saved"] is False and "fly" in r["reason"]
    assert (grants_root / "sandbar" / eg.DECL_FILE).read_bytes() == before


def test_save_night_tier_caps_note(grants_root):
    r = eg.save_declaration("sandbar", {}, "host", 1_000,
                            night_tier={"enabled": True, "until": 9_000, "note": "n" * 900})
    assert r["saved"] is True and len(r["resolved"]["night_tier"]["note"]) == 500


# ---------- _poc 桩兼容契约（t260922-10 场景桩只认三参+裸串 caller——gen1 集成闸实录） ----------

def test_poc_signature_stub_compatible(ticket_mod):
    """_poc 形状锁：(subcmd, payload, caller=None) 三参——场景/registry 桩按此替换；
    caller 一律裸串（推导出处走 _PENDING_CALLER_SRC 暂存，不加形参）。"""
    import inspect
    sig = inspect.signature(ticket_mod._poc)
    assert list(sig.parameters) == ["subcmd", "payload", "caller"]
    assert sig.parameters["caller"].default is None


def test_write_op_poc_stub_receives_plain_string_caller(ticket_mod, monkeypatch, tmp_path):
    """进程内桩重放形：_write_op_poc 调 _poc 时 caller=裸串 key（不是元组），
    无额外 kwargs——stubs str(caller) 注 env 仍是合法项目 key。"""
    calls = []

    def fake_poc(subcmd, payload, caller=None):
        calls.append((subcmd, payload, caller))
        return {"ok": True, "result": {}}

    monkeypatch.setattr(ticket_mod, "_poc", fake_poc)
    ticket_mod._write_op_poc("ticket-cancel", {"op": "cancel"}, {"caller_project": "proj-a"})
    assert calls and calls[0][2] == "proj-a", calls
    # 暂存槽被清零：下一次无 caller 的 _poc 不残留出处
    assert ticket_mod._PENDING_CALLER_SRC == ""


def test_write_op_poc_real_poc_injects_src_env(ticket_mod, monkeypatch):
    """真 _poc 路径：_write_op_poc 暂存的出处进子进程 env（不 spawn——在 spawn 前
    断言 env 构造）。"""
    captured = {}
    real_run = ticket_mod.subprocess.run

    def fake_run(cmd, **kw):
        captured["env"] = kw.get("env") or {}
        class P:
            stdout = '{"ok": true, "result": {}}'
            stderr = ""
        return P()

    monkeypatch.setattr(ticket_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(ticket_mod, "TEMP_PY", "python3")
    ticket_mod._write_op_poc("ticket-cancel", {"op": "cancel", "who": "w", "reason": "r", "id": "t1"},
                             {"caller_project": "proj-a"})
    env = captured["env"]
    assert env[shared.CALLER_PROJECT_ENV] == "proj-a"
    assert env[shared.CALLER_IDENTITY_SRC_ENV] == "arg"


# ---------- client 侧接线（pre-fix 红：模块/kind 均不存在） ----------

def test_client_gate_kind_and_helper_exist():
    """反证杆：pre-fix 代码无此 kind/无此闸——本组用例对旧代码必然红。"""
    assert cl.KIND_EXECUTOR_GRANT_REFUSED == "executor_grant_refused"
    assert callable(cl._executor_grant_gate)
    assert eg.EXECUTOR_CHANNEL == "cwd"
    assert "sign" in eg.GRANT_OPS and "send-back" in eg.GRANT_OPS


def test_client_gate_only_cwd_channel(grants_root, monkeypatch):
    """通道端到端（t261001-20 gen2 判据）：arg/env-external 无会话点名=放行不设闸
    （集成夹具/light-lane 零回归）；cwd 通道维持 t260930-14 原语义：未授予=结构化
    拒收（kind=executor_grant_refused），授予后放行并带溯源观测键；会话点名受闸杆
    见 test_t261001_20_executor_grant_declared_channel.py。"""
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {}})
    monkeypatch.delenv(shared.CALLER_SURFACE_ENV, raising=False)
    # 声明通道无会话点名：闸不设（err=None 且不带执行器键）
    for channel in ("arg", "env"):
        g = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": channel, "channel_src": channel},
                                    "sign", "sandbar"))
        assert g["err"] is None and g["keys"] == {}, channel
    # 未声明：闸不设
    for channel in ("none", ""):
        g = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": channel, "channel_src": channel},
                                    "sign", "sandbar"))
        assert g["err"] is None and g["keys"] == {}, channel
    # lane-agent surface：闸不设（零回归红线）
    monkeypatch.setenv(shared.CALLER_SURFACE_ENV, shared.CALLER_SURFACE_LANE_AGENT)
    g = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": "env", "channel_src": "env"},
                                "sign", "sandbar"))
    assert g["err"] is None and g["keys"] == {}
    monkeypatch.delenv(shared.CALLER_SURFACE_ENV)
    # cwd 通道：未授予=结构化拒收（点名 kind）
    g = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": "cwd", "channel_src": "cwd"},
                                "sign", "sandbar"))
    assert g["err"] is not None and g["err"]["kind"] == "executor_grant_refused"
    assert eg.DECL_FILE in g["err"]["error"] and "grants.sign" in g["err"]["error"]
    # cwd 通道：授予后放行并带溯源观测键
    _write_decl(grants_root, "sandbar", {"version": 1, "grants": {"sign": True}})
    g2 = asyncio.run(cl._executor_grant_gate({"value": "sandbar", "src": "cwd", "channel_src": "cwd"},
                                 "sign", "sandbar"))
    assert g2["err"] is None
    assert g2["keys"]["executor_grant_op"] == "sign"
    assert "grants.sign" in g2["keys"]["executor_grant_source"]
    assert g2["keys"]["executor_channel"] == "cwd"


def test_client_channel_env_beats_resolved_src(grants_root, monkeypatch):
    """通道辨认：SANDBAR_CALLER_IDENTITY_SRC 在场优先（ticket.py 透传 cwd 出处），
    缺席回落身份解析 src；身份 dict 本身不被污染（identity 契约不变）。"""
    ident = {"value": "sandbar", "src": "env", "identity_class": "declared"}
    monkeypatch.setenv(shared.CALLER_IDENTITY_SRC_ENV, "cwd")
    assert cl._executor_channel(ident) == "cwd"
    monkeypatch.delenv(shared.CALLER_IDENTITY_SRC_ENV)
    assert cl._executor_channel(ident) == "env"
    assert "channel_src" not in ident


# ---------- ticket.py 通道透传（纯函数） ----------

def test_ticket_caller_env_injects_identity_and_src(ticket_mod):
    env = ticket_mod._caller_env("sandbar", "cwd")
    assert env[shared.CALLER_PROJECT_ENV] == "sandbar"
    assert env[shared.CALLER_IDENTITY_SRC_ENV] == "cwd"


def test_ticket_caller_env_empty_caller_injects_nothing(ticket_mod):
    assert ticket_mod._caller_env("") == {}
    assert ticket_mod._caller_env(None) == {}


def test_ticket_caller_env_defaults_src_to_env(ticket_mod):
    env = ticket_mod._caller_env("sandbar")
    assert env[shared.CALLER_IDENTITY_SRC_ENV] == "env"


def test_ticket_resolve_caller_returns_pair(ticket_mod, tmp_path, monkeypatch):
    """显式参数通道 → ('<key>', 'arg')；无任何身份 → ('', 'cwd' 或 '')。"""
    monkeypatch.chdir(tmp_path)
    k, src = ticket_mod._resolve_caller({"caller_project": "sandbar"})
    assert (k, src) == ("sandbar", "arg")


@pytest.fixture(autouse=True)
def _engine_submit_stub(monkeypatch):
    """t261005-12: gate recording now runs in the ENGINE process — install the
    in-process engine stand-in per test (production perform_delivery dispatch,
    rows land via the real record_from_gate; zero Temporal). Single source:
    test_t261005_12_gate_engine_recording.install_fake_engine."""
    from test_t261005_12_gate_engine_recording import install_fake_engine
    install_fake_engine(monkeypatch)
