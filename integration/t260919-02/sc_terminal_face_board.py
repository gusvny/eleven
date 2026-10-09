#!/usr/bin/env python3
"""t260919-02 场景：终态失败票两面可见——列表失败行 + 详情失败面（灰盒 L2，stub temporalio 离线）。

用户场景（工单正文，260919 实案）：巡检票 t260919-01 / t260918-01 的工作流早已是
Temporal 终态 FAILED，但票板两个面都看不见——(a) 列表行照旧显示在跑（status=dispatched /
stage_state=running，用户看到一张永远在跑、永不动弹的票）；(b) 点开详情只闪一句错误，
详情面板空白，看不到「它为什么失败」。

收口后用户可感知行为（票面验收三条 + 方案 v1 承诺，.sandbar/plan_t260919-02.md）：
  A. 终态失败票的列表行不得再显「在跑」：status/stage_state 不落 dispatched/running 形、
     不与 done（closed）混同；行带失败标记（exec_status=FAILED 在行上可辨）；
     标题诚实——绝不出现「查询超时，刷新重试」占位符（KI-018① 家族：错误文案不得
     顶替数据字段）；巡检行票身份（实例/期号）不因失败丢失；
  B. dev-lane 形失败行同口径（极简行不再 status=""/awaiting 被 UI 缺省推成在跑），
     行键集 parity（不加新键，t260915-08 R9 口径）；
  C. 终态失败票详情：回执 kind=terminal（KI-025 分级不变）、文案仍明说「刷新无效」
     （绝不诱导刷新/绝不谎报瞬时/绝不谎报不存在），并带可渲染失败面 face：
     执行状态、失败原因串、终态时刻、票身份（巡检含实例与期号）、「无快照及为何无」
     显式说明——绝不空面、绝不编造；
  D. 反用例：终态但原因不可得 → face 显式「原因不可得」并保留执行状态（票面验收②原文）；
     畸形 desc（无 close_time / SA 读炸）→ face 显式降级不崩、kind 仍 terminal；
  E. 资源纪律：失败行不发注定失败的 snapshot 查询（终态快照永不可查询，KI-003 族
     超时窗白烧=0）；
  F. 回归：混合板各行其形不串行（RUNNING=在跑原样 / COMPLETED 窗内=closed 原样 /
     FAILED=失败形），TERMINATED 不上板且零查询（僵尸纪律半边原样）。

依据三支：①工单验收口径原文（列表失败态可辨/详情失败面含原因串/反用例原因不可得/
回归用例 RUNNING、COMPLETED、TERMINATED 与 KI-025 家族零回归）；②KI 账本
（notes/debts/known-issues.md）：KI-025（fixed——kind 分级与「刷新无效」文案是本票
红线，face 加键不得破）、KI-018①（open——「占位符文案被当作数据写进 title」正是本票
病灶实例，失败行注入用例对应之）、KI-003/008（查询降级显式性——失败票零白烧查询）；
③契约=方案 v1 承诺（失败行 status/stage_state="failed"、_err 回执可选 face 顶层键、
kind=terminal 与 410 分级一字不改）。

黑盒口径（镜 t260915-08/board-rows 桩法，共享夹具 _stub_temporalio 复用）：_connect
打桩+假 list_workflows 按 WorkflowType/ProjectKey/EpicCode 原子真过滤（过滤行为本身
是被测面，桩必须忠实）；SA 桩两态通吃（真 SDK str(key)==键名原词 / 桩 tuple key 取
第二元）。face 内容断言走宽容多落点 helper（镜 t260915-08 findings_count_of 手法：
任一契约落点在位且语义相符即可，全不在=FAIL 并点名键集——报错精确纪律）。
纯离线（stub temporalio+纯 stdlib 声明夹具），无 ENV_FAIL 子用例——环境红捂不住本面。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

跑法：python3 -B integration/t260919-02/sc_terminal_face_board.py
"""
import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
    """SA 桩三态通吃（t260921-03 顺便修复）：真 SDK 键对象取 .name（_stub_temporalio
    改为「真包可导入即不装桩」后，引擎 venv 下本场景跑的是真 temporalio 的
    SearchAttributeKey，真键对象 str() 未必等于键名原词，假 SA 表（字符串键）取不到
    → 行 project 恒空假红）；共享桩 for_keyword 返回 ("kw", name) 二元组取第二元；
    字符串键原样——三种形态都不丢。"""

    def __init__(self, kv):
        self.kv = kv

    def get(self, key):
        if isinstance(key, tuple) and len(key) == 2:
            name = key[1]
        else:
            name = getattr(key, "name", None) or str(key)
        return self.kv.get(name)


class FakeSA:
    def __init__(self, kv):
        self.typed_search_attributes = FakeSAKeys(kv)


class FakeSABroken:
    """SA 读炸桩（D2 畸形子用例）：读取即抛——face 构造必须 try/except 降级，不崩。"""

    @property
    def typed_search_attributes(self):
        raise RuntimeError("stub SA store unavailable")


class FakeDesc:
    """cmd_ticket_query 的 describe 桩。close_time 显式传 None=「终态但无闭合时刻」
    畸形子用例；缺属性形态由 Broken 变体覆盖（实现须 getattr/try 防御）。"""

    def __init__(self, status_name, close_time=None, start_time=None, broken=False):
        self.status = FakeStatus(status_name)
        self.run_id = "stub-run"
        self.raw_description = None
        if not broken:
            self.close_time = close_time
            self.start_time = start_time


class BrokenDesc(FakeDesc):
    """无 close_time/start_time 属性的 desc（畸形三态之「缺失」）。"""

    def __init__(self, status_name):
        super().__init__(status_name, broken=True)


class FakeHandle:
    def __init__(self, status_name="RUNNING", snapshot=None, result_value=None,
                 result_raises=False, raise_exc=None, close_time=None, start_time=None):
        self.status_name = status_name
        self.snapshot = snapshot if snapshot is not None else {}
        self.result_value = result_value
        self.result_raises = result_raises
        self.raise_exc = raise_exc
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
            raise self.raise_exc or RuntimeError("stub result unavailable")
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
    """按过滤串真过滤的假列表（镜 t260915-08）：解析 WorkflowType="X" / ProjectKey="Y"
    / EpicCode="Z" 原子；有 WorkflowType 原子则 wf.wf_type 必须在集合内；project/epic
    原子 AND SA。"""

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
    except Exception as e:  # noqa: BLE001——板面契约：任何异常= FAIL 而非 crash 出局
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

NOW = datetime(2026, 9, 19, 7, 30, 0, tzinfo=timezone.utc)

# 260928 修（**时间炸弹**，KI-136/KI-137「桩时钟与判据时钟不同源 ⇒ 用例有保质期」家族）：
# 本场景原来把所有 close_time 钉在冻结常量 NOW（2026-09-19）上，而产品侧「闭合行只在
# 7 天 hydrate 窗内上板」（client.CLOSED_HYDRATE_WINDOW_S = 7*86400）吃的是**真墙钟**
# ⇒ 2026-09-26 之后 F 组 COMPLETED 行必被窗杀（实测：COMPLETED 行 got None、板面 3 行
# got 2）。修法=桩喂相对此刻的终态时刻（恒在窗内）；冻结的 NOW 只留给需要稳定字面量的
# 面（如 start_time）。
def _closed_ago(hours: float = 1.0) -> datetime:
    """「真此刻 − hours」的终态时刻（与判据时钟同源；恒落在 hydrate 窗内）。"""
    return datetime.now(timezone.utc) - timedelta(hours=hours)

HOUR = 3600.0
Q = client_mod.TASK_QUEUE

TID_F = "inspection-integration-tests-20260919"   # 实案同形：实例 integration-tests，09-19 期
PERIOD = "20260919"
INSTANCE = "integration-tests"

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
           "InspectionInstance": INSTANCE, "InspectionPeriod": PERIOD}
KV_DEV = {"ProjectKey": "sandbar", "EpicCode": ""}


def insp_closed_snap(tid, close_note=""):
    """窗内闭合巡检票的完整终态快照（result() 返回值=run() 返回 _snapshot() 形状）——
    F 组 COMPLETED 回归用例用（t260915-08 C 组同款：完整形非降级非匿名）。"""
    return {"id": tid, "kind": "inspection", "template": "inspection-lite",
            "stage": "close", "stage_state": "awaiting-human", "status": "closed",
            "decision": "", "face": {"ticket_id": tid, "kind": "inspection",
                                     "instance_id": INSTANCE, "period": tid.rsplit("-", 1)[-1],
                                     "summary": {"high": 0, "med": 0, "low": 0},
                                     "findings": [], "suggested_fix_tickets": [],
                                     "report_path": "", "heartbeat": False},
            "timeline": [], "gate_error": close_note}


def failed_result_exc(cause_msg="套件 boom: step close failed", top_msg="workflow 执行失败"):
    """终态 result() 异常桩：异常链（__cause__）携带失败消息——方案考证的正源形态
    （WorkflowFailureError.__cause__ 链；桩用 RuntimeError 等价形）。cause_msg=None
    =「原因不可得」反用例（链上无任何消息）。"""
    e = RuntimeError(top_msg)
    if cause_msg is not None:
        e.__cause__ = RuntimeError(cause_msg)
    return e


def ins_wf(tid=TID_F, status_name="FAILED", close_time=None, start_time=NOW):
    if close_time is None:
        close_time = _closed_ago()   # 260928：相对此刻（同源时钟），不再钉冻结 NOW
    return FakeListWf(tid, "InspectionPeriodicWorkflow", status_name, Q, KV_INSP,
                      close_time=close_time, start_time=start_time)


def failed_handle(status_name="FAILED", **kw):
    """终态票 handle 桩：close_time 与扫描面一致（终态时刻面断言有真值可对）。"""
    ct = _closed_ago()   # 260928：同源时钟（见文件头时间炸弹注记）
    return FakeHandle(status_name, close_time=kw.pop("close_time", ct), **kw)


def dev_wf(tid="t-dev-failed", status_name="FAILED"):
    return FakeListWf(tid, "DevLaneWorkflow", status_name, Q, KV_DEV, start_time=NOW)


def dev_snap():
    """t260915-08 D 组同款 dev-lane 健康快照形状（对照面）。"""
    return {"engine": client_mod.ENGINE_V2,
            "meta": {"id": "t-dev", "title": "开发票", "project": "sandbar",
                     "role": "developer", "status": "dispatched", "stage": "implement",
                     "stage_state": "running", "created": 1700000000, "updated": 1700000100}}


# dev-lane 极简行旧形状键集（client.py else 分支原样：无 paused/paused_phase——那是
# meta 分支才并的键）。失败行 parity 守的是「极简行键集不加新键」。
# t260921-03 有意更新（键集随四形状同步扩展，parity 纪律不破）：收口健康度键
# close_health/close_health_reason 进 dev-lane 全部四形状（meta/极简/失败/降级）——
# 票面要求②「每行都必须能判定收口健康度」覆盖 dev-lane；引擎 UT
# test_t260915_08_inspection_board.py 的 DEVLANE_ROW_KEYS 钉同一键集。
DEV_ROW_KEYS = {"id", "project", "epic", "role", "status", "title", "workflow", "proposal_id",
                "stage", "stage_state", "handoff_count",
                "pending_count", "worktree", "workspace", "created", "updated",
                "updated_ts", "close_ts", "engine", "exec_status", "authz_active",
                "close_health", "close_health_reason"}


# ---------------------------------------------------------------- face 宽容读取（灰盒浅绑定）

def face_of(res):
    """终态回执里的失败面（方案定稿承诺：_err 回执顶层可选 face 键）。取不到=返回
    None 并点名回执键集（报错精确，不留「哪都没找到」悬案）。"""
    f = (res or {}).get("face")
    if isinstance(f, dict):
        return f
    return None


def face_text(face):
    return json.dumps(face, ensure_ascii=False, default=str) if isinstance(face, dict) else ""


def check_failed_row_shape(row, label, exec_status="FAILED"):
    """列表失败行的票面验收断言（验收①原文：与 running 可区分、不与 done 混同、
    失败标记可辨、标题诚实）。exec_status 参数化（FAILED/CANCELED 各断各的真值）。"""
    ok(row.get("status") not in ("dispatched", "running"),
       "%s：行 status 不得再显在跑形（got status=%r）" % (label, row.get("status")))
    ok(row.get("stage_state") != "running",
       "%s：行 stage_state 不得再显 running（got %r）" % (label, row.get("stage_state")))
    ok(row.get("status") != "closed" and row.get("stage_state") != "closed",
       "%s：失败不得混同收口（status=%r stage_state=%r）"
       % (label, row.get("status"), row.get("stage_state")))
    ok(row.get("exec_status") == exec_status,
       "%s：行带失败标记 exec_status=%s（got %r）" % (label, exec_status, row.get("exec_status")))
    title = str(row.get("title") or "")
    ok(title.strip() != "", "%s：标题非空（绝不匿名行）" % label)
    for bad in ("查询超时", "刷新重试", "瞬时"):
        ok(bad not in title,
           "%s：标题不含「%s」占位/诱导词（KI-018① 错误文案不进数据字段；title=%r）"
           % (label, bad, title))


# ---------------------------------------------------------------- 用例

def main() -> int:
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="sandbar-t26091902-face-")
    decl_path = os.path.join(tmp, "inspection.yaml")
    with open(decl_path, "w", encoding="utf-8") as f:
        f.write(DECL)
    old_decl = os.environ.get("SANDBAR_INSPECTION_DECL")
    os.environ["SANDBAR_INSPECTION_DECL"] = decl_path
    if hasattr(client_mod, "QUERY_RETRY_BASE_DELAY"):
        client_mod.QUERY_RETRY_BASE_DELAY = 0.0
    if hasattr(client_mod, "QUERY_RETRY_JITTER"):
        client_mod.QUERY_RETRY_JITTER = 0.0
    try:
        # ---- A 组：巡检形失败行（验收①巡检子用例）----
        print("== A 组：FAILED 巡检票列表失败行（不再显在跑+身份不丢）==")
        res = run_list({"kind": "inspection"}, [ins_wf()], {TID_F: FakeHandle("FAILED")})
        rows = rows_of(res)
        if res.get("_scenario_error") or rows is None:
            ok(False, "巡检失败票列表调用崩溃：%r" % res.get("_scenario_error"))
        else:
            row = row_of(res, TID_F)
            ok(row is not None, "终态 FAILED 巡检票上板（失败可见是本票核心诉求；行集=%r）"
               % [r.get("id") for r in rows if isinstance(r, dict)])
            if row is None:
                ok(False, "A 组行面断言无行可验")
            else:
                check_failed_row_shape(row, "A 巡检失败行")
                ok(row.get("kind") == "inspection", "巡检标识保持（kind=%r）" % row.get("kind"))
                ok(row.get("instance_id") == INSTANCE and row.get("period") == PERIOD,
                   "票身份不丢：实例/期号在行（instance_id=%r period=%r——SA 兜底路径）"
                   % (row.get("instance_id"), row.get("period")))
        # CANCELED 同族断言（失败类不止 FAILED——票面「FAILED/CANCELED 等失败类」）
        tid_c = "inspection-integration-tests-20260918"
        wfc = ins_wf(tid_c, status_name="CANCELED")
        res = run_list({"kind": "inspection"}, [wfc], {tid_c: FakeHandle("CANCELED")})
        row = row_of(res, tid_c)
        if res.get("_scenario_error") or row is None:
            ok(False, "CANCELED 巡检票失败行缺席/崩溃：%r" % (res.get("_scenario_error"),))
        else:
            check_failed_row_shape(row, "A2 CANCELED 失败行", exec_status="CANCELED")

        # ---- B 组：dev-lane 形失败行（验收① dev-lane 子用例）----
        print("== B 组：FAILED dev-lane 票极简失败行（不再推在跑+键集 parity）==")
        res = run_list({}, [dev_wf()], {"t-dev-failed": FakeHandle("FAILED")})
        row = row_of(res, "t-dev-failed")
        if res.get("_scenario_error") or row is None:
            ok(False, "dev-lane 失败票行缺席/崩溃：%r" % (res.get("_scenario_error"),))
        else:
            check_failed_row_shape(row, "B dev 失败行")
            ok(row.get("project") == "sandbar",
               "行 project 不丢（SA 真源；got %r）" % row.get("project"))
            ok(set(row.keys()) == DEV_ROW_KEYS,
               "dev 失败行键集 parity（不加新键，t260915-08 R9 口径；diff=%r）"
               % (set(row.keys()) ^ DEV_ROW_KEYS))

        # ---- C 组：终态详情失败面（验收②）----
        print("== C 组：FAILED 巡检票详情=诚实错误+可渲染失败面 ==")
        res = run_query(TID_F, [ins_wf()], {TID_F: failed_handle("FAILED", result_raises=True,
                                                                 raise_exc=failed_result_exc())})
        if res.get("_scenario_error"):
            ok(False, "终态详情调用崩溃：%r" % res.get("_scenario_error"))
        else:
            ok(res.get("ok") is False and res.get("kind") == "terminal",
               "回执 ok:false + kind=terminal（KI-025 分级零退化；got kind=%r）"
               % res.get("kind"))
            errtxt = str(res.get("error") or "")
            ok("already terminal" in errtxt and "refreshing will not help" in errtxt,
               "文案仍明说终态/刷新无效（诚实口径红线；got=%r)" % errtxt[:80])
            for bad in ("retry", "transient", "ticket does not exist"):
                ok(bad not in errtxt,
                   "文案不含「%s」（终态绝不伪装可重试/瞬时/不存在——含否定形式也算）"
                   % bad)
            face = face_of(res)
            ok(face is not None,
               "回执带可渲染失败面 face（顶层键；回执键集=%s）" % sorted(res))
            if face is not None:
                ft = face_text(face)
                ok("FAILED" in ft, "失败面含执行状态（FAILED 可寻；keys=%s）" % sorted(face))
                ok("boom" in ft, "失败面含失败原因串（异常链「boom」可寻——Temporal "
                                "工作流失败信息正源）")
                ok(INSTANCE in ft and PERIOD in ft,
                   "失败面含票身份（巡检：实例 %s + 期 %s）" % (INSTANCE, PERIOD))
                has_time, why = False, "face keys=%s" % sorted(face)
                for k, v in face.items():
                    kl = str(k).lower()
                    if ("close" in kl or "start" in kl or "time" in kl) and v:
                        has_time, why = True, "key=%s=%r" % (k, v)
                        break
                if not has_time:
                    if re.search(r"\d{4}-\d{2}-\d{2}|\d{2}-\d{2} \d{2}:\d{2}", ft):
                        has_time, why = True, "date-like 值"
                ok(has_time, "失败面含终态时刻面（close/start 时间；%s）" % why)
                # t261008-29: the explanation may be carried by snapshot_note (English
                # "no snapshot ...") OR the last_stage note (Chinese 快照/不可查) — the
                # contract is "the face explains WHY there is no snapshot", not one
                # historical note's Chinese wording (KI-025 honesty, language-neutral).
                _snap_explained = (
                    ("快照" in ft or "snapshot" in ft.lower())
                    and ("不可得" in ft or "无快照" in ft or "不可查" in ft
                         or "no longer runs" in ft or "not a transient" in ft)
                )
                ok(_snap_explained,
                   "失败面含「无快照及为何无」显式说明（绝不空面；ft 摘=%r）" % ft[:120])
        print("== C2 组：FAILED dev-lane 票详情失败面 ==")
        tid_d = "t-dev-failed"
        res = run_query(tid_d, [dev_wf()], {tid_d: failed_handle("FAILED", result_raises=True,
                                                                 raise_exc=failed_result_exc(
                                                                     cause_msg="dev boom"))})
        if res.get("_scenario_error"):
            ok(False, "dev-lane 终态详情崩溃：%r" % res.get("_scenario_error"))
        else:
            ok(res.get("kind") == "terminal", "dev-lane 终态回执 kind=terminal（got %r）"
               % res.get("kind"))
            face = face_of(res)
            ok(face is not None, "dev-lane 回执带失败面 face（键集=%s）" % sorted(res))
            if face is not None:
                ft = face_text(face)
                ok("FAILED" in ft and "dev boom" in ft,
                   "失败面含执行状态+原因串（FAILED / dev boom）")
                ok("快照" in ft or "snapshot" in ft.lower(),
                   "失败面含无快照说明（ft 摘=%r）" % ft[:100])

        # ---- D 组：反用例——原因不可得（验收②反用例+红线「绝不编造」）----
        print("== D 组：终态但原因不可得 → 显式「原因不可得」并保留执行状态 ==")
        res = run_query(TID_F, [ins_wf()], {TID_F: failed_handle("FAILED", result_raises=True,
                                                                 raise_exc=failed_result_exc(
                                                                     cause_msg=None, top_msg=""))})
        if res.get("_scenario_error"):
            ok(False, "原因不可得子用例崩溃：%r" % res.get("_scenario_error"))
        else:
            face = face_of(res)
            ok(face is not None, "反用例仍带失败面（绝不空面；键集=%s）" % sorted(res))
            if face is not None:
                ft = face_text(face)
                ok("原因不可得" in ft,
                   "显式「原因不可得」（票面验收②原文；ft=%r）" % ft[:120])
                ok("FAILED" in ft, "执行状态保留（不因原因缺失而丢状态）")
                ok("boom" not in ft and "套件" not in ft,
                   "绝不编造原因（桩链上无消息，face 不得出现臆造串）")

        # ---- D2 组：畸形 desc——无 close_time 属性 + SA 读炸 → face 降级不崩 ----
        print("== D2 组：畸形 desc/SA 读炸 → 失败面显式降级，kind 仍 terminal ==")
        async def _query_broken_desc():
            class _C:
                def get_workflow_handle(self, tid):
                    h = FakeHandle("FAILED", result_raises=True,
                                   raise_exc=failed_result_exc())
                    async def describe():
                        return BrokenDesc("FAILED")
                    h.describe = describe
                    return h
            return _C()
        client_mod._connect = lambda *a, **k: _query_broken_desc()
        try:
            res = asyncio.run(client_mod.cmd_ticket_query({"ticket_id": TID_F}))
        except Exception as e:  # noqa: BLE001
            res = {"_scenario_error": "%s: %s" % (type(e).__name__, e)}
        if res.get("_scenario_error"):
            ok(False, "畸形 desc 终态详情崩溃（必须显式降级）：%r" % res.get("_scenario_error"))
        else:
            ok(res.get("kind") == "terminal",
               "畸形 desc 下 kind 仍 terminal（不误判瞬时/内部；got %r）" % res.get("kind"))
            ok(isinstance(face_of(res), dict),
               "畸形 desc 下失败面仍在（字段可降级空，面不可缺；键集=%s）" % sorted(res))

        # ---- E 组：资源纪律——失败票零白烧查询（KI-003 族）----
        print("== E 组：失败票列表不发注定失败的 snapshot 查询 ==")
        h = FakeHandle("FAILED")
        run_list({"kind": "inspection"}, [ins_wf()], {TID_F: h})
        ok(h.query_count == 0,
           "FAILED 票 snapshot 查询数=0（终态快照永不可查询，白烧=超时窗风险；"
           "query_count=%d）" % h.query_count)

        # ---- F 组：混合板各行其形 + TERMINATED 不上板（回归用例）----
        print("== F 组：RUNNING/COMPLETED/FAILED/TERMINATED 混合板零串行 ==")
        tid_run = "inspection-integration-tests-20260921"
        tid_done = "inspection-integration-tests-20260914"
        tid_term = "inspection-integration-tests-20260911"
        wfs = [ins_wf(TID_F, "FAILED"),
               ins_wf(tid_run, "RUNNING", close_time=None),
               ins_wf(tid_done, "COMPLETED"),
               ins_wf(tid_term, "TERMINATED")]
        handles = {TID_F: FakeHandle("FAILED"),
                   tid_run: FakeHandle("RUNNING", snapshot={}),
                   tid_done: FakeHandle("COMPLETED", result_value=insp_closed_snap(tid_done)),
                   tid_term: FakeHandle("TERMINATED")}
        res = run_list({"kind": "inspection"}, wfs, handles)
        rows = rows_of(res)
        if res.get("_scenario_error") or rows is None:
            ok(False, "混合板调用崩溃：%r" % res.get("_scenario_error"))
        else:
            got = {r.get("id") for r in rows if isinstance(r, dict)}
            ok(tid_term not in got, "TERMINATED 不上板（僵尸纪律半边原样；混入=%r）"
               % (got & {tid_term}))
            r_run = row_of(res, tid_run)
            ok(r_run is not None and r_run.get("status") == "dispatched"
               and r_run.get("stage_state") == "running",
               "RUNNING 行原样在跑形（零回归；got %r/%r）"
               % (r_run and r_run.get("status"), r_run and r_run.get("stage_state")))
            r_done = row_of(res, tid_done)
            ok(r_done is not None and r_done.get("status") == "closed",
               "COMPLETED 行收口形原样（零回归；got %r)" % (r_done and r_done.get("status")))
            r_fail = row_of(res, TID_F)
            ok(r_fail is not None and r_fail.get("status") == "failed",
               "FAILED 行失败形（三行同板各行其形不串行；got %r)"
               % (r_fail and r_fail.get("status")))
            ok(len([r for r in rows if isinstance(r, dict)]) == 3,
               "板面行数==在板票数（3；got %d）" % len(rows))
    finally:
        if old_decl is None:
            os.environ.pop("SANDBAR_INSPECTION_DECL", None)
        else:
            os.environ["SANDBAR_INSPECTION_DECL"] = old_decl

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
