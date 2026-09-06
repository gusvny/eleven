#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-02 共享探针（无 sc_ 前缀=共享代码，不登记场景清单）：
describe 指定 workflow 的服务端可见状态（watch 收口自退的判据面）。

用法：probe_wf_status.py <host:port> <namespace> <workflow_id>
输出 stdout 单行 JSON：
  {"found": true,  "status": "COMPLETED"}   # 状态名（Temporal enum name）
  {"found": false, "reason": "…"}           # 不存在/连接失败（reason 点名）

断言锚=Temporal 服务端可见的 workflow 终态（对外数据契约），非实现内部结构。
"""
import asyncio
import json
import sys


async def main():
    if len(sys.argv) < 4:
        print(json.dumps({"found": False, "reason": "usage: probe_wf_status.py host ns wf_id"}))
        return
    host, ns, wfid = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        from temporalio.client import Client
    except ImportError:
        print(json.dumps({"found": False, "reason": "temporalio_missing"}))
        return
    try:
        c = await Client.connect(host, namespace=ns)
        d = await c.get_workflow_handle(wfid).describe()
        print(json.dumps({"found": True,
                          "status": d.status.name if d.status is not None else ""}))
    except Exception as e:
        print(json.dumps({"found": False,
                          "reason": "%s:%s" % (type(e).__name__, str(e)[:160])}))


if __name__ == "__main__":
    asyncio.run(main())
