#!/usr/bin/env python3
"""t260921-03 场景：已结束工单的收口健康度行/详情契约（灰盒 L2，stub temporalio 离线）。

用户场景（工单正文，宿主 260921 实案）：巡检票 t260920-02 / t260921-01 的工作流早已
Temporal COMPLETED（本期没跑出任何报告），但左栏工单列表显示「阻塞在 inspect」——
用户看到一张永远受阻的票，看不出它其实已经结束、更看不出它没产出报告。宿主要求：
已结束的票必须同时表达「结束了」与「怎么结束的（正常/异常）」，异常收口不得看起来
正常，也不得伪装成在跑/阻塞。

收口后引擎侧用户可感知契约（票面验收五条之数据面；呈现面归 sc_close_health_ui_model）：
  A. 每行带可判定收口健康度键 close_health ∈ {'',ok,failed,abnormal,unreadable}
     （'' =未收口在飞；ok=正常收口；failed=失败类终态；abnormal=已完成但缺应有产物；
     unreadable=已结束但收口快照读不到——显式存疑，绝不冒充 ok）。health ∈
     {abnormal,unreadable} 时行必带非空事实原因串 close_health_reason（无因异常禁止）。
     键名行/详情同名（防双键漂移，review 意见3 契约化）。
  B. 六格矩阵（终态×产物，验收①）：COMPLETED×有产物→ok；COMPLETED×无产物（实案形：
     面快照 blocked+findings 0+report_path 缺）→abnormal；COMPLETED×受阻面+落账镜像
     文件在（live 对账发现的实案真形态，t260917-02 起 blocked 收口也落账同名文件）
     →仍 abnormal（健康度看面不看文件名）；FAILED×两格→failed（dev-lane
     与巡检同口径；失败类不参与产物格）；TERMINATED×两格→不产生行（既有僵尸不上板
     纪律原样，票面验收④明文零回归；板面不可达故不设枚举值）。
  C. 实案复现用例（验收②）：面快照 blocked + exec COMPLETED + 无报告 → 行带
     close_health=abnormal + exec_status=COMPLETED + 词面事实原样保留（blocked_reason/
     findings=0 不回填不清洗——历史数据不动，票面边界明文）；详情 meta 带
     exec_status/close_health/close_health_reason（详情终态卡数据源，现状 meta 无
     exec_status=表达缺口，必须补齐）。
  D. 反用例（验收③）：正常收口（有产物）→close_health=ok 且 reason 空（绝不反向
     撒谎）；abnormal 行 reason 必非空；failed 行是 failed 不是 abnormal（两族不混）。
  E. 畸形/边界（输入三态）：face 缺失/非 dict 的 COMPLETED 巡检 → 非 ok（产物不可证
     即不判正常——宁可异常不可假正常）且 reason 点名事实；report_path 非串/None 按缺
     处置；findings 非列表容忍；收口快照读不到的降级行 →unreadable（绝不 ok）+ 真在飞
     的查询超时降级行保持 ''（在飞不误读为已结束，t260915-08 KI-008 口径原样）。
  F. 回归（验收④）：dev-lane 四形状（meta/极简/失败/降级）既有键值逐一零回归、
     close_health 只加不改；四形状 close_health 键 parity（同加全族，不破 t260915-08/
     t260919-02 的键集 parity 口径）；TERMINATED 零 snapshot 查询（资源纪律）；R8 闭合
     窗与白名单口径原样（深钉归 t260915-08-board-rows，本场景只钉「本票改动不扰动」）。
  G. KI-018① 边界声明：本票**新增**字段（close_health/close_health_reason）不得携带
     「刷新重试/查询超时/瞬时」类瞬态占位语——既有降级行 title 的占位语是 KI-018 在册
     面（修复随 observability 票），不属本票范围，不随手修也不豁免新增面。

依据三支：①工单原始 user_request 与验收五条+四组用例口径（上 A-F 逐条对映）；②已知问题清单
（notes/debts/known-issues.md）：KI-018①（open——占位符严禁进新增数据字段）、KI-008
（降级显式性——unreadable 承接其纪律）、KI-055（台面绿×真机红全族排查——本场景钉
引擎数据面全族：两列表面×四形状×详情，不只点名两实案行）；③对外契约=t260921-03
方案 v1 承诺（close_health 词表五值/行键只加不改/详情 meta 补 exec_status）。

分工（防 intent 级重复）：t260915-08-board-rows 深钉巡检行形状/R8 窗/白名单僵尸（彼时
无健康度概念），本条只钉健康度键的存在性与词表语义+零扰动 spot；t260919-02-terminal-
face-board 深钉失败行形状与终态失败面 face 载荷，本条只钉 failed 格与失败行加键零回归
spot；t260916-02/t260917-02 守旧形三代/不可辨在跑，零重叠；UI 词表与呈现半边归
sc_close_health_ui_model，本条不碰任何 UI 源。
纯离线（stub temporalio+纯 stdlib 夹具，镜 t260919-02 共享桩法），无 ENV_FAIL 子用例。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B integration/t260921-03/sc_close_health_board.py
"""
import asyncio
import json
import os
import sys
import tempfile
import time
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

# 查询重试退避压到最小（降级子用例要真走一遍超时路径，但别烧墙钟；常量缺席=容忍，
# 退回真退避也只是慢几秒）
for _k in ("QUERY_RETRY_ATTEMPTS",):
    if hasattr(client_mod, _k):
        setattr(client_mod, _k, 1)
for _k in ("QUERY_RETRY_BASE_S", "QUERY_RETRY_BASE", "QUERY_RETRY_SLEEP_S"):
    if hasattr(client_mod, _k):
        try:
            setattr(client_mod, _k, 0.01)
        except Exception:
            pass

PASS = 0
FAIL = 0

HEALTH_WORDS = {"", "ok", "failed", "abnormal", "unreadable"}
PLACEHOLDER_WORDS = ("刷新重试", "查询超时", "瞬时")   # KI-018①：瞬态占位语不进新增数据字段
FACT_BLOCKED_REASON = 'agent 退出码 1（未完成）；输出尾：unknown preset "read-only"'
FACT_REPORT = "server/engine/out/inspection/inspection-integration-tests-20260922.json"


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


# ---------------------------------------------------------------- 假件（镜 t260919-02 桩法）

class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeSAKeys:
    """SA 桩两态通吃（真 SDK str(key)==键名原词 / 共享桩 tuple key 取第二元）。"""

    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        name = key[1] if isinstance(key, tuple) and len(key) == 2 else str(key)
        return self.kv.get(name)


class FakeSA:
    def __init__(self, kv):
        self.typed_search_attributes = FakeSAKeys(kv)


class FakeDesc:
    def __init__(self, status_name, close_time=None, start_time=None):
        self.status = FakeStatus(status_name)
        self.run_id = "stub-run"
        self.raw_description = None
        self.close_time = close_time
        self.start_time = start_time


class FakeHandle:
    def __init__(self, status_name="RUNNING", snapshot=None, result_value=None,
                 result_raises=False, close_time=None, start_time=None):
        self.status_name = status_name
        self.snapshot = snapshot if snapshot is not None else {}
        self.result_value = result_value
        self.result_raises = result_raises
        self.close_time = close_time
        self.start_time = start_time
        self.query_count = 0
        self.result_count = 0
        self.result_run_id = "stub-run"
        self.run_id = "stub-run"

    async def query(self, name):
        self.query_count += 1
        if isinstance(self.snapshot, dict) and self.snapshot.get("_stub_timeout"):
            raise asyncio.TimeoutError("stub timeout")
        return self.snapshot

    async def result(self):
        self.result_count += 1
        if self.result_raises:
            raise RuntimeError("stub result unavailable")
        return self.result_value

    async def describe(self):
        return FakeDesc(self.status_name, close_time=self.close_time,
                        start_time=self.start_time)


class FakeListWf:
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
    """按过滤串真过滤的假列表（过滤行为是被测面，桩必须忠实——镜 t260919-02）。"""

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
            if proj and sa.get("ProjectKey") != proj:
                continue
            if epic and sa.get("EpicCode") != epic:
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
    except Exception as e:  # noqa: BLE001——板面契约：任何异常=FAIL 而非 crash 出局
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

HOUR = 3600.0
DAY = 86400.0
Q = client_mod.TASK_QUEUE
NOW_DT = datetime.fromtimestamp(time.time(), tz=timezone.utc)


def fresh_close_ts():
    return time.time() - HOUR


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
"""

KV_INSP = {"ProjectKey": "sandbar", "EpicCode": "",
           "InspectionInstance": "integration-tests", "InspectionPeriod": "20260922"}
KV_ZOMBIE = {"ProjectKey": "sandbar", "EpicCode": "",
             "InspectionInstance": "test-face", "InspectionPeriod": "20260909"}  # 白名单外实例
KV_DEV = {"ProjectKey": "sandbar", "EpicCode": ""}

TID_ABN = "inspection-integration-tests-20260922"   # 实案同形：blocked 面无报告
TID_ABN2 = "inspection-integration-tests-20260920"  # 实案真形：blocked 面+落账镜像
TID_OK = "inspection-integration-tests-20260923"    # 正常收口（有报告）
TID_STALE = "inspection-integration-tests-20260901"  # 超窗闭合行（R8 窗外）
TID_ZOMBIE = "inspection-test-face-95711-20260909"  # 白名单外实例（不在册）
TID_DEV_OK = "t-dev-done"
TID_DEV_FAIL = "t-dev-failed"
TID_DEV_MIN = "t-dev-minimal"
TID_DEV_DEG = "t-dev-degraded"


def snap_blocked_no_report(tid):
    """实案复现夹具（验收②用例）：面快照 blocked + 无 report_path 键 + findings 空——
    t260917-02 之前代的 blocked 面形态（引擎 _blocked 不写 report_path）。"""
    return {"id": tid, "kind": "inspection", "template": "inspection-lite",
            "stage": "inspect", "stage_state": "blocked", "status": "blocked",
            "decision": "",
            "face": {"ticket_id": tid, "kind": "inspection",
                     "instance_id": "integration-tests", "period": "20260922",
                     "summary": {}, "findings": [], "suggested_fix_tickets": [],
                     "blocked_reason": FACT_BLOCKED_REASON, "heartbeat": False},
            "timeline": [], "gate_error": ""}


def snap_blocked_with_ledger_mirror(tid):
    """实案真形态夹具（live 对账 260921 发现、t260921-03 实施中收紧）：t260917-02 起
    blocked 收口也落账（dead-man 面），_write_ledger 走 write_inspection_report 同名
    约定并回写 face.report_path——live 的 t260920-02/t260921-01 面即此形：report_path
    在场而文件内容=受阻面镜像（status=blocked、findings 0）。健康度看面不看文件名，
    report_path 在场≠报告在。"""
    snap = snap_blocked_no_report(tid)
    snap["face"]["report_path"] = (
        "/Users/user/Documents/sandbar/server/engine/out/inspection/"
        "inspection-integration-tests-20260920.json")
    return snap


def snap_closed_with_report(tid):
    """正常收口夹具（反用例③）：报告在。status/stage_state 词面无论长什么样，
    close_health 都必须按产物在=ok 判（词面不参与健康度）。"""
    return {"id": tid, "kind": "inspection", "template": "inspection-lite",
            "stage": "close", "stage_state": "awaiting-human", "status": "closed",
            "decision": "",
            "face": {"ticket_id": tid, "kind": "inspection",
                     "instance_id": "integration-tests", "period": "20260923",
                     "summary": {"high": 0, "med": 1, "low": 2},
                     "findings": [{"severity": "med", "title": "样例"},],
                     "suggested_fix_tickets": [],
                     "report_path": FACT_REPORT, "heartbeat": True},
            "timeline": [], "gate_error": ""}


def snap_faceless(tid):
    """畸形夹具（E 组）：COMPLETED 但 face 缺失——产物不可证。"""
    return {"id": tid, "kind": "inspection", "template": "inspection-lite",
            "stage": "close", "stage_state": "awaiting", "status": "closed",
            "decision": "", "timeline": []}


def dev_completed_snap():
    return {"engine": client_mod.ENGINE_V2,
            "meta": {"id": TID_DEV_OK, "title": "开发票", "project": "sandbar",
                     "role": "developer", "status": "closed", "stage": "verify",
                     "stage_state": "awaiting", "created": 1700000000,
                     "updated": 1700000100}}


def insp_wf(tid, status_name="COMPLETED", close_ts=None):
    ct = datetime.fromtimestamp(close_ts if close_ts is not None else fresh_close_ts(),
                                tz=timezone.utc)
    return FakeListWf(tid, "InspectionPeriodicWorkflow", status_name, Q, KV_INSP,
                      close_time=ct, start_time=NOW_DT)


def dev_wf(tid, status_name="COMPLETED", close_ts=None):
    ct = datetime.fromtimestamp(close_ts if close_ts is not None else fresh_close_ts(),
                                tz=timezone.utc)
    return FakeListWf(tid, "DevLaneWorkflow", status_name, Q, KV_DEV,
                      close_time=ct, start_time=NOW_DT)


def meta_of(res):
    """详情 meta 宽容落点（报错精确：取不到点名回执键集，不留悬案）。已证形状=
    cmd_ticket_query 回执 result.ticket（_inspection_query_meta 同构）；兼容顶层
    meta / result.meta 旧形。"""
    if not isinstance(res, dict) or res.get("_scenario_error"):
        return None
    result = res.get("result") if isinstance(res.get("result"), dict) else {}
    for cand in (result.get("ticket"), result.get("meta"), res.get("meta"),
                 res if res.get("kind") == "inspection" else None):
        if isinstance(cand, dict) and cand:
            return cand
    return None


def check_health_key(row, label, expect_health, expect_reason_nonempty=None):
    """健康度行键契约断言（A 组词表 + D 组反用例共用）。键缺席=FAIL 并点名行键集。"""
    if not isinstance(row, dict):
        ok(False, "%s：行不存在（板面回执无此票）" % label)
        return
    health = row.get("close_health", _MISSING)
    ok(health != _MISSING,
       "%s：行带 close_health 键（行键集=%s）" % (label, sorted(row.keys())))
    ok(health in HEALTH_WORDS,
       "%s：close_health 在词表内 %r ⊆ %s" % (label, health, sorted(HEALTH_WORDS)))
    ok(health == expect_health,
       "%s：close_health==%r（got %r）" % (label, expect_health, health))
    reason = row.get("close_health_reason", _MISSING)
    if expect_health in ("abnormal", "unreadable"):
        ok(isinstance(reason, str) and reason.strip() != "",
           "%s：异常收口必带非空事实原因 close_health_reason（got %r；无因异常禁止）"
           % (label, reason))
    elif expect_health == "failed":
        # failed 行 reason 容忍事实串（如执行状态原文——要求④失败面形态），只禁瞬态占位语
        pass
    else:  # ok / ''：健康度正常或在飞就不造原因（反编造）
        ok(reason in ("", None, _MISSING) or str(reason).strip() == "",
           "%s：reason 空或不带（got %r——健康度正常就不造原因）" % (label, reason))
    if isinstance(reason, str):
        for bad in PLACEHOLDER_WORDS:
            ok(bad not in reason,
               "%s：原因串不含「%s」瞬态占位语（KI-018① 新增字段纪律）" % (label, bad))
    if expect_reason_nonempty is not None:
        words = expect_reason_nonempty if isinstance(expect_reason_nonempty, tuple) \
            else (expect_reason_nonempty,)
        ok(any(w in str(reason) for w in words),
           "%s：原因串点名事实（含任一 %s；got %r）" % (label, list(words), reason))


_MISSING = object()


# ---------------------------------------------------------------- 用例

def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sandbar-t26092103-close-health-")
    decl_path = os.path.join(tmp, "inspection.yaml")
    with open(decl_path, "w", encoding="utf-8") as f:
        f.write(DECL)
    old_decl = os.environ.get("SANDBAR_INSPECTION_DECL")
    os.environ["SANDBAR_INSPECTION_DECL"] = decl_path

    fresh = fresh_close_ts()
    stale_ts = time.time() - 8 * DAY   # R8 窗（7 天）外

    # 板面夹具：巡检 4 张 + dev-lane 4 张（覆盖六格与四形状）
    wfs = [
        insp_wf(TID_ABN, "COMPLETED", fresh),          # COMPLETED×无产物（实案形）
        insp_wf(TID_ABN2, "COMPLETED", fresh),         # COMPLETED×受阻面+落账镜像（实案真形）
        insp_wf(TID_OK, "COMPLETED", fresh),           # COMPLETED×有产物
        insp_wf(TID_STALE, "COMPLETED", stale_ts),     # 超窗闭合行（F 组：窗口径原样）
        FakeListWf(TID_ZOMBIE, "InspectionPeriodicWorkflow", "RUNNING", Q, KV_ZOMBIE,
                   start_time=NOW_DT),                 # 白名单外实例（F 组：不上板原样）
        dev_wf(TID_DEV_OK, "COMPLETED", fresh),        # dev COMPLETED（meta 行）
        dev_wf(TID_DEV_FAIL, "FAILED"),                # dev FAILED（失败行）
        dev_wf(TID_DEV_MIN, "COMPLETED", stale_ts),    # dev 超窗（极简行路径）
        dev_wf(TID_DEV_DEG, "RUNNING"),                # dev 在飞（降级行路径）
    ]
    handles = {
        TID_ABN: FakeHandle("COMPLETED", result_value=snap_blocked_no_report(TID_ABN),
                            close_time=fresh),
        TID_ABN2: FakeHandle("COMPLETED", result_value=snap_blocked_with_ledger_mirror(TID_ABN2),
                             close_time=fresh),
        TID_OK: FakeHandle("COMPLETED", result_value=snap_closed_with_report(TID_OK),
                           close_time=fresh),
        TID_STALE: FakeHandle("COMPLETED", result_value=snap_closed_with_report(TID_STALE),
                              close_time=stale_ts),
        TID_ZOMBIE: FakeHandle("RUNNING", snapshot={"id": TID_ZOMBIE}),
        TID_DEV_OK: FakeHandle("COMPLETED", snapshot=dev_completed_snap(), close_time=fresh),
        TID_DEV_FAIL: FakeHandle("FAILED", result_raises=True),
        TID_DEV_MIN: FakeHandle("COMPLETED", snapshot={}, close_time=stale_ts),
        TID_DEV_DEG: FakeHandle("RUNNING", snapshot={"_stub_timeout": True}),
    }

    try:
        # ---- B/C 组：巡检板面（六格 + 实案复现 + 词面事实保留）----
        print("== B/C 组：巡检板面 close_health（实案复现 + 六格 + 词面事实保留）==")
        res = run_list({"kind": "inspection"}, wfs, handles)
        rows = rows_of(res) or []
        ok(res.get("_scenario_error") is None,
           "kind=inspection 板面可离线装配（err=%r)" % res.get("_scenario_error"))
        r_abn = row_of(res, TID_ABN)
        check_health_key(r_abn, "实案形（blocked 面×COMPLETED×无报告）", "abnormal",
                         expect_reason_nonempty=("报告", "report_path"))
        if isinstance(r_abn, dict):
            ok(r_abn.get("exec_status") == "COMPLETED",
               "实案形行带 exec_status=COMPLETED（UI 终态对账的判定输入，行必携带）")
            ok(r_abn.get("blocked_reason") == FACT_BLOCKED_REASON,
               "实案形 blocked_reason 原文保留（不回填不清洗历史数据——票面边界）")
            ok(r_abn.get("findings", {}).get("total") == 0,
               "实案形 findings=0 事实保留（本期无报告的佐证面）")
            ok(r_abn.get("report_path") == "",
               "实案形 report_path 缺→空串（不编造产物路径）")
        # 实案真形（live 对账发现）：blocked 面 + report_path 在场（落账镜像）——
        # 仍 abnormal，绝不因文件在场被误判 ok（健康度看面不看文件名）。
        r_abn2 = row_of(res, TID_ABN2)
        check_health_key(r_abn2, "实案真形（blocked 面×COMPLETED×落账镜像文件在）",
                         "abnormal", expect_reason_nonempty=("受阻面镜像", "报告"))
        if isinstance(r_abn2, dict):
            ok(r_abn2.get("report_path") != "",
               "实案真形 report_path 原样保留（产物路径事实不清洗）")
        r_ok = row_of(res, TID_OK)
        check_health_key(r_ok, "正常收口（有报告）", "ok")
        if isinstance(r_ok, dict):
            ok(r_ok.get("report_path") == FACT_REPORT,
               "正常收口行 report_path 原样（产物事实不清洗）")
        ok(row_of(res, TID_STALE) is None,
           "超 R8 窗闭合行不上板（闭合窗口径原样，验收④零回归）")
        ok(row_of(res, TID_ZOMBIE) is None,
           "白名单外实例不上板（僵尸纪律半边原样，验收④零回归）")

        # ---- B 组：dev-lane 板面（六格 dev 半边 + 四形状加键 parity）----
        print("== B/F 组：dev-lane 板面（failed 格 + 四形状 close_health parity）==")
        res_d = run_list({}, wfs, handles)
        rows_d = rows_of(res_d) or []
        ok(res_d.get("_scenario_error") is None,
           "缺省 dev-lane 板面可离线装配（err=%r)" % res_d.get("_scenario_error"))
        r_devok = row_of(res_d, TID_DEV_OK)
        check_health_key(r_devok, "dev COMPLETED（meta 行）", "ok")
        r_devfail = row_of(res_d, TID_DEV_FAIL)
        check_health_key(r_devfail, "dev FAILED（失败行）", "failed")
        if isinstance(r_devfail, dict):
            ok(r_devfail.get("status") == "failed" and r_devfail.get("stage_state") == "failed",
               "dev FAILED 行失败形原样（t260919-02 形状零回归，只加键不改值）")
            title = str(r_devfail.get("title") or "")
            ok("查询超时" not in title and "刷新重试" not in title,
               "失败行标题仍诚实（t260919-02 KI-018① 锚零回归）")
        r_devmin = row_of(res_d, TID_DEV_MIN)
        check_health_key(r_devmin, "dev 超窗极简行", "ok")
        r_devdeg = row_of(res_d, TID_DEV_DEG)
        check_health_key(r_devdeg, "dev 在飞查询超时降级行", "")
        if isinstance(r_devdeg, dict):
            ok(r_devdeg.get("stage_state") == "running",
               "在飞降级行保持 running 词面（真在跑不误读为已结束——KI-008 口径原样）")
        # parity：无快照族三形状（失败/极简/降级）键集一致（t260919-02 parity 口径的原族——
        # meta 行键集历史上是超集（paused 等仅 meta 分支并键），不进 parity 组，只查带键）
        shapes = [r for r in (r_devfail, r_devmin, r_devdeg) if isinstance(r, dict)]
        if len(shapes) == 3:
            keysets = [set(r.keys()) for r in shapes]
            ok(all(ks == keysets[0] for ks in keysets),
               "dev-lane 无快照族三形状键集 parity 保持（close_health 同加全族；%s)"
               % [len(ks) for ks in keysets])
        allshapes = [r for r in (r_devok, r_devfail, r_devmin, r_devdeg) if isinstance(r, dict)]
        ok(len(allshapes) == 4 and all("close_health" in set(r.keys()) for r in allshapes),
           "四形状都带 close_health（每行一个可判定字段——要求②字面）")

        # ---- C 组：详情 meta（终态卡数据源）----
        print("== C 组：详情 meta 补终态对账数据源（exec_status/close_health/原因/终态时刻）==")
        res_q = run_query(TID_ABN, wfs, handles)
        meta = meta_of(res_q)
        if not isinstance(meta, dict):
            ok(False, "实案票详情 meta 可取得（回执键集=%s）" % sorted((res_q or {}).keys()))
        else:
            ok(meta.get("exec_status") == "COMPLETED",
               "详情 meta 带 exec_status（现状缺失=详情面无法终态对账的根，必须补）")
            check_health_key(meta, "详情 meta", "abnormal", expect_reason_nonempty="报告")
            closeish = json.dumps(meta, ensure_ascii=False, default=str)
            ok(("close_ts" in meta) or ("close_time" in closeish) or ("close_time_txt" in meta),
               "详情带终态时刻数据源（结束方式可表达——要求④「已结束+结束方式」）")

        # ---- E 组：畸形/边界 ----
        print("== E 组：畸形输入三态（face 缺失/非串 report_path/收口快照读不到）==")
        wfs_e = [insp_wf(TID_ABN, "COMPLETED", fresh)]
        handles_e = {TID_ABN: FakeHandle("COMPLETED", result_value=snap_faceless(TID_ABN),
                                         close_time=fresh)}
        res_e = run_list({"kind": "inspection"}, wfs_e, handles_e)
        r_faceless = row_of(res_e, TID_ABN)
        if isinstance(r_faceless, dict):
            ok(r_faceless.get("close_health") in ("abnormal", "unreadable"),
               "face 缺失的 COMPLETED 巡检不判 ok（产物不可证≠产物在——宁可异常不可假正常；"
               "got %r)" % r_faceless.get("close_health"))
            ok(str(r_faceless.get("close_health_reason") or "").strip() != "",
               "face 缺失行仍带非空原因（点名「票面缺失/无法确认」事实）")
        else:
            ok(False, "face 缺失行仍在板（畸形输入不得静默丢行）")
        # 收口快照读不到 → unreadable（显式存疑，绝不冒充 ok）
        wfs_e2 = [insp_wf(TID_ABN, "COMPLETED", fresh)]
        handles_e2 = {TID_ABN: FakeHandle("COMPLETED", result_raises=True, close_time=fresh)}
        res_e2 = run_list({"kind": "inspection"}, wfs_e2, handles_e2)
        r_unread = row_of(res_e2, TID_ABN)
        check_health_key(r_unread, "收口快照读取失败行", "unreadable")
        if isinstance(r_unread, dict):
            ok(r_unread.get("close_health") != "ok",
               "读不到快照绝不判 ok（窗内闭合行读败冒充正常=反向撒谎）")

        # ---- B 组 TERMINATED 两格：不产生行 + 零查询（资源纪律）----
        print("== B/F 组：TERMINATED 两格不上板且零查询（板面不可达故不设枚举值）==")
        h_term = FakeHandle("TERMINATED", result_raises=True)
        wfs_t = [FakeListWf("inspection-integration-tests-20260922t", "InspectionPeriodicWorkflow",
                            "TERMINATED", Q, KV_INSP, close_time=datetime.fromtimestamp(fresh, tz=timezone.utc),
                            start_time=NOW_DT),
                 FakeListWf("t-dev-term", "DevLaneWorkflow", "TERMINATED", Q, KV_DEV,
                            close_time=datetime.fromtimestamp(fresh, tz=timezone.utc),
                            start_time=NOW_DT)]
        res_t = run_list({}, wfs_t, {"t-dev-term": h_term})
        ok(row_of(res_t, "t-dev-term") is None,
           "dev TERMINATED 不上板（僵尸纪律半边原样）")
        res_t2 = run_list({"kind": "inspection"}, wfs_t, {})
        ok(row_of(res_t2, "inspection-integration-tests-20260922t") is None,
           "巡检 TERMINATED 不上板（既有口径原样，验收④）")
        ok(h_term.query_count == 0 and h_term.result_count == 0,
           "TERMINATED 票零 snapshot/result 查询（终态永不可查询，白烧=0）")
    finally:
        if old_decl is None:
            os.environ.pop("SANDBAR_INSPECTION_DECL", None)
        else:
            os.environ["SANDBAR_INSPECTION_DECL"] = old_decl

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
