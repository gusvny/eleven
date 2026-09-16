#!/usr/bin/env python3
"""t260916-05 场景②：巡检查询回执携带拓扑导出的缝契约（灰盒 L2，stub temporalio 离线）。

用户场景（工单验收①的数据半）：宿主打开巡检票详情看到泳道图——图的数据源是
ticket-query 回执里的 topology 键。前端渲染面由 sc_inspection_detail_lane_map_dom
（API 桩）守；本条守**引擎数据半**：拓扑真的从 workflow snapshot 流到查询回执的
ticket 面——缝断了（snapshot 有、回执没有）则图永远出不来且 DOM 场景的桩测不出来。

用户可感知行为契约（方案 §1.1③/§1.3，review_plan gen1 附条件放行）：
  T1. 新实例常态（snapshot 带 topology）→回执 ticket 面 topology **原样透传**
      （逐键相等不重形：version=topology-v1/template=inspection-lite/5 节点/
      线性 4 边/close kind=human/setup·suite optional=仅套件档），snapshot 通道
      同在（双通道互证）；**face 既有字段不因加键丢失**（findings/summary/
      report_path/gate_id/instance_id/period 照常——加键挤掉既有面=立即红）；
  T2. 老实例重放常态（snapshot 无 topology，_patched 门关）→回执**无 topology 键**
      且 face 照常（省键降级契约，绝不编造）；
  T3. topology 畸形三态（非 dict：123/'garbage'/[]）→无键不炸、face 照常
      （fail-soft 守卫——查询边界绝不抛，抛了就是 KI-025 族谎报温床）。

依据三支：①工单验收①「巡检票详情渲染出泳道图」的数据链半+方案 additive 键纪律；
②KI 账本：KI-025（查询层谎报/抛错形态）、KI-046/049（缝没接通/测试在场≠生效——
本条即查询缝的独立锁定面）；③契约=方案承诺「_inspection_query_meta 透传 topology
（dict 才带键，缺省/畸形省键）」。黑盒口径镜 t260915-08-board-rows（_connect 打桩+
假 handle，过滤桩不适用本条——查询不走 visibility）。纯离线（stub temporalio+纯
stdlib 夹具），无 ENV_FAIL 腿——环境红捂不住本面。

分工（防 intent 级重复）：t260915-08-board-rows G 组守巡检分支 engine 标记+face
可达+dev-lane 查询键集 parity（本条不重复）；snapshot 门两态的 workflow 侧归
developer L1（镜 test_template_topology F 腿）；t260916-05-detail-lane-map-dom 守
消费端渲染；t260916-05-dual-source-lock 守双真源同步锁活性。
实现段落地前红属预期（TDD 信号：T1 红=透传缝未接；T2/T3 应即绿），arbitrate/merge
期必须绿。

跑法：python3 -B integration/t260916-05/sc_inspection_topology_receipt.py
"""
import asyncio
import copy
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "engine"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "t260901-23"))
sys.path.insert(0, str(POC))

import _stub_temporalio  # noqa: E402  # client 顶层 import temporalio——无包环境先装桩
_stub_temporalio.install()

import client as client_mod  # noqa: E402

# 查询重试延迟归零（stub 永不超时；防御性归零保持秒级，t02/board-rows 先例）
for _k in ("QUERY_RETRY_BASE_DELAY", "QUERY_RETRY_JITTER"):
    os.environ.setdefault(_k, "0")

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


# ---------------------------------------------------------------- 假件（查询路径最小桩）

class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeDesc:
    """cmd_ticket_query 的 describe 桩：raw_description 缺席 → pulse 软降级 None（契约内）。"""

    def __init__(self, status_name="RUNNING"):
        self.status = FakeStatus(status_name)
        self.run_id = "stub-run"
        self.raw_description = None
        self.typed_search_attributes = type("SA", (), {"get": staticmethod(lambda k: None)})()


class FakeHandle:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.query_count = 0
        self.result_run_id = "stub-run"
        self.run_id = "stub-run"

    async def query(self, name):
        self.query_count += 1
        return self.snapshot

    async def result(self):
        return {}

    async def describe(self):
        return FakeDesc("RUNNING")


class FakeClient:
    def __init__(self, handles):
        self._handles = handles

    def get_workflow_handle(self, tid):
        return self._handles[tid]


def run_query(tid, snap):
    async def _connect(*a, **k):
        return FakeClient({tid: FakeHandle(snap)})

    client_mod._connect = _connect

    async def runner():
        return await client_mod.cmd_ticket_query({"ticket_id": tid})

    try:
        return asyncio.run(runner())
    except Exception as e:  # noqa: BLE001——回执契约：任何异常= FAIL 而非 crash 出局
        return {"_scenario_error": "%s: %s" % (type(e).__name__, e)}


def receipt_of(res):
    """(回执 ticket 面, 原样 snapshot)；场景错误时 (None, None)。"""
    if not isinstance(res, dict) or res.get("_scenario_error"):
        return None, None
    q = res.get("result")
    if not isinstance(q, dict):
        return None, None
    tk = q.get("ticket") if isinstance(q.get("ticket"), dict) else None
    return tk, q.get("snapshot")


# ---------------------------------------------------------------- 夹具

TID = "inspection-fixture-20260916"

TOPO = {
    "version": "topology-v1",
    "template": "inspection-lite",
    "name": "巡检",
    "nodes": [
        {"id": "setup", "label": "泳道准备", "role": "", "kind": "gate",
         "parts": ["script"], "optional": "仅套件档"},
        {"id": "scan", "label": "扫描", "role": "", "kind": "gate", "parts": ["script"]},
        {"id": "suite", "label": "巡检泳道套件", "role": "", "kind": "gate",
         "parts": ["script"], "optional": "仅套件档"},
        {"id": "report", "label": "落账", "role": "", "kind": "gate", "parts": ["script"]},
        {"id": "close", "label": "人审收口", "role": "", "kind": "human",
         "parts": ["human", "script"]},
    ],
    "edges": [["setup", "scan"], ["scan", "suite"], ["suite", "report"], ["report", "close"]],
    "groups": [],
}

INSPECTION_IDS = ["setup", "scan", "suite", "report", "close"]


def ins_snap(topology="present"):
    """巡检 workflow snapshot 契约形状（inspection_flow.py snapshot 键面）。
    topology='present' 带契约夹具；None=老实例重放态（无键）；其余值=注入畸形。"""
    snap = {
        "id": TID,
        "kind": "inspection",
        "template": "inspection-lite",
        "project": "sandbar",
        "stage": "scan",
        "stage_state": "running",
        "status": "running",
        "decision": "",
        "face": {
            "instance_id": "fixture",
            "period": "20260916",
            "report_path": "out/inspection/fixture-20260916.json",
            "red_line": "巡检只出报告与开票建议，绝不直接改码。",
            "heartbeat": True,
            "summary": {"high": 0, "med": 1, "low": 1},
            "findings": [
                {"id": "f1", "scan": "test", "severity": "med", "subject": "中危样例"},
                {"id": "f2", "scan": "test", "severity": "low", "subject": "低危样例"},
            ],
            "suggested_fix_tickets": [],
            "blocked_reason": "",
        },
        "timeline": [
            {"at": "2026-09-16T08:00:00", "stage": "setup", "state": "running", "reason": "泳道准备"},
            {"at": "2026-09-16T08:01:00", "stage": "scan", "state": "running", "reason": "扫描"},
        ],
        "gate_error": "",
    }
    if topology == "present":
        snap["topology"] = copy.deepcopy(TOPO)
    elif topology is not None:
        snap["topology"] = topology
    return snap


def face_ok(tk, where):
    """face 既有字段不因 topology 加键/降级丢失（T1/T2/T3 共用健康面）。"""
    ok(isinstance(tk, dict), "%s：回执 ticket 面是 dict" % where)
    if not isinstance(tk, dict):
        return
    ok(tk.get("gate_id") == "inspection-close",
       "%s：gate_id 单点在位（签字回带依据）：%r" % (where, tk.get("gate_id")))
    ok(isinstance(tk.get("findings"), list) and len(tk["findings"]) == 2,
       "%s：findings 两条照常（加键不挤既有面）：%r"
       % (where, len(tk.get("findings") or []) if isinstance(tk.get("findings"), list) else tk.get("findings")))
    ok(tk.get("instance_id") == "fixture" and tk.get("period") == "20260916",
       "%s：instance_id/period 照常：%r/%r" % (where, tk.get("instance_id"), tk.get("period")))
    ok(tk.get("report_path") == "out/inspection/fixture-20260916.json",
       "%s：report_path 照常：%r" % (where, tk.get("report_path")))
    ok(isinstance(tk.get("summary"), dict) and tk["summary"].get("med") == 1,
       "%s：summary 照常：%r" % (where, tk.get("summary")))


# ---------------------------------------------------------------- 场景

def main():
    print("== T1 新实例常态：snapshot 带 topology → 回执原样透传+face 不丢")
    res1 = run_query(TID, ins_snap())
    tk, raw = receipt_of(res1)
    if not isinstance(tk, dict):
        err = res1.get("_scenario_error") if isinstance(res1, dict) else None
        ok(False, "T1：查询回执不可读——透传缝未接或查询炸（TDD 红属预期）：%r"
           % (err or res1,))
    else:
        ok(True, "T1：查询回执 ok 且 ticket 面是 dict")
        ok(tk.get("topology") == TOPO,
           "T1：ticket 面 topology 原样透传（逐键相等不重形）%s"
           % ("" if tk.get("topology") == TOPO else "：实得 %r" % (tk.get("topology"),)))
        topo = tk.get("topology")
        if isinstance(topo, dict):
            ok(topo.get("version") == "topology-v1" and topo.get("template") == "inspection-lite",
               "T1：契约头 version/template 在位：%r/%r" % (topo.get("version"), topo.get("template")))
            nodes = topo.get("nodes") if isinstance(topo.get("nodes"), list) else []
            ids = [n.get("id") for n in nodes if isinstance(n, dict)]
            ok(ids == INSPECTION_IDS,
               "T1：节点集==阶段声明全集且有序：%r" % (ids,))
            edges = topo.get("edges") if isinstance(topo.get("edges"), list) else []
            ok(len(edges) == 4,
               "T1：线性 4 边（setup→scan→suite→report→close）：%r" % (edges,))
            human = [n for n in nodes if isinstance(n, dict) and n.get("kind") == "human"]
            ok(len(human) == 1 and human[0].get("id") == "close",
               "T1：人门标记恰落 close（kind=human）：%r"
               % ([n.get("id") for n in human],))
            opts = {n.get("id"): n.get("optional") for n in nodes
                    if isinstance(n, dict) and n.get("optional")}
            ok(opts == {"setup": "仅套件档", "suite": "仅套件档"},
               "T1：条件段注记恰 setup+suite=仅套件档：%r" % (opts,))
        else:
            ok(False, "T1：topology 非 dict——形状五腿随缝接通转绿：%r" % (topo,))
        ok(isinstance(raw, dict) and isinstance(raw.get("topology"), dict),
           "T1：snapshot 通道 topology 同在（双通道互证）")
        face_ok(tk, "T1")

    print("== T2 老实例重放常态：snapshot 无 topology → 回执省键不编造")
    tk2, _ = receipt_of(run_query(TID, ins_snap(topology=None)))
    if isinstance(tk2, dict):
        ok("topology" not in tk2,
           "T2：无 topology 键（省键降级，绝不编造）：%r" % (tk2.get("topology"),))
        face_ok(tk2, "T2")
    else:
        ok(False, "T2：回执不可读（省键态炸了=fail-soft 契约破）")

    print("== T3 畸形三态：topology 非 dict → 无键不炸 face 照常")
    for i, bad in enumerate([123, "garbage", ["not", "a", "dict"]]):
        tk3, _ = receipt_of(run_query(TID, ins_snap(topology=bad)))
        if isinstance(tk3, dict):
            ok("topology" not in tk3,
               "T3.%d：畸形 %r → 省键不透传：%r" % (i + 1, bad, tk3.get("topology")))
            face_ok(tk3, "T3.%d" % (i + 1))
        else:
            ok(False, "T3.%d：畸形 %r → 查询炸了（fail-soft 契约破）" % (i + 1, bad))

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
