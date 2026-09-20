"""t260917-02 修复①：调度路径票形统一（重定向家族）单测——S3 纯面。

覆盖口径（=方案 v2 §S3 + review R2/R7）：
  A. has_ticket_id_shape 真值表：形状判别（全工单票共形），非巡检票身份判别（R7①
     圈死语义——t 形/三位序号/服务端后缀形/旧形 id/空串）。
  B. _resolve_spawn_identity 身份回退链（R2b）：args 显式优先 → plan.instance_project_key
     回退（缺 project_key 的 260917 实况子用例）→ 双缺 repo_root 可解析；都决议不出=
     fail-closed ValueError。
  C. spawn_inspection_period 活动面（桩注入）：args.period 透传（重定向把已铸期传下）；
     身份回退链在活动里生效；身份决议失败显式 ok=False；face 空传走声明 scan_face。
UT 全程禁网络/真 Temporal（Client/plan/open_period_ticket 全桩）。
运行：server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260917_02_inspection_redirect.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import activities as acts  # noqa: E402
import inspection_decl as decl_mod  # noqa: E402
import inspection_flow as flow  # noqa: E402
import inspection_ticketing as tick  # noqa: E402
import shared  # noqa: E402


# ---------------------------------------------------------------- A. 形状判别（R7①）

def test_has_ticket_id_shape_truth_table():
    # 两侧空白防御性 strip（id 手抄容错），故前后带空格都算匹配
    yes = ["t260916-13", "t260101-01", "t260916-130", " t260916-13", "t260916-13 "]
    no = ["", None, "t260916-1", "T260916-13", "t26091-13", "t260916",
          "inspection-foo-20260916",
          "inspection-integration-tests-period-2026-09-16T23:30:00Z",
          "x260916-13"]
    for tid in yes:
        assert tick.has_ticket_id_shape(tid) is True, tid
    for tid in no:
        assert tick.has_ticket_id_shape(tid) is False, tid
    # 共形自指（R7①）：本票自己的票号 t260917-02 同样匹配——故它只能当形状判别，
    # 绝不能当巡检票身份判别（身份判别=SA 单点，另测于 test_t260916_02）。
    assert tick.has_ticket_id_shape("t260917-02") is True


# ---------------------------------------------------------------- B. 身份回退链（R2b）

PLAN = {"ok": True, "instance_id": "integration-tests", "instance_project_key": "sandbar",
        "scan_face": "doc", "tz": "Asia/Shanghai"}


def test_identity_args_explicit_wins(monkeypatch):
    monkeypatch.setattr(shared, "resolve_project_root",
                        lambda k: (_ for _ in ()).throw(AssertionError("不应触注册表")))
    ident = acts._resolve_spawn_identity(
        {"project_key": "proj-a", "repo_root": "/repo/a"}, PLAN)
    assert ident == {"project_key": "proj-a", "repo_root": "/repo/a"}


def test_identity_falls_back_to_decl_when_args_missing(monkeypatch):
    """260917 实况子用例：旧 action payload 无 project_key、repo_root 非空——声明回退补齐
    身份；repo_root 显式保留（resolve_project_root 不触）。"""
    ident = acts._resolve_spawn_identity({"repo_root": "/Users/x/Documents/sandbar"}, PLAN)
    assert ident["project_key"] == "sandbar"
    assert ident["repo_root"] == "/Users/x/Documents/sandbar"


def test_identity_repo_resolved_from_registry_when_both_missing(monkeypatch):
    calls = []

    def fake_root(key):
        calls.append(key)
        return "/registry/%s" % key

    monkeypatch.setattr(shared, "resolve_project_root", fake_root)
    ident = acts._resolve_spawn_identity({}, PLAN)
    assert ident == {"project_key": "sandbar", "repo_root": "/registry/sandbar"}
    assert calls == ["sandbar"]


def test_identity_unresolvable_fails_closed(monkeypatch):
    """双缺（无 args 身份、plan 无实例级身份）且无 repo_root → ValueError（绝不静默
    回落引擎仓——无主守卫只拦双空，repo_root 残值会放行 ProjectKey 空的票）。"""
    monkeypatch.setattr(shared, "resolve_project_root",
                        lambda k: (_ for _ in ()).throw(ValueError("项目身份为空")))
    with pytest.raises(ValueError):
        acts._resolve_spawn_identity({"repo_root": ""}, {"ok": True})
    with pytest.raises(ValueError):
        acts._resolve_spawn_identity({"project_key": "", "repo_root": ""}, PLAN)


# ---------------------------------------------------------------- C. spawn 活动面（桩注入）

class _FakeClient:
    def __init__(self):
        self.connected = True


class _OpenSpy:
    def __init__(self):
        self.calls = []
        self.ret = {"ok": True, "result": {"triggered": True, "ticket_id": "t260917-01"}}

    async def __call__(self, client, **kw):
        self.calls.append(kw)
        import json
        return json.loads(json.dumps(self.ret))


def _patch_env(monkeypatch, plan, open_spy):
    monkeypatch.setattr(acts, "Client", SimpleNamespace(
        connect=None))  # connect 在被测路径里按需替换（下方闭包）
    async def fake_connect(host, namespace=None):
        return _FakeClient()
    monkeypatch.setattr(acts, "Client", SimpleNamespace(connect=fake_connect))
    monkeypatch.setattr(decl_mod, "resolve_instance_plan", lambda iid, p=None: dict(plan))
    monkeypatch.setattr(tick, "open_period_ticket", open_spy)
    monkeypatch.setattr(acts, "activity", SimpleNamespace(
        info=lambda: SimpleNamespace(task_queue="q-t")))
    # 身份回退链的注册表桩（活动内部 from shared import → 读模块属性，可注）
    monkeypatch.setattr(shared, "resolve_project_root",
                        lambda k: "/registry/%s" % k)


def test_spawn_period_override_and_identity_fallback(monkeypatch):
    """重定向复用子用例：args.period 透传（不按 tz 现铸）+ 缺 project_key 走声明回退；
    face 空传 → scan_face 走声明（doc）。"""
    spy = _OpenSpy()
    _patch_env(monkeypatch, PLAN, spy)
    res = acts.spawn_inspection_period.__wrapped__ if False else None  # noqa: F841
    import asyncio
    out = asyncio.run(acts.spawn_inspection_period({
        "instance_id": "integration-tests", "period": "20260901",
        "face": "", "project_key": "", "repo_root": ""}))
    assert out["ok"] is True
    call = spy.calls[0]
    assert call["period"] == "20260901"            # 透传期号（非现铸）
    assert call["project_key"] == "sandbar"        # 声明回退（R2c 断言值）
    assert call["repo_root"] == "/registry/sandbar"
    assert call["scan_face"] == "doc"              # 旧 payload face 不采信
    assert call["task_queue"] == "q-t"


def test_spawn_without_period_mints_by_decl_tz(monkeypatch):
    """存量 spawner 行为零变化：args.period 空 → 按 plan.tz 现铸（回归钉）。"""
    spy = _OpenSpy()
    _patch_env(monkeypatch, PLAN, spy)
    import asyncio
    out = asyncio.run(acts.spawn_inspection_period({
        "instance_id": "integration-tests", "face": "test",
        "project_key": "sandbar", "repo_root": "/repo/x"}))
    assert out["ok"] is True
    call = spy.calls[0]
    assert call["period"] and len(str(call["period"])) == 8   # YYYYMMDD 现铸
    assert call["project_key"] == "sandbar" and call["repo_root"] == "/repo/x"
    assert call["scan_face"] == "test"             # args 显式 face 仍优先（spawner 原语义）


def test_spawn_identity_failure_is_explicit(monkeypatch):
    spy = _OpenSpy()
    _patch_env(monkeypatch, {"ok": True, "instance_id": "i"}, spy)  # plan 无身份键
    def boom(key):                     # 注意：同步抛错（async 会返回协程不抛）
        raise ValueError("项目身份为空")
    monkeypatch.setattr(shared, "resolve_project_root", boom)
    import asyncio
    out = asyncio.run(acts.spawn_inspection_period({"instance_id": "i"}))
    assert out["ok"] is False and "身份决议失败" in out["error"]
    assert spy.calls == []                          # 不起票


def test_spawn_decl_not_ok_fails_first(monkeypatch):
    spy = _OpenSpy()
    _patch_env(monkeypatch, {"ok": False, "error": "实例已停用"}, spy)
    import asyncio
    out = asyncio.run(acts.spawn_inspection_period({"instance_id": "i", "period": "20260901"}))
    assert out["ok"] is False and "停用" in out["error"]
    assert spy.calls == []


# ---------------------------------------------------------------- D. 重定向守卫判据（S4 纯面）

def test_legacy_fire_redirect_reason_truth_table():
    assert flow.legacy_fire_redirect_reason("t260916-13") == ""          # t 形：零影响
    assert flow.legacy_fire_redirect_reason("") != ""                    # 空 id 也拦（fail-closed）
    r = flow.legacy_fire_redirect_reason(
        "inspection-integration-tests-period-2026-09-16T23:30:00Z")      # 260917 实况形
    assert "非 t 形" in r and "schedule-up" in r and "open_period_ticket" in r
    r2 = flow.legacy_fire_redirect_reason("inspection-foo-20260916")     # 旧形 id 同拦
    assert "schedule-up" in r2


def test_redirect_patch_id_registered_constant():
    # 命名与 SUITE/PROJECT 同族（patch 门惯例）；值可读出票号便于历史对账
    assert flow.REDIRECT_PATCH_ID == "t260917-02-inspection-legacy-fire-redirect"
    assert flow.PROJECT_PATCH_ID.startswith("t260915-20-")
    assert flow.SUITE_PATCH_ID.startswith("t260913-02-")
