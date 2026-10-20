"""t260912-03 信号面与接线单测（dev_lane sign intake / 消费留痕 / 四 handler 卫兵 / 源码锁）。

覆盖（方案 S3/S4 + review RC2/RC7/RC8/C2）：
  - dev_lane.sign 的 authorize 分支：合法投递落 meta['authorizations'] + 时间线签发事件 +
    log 记名；refused 各分支（反自签/上限/过期/别票/坏 kind）不进 meta；
  - 不带 authorize 的 sign：既有 merge 人门语义逐字节不变（非 merge 段照旧拒收）；
  - _protected_authz_records / _arbitration_authz 的生效过滤；
  - _record_authz_uses：机读键在场才记（and 只记匹配的 who@issued），缺键/畸形不记；
  - 三个非 dev_lane handler（base/workflows/inspection_flow）的 authorize 卫兵：
    误投不产生任何放行（RC7）；
  - 源码锁：两处仲裁判定点走 arbitration_cap_route、授权推进分支与 pass 同形 _finish（C2）、
    三处 args 带 authorizations、settle 走 exempt_authorized+记名、CLI/节点白名单收口。

UT 零 Temporal 运行时（stub dev_lane.workflow）/零网络/零 git。
"""
import datetime
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base  # noqa: E402
import dev_lane  # noqa: E402
import inspection_flow  # noqa: E402
import shared  # noqa: E402
import workflows  # noqa: E402
from shared import (  # noqa: E402
    AUTH_ARBITRATION_VERDICT,
    AUTH_PROTECTED_PATH,
    AUTHZ_USED_KEY,
    HumanAuthorization,
    Signature,
)

NOW = 1_757_000_000
NOW_DT = datetime.datetime(2026, 9, 12, 12, 0, 0,
                           tzinfo=datetime.timezone.utc)


def _auth(**kw):
    base_kw = dict(kind=AUTH_PROTECTED_PATH, who="宿主",
                   scope=["integration/baselines"],
                   reason="修期望值", expires=int(NOW_DT.timestamp()) + 3600)
    base_kw.update(kw)
    return HumanAuthorization(**base_kw)


def _mk_wf(meta=None, timeline=None, refused=None):
    """免 Temporal 运行时的 DevLaneWorkflow 壳（host_ruling 单测同款套路）。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: False, now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = list(timeline or [])
    wf.refused = list(refused or [])
    wf._sigs = {}
    wf.results = {}
    wf.ticket_id = str((meta or {}).get("ticket_id") or "t-ut")
    return wf


def _sign(wf, sig):
    fn = dev_lane.DevLaneWorkflow.__dict__["sign"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, sig)


def _authz_sig(auth):
    return Signature(who=auth.who, gate="", decision="approve", authorize=auth)


# ---------- intake 接受子用例 ----------

def test_intake_accepts_and_records():
    wf = _mk_wf(meta={"stage": "implement", "stage_state": "blocked", "status": "dispatched"})
    _sign(wf, _authz_sig(_auth()))
    recs = wf.meta.get("authorizations")
    assert isinstance(recs, list) and len(recs) == 1
    r = recs[0]
    assert r["kind"] == AUTH_PROTECTED_PATH and r["who"] == "宿主"
    assert r["scope"] == ["integration/baselines"] and r["uses"] == []
    assert r["issued"] == int(NOW_DT.timestamp())      # issued 由 workflow.now() 盖写
    assert r["expires"] == int(NOW_DT.timestamp()) + 3600
    assert wf.refused == []
    assert any(t.get("state") == "authorized" for t in wf.timeline)
    assert any("human authorization issued" in (e.get("note") or "") for e in wf.meta.get("log") or [])
    # 任意态可投：merge 人门未等待/段非 merge 也照样受理（与 host_ruling 同族）
    assert wf._sigs == {}


def test_intake_overwrites_caller_issued():
    wf = _mk_wf()
    _sign(wf, _authz_sig(_auth(issued=1)))
    assert wf.meta["authorizations"][0]["issued"] == int(NOW_DT.timestamp())


@pytest.mark.parametrize("auth,frag", [
    (_auth(kind="bogus"), "invalid kind"),
    (_auth(who="developer"), "must not self-authorize"),
    (_auth(who="INTEGRATION "), "must not self-authorize"),
    (_auth(who="integration-agent"), "must not self-authorize"),
    (_auth(reason="  "), "missing reason"),
    (_auth(scope=[]), "empty scope"),
    (_auth(expires=int(NOW_DT.timestamp()) - 1), "already passed"),
    (_auth(expires=int(NOW_DT.timestamp()) + shared.AUTHZ_EXPIRES_MAX_SEC + 1), "expires over the cap"),
    (_auth(kind=AUTH_ARBITRATION_VERDICT, scope=["t-other"]), "must be exactly this ticket's id"),
])
def test_intake_refuses_do_not_enter_history(auth, frag):
    wf = _mk_wf()
    _sign(wf, _authz_sig(auth))
    assert "authorizations" not in wf.meta            # 拒收不进事件历史
    assert len(wf.refused) == 1 and frag in wf.refused[0]["why"]
    assert not any(t.get("state") == "authorized" for t in wf.timeline)


def test_plain_signature_semantics_unchanged():
    """不带 authorize：非 merge 等待中照旧拒收；merge 等待中照旧落 _sigs（零回归）。"""
    wf = _mk_wf(meta={"stage": "implement", "stage_state": "running"})
    _sign(wf, Signature(who="宿主", gate="merge", decision="approve", note=""))
    assert wf._sigs == {} and len(wf.refused) == 1
    wf2 = _mk_wf(meta={"stage": "merge", "stage_state": "awaiting-human"})
    _sign(wf2, Signature(who="宿主", gate="merge", decision="approve", note="ok"))
    assert "merge" in wf2._sigs and wf2.refused == []


# ---------- 生效过滤与消费留痕 ----------

def _seed(wf, *recs):
    wf.meta.setdefault("authorizations", []).extend(recs)


def test_protected_records_filters_expired_and_kind():
    wf = _mk_wf()
    now = int(NOW_DT.timestamp())
    _seed(wf,
          {"kind": AUTH_PROTECTED_PATH, "who": "活", "scope": ["a"], "reason": "r",
           "issued": now, "expires": now + 10},
          {"kind": AUTH_PROTECTED_PATH, "who": "死", "scope": ["b"], "reason": "r",
           "issued": now - 100, "expires": now - 1},
          {"kind": AUTH_ARBITRATION_VERDICT, "who": "仲裁", "scope": ["t-ut"],
           "reason": "r", "issued": now, "expires": now + 10})
    got = wf._protected_authz_records()
    assert [r["who"] for r in got] == ["活"]
    assert got[0]["scope"] == ["a"] and got[0]["issued"] == now


def test_arbitration_authz_ticket_and_expiry():
    wf = _mk_wf(meta={"ticket_id": "t-ut"})
    wf.ticket_id = "t-ut"
    now = int(NOW_DT.timestamp())
    _seed(wf,
          {"kind": AUTH_ARBITRATION_VERDICT, "who": "别票", "scope": ["t-other"],
           "reason": "r", "issued": now, "expires": now + 10},
          {"kind": AUTH_ARBITRATION_VERDICT, "who": "过期", "scope": ["t-ut"],
           "reason": "r", "issued": now - 100, "expires": now - 1})
    assert wf._arbitration_authz() is None
    _seed(wf, {"kind": AUTH_ARBITRATION_VERDICT, "who": "本票", "scope": ["t-ut"],
               "reason": "接受判决", "issued": now, "expires": now + 10})
    assert wf._arbitration_authz()["who"] == "本票"


def test_record_authz_uses_only_when_key_present():
    wf = _mk_wf()
    now = int(NOW_DT.timestamp())
    rec = {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["verify.yaml"],
           "reason": "r", "issued": now, "expires": now + 10, "uses": []}
    other = {"kind": AUTH_PROTECTED_PATH, "who": "别人", "scope": ["verify.yaml"],
             "reason": "r", "issued": now + 1, "expires": now + 10, "uses": []}
    _seed(wf, rec, other)
    # 无键（未发生豁免）→ 谁都不记
    wf._record_authz_uses("[worker settle] 工作区已干净", "implement")
    assert rec["uses"] == [] and other["uses"] == []
    # 键在场 → 只记匹配的 who@issued
    wf._record_authz_uses(
        "%s宿主@%d:verify.yaml" % (AUTHZ_USED_KEY, now), "implement")
    assert len(rec["uses"]) == 1 and rec["uses"][0]["stage"] == "implement"
    assert "verify.yaml" in rec["uses"][0]["detail"]
    assert other["uses"] == []
    # 畸形键 → 不炸不记
    wf._record_authz_uses("%swho@abc:x" % AUTHZ_USED_KEY, "implement")
    assert len(rec["uses"]) == 1


# ---------- 三个非 dev_lane handler 的 authorize 卫兵（误投不放行） ----------

def test_base_sign_guard_refuses_authorize():
    wf = object.__new__(base.TicketWorkflowBase)
    wf.refused = []
    wf.meta = {"stage": "approve"}
    fn = base.TicketWorkflowBase.__dict__["sign"]
    fn = getattr(fn, "__func__", fn)
    fn(wf, _authz_sig(_auth()))
    assert len(wf.refused) == 1 and "no authorization face" in wf.refused[0]["why"]
    assert getattr(wf, "_sigs", {}) == {}


def test_workflows_sign_guard_refuses_authorize():
    wf = object.__new__(workflows.ContentPipelineWorkflow)
    wf.refused_attempts = []
    wf._sigs = {}
    wf.signatures = {}
    old = workflows.workflow
    workflows.workflow = SimpleNamespace(
        logger=SimpleNamespace(warn=lambda *a, **k: None,
                               warning=lambda *a, **k: None))
    try:
        fn = workflows.ContentPipelineWorkflow.__dict__["sign"]
        fn = getattr(fn, "__func__", fn)
        fn(wf, _authz_sig(_auth()))
    finally:
        workflows.workflow = old
    assert len(wf.refused_attempts) == 1
    assert "no authorization face" in wf.refused_attempts[0]["why"]
    assert wf._sigs == {} and wf.signatures == {}


def test_inspection_sign_guard_refuses_authorize():
    wf = object.__new__(inspection_flow.InspectionPeriodicWorkflow)
    wf._gate_err = ""
    wf._close_sig = None
    old = inspection_flow.workflow
    inspection_flow.workflow = SimpleNamespace(
        logger=SimpleNamespace(warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    try:
        fn = inspection_flow.InspectionPeriodicWorkflow.__dict__["sign"]
        fn = getattr(fn, "__func__", fn)
        fn(wf, _authz_sig(_auth()))
    finally:
        inspection_flow.workflow = old
    # 260927 报告英文面：拒收事由改英文（语义不变：无授权面 → 拒收不落签字）
    assert wf._close_sig is None and "no authorization face" in wf._gate_err


# ---------- 源码锁（接线不漂移） ----------

def _src(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def test_source_lock_arbitration_sites_use_cap_route():
    src = _src("server/engine/dev_lane.py")
    assert src.count("arbitration_cap_route(") == 2, "两处仲裁判定点都必须走授权感知路由"
    assert "integration_route(verdict, tests_rounds, code_rounds)" in src  # 仅用于判决原文记录


def test_source_lock_authorized_advance_same_shape_as_pass():
    """C2：授权推进分支与 verdict=pass 同形（_finish 落 arbitrate 终态 + _handoff）。
    260923 D 收口拦截插入后，扫描窗按语义边界（至 merge_check 消费点）取块——
    断言集逐条不变（同形四锚全保留），只把定长距离窗换成语义窗（对后续合法插入
    稳健，不弱化覆盖面）。"""
    src = _src("server/engine/dev_lane.py")
    idx = src.find("authz_advance")
    assert idx > 0
    end = src.find('phase = "merge_check"', idx)
    block = src[idx:end if end > idx else idx + 2600]
    assert '_finish("arbitrate"' in block, "授权推进分支必须 _finish 落终态（C2）"
    assert '_handoff("arbitrate"' in block, "授权推进分支必须 _handoff 记判决原文+授权"
    assert "acceptance_walkthrough" in block
    assert src.count("authz_advance") >= 3


def test_source_lock_settle_args_carry_authorizations():
    src = _src("server/engine/dev_lane.py")
    # t261019-32: +2 = the quickmanual lane's work-stage settle_lane and its
    # merge_check call - same discipline, the protected-path authorization
    # record travels into every settle/merge_check construction.
    assert src.count("authorizations=self._protected_authz_records()") == 6, \
        ("six settle-args construction sites (the agent stage / the join "
         "settle_lane / the arbitrate settle_lane / merge_check / the "
         "quickmanual work-stage settle_lane / the quickmanual merge_check) "
         "must all carry the authorization record")
    aa = _src("server/engine/agent_activities.py")
    assert "exempt_authorized(" in aa and "authorized_passage_note(" in aa
    assert "authorizations: Optional[List[Dict[str, Any]]] = None" in aa


def test_source_lock_cli_and_node_entry_closed():
    tk = _src("server/tools/ticket.py")
    assert "if op == 'authorize':" in tk and "def _authorize(a):" in tk
    assert "authorize" in tk.split("_TICKET_CLI_USAGE")[1][:400]
    cl = _src("server/engine/client.py")
    assert 'if op == "authorize":' in cl
    assert "def normalize_authorize_args(" in cl
    assert "authorize=人授权签发" in cl          # USAGE 帮助串
    nd = _src("server/plugins/workbench/node.ts")
    assert "'authorize'" in nd.split("const OPS = new Set(")[1].split(")")[0]
    assert "if (op === 'authorize')" in nd
    # node.ts 的 authorize 分支必须经 ticket.py（审计面），不得直连 signal
    br = nd.split("if (op === 'authorize')")[1][:600]
    assert "runPocCli(cli, ['ticket'" in br


def test_source_lock_snapshot_readability():
    cl = _src("server/engine/client.py")
    assert '"authz_active": len(_authz)' in cl
    tk = _src("server/tools/ticket.py")
    assert "authz_active" in tk and "def _authz_view(" in tk
