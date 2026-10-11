#!/usr/bin/env python3
"""t261011-17 — a green-run face miss is visible on the ticket face, not only in
the worker log (grey-box L3, offline seconds, zero docker/Temporal/browser,
never touches 3099).

User need (ticket t261011-17 item 3): when the green-run face is not recorded
the miss was swallowed into one log line — a steward on duty had to grep the
log to learn a face was supposed to be written. The fix leaves a NAMED note on
the workflow meta (the ticket result face). This scenario judges the reader
side of that contract by driving the real dev_lane green-run recorder
(_ki220_record_green_run) through a stubbed workflow facade:

  A. activity failure — meta carries NO last_green_run face (fail-closed is
     untouched, never a fabricated green) AND carries a named miss note that
     names the green-run face and the failed activity (lane_head_sha);
  B. activity returns ok=false — same: no face, note present (the two failure
     exits are equally observable);
  C. success — the face lands (sha + at) and the miss note is GONE (a
     recovered lane must not carry a stale failure note);
  D. unpatched replay (patch gate closed) — the recorder is inert: no face,
     no note (old in-flight replays must not observe anything).

Intent split: the note's truth-table matrix, malformed-activity-result shapes
and the guard mechanics belong to the developer's L1 tests; this scenario locks
the reader-facing observability contract (note present / cleared / replay-inert)
from outside the unit suite. The develop-buffer landing refusal text and the
shared.green_run_face semantics are out of scope (ticket spec item 4) — the
precondition stays fail-closed and leg A asserts exactly that half.

Engine tree or temporalio unimportable = ENV_FAIL exit 2.
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(ROOT, "server", "engine")
if not os.path.isdir(ENGINE):
    print("ENV_FAIL: engine tree missing: %s" % ENGINE)
    sys.exit(2)
sys.path.insert(0, ENGINE)

try:
    import dev_lane  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: dev_lane unimportable: %s: %s" % (type(e).__name__, e))
    sys.exit(2)

SHA = "b" * 40


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 0)
        self.passed = kw.get("passed", 0)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


class _StubWf:
    """Stubbed workflow facade (same seam the L1 suite pins): patched flag +
    programmed execute_activity result (value, dict, or Exception to raise)."""
    flag = True
    result = {"ok": True, "sha": SHA}

    @staticmethod
    def patched(_pid):
        return _StubWf.flag

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        res = _StubWf.result
        if isinstance(res, Exception):
            raise res
        return res


def _make_wf():
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"worktree": "wt", "branch": "lane/x"}
    wf.ticket_id = "t261011-17"
    wf._log = lambda *a, **k: None
    wf._now_epoch = lambda: 1234
    return wf


def _fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def _note_on_face(meta):
    """Reader view of the ticket face: the note must be findable WITHOUT the
    log — some entry on meta names the green-run face as not recorded."""
    blob = json.dumps(meta, default=str)
    if "green_run" not in blob:
        return None
    if '"last_green_run"' in meta and len(meta) == 1:
        return None
    return blob


def _assert_miss_note(wf, expect_activity_name):
    if "last_green_run" in wf.meta:
        _fail("fail-closed broken: a last_green_run face was minted despite the "
              "lane_head_sha failure (fabricated green)")
    blob = _note_on_face(wf.meta)
    if blob is None:
        _fail("green-run miss is not visible on the ticket face: meta=%s "
              "(a steward must not have to grep the worker log)" % wf.meta)
    if expect_activity_name and expect_activity_name not in blob:
        _fail("miss note does not name the failed activity %s: %s"
              % (expect_activity_name, blob))
    if '"recorded": true' in blob or '"recorded":true' in blob:
        _fail("miss note claims recorded=true: %s" % blob)


def main():
    # Bind the stubbed facade at the module seam (outside a real workflow event
    # loop the temporalio facade refuses to answer `patched`).
    dev_lane.workflow = _StubWf
    # ---- A: activity raises -> no face, named miss note on the face
    _StubWf.flag = True
    _StubWf.result = RuntimeError("Activity task failed")
    wf = _make_wf()
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    _assert_miss_note(wf, "lane_head_sha")
    print("PASS A: activity failure leaves a named miss note on the face, "
          "no fabricated green face")

    # ---- B: activity returns ok=false -> no face, note present
    _StubWf.result = {"ok": False, "sha": "", "error": "rev-parse boom"}
    wf = _make_wf()
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    _assert_miss_note(wf, None)
    print("PASS B: ok=false failure is equally observable on the face")

    # ---- C: success -> face lands, miss note cleared
    _StubWf.result = {"ok": True, "sha": SHA}
    wf = _make_wf()
    wf.meta["green_run_note"] = {"face": "green_run", "recorded": False}
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    face = wf.meta.get("last_green_run")
    if not face or face.get("sha") != SHA or not face.get("at"):
        _fail("success did not record the green-run face: %s" % wf.meta)
    if "green_run_note" in wf.meta:
        _fail("stale miss note outlived a recovered lane: %s" % wf.meta)
    print("PASS C: success records the face and clears the miss note")

    # ---- D: unpatched replay -> inert, nothing observed
    _StubWf.flag = False
    _StubWf.result = RuntimeError("should never be reached")
    wf = _make_wf()
    wf.meta = {}
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), False))
    if wf.meta:
        _fail("unpatched replay is not inert: %s" % wf.meta)
    _StubWf.flag = True
    print("PASS D: unpatched replay stays inert (no face, no note)")

    print("PASS t261011-17-green-run-face-note: green-run miss observable on "
          "the ticket face, fail-closed precondition untouched")
    sys.exit(0)


if __name__ == "__main__":
    main()
