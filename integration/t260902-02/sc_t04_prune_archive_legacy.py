#!/usr/bin/env python3
"""t04 —— ticket-prune / ticket-archive-legacy（Temporal 回归运行态的清理面）。

prune 三清单 fail-closed：已归档可删 / legacy 需 --allow-legacy / 未归档拒删 /
manifest 畸形计失败；dry-run 零删除（deleter 不调用）；execute 逐票调用注入 deleter；
deleter 抛错不中断全批计入 failed；超时（wait_for）回收计入 failed。
archive-legacy 诚实过账：closed 无档票写 legacy manifest（files 空 + reason 明牌）；
已有真档幂等跳过不覆盖；meta 取 result_of 快照，取不到记 _meta_unavailable；
manifest 畸形计 failed。

client.py 的 Temporal 依赖（workflows/workflows_v2/temporalio.*）整体打桩——
被测函数全部走注入缝，不依赖真 Temporal server。
跑法：python3 integration/t260902-02/t04_prune_archive_legacy.py（cwd=泳道根）
"""
import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "engine"

# ---- 桩：temporalio.* 与 workflows*（client.py 模块级依赖；被测函数走注入缝）----
_tio = types.ModuleType("temporalio")
_tclient = types.ModuleType("temporalio.client")
_tcommon = types.ModuleType("temporalio.common")
_tapi_common = types.ModuleType("temporalio.api.common.v1")
_tapi_wfs = types.ModuleType("temporalio.api.workflowservice.v1")


class _ClientStub:
    pass


class _SAKStub:
    @staticmethod
    def for_keyword(_name):
        return object()


class _WFExec:
    def __init__(self, workflow_id=None, run_id=None):
        self.workflow_id = workflow_id
        self.run_id = run_id


class _DelReq:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_tclient.Client = _ClientStub
_tcommon.SearchAttributeKey = _SAKStub
_tapi_common.WorkflowExecution = _WFExec
_tapi_wfs.DeleteWorkflowExecutionRequest = _DelReq
for name, mod in [("temporalio", _tio), ("temporalio.client", _tclient),
                  ("temporalio.common", _tcommon),
                  ("temporalio.api", types.ModuleType("temporalio.api")),
                  ("temporalio.api.common", types.ModuleType("temporalio.api.common")),
                  ("temporalio.api.common.v1", _tapi_common),
                  ("temporalio.api.workflowservice", types.ModuleType("temporalio.api.workflowservice")),
                  ("temporalio.api.workflowservice.v1", _tapi_wfs)]:
    sys.modules.setdefault(name, mod)

_workflows = types.ModuleType("workflows")
_workflows_v2 = types.ModuleType("workflows_v2")


class _DummyWf:
    pass


_workflows.ContentPipelineWorkflow = _DummyWf
_workflows.DispatcherScanWorkflow = _DummyWf
_workflows_v2.TEMPLATE_CLASSES = {"dev-lane": _DummyWf}
sys.modules.setdefault("workflows", _workflows)
sys.modules.setdefault("workflows_v2", _workflows_v2)
sys.path.insert(0, str(POC))

import client  # noqa: E402

PASS = FAIL = ENV_FAIL = 0  # 三态契约：0=PASS、1=FAIL（产品红）、2=ENV_FAIL（环境红）
ROOT = tempfile.mkdtemp(prefix="t04-sb-")


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def write_manifest(tid, project="suyou", legacy=False, content=None):
    d = Path(ROOT) / project / "data" / "tickets" / tid
    d.mkdir(parents=True, exist_ok=True)
    if content is not None:
        (d / "archive.json").write_text(content, encoding="utf-8")
    else:
        (d / "archive.json").write_text(json.dumps(
            {"schema": "v1", "ticket_id": tid, "legacy": legacy, "files": []},
            ensure_ascii=False), encoding="utf-8")
    return d


ENTRIES = [
    {"id": "t04-archived", "sa_project": "suyou", "close_ts": 1},
    {"id": "t04-legacy", "sa_project": "suyou", "close_ts": 1},
    {"id": "t04-missing", "sa_project": "suyou", "close_ts": 1},
    {"id": "t04-bad", "sa_project": "suyou", "close_ts": 1},
    {"id": "t04-other-proj", "sa_project": "other", "close_ts": 1},
]


def make_calls():
    calls = []

    async def deleter(wf_id):
        calls.append(wf_id)
        if wf_id == "t04-boom":
            raise RuntimeError("backend exploded")

    return calls, deleter


def main():
    os.environ["SANDBAR_PROJECTS_DIR"] = ROOT
    try:
        write_manifest("t04-archived")
        write_manifest("t04-legacy", legacy=True)
        write_manifest("t04-bad", content="{corrupt")
        # t04-missing：无 manifest；t04-other-proj：别的项目 key 无 manifest

        # ---- prune dry-run：零删除、三清单分流正确 ----
        calls, deleter = make_calls()
        r = asyncio.run(client.cmd_ticket_prune({}, entries=list(ENTRIES), deleter=deleter))
        body = r["result"]
        ok(r["ok"] and body["dry_run"] is True, "dry-run 模式回执")
        ok(calls == [], "dry-run 零 deleter 调用（默认安全）")
        ok(body["deleted"] == ["t04-archived"], "已归档非 legacy → 将删清单")
        ok(body["skipped_legacy"] == ["t04-legacy"], "legacy 未确认 → 待确认清单（拒删）")
        ok(body["skipped_not_archived"] == ["t04-missing", "t04-other-proj"],
           "未归档 → 拒删清单（历史不蒸发）")
        ok(len(body["failed"]) == 1 and body["failed"][0]["id"] == "t04-bad",
           "manifest 畸形 → 计 failed（fail-closed 不静默当未归档）")

        # ---- prune execute：逐票调用 + 异常不中断 + 超时回收 ----
        entries2 = ENTRIES + [{"id": "t04-boom", "sa_project": "suyou", "close_ts": 1}]
        write_manifest("t04-boom")
        calls, deleter = make_calls()

        async def slow_deleter(_wf_id):
            await asyncio.sleep(5)

        r2 = asyncio.run(client.cmd_ticket_prune(
            {"execute": True, "timeout_sec": 0.2},
            entries=[{"id": "t04-archived", "sa_project": "suyou", "close_ts": 1}],
            deleter=slow_deleter))
        ok(r2["result"]["failed"] and "超时" in r2["result"]["failed"][0]["why"],
           "deleter 超时 → wait_for 回收计入 failed")
        r3 = asyncio.run(client.cmd_ticket_prune(
            {"execute": True}, entries=list(entries2), deleter=deleter))
        b3 = r3["result"]
        ok(calls == ["t04-archived", "t04-boom"], "execute：已归档逐票调用 deleter")
        ok("t04-archived" in b3["deleted"], "正常删除计入 deleted")
        ok(any(f["id"] == "t04-boom" and "backend exploded" in f["why"] for f in b3["failed"]),
           "deleter 抛错 → 计 failed 且全批继续（不中断）")

        # ---- prune allow-legacy：双旗放行 ----
        calls, deleter = make_calls()
        r4 = asyncio.run(client.cmd_ticket_prune(
            {"execute": True, "allow_legacy": True},
            entries=[{"id": "t04-legacy", "sa_project": "suyou", "close_ts": 1}],
            deleter=deleter))
        ok(calls == ["t04-legacy"], "--allow-legacy：legacy 票放行删除")

        # ---- prune project 过滤 ----
        calls, deleter = make_calls()
        r5 = asyncio.run(client.cmd_ticket_prune(
            {"execute": True, "project": "suyou"}, entries=list(ENTRIES), deleter=deleter))
        ok("t04-other-proj" not in r5["result"]["deleted"]
           and "t04-other-proj" not in r5["result"]["skipped_not_archived"],
           "project 过滤：非本 project 的票不入任何清单")
        r5e = asyncio.run(client.cmd_ticket_prune({"project": "BAD KEY!"}, entries=[], deleter=deleter))
        ok(not r5e["ok"], "project 形状非法 → 显式报错")

        # ---- archive-legacy：诚实过账 ----
        entries_l = [{"id": "t04-old-1", "sa_project": "suyou", "close_ts": 1},
                     {"id": "t04-old-2", "sa_project": "suyou", "close_ts": 1},
                     {"id": "t04-archived", "sa_project": "suyou", "close_ts": 1},  # 已有真档
                     {"id": "t04-bad", "sa_project": "suyou", "close_ts": 1}]      # 畸形

        async def result_of(wf_id):
            if wf_id == "t04-old-2":
                raise RuntimeError("result 不可达")
            return {"meta": {"stage": "merge", "status": "closed", "ticket": wf_id}}

        ra = asyncio.run(client.cmd_ticket_archive_legacy(
            {}, entries=list(entries_l), result_of=result_of))
        ba = ra["result"]
        ok({w["id"] for w in ba["written"]} == {"t04-old-1", "t04-old-2"},
           "无档票过账 written；已有真档跳过不覆盖")
        ok("t04-archived" in ba["skipped"], "已有 manifest 幂等跳过")
        ok(any(f["id"] == "t04-bad" for f in ba["failed"]), "畸形 manifest 计 failed")
        m1 = json.loads((Path(ROOT) / "suyou/data/tickets/t04-old-1/archive.json").read_text(
            encoding="utf-8"))
        ok(m1["legacy"] is True and m1["files"] == [] and m1["schema"] == "v1",
           "legacy manifest：schema v1 + files 空")
        ok("不可恢复" in (m1.get("reason") or ""), "legacy reason 明牌")
        ok(m1["meta"].get("ticket") == "t04-old-1", "meta 快照来自 result_of")
        m2 = json.loads((Path(ROOT) / "suyou/data/tickets/t04-old-2/archive.json").read_text(
            encoding="utf-8"))
        ok("_meta_unavailable" in m2["meta"], "result_of 失败 → 记 _meta_unavailable 不炸")
        # 过账幂等：再跑全部 skipped
        ra2 = asyncio.run(client.cmd_ticket_archive_legacy(
            {}, entries=list(entries_l), result_of=result_of))
        ok(len(ra2["result"]["written"]) == 0 and len(ra2["result"]["skipped"]) == 3,
           "archive-legacy 幂等：二次过账零 written")

        # ---- _read_archive_manifest 三态（消费侧共用判定）----
        st = client._read_archive_manifest("t04-archived", "suyou")
        ok(st["state"] == "ok" and st["legacy"] is False, "manifest 三态：ok")
        st2 = client._read_archive_manifest("t04-legacy", "suyou")
        ok(st2["state"] == "ok" and st2["legacy"] is True, "manifest 三态：ok+legacy")
        st3 = client._read_archive_manifest("t04-missing", "suyou")
        ok(st3["state"] == "missing", "manifest 三态：missing")
        st4 = client._read_archive_manifest("t04-bad", "suyou")
        ok(st4["state"] == "malformed", "manifest 三态：malformed")
    finally:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, FAIL, ENV_FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
