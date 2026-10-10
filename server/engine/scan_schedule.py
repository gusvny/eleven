#!/usr/bin/env python3
"""dispatcher-scan Schedule governance tool (M6, t260821-m6-scan-expand).

Since t261009-50 the scan tick this Schedule fires also ASKS the line round
for every declared develop line (event trigger + scheduled backstop; body
truth `develop_certify.line_round_tick`, pending wiring see
integration/t261009-50/wiring-handoff.md). This tool's own face is unchanged:
it governs pause/resume/trigger of the Schedule, nothing else.

Note governance: pause/resume must carry a note saying who, why, and at what
frequency. The note goes into the schedule state, so anyone can read it via
`describe` or the Temporal UI — no unexplained pauses.

Usage (from the engine directory, with .venv/bin/python):
    scan_schedule.py describe                          # read-only snapshot (includes num_actions evidence)
    scan_schedule.py resume [--minutes 45] [--note …]  # set interval + unpause (default 45min)
    scan_schedule.py pause  --note …                   # pause (a reason is required)
    scan_schedule.py trigger                           # trigger one scan round immediately

stdout is always a single JSON line {ok, result|error} (same contract as
client.py). This tool is an OPS channel (for humans / the steward); it is not
exposed to the dsh model tool surface — the model side can only read schedules
via client.py schedule-list (read-only).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta
from typing import Any, Dict

from temporalio.client import (
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
)
from temporalio.service import RPCError

from shared import SCHEDULE_ID, TARGET_HOST, NAMESPACE
from temporalio.client import Client

DEFAULT_MINUTES = 45  # M6 decided interval: 45min (inside the suggested 30-60min band)


def _ok(result: Any) -> Dict[str, Any]:
    return {"ok": True, "result": result}


def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}


async def _connect() -> Client:
    return await Client.connect(TARGET_HOST, namespace=NAMESPACE)


async def _describe(handle) -> Dict[str, Any]:
    desc = await handle.describe()
    spec = desc.schedule.spec
    intervals = [str(iv.every) for iv in (spec.intervals or [])] if spec else []
    state = desc.schedule.state
    info = desc.info
    return {
        "id": desc.id,
        "paused": bool(state.paused) if state else None,
        "note": (state.note or "") if state else "",
        "intervals": intervals,
        "overlap": str(desc.schedule.policy.overlap).split(".")[-1]
        if desc.schedule.policy and desc.schedule.policy.overlap else "",
        "num_actions": info.num_actions if info else 0,
        "next_action_times": [t.isoformat(timespec="seconds")
                              for t in (info.next_action_times or [])][:3] if info else [],
        "recent_action_times": [a.scheduled_at.isoformat(timespec="seconds")
                                for a in (info.recent_actions or [])][-3:] if info else [],
    }


async def cmd_describe() -> Dict[str, Any]:
    client = await _connect()
    try:
        return _ok(await _describe(client.get_schedule_handle(SCHEDULE_ID)))
    except RPCError as e:
        return _err("schedule %s 不存在或不可达：%s" % (SCHEDULE_ID, e))


async def cmd_resume(minutes: int, note: str) -> Dict[str, Any]:
    if minutes < 1 or minutes > 24 * 60:
        return _err("minutes 超出合理区间（1–1440）：%r" % minutes)
    client = await _connect()
    handle = client.get_schedule_handle(SCHEDULE_ID)

    def _upd(inp) -> ScheduleUpdate:
        sched = inp.description.schedule
        sched.spec = ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=minutes))])
        sched.policy = SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP)
        return ScheduleUpdate(schedule=sched)

    try:
        await handle.update(_upd)
    except RPCError as e:
        return _err("schedule %s 不存在或不可达：%s" % (SCHEDULE_ID, e))
    await handle.unpause(note=note)
    return _ok({"resumed": True, "minutes": minutes, "note": note,
                "after": await _describe(handle)})


async def cmd_pause(note: str) -> Dict[str, Any]:
    if not note:
        return _err("pause 必须带 --note（note 治理：不留无解释的暂停）")
    client = await _connect()
    handle = client.get_schedule_handle(SCHEDULE_ID)
    await handle.pause(note=note)
    return _ok({"paused": True, "note": note, "after": await _describe(handle)})


async def cmd_trigger() -> Dict[str, Any]:
    client = await _connect()
    handle = client.get_schedule_handle(SCHEDULE_ID)
    await handle.trigger()
    return _ok({"triggered": True, "after": await _describe(handle)})


USAGE = (
    "用法：scan_schedule.py <describe|resume|pause|trigger> [--minutes N] [--note 文本]\n"
    "note 治理：pause/resume 必须带 --note（谁、为什么、什么频率），进 schedule state 可查。"
)


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(json.dumps(_err(USAGE), ensure_ascii=False))
        return
    sub = argv[0]
    minutes = DEFAULT_MINUTES
    note = ""
    i = 1
    while i < len(argv):
        if argv[i] == "--minutes" and i + 1 < len(argv):
            minutes = int(argv[i + 1])
            i += 2
        elif argv[i] == "--note" and i + 1 < len(argv):
            note = argv[i + 1]
            i += 2
        else:
            print(json.dumps(_err("未知参数 %r。%s" % (argv[i], USAGE)), ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
            return
    try:
        if sub == "describe":
            result = asyncio.run(cmd_describe())
        elif sub == "resume":
            if not note:
                result = _err("resume 必须带 --note（note 治理：说清谁/为什么/什么频率）")
            else:
                result = asyncio.run(cmd_resume(minutes, note))
        elif sub == "pause":
            result = asyncio.run(cmd_pause(note))
        elif sub == "trigger":
            result = asyncio.run(cmd_trigger())
        else:
            result = _err("未知子命令 %r。%s" % (sub, USAGE))
    except Exception as e:  # infrastructure failure -> structured receipt
        result = _err("%s: %s" % (type(e).__name__, e))
    print(json.dumps(result, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))


if __name__ == "__main__":
    main()
