#!/usr/bin/env python3
"""t261031-20 — a gate receipt is valid only for the tree it measured.

User need (cross-project report, three tickets in one day): the gate went red,
arbitrate said it changed the criterion, and the flow walked straight into the
merge gate. The signature then rested on a failed receipt that described a tree
the lane no longer had. Asking a person to notice that by hand is the defect.

This scenario judges the reader-facing contract from outside the unit suite. It
drives the real dev_lane workflow class behind a stubbed workflow facade (the
same seam the L1 suite uses): offline, in seconds, no Temporal server, no
docker, no console.

  A. the reported shape: the receipt measured tree A, a later stage committed,
     the lane head is B. At the merge door the guard must void the receipt and
     send the flow back to the gate. It must not report a verified receipt, and
     its reader text must name both trees and the last stage entered, and must
     not claim who committed.
  B. the 261009 control: a MAIN-SYNC delta (A -> B) never voids. The guard
     proceeds, the text names both trees, and the merge face names the tree the
     merge will land. Other people's merges must not stall a lane.
  C. an unresolvable head probe is never fresh: a failed probe and a raising
     probe each stop the lane with the unprovable copy that names the
     head-resolution failure and both exits; nothing escapes the guard.
  D. a missing or malformed anchor is never fresh: no anchor, an empty sha, a
     None sha and a non-dict anchor each refuse the fresh verdict, and a second
     miss stops (the no-receipt bound is one round).
  E. the void bound is reachable and a new anchor does not reset it: three stale
     evaluations separated by new anchors end in a named stop that gives both
     exits; a human retry_qc opens one more round (the reset must not sit behind
     the old conflict-counter gate, which is closed on an armed pre-anchor lane).
  F. the arming rule: armed, the recorder issues exactly one head probe, mints
     the anchor with the measured sha and the surface, and clears a stale miss
     note on recovery; a failed probe leaves a named note and no anchor. The
     source lock requires the patch id, the arming signal, the arming predicate
     and an arming check above every declared command site — the half-armed
     defect this family measured.

Binding note (shallow on purpose): the assertions use the interface the ticket
fixes — the anchor key `receipt_sha`/`surface`, the `merge_face` reader face,
the guard's fresh/void outcomes, the arming predicate and the signal. They do
not read private counters or return-value internals; a refactor that keeps these
names and this behaviour stays green. A rename is red by design, the same rule
the declared-anchor siblings use.

Intent split (no intent-level duplication): the pure function's state table per
input shape and the main-loop journey belong to the developer L1 battery; this
entry asserts the GUARD's reaction at the seam (never fresh, never raises, the
bound, the stop copy) and the arming rule;
t261011-17-green-run-face-note owns the green-only `last_green_run` face and its
miss note; t261005-14 / t261005-15 / t261006-19 own the concurrency and
conflict-counter replay families. THIS entry uniquely owns the receipt-to-tree
identity at the merge door plus the arming rule over its command sites. A real
Temporal full lane journey stays in the engine pool / verification stage.

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no other outcome).
"""
import asyncio
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

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40
SHA_E = "e" * 40
SURFACE = "full suite"
VOID_COPY = "cannot tie the gate receipt to the merged tree"

_FAILS = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           ("  -- " + str(detail)[:400]) if (detail and not cond) else ""))
    if not cond:
        _FAILS.append(name)


class _Stop(Exception):
    """Raised by the stubbed blocked entry: the lane stopped, the drive ends."""


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 12)
        self.passed = kw.get("passed", 12)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


class _StubWf:
    """The workflow facade seam: patched answers per patch id, execute_activity
    records the command name and answers a programmed result (value or raise)."""

    flags = {}
    head = {"ok": True, "sha": SHA_A}
    commands = []

    @staticmethod
    def patched(pid):
        return bool(_StubWf.flags.get(str(pid), False))

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        _StubWf.commands.append(getattr(name, "name", getattr(name, "__name__", str(name))))
        if isinstance(_StubWf.head, Exception):
            raise _StubWf.head
        return _StubWf.head

    @staticmethod
    def now():
        return 0.0

    @staticmethod
    def info():
        raise RuntimeError("no workflow info off the event loop")

    @staticmethod
    async def wait_condition(_fn):
        raise _Stop("wait_condition")


def reset_stub(head=None, patched=()):
    _StubWf.commands = []
    _StubWf.flags = {pid: True for pid in patched}
    _StubWf.head = head if head is not None else {"ok": True, "sha": SHA_A}


def make_shell(*, anchor_sha=None, anchor_raw=None, deltas=None, arm=False,
               stage="acceptance"):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = "t261031-20"
    wf.meta = {"worktree": "wt", "branch": "lane/t261031-20", "stage": stage}
    if anchor_raw is not None:
        wf.meta["gate_receipt"] = anchor_raw
    elif anchor_sha is not None:
        wf.meta["gate_receipt"] = {"receipt_sha": anchor_sha, "receipt_at": 1000,
                                   "surface": SURFACE, "deltas": list(deltas or [])}
    wf.timeline = []
    wf.results = {}
    wf.refused = []
    wf._receipt_void_rounds = 0
    wf._gate_receipt_guard_enabled = bool(arm)
    wf._retry_token = 0
    wf._rework = None
    wf.lines = []      # handoff + log text (the reader side)
    wf.stops = []      # blocked reasons
    wf._log = lambda msg="", *a, **k: wf.lines.append(str(msg))
    wf._handoff = lambda step_id="", summary="", artifacts=None, report="": \
        wf.lines.append(str(summary))
    wf._touch = lambda: None
    wf._enter = lambda *a, **k: None
    wf._finish = lambda *a, **k: None
    wf._mark = lambda *a, **k: None
    wf._gen = lambda *a, **k: 1
    wf._now_iso = lambda: "2026-10-31T00:00:00Z"
    wf._now_epoch = lambda: 1000

    async def _blocked(step_id="", why=""):
        wf.stops.append(str(why))
        raise _Stop(str(why))

    wf._blocked = _blocked
    return wf


def text_of(wf):
    return "\n".join(wf.lines)


def drive(wf, entry, *args, **kwargs):
    """Run one async entry on the shell. Returns (ok, error-or-None); a blocked
    stop is an expected end, not an error."""
    fn = getattr(wf, entry, None)
    if fn is None:
        return False, "no %s on the lane class (declared interface missing)" % entry
    try:
        asyncio.run(fn(*args, **kwargs))
        return True, None
    except _Stop:
        return True, None
    except Exception as e:  # noqa: BLE001 - reported as a check failure, never a crash
        return False, "%s: %s" % (type(e).__name__, e)


def merge_face(wf):
    rec = wf.meta.get("gate_receipt")
    if not isinstance(rec, dict):
        return {}
    got = rec.get("merge_face")
    return got if isinstance(got, dict) else {}


def verified(wf):
    return "verified" in text_of(wf).lower()


def refused_fresh(wf):
    """Never read as fresh: a void was recorded, or the lane stopped."""
    rec = wf.meta.get("gate_receipt")
    void_rec = bool(isinstance(rec, dict) and (rec.get("merge_face") or {}).get("void"))
    void_rec = void_rec or bool(wf.meta.get("gate_receipt_void"))
    return (not verified(wf)) and (void_rec or bool(wf.stops))


def section_a():
    print("\n== A. the reported shape: a stale receipt must not reach the merge")
    reset_stub(head={"ok": True, "sha": SHA_B},
               patched=[dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID])
    wf = make_shell(anchor_sha=SHA_A)
    ok, err = drive(wf, "_gate_receipt_guard")
    check("A1 the guard runs without raising (got %s)" % err, ok)
    check("A2 the stale receipt is refused and the lane stops or re-runs the gate",
          refused_fresh(wf), text_of(wf) + " | stops=" + repr(wf.stops))
    check("A3 no verified receipt is reported at the merge door", not verified(wf),
          text_of(wf))
    line = text_of(wf)
    check("A4 the reader text names the measured tree (A)", SHA_A[:12] in line, line)
    check("A5 the reader text names the tree the lane is on now (B)",
          SHA_B[:12] in line, line)
    check("A6 the reader text names the last stage it entered", "acceptance" in line, line)
    check("A7 the reader text claims no committer", "committed" not in line.lower(), line)


def section_b():
    print("\n== B. the 261009 control: a main-sync delta never voids")
    reset_stub(head={"ok": True, "sha": SHA_B},
               patched=[dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID])
    deltas = [{"from": SHA_A, "to": SHA_B, "cause": "main_sync", "at": 1001}]
    wf = make_shell(anchor_sha=SHA_A, deltas=deltas)
    ok, err = drive(wf, "_gate_receipt_guard")
    check("B1 the guard runs without raising (got %s)" % err, ok)
    check("B2 no void and no stop for a main-sync move",
          not wf.stops and not merge_face(wf).get("void"),
          text_of(wf) + " | stops=" + repr(wf.stops))
    check("B3 the receipt is reported verified", verified(wf), text_of(wf))
    check("B4 the text names both trees", SHA_A[:12] in text_of(wf)
          and SHA_B[:12] in text_of(wf), text_of(wf))
    face = merge_face(wf)
    land = str(face.get("land_sha") or "")
    check("B5 the merge face names the tree the merge will land",
          land.startswith(SHA_B[:12]), face)


def section_c():
    print("\n== C. an unresolvable head probe is never fresh")
    for label, head in (("failed probe", {"ok": False, "sha": "", "error": "rev-parse boom"}),
                        ("raising probe", RuntimeError("probe exploded"))):
        reset_stub(head=head, patched=[dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID])
        wf = make_shell(anchor_sha=SHA_A)
        ok, err = drive(wf, "_gate_receipt_guard")
        check("C %s: the guard does not raise out of it (got %s)" % (label, err), ok)
        check("C %s: the lane stops instead of merging" % label, bool(wf.stops),
              text_of(wf) + " | " + repr(wf.stops))
        stop = "\n".join(wf.stops).lower()
        check("C %s: the stop uses the unprovable copy (names the head failure)" % label,
              VOID_COPY in stop, stop)
        check("C %s: the stop names both exits (rework and retry_qc)" % label,
              "rework" in stop and "retry_qc" in stop, stop)
        check("C %s: no verified receipt is reported" % label, not verified(wf), text_of(wf))


def section_d():
    print("\n== D. a missing or malformed anchor is never fresh")
    cases = [
        ("no anchor at all", {}, False),
        ("empty sha", {"receipt_sha": "", "surface": SURFACE, "deltas": []}, False),
        ("None sha", {"receipt_sha": None, "surface": SURFACE, "deltas": []}, False),
        ("non-dict anchor", "junk", True),
    ]
    for label, anchor, raw in cases:
        reset_stub(head={"ok": True, "sha": SHA_A},
                   patched=[dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID])
        wf = make_shell(anchor_raw=anchor if raw else None) if raw \
            else make_shell(anchor_raw=anchor)
        ok, err = drive(wf, "_gate_receipt_guard")
        check("D %s: the guard does not raise (got %s)" % (label, err), ok)
        check("D %s: no verified receipt is reported" % label, not verified(wf), text_of(wf))
        check("D %s: the lane re-runs the gate or stops, never merges" % label,
              refused_fresh(wf), text_of(wf) + " | stops=" + repr(wf.stops))

    # The no-receipt bound is ONE round: the second miss stops.
    reset_stub(head={"ok": True, "sha": SHA_A},
               patched=[dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID])
    wf = make_shell(anchor_raw={})
    drive(wf, "_gate_receipt_guard")
    first_round_ok = not wf.stops
    drive(wf, "_gate_receipt_guard")
    check("D5 the no-receipt bound is one round: a second miss stops",
          first_round_ok and bool(wf.stops),
          "first_round_no_stop=%r stops=%r" % (first_round_ok, wf.stops))


def section_e():
    print("\n== E. the void bound is reachable; a new anchor does not reset it")
    patched = [dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID]
    reset_stub(head={"ok": True, "sha": SHA_B}, patched=patched)
    wf = make_shell(anchor_sha=SHA_A)
    drive(wf, "_gate_receipt_guard")
    check("E1 void 1: the lane re-runs the gate (no stop yet)", not wf.stops,
          repr(wf.stops))
    # The gate round mints a new anchor; the bound must survive it.
    wf.meta["gate_receipt"]["receipt_sha"] = SHA_B
    _StubWf.head = {"ok": True, "sha": SHA_C}
    drive(wf, "_gate_receipt_guard")
    check("E2 void 2 counts even after a new anchor (no reset, no stop yet)",
          not wf.stops, repr(wf.stops))
    wf.meta["gate_receipt"]["receipt_sha"] = SHA_C
    _StubWf.head = {"ok": True, "sha": SHA_D}
    drive(wf, "_gate_receipt_guard")
    check("E3 the third stale evaluation stops instead of spending another round",
          bool(wf.stops), text_of(wf))
    stop = "\n".join(wf.stops)
    check("E4 the stop names both exits (rework and retry_qc)",
          "rework" in stop and "retry_qc" in stop, stop)
    # A human retry opens one more round. This only holds if the counter reset
    # is NOT behind the old conflict-counter gate: an armed pre-anchor lane has
    # that gate closed (no marker, start time before the anchor).
    wf.retry_qc(who="host")
    wf.meta["gate_receipt"]["receipt_sha"] = SHA_D
    _StubWf.head = {"ok": True, "sha": SHA_E}
    wf.stops = []
    drive(wf, "_gate_receipt_guard")
    check("E5 a human retry_qc opens one more round (void, no immediate re-stop)",
          not wf.stops, repr(wf.stops))


def section_f():
    print("\n== F. the arming rule and the anchor recorder")
    # F1: armed recorder mints the anchor with one head probe.
    reset_stub(head={"ok": True, "sha": SHA_A})
    wf = make_shell(arm=True)
    ok, err = drive(wf, "_record_gate_receipt_anchor", _Receipt(),
                    closing=False, surface=SURFACE)
    check("F1 armed: the recorder does not raise (got %s)" % err, ok)
    check("F2 armed: the recorder issues exactly one head probe",
          _StubWf.commands == ["lane_head_sha"], list(_StubWf.commands))
    rec = wf.meta.get("gate_receipt") or {}
    check("F3 armed: the anchor carries the measured head", rec.get("receipt_sha") == SHA_A,
          rec)
    check("F4 armed: the anchor names the surface it ran on", rec.get("surface") == SURFACE,
          rec)

    # F5: a failed probe leaves a named note, no anchor; a later success clears it.
    reset_stub(head={"ok": False, "sha": "", "error": "rev-parse boom"})
    wf = make_shell(arm=True)
    ok, err = drive(wf, "_record_gate_receipt_anchor", _Receipt(),
                    closing=False, surface=SURFACE)
    check("F5 a failed probe does not raise (got %s)" % err, ok)
    check("F6 a failed probe mints no anchor (never a fabricated identity)",
          "gate_receipt" not in wf.meta, wf.meta.get("gate_receipt"))
    note = wf.meta.get("gate_receipt_note") or {}
    check("F7 the miss is named on the face with the resolver error",
          note.get("recorded") is False and "rev-parse boom" in str(note.get("error")),
          note)
    reset_stub(head={"ok": True, "sha": SHA_A})
    drive(wf, "_record_gate_receipt_anchor", _Receipt(), closing=False, surface=SURFACE)
    check("F8 a later success clears the stale miss note",
          "gate_receipt_note" not in wf.meta and
          (wf.meta.get("gate_receipt") or {}).get("receipt_sha") == SHA_A, wf.meta)

    # F9: armed guard verifies a matching anchor.
    reset_stub(head={"ok": True, "sha": SHA_A})
    wf = make_shell(anchor_sha=SHA_A, arm=True)
    ok, err = drive(wf, "_gate_receipt_guard")
    check("F9 armed: the guard verifies the fresh anchor (got %s)" % err, ok)
    check("F10 armed: a verified line is reported", verified(wf), text_of(wf))
    check("F11 armed: no stop and no void for a matching anchor",
          not wf.stops and not merge_face(wf).get("void"), text_of(wf))

    # F12: the arming predicate is exactly (patch marker OR arm flag).
    class _Shell:
        def __init__(self, flag):
            self._gate_receipt_guard_enabled = flag

    check("F12 the arming predicate reads patch-or-flag",
          hasattr(dev_lane, "_gate_receipt_arm")
          and dev_lane._gate_receipt_arm(_StubWf, _Shell(True)) is True
          and dev_lane._gate_receipt_arm(_StubWf, _Shell(False)) is False,
          getattr(dev_lane, "_gate_receipt_arm", None))

    # F13: source lock — the declared command sites sit behind the arming rule.
    src = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
    check("F13 the patch id constant is present",
          "GATE_RECEIPT_FRESHNESS_PATCH_ID" in src
          and "t261031-20-gate-receipt-freshness-v1" in src)
    check("F14 the arming signal is a declared workflow signal",
          "def enable_gate_receipt_guard" in src)
    for entry in ("_record_gate_receipt_anchor", "_gate_receipt_guard",
                  "_record_merge_line_delta", "_accept_closing_receipt"):
        check("F15 %s is declared" % entry, _function_body(src, entry) is not None)
        unarmed = _unarmed_call_sites(src, entry)
        check("F16 every call site of %s sits behind the arming rule" % entry,
              unarmed == [], unarmed)


def _function_body(src, name):
    """Body text of one method definition, or None when it is not declared."""
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("def %s(" % name) or \
                line.lstrip().startswith("async def %s(" % name):
            indent = len(line) - len(line.lstrip())
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                out.append(nxt)
            return "\n".join(out)
    return None


def _unarmed_call_sites(src, name, window=14):
    """Call sites of `self.<name>(` that carry no arming check in the lines above
    (or the enclosing function body for the new methods)."""
    lines = src.splitlines()
    body = _function_body(src, name) or ""
    bad = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("def %s(" % name) or \
                line.lstrip().startswith("async def %s(" % name):
            continue
        if ("self.%s(" % name) not in line:
            continue
        near = "\n".join(lines[max(0, i - window):i + 1])
        if "_gate_receipt_arm" in near:
            continue
        # A call inside a method that checks the arm itself (an early return)
        # is armed by that method's contract.
        enclosing = _enclosing_function(lines, i)
        if "_gate_receipt_arm" in _function_body(src, enclosing):
            continue
        bad.append("line %d: %s" % (i + 1, line.strip()[:120]))
    return bad


def _enclosing_function(lines, idx):
    for j in range(idx, -1, -1):
        st = lines[j].lstrip()
        if st.startswith("def ") or st.startswith("async def "):
            return st.split("(")[0].replace("def ", "").replace("async ", "").strip()
    return ""


def main():
    saved = sys.modules["dev_lane"].workflow
    dev_lane.workflow = _StubWf
    try:
        section_a()
        section_b()
        section_c()
        section_d()
        section_e()
        section_f()
    finally:
        sys.modules["dev_lane"].workflow = saved

    if _FAILS:
        print("\nFAIL: %d case(s) red:" % len(_FAILS))
        for f in _FAILS:
            print("  - %s" % f)
        sys.exit(1)
    print("\nPASS: t261031-20 gate receipt freshness contract green")
    sys.exit(0)


if __name__ == "__main__":
    if getattr(dev_lane, "GATE_RECEIPT_FRESHNESS_PATCH_ID", None) is None:
        print("FAIL: dev_lane.GATE_RECEIPT_FRESHNESS_PATCH_ID is not declared "
              "(the declared interface this scenario binds to)")
        sys.exit(1)
    main()
