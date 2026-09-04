#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-02 共享探针（无 sc_ 前缀=共享代码，不登记清单）：
经 temporalio Client fetch_history 取 WorkflowExecutionStarted 事件的 input payload。

用法：probe_wf_input.py <host:port> <namespace> <workflow_id>
输出：stdout 单行 JSON ——
  {"found": true,  "input": {...}}          # 找到起始事件且有 payload
  {"found": true,  "input": {"_raw": "…"}}  # payload 非 JSON（编码面证据，不静默丢）
  {"found": false, "reason": "not_found:…"} # 工单在该 namespace 不存在（隔离断言用）
  {"found": false, "reason": "…"}           # 其它失败（连接/历史空）

断言锚=持久化在 Temporal 里的工单 payload（对外数据契约），非实现内部结构。
"""
import asyncio
import json
import sys


async def main():
    if len(sys.argv) < 4:
        print(json.dumps({"found": False, "reason": "usage: probe_wf_input.py host ns tid"}))
        return
    host, ns, tid = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        from temporalio.client import Client
    except ImportError:
        print(json.dumps({"found": False, "reason": "temporalio_missing"}))
        return
    try:
        c = await Client.connect(host, namespace=ns)
        h = c.get_workflow_handle(tid)
        hist = await h.fetch_history()
    except Exception as e:
        print(json.dumps({"found": False,
                          "reason": "%s:%s" % (type(e).__name__, str(e)[:160])}))
        return
    for ev in hist.events:
        try:
            if not ev.HasField("workflow_execution_started_event_attributes"):
                continue
            payloads = ev.workflow_execution_started_event_attributes.input.payloads
        except Exception:
            continue
        if not payloads:
            continue
        raw = bytes(payloads[0].data)
        try:
            data = json.loads(raw)
        except Exception:
            data = {"_raw": raw[:200].decode("utf-8", "replace")}
        print(json.dumps({"found": True, "input": data}, ensure_ascii=False))
        return
    print(json.dumps({"found": False, "reason": "no_started_event_or_empty_input"}))


if __name__ == "__main__":
    asyncio.run(main())
