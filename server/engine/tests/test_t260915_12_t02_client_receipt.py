"""t260915-12 跨项目写操作闸——client.py 接线单测（t02）。

覆盖：_write_gate 前置三态（transient 不判越权 KI-025 / not_found / 拒收与放行）、
八写 op 盖章下发、undeclared 哨兵与 C3 分档 notice（retry_qc/update 的记名只在
admin.log——回执文案不许超诺）、越权旗 pass_override、cancel 的 C2① 三态
（SA 瞬时失败=结构化拒收不放行 terminate；无 SA 引擎件=engine-internal 放行）、
ticket-start 创建面拒收、_emit 的 admin.log 身份行键。
全程禁网络/真 Temporal：_connect 打桩、SANDBAR_ADMIN_LOG 指 tmp（test_client_audit 同款隔离）。
"""
import asyncio
import json

import pytest

import audit
import caller_gate
import client
import shared


SNAP = {"meta": {"project": "sandbar"}, "workflow_class": "DevLaneWorkflow",
        "template_id": "dev-lane", "refused": [], "authorizations": []}


class FakeSearchAttrs:
    def __init__(self, project):
        self._p = project

    def get(self, key):
        return self._p


class FakeDesc:
    def __init__(self, project):
        self.typed_search_attributes = FakeSearchAttrs(project)


class FakeHandle:
    def __init__(self, snap=None, project="", query_exc=None, desc_exc=None):
        self._snap = snap if snap is not None else SNAP
        self.project = project
        self.query_exc = query_exc
        self.desc_exc = desc_exc
        self.signals = []
        self.terminated = None
        self.updates = []

    async def query(self, name):
        if self.query_exc is not None:
            raise self.query_exc
        return self._snap

    async def describe(self):
        if self.desc_exc is not None:
            raise self.desc_exc
        return FakeDesc(self.project)

    async def signal(self, name, payload):
        self.signals.append((name, payload))

    async def terminate(self, reason=""):
        self.terminated = reason

    async def execute_update(self, name, args=None):
        self.updates.append((name, args))
        return {"ok": True, "id": "t1"}


class FakeClient:
    def __init__(self, handle):
        self.handle = handle
        self.started = []

    def get_workflow_handle(self, tid):
        return self.handle

    async def start_workflow(self, *a, **k):
        self.started.append(k)
        return type("H", (), {"id": "t1", "result_run_id": "run-1"})()


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    monkeypatch.delenv(shared.CALLER_PROJECT_ENV, raising=False)
    monkeypatch.delenv(audit.ENTRY_ENV, raising=False)
    monkeypatch.delenv(audit.CALL_ID_ENV, raising=False)
    return log


def _patch_connect(monkeypatch, fake):
    monkeypatch.setattr(client, "_connect", lambda: asyncio.sleep(0, result=fake))


def _run(coro):
    return asyncio.run(coro)


def _rows(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


# ---------- sign：declared 同项目 / 异项目拒收 / 越权旗 / undeclared ----------

def test_sign_same_project_stamped_and_pass(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1",
                                "input": {"who": "宿主", "gate": "merge"}}))
    assert r["ok"] and r["result"]["delivered"] is True
    assert r["caller_project"] == "sandbar"          # 身份键在外层（与拒收回执同层）
    assert r["identity_class"] == "declared"
    name, payload = h.signals[0]
    assert name == "sign" and payload.caller_project == "sandbar"
    assert payload.cross_project_note == ""


def test_sign_mismatch_refused_no_signal(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1",
                                "input": {"who": "宿主"}}))
    assert r["ok"] is False and r["kind"] == "cross_project_refused"
    # 人话点名：双项目键 + 目标票号都在场（真链路场景相三判据）
    assert "dengzhufpv" in r["error"] and "sandbar" in r["error"] and "t1" in r["error"]
    assert h.signals == []  # fail-closed：信号不出手
    assert r["caller_project"] == "dengzhufpv" and r["identity_class"] == "declared"


def test_sign_mismatch_with_flag_passes_override(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1",
                                "input": {"who": "宿主"},
                                "cross_project": {"by": "宿主", "reason": "代管收口"}}))
    assert r["ok"] and r["cross_project_used"] is True
    _, payload = h.signals[0]
    assert payload.caller_project == "dengzhufpv"
    assert payload.cross_project_note == "代管收口"


def test_sign_undeclared_sentinel_and_notice(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1",
                                "input": {"who": "宿主"}}))
    assert r["ok"] and r["identity_class"] == "undeclared"
    assert "未声明" in r["cross_project_notice"]
    _, payload = h.signals[0]
    assert payload.caller_project == shared.CALLER_UNDECLARED_MARK  # 哨兵送达（C3 记名靠它）


def test_sign_shape_invalid_env_refused(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "SANDBAR")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1", "input": {}}))
    assert r["ok"] is False and r["kind"] == "cross_project_refused"
    assert h.signals == []


# ---------- 闸前置三态（C2① KI-025 口径） ----------

def test_query_transient_not_judged_as_cross_project(monkeypatch):
    h = FakeHandle(query_exc=TimeoutError("deadline exceeded"))
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setattr(client, "_query_snapshot_with_retry",
                        lambda handle, **k: _raise(TimeoutError("deadline exceeded")))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1", "input": {"who": "x"}}))
    assert r["ok"] is False and r["kind"] == "transient"
    assert "未执行任何动作" in r["error"] and h.signals == []


def test_query_not_found(monkeypatch):
    _patch_connect(monkeypatch, FakeClient(FakeHandle()))
    monkeypatch.setattr(client, "_query_snapshot_with_retry",
                        lambda handle, **k: _raise(RuntimeError("workflow not found: t1")))
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1", "input": {"who": "x"}}))
    assert r["ok"] is False and r["kind"] == "not_found"


async def _raise(e):
    raise e


# ---------- C3 分档：不盖章 op 的 undeclared notice 说实话 ----------

def test_retry_qc_undeclared_notice_admin_log_only(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_ticket({"op": "retry_qc", "ticket_id": "t1", "who": "宿主"}))
    assert r["ok"] and r["identity_class"] == "undeclared"
    notice = r["cross_project_notice"]
    assert "仅在 admin.log" in notice and "cross_project_uses 列不出" in notice
    name, payload = h.signals[0]
    assert name == "retry_qc" and payload == "宿主"  # 裸 who 契约不破


def test_update_undeclared_notice_admin_log_only(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_ticket({"op": "update", "ticket_id": "t1", "status": "settled"}))
    assert r["ok"] and "仅在 admin.log" in r["cross_project_notice"]
    assert h.updates and h.updates[0][0] == "update_status"


def test_rework_stamped(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket({"op": "rework", "ticket_id": "t1", "note": "返工",
                                "who": "宿主"}))
    assert r["ok"]
    _, payload = h.signals[0]
    assert payload.caller_project == "sandbar" and payload.note == "返工"


def test_pause_resume_stamped(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    for op in ("pause", "resume"):
        r = _run(client.cmd_ticket({"op": op, "ticket_id": "t1", "input": {"who": "宿主"}}))
        assert r["ok"] and r["result"]["signal"] == op
    assert [n for n, _ in h.signals] == ["pause", "resume"]
    assert h.signals[0][1].caller_project == "sandbar"


# ---------- cancel：C2① 三态 + engine-internal ----------

def test_cancel_sa_mismatch_refused_no_terminate(monkeypatch):
    h = FakeHandle(project="sandbar")
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_cancel({"workflow_id": "t1", "reason": "清场"}))
    assert r["ok"] is False and r["kind"] == "cross_project_refused"
    assert h.terminated is None  # 绝不 fail-open


def test_cancel_sa_mismatch_flag_terminates(monkeypatch):
    h = FakeHandle(project="sandbar")
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_cancel({"workflow_id": "t1", "reason": "清场",
                                "cross_project": {"by": "宿主", "reason": "代管清场"}}))
    assert r["ok"] and r["result"]["terminated"] is True
    assert r["cross_project_used"] is True
    assert h.terminated == "清场"


def test_cancel_no_sa_engine_internal(monkeypatch):
    h = FakeHandle(project="")  # dispatcher-scan 等无项目 SA
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_cancel({"workflow_id": "dispatcher-scan"}))
    assert r["ok"] and r["identity_class"] == "engine-internal"
    assert h.terminated is not None


def test_cancel_transient_refused(monkeypatch):
    h = FakeHandle(desc_exc=TimeoutError("deadline"))
    _patch_connect(monkeypatch, FakeClient(h))
    r = _run(client.cmd_cancel({"workflow_id": "t1"}))
    assert r["ok"] is False and r["kind"] == "transient"
    assert "未执行任何动作" in r["error"] and h.terminated is None


# ---------- ticket-start：创建面 ----------

def test_ticket_start_mismatch_refused(monkeypatch, tmp_path):
    fc = FakeClient(FakeHandle())
    _patch_connect(monkeypatch, fc)
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "dengzhufpv")
    r = _run(client.cmd_ticket_start({"ticket_id": "t9", "template_id": "dev-lane",
                                      "project": "sandbar", "title": "x"}))
    assert r["ok"] is False and r["kind"] == "cross_project_refused"
    assert fc.started == []  # 未锚定不创建


# ---------- audit 行键（_emit 提取回执身份键落账） ----------

def test_emit_writes_identity_row_keys(monkeypatch, tmp_path):
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    receipt = {"ok": False, "error": "跨项目写操作拒收", "kind": "cross_project_refused",
               "caller_project": "dengzhufpv", "identity_class": "declared",
               "cross_project_used": True}
    client._emit("ticket", {}, receipt)
    rows = _rows(log)
    assert rows and rows[-1]["caller_project"] == "dengzhufpv"
    assert rows[-1]["identity_class"] == "declared" and rows[-1]["override"] is True


def test_emit_success_receipt_nested_keys(monkeypatch, tmp_path):
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    client._emit("ticket", {}, {"ok": True, "result": {
        "identity_class": "undeclared", "caller_project": ""}})
    rows = _rows(log)
    assert rows[-1]["identity_class"] == "undeclared"
    assert "override" not in rows[-1] and "caller_project" not in rows[-1] or \
        rows[-1].get("caller_project") in (None, "")


# ---------- cwd 窄兜底（真链路场景相八的进程内等价子用例） ----------

def test_cwd_under_registered_dir_derives_declared(monkeypatch, tmp_path):
    ws = tmp_path / "myproj"
    ws.mkdir()
    monkeypatch.setattr(client, "REPO_ROOT", tmp_path / "repo")
    # 真 load_projects_registry 返回 (projects, quarantined) 二元组——桩同形
    monkeypatch.setattr(client, "load_projects_registry",
                        lambda: ([{"key": "projx", "dirs": [str(ws)]}], []))
    monkeypatch.setattr(client.os, "getcwd", lambda: str(ws))
    ident = client._caller_identity({})
    assert ident == {"value": "projx", "src": "cwd", "identity_class": "declared"}


def test_cwd_inside_repo_tree_stays_undeclared(monkeypatch, tmp_path):
    """C1 检测器：仓内子目录（真实 dsh/console spawn 形态）恒 undeclared，哪怕注册表
    把仓根注册成了项目 dir（行为反转探测条目）。"""
    repo = tmp_path / "repo"
    (repo / "server" / "engine").mkdir(parents=True)
    monkeypatch.setattr(client, "REPO_ROOT", repo)
    monkeypatch.setattr(client, "load_projects_registry",
                        lambda: ([{"key": "sc12repo", "dirs": [str(repo)]}], []))
    monkeypatch.setattr(client.os, "getcwd", lambda: str(repo / "server" / "engine"))
    ident = client._caller_identity({})
    assert ident["identity_class"] == "undeclared" and ident["src"] == "none"


def test_registry_unreadable_degrades_cwd_fallback_only(monkeypatch, tmp_path):
    """注册表读不到=cwd 兜底缺席（退回 arg/env/undeclared），不放大成全写面拒收。"""
    ws = tmp_path / "myproj"
    ws.mkdir()
    monkeypatch.setattr(client, "REPO_ROOT", tmp_path / "repo")
    def _boom():
        raise RuntimeError("registry gone")
    monkeypatch.setattr(client, "load_projects_registry", _boom)
    monkeypatch.setattr(client.os, "getcwd", lambda: str(ws))
    assert client._caller_identity({})["identity_class"] == "undeclared"
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "projx")
    assert client._caller_identity({})["value"] == "projx"


# ---------- admin.log 行 identity_src 键（场景相二判据） ----------

def test_audit_row_carries_identity_src(monkeypatch, tmp_path):
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1", "input": {"who": "x"}}))
    client._emit("ticket", {}, r)  # main() 的落账出口（真实回执原样入账）
    rows = _rows(log)
    assert rows and rows[-1].get("identity_src") == "env"
    assert rows[-1].get("override") is False  # 同项目放行也是 false（非越权）


# ---------- 判定/回执不把注册表外 key 当 undeclared（C2② 接线面） ----------

def test_unregistered_declared_key_gets_registered_false(monkeypatch):
    h = FakeHandle()
    _patch_connect(monkeypatch, FakeClient(h))
    monkeypatch.setenv(shared.CALLER_PROJECT_ENV, "sandbar")
    r = _run(client.cmd_ticket({"op": "sign", "ticket_id": "t1",
                                "input": {"who": "x"},
                                "caller_project": "no-such-key-but-valid-shape"}))
    assert r["ok"] is False and r["kind"] == "cross_project_refused"
    assert r.get("caller_project_registered") is False
