"""260930 批次 B 单测：终态票**留痕对账**与**票面回落**（dengzhufpv E4+E5 合并需求）。

E4 的病：`t260929-31` 是 TERMINATED，历史里的理由串写着「宿主经…当面决定停掉本票」，
而该票**唯一的信号是 pause**（那个"宿主决定"从未发生）——引擎侧确有一条裸 terminate 路径
不发 `cancel_notice`，且 `admin.log` 里也没有任何 cancel 记录（更像引擎之外的 terminate）。
当时要查清只能自己写 Temporal SDK 脚本读历史（E5）。

两条修法各锁一层：
  B5 `client.py cancel-audit`（**只读**）：列出近期 TERMINATED 工单，逐张读事件历史，核
     「terminate 理由串」是否有**同串的 `cancel_notice` 信号**先于它（引擎契约：先留痕、
     后终结、reason 三方同串）⇒ 分桶 matched / missing_notice / reason_mismatch /
     history_unreadable，违规即 exit 1（fail-loud）。这同时是 E5「读事件历史无工具入口」的答案。
  B6 终态票面回落：`_terminal_failure_face` 增**最后一个信号名**（复盘第一眼要看的），
     `QueryError` 携带 face、`_cli` 回执把 face 上送 ⇒ 正规入口就能读到，不必写脚本。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260930_cancel_audit_and_terminal_face.py -q
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
sys.path.insert(0, str(POC.parent.parent / "server" / "tools"))

import client as cl  # noqa: E402


def _term(reason):
    return SimpleNamespace(
        workflow_execution_terminated_event_attributes=SimpleNamespace(reason=reason))


def _sig(name, payload=None):
    payloads = []
    if payload is not None:
        payloads = [SimpleNamespace(data=json.dumps(payload).encode("utf-8"))]
    return SimpleNamespace(workflow_execution_signaled_event_attributes=SimpleNamespace(
        signal_name=name, input=SimpleNamespace(payloads=payloads)))


class _Handle:
    def __init__(self, events=None, boom=None):
        self._events = events or []
        self._boom = boom

    async def fetch_history(self):
        if self._boom:
            raise self._boom
        return SimpleNamespace(events=self._events)


class _Client:
    """假 Temporal client：list_workflows 产 id；get_workflow_handle 给历史。"""

    def __init__(self, by_id, times=None):
        self._by_id = by_id
        self._times = times or {}
        self.queries = []

    def list_workflows(self, query):
        self.queries.append(query)
        times = self._times

        async def _gen():
            for wid in self._by_id:
                yield SimpleNamespace(id=wid, close_time=times.get(wid))

        return _gen()

    def get_workflow_handle(self, wid):
        return self._by_id[wid]


@pytest.fixture()
def fake_client(monkeypatch):
    def _install(by_id, times=None):
        c = _Client(by_id, times)

        async def _connect():
            return c

        monkeypatch.setattr(cl, "_connect", _connect)
        return c

    return _install


def _audit(**args):
    return asyncio.run(cl.cmd_cancel_audit(args))


# ---------------- B5：分桶判据 ----------------

def test_notice_with_same_reason_is_matched(fake_client):
    fake_client({"t1": _Handle([_sig("pause"), _sig("cancel_notice", {"who": "宿主", "reason": "R"}),
                                _term("R")])})
    out = _audit()["result"]
    assert out["checked"] == 1 and out["violations"] == 0 and out["alarmed"] is False
    assert "ok" not in out          # 违规=alarmed，命令成功与否=外层 ok，两者不复用同一个键
    assert out["matched"][0]["last_signal"] == "cancel_notice"
    assert out["matched"][0]["terminate_reason"] == "R"
    assert out["matched"][0]["notice_count"] == 1


def test_missing_notice_is_a_violation(fake_client):
    """E4 的形态：历史里只有 pause，terminate 理由串却自称宿主决定。"""
    fake_client({"t260929-31": _Handle([_sig("pause"), _term("宿主经…当面决定停掉本票")])})
    res = _audit()
    out = res["result"]
    assert out["alarmed"] is True and out["violations"] == 1
    bad = out["missing_notice"][0]
    assert bad["id"] == "t260929-31" and bad["last_signal"] == "pause"
    assert "宿主经" in bad["terminate_reason"], "理由串原文必须带出（不实归因要可读）"
    assert "只读" in out["note"] and "不动任何票" in out["note"]


def test_notice_with_a_different_reason_is_a_mismatch(fake_client):
    fake_client({"t2": _Handle([_sig("cancel_notice", {"who": "x", "reason": "别的理由"}),
                                _term("R")])})
    out = _audit()["result"]
    assert out["alarmed"] is True and out["reason_mismatch"][0]["id"] == "t2"
    assert out["reason_mismatch"][0]["notice_reasons"] == ["别的理由"]


def test_close_out_notice_with_face_prefix_is_matched(fake_client):
    """close_out 正规路径理由带面首（"close_out（…）：<reason>"），notice 载荷是 reason 原文。

    实测假阳性：按全等比对会把 t260928-32/-33 判成违规 —— 口径必须是**包含**。
    """
    fake_client({"t1": _Handle([
        _sig("close_out_notice", {"who": "宿主", "reason": "工作已完成"}),
        _term("close_out（人工记名收口·工作已完成）：工作已完成")])})
    r = _audit()["result"]
    assert r["matched"] and not r["missing_notice"] and not r["reason_mismatch"]
    assert r["alarmed"] is False
    assert "ok" not in r, "命令成功与查出违规是两个键：内层不许复用 ok（否则被当业务拒绝）"
    assert r["matched"][0]["notice_kinds"] == ["close_out_notice"]


def test_pre_mechanism_termination_is_legacy_not_a_violation(fake_client):
    """留痕机制上线（2026-09-23）之前终结的票结构上无法留痕 → 单列 legacy，不告警。"""
    old = datetime(2026, 9, 10, tzinfo=timezone.utc)
    new = datetime(2026, 9, 29, tzinfo=timezone.utc)
    fake_client({"t-old": _Handle([_term("旧账")]), "t-new": _Handle([_term("新账")])},
                times={"t-old": old, "t-new": new})
    r = _audit()["result"]
    assert [v["id"] for v in r["legacy_pre_mechanism"]] == ["t-old"]
    assert [v["id"] for v in r["missing_notice"]] == ["t-new"]
    assert r["violations"] == 1 and r["alarmed"] is True
    assert r["legacy_pre_mechanism"][0]["terminated_at"] == "2026-09-10T00:00:00Z"


def test_cutoff_is_overridable_and_reported(fake_client):
    t = datetime(2026, 9, 25, tzinfo=timezone.utc)
    fake_client({"t1": _Handle([_term("R")])}, times={"t1": t})
    r = _audit(cutoff="2030-01-01")["result"]     # 把线推到未来 → 同一张票落入 legacy
    assert r["cutoff"] == "2030-01-01" and r["alarmed"] is False
    assert [v["id"] for v in r["legacy_pre_mechanism"]] == ["t1"]
    r3 = _audit()["result"]                       # 默认线下 → 同一张票是违规
    assert r3["alarmed"] is True and [v["id"] for v in r3["missing_notice"]] == ["t1"]
    r2 = _audit(cutoff="不是日期")["result"]      # 参数不可解=回落到默认，不静默放宽
    assert r2["cutoff"] == cl.NOTICE_MECHANISM_CUTOFF
    r4 = _audit()["result"]                       # 时间不可得时从严：按「机制后」算，不白送 legacy
    assert r4["alarmed"] is True


def test_history_unreadable_is_reported_but_not_counted_as_a_violation(fake_client):
    fake_client({"t3": _Handle(boom=RuntimeError("history unavailable"))})
    out = _audit()["result"]
    assert out["checked"] == 1 and out["violations"] == 0
    assert out["history_unreadable"][0]["id"] == "t3"
    assert "RuntimeError" in out["history_unreadable"][0]["why"]


def test_query_shape_and_arg_robustness(fake_client):
    c = fake_client({"t4": _Handle([_sig("cancel_notice", {"reason": "R"}), _term("R")])})
    out = _audit(limit="oops", days="oops")["result"]
    assert out["limit"] == 20 and out["checked"] == 1, "畸形入参回落缺省，不炸"
    q = c.queries[0]
    assert 'ExecutionStatus="Terminated"' in q and "CloseTime >" in q, \
        "只查终态（TERMINATED）且只查时间窗内：%s" % q


def test_limit_stops_early(fake_client):
    fake_client({"a": _Handle([_term("R")]), "b": _Handle([_term("R")]), "c": _Handle([_term("R")])})
    out = _audit(limit=2)["result"]
    assert out["checked"] == 2


def test_malformed_signal_payload_never_raises(fake_client):
    """载荷解不出＝reason 空 ⇒ 归入 mismatch 桶（有 notice 但串不同），绝不抛。"""
    fake_client({"t5": _Handle([_sig("cancel_notice", None), _term("R")])})
    out = _audit()["result"]
    assert out["violations"] == 1 and out["reason_mismatch"][0]["notice_reasons"] == [""]


# ---------------- B6：终态票面回落 ----------------

def test_last_signal_from_history():
    h = _Handle([_sig("pause"), _sig("rework"), _sig("cancel_notice", {"reason": "R"})])
    got = asyncio.run(cl._terminal_face_last_signal(h))
    assert got["last_signal"] == "cancel_notice" and got["last_signal_available"] is True
    assert got["signal_names"] == ["pause", "rework", "cancel_notice"]


def test_last_signal_absent_is_named_not_faked():
    got = asyncio.run(cl._terminal_face_last_signal(_Handle([])))
    assert got["last_signal"] == "" and got["last_signal_available"] is False
    assert "零信号事件" in got["last_signal_note"]


def test_last_signal_unreadable_degrades_honestly():
    got = asyncio.run(cl._terminal_face_last_signal(_Handle(boom=RuntimeError("boom"))))
    assert got["last_signal_available"] is False and "不可得" in got["last_signal_note"]
    assert "RuntimeError" in got["last_signal_note"]


def test_face_is_wired_into_the_terminal_path():
    """接线锁：face 由 _terminal_failure_face 现算 → QueryError 携带 → _cli 回执上送。"""
    src = Path(cl.__file__).read_text("utf-8")
    assert "_terminal_face_last_signal(handle)" in src, "终态 face 必须带最后信号名"
    assert "face=await _terminal_failure_face(" in src, "终态分支必须现算 face"
    tsrc = (POC.parent / "tools" / "ticket.py").read_text("utf-8")
    assert "self.face = face" in tsrc and "face=out.get('face') if kind == 'terminal'" in tsrc
    assert "out['face'] = face" in tsrc, "CLI 回执必须把 face 上送（否则正规入口读不到）"


def test_query_error_carries_kind_and_face():
    import ticket as tk
    e = tk.QueryError("工单查询失败（terminal）：…", kind="terminal", face={"last_signal": "pause"})
    assert isinstance(e, ValueError) and e.kind == "terminal" and e.face["last_signal"] == "pause"
    e2 = tk.QueryError("boom")
    assert e2.kind == "internal" and e2.face is None, "缺省零感知（老消费方 addtive 兼容）"
