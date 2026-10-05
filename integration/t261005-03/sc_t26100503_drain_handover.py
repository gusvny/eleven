#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-03 scenario ①: drain hands over — the single-poller guard decides on the
draining state, not pid liveness (clause A, grey-box L3, offline, zero docker).

User-perceivable contract (261005 incident: two RUNNING tickets with ZERO pollers
for ~15 min because a draining-but-alive worker's pid blocked the replacement):
- D1 a live pidfile pid whose meta says state=draining (and whose meta.pid matches
  the pidfile pid) must NOT block a replacement: the guard admits the start and
  names the takeover in its log — the zero-poller window on a RUNNING ticket must
  not outlive one meta write;
- D2 a live pid with the OLD meta shape (no state key — every worker spawned before
  this ticket) must still be refused exactly as today: backward compatibility is a
  refusal, never a surprise double-poller;
- D3 a draining meta whose meta.pid does NOT match the pidfile pid is a mismatch:
  the guard stays conservative and refuses with the mismatch named (never guesses);
- D4 a malformed meta sidecar keeps today's fail-conservative refusal, named;
- D5 a meta written in the old shape must read back as serving (the read side takes
  keys on demand) so pre-ticket workers are classified, not crashed on.

Intent split: the ensure-side decision ('replaced-draining') and the graceful-
shutdown meta rewrite belong to the engine gate / developer battery (they need a
live Temporal face or the in-process worker harness); this entry pins the slot
arbitration contract at the guard face. Engine modules unavailable = ENV_FAIL
exit 2. Pre-implement D1 (and the state-key read) is red expected — TDD signal;
arbitrate/merge must be green.

Run: PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
     integration/t261005-03/sc_t26100503_drain_handover.py  (cwd = repo root)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t26100503 import (  # noqa: E402
    check, env_fail, load_engine, mk_lane_root, summary, write_meta, write_pidfile,
)


def main():
    loaded, why = load_engine()
    if loaded is None:
        env_fail("engine modules unavailable (%s) — no stdlib substitute case" % why)
    shared, worker = loaded
    root = mk_lane_root("drain")
    pidfile = root / ".lane" / "t261005-03-fixture" / "worker.pid"
    repo_root = str(shared.REPO_ROOT)
    live_pid = os.getpid()  # a real live pid: this interpreter itself

    # --- D5 backward-compatible read: old-shape meta reads as serving ---
    write_pidfile(pidfile, live_pid)
    write_meta(pidfile, live_pid, repo_root)  # old shape, no state key
    meta, state, _ = shared.read_worker_meta_state(str(pidfile) + ".meta")
    check("D5 old-shape meta reads ok", state == "ok" and meta is not None, str(state))
    check("D5 old-shape meta classifies as serving",
          meta is not None and shared.read_worker_meta_state(
              str(pidfile) + ".meta")[0].get("state", "serving") == "serving",
          "state=%r" % (meta or {}).get("state"))

    # --- D2 old-shape live owner still refused (today's behavior preserved) ---
    reason = worker.guard_single_worker(str(pidfile), replace=False)
    check("D2 live serving owner refused", isinstance(reason, str) and str(live_pid) in reason,
          "refusal=%r" % reason)

    # --- D1 draining owner does not block takeover; takeover is named ---
    write_meta(pidfile, live_pid, repo_root, state="draining")
    captured = []
    handler = logging.Handler()
    handler.emit = lambda rec: captured.append(rec.getMessage())
    log = logging.getLogger()
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.INFO)
    try:
        reason = worker.guard_single_worker(str(pidfile), replace=False)
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
    check("D1 draining owner admits replacement", reason is None, "refusal=%r" % reason)
    check("D1 takeover is named in the log",
          any("drain" in m.lower() for m in captured),
          "log lines=%d" % len(captured))

    # --- D3 pid mismatch: conservative refusal, mismatch named ---
    write_meta(pidfile, 999999999, repo_root, state="draining")  # meta.pid != pidfile pid
    reason = worker.guard_single_worker(str(pidfile), replace=False)
    check("D3 draining meta with foreign pid refused",
          isinstance(reason, str), "refusal=%r" % reason)

    # --- D4 malformed meta: fail-conservative refusal, no crash ---
    write_pidfile(pidfile, live_pid)
    write_meta(pidfile, live_pid, repo_root, raw="{not json")
    try:
        reason = worker.guard_single_worker(str(pidfile), replace=False)
        check("D4 malformed meta refused without crash", isinstance(reason, str),
              "refusal=%r" % reason)
    except Exception as e:  # noqa: BLE001
        check("D4 malformed meta refused without crash", False,
              "raised %s: %s" % (type(e).__name__, e))

    summary()


if __name__ == "__main__":
    main()
