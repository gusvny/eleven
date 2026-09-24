"""t260925-01 票：产出型巡检 workflow 层单测（InspectionProduceWorkflow + 起票队列）。

覆盖（方案步4）：
- 结构面：新 workflow 注册进 ALL_WORKFLOWS（worker 识别面）、自带 sign/authorize/
  snapshot/run、独立 gate id（不带报告链 CLOSE_GATE_ID 字面值——防信号串门）；
- 红灯闸 _approve_blockers（A2/A3/A5 三态逐一、授权窄通放行）；
- 起票队列口径（KI-113）：open_period_ticket(per_ticket_queue=True) 起票 task_queue
  =ticket_task_queue(ticket_id)（per-ticket 前缀），≠共享队列；缺省 False 行为不变；
- 起票 input_cls=InspectionProduceInput / workflow_cls=InspectionProduceWorkflow 通。
Fake client 最小实现（async 迭代器），不依赖真 Temporal。
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_flow as flow  # noqa: E402
import inspection_produce as prod  # noqa: E402
import inspection_ticketing as tick  # noqa: E402
import workflows as wf_reg  # noqa: E402


# ---------- 结构面 ----------

def test_produce_workflow_registered_and_structured():
    assert flow.InspectionProduceWorkflow in wf_reg.ALL_WORKFLOWS
    wf = flow.InspectionProduceWorkflow()
    assert all(hasattr(wf, n) for n in ("sign", "authorize", "snapshot", "run"))
    # 独立 gate id：不带报告链 CLOSE_GATE_ID 字面值（防信号串门，方案 C1 第 3 条）
    assert flow.CLOSE_GATE_ID == "inspection-close"
    assert prod.PRODUCE_CLOSE_GATE_ID != flow.CLOSE_GATE_ID
    assert prod.PRODUCE_CLOSE_GATE_ID == "inspection-produce-close"
    assert "setup" in flow.InspectionProduceWorkflow.STAGES
    assert not any(s in flow.InspectionProduceWorkflow.STAGES
                   for s in ("implement", "arbitrate", "design_integration_tests"))


def test_produce_input_defaults():
    inp = flow.InspectionProduceInput(instance_id="doc-sync")
    assert inp.period == "" and inp.project_key == "" and inp.repo_root == ""


def test_gate_literal_mirror_locked():
    """flow 侧字面真源 ↔ produce 侧缺省参数镜像：等值机械锁（漂移即红）。"""
    assert flow.PRODUCE_CLOSE_GATE_ID == prod.PRODUCE_CLOSE_GATE_ID
    assert flow.PRODUCE_AUTHORIZE_GATE_ID == prod.PRODUCE_AUTHORIZE_GATE_ID


def test_authorize_rerun_has_consumer():
    """F-1 回归锁（验收 gen0 打回点）：授权复跑请求必须有消费点——
    finalize 的门等待条件含 _rerun_paths，且 produce 活动以 focus=授权清单复跑。"""
    import inspect as _insp
    src = _insp.getsource(flow.InspectionProduceWorkflow._finalize_and_close)
    assert "_close_sig is not None or bool(self._rerun_paths)" in src
    assert '"focus": rerun_paths' in src
    assert src.count("run_inspection_produce") == 1  # 复跑调用点恰一个（首趟在 run）
    run_src = _insp.getsource(flow.InspectionProduceWorkflow.run)
    assert '"focus": []' in run_src  # 首趟无 focus


def test_open_produce_route_wrapper_defaults():
    """起票路由薄壳 open_produce_period_ticket：produce 定形（队列+workflow 类）单点。"""
    import inspect as _insp
    src = _insp.getsource(tick.open_produce_period_ticket)
    assert "per_ticket_queue" in src and "InspectionProduceWorkflow" in src


# ---------- 红灯闸（approve blockers） ----------

def _wf_with_authorized(paths):
    wf = object.__new__(flow.InspectionProduceWorkflow)
    wf._authorized = list(paths)
    return wf


def test_blockers_out_of_root_named():
    wf = _wf_with_authorized([])
    sc = {"out_of_root": [{"path": "server/x.py", "reason": "越出文档根 docs"}],
          "protected_overlap": [], "zero_change_error": ""}
    b = wf._approve_blockers(sc)
    assert len(b) == 1 and "A2" in b[0] and "server/x.py" in b[0]


def test_blockers_zero_change_red():
    wf = _wf_with_authorized([])
    b = wf._approve_blockers({"out_of_root": [], "protected_overlap": [],
                              "zero_change_error": "evidence 空"})
    assert len(b) == 1 and "A5" in b[0]


def test_blockers_protected_unauthorized_named():
    wf = _wf_with_authorized([])
    b = wf._approve_blockers({"out_of_root": [], "zero_change_error": "",
                              "protected_overlap": ["docs/design"]})
    assert len(b) == 1 and "A3" in b[0] and "docs/design" in b[0] \
        and prod.PRODUCE_AUTHORIZE_GATE_ID in b[0]


def test_blockers_authorized_protected_passes():
    wf = _wf_with_authorized(["docs/design"])
    b = wf._approve_blockers({"out_of_root": [], "zero_change_error": "",
                              "protected_overlap": ["docs/design"]})
    assert b == []


def test_blockers_all_clear():
    wf = _wf_with_authorized([])
    assert wf._approve_blockers({"out_of_root": [], "zero_change_error": "",
                                 "protected_overlap": []}) == []


# ---------- 起票队列口径（KI-113） ----------

class _Status:
    """SDK WorkflowExecutionStatus 桩（.name 面，describe_period_run 消费）。"""

    def __init__(self, name: str):
        self.name = name


class _FakeHandle:
    first_execution_run_id = "run-1"

    def __init__(self, wf: "_FakeWf"):
        self._wf = wf

    async def describe(self):
        class _Desc:
            pass
        d = _Desc()
        d.status = _Status(self._wf.status)
        d.search_attributes = dict(self._wf.sa)
        return d


class _FakeWf:
    def __init__(self, wid, sa, status="RUNNING"):
        self.id = wid
        self.sa = sa
        self.status = status


class _FakeClient:
    """最小 fake：list_workflows=按查询键值过滤已起票（dedup 面）；get_workflow_handle
    → describe 带 status/sa（KI-114/t260925-09 状态感知去重面）；start_workflow 捕获
    queue/wf_cls/payload。"""

    def __init__(self):
        self.wfs = {}
        self.started = None

    async def list_workflows(self, query):
        import re as _re
        # WorkflowType 条件不参与过滤（fake 同时服务两族 workflow 类型，真实后端
        # 的类型过滤由 SA 组合覆盖）
        conds = [(k, v) for k, v in _re.findall(r'(\w+)="([^"]*)"', query)
                 if k != "WorkflowType"]
        for w in self.wfs.values():
            if all(w.sa.get(k) == v for k, v in conds):
                yield w

    def get_workflow_handle(self, ticket_id):
        return _FakeHandle(self.wfs[ticket_id])

    async def start_workflow(self, wf_cls, payload, id=None, task_queue=None,
                             search_attributes=None, **kw):
        sa = {}
        try:
            for p in (search_attributes or []):
                sa[p.key.name] = p.value
        except TypeError:
            sa = {}
        self.wfs[id] = _FakeWf(id, sa)
        self.started = {"wf_cls": wf_cls, "payload": payload, "id": id,
                        "queue": task_queue}
        return _FakeHandle(self.wfs[id])


def _open(client, tmp_path, **kw):
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(tmp_path / "ledger")
    try:
        base = dict(instance_id="doc-sync", period="20260925", project_key="sandbar",
                    repo_root="/repo", scan_face="doc", decl_path="", task_queue="tq")
        base.update(kw)
        return asyncio.run(tick.open_period_ticket(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def test_open_produce_ticket_uses_per_ticket_queue(tmp_path):
    """KI-113 口径：produce 起票队列=ticket_task_queue(<ticket_id>)，不落共享队列。"""
    from inspection_flow import InspectionProduceInput, InspectionProduceWorkflow
    from shared import ticket_task_queue
    c = _FakeClient()
    r = _open(c, tmp_path, per_ticket_queue=True,
              workflow_cls=InspectionProduceWorkflow,
              input_cls=InspectionProduceInput)
    assert r["ok"] is True and r["result"]["triggered"] is True
    st = c.started
    assert st["queue"] == ticket_task_queue(r["result"]["ticket_id"])
    assert st["queue"] != "tq"
    assert st["wf_cls"] is InspectionProduceWorkflow
    assert isinstance(st["payload"], InspectionProduceInput)


def test_open_ticket_default_queue_unchanged(tmp_path):
    """缺省（per_ticket_queue=False）=现状零行为：task_queue 透传原值（A6）。"""
    c = _FakeClient()
    r = _open(c, tmp_path)
    assert r["ok"] is True
    assert c.started["queue"] == "tq"


def test_open_produce_ticket_dedup_still_one_period_one_ticket(tmp_path):
    """一期一票不变：同实例同期第二次起票=deduped（SA 查询命中第一张），不开第二张。"""
    from inspection_flow import InspectionProduceInput, InspectionProduceWorkflow
    c = _FakeClient()
    kw = dict(per_ticket_queue=True, workflow_cls=InspectionProduceWorkflow,
              input_cls=InspectionProduceInput)
    r1 = _open(c, tmp_path, **kw)
    assert r1["ok"] is True and r1["result"]["triggered"] is True
    r2 = _open(c, tmp_path, **kw)
    assert r2["ok"] is True and r2["result"]["deduped"] is True
    assert r2["result"]["dedup_source"] == "sa_query"
    assert r2["result"].get("period_state") == "live"


def test_open_produce_ticket_terminated_frees_period_slot(tmp_path):
    """t260925-09 新语义：终止票（TERMINATED）释放期槽位——同期重开=开新票而非
    deduped；活票照旧 dedup（上一测试）。produce 路由随语义升级零额外分支。"""
    from inspection_flow import InspectionProduceInput, InspectionProduceWorkflow
    c = _FakeClient()
    kw = dict(per_ticket_queue=True, workflow_cls=InspectionProduceWorkflow,
              input_cls=InspectionProduceInput)
    r1 = _open(c, tmp_path, **kw)
    assert r1["ok"] is True
    old_id = r1["result"]["ticket_id"]
    c.wfs[old_id].status = "TERMINATED"  # 期票被终止（KI-114 槽位释放）
    r2 = _open(c, tmp_path, **kw)
    assert r2["ok"] is True and r2["result"]["triggered"] is True
    assert r2["result"]["ticket_id"] != old_id  # 新票承接，期槽位不复用旧号
    assert r2["result"].get("superseded_ticket_id") == old_id  # 重开审计链接
