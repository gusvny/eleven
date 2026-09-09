# fixture_ticket_worker.py —— 夹具票收口 worker（260908；lib_stage_console 的
# seedFixtures spawn 本脚本，把 RUNNING 的夹具票跑到 COMPLETED）。
#
# 生命周期=一次性排水：起 Worker 轮询各夹具票的专属队列（sandbar-ticket-<id>），
# 等全部票 COMPLETED 即自退。票已收口的常态下秒退。
# 为什么值得一个真 worker 进程：COMPLETED 之后整张票免 worker 直读（见
# fixture_ticket_fake.py 头注）——常驻成本只在首种那几秒。
#
# 用法： python3 fixture_ticket_worker.py <host:port> <namespace> <id1,id2,...> [超时秒]
# 退出码：0=全部收口；1=超时/失败（stderr 给原因——seedFixtures 如实 warn）。
import asyncio
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from fixture_ticket_fake import FixtureTicket


async def main() -> int:
    addr, ns, ids_raw = sys.argv[1], sys.argv[2], sys.argv[3]
    budget = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0
    queues = ["sandbar-ticket-%s" % t for t in ids_raw.split(",") if t.strip()]
    client = await Client.connect(addr, namespace=ns)
    # temporalio 1.18 的 Worker 单 task_queue——每票一个 Worker 并发跑。
    workers = [Worker(client, task_queue=q, workflows=[FixtureTicket]) for q in queues]
    wts = [asyncio.create_task(w.run()) for w in workers]

    async def done_all() -> bool:
        for tid in ids_raw.split(","):
            tid = tid.strip()
            if not tid:
                continue
            try:
                d = await client.get_workflow_handle(tid).describe()
            except Exception:
                return False
            if (d.status.name if d.status is not None else "") != "COMPLETED":
                return False
        return True

    try:
        waited = 0.0
        while waited < budget:
            if await done_all():
                return 0
            await asyncio.sleep(2.0)
            waited += 2.0
        print("夹具票收口超时（%ss 内未全部 COMPLETED）" % int(budget), file=sys.stderr)
        return 1
    finally:
        for w in workers:
            await w.shutdown()
        await asyncio.gather(*wts, return_exceptions=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
