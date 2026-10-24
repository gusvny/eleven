#!/usr/bin/env python3
"""sc_t261021_15_plan_gap_gate.py — t261021-15, the plan-side write-set gap
gate seen from the ticket's own journey, not from the helper's truth table.

Incident (host 261021, measured on t261021-11): six tickets were born with a
write set of only the auto-injected integration/.  create_plan returned
files_changed=[], the union admitted nothing, the write set stayed
['integration/'], and the only reaction was the 260930 non-blocking reminder.
Three implement rounds then reverted every out-of-set edit until the executor
paused the ticket.  The fix under contract: refuse to advance to implement,
on the plan side, when (integration-only initial set) AND (files_changed
empty or absent) AND (no no_file_changes declaration) — a conjunction, so an
empty receipt alone must never rework a ticket (260930 decision).

Grey-box L3 (integration-owned, ticket t261021-15).  Offline seconds, pure
stdlib + real dev_lane/shared modules, zero docker/Temporal-server/browser,
never touches 3099/7233.  The real DevLaneWorkflow._refresh_write_set_after_plan
is driven on a minimal fake self (real dicts, real logs, real refresh) and the
review_plan pass-branch wiring is pinned by source locks; the same technique
as t260904-18's KI-049 seam contract, which this scenario must not duplicate:
that entry owns the receipt-SHAPE seam (malformed/empty never pollutes the
set), THIS entry uniquely owns the gate decision — when an integration-only
ticket with an empty plan receipt is refused instead of reminded, that the
refusal is a NAMED stop (WRITE_SET_PLAN_GAP) naming the three facts and the
lawful ways out, that real-scope tickets keep today's non-blocking reminder,
and that the prose-vs-receipt mismatch is said out loud in the log.

Ticket faces under contract (host 261021 requirements 1–6):
  A the incident conjunction refuses, on the plan side, with a named stop —
    the reason starts with WRITE_SET_PLAN_GAP, names all three facts
    (integration-only set, empty/absent receipt, no declaration) and the one
    lawful way out (rework to create_plan listing every file in files_changed
    — the write set follows the plan — or ask the host to authorize paths);
    a machine-readable gap flag lands on meta for the ticket face.
  B real scope + empty receipt keeps today's behaviour — no refusal, the
    non-blocking reminder stays, the ticket proceeds (260930 intact).
  C each fact missing in turn does not refuse — declaration present, or
    non-empty files_changed, or a set that already carries real scope.
  D absent counts as empty (the old-ticket receipt shape).
  E the plan prose asking for a wider write set while files_changed is empty
    is named explicitly in the log, not hidden behind a bare empty-receipt
    line.
  F the stop reason classifies as a judgement (human-only) stop — the lawful
    outs are rework or host authorization, not an executor lift.
  G replay safety — with the patch gate unpatched, the legacy behaviour is
    byte-for-byte: no gap flag, no refusal, existing reminders untouched.

Intent split (no intent-level duplication): the pure-helper truth tables
(integration-only detection, prose detector, stop-reason text assembly) and
the three-facts-missing L1 matrix belong to developer L1
(server/engine/tests/test_t261021_15_plan_gap_gate.py, delivered with the
implementation); the receipt-shape/malformed seam (a mangled receipt must
never pollute the set) belongs to t260904-18-ki049-write-set-contract; the
effective-write-set record/reader contract belongs to t261009-58; THIS entry
uniquely owns "an integration-only ticket with an empty plan receipt is
stopped on the plan side with a named gate, and nothing else changes".

The delivered gate absent = FAIL named (the pre-implement tree red is the
named TDD signal); green required at the integration gate / merge.
dev_lane/shared unimportable = ENV_FAIL exit 2.

Run: python3 integration/t261021-15/sc_t261021_15_plan_gap_gate.py
(cwd = repository root).
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

PASS = 0
FAILS = []
ENVS = []


def check(name, ok, why=""):
    global PASS
    if ok:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, len(FAILS), len(ENVS)))
    if FAILS:
        print("FAIL t261021-15-plan-gap-gate (%d): %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    if ENVS:
        print("ENV_FAIL t261021-15-plan-gap-gate: %s" % "; ".join(ENVS))
        sys.exit(2)
    print("PASS t261021-15-plan-gap-gate")
    sys.exit(0)


try:
    import dev_lane  # noqa: E402
    import shared  # noqa: E402
except Exception as exc:
    ENVS.append("server/engine modules unimportable: %r" % (exc,))
    summary()

STOP_CODE = "WRITE_SET_PLAN_GAP"
GATE_PATCH_ID = "dev-lane-write-set-plan-gap-v1"

# ---------------------------------------------------------------------------
# Minimal workflow self: real dicts, real logs, fixed clock — no Temporal.
# ---------------------------------------------------------------------------


class FakeLane:
    def __init__(self, write_set, receipt, no_file_changes=False,
                 initial_write_set=None):
        self.meta = {"write_set": list(write_set),
                     "no_file_changes": no_file_changes}
        if initial_write_set is not None:
            self.meta["initial_write_set"] = list(initial_write_set)
        self.results = {"create_plan": receipt}
        self.logs = []

    def _now_epoch(self):
        return 0

    def _now_iso(self):
        return "1970-01-01T00:00:00Z"

    def _log(self, note, status=None):
        self.logs.append(str(note))


def drive(write_set, receipt, no_file_changes=False, initial=None, patched=True):
    fake = FakeLane(write_set, receipt, no_file_changes, initial)
    real_wf = dev_lane.workflow
    # When patched=True every patch is on (today's behaviour, the gate
    # included); when patched=False every patch is off — the old RUNNING
    # instance replays the legacy path byte for byte.
    dev_lane.workflow = types.SimpleNamespace(patched=lambda pid: patched)
    try:
        ret = dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(fake)
    finally:
        dev_lane.workflow = real_wf
    return ret, fake


INCIDENT_RECEIPT = {"files_changed": [], "files_changed_shape": "ok"}
WIDER_PROSE = ("The engine conversion lives under server/ and is flagged "
               "for a widened write set; authorize the paths below.")

# ---------------------------------------------------------------------------
# A — the incident conjunction refuses, plan side, named stop
# ---------------------------------------------------------------------------

ret, fake = drive(["integration/"], INCIDENT_RECEIPT)
check("A1 incident conjunction returns a named gap reason (not None)",
      isinstance(ret, str) and ret.startswith(STOP_CODE + ":"), "ret=%r" % (ret,))
check("A2 gap flag lands on meta for the ticket face",
      isinstance(fake.meta.get("write_set_plan_gap"), dict)
      and STOP_CODE in str(fake.meta.get("write_set_plan_gap")), "meta keys=%r" % list(fake.meta))
check("A3 write set untouched by the refusal (no silent widening)",
      fake.meta.get("write_set") == ["integration/"], "write_set=%r" % fake.meta.get("write_set"))
reason = ret or ""
check("A4 reason names fact 1: the integration-only initial set",
      "integration" in reason, "reason=%r" % reason)
check("A5 reason names fact 2: the empty plan receipt",
      ("empty" in reason.lower()) or ("absent" in reason.lower()), "reason=%r" % reason)
check("A6 reason names fact 3: no no_file_changes declaration",
      "no_file_changes" in reason, "reason=%r" % reason)
check("A7 reason names lawful way out 1: rework to create_plan listing files",
      "create_plan" in reason and "files_changed" in reason, "reason=%r" % reason)
check("A8 reason names lawful way out 2: host authorization",
      "authoriz" in reason.lower(), "reason=%r" % reason)
check("A9 the stop is not the old reminder-only outcome (a refusal beats a remind)",
      any(STOP_CODE in ln or "WRITE_SET_PLAN_GAP" in ln for ln in fake.logs)
      or bool(fake.meta.get("write_set_plan_gap")), "logs=%r" % fake.logs)

# D — absent counts as empty
ret_d, fake_d = drive(["integration/"], {"files_changed_shape": "absent"})
check("D1 files_changed absent + integration-only set refuses too",
      isinstance(ret_d, str) and ret_d.startswith(STOP_CODE + ":"), "ret=%r" % (ret_d,))

# ---------------------------------------------------------------------------
# C — each fact missing in turn does not refuse
# ---------------------------------------------------------------------------

# fact 3 missing: declared no work
ret_c3, fake_c3 = drive(["integration/"], INCIDENT_RECEIPT, no_file_changes=True)
check("C3 no_file_changes declared → no refusal, ticket proceeds",
      ret_c3 is None and not fake_c3.meta.get("write_set_plan_gap"), "ret=%r" % (ret_c3,))

# fact 2 missing: a non-empty receipt widens normally
ret_c2, fake_c2 = drive(["integration/"],
                        {"files_changed": ["server/engine/shared.py"],
                         "files_changed_shape": "ok"})
check("C2 non-empty receipt on integration-only set → union proceeds, no refusal",
      ret_c2 is None
      and fake_c2.meta.get("write_set") == ["integration/", "server/engine/shared.py"],
      "ret=%r write_set=%r" % (ret_c2, fake_c2.meta.get("write_set")))

# fact 1 missing: the set already carries real scope
ret_c1, fake_c1 = drive(["integration/", "server/"], INCIDENT_RECEIPT)
check("C1 real-scope set + empty receipt → no refusal (260930 reminder intact)",
      ret_c1 is None and not fake_c1.meta.get("write_set_plan_gap"), "ret=%r" % (ret_c1,))
check("C1b real-scope empty receipt still leaves the non-blocking reminder in the log",
      any("提醒" in ln for ln in fake_c1.logs), "logs=%r" % fake_c1.logs)

# a ticket that already widened past its initial set is not integration-only
ret_c1w, fake_c1w = drive(["integration/", "server/tools"],
                          INCIDENT_RECEIPT,
                          initial=["integration/"])
check("C1c prior widening gave real scope → a later empty receipt does not refuse",
      ret_c1w is None and not fake_c1w.meta.get("write_set_plan_gap"), "ret=%r" % (ret_c1w,))

# ---------------------------------------------------------------------------
# E — prose says wider write set while files_changed is empty: say it out loud
# ---------------------------------------------------------------------------

_, fake_e = drive(["integration/"], {"files_changed": [], "files_changed_shape": "ok",
                                     "summary": WIDER_PROSE})
check("E1 gap path names the prose-vs-receipt mismatch explicitly",
      any("prose" in ln.lower() and ("wider" in ln.lower() or "widen" in ln.lower())
          for ln in fake_e.logs), "logs=%r" % fake_e.logs)
_, fake_e2 = drive(["integration/", "server/"],
                   {"files_changed": [], "files_changed_shape": "ok",
                    "summary": WIDER_PROSE})
check("E2 real-scope path also names the prose mismatch (not just the empty receipt)",
      any("prose" in ln.lower() for ln in fake_e2.logs), "logs=%r" % fake_e2.logs)
_, fake_e3 = drive(["integration/"],
                   {"files_changed": [], "files_changed_shape": "ok",
                    "summary": "No file changes were needed; the plan is a pure inventory."})
check("E3 no prose signal → no prose claim in the log (报错必须精确)",
      not any("prose" in ln.lower() for ln in fake_e3.logs), "logs=%r" % fake_e3.logs)

# ---------------------------------------------------------------------------
# F — the stop classifies judgement (human-only lift), read from text alone
# ---------------------------------------------------------------------------

tier = None
try:
    tier, _kind = shared.classify_stop_tier(reason)
except Exception as exc:  # noqa: BLE001
    check("F1 classify_stop_tier consumes the gap reason", False, "%s: %s" % (type(exc).__name__, exc))
else:
    check("F1 gap stop classifies judgement (rework/host are human actions)",
          tier == "judgement", "tier=%r" % (tier,))

# ---------------------------------------------------------------------------
# G — replay safety: unpatched gate = legacy behaviour byte for byte
# ---------------------------------------------------------------------------

ret_g, fake_g = drive(["integration/"], INCIDENT_RECEIPT, patched=False)
check("G1 unpatched gate never refuses (old RUNNING instances replay legacy)",
      ret_g is None and not fake_g.meta.get("write_set_plan_gap"), "ret=%r" % (ret_g,))
check("G2 unpatched gate leaves no new meta keys",
      not any("write_set_plan_gap" in k for k in fake_g.meta), "meta keys=%r" % list(fake_g.meta))

# ---------------------------------------------------------------------------
# Source locks — the gate fires on the plan side, never at implement's revert
# (requirement 3; the caller must block instead of advancing)
# ---------------------------------------------------------------------------

DL_SRC = (ENGINE / "dev_lane.py").read_text(encoding="utf-8")
check("S1 the gate is patch-gated (replay safety lives in the source, not the runtime)",
      GATE_PATCH_ID in DL_SRC)
call_at = DL_SRC.find("self._refresh_write_set_after_plan()")
check("S2 the pass branch captures the refresh verdict (not fire-and-forget)",
      call_at != -1
      and DL_SRC[call_at - 40:call_at].strip().endswith("="),
      "caller at %d does not capture the return" % call_at)
check("S3 the pass branch captures the refresh verdict",
      call_at != -1 and "gap" in DL_SRC[call_at:call_at + 1200].lower(),
      "caller region does not mention the gap verdict")
check("S4 the verdict blocks via _blocked on review_plan (named stop on the face)",
      DL_SRC.find("_blocked(\"review_plan\"", call_at) != -1
      or DL_SRC.find("_blocked('review_plan'", call_at) != -1)

summary()
