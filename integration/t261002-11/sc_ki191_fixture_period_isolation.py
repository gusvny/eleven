#!/usr/bin/env python3
"""sc_ki191_fixture_period_isolation.py — KI-191 夹具期号空间隔离+清坑+回执点名 L3 回归棒
（t261002-11；灰盒离线秒级零 docker 零 Temporal 服务：真 open_period_ticket 公开函数面
+ 最小客户端桩注入，test_t260916_02 桩形同款。注意：open_period_ticket 内部 import
inspection_flow → temporalio，故须引擎 venv 链执行（登记 cmd 带 venv 回落链；
temporalio 缺席=ModuleNotFoundError 即环境红，非场景红）。

锁面（工单验收 1–3 + review_plan 三条意见的契约锚，全部落公开接口/用户可感知行为，
不锚内部结构）：
  A 隔离面（验收 1「fixture mark 不可被去重」）：带 mark 的既有夹具票**不是**真触发
    的合法去重目标——真触发必须另铸真票；同 mark 夹具触发可正常幂等去重；夹具触发
    撞上无 mark 真票=具名 fail-closed 报错（点名哪个检查失败，非裸布尔）。
  B 清坑面（验收 2「终态=期号槽释放，零占坑残留」）：release_period_ticket 快乐路
    （票到终态+指针清+槽面报空）；mark 不匹配=具名报错；mark 缺失（空串）=具名报错
    （review 意见 1，不许静默塌缩进 mismatch）；双清=具名报错点名「已释放」。
  C 诚实槽面（「谁占着期号槽」可查询，非布尔）：活夹具占坑报 mark+占坑时刻；
    legacy 无戳票诚实报空 mark/unknown 时刻（不编造，review 意见 2）；空槽显式 empty。
  D 回执点名面（验收 3）：inspection_flow 回执不得再有 `result.get("ticket") or "?"`
    静默兜底（KI-191 事故根因），必须读 ticket_id 并带占坑时刻（legacy 诚实 unknown）；
    spawn 活动把 fixture_mark 从入参穿透进 open_period_ticket（缺省空=排程路不变）。
  E 夹具卫生自证：本场景自身=夹具纪律范本（隔离 SANDBAR_INSPECTION_DIR + finally 清坑）。

A/B/C 经真函数面驱动（实现未落地段红属预期——TDD 信号，arbitrate/merge 期必须绿）；
D 为源码锁（回执字符串是用户可感知面）。

Run directly: python3 integration/t261002-11/sc_ki191_fixture_period_isolation.py（cwd=仓根）。
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0
ENV_FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title):
    print("\n%s" % title)


def named_error(exc, *needles):
    """具名报错判定：异常消息点名检查项（含任一关键词），且非裸布尔/空文案。"""
    msg = str(getattr(exc, "args", [None])[0] or "")
    return bool(msg.strip()) and any(n in msg for n in needles)


# ---------- 导入面（实现未落地=逐项具名红，不裸崩） ----------
section("0 导入面")
try:
    import inspection_ticketing as tick  # noqa: E402
    import shared  # noqa: E402
    _missing = [n for n in ("open_period_ticket", "describe_period_slot",
                            "release_period_slot") if not hasattr(tick, n)]
    _missing += [n for n in ("INSPECTION_FIXTURE_SA_NAME",
                             "INSPECTION_SLOT_TAKEN_SA_NAME") if not hasattr(shared, n)]
    ok(not _missing, "ticketing 公开面三函数 + shared 两 SA 名在册")
    if _missing:
        print("\nFAIL: KI-191 公开面未落地（TDD 红）——缺: %s；A/B/C 全族不可驱动" %
              ", ".join(_missing))
        print("RESULT: FAIL pass=%d fail=%d env_fail=0" % (PASS, FAIL + 0))
        sys.exit(1)
except Exception as e:  # noqa: BLE001
    ok(False, "engine 模块导入失败: %r" % (e,))
    print("\nFAIL: engine 公开面未落地（TDD 红），A/B/C 全族不可驱动")
    print("RESULT: FAIL pass=0 fail=1 env_fail=0")
    sys.exit(1)


# ---------- 最小客户端桩（test_t260916_02 桩形同款，零 temporalio 依赖） ----------
class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeDesc:
    def __init__(self, wf):
        self.status = wf.status
        self.typed_search_attributes = {k: [v] for k, v in (wf.sa or {}).items()}


class FakeHandle:
    def __init__(self, client, tid):
        self._c = client
        self._tid = tid
        self.first_execution_run_id = "run-%s" % tid

    async def describe(self):
        wf = self._c.wfs.get(self._tid)
        if wf is None:
            raise RuntimeError("NOT_FOUND: workflow %s not found" % self._tid)
        return FakeDesc(wf)

    async def query(self, name):
        wf = self._c.wfs.get(self._tid)
        return dict(wf.snap) if wf and wf.snap else {}

    async def cancel(self):
        wf = self._c.wfs.get(self._tid)
        if wf is not None:
            wf.status = FakeStatus("CANCELED")
            wf.cancelled = True


class FakeWf:
    def __init__(self, tid, status="RUNNING", sa=None,
                 wf_type="InspectionPeriodicWorkflow", snap=None):
        self.id = tid
        self.status = FakeStatus(status)
        self.sa = dict(sa or {})
        self.workflow_type = wf_type
        self.snap = snap or {}
        self.cancelled = False


class FakeClient:
    def __init__(self, wfs=None):
        self.wfs = {w.id: w for w in (wfs or [])}
        self.started: list = []

    def get_workflow_handle(self, tid):
        return FakeHandle(self, tid)

    async def list_workflows(self, query):
        ins = shared.INSPECTION_INSTANCE_SA_NAME
        per = shared.INSPECTION_PERIOD_SA_NAME
        import re as _re
        if "STARTS_WITH" in query:
            m = _re.search(r'STARTS_WITH "([^"]*)"', query)
            for w in self.wfs.values():
                if w.id.startswith(m.group(1)):
                    yield w
            return
        inst_m = _re.search(r'%s="([^"]*)"' % ins, query)
        per_m = _re.search(r'%s="([^"]*)"' % per, query)
        for w in self.wfs.values():
            if w.workflow_type != "InspectionPeriodicWorkflow":
                continue
            if inst_m and w.sa.get(ins) != inst_m.group(1):
                continue
            if per_m and w.sa.get(per) != per_m.group(1):
                continue
            yield w

    async def start_workflow(self, wf_cls, payload, id=None, task_queue=None,
                             search_attributes=None, **kw):
        sa = {}
        try:
            for p in (search_attributes or []):
                sa[p.key.name] = p.value
        except TypeError:
            sa = dict(search_attributes or {})
        if id in self.wfs and self.wfs[id].status.name == "RUNNING":
            raise RuntimeError("already started: %s" % id)
        wf = FakeWf(id, "RUNNING", sa)
        self.wfs[id] = wf
        self.started.append({"id": id, "sa": sa})
        return FakeHandle(self, id)


def run(coro):
    return asyncio.run(coro)


FIX = "fixture-20260926-ui"       # 夹具 mark 样例（语义：哪个夹具批次占的坑）
INS_ID = "integration-tests"
PERIOD = "20261002"               # KI-191 实证被占的期号


def open_ticket(client, ledger_dir, **kw):
    """open_period_ticket 固定注入面：账本目录=场景私有 tmp（SANDBAR_INSPECTION_DIR 链）。
    契约对齐（t261002-11 实现段）：open_period_ticket 的失败面是 {"ok":False,"error":…}
    单行 dict（与既有三路起票回执同形，绝不裸异常穿越活动边界）——本壳在 ok=False 时
    转译成 TicketingError 上抛，让场景断言面（try/except + 具名关键词）保持工单规格
    的「具名报错」读法；ok=True 解包 result（场景只读用户可感知键）。"""
    base = dict(instance_id=INS_ID, period=PERIOD, project_key="sandbar",
                repo_root="/repo", scan_face="test", decl_path="", task_queue="tq")
    base.update(kw)
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(ledger_dir)
    try:
        res = run(tick.open_period_ticket(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old
    if not res.get("ok"):
        raise tick.TicketingError(str(res.get("error") or "起票失败（无事由）"))
    return res.get("result") or {}


def release_slot(ledger_dir, client, **kw):
    """release_period_slot 固定注入面：清坑面同样经 SANDBAR_INSPECTION_DIR 定位飞行指针，
    必须挂同一隔离目录（与 open 同链），否则清到引擎缺省 out 目录=清坑半途。
    返回引擎的 {ok, error/released, pointer_cleared} 形态（fail=返回 ok=False，不抛）。"""
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(ledger_dir)
    try:
        return run(tick.release_period_slot(client, **kw))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def main():
    tmp = Path(tempfile.mkdtemp(prefix="sc-ki191-"))
    try:
        # ============ A 隔离面（验收 1） ============
        section("A 夹具隔离面：mark 票不可吞真触发（验收 1）")
        client = FakeClient()
        led = tmp / "ledgerA"
        r_fix = open_ticket(client, led, fixture_mark=FIX)
        ok(bool(r_fix.get("ticket_id")), "夹具触发铸票 ticket_id=%s" % r_fix.get("ticket_id"))
        ok(bool(r_fix.get("fixture")), "夹具回执回显 fixture 标记")
        r_fix2 = open_ticket(client, led, fixture_mark=FIX)
        ok(r_fix2.get("deduped") and r_fix2.get("ticket_id") == r_fix.get("ticket_id"),
           "同 mark 夹具触发正常幂等去重到夹具票（真票未在场时）")
        try:
            open_ticket(client, led, fixture_mark="fixture-other-batch")
            ok(False, "异 mark 夹具触发撞夹具占坑应 fail-closed")
        except Exception as e:  # noqa: BLE001
            ok(named_error(e, "mark", "fixture"), "异 mark 撞坑=具名报错点名 mark 检查")
        r_real = open_ticket(client, led)  # 真排程触发：无 mark
        ok(bool(r_real.get("ticket_id")) and not r_real.get("deduped"),
           "真触发不 dedup 到夹具票——另铸真票（deduped=%r）" % r_real.get("deduped"))
        ok(r_real.get("ticket_id") != r_fix.get("ticket_id"),
           "真票 id ≠ 夹具票 id（%s vs %s）" % (r_real.get("ticket_id"), r_fix.get("ticket_id")))

        section("A2 夹具触发撞真票=具名 fail-closed（不许静默吞真票）")
        client2 = FakeClient([FakeWf("t261001-50", status="RUNNING", sa={
            shared.INSPECTION_INSTANCE_SA_NAME: INS_ID,
            shared.INSPECTION_PERIOD_SA_NAME: PERIOD})])  # 无 mark 真票
        try:
            open_ticket(client2, tmp / "ledgerA2", fixture_mark=FIX)
            ok(False, "夹具触发撞真票应 fail-closed")
        except Exception as e:  # noqa: BLE001
            ok(named_error(e, "mark", "fixture", "unmarked"),
               "撞无 mark 真票=具名报错（%s）" % str(getattr(e, "args", [""])[0])[:80])

        # ============ B 清坑面（验收 2） ============
        section("B 清坑面：release_period_slot（验收 2 + review 意见 1）")
        client3 = FakeClient()
        led3 = tmp / "ledgerB"
        rf = open_ticket(client3, led3, fixture_mark=FIX)
        fid = rf.get("ticket_id")
        r0 = run(tick.describe_period_slot(client3, instance_id=INS_ID, period=PERIOD))
        ok(r0.get("ticket_id") == fid and r0.get("fixture_mark") == FIX,
           "释放前槽面点名占坑票与 mark")
        ok(bool(r0.get("slot_taken_at")), "占坑时刻有戳（slot_taken_at=%s）" % r0.get("slot_taken_at"))
        r_rel = release_slot(led3, client3, instance_id=INS_ID, period=PERIOD,
                             fixture_mark=FIX)
        ok(r_rel.get("ok") is True and fid in (r_rel.get("released") or []),
           "清坑快乐路 ok=True 且点名释放票（%s）" % r_rel)
        ok(r_rel.get("pointer_cleared") is True, "飞行指针已清（终态=槽位释放的一半）")
        r1 = run(tick.describe_period_slot(client3, instance_id=INS_ID, period=PERIOD))
        ok(r1.get("slot_state") in ("empty", "freed") or not r1.get("ticket_id"),
           "释放后槽面报空（slot_state=%r ticket=%r）" % (r1.get("slot_state"), r1.get("ticket_id")))
        wf = client3.wfs.get(fid)
        ok(wf is None or wf.status.name in ("CANCELED", "TERMINATED", "COMPLETED",
                                            "FAILED", "CONTINUED_AS_NEW"),
           "夹具票到终态（status=%s）" % (wf.status.name if wf else "<gone>"))
        r_dc = release_slot(led3, client3, instance_id=INS_ID, period=PERIOD,
                            fixture_mark=FIX)
        ok(r_dc.get("ok") is False and
           named_error(Exception(r_dc.get("error") or ""), "double-clean", "已释放"),
           "双清=具名报错点名「已释放」（%s）" % (r_dc.get("error") or "")[:60])
        client4 = FakeClient()
        open_ticket(client4, led3, fixture_mark=FIX)
        r_mm = release_slot(led3, client4, instance_id=INS_ID, period=PERIOD,
                            fixture_mark="fixture-wrong")
        ok(r_mm.get("ok") is False and
           named_error(Exception(r_mm.get("error") or ""), "mark", "mismatch", "匹配", "ownership"),
           "mark 不匹配=具名报错（%s）" % (r_mm.get("error") or "")[:60])
        r_ms = release_slot(led3, client4, instance_id=INS_ID, period=PERIOD,
                            fixture_mark="")
        ok(r_ms.get("ok") is False and
           named_error(Exception(r_ms.get("error") or ""), "mark", "missing", "缺"),
           "mark 缺失（空串）=具名报错，不塌缩进 mismatch（%s）"
           % (r_ms.get("error") or "")[:60])

        # ============ C 诚实槽面（可查询非布尔） ============
        section("C 诚实槽面：describe_period_slot（review 意见 2）")
        client5 = FakeClient([FakeWf("t261001-80", status="RUNNING", sa={
            shared.INSPECTION_INSTANCE_SA_NAME: INS_ID,
            shared.INSPECTION_PERIOD_SA_NAME: PERIOD})])  # legacy 无戳票
        rl = run(tick.describe_period_slot(client5, instance_id=INS_ID, period=PERIOD))
        ok(rl.get("ticket_id") == "t261001-80", "legacy 占坑票可点名")
        ok(rl.get("fixture_mark", None) == "" and
           rl.get("slot_taken_at") in (None, "", "unknown"),
           "legacy 无戳=诚实报空 mark/unknown 时刻，不编造")
        client6 = FakeClient()
        re_ = run(tick.describe_period_slot(client6, instance_id=INS_ID, period=PERIOD))
        ok(re_.get("slot_state") == "empty" and not re_.get("ticket_id"),
           "空槽显式 empty")

        # ============ D 回执点名面（验收 3，源码锁） ============
        section("D 回执点名面：ticket_id + 占坑时刻（验收 3）")
        flow_src = (ROOT / "server/engine/inspection_flow.py").read_text("utf-8")
        ok('result.get("ticket")' not in flow_src,
           "回执不再有 result.get(\"ticket\") 静默兜底（KI-191 事故根因摘除）")
        ok('result.get("ticket_id")' in flow_src or '"ticket_id"' in flow_src,
           "回执读 ticket_id 键")
        ok("slot_taken_at" in flow_src,
           "回执带占坑时刻字段（deduped 时点名坑何时被占）")
        ok("unknown" in flow_src,
           "legacy 无戳票占坑时刻诚实 unknown（不编造）")
        act_src = (ROOT / "server/engine/activities.py").read_text("utf-8")
        ok("fixture_mark" in act_src and "fixture_mark" in
           (ROOT / "server/engine/inspection_ticketing.py").read_text("utf-8"),
           "spawn 活动→open_period_ticket 穿透 fixture_mark（缺省空=排程路不变）")

        # ============ E 夹具卫生自证 ============
        section("E 夹具卫生自证")
        ok(led.exists() and not any(led.glob("*.ticket.lock*")),
           "本场景账本目录隔离且无双清残锁（SANDBAR_INSPECTION_DIR 隔离链）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # 清坑纪律：场景自身零残留

    print("\nRESULT: %s pass=%d fail=%d env_fail=%d" % (
        "PASS" if FAIL == 0 else "FAIL", PASS, FAIL, ENV_FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
