#!/usr/bin/env python3
"""sc_ki192_supersede_adjudication.py — KI-192 期槽裁决（supersede 链采信 + blocked-completed
不占 served 席 + 「人工处置」必须点名真实入口）L3 回归棒（t261003-03）。

灰盒离线秒级零 docker 零 Temporal 服务：真 open_period_ticket 公开函数面 + 最小客户端
桩注入（t261002-11 sc_ki191 桩形同款）。注意：open_period_ticket 内部懒 import
inspection_flow → temporalio，故须引擎 venv 链执行（登记 cmd 带回落链；temporalio
缺席=ModuleNotFoundError 即环境红 ENV_FAIL exit 2，非场景红）。

锁面（工单验收 1–4，全部落公开接口/用户可感知行为，不锚内部结构）：
  A supersede 塌缩面（验收 1）：同期 [已被替代的 served 旧票 + 存活 served 票]，带
    reopen_reason 必须重开成功（旧票不再占 served 席）；审计三痕齐（reopen journal 行
    带 reason＋指针 payload supersedes_ticket_id＋回执点名被替代票）；无 reason 时塌缩
    到存活票正常幂等去重（报 period_state=completed 指向存活票，不再是多张一刀切拒）。
  B blocked-completed 面（验收 2）：inspect 阶段 fail-closed 解析拒收的 run（workflow
    COMPLETED + 期台账面带 blocked_reason）服务了零个人——带具名理由必须可重开；无
    理由绝不允许静默 dedup 成「已服务」假面（那是「本期已收口有产出」的谎言）。
  C 拒绝点名真实动作面（验收 3）：真无链路的多张 served 票、无 reason 被拒时，报错
    必须点名一个**真实存在**的入口（--reopen-reason / reopen_reason 字样）——绝不许
    「人工处置」空指针；带 reason 时走既有具名重开通道收口（塌缩到存活票）。
  D 具名输入检查面（派发规格）：supersede 链消费的外部痕迹三类畸形各报**具名**错误
    （点名哪个检查失败，非裸布尔）：①指针声明 supersedes_ticket_id 但 journal 无行；
    ②链指向不存在的票；③一旧票被两张新票替代（双替代）。任何一类都不得静默放行铸新票。
  E 夹具卫生自证：隔离 SANDBAR_INSPECTION_DIR + finally rmtree 零残留（L8）。

intent 分工（防 intent 级重复）：supersede_links/ledger-face 纯函数真值分支、畸形行降级
矩阵、回执字段级形状归 developer L1（随实现交付）；K114/K191 既有 borrowed 面归
t260916-02/t260917-02/t261002-11 既有电池，本条不重复。实现未落地段红属预期（TDD
信号），arbitrate/merge 期必须绿。

Run directly: python3 integration/t261003-03/sc_ki192_supersede_adjudication.py（cwd=仓根）。
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


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


# ---------- 导入面（实现未落地=逐项具名红，不裸崩） ----------
section("0 导入面")
try:
    import inspection_ticketing as tick  # noqa: E402
    import shared  # noqa: E402
    _missing = [n for n in ("open_period_ticket", "period_slot_verdict",
                            "append_reopen_journal", "REOPEN_JOURNAL_NAME",
                            "ledger_file_name") if not hasattr(tick, n)]
    _missing += [n for n in ("INSPECTION_INSTANCE_SA_NAME",
                             "INSPECTION_PERIOD_SA_NAME") if not hasattr(shared, n)]
    ok(not _missing, "ticketing 公开面 + shared SA 名在册")
    if _missing:
        print("\nFAIL: KI-192 公开面未落地（TDD 红）——缺: %s" % ", ".join(_missing))
        print("RESULT: FAIL pass=%d fail=1 env_fail=0" % PASS)
        sys.exit(1)
except Exception as e:  # noqa: BLE001
    ok(False, "engine 模块导入失败: %r" % (e,))
    print("\nFAIL: engine 公开面未落地（TDD 红）")
    print("RESULT: FAIL pass=0 fail=1 env_fail=0")
    sys.exit(1)


# ---------- 最小客户端桩（t261002-11 桩形同款，零 temporalio 依赖） ----------
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


class FakeWf:
    def __init__(self, tid, status="RUNNING", sa=None,
                 wf_type="InspectionPeriodicWorkflow"):
        self.id = tid
        self.status = FakeStatus(status)
        self.sa = dict(sa or {})
        self.workflow_type = wf_type


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
        if id in self.wfs:
            raise RuntimeError("already started: %s" % id)
        wf = FakeWf(id, "RUNNING", sa)
        self.wfs[id] = wf
        self.started.append({"id": id, "sa": sa})
        return FakeHandle(self, id)


INS_ID = "integration-tests"
PERIOD = "20261002"          # KI-192 实证被锁死的期号
REASON = "ki192-scenario-named-reopen"


def _sa_for(tid_taken=""):
    sa = {shared.INSPECTION_INSTANCE_SA_NAME: INS_ID,
          shared.INSPECTION_PERIOD_SA_NAME: PERIOD}
    if tid_taken:
        sa["InspectionSlotTakenAt"] = tid_taken
    return sa


def open_ticket(client, ledger_dir, **kw):
    """open_period_ticket 固定注入面（隔离 SANDBAR_INSPECTION_DIR；失败回执 ok=False
    原样返回给断言面——本场景大量断言的就是失败文案，绝不转译吞掉）。"""
    base = dict(instance_id=INS_ID, period=PERIOD, project_key="sandbar",
                repo_root="/repo", scan_face="test", decl_path="", task_queue="tq")
    base.update(kw)
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(ledger_dir)
    try:
        return asyncio.run(tick.open_period_ticket(client, **base))
    except ModuleNotFoundError as e:
        print("\nENV_FAIL: temporalio/依赖缺席（环境红非场景红）: %r" % (e,))
        sys.exit(2)
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def journal_rows(ledger_dir):
    p = Path(str(ledger_dir)) / tick.REOPEN_JOURNAL_NAME
    try:
        text = p.read_text("utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            rows.append(r)
    return rows


def write_journal_row(ledger_dir, old_tid, new_tid, reason=""):
    tick.append_reopen_journal(ledger_dir, INS_ID, PERIOD, old_tid, new_tid,
                               now_fn=time.time, reason=reason)


def write_pointer(ledger_dir, ticket_id, supersedes="", age_s=3600.0):
    """种子一枚**陈旧**指针（payload 带 supersedes_ticket_id；mtime 回拨=宽限窗外，
    裁决读痕不受飞行窗保护干扰）。"""
    p = tick.pointer_path(ledger_dir, INS_ID, PERIOD)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ticket_id": ticket_id, "instance_id": INS_ID, "period": PERIOD,
               "project_key": "sandbar", "supersedes_ticket_id": str(supersedes or ""),
               "at": time.time() - age_s}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    past = time.time() - age_s
    os.utime(p, (past, past))
    return p


def write_blocked_ledger(ledger_dir, ticket_id):
    """期台账面（_blocked dead-man 面形状：ticket_id + blocked_reason + stage）。"""
    p = Path(str(ledger_dir)) / tick.ledger_file_name(INS_ID, PERIOD)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ticket_id": ticket_id, "kind": "inspection",
                             "instance_id": INS_ID, "period": PERIOD,
                             "blocked_reason": "findings parse rejected: zero findings",
                             "stage": "inspect"}, ensure_ascii=False), encoding="utf-8")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="sc-ki192-"))
    try:
        # ============ A supersede 塌缩面（验收 1） ============
        section("A supersede 塌缩面：已替代旧票不占 served 席（验收 1）")
        client = FakeClient()
        led = tmp / "A"
        client.wfs["t-old"] = FakeWf("t-old", "COMPLETED", _sa_for("2026-10-02T01:00:00+00:00"))
        r1 = open_ticket(client, led, reopen_reason=REASON)          # 第一次具名重开（既有合法路）
        ok(r1.get("ok") is True and r1.get("result", {}).get("triggered") is True,
           "前置：单张 served 票带具名理由重开成功（既有 K114 面）")
        t_cur = (r1.get("result") or {}).get("ticket_id") or ""
        ok(bool(t_cur), "第一次重开铸出新票 %s" % t_cur)
        client.wfs[t_cur].status = FakeStatus("COMPLETED")            # 新票也已服务收口
        r2 = open_ticket(client, led, reopen_reason=REASON + "-2")
        ok(r2.get("ok") is True, "同期 [已替代 served 旧票 + 存活 served 票] 带具名理由重开成功"
           "（t-old 不再占 served 席；修复前此地=多张一刀切拒）")
        t_new = (r2.get("result") or {}).get("ticket_id") or ""
        ok(r2.get("ok") is True and t_new and t_new != t_cur, "塌缩后铸出存活新票 %s" % t_new)
        if r2.get("ok"):
            res2 = r2.get("result") or {}
            named = str(res2.get("superseded_ticket_id") or "") or \
                ",".join(res2.get("collapsed_superseded") or [])
            ok("t-old" in named, "回执点名被塌缩的已替代旧票（got=%r）" % named)
            rows = journal_rows(led)
            ok(any(r.get("reason") == REASON + "-2" for r in rows),
               "审计痕①：reopen journal 行带人具名理由")
            ppath = tick.pointer_path(led, INS_ID, PERIOD)
            ok(ppath.exists(), "审计痕②：重开指针在场")
            try:
                _kind, pdata = tick.read_pointer_state(ppath)
                ok(bool(str(pdata.get("supersedes_ticket_id") or "")),
                   "审计痕②：指针 payload supersedes_ticket_id 非空")
            except Exception as e:  # noqa: BLE001
                ok(False, "指针可读: %r" % (e,))
            ok(bool(named), "审计痕③：回执携带被替代票号（supersede 链接第三处）")
        r3 = open_ticket(client, led)                                  # 无 reason
        res3 = r3.get("result") or {}
        deduped_ok = r3.get("ok") is True and res3.get("deduped") is True
        refused_named = r3.get("ok") is False and "reopen" in str(r3.get("error") or "")
        ok(deduped_ok or refused_named,
           "无理由：期上收敛裁决（活票在=去重到活票；否则塌缩到存活票）或具名拒点名"
           "重开入口；绝不是多张一刀切拒（got=%r / ticket=%r）"
           % (r3.get("error"), res3.get("ticket_id")))

        # ============ B blocked-completed 面（验收 2） ============
        section("B blocked-completed：解析拒收的 COMPLETED 不算已服务（验收 2）")
        client = FakeClient()
        led = tmp / "B"
        client.wfs["t-blk"] = FakeWf("t-blk", "COMPLETED", _sa_for("2026-10-02T03:00:00+00:00"))
        write_blocked_ledger(led, "t-blk")
        rb0 = open_ticket(client, led)                                 # 无理由
        silent_served = rb0.get("ok") is True and \
            (rb0.get("result") or {}).get("deduped") is True and \
            str((rb0.get("result") or {}).get("period_state") or "") == "completed"
        ok(not silent_served,
           "无理由：blocked 票绝不被静默 dedup 成「已服务 completed」假面（got=%r）"
           % ((rb0.get("result") or {}).get("period_state")))
        ok((rb0.get("ok") is False and ("blocked" in str(rb0.get("error") or "") or
                                        "reopen" in str(rb0.get("error") or ""))) or
           (rb0.get("ok") is True),  # 允许「同 freed 自动重开」实现，但不许假 served 面
           "无理由：blocked 票要么具名拒（点名 blocked/重开入口），要么走具名审计面自动重开")
        rb1 = open_ticket(client, led, reopen_reason=REASON)
        ok(rb1.get("ok") is True and (rb1.get("result") or {}).get("triggered") is True,
           "带具名理由：blocked-completed 票可重开（修复前=永久占坑）")
        ok(any(r.get("reason") == REASON for r in journal_rows(led)),
           "blocked 重开的 journal 行带人具名理由（审计三痕之一）")

        # ============ C 拒绝点名真实动作面（验收 3） ============
        section("C 「人工处置」必须点名真实入口（验收 3）")
        client = FakeClient()
        led = tmp / "C"
        # 真无链路的两张 served 票（无 journal 行、无指针 supersedes 声明）
        client.wfs["t-a"] = FakeWf("t-a", "COMPLETED", _sa_for("2026-10-02T01:00:00+00:00"))
        client.wfs["t-b"] = FakeWf("t-b", "COMPLETED", _sa_for("2026-10-02T05:00:00+00:00"))
        rc0 = open_ticket(client, led)
        err0 = str(rc0.get("error") or "")
        ok(rc0.get("ok") is False, "无链路多张 served、无理由：fail-closed 拒（不猜）")
        ok("--reopen-reason" in err0 or "reopen_reason" in err0,
           "拒绝文案点名**真实存在**的入口（--reopen-reason），不许裸「人工处置」空指针"
           "（got=%r）" % err0[:120])
        rc1 = open_ticket(client, led, reopen_reason=REASON)
        ok(rc1.get("ok") is True and (rc1.get("result") or {}).get("triggered") is True,
           "带理由：无链路多张 served 经既有具名重开通道收口（override=重开本身）")
        ok(any(r.get("reason") == REASON for r in journal_rows(led)),
           "override 重开的 journal 行带人具名理由")

        # ============ D 具名输入检查面（派发规格） ============
        section("D supersede 链畸形三态：具名报错，绝不静默铸票")
        # D1 指针声明 supersedes 但 journal 无行
        client = FakeClient()
        led = tmp / "D1"
        client.wfs["t-old"] = FakeWf("t-old", "COMPLETED", _sa_for("2026-10-02T01:00:00+00:00"))
        client.wfs["t-cur"] = FakeWf("t-cur", "COMPLETED", _sa_for("2026-10-02T05:00:00+00:00"))
        write_pointer(led, "t-cur", supersedes="t-old")
        n0 = len(client.started)
        rd1 = open_ticket(client, led, reopen_reason=REASON)
        ok(rd1.get("ok") is False and ("supersede" in str(rd1.get("error") or "") or
                                       "journal" in str(rd1.get("error") or "")),
           "D1 指针声明 supersedes 但 journal 无行=具名报错（got=%r）"
           % str(rd1.get("error") or "")[:120])
        ok(len(client.started) == n0, "D1 链不采信时绝不静默铸新票")
        # D2 链指向不存在的票（断链锚在候选上：候选票被 ghost 声明替代——
        # 危险真形态=承接票已消失/从未起票，链半断必须具名拒；两端都不在候选的
        # **历史行**是惰性档案，不得触发本检查污染无关裁决——见仲裁报告）
        client = FakeClient()
        led = tmp / "D2"
        client.wfs["t-cur"] = FakeWf("t-cur", "COMPLETED", _sa_for("2026-10-02T05:00:00+00:00"))
        write_journal_row(led, "t-cur", "t-ghost", reason="seed")
        rd2 = open_ticket(client, led, reopen_reason=REASON)
        ok(rd2.get("ok") is False and ("supersede" in str(rd2.get("error") or "") or
                                       "exist" in str(rd2.get("error") or "") or
                                       "不存在" in str(rd2.get("error") or "")),
           "D2 链指向不存在的票=具名报错点名双方（got=%r)"
           % str(rd2.get("error") or "")[:120])
        # D3 一旧票被两张新票替代
        client = FakeClient()
        led = tmp / "D3"
        client.wfs["t-a2"] = FakeWf("t-a2", "COMPLETED", _sa_for("2026-10-02T05:00:00+00:00"))
        client.wfs["t-b2"] = FakeWf("t-b2", "COMPLETED", _sa_for("2026-10-02T06:00:00+00:00"))
        write_journal_row(led, "t-old", "t-a2", reason="seed1")
        write_journal_row(led, "t-old", "t-b2", reason="seed2")
        rd3 = open_ticket(client, led, reopen_reason=REASON)
        ok(rd3.get("ok") is False and ("supersede" in str(rd3.get("error") or "") or
                                       "double" in str(rd3.get("error") or "") or
                                       "双" in str(rd3.get("error") or "")),
           "D3 双替代=具名报错点名三票（got=%r）" % str(rd3.get("error") or "")[:120])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nRESULT: %s pass=%d fail=%d env_fail=0"
          % ("PASS" if FAIL == 0 else "FAIL", PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
