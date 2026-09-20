#!/usr/bin/env python3
"""t260915-08 场景①：引擎工单板收录巡检票——行面契约黑盒（灰盒 L2，stub temporalio 离线）。

用户场景（工单正文①②+验收①）：宿主在 3099 问「为什么看不见巡检的工单」——巡检票
（InspectionPeriodicWorkflow）不在 ticket-list 的 WorkflowType 过滤里，板面天生黑。
收口后用户可感知行为（方案 v2 R4/R8/R9，review_plan gen1 附条件放行）：
  A. kind=inspection 列表出巡检行：实例/期号/段/发现数/人门态字段齐，等你票可辨；
     待签判定不依赖 face.human_gate（签字前该键常态缺席）；
  B. 历史测试面僵尸（test-face 改名/suite-drill 未声明/mechanism-face 停用）不上板，
     且不为它们发 snapshot 查询（查询前白名单预过滤=坑C）；
  C. 未来闭合行 Flooding 有界（R8）：超窗（CLOSED_HYDRATE_WINDOW_S=7 天）闭合票与
     close_ts 缺失的 COMPLETED 票不上板；窗内闭合票=完整巡检形（非匿名极简行）；
     result() 失败=显式降级行（title 非空点名，绝不匿名）；
  D. 默认列表（无 kind）行集合零变化（R9）：巡检票不进默认板；dev-lane 行形状 parity；
  E. 声明读不到=显式降级（inspection_filter_degraded 顶层标记），不静默；
     dev-lane 行不受累；
  F. 畸形快照（非 dict/findings 非 list/缺 face）不崩，且不株连同板健康票；
  G. ticket-query inspection 分支：engine 标记在位（治坑A——否则 ticket.py _v2_query
     把在飞巡检票谎报「工单不存在」，KI-025 同族新入水口）+ 票面数据进 ticket 面；
     dev-lane 查询回执键集不变。

依据三支：①工单验收「ticket-list 断言巡检票行在场且字段齐（实例/期号/段/发现数/人门
态）／僵尸旧面不上板断言／dev-lane 票列表行形状零变化（parity 断言）」；②KI 账本
（notes/debts/known-issues.md）：KI-003/008（查询降级必须显式——本票巡检分支是同机制
新面）、KI-018①（占位符不得顶替真数据——本票降级行是「无快照可显」的显式降级，与
「顶掉真标题」不同面）、KI-025（查询失败谎报不存在——坑A 即该族）；③契约=方案 v2
R4/R8/R9 行面承诺（.sandbar/plan-t260915-08.md）。

黑盒口径（镜 t260901-23/t02，取舍见方案 §3.5 镜A）：_connect 打桩+假 list_workflows；
与 t02 的关键差别=**假列表按过滤串的 WorkflowType/ProjectKey/EpicCode 原子真过滤**——
「过滤扩展收 InspectionPeriodicWorkflow」本身就是被测行为，桩必须忠实模拟 visibility
侧过滤，否则测的是桩不是引擎。SA 经 typed_search_attributes 假对象直取；重试延迟归零
配置面带过来（t02 先例）。纯离线（stub temporalio+纯 stdlib 声明夹具），无 ENV_FAIL
子用例——环境红捂不住本面。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

跑法：python3 -B integration/t260915-08/sc_inspection_board_rows.py
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
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


# ---------------------------------------------------------------- 假件（过滤串忠实桩）

class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeSAKeys:
    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        return self.kv.get(str(key))


class FakeSA:
    def __init__(self, kv):
        self.typed_search_attributes = FakeSAKeys(kv)


class FakeDesc:
    """cmd_ticket_query 的 describe 桩：raw_description 缺席 → pulse 软降级 None
    （client._pulse_from_desc 的防御路径，契约内）。"""

    def __init__(self, status_name):
        self.status = FakeStatus(status_name)
        self.run_id = "stub-run"
        self.raw_description = None


class FakeHandle:
    def __init__(self, snapshot=None, result_value=None, result_raises=False):
        self.snapshot = snapshot if snapshot is not None else {}
        self.result_value = result_value
        self.result_raises = result_raises
        self.query_count = 0
        self.result_run_id = "stub-run"   # client 查询回执读 handle.result_run_id or run_id
        self.run_id = "stub-run"

    async def query(self, name):
        self.query_count += 1
        if isinstance(self.snapshot, dict) and self.snapshot.get("_stub_timeout"):
            raise asyncio.TimeoutError("stub timeout")
        return self.snapshot

    async def result(self):
        if self.result_raises:
            raise RuntimeError("stub result unavailable")
        return self.result_value

    async def describe(self):
        return FakeDesc("RUNNING" if self.result_value is None and not self.result_raises
                        else "COMPLETED")


class FakeListWf:
    """visibility 行假件：wf_type 参与过滤串判定（桩忠实面）；SA 直取。"""

    def __init__(self, tid, wf_type, status_name, task_queue, kv,
                 close_time=None, start_time=None):
        self.id = tid
        self.wf_type = wf_type
        self.status = FakeStatus(status_name)
        self.task_queue = task_queue
        self.close_time = close_time
        self.start_time = start_time
        self._sa = FakeSA(kv)

    @property
    def typed_search_attributes(self):
        return self._sa.typed_search_attributes


class FakeClient:
    """按过滤串真过滤的假列表：解析 WorkflowType="X" / ProjectKey="Y" / EpicCode="Z"
    原子；有 WorkflowType 原子则 wf.wf_type 必须在集合内；project/epic 原子 AND SA。"""

    def __init__(self, wfs, handles):
        self._wfs = wfs
        self._handles = handles
        self.last_filter = ""

    def get_workflow_handle(self, tid):
        return self._handles[tid]

    async def list_workflows(self, flt):
        import re as _re
        self.last_filter = flt
        types = set(_re.findall(r'WorkflowType="([^"]+)"', flt))
        proj = (_re.findall(r'ProjectKey="([^"]+)"', flt) or [None])[0]
        epic = (_re.findall(r'EpicCode="([^"]+)"', flt) or [None])[0]
        for w in self._wfs:
            if types and w.wf_type not in types:
                continue
            sa = w._sa.typed_search_attributes
            if proj and sa.get("k-project") != proj:
                continue
            if epic and sa.get("k-epic") != epic:
                continue
            yield w


def run_list(args, wfs, handles):
    async def _connect(*a, **k):
        return FakeClient(wfs, handles)

    client_mod._connect = _connect

    async def runner():
        return await client_mod.cmd_ticket_list(dict(args))

    try:
        return asyncio.run(runner())
    except Exception as e:  # noqa: BLE001——列表面契约：任何异常= FAIL 而非 crash 出局
        return {"_scenario_error": "%s: %s" % (type(e).__name__, e)}


def run_query(tid, wfs, handles):
    async def _connect(*a, **k):
        return FakeClient(wfs, handles)

    client_mod._connect = _connect

    async def runner():
        return await client_mod.cmd_ticket_query({"ticket_id": tid})

    try:
        return asyncio.run(runner())
    except Exception as e:  # noqa: BLE001
        return {"_scenario_error": "%s: %s" % (type(e).__name__, e)}


def rows_of(res):
    if res.get("_scenario_error"):
        return None
    return ((res or {}).get("result") or {}).get("tickets")


def row_of(res, tid):
    for r in (rows_of(res) or []):
        if isinstance(r, dict) and r.get("id") == tid:
            return r
    return None


# ---------------------------------------------------------------- 夹具

NOW = datetime(2026, 9, 15, 7, 30, 0, tzinfo=timezone.utc)
DAY = 86400.0
Q = client_mod.TASK_QUEUE if hasattr(client_mod, "TASK_QUEUE") else "suyou-tickets"  # naming-compat

DECL = """schema: v1
instances:
  - id: integration-tests
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 30 7 * * *
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: mechanism-face
    enabled: false
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 7 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

INS_SNAP_TEMPLATE_KEYS = ("id", "kind", "template", "stage", "stage_state", "status",
                          "decision", "face", "timeline", "gate_error")


def insp_face(instance="integration-tests", period="20260915", tid="inspection-integration-tests-20260915",
              human_gate=None, findings=None):
    if findings is None:
        # 6 条：1 high + 2 med + 3 low（与 summary 互锁，发现数断言有真值可对）
        findings = ([{"id": "f1", "scan": "test", "severity": "high", "subject": "s1",
                      "evidence": "e1", "suggestion": "g1"}]
                    + [{"id": "f%d" % i, "scan": "test", "severity": "med", "subject": "s",
                        "evidence": "e", "suggestion": "g"} for i in range(2, 4)]
                    + [{"id": "f%d" % i, "scan": "test", "severity": "low", "subject": "s",
                        "evidence": "e", "suggestion": "g"} for i in range(4, 7)])
    face = {"ticket_id": tid, "kind": "inspection", "instance_id": instance,
            "period": period, "red_line": "巡检只出报告", "heartbeat": True,
            "summary": {"high": 1, "med": 2, "low": 3}, "findings": findings,
            "suggested_fix_tickets": [], "report_path": "out/inspection/%s.json" % tid}
    if human_gate is not None:
        face["human_gate"] = human_gate
    return face


def insp_snap(tid="inspection-integration-tests-20260915", stage="close",
              stage_state="awaiting-human", status="running", **face_kw):
    return {"id": tid, "kind": "inspection", "template": "inspection-lite",
            "stage": stage, "stage_state": stage_state, "status": status,
            "decision": "", "face": insp_face(tid=tid, **face_kw),
            "timeline": [], "gate_error": ""}


def dev_snap():
    # t02 同款 dev-lane 快照形状（meta 键在位）——D 组 parity 的健康对照面
    return {"engine": client_mod.ENGINE_V2,
            "meta": {"id": "t-dev", "title": "开发票", "project": "sandbar",
                     "role": "developer", "status": "dispatched", "stage": "implement",
                     "stage_state": "running", "created": 1700000000, "updated": 1700000100}}


def ins_wf(tid, wf_type="InspectionPeriodicWorkflow", status_name="RUNNING",
           close_time=None, start_time=NOW, instance=None):
    kv = {"k-project": "", "k-epic": ""}
    if instance:
        tid = "inspection-%s-20260915" % instance
    return FakeListWf(tid, wf_type, status_name, Q, kv,
                      close_time=close_time, start_time=start_time)


def dev_wf(tid="t-dev"):
    return FakeListWf(tid, "DevLaneWorkflow", "RUNNING", Q,
                      {"k-project": "sandbar", "k-epic": ""}, start_time=NOW)


def findings_count_of(row):
    """行上发现数读取（灰盒浅绑定）：R4 钉「findings 高中低计数」，实现落点=行
    findings={high,med,low,total}（face.summary 真源优先，逐条重计兜底）；夹具真值
    1high/2med/3low（total 6）。任一契约落点在位且与真值相符即可，都不在=FAIL 并点名
    行键集（报错精确，不留「哪都没找到」悬案）。"""
    if not isinstance(row, dict):
        return None, "行非 dict"
    v = row.get("findings")
    if isinstance(v, dict):
        if v.get("high") == 1 and v.get("med") == 2 and v.get("total") == 6:
            return True, "key=findings{high,med,low,total}"
        return False, "findings 在但值不符：%r" % v
    if isinstance(v, list) and len(v) == 6:
        return True, "key=findings(len)"
    for key in ("summary", "findings_summary", "counts"):
        d = row.get(key)
        if isinstance(d, dict) and d.get("high") == 1 and d.get("med") == 2:
            return True, "key=%s" % key
    return False, "tried findings/summary/findings_summary/counts, row keys=%s" % sorted(row)


# ---------------------------------------------------------------- 用例

def main() -> int:
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="sandbar-t26091508-rows-")
    decl_path = os.path.join(tmp, "inspection.yaml")
    with open(decl_path, "w", encoding="utf-8") as f:
        f.write(DECL)
    old_decl = os.environ.get("SANDBAR_INSPECTION_DECL")
    old_base = os.environ.get("QUERY_RETRY_BASE_DELAY")
    old_jitter = os.environ.get("QUERY_RETRY_JITTER")
    os.environ["SANDBAR_INSPECTION_DECL"] = decl_path
    # 重试延迟归零配置面（镜A 带过来）：降级路径毫秒级跑完
    if hasattr(client_mod, "QUERY_RETRY_BASE_DELAY"):
        client_mod.QUERY_RETRY_BASE_DELAY = 0.0
        client_mod.QUERY_RETRY_JITTER = 0.0
    try:
        print("== A 组：巡检行在场字段齐（kind=inspection）==")
        tid = "inspection-integration-tests-20260915"
        h = FakeHandle(snapshot=insp_snap(tid=tid))
        res = run_list({"kind": "inspection"}, [ins_wf(tid)], {tid: h})
        rows = rows_of(res)
        if res.get("_scenario_error") or rows is None:
            ok(False, "kind=inspection 列表调用崩溃：%r" % res.get("_scenario_error"))
        else:
            row = row_of(res, tid)
            ok(row is not None, "声明的在飞巡检票上板（过滤扩展收 InspectionPeriodicWorkflow）")
            if row is None:
                ok(False, "后续 A 组行面断言无行可验（行集合=%r）" % [r.get("id") for r in rows])
            else:
                ok(row.get("engine") == "inspection",
                   "行 engine=inspection 标记（治坑B：不得喂 ENGINE_V2 误给管理操作位）")
                ok(row.get("instance_id") == "integration-tests" and row.get("period") == "20260915",
                   "实例/期号字段齐（instance_id=%r period=%r）"
                   % (row.get("instance_id"), row.get("period")))
                ok(row.get("stage") == "close" and row.get("stage_state") == "awaiting-human",
                   "当前段/人门态透传（stage=%r stage_state=%r）"
                   % (row.get("stage"), row.get("stage_state")))
                found, detail = findings_count_of(row)
                ok(found, "发现数可读且与票面真值相符（1high/2med/3low）：%s" % detail)
                ok(row.get("human_gate") in (None, "", {}),
                   "待签常态：签字前行不带已签回执（human_gate=%r）" % (row.get("human_gate"),))
                ok(bool(row.get("awaiting_gate")) or row.get("stage_state") == "awaiting-human",
                   "等你态可判（awaiting_gate=%r stage_state=%r——黄行数据源）"
                   % (row.get("awaiting_gate"), row.get("stage_state")))

        print("== A2 组：created 派生（坑D）==")
        st = datetime(2026, 9, 14, 3, 0, 0, tzinfo=timezone.utc)
        res = run_list({"kind": "inspection"},
                       [ins_wf(tid, start_time=st)], {tid: FakeHandle(snapshot=insp_snap(tid=tid))})
        row = row_of(res, tid)
        if row is None:
            ok(False, "created 派生无行可验（巡检行缺席）")
        else:
            expected = st.timestamp()
            ok(abs((row.get("created") or 0) - expected) < 1,
               "created 派生自 wf.start_time（expected≈%s got=%r）" % (expected, row.get("created")))

        print("== B 组：僵尸不上板且零查询（坑C）==")
        zids = {"inspection-test-face-20260910",       # 260910 改名→不在声明
                "inspection-suite-drill-20260911",      # 未声明实例
                "inspection-mechanism-face-20260910"}   # 声明在册但 enabled=false
        zwfs = [ins_wf(t) for t in sorted(zids)]
        zhandles = {t: FakeHandle(snapshot=insp_snap(tid=t)) for t in sorted(zids)}
        good = ins_wf(tid)
        ghandle = FakeHandle(snapshot=insp_snap(tid=tid))
        res = run_list({"kind": "inspection"}, zwfs + [good],
                        dict(zhandles, **{tid: ghandle}))
        rows = rows_of(res)
        if rows is None:
            ok(False, "僵尸组列表调用崩溃：%r" % res.get("_scenario_error"))
        else:
            got = {r.get("id") for r in rows if isinstance(r, dict)}
            ok(not (got & zids), "三类僵尸（改名/未声明/停用实例）全不上板：混入=%r" % (got & zids))
            ok(row_of(res, tid) is not None, "白名单内健康票同拍照常上板")
            ok(all(zhandles[t].query_count == 0 for t in zids),
               "僵尸票零 snapshot 查询（查询前白名单预过滤，白烧负载=0）：%s"
               % {t: zhandles[t].query_count for t in zids})

        print("== C 组：闭合行 Flooding 有界（R8）==")
        old_id = "inspection-integration-tests-20260908"
        wfs = [ins_wf(tid), ins_wf(old_id, status_name="COMPLETED",
                                   close_time=datetime.fromtimestamp(NOW.timestamp() - 8 * DAY, tz=timezone.utc)),
               ins_wf("inspection-integration-tests-20260914", status_name="COMPLETED",
                      close_time=datetime.fromtimestamp(NOW.timestamp() - 1 * DAY, tz=timezone.utc)),
               ins_wf("inspection-integration-tests-20260913", status_name="COMPLETED",
                      close_time=None)]
        handles = {tid: FakeHandle(snapshot=insp_snap(tid=tid)),
                   old_id: FakeHandle(result_value=insp_snap(tid=old_id, status="closed",
                                                             human_gate={"who": "human", "gate": "inspection-close",
                                                                         "decision": "approve", "note": ""})),
                   "inspection-integration-tests-20260914": FakeHandle(result_value=insp_snap(
                       tid="inspection-integration-tests-20260914", status="closed",
                       human_gate={"who": "human", "gate": "inspection-close",
                                   "decision": "approve", "note": ""})),
                   "inspection-integration-tests-20260913": FakeHandle(result_value=insp_snap(
                       tid="inspection-integration-tests-20260913", status="closed"))}
        res = run_list({"kind": "inspection"}, wfs, handles)
        rows = rows_of(res)
        if rows is None:
            ok(False, "闭合组列表调用崩溃：%r" % res.get("_scenario_error"))
        else:
            got = {r.get("id") for r in rows if isinstance(r, dict)}
            ok(old_id not in got, "超窗闭合票（8 天前）不上板：混入=%r" % old_id)
            ok("inspection-integration-tests-20260913" not in got,
               "close_ts 缺失的 COMPLETED 票不上板（畸形防御不收）")
            win = row_of(res, "inspection-integration-tests-20260914")
            ok(win is not None and win.get("kind") == "inspection"
               and str(win.get("title") or "").strip() != "",
               "窗内闭合票=完整巡检形非匿名（kind=%r title=%r）"
               % (win and win.get("kind"), win and win.get("title")))
            ok(win is not None and win.get("status") == "closed",
               "窗内闭合票 status=closed（四态收口折叠数据面）")
            ok(len([r for r in rows if isinstance(r, dict)]) <= 3,
               "板面闭合行有确定上界（窗口常数，本拍 %d 行 ≤ 3）" % len(rows))
        # result() 失败 → 显式降级行（绝不做匿名空行）
        fail_id = "inspection-integration-tests-20260912"
        res = run_list({"kind": "inspection"},
                       [ins_wf(fail_id, status_name="COMPLETED",
                               close_time=datetime.fromtimestamp(NOW.timestamp() - 0.5 * DAY, tz=timezone.utc))],
                       {fail_id: FakeHandle(result_raises=True)})
        row = row_of(res, fail_id)
        if res.get("_scenario_error"):
            ok(False, "result() 失败子用例调用崩溃：%r" % res.get("_scenario_error"))
        elif row is None:
            ok(False, "窗内 result() 失败=行整行消失（丢票比降级更糟）")
        else:
            ok(str(row.get("title") or "").strip() != "",
               "闭合快照读取失败=显式降级行 title 非空点名（got title=%r）" % row.get("title"))

        print("== D 组：默认列表行集合零变化（R9）==")
        res = run_list({}, [dev_wf(), ins_wf(tid)], {tid: FakeHandle(snapshot=insp_snap(tid=tid)),
                                                     "t-dev": FakeHandle(snapshot=dev_snap())})
        rows = rows_of(res)
        if rows is None:
            ok(False, "默认列表调用崩溃：%r" % res.get("_scenario_error"))
        else:
            got = {r.get("id") for r in rows if isinstance(r, dict)}
            ok(tid not in got and "t-dev" in got,
               "无 kind 参数时巡检票不进默认板、dev-lane 照常（got=%r）" % sorted(got))
        res = run_list({}, [dev_wf()], {"t-dev": FakeHandle(snapshot=dev_snap())})
        row = row_of(res, "t-dev")
        pinned = {"id", "project", "epic", "role", "status", "title", "workflow", "proposal_id",
                  "stage", "stage_state", "paused", "paused_phase", "handoff_count",
                  "pending_count", "worktree", "workspace", "created", "updated",
                  "updated_ts", "close_ts", "engine", "exec_status", "authz_active"}
        if row is None:
            ok(False, "dev-lane 行 parity 无行可验")
        else:
            ok(set(row.keys()) == pinned,
               "dev-lane 行键集 parity（今天形状逐键钉死；diff=%r）"
               % (set(row.keys()) ^ pinned))

        print("== E 组：声明不可读=显式降级（不静默）==")
        os.environ["SANDBAR_INSPECTION_DECL"] = os.path.join(tmp, "no-such-decl.yaml")
        res = run_list({"kind": "inspection"}, [ins_wf(tid)], {tid: FakeHandle(snapshot=insp_snap(tid=tid))})
        if res.get("_scenario_error"):
            ok(False, "声明不可读时 kind=inspection 调用崩溃（必须显式降级不崩）：%r"
               % res.get("_scenario_error"))
        else:
            ok(rows_of(res) == [], "声明读不到 → 巡检行全不上板（不猜不静默）")
            info = (res.get("result") or {}).get("inspection_filter") or {}
            degraded_marked = bool(info.get("degraded")) or \
                bool((res.get("result") or {}).get("inspection_filter_degraded"))
            ok(degraded_marked and str(info.get("note") or "") != "",
               "回执带显式降级标记+点名 note（inspection_filter.degraded/note；got %r/%r）"
               % (info.get("degraded"), (info.get("note") or "")[:60]))
        res = run_list({}, [dev_wf()], {"t-dev": FakeHandle(snapshot=dev_snap())})
        ok(row_of(res, "t-dev") is not None and not res.get("_scenario_error"),
           "声明降级不株连 dev-lane 默认板")
        os.environ["SANDBAR_INSPECTION_DECL"] = decl_path

        print("== F 组：畸形快照不崩且不株连 ==")
        # kind=inspection 板面只有巡检类型（R9 分支过滤）——对照健康票用巡检票，
        # dev 票进不了这块板（那正是 D 组守的面）
        healthy = "inspection-integration-tests-20260914"
        cases = [("snap 非 dict", "garbage-string"),
                 ("face 缺失", {"id": tid, "kind": "inspection", "stage": "close",
                                "stage_state": "running", "status": "running"}),
                 ("findings 非 list", {**insp_snap(tid=tid),
                                       "face": {**insp_face(tid=tid), "findings": "oops"}})]
        for label, snap in cases:
            res = run_list({"kind": "inspection"},
                           [ins_wf(tid), ins_wf(healthy)],
                           {tid: FakeHandle(snapshot=snap),
                            healthy: FakeHandle(snapshot=insp_snap(tid=healthy))})
            ok(not res.get("_scenario_error") and isinstance(rows_of(res), list),
               "畸形不崩（%s）：%r" % (label, res.get("_scenario_error")))
            ok(row_of(res, healthy) is not None,
               "畸形不株连同板健康票（%s，%s 行在）" % (label, healthy))

        print("== G 组：ticket-query inspection 分支（治坑A/KI-025 族）==")
        res = run_query(tid, [ins_wf(tid)], {tid: FakeHandle(snapshot=insp_snap(tid=tid))})
        q = res.get("result") if isinstance(res.get("result"), dict) else {}
        if res.get("_scenario_error") or not q:
            ok(False, "ticket-query 巡检子用例崩溃/空回执：%r" % (res.get("_scenario_error"),))
        else:
            ok(q.get("engine") == client_mod.ENGINE_V2,
               "查询回执 engine 标记在位（空值=被 _v2_query 谎报「工单不存在」，KI-025 族）got=%r"
               % q.get("engine"))
            tk = q.get("ticket")
            has_face = isinstance(tk, dict) and (
                isinstance(tk.get("face"), dict)
                or (isinstance(tk.get("summary"), dict) and "instance_id" in tk))
            ok(has_face,
               "票面数据进 ticket 面（详情下钻数据源；tk 键=%r）"
               % (sorted(tk) if isinstance(tk, dict) else tk))
            ok(isinstance(tk, dict) and tk.get("gate_id") == "inspection-close",
               "ticket 面带 gate_id 单点（签字回带依据，零旁路）：%r"
               % (tk.get("gate_id") if isinstance(tk, dict) else None))
        res = run_query("t-dev", [dev_wf()], {"t-dev": FakeHandle(snapshot=dev_snap())})
        q = res.get("result") if isinstance(res.get("result"), dict) else {}
        pinned_q = {"ticket_id", "run_id", "exec_status", "engine", "snapshot", "ticket", "pulse"}
        ok(not res.get("_scenario_error") and set(q.keys()) == pinned_q,
           "dev-lane 查询回执键集 parity（diff=%r）"
           % (set(q.keys()) ^ pinned_q if q else res.get("_scenario_error")))
    finally:
        if old_decl is None:
            os.environ.pop("SANDBAR_INSPECTION_DECL", None)
        else:
            os.environ["SANDBAR_INSPECTION_DECL"] = old_decl
        if old_base is not None:
            os.environ["QUERY_RETRY_BASE_DELAY"] = old_base
        if old_jitter is not None:
            os.environ["QUERY_RETRY_JITTER"] = old_jitter

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
