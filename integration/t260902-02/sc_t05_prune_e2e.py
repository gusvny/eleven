# -*- coding: utf-8 -*-
"""t260902-02 t05 —— `ticket-prune` 黑盒 e2e：干跑零删除/归档才可删/legacy 双旗/删后报告可回读。

用户故事（Temporal 回归运行态）：
- 引擎里 closed 的工单历史只在「归档真源已落 data 目录」后才可清；dry-run 默认，
  一滴都不许真删；project 过滤只碰本测试自己的票（共享测试环境不误伤他人）；
- legacy 票（归档时泳道已拆、报告不可恢复）必须 execute+allow_legacy 双旗才删，
  防误删审计凭据；
- **根治证据**：Temporal 历史删掉后，data 目录里的 stage 报告仍可读——
  「完结工单 stage 报告随泳道拆除丢失」不再发生。

e2e 手法：自带临时 worker 造 3 张 closed「票」（workflow type=DevLaneWorkflow、
专属队列前缀、ProjectKey SA=itestkey，与真票同列表面），data 目录用 tmp fixture。
**只连显式设置的测试环境**（SUYOU_TARGET_HOST 未设/=生产缺省 7233 → SKIP）。

跑法：python3 integration/t260902-02/t05_prune_e2e.py（cwd=泳道根）
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
try:
    from temporalio import workflow  # noqa: E402
    from temporalio.client import Client  # noqa: E402
    from temporalio.worker import Worker  # noqa: E402

    shared = fx.load_module("shared")  # noqa: E402  env 外部设定后现读 TARGET_HOST/NAMESPACE
    SDK_OK = True
except ImportError as e:
    sdk_err = sdk_err or ("temporalio 导入失败：%s" % e)

KEY = "itestkey"
T_ARCH = "t-integ-arch1"   # 已归档（非 legacy）→ 可删
T_UNA = "t-integ-unarch1"  # 无 archive.json → 拒删
T_LEG = "t-integ-legacy1"  # legacy 归档 → 需 --allow-legacy


if SDK_OK:

    @workflow.defn(name="DevLaneWorkflow")
    class FakeTicket:
        @workflow.run
        async def run(self, mode: str) -> dict:
            return {"meta": {"project": KEY, "status": "closed", "stage": "done",
                             "title": "integ-t05"}, "status": "ok"}


def write_manifest(sb, ticket, legacy):
    d = sb.archive_dir(KEY, ticket)
    d.mkdir(parents=True, exist_ok=True)
    m = {"schema": "v1", "ticket_id": ticket, "archived_at": "2026-09-02T00:00:00+08:00",
         "legacy": legacy, "files": [], "meta": {"stage": "done", "status": "closed"}}
    if legacy:
        m["reason"] = "归档前泳道已拆除，stage 报告不可恢复（存量工单诚实过账）"
    else:
        m["files"] = [{"src": ".suyou/stage_merge_gen0.json",
                       "dst": "stages/stage_merge_gen0.json", "bytes": 13}]
        (d / "stages").mkdir(exist_ok=True)
        (d / "stages" / "stage_merge_gen0.json").write_text('{"status":"ok"}', "utf-8")
    (d / "archive.json").write_text(json.dumps(m, ensure_ascii=False), "utf-8")


async def exists(client, wf_id):
    try:
        await asyncio.wait_for(client.get_workflow_handle(wf_id).describe(), 20)
        return True
    except Exception:
        return False


async def hard_delete(client, ns, wf_id):
    from temporalio.api.common.v1 import WorkflowExecution
    from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest
    try:
        await asyncio.wait_for(client.workflow_service.delete_workflow_execution(
            DeleteWorkflowExecutionRequest(namespace=ns,
                                           workflow_execution=WorkflowExecution(workflow_id=wf_id))), 20)
    except Exception:
        pass


def payload_of(r, label):
    """client.py 末行 JSON 回执；解析失败 = FAIL。"""
    try:
        payload = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        L.ok(False, "%s 回执不是末行 JSON（stdout=%r）" % (label, r.stdout[-200:]))
        return None
    if not payload.get("ok"):
        L.ok(False, "%s 回执 ok=false：%s" % (label, str(payload.get("error"))[:200]))
        return None
    return payload.get("result") or {}


async def scenario():
    client = await asyncio.wait_for(Client.connect(shared.TARGET_HOST, namespace=shared.NAMESPACE), 20)
    tq = shared.TICKET_QUEUE_PREFIX + "integt05"
    worker = Worker(client, task_queue=tq, workflows=[FakeTicket])
    await worker.start()
    spawned = [T_ARCH, T_UNA, T_LEG]
    try:
        for tid in spawned:
            await asyncio.wait_for(client.start_workflow(
                FakeTicket.run, "ok", id=tid, task_queue=tq,
                typed_search_attributes=shared.project_search_attributes(KEY)), 20)
        for tid in spawned:
            await asyncio.wait_for(client.get_workflow_handle(tid).result(), 30)

        with fx.Sandbox() as sb:
            write_manifest(sb, T_ARCH, legacy=False)
            write_manifest(sb, T_LEG, legacy=True)

            def run_prune(extra):
                args = {"project": KEY}
                args.update(extra)
                return fx.run_client(["ticket-prune", json.dumps(args)], {})

            # —— dry-run：三票各归各位（将删/未归档/legacy 待确认），deleter 零调用 ——
            p1 = payload_of(fx.run_client(
                ["ticket-prune", json.dumps({"project": KEY})], {}), "prune dry-run")
            if p1 is not None:
                L.ok(T_ARCH in p1.get("deleted", []), "dry-run：已归档票进「将删」清单")
                L.ok(T_UNA in p1.get("skipped_not_archived", []), "dry-run：未归档票进拒删清单")
                L.ok(T_LEG in p1.get("skipped_legacy", []), "dry-run：legacy 票进双旗待确认清单")
            for tid in spawned:
                L.ok(await exists(client, tid), "dry-run 后 %s 历史仍在（零删除）" % tid)

            # —— execute：只删已归档非 legacy ——
            p2 = payload_of(fx.run_prune({"execute": True}), "prune execute")
            if p2 is not None:
                L.ok(T_ARCH in p2.get("deleted", []), "execute：已归档票已删")
                L.ok(T_UNA in p2.get("skipped_not_archived", []), "execute：未归档票拒删")
                L.ok(T_LEG in p2.get("skipped_legacy", []), "execute：legacy 无 --allow-legacy 拒删")
            L.ok(not await exists(client, T_ARCH), "execute 后 %s 历史已清（describe 消失）" % T_ARCH)
            L.ok(await exists(client, T_UNA), "未归档票 %s 历史仍在" % T_UNA)
            L.ok(await exists(client, T_LEG), "legacy 票 %s 历史仍在" % T_LEG)

            # —— 根治证据：引擎历史删了，data 目录报告仍在且可读 ——
            mpath = sb.archive_dir(KEY, T_ARCH)
            L.ok(mpath.joinpath("archive.json").is_file(), "Temporal 历史删除后 archive.json 仍在")
            L.ok(mpath.joinpath("stages/stage_merge_gen0.json").is_file(),
                 "Temporal 历史删除后 stage 报告仍可读（根治丢失）")

            # —— execute + allow-legacy：legacy 可删，未归档仍拒 ——
            p3 = payload_of(fx.run_prune({"execute": True, "allow_legacy": True}),
                            "prune execute+allow-legacy")
            if p3 is not None:
                L.ok(T_LEG in p3.get("deleted", []), "双旗后 legacy 票已删")
                L.ok(T_UNA in p3.get("skipped_not_archived", []), "未归档票双旗下仍拒删（不被误伤）")
            L.ok(not await exists(client, T_LEG), "双旗后 %s 历史已清" % T_LEG)
            L.ok(await exists(client, T_UNA), "未归档票 %s 历史仍在（终态）" % T_UNA)

            # —— 拒删票绝不写入任何归档产物 ——
            L.ok(not sb.archive_dir(KEY, T_UNA).exists(), "拒删票未产出归档目录")
    finally:
        await hard_delete(client, shared.NAMESPACE, T_UNA)
        for tid in (T_ARCH, T_LEG):
            if await exists(client, tid):
                await hard_delete(client, shared.NAMESPACE, tid)
        await worker.shutdown()


def main():
    if sdk_err:
        L.skip1("全部用例", sdk_err)
        return L.finish()
    if guard_err:
        L.skip1("全部用例", guard_err)
        return L.finish()
    try:
        asyncio.run(asyncio.wait_for(scenario(), 300))
    except Exception as e:
        L.ok(False, "e2e 场景异常：%s: %s" % (type(e).__name__, str(e)[:300]))
    return L.finish()


if __name__ == "__main__":
    sys.exit(main())
