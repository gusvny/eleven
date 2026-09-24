#!/usr/bin/env python3
"""t260925-09 · KI-114 终态票期号黑洞——期槽重开契约面（灰盒 L2，真引擎模块×场景自有
桩客户端，ro 离线秒级，零 docker 零端口零真仓写入）。

用户可感知契约（工单正文+KI-114 逐条反演，锚公开回执形状=open_period_ticket 回执
dict 的承诺键 triggered/deduped/dedup_source/stale_pointer_cleared + 本票新增承诺
superseded_ticket_id / period_state + 重开审计行，不锚实现内部——状态感知去重的
内部判定函数、指针 payload 细节不作用例依据）：

  A 主诉回归（KI-114 病象正面锁）：同（实例,期）仅存 TERMINATED 票 → 再 trigger 必须
    开出新票：triggered=true、新票号≠旧票号、superseded_ticket_id=旧票号（同号两 run
    的审计链接承诺）；旧指针在场时被清且 stale_pointer_cleared 留痕点名旧票；重开审计
    追加一行含 at/instance/period/旧票号/新票号。
  B 活期防并发（规格明文「dedup must still prevent concurrent duplicates for a LIVE
    period」）：RUNNING 票 → deduped=true / dedup_source=sa_query / triggered=false，
    零新票（t260916-02 既有语义不回退）。
  C 已服务期防双计：COMPLETED 票 → deduped=true且回执点名 completed 语义
    （period_state）——重开=台账双计，必须挡。
  D fail-closed（规格红线「unknown/ambiguous terminal state must not silently open a
    second concurrent run」）：FAILED / 未知状态名 / describe 瞬态不可判 → ok=false
    显式 error 且零新票（票面可见数不变），绝不静默开第二张。
  E 重开后 LIVE 收敛（并发面）：A 成功后再 trigger → deduped=true（sa_query 指向新活
    票），票总数恒=2（旧终止+新活），不产生第三张。
  F 指针层黑洞回归：SA 查无但指针指向终止票 → 指针清 + 正常重开（指针分支也认终态，
    病根②不回潮）。
  G 审计日志容错：重开审计文件既有坏 JSON 行 → 追加仍成功且旧行原样保留（追加面不因
    历史烂行丢审计）。

三态纪律：引擎模块不可导入=ENV_FAIL exit 2；断言红=exit 1。实现落地前 A/C/D/E/F/G
红属预期（TDD 信号：superseded/period_state/状态感知去重尚未落地），arbitrate/merge
期必须全绿。intent 分工：developer L1（server/engine/tests/test_t260925_09_*）守状态
分类纯函数真值表与 FakeClient 结构锁——本条锚用户可感知回执契约与病象旅程，不重复
结构锁；t260916-02 场景族守既有去重三路语义（本条 B 仅作活期回归锚，不重写彼面）；
t260905-03 真台旅程守开票→收口全链（需 exclusive 台）——本条 ro 离线，不触真台。
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))
import lib_env  # noqa: E402

ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE))
try:
    import inspection_ticketing as tick  # noqa: E402
    import shared  # noqa: E402
except Exception as e:  # noqa: BLE001
    lib_env.env_fail("server/engine 引擎模块不可导入（inspection_ticketing/shared）：%s: %s"
                     % (type(e).__name__, e))


def _install_temporalio_stub():
    """本环境无 temporalio SDK 时装最小桩（t260901-23/t260902-02 先例口径）：open_period_ticket
    启动路径经 shared.inspection_search_attributes 函数内 import temporalio.common——桩只
    承载 SA 三件套形状（Key.name/Pair/TypedSearchAttributes），零行为。真 SDK 在场则不装。"""
    try:
        import temporalio.common  # noqa: F401
        return
    except Exception:  # noqa: BLE001
        pass
    import types
    tmod = types.ModuleType("temporalio")
    cmod = types.ModuleType("temporalio.common")

    class SearchAttributeKey:
        def __init__(self, name):
            self.name = name

        @staticmethod
        def for_keyword(name):
            return SearchAttributeKey(name)

    class SearchAttributePair:
        def __init__(self, key, value):
            self.key, self.value = key, value

    class TypedSearchAttributes:
        def __init__(self, pairs):
            self.pairs = list(pairs)

        def __iter__(self):
            return iter(self.pairs)

    cmod.SearchAttributeKey = SearchAttributeKey
    cmod.SearchAttributePair = SearchAttributePair
    cmod.TypedSearchAttributes = TypedSearchAttributes
    tmod.common = cmod
    sys.modules["temporalio"] = tmod
    sys.modules["temporalio.common"] = cmod


_install_temporalio_stub()

INS = shared.INSPECTION_INSTANCE_SA_NAME
PER = shared.INSPECTION_PERIOD_SA_NAME
INST = "ki114-scenario"
PERIOD = "20260925"

# ---------- 场景自有桩客户端（锚公开接口形态：list_workflows/get_workflow_handle/
# start_workflow；不 import developer 的 FakeClient——夹具自足，防跨票耦合） ----------

class St:
    def __init__(self, name):
        self.name = name


class Desc:
    def __init__(self, wf):
        self.typed_search_attributes = [(k, v) for k, v in wf.sa.items()]
        self.status = St(wf.status)


class Handle:
    def __init__(self, c, tid):
        self._c, self._tid = c, tid

    async def describe(self):
        wf = self._c.wfs.get(self._tid)
        if wf is None:
            raise RuntimeError("workflow %s not found" % self._tid)
        if wf.transient:
            raise TimeoutError("describe unavailable")
        return Desc(wf)

    async def query(self, _name):
        return {}


class Wf:
    """桩工作流（属性面=真 describe 形态：status.name / SA 章 / 瞬态注入）。"""

    def __init__(self, d):
        self.id = d["id"]
        self.status = d["status"]
        self.sa = d["sa"]
        self.wf_type = d["wf_type"]
        self.transient = d["transient"]


class Client:
    """list_workflows 只按 SA 章过滤（可见性索引不认执行状态——病根形态）；
    start_workflow 同 id 活票则 already-started，终态票允许重占（真 Temporal 语义）。"""

    def __init__(self, wfs):
        self.wfs = {w.id: w for w in (Wf(w) if isinstance(w, dict) else w for w in wfs)}
        self.started = []

    def get_workflow_handle(self, tid):
        return Handle(self, tid)

    async def list_workflows(self, query):
        import re as _re
        m = _re.search(r'STARTS_WITH "([^"]*)"', query)
        if m:                     # 铸号扫描：前缀语义（含终态票——序号空间不重用）
            for w in self.wfs.values():
                if w.id.startswith(m.group(1)):
                    yield w
            return
        if 'WorkflowType="InspectionPeriodicWorkflow"' not in query:
            return
        im = _re.search(r'%s="([^"]*)"' % INS, query)
        pm = _re.search(r'%s="([^"]*)"' % PER, query)
        for w in self.wfs.values():
            if w.wf_type != "InspectionPeriodicWorkflow":
                continue
            if im and w.sa.get(INS) != im.group(1):
                continue
            if pm and w.sa.get(PER) != pm.group(1):
                continue
            yield w

    async def start_workflow(self, cls, payload, id=None, task_queue="", search_attributes=None):
        old = self.wfs.get(id)
        if old is not None and old.status in ("RUNNING", "CONTINUED_AS_NEW"):
            raise RuntimeError("WorkflowAlreadyStartedError: %s already started" % id)
        sa = {}
        for pair in (search_attributes or []):
            try:
                sa[pair.key.name] = pair.value
            except AttributeError:
                sa[str(pair[0])] = str(pair[1])
        wf = Wf({"id": id, "status": "RUNNING", "sa": sa,
                 "wf_type": "InspectionPeriodicWorkflow", "transient": False})
        self.wfs[id] = wf
        self.started.append(id)

        class H:
            first_execution_run_id = "run-" + str(id)

        return H()


class Input:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def wf(tid, status, transient=False):
    return {"id": tid, "status": status, "transient": transient, "wf_type": "InspectionPeriodicWorkflow",
            "sa": {INS: INST, PER: PERIOD}}


def default_kwargs(ledger_dir):
    return dict(instance_id=INST, period=PERIOD, project_key="sandbar",
                repo_root=str(REPO), scan_face="test", decl_path="",
                task_queue="q", workflow_cls=object, input_cls=Input,
                grace_sec=1.0, now_fn=time.time)


def pointer_of(ledger_dir):
    return tick.pointer_path(ledger_dir, INST, PERIOD)


def journal_lines(ledger_dir):
    p = Path(ledger_dir) / "inspection-reopen.jsonl"
    if not p.exists():
        return None
    return p.read_text("utf-8").splitlines()


def search_attrs_payload(inst, period):
    try:
        pairs = shared.inspection_search_attributes("sandbar", inst, period)
        out = {}
        for p in pairs:
            try:
                out[p.key.name] = p.value
            except AttributeError:
                out[str(p[0])] = str(p[1])
        return out
    except Exception:  # noqa: BLE001
        return {}


# ---------- 三态结算 ----------

results = []


def leg(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS [%s] %s" if cond else "FAIL [%s] %s") % (name, detail or name))


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="t26092509-"))
    ledger = tmp / "ledger"
    ledger.mkdir()
    os.environ["SANDBAR_INSPECTION_DIR"] = str(ledger)
    kw = default_kwargs(str(ledger))

    # ---- A 主诉：终止票占槽 → 重开 + 审计链接 ----
    c = Client([wf("t260925-01", "TERMINATED")])
    ppath = pointer_of(ledger)
    ppath.write_text(json.dumps({"ticket_id": "t260925-01", "instance_id": INST,
                                 "period": PERIOD, "project_key": "sandbar",
                                 "at": time.time() - 999}), encoding="utf-8")
    os.utime(ppath, (time.time() - 999,) * 2)   # 指针年龄基准=st_mtime（R4）：回拨出飞行窗
    r = await tick.open_period_ticket(c, **kw)
    okA = (r.get("ok") is True and (r.get("result") or {}).get("triggered") is True)
    new_id = (r.get("result") or {}).get("ticket_id") if r.get("ok") else ""
    leg("A1 terminated-slot reopen triggers new ticket",
        okA and new_id not in ("", "t260925-01"), "receipt=%s" % json.dumps(r, ensure_ascii=False)[:220])
    leg("A2 receipt links superseded_ticket_id=old",
        (r.get("result") or {}).get("superseded_ticket_id") == "t260925-01")
    cleared = json.dumps((r.get("result") or {}).get("stale_pointer_cleared") or [], ensure_ascii=False)
    leg("A3 stale pointer cleared and names old ticket",
        "t260925-01" in cleared, "stale_pointer_cleared=%s" % cleared)
    pl = json.loads(ppath.read_text("utf-8")) if ppath.exists() else {}
    leg("A4 new ticket started with same instance+period SA",
        new_id in c.wfs and c.wfs[new_id].sa.get(INS) == INST
        and c.wfs[new_id].sa.get(PER) == PERIOD)
    lines = journal_lines(ledger) or []
    linked = [ln for ln in lines if "t260925-01" in ln and new_id and new_id in ln]
    leg("A5 reopen journal links old+new ticket ids", len(linked) >= 1,
        "journal=%s" % (lines[-3:] if lines else lines))

    # ---- E 重开后 LIVE 收敛：再 trigger 必 dedup，不产第三张 ----
    before = len(c.wfs)
    r2 = await tick.open_period_ticket(c, **kw)
    res2 = r2.get("result") or {}
    leg("E1 re-trigger after reopen dedups on live new ticket",
        r2.get("ok") is True and res2.get("deduped") is True and res2.get("triggered") is False
        and res2.get("ticket_id") == new_id, "receipt=%s" % json.dumps(r2, ensure_ascii=False)[:200])
    leg("E2 no third ticket created", len(c.wfs) == before)

    # ---- B 活期防并发：RUNNING → dedup（既有语义回归锚） ----
    c3 = Client([wf("t260925-07", "RUNNING")])
    r3 = await tick.open_period_ticket(c3, **kw)
    res3 = r3.get("result") or {}
    leg("B1 live period stays deduped via sa_query",
        r3.get("ok") is True and res3.get("deduped") is True
        and res3.get("dedup_source") == "sa_query" and not c3.started)

    # ---- C 已服务期防双计：COMPLETED → dedup 且点名 completed ----
    c4 = Client([wf("t260925-08", "COMPLETED")])
    r4 = await tick.open_period_ticket(c4, **kw)
    res4 = r4.get("result") or {}
    leg("C1 completed period not reopened (no double count)",
        r4.get("ok") is True and res4.get("deduped") is True and not c4.started,
        "receipt=%s" % json.dumps(r4, ensure_ascii=False)[:200])
    leg("C2 receipt names completed period state",
        str(res4.get("period_state") or "").strip().lower() == "completed")

    # ---- D fail-closed：含糊终态绝不静默开第二张 ----
    for tag, status, transient in (("FAILED", "FAILED", False), ("UNKNOWN", "SOMETHING_ELSE", False),
                                   ("TRANSIENT", "TERMINATED", True)):
        cc = Client([wf("t260925-09", status, transient=transient)])
        rr = await tick.open_period_ticket(cc, **kw)
        leg("D fail-closed on %s hit (explicit error, no new ticket)" % tag,
            rr.get("ok") is False and bool(str(rr.get("error") or "").strip())
            and not cc.started,
            "receipt=%s" % json.dumps(rr, ensure_ascii=False)[:160])

    # ---- F 指针层黑洞：SA 查无但指针指向终止票 → 清 + 重开 ----
    c5 = Client([])          # SA 索引空：终态票只在指针层可见
    ppath.unlink(missing_ok=True)
    ppath.write_text(json.dumps({"ticket_id": "t260925-02", "instance_id": INST,
                                 "period": PERIOD, "project_key": "sandbar",
                                 "at": time.time() - 999}), encoding="utf-8")
    os.utime(ppath, (time.time() - 999,) * 2)   # 同 R4：回拨出飞行窗
    r5 = await tick.open_period_ticket(c5, **kw)
    res5 = r5.get("result") or {}
    leg("F1 pointer-to-terminated is cleared and slot reopens",
        r5.get("ok") is True and res5.get("triggered") is True
        and "t260925-02" in json.dumps(res5.get("stale_pointer_cleared") or [], ensure_ascii=False),
        "receipt=%s" % json.dumps(r5, ensure_ascii=False)[:200])

    # ---- G 审计日志容错：坏 JSON 行不阻断追加 ----
    jp = ledger / "inspection-reopen.jsonl"
    if jp.exists():
        good = jp.read_text("utf-8")
        jp.write_text("NOT-JSON{{{\n" + good, encoding="utf-8")
        c6 = Client([wf("t260925-03", "TERMINATED")])
        ppath.unlink(missing_ok=True)
        r6 = await tick.open_period_ticket(c6, **kw)
        tail = (jp.read_text("utf-8").splitlines() if jp.exists() else [])
        leg("G1 corrupt journal line does not block audit append",
            r6.get("ok") is True and tail[0] == "NOT-JSON{{{"
            and len(tail) >= len(good.splitlines()) + 1)
    else:
        leg("G1 corrupt journal line does not block audit append", False,
            "A 未产出重开审计文件，G 无对象")

    # 汇总（lib_env 契约：SUMMARY 行 + fail_if_all_na + exit 码）
    passed = sum(1 for _, ok in results if ok)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, len(results) - passed))
    lib_env.fail_if_all_na(len(results), 0)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
