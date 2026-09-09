# fixture_ticket_worker.py — drain worker for fixture tickets (260908).
# lib_stage_console's seedFixtures spawns this script to drive RUNNING
# fixture tickets to COMPLETED.
#
# Lifecycle: one-shot drain. It starts a Worker polling each fixture ticket's
# dedicated queue (sandbar-ticket-<id>) and exits once every ticket is
# COMPLETED. When tickets are already closed, it exits in about a second.
# A real worker process is worth it: after COMPLETED the whole ticket is
# readable with no worker at all (see the header of fixture_ticket_fake.py),
# so the running cost only exists for those few seconds of first seeding.
#
# Usage: python3 fixture_ticket_worker.py <host:port> <namespace> <id1,id2,...> [timeout seconds]
# Exit codes: 0 = all closed; 1 = timeout or failure (reason on stderr —
# seedFixtures surfaces it as a warning).
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
    # temporalio 1.18 Workers take a single task_queue — run one Worker per ticket.
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
