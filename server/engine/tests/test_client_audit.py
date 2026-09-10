"""server/engine/audit.py 单元测试（KI-067，t260910-06）。

覆盖：claimed-source 语义（bare / 精确 'ticket' / 任意值）、entry_hint 附着
（含成功回执、被拒收回执）、审计行形状与截断、畸形输入（非 dict receipt、
不可序列化对象）、日志不可写不吞回执、并发 append 完整性。
全程禁网络/真 Temporal：日志路径经 SANDBAR_ADMIN_LOG 指向 tmp。
"""
import json
import os
import threading

import pytest

import audit


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """每用例独立日志文件 + 干净的 env 标记（防外部环境污染判定）。"""
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    monkeypatch.delenv(audit.ENTRY_ENV, raising=False)
    monkeypatch.delenv(audit.CALL_ID_ENV, raising=False)
    return log


def _rows(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


# ---------- claimed-source 语义 ----------

def test_source_default_bare():
    assert audit.claimed_source() == "bare"
    assert audit.is_ticket_entry() is False


def test_source_exact_ticket_only_silent(monkeypatch):
    monkeypatch.setenv(audit.ENTRY_ENV, "ticket")
    assert audit.is_ticket_entry() is True
    assert audit.claimed_source() == "ticket"


@pytest.mark.parametrize("val", ["ticket.py", "1", "ticket ", " ticket", "TICKET", "x" * 64])
def test_source_any_other_value_is_bare_treatment(val, monkeypatch):
    """静默仅认精确等值 'ticket'；任意其它值（含空白/大小写/超长）一律 bare 待遇。"""
    monkeypatch.setenv(audit.ENTRY_ENV, val)
    assert audit.is_ticket_entry() is False
    # source 记原值（≤32 截断），便于排查伪造/误配
    assert audit.claimed_source() == val[:32]


def test_source_empty_env_equals_unset(monkeypatch):
    """空串 env 视同未设：bare 待遇 + source 记 'bare'。"""
    monkeypatch.setenv(audit.ENTRY_ENV, "")
    assert audit.is_ticket_entry() is False
    assert audit.claimed_source() == "bare"


# ---------- entry_hint ----------

def test_hint_on_success_receipt_bare():
    r = audit.attach_entry_hint({"ok": True, "result": {}})
    assert r["entry_hint"] == audit.ENTRY_HINT


def test_hint_on_error_receipt_bare():
    r = audit.attach_entry_hint({"ok": False, "error": "x"})
    assert "entry_hint" in r


def test_no_hint_for_ticket_entry(monkeypatch):
    audit.attach_entry_hint({"ok": True})  # bare 环境对照：附 hint
    monkeypatch.setenv(audit.ENTRY_ENV, "ticket")
    r = audit.attach_entry_hint({"ok": True, "result": {}})
    assert "entry_hint" not in r


def test_hint_not_duplicated_and_non_dict_passthrough():
    r = audit.attach_entry_hint({"ok": True, "entry_hint": "已有"})
    assert r["entry_hint"] == "已有"
    assert audit.attach_entry_hint(None) is None


# ---------- audit_call ----------

def test_audit_row_shape_and_call_id(tmp_path, monkeypatch):
    log = tmp_path / "a.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    audit.audit_call("nosuch", {"ok": False, "error": "未知子命令"})
    (row,) = _rows(log)
    assert row["sub"] == "nosuch"
    assert row["ok"] is False
    assert row["source"] == "bare"
    assert len(row["call_id"]) == 12
    assert isinstance(row["ts"], int)


def test_audit_rejected_calls_recorded_too(tmp_path, monkeypatch):
    log = tmp_path / "a.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    audit.audit_call("ticket", {"ok": False, "error": "argsJSON 不是合法 JSON"})
    rows = _rows(log)
    assert len(rows) == 1 and rows[0]["ok"] is False  # 拒收不记录=盲区仍在（KI-067）


def test_audit_call_id_from_env_shared(tmp_path, monkeypatch):
    """ticket.py 直调双行：client 行取 env 关联键，两行 call_id 一致。"""
    log = tmp_path / "a.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    monkeypatch.setenv(audit.CALL_ID_ENV, "feedface1234")
    cid = audit.audit_call("ticket-list", {"ok": True, "result": {}})
    assert cid == "feedface1234"
    assert _rows(log)[0]["call_id"] == "feedface1234"


def test_audit_malformed_receipt_and_huge_fields(tmp_path, monkeypatch):
    """畸形输入：非 dict receipt 不炸；超长 summary 截断到 800。"""
    log = tmp_path / "a.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    audit.audit_call("x", None)
    audit.audit_call("y", {"ok": True, "blob": "z" * 100000})
    rows = _rows(log)
    assert rows[0]["ok"] is False
    assert len(rows[1]["summary"]) <= 800


def test_audit_unwritable_log_does_not_raise(tmp_path, monkeypatch, capsys):
    """admin.log 不可写：回执主契约不受影响，stderr 留痕（显式降级非静默）。"""
    d = tmp_path / "d"
    d.write_text("占位成文件，open('d/x') 必败")
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(d / "sub" / "x.log"))
    audit.audit_call("x", {"ok": True})  # 不 raise 即过
    assert "写失败" in capsys.readouterr().err


def test_audit_concurrent_appends_intact(tmp_path, monkeypatch):
    """多线程并发 append：每行完整 JSON，无交错撕裂（O_APPEND 契约）。"""
    log = tmp_path / "a.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    n_threads, per = 8, 20

    def worker(t):
        for i in range(per):
            audit.audit_call("t%d" % t, {"ok": True, "i": i})

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    rows = _rows(log)
    assert len(rows) == n_threads * per
    assert all(r["sub"].startswith("t") for r in rows)
