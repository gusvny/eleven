"""server/tools/ticket.py 直 spawn CLI 与 sign/retry_qc 包装单元测试（KI-067，
t260910-06）。被测文件无包结构，importlib 载入；Temporal 面一律桩掉 `_poc`，
绝不触真 Temporal。CLI 子进程用例只压不 spawn 的路径（参数校验/拒收），真
Temporal 链路归 integration 场景（sc_ki067_entry_audit）。
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TICKET_PY = REPO / "server" / "tools" / "ticket.py"


@pytest.fixture()
def tk(tmp_path, monkeypatch):
    """载入 ticket.py 模块：日志指向 tmp，_poc 换成捕获桩。"""
    spec = importlib.util.spec_from_file_location("ticket_mod_under_test", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_mod_under_test"] = mod
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "admin.log"))
    monkeypatch.delenv("SANDBAR_CLIENT_ENTRY", raising=False)
    monkeypatch.delenv("SANDBAR_CLIENT_CALL_ID", raising=False)
    spec.loader.exec_module(mod)
    calls = []

    def fake_poc(subcmd, payload):
        calls.append((subcmd, payload))
        return {"ok": True, "result": {"delivered": True, "signal": payload.get("op")}}

    monkeypatch.setattr(mod, "_poc", fake_poc)
    mod._calls = calls
    return mod


# ---------- op 转发形状（谁也不许改 workflow 侧契约） ----------

def test_retry_qc_forwards_bare_who(tk):
    r = tk.run({"op": "retry_qc", "id": "t1", "by": "integration"})
    assert r["delivered"] is True
    subcmd, payload = tk._calls[0]
    assert (subcmd, payload) == ("ticket", {"op": "retry_qc", "ticket_id": "t1",
                                            "who": "integration"})


def test_retry_qc_default_who_oplocal(tk):
    tk.run({"op": "retry_qc", "id": "t1"})
    assert tk._calls[0][1]["who"] == "op-local"


def test_who_alias_and_by_equivalent(tk):
    """who（信号语义名，场景/workbench 面）与 by（schema 主名）双读等价——
    who 在包装层被丢=代签无主（KI-067 包装面事故形状）。"""
    tk.run({"op": "retry_qc", "id": "t1", "who": "u1"})
    assert tk._calls[-1][1]["who"] == "u1"
    tk.run({"op": "sign", "id": "t1", "who": "u2"})
    assert tk._calls[-1][1]["input"]["who"] == "u2"
    tk.run({"op": "rework", "id": "t1", "note": "n", "who": "u3"})
    assert tk._calls[-1][1]["who"] == "u3"
    tk.run({"op": "sign", "id": "t1", "by": "u4"})
    assert tk._calls[-1][1]["input"]["who"] == "u4"


def test_retry_qc_rejects_note(tk):
    """workflow 契约只收裸串 who：note 静默蒸发不可接受，CLI 层显式拒收。"""
    with pytest.raises(ValueError, match="不收 note"):
        tk.run({"op": "retry_qc", "id": "t1", "note": "带话"})
    assert tk._calls == []


def test_retry_qc_needs_id(tk):
    with pytest.raises(ValueError, match="需要 id"):
        tk.run({"op": "retry_qc"})


def test_sign_forwards_signature_shape(tk):
    r = tk.run({"op": "sign", "id": "t1", "by": "host", "gate": "g1",
                "decision": "reject", "note": "不收"})
    assert r["delivered"] is True
    subcmd, payload = tk._calls[0]
    assert subcmd == "ticket"
    assert payload["op"] == "sign"
    assert payload["ticket_id"] == "t1"
    assert payload["input"] == {"who": "host", "gate": "g1",
                                "decision": "reject", "note": "不收"}


def test_sign_defaults_and_bad_decision(tk):
    tk.run({"op": "sign", "id": "t1"})
    assert tk._calls[0][1]["input"]["decision"] == "approve"
    with pytest.raises(ValueError, match="approve|reject"):
        tk.run({"op": "sign", "id": "t1", "decision": "maybe"})


def test_sign_needs_id(tk):
    with pytest.raises(ValueError, match="需要 id"):
        tk.run({"op": "sign"})


def test_unknown_op_raises(tk):
    with pytest.raises(ValueError, match="未知 op"):
        tk.run({"op": "nonsense"})


def test_create_bad_project_raises_before_poc(tk):
    """create 拒收在 spawn 之前（形状非法 key 任何注册表都拒）——失败不触 Temporal。"""
    with pytest.raises(ValueError):
        tk.run({"op": "create", "project": "!!! bad key !!!",
                "workflow": "dev-lane", "title": "x"})
    assert tk._calls == []


# ---------- _poc 自报家门注入 ----------

def test_poc_injects_entry_mark_and_call_id(tmp_path, monkeypatch):
    """_poc 子进程 env 带精确 'ticket' 标记；CALL_ID_ENV 有值则透传关联。
    独立载入模块（tk 夹具把 _poc 换成了桩），subprocess.run 桩在模块级还原。"""
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(tmp_path / "a.log"))
    monkeypatch.setenv("SANDBAR_CLIENT_CALL_ID", "cafecafe1234")
    spec = importlib.util.spec_from_file_location("ticket_poc_env", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_poc_env"] = mod
    spec.loader.exec_module(mod)
    captured = {}

    def fake_run(cmd, **kw):
        captured["env"] = kw["env"]

        class P:
            stdout = '{"ok": true, "result": {}}'
            stderr = ""
            returncode = 0
        return P()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    mod._poc("ticket-list", {})
    assert captured["env"]["SANDBAR_CLIENT_ENTRY"] == "ticket"
    assert captured["env"]["SANDBAR_CLIENT_CALL_ID"] == "cafecafe1234"


# ---------- CLI 子进程（退出码契约：绝不空输出+退出 0） ----------

def _run_cli(args, log_path):
    env = dict(os.environ)
    env["SANDBAR_ADMIN_LOG"] = str(log_path)
    return subprocess.run([sys.executable, str(TICKET_PY)] + args,
                          capture_output=True, text=True, env=env, timeout=60)


def _assert_structured_failure(proc):
    assert proc.returncode != 0, "失败必须非零退出（KI-067 根因契约）"
    out = json.loads(proc.stdout)  # 绝不空输出：stdout 必是结构化 JSON
    assert out["ok"] is False and out["error"]


def test_cli_no_args_nonzero_structured(tmp_path):
    proc = _run_cli([], tmp_path / "a.log")
    _assert_structured_failure(proc)


def test_cli_help_nonzero_anti_misuse(tmp_path):
    """-h 也非零：本 CLI 无交互面，防打印用法后空跑被上游当成功（方案注明的取舍）。"""
    proc = _run_cli(["-h"], tmp_path / "a.log")
    _assert_structured_failure(proc)


def test_cli_malformed_json_nonzero(tmp_path):
    proc = _run_cli(["not-json{{"], tmp_path / "a.log")
    _assert_structured_failure(proc)
    assert "JSON" in json.loads(proc.stdout)["error"]


def test_cli_rejected_op_nonzero_and_audited(tmp_path):
    """拒收路径：非零退出 + 结构化错误 + admin.log 有痕（不经 registry 也进账）。"""
    log = tmp_path / "a.log"
    proc = _run_cli(['{"op":"retry_qc","id":"t1","note":"x"}'], log)
    _assert_structured_failure(proc)
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["source"] == "ticket.py-direct"
    assert rows[0]["sub"] == "ticket.retry_qc"
    assert rows[0]["ok"] is False


def test_cli_success_via_stubbed_spawn(tmp_path, monkeypatch):
    """成功路径：exit 0 + 回执 JSON + 自记一行（client 行在真链路，此处桩掉）。"""
    log = tmp_path / "a.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    monkeypatch.delenv("SANDBAR_CLIENT_CALL_ID", raising=False)  # 清关联键，验证自生成
    spec = importlib.util.spec_from_file_location("ticket_cli_succ", TICKET_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ticket_cli_succ"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_poc", lambda s, p: {"ok": True, "result": {"delivered": True}})
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod._cli(['{"op":"retry_qc","id":"t1"}'])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True and out["result"]["delivered"] is True
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["ok"] is True
    assert rows[0]["source"] == "ticket.py-direct"
