# -*- coding: utf-8 -*-
"""t260902-02 t06 —— `ticket-archive-legacy` 诚实过账：legacy manifest 形状 + 闭环口径。

用户故事（存量 40 票处置，R4）：本单落地前的已完结工单，stage 报告已随泳道拆除
丢失、无法如实补产。archive-legacy 必须**诚实**：archive.json 标 legacy:true、
文件清单为空、reason 写明「不可恢复」——不伪造报告；不闭环的票不许删落盘：
- meta/sa_project 不可得的票（project 拼不出归档路径，N3）→ 计入 failed 报告，
  零文件产物，不静默；
- 已有真档的票 → 跳过（幂等，绝不覆盖真档）。

手法：client.py 公开注入缝（entries/result_of）+ 真文件系统（tmp data 根）直调
cmd_ticket_archive_legacy——不依赖真 Temporal server，有 SDK 即可跑；running 票
不收的 live 子用例走真测试环境（未设 → 如实 ENV_FAIL，exit 2）。

跑法：python3 integration/t260902-02/t06_archive_legacy_e2e.py（cwd=泳道根）
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

L = fx.Ledger()

PY, sdk_err = fx.ensure_sdk()
guard_err = fx.test_env_guard()

SDK_OK = False
client_mod = None
try:
    from temporalio.client import Client  # noqa: E402
    from temporalio.worker import Worker  # noqa: E402

    # 假票类住独立模块（lib/fake_ticket.py）：workflow 沙箱只复导入定义类所在的
    # 那个模块；留在本文件里沙箱会整文件重跑 __main__，模块级的 shared/fixture
    # 加载（pathlib.Path.resolve/subprocess 在沙箱禁用）会在校验时炸
    from fake_ticket import FakeTicket  # noqa: E402
    shared = fx.load_module("shared")  # noqa: E402
    client_mod = fx.load_module("client")
    SDK_OK = True
except ImportError as e:
    sdk_err = sdk_err or ("temporalio 导入失败：%s" % e)

KEY = "itestkey"
T_OK = "t-integ-legok1"    # closed + ProjectKey SA → 诚实 legacy 归档
T_NSA = "t-integ-legnsa1"  # sa_project 不可得 → failed 报告，零产物
META = {"project": KEY, "status": "closed", "stage": "done", "title": "integ-t06"}


if SDK_OK:
    _PAYLOAD = {"meta": META, "status": "ok"}


async def _result_ok(tid):
    return {"meta": dict(META)}


async def _inject_scenario(sb):
    """注入缝直调真命令逻辑（活文件系统，零 Temporal server 依赖）。"""
    entries = [{"id": T_OK, "sa_project": KEY, "close_ts": 0},
               {"id": T_NSA, "sa_project": "", "close_ts": 0}]
    res = await client_mod.cmd_ticket_archive_legacy(
        {}, entries=entries, result_of=_result_ok)
    data = res.get("result") or {}
    L.ok(res.get("ok") is True, "archive-legacy 回执 ok")
    written = [w.get("id") for w in data.get("written", [])]
    L.ok(T_OK in written, "%s 过账 written 清单" % T_OK)
    L.ok(T_NSA in [f.get("id") for f in data.get("failed", [])],
         "project 不可得票计入 failed（N3 不静默）")

    m = sb.manifest(KEY, T_OK)
    L.ok(m is not None, "%s 产出 archive.json" % T_OK)
    if m:
        L.ok(m.get("legacy") is True, "legacy=true")
        L.ok(m.get("files") == [], "files 为空（不伪造报告）")
        # 261012 (KI-01M4PX56PCD family): anchor the promise, not the prose.
        # The copy-language gate anglicized this reason ("...stage report
        # unrecoverable (legacy tickets posted honestly)"); the promise is
        # that the reason NAMES the unrecoverable state — anchor the stable
        # token in either language, never one language's wording.
        _reason = str(m.get("reason", ""))
        L.ok("unrecoverable" in _reason.lower() or "不可恢复" in _reason,
             "reason 写明报告不可恢复（实际 %r）" % m.get("reason"))
        L.ok(m.get("ticket_id") == T_OK, "ticket_id 回写")
        L.ok((m.get("meta") or {}).get("title") == "integ-t06", "meta 快照原样入 manifest")
    L.ok(not sb.archive_dir(KEY, T_NSA).exists(), "failed 票零文件产物")

    # —— 幂等：重跑不覆盖真档（第二跑 T_OK 进 skipped）——
    res2 = await client_mod.cmd_ticket_archive_legacy(
        {}, entries=[{"id": T_OK, "sa_project": KEY, "close_ts": 0}],
        result_of=_result_ok)
    data2 = (res2.get("result") or {})
    L.ok(T_OK in data2.get("skipped", []), "重跑：已有档票进 skipped（幂等，不覆盖真档）")
    m2 = sb.manifest(KEY, T_OK)
    L.ok(m2 is not None and m2.get("legacy") is True and m2.get("files") == [],
         "重跑后 manifest 语义不漂（仍 legacy、不补产文件）")


async def _live_scenario():
    """live 子用例：running 的票不进过账面（只列 COMPLETED）。"""
    client = await asyncio.wait_for(Client.connect(shared.TARGET_HOST, namespace=shared.NAMESPACE), 20)
    tq = shared.TICKET_QUEUE_PREFIX + "integt06"
    worker = Worker(client, task_queue=tq, workflows=[FakeTicket])
    wt = asyncio.create_task(worker.run())  # 1.18 API：run() 常驻，shutdown() 收场
    try:
        await asyncio.wait_for(client.start_workflow(
            FakeTicket.run, {"mode": "hang", "payload": dict(_PAYLOAD)},
            id=T_RUN, task_queue=tq,
            search_attributes=shared.project_search_attributes(KEY)), 20)
        with fx.Sandbox() as sb:
            res = await client_mod.cmd_ticket_archive_legacy({"project": KEY})
            data = res.get("result") or {}
            all_seen = (data.get("written", []) + data.get("skipped", [])
                        + data.get("failed", []))
            ids = [x.get("id") if isinstance(x, dict) else x for x in all_seen]
            L.ok(T_RUN not in ids, "running 票不在过账面（不收未完成执行）")
            L.ok(not sb.archive_dir(KEY, T_RUN).exists(), "running 票零产物")
    finally:
        try:
            await asyncio.wait_for(client.get_workflow_handle(T_RUN).terminate(), 20)
        except Exception:
            pass
        from temporalio.api.common.v1 import WorkflowExecution
        from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest
        try:
            await asyncio.wait_for(client.workflow_service.delete_workflow_execution(
                DeleteWorkflowExecutionRequest(
                    namespace=shared.NAMESPACE,
                    workflow_execution=WorkflowExecution(workflow_id=T_RUN))), 20)
        except Exception:
            pass
        await worker.shutdown()
        await asyncio.wait_for(wt, 20)


T_RUN = "t-integ-legrun1"  # running → 不进 COMPLETED 过账面


def main():
    if sdk_err or not SDK_OK:
        L.skip1("全部用例", sdk_err or "client 模块导入失败")
        return L.finish()
    with fx.Sandbox() as sb:
        try:
            asyncio.run(asyncio.wait_for(_inject_scenario(sb), 120))
        except Exception as e:
            L.ok(False, "注入缝场景异常：%s: %s" % (type(e).__name__, str(e)[:300]))
    if guard_err:
        L.skip1("live 子用例（running 不收）", guard_err)
    else:
        try:
            asyncio.run(asyncio.wait_for(_live_scenario(), 180))
        except Exception as e:
            L.ok(False, "live 子用例异常：%s: %s" % (type(e).__name__, str(e)[:300]))
    return L.finish()


if __name__ == "__main__":
    sys.exit(main())
