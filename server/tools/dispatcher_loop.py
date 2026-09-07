#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatcher_loop —— 总管单例巡检（260820 用户要求：dispatcher 应被定时调度起来检查+派发，且 singleton）。

职责：
1. 单例锁：锁文件 /tmp/sandbar-dispatcher.lock（JSON {session, ts}，TTL 600s；旧 /tmp/sandbar-dispatcher.lock 只读回落，退役账#4）。
   - 持有锁（或锁过期可接管）→ 续期，返回 lock_held=true，继续巡检；
   - 被他人持有且未过期 → lock_held=false，只读不派（防多个 dispatcher 会话同时派活撞车）。
2. 巡检产出待办清单（不在此派发——派发是 dsh dispatcher 会话的 dispatch_<role> 动作）：
   - 待派：stage_state=awaiting 且 status∈{dispatched,rework}（要 spawn 下一棒 agent）
   - 待验收：status=settled（agent 已结算，等总管验收/推进）
   - 待审批：stage_state=awaiting-human（等用户，不自动派，只提示）
3. 幂等：同一工单不重复派（lock 会话内已派记录可选，本版只列清单，派发去重靠工单 status/stage_state 推进）。

用法（仓库根）：
  python3 server/admin.py call dispatcher_loop '{"session":"<dispatcher 会话 id>"}'
  或 dsh-schedule 提醒里由 dispatcher 直接跑本脚本/读输出。
"""
import json
import os
import time
from pathlib import Path

# 锁文件改名（t260907-04）：新锁 /tmp/sandbar-dispatcher.lock 为权威；旧锁只读
# 回落——新锁无而旧锁 TTL 内 → 视为 held（防旧实例并行双派）。旧锁不写不删。
# 退役账#4：巡检观测旧锁零命中连续一个周期后，删 LEGACY_LOCK 与回落分支。
LOCK = Path("/tmp/sandbar-dispatcher.lock")
LEGACY_LOCK = Path("/tmp/suyou-dispatcher.lock")
TTL = 600  # 秒：锁超时视为失活，可接管
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def _tickets():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ticket", str(HERE / "ticket.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(args):
    session = (args.get("session") or os.environ.get("DSH_SESSION_ID") or "unknown").strip()
    now = int(time.time())
    lock_held = True
    # 单例锁（新锁权威；旧锁只读回落，TTL 内视为他人持有）
    try:
        cur = json.loads(LOCK.read_text(encoding="utf-8"))
    except Exception:
        cur = None
    if not cur:
        try:
            cur = json.loads(LEGACY_LOCK.read_text(encoding="utf-8"))
        except Exception:
            cur = None
    if cur and cur.get("session") != session and now - int(cur.get("ts", 0)) < TTL:
        lock_held = False  # 他人持有且未过期
    if lock_held:
        LOCK.write_text(json.dumps({"session": session, "ts": now}, ensure_ascii=False), encoding="utf-8")

    tk = _tickets()
    pending_dispatch, pending_verify, awaiting_human = [], [], []
    try:
        rows = tk._list({}).get("tickets", [])
    except Exception:
        # 兼容：list 可能返回 {count,tickets} 或直接列表
        res = tk.run({"op": "list"})
        rows = res.get("tickets", []) if isinstance(res, dict) else []
    for t in rows:
        status, st = t.get("status"), t.get("stage_state")
        if st == "awaiting-human":
            awaiting_human.append({"id": t.get("id"), "title": t.get("title", "")[:40]})
        elif st == "awaiting" and status in ("dispatched", "rework"):
            pending_dispatch.append({"id": t.get("id"), "role": t.get("role"), "workflow": t.get("workflow"),
                                     "title": t.get("title", "")[:40]})
        elif status == "settled":
            pending_verify.append({"id": t.get("id"), "role": t.get("role"), "title": t.get("title", "")[:40]})

    return {
        "lock_held": lock_held,
        "session": session,
        "ts": now,
        "待派": pending_dispatch,
        "待验收": pending_verify,
        "待审批": awaiting_human,
    }


TOOL = {
    "name": "dispatcher_loop",
    "description": "总管单例巡检：带 /tmp/sandbar-dispatcher.lock 单例锁（旧锁只读回落）（TTL 600s），列出待派/待验收/待审批工单，供 dispatcher 定时派发与推进。lock_held=false 时只读不派。",
    "parameters": {
        "type": "object",
        "properties": {
            "session": {"type": "string", "description": "当前 dispatcher 会话 id（缺省取 DSH_SESSION_ID 环境变量）"}
        },
        "required": []
    },
}
