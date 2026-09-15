"""t260912-03 CLI/可查面单测（ticket.py op=authorize 包装、list/show 可读面、client.py 归一）。

覆盖（方案 S5 + review RC6/RC9）：
  - ticket.py _authorize：payload 形状（经 sign 信号面／审计面）、scope 双形、参数校验各腿；
  - ticket.py _list：authz_active 透传（缺键补 0，不炸）；
  - ticket.py _show/_authz_view：全量条目 + 逐条状态（生效中/已过期）+ uses 计数；
  - client.py normalize_authorize_args：ISO8601/epoch/数字串/畸形/缺失各腿；
  - client.py _row_from_meta：authz_active 只数生效中（过期/坏 kind 不计）。

Temporal 面一律桩掉 `_poc`/`_v2_query`，零网络零 Temporal。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "server" / "engine"))

import client as client_mod  # noqa: E402

TICKET_PY = REPO / "server" / "tools" / "ticket.py"
NOW = 4_000_000_000   # 远未来（避免用真当前时间做「生效中」判定）


@pytest.fixture()
def tk(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ticket_mod_authz_ut", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_authz_ut"] = mod
    monkeypatch.setenv("SANBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.setenv("SANBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.delenv("SANBAR_CLIENT_ENTRY", raising=False)
    monkeypatch.delenv("SANBAR_CLIENT_CALL_ID", raising=False)
    spec.loader.exec_module(mod)
    calls = []

    def fake_poc(subcmd, payload, caller=None):  # t260915-12：+caller 身份注入形参
        calls.append((subcmd, payload))
        return {"ok": True, "result": {"delivered": True}}

    monkeypatch.setattr(mod, "_poc", fake_poc)
    mod._calls = calls
    return mod


# ---------- ticket.py op=authorize ----------

def test_authorize_payload_shape(tk):
    r = tk.run({"op": "authorize", "id": "t1", "by": "宿主",
                "kind": "protected_path", "scope": ["integration/baselines"],
                "reason": "修期望值", "expires": NOW + 3600})
    assert r["delivered"] is True
    subcmd, payload = tk._calls[0]
    assert subcmd == "ticket"
    assert payload["op"] == "authorize" and payload["ticket_id"] == "t1"
    assert payload["input"] == {"who": "宿主", "kind": "protected_path",
                               "scope": ["integration/baselines"],
                               "reason": "修期望值", "expires": NOW + 3600}


def test_authorize_scope_string_and_who_alias(tk):
    tk.run({"op": "authorize", "id": "t1", "who": "张三",
            "kind": "protected_path", "scope": "verify.yaml, docs/design",
            "reason": "r", "expires": "2026-09-20T00:00:00+08:00"})
    _s, payload = tk._calls[0]
    assert payload["input"]["who"] == "张三"
    assert payload["input"]["scope"] == ["verify.yaml", "docs/design"]
    assert payload["input"]["expires"] == "2026-09-20T00:00:00+08:00"  # 归一在 client.py


@pytest.mark.parametrize("bad,frag", [
    ({"op": "authorize", "kind": "protected_path", "scope": ["x"], "reason": "r",
      "expires": 1, "by": "宿主"}, "需要 id"),
    ({"op": "authorize", "id": "t1", "kind": "protected_path", "scope": ["x"],
      "reason": "r", "expires": 1}, "需要 by|who"),
    ({"op": "authorize", "id": "t1", "by": "宿主", "kind": "bogus", "scope": ["x"],
      "reason": "r", "expires": 1}, "kind 只收"),
    ({"op": "authorize", "id": "t1", "by": "宿主", "kind": "protected_path",
      "scope": [], "reason": "r", "expires": 1}, "需要 scope"),
    ({"op": "authorize", "id": "t1", "by": "宿主", "kind": "protected_path",
      "scope": ["x"], "reason": "r"}, "需要 expires"),
    ({"op": "authorize", "id": "t1", "by": "宿主", "kind": "protected_path",
      "scope": ["x"], "expires": 1}, "需要 reason"),
])
def test_authorize_rejects_malformed(tk, bad, frag):
    with pytest.raises(ValueError) as ei:
        tk.run(bad)
    assert frag in str(ei.value)
    assert tk._calls == []          # 拒收在包装层，不发信号


def test_authorize_dispatch_registered(tk):
    assert tk.run({"op": "authorize", "id": "t1", "by": "宿主",
                   "kind": "arbitration_verdict", "scope": ["t1"],
                   "reason": "接受判决", "expires": NOW + 60})["delivered"] is True
    assert "authorize" in tk._TICKET_CLI_USAGE


# ---------- 列表可读面 ----------

def test_list_passes_through_authz_active(tk, monkeypatch):
    rows = [{"id": "t1", "project": "", "epic": "", "role": "developer",
             "status": "dispatched", "title": "x", "workflow": "", "proposal_id": "",
             "stage": "implement", "stage_state": "blocked", "engine": "v2",
             "handoff_count": 2, "pending_count": 0, "worktree": "", "workspace": None,
             "created": {"seconds": NOW}, "updated_ts": NOW, "close_ts": 0,
             "authz_active": 2},
            {"id": "t2", "project": "", "epic": "", "role": "developer",
             "status": "dispatched", "title": "y", "workflow": "", "proposal_id": "",
             "stage": "implement", "stage_state": "running", "engine": "v2",
             "handoff_count": 0, "pending_count": 0, "worktree": "", "workspace": None,
             "created": {"seconds": NOW}, "updated_ts": NOW, "close_ts": 0}]
    monkeypatch.setattr(tk, "_poc",
                        lambda s, p: {"ok": True, "result": {"tickets": rows}})
    out = tk.run({"op": "list"})
    by_id = {r["id"]: r for r in out["tickets"]}
    assert by_id["t1"]["authz_active"] == 2
    assert by_id["t2"]["authz_active"] == 0        # 老引擎行缺键 → 补 0 不炸


def test_list_created_non_dict_tolerated(tk, monkeypatch):
    rows = [{"id": "t1", "created": NOW, "updated_ts": NOW, "handoff_count": 0,
             "pending_count": 0}]
    monkeypatch.setattr(tk, "_poc",
                        lambda s, p: {"ok": True, "result": {"tickets": rows}})
    out = tk.run({"op": "list"})
    assert out["tickets"][0]["authz_active"] == 0


# ---------- show 可读面 ----------

def test_authz_view_status_and_uses(tk):
    _now = int(__import__("time").time())          # 状态口径=读取时刻，用真当前时间造两态
    items = [
        {"kind": "protected_path", "who": "宿主", "scope": ["integration/baselines"],
         "reason": "r", "issued": _now - 10, "expires": _now + 100,
         "uses": [{"ts": _now, "stage": "implement", "detail": "x"}]},
        {"kind": "arbitration_verdict", "who": "宿主", "scope": ["t1"], "reason": "接受判决",
         "issued": _now - 1000, "expires": _now - 1, "uses": []},
        "malformed",
    ]
    # 真路径形状（260912 仲裁实证）：_v2_query[0]=扁平 ticket face，authorizations 在顶层
    view = tk._authz_view({"authorizations": items})
    assert [v["status"] for v in view] == ["生效中", "已过期"]
    assert view[0]["used_count"] == 1 and view[0]["scope"] == ["integration/baselines"]
    assert view[1]["used_count"] == 0
    # 嵌套形状兼容腿（snapshot 形状）
    view2 = tk._authz_view({"meta": {"authorizations": items}})
    assert [v["status"] for v in view2] == ["生效中", "已过期"]
    # 老票无该键 → 不加展示层键（两种形状都判 None）
    assert tk._authz_view({}) is None
    assert tk._authz_view({"meta": {}}) is None


def test_show_annotates_without_shape_change(tk, monkeypatch):
    # 真 _v2_query 契约形状：返回 (meta扁平face, snapshot)，meta 顶层带 authorizations
    meta = {"id": "t1", "status": "RUNNING", "authorizations": [
        {"kind": "protected_path", "who": "宿主", "scope": ["verify.yaml"], "reason": "r",
         "issued": NOW, "expires": NOW + 100, "uses": []}]}
    monkeypatch.setattr(tk, "_v2_query", lambda tid: (meta, {"stage": "implement"}))
    out = tk.run({"op": "show", "id": "t1"})
    assert out["authz_active"] == 1
    assert out["authz"][0]["who"] == "宿主" and out["authz"][0]["status"] == "生效中"
    assert out["authorizations"][0]["who"] == "宿主"          # 真源原样保留（扁平顶层）
    assert out["id"] == "t1"                                   # 既有 show 面不被改形


# ---------- client.py 归一与行计数 ----------

def test_normalize_authorize_args_forms():
    auth, err = client_mod.normalize_authorize_args({"input": {
        "kind": "protected_path", "who": "宿主", "scope": ["a", " b "],
        "reason": "r", "expires": "2026-09-20T00:00:00+08:00"}})
    assert err == "" and auth.kind == "protected_path"
    assert auth.scope == ["a", "b"]                  # 条目 strip
    assert auth.expires == 1789833600                # ISO → epoch
    auth2, err2 = client_mod.normalize_authorize_args(
        {"kind": "arbitration_verdict", "who": "宿主", "scope": "t1",
         "reason": "r", "expires": "1757650000"})
    assert err2 == "" and auth2.scope == ["t1"] and auth2.expires == 1757650000
    auth3, err3 = client_mod.normalize_authorize_args(
        {"kind": "protected_path", "who": "宿主", "scope": ["a"], "reason": "r",
         "expires": 1757650000})
    assert err3 == "" and auth3.expires == 1757650000


@pytest.mark.parametrize("bad,frag", [
    ({}, "kind"),
    ({"kind": "bogus", "who": "w", "scope": ["a"], "expires": 1}, "kind"),
    ({"kind": "protected_path", "who": "w", "scope": [], "expires": 1}, "scope"),
    ({"kind": "protected_path", "who": "w", "scope": " , ", "expires": 1}, "scope"),
    ({"kind": "protected_path", "who": "w", "scope": ["a"]}, "expires"),
    ({"kind": "protected_path", "who": "w", "scope": ["a"], "expires": "不是时间"}, "expires 非法"),
    ({"kind": "protected_path", "who": "w", "scope": ["a"], "expires": 0}, "expires"),
    ({"kind": "protected_path", "who": "  ", "scope": ["a"], "expires": 1}, "who"),
])
def test_normalize_authorize_args_rejects(bad, frag):
    auth, err = client_mod.normalize_authorize_args(bad)
    assert auth is None and frag in err


def test_row_from_meta_authz_active_counts_only_live():
    now = int(__import__("time").time())
    meta = {"authorizations": [
        {"kind": "protected_path", "who": "a", "expires": now + 100},
        {"kind": "arbitration_verdict", "who": "b", "expires": now + 100},
        {"kind": "protected_path", "who": "c", "expires": now - 1},   # 过期
        {"kind": "bogus", "who": "d", "expires": now + 100},          # 坏 kind
        "malformed",
    ]}
    row = client_mod._row_from_meta("t1", meta, "RUNNING")
    assert row["authz_active"] == 2
    assert client_mod._row_from_meta("t2", {}, "RUNNING")["authz_active"] == 0
