# fixture_holder_worker.py —— t260904-14 真票子用例的占位 worker（260908）。
#
# 生命周期=场景子用例时长：装载 fixture_holder_fake 常驻指定专属队列，让在飞票
# 的 query 快速失败（见 fixture_holder_fake.py 头注）。场景 finally 负责 SIGTERM
# 本进程（temporal dev-server 死后 workflow 也不复存在，无残留）。
#
# 用法： python3 fixture_holder_worker.py <host:port> <namespace> <ticket-id>
import asyncio
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from fixture_holder_fake import FixtureHolder


async def main() -> int:
    addr, ns, tid = sys.argv[1], sys.argv[2], sys.argv[3]
    client = await Client.connect(addr, namespace=ns)
    worker = Worker(client, task_queue="sandbar-ticket-%s" % tid,
                    workflows=[FixtureHolder])
    await worker.run()  # 常驻到被 SIGTERM（场景 finally 必杀）
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
