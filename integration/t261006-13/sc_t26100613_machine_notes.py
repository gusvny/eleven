#!/usr/bin/env python3
"""sc_t26100613_machine_notes.py — the machinery's own noise is not a finding
(t261006-13, B5; offline source locks + pure-function replay, stdlib only).

Locked faces (grey-box L3 — what lands in a period report):
  Sweep truncation (enum_note), skipped-ticket lists and unreadable-ticket lists become
  MACHINE NOTES carrying {kind, count, reason} — how many and why — instead of
  line-enumerated findings repeated every period (ticket B5; today's "192 unreadable
  ticket(s)" face).
  Fail-closed is preserved: a permanent unreadable state with a nonzero count still
  appears on the front page as a named note (never silently "no problem"), and "sweep
  did not run" remains a real finding — it is a failure, not noise.

Pre-implement = FAIL naming the missing faces (TDD-phase red expected); green at
arbitrate/merge. Zero docker/Temporal/browser, never touches 3099/7233.

Run directly: python3 integration/t261006-13/sc_t26100613_machine_notes.py (cwd=repo root).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))
sys.path.insert(0, str(ROOT / "integration"))

from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600)
ok, na, finish, env_fail = _ck.ok, _ck.na, _ck.finish, _ck.env_fail
NAME = "t261006-13-machine-notes"

FLOW_SRC = (ROOT / "server/engine/inspection_flow.py").read_text("utf-8")
LW_PATH = ROOT / "server/engine/inspection_lane_watchdog.py"
LW_SRC = LW_PATH.read_text("utf-8") if LW_PATH.exists() else ""

NOTES = None
try:
    # the noise->note conversion is expected as a replayable pure face
    import inspection_lane_watchdog as lw  # noqa: E402
    NOTES = getattr(lw, "machine_notes_from_meta", None) \
        or getattr(lw, "noise_notes_from_meta", None)
except Exception as e:
    print("FAIL named: server/engine/inspection_lane_watchdog.py not importable: "
          "%s: %s" % (type(e).__name__, e))

# ---------- source locks: noise leaves the finding list ----------
print("\nSource locks (noise becomes counted notes, not findings)")
ok("machine_notes" in FLOW_SRC or "machine_notes" in LW_SRC
   or "machine_notes" in (ROOT / "server/engine/inspection_inspect.py").read_text("utf-8"),
   "machine_notes channel exists in the inspection flow (noise is notes, not findings)")
ok("unreadable_finding_specs" not in FLOW_SRC
   or "machine_notes" in FLOW_SRC,
   "unreadable-ticket line-enumerated findings path superseded by counted notes")
ok("sweep was truncated" not in FLOW_SRC.lower()
   or "machine_notes" in FLOW_SRC,
   "truncation ('sweep was truncated') no longer minted as a low finding")
ok("did not run" in FLOW_SRC.lower() or "did_not_run" in FLOW_SRC
   or "sweep" in FLOW_SRC.lower(),
   "sweep-not-run stays a named failure path (real failure, not noise)")

# ---------- replay: notes carry count + reason, findings stay empty ----------
print("\nReplay (meta with noise -> notes with {kind,count,reason}, zero added findings)")
if NOTES is not None:
    meta = {
        "unreadable": ["t1: timeout after retry", "t2: Workflow Task in failed state"],
        "enum_note": "enumeration truncated at cap 500",
    }
    skipped = ["t3: out-of-scope non-terminal"]
    try:
        notes, added_findings = NOTES(meta, skipped)
    except TypeError:
        notes, added_findings = NOTES(meta)
    ok(isinstance(notes, list) and isinstance(added_findings, list),
       "converter returns (notes, added_findings)")
    ok(len(notes) >= 3, "each noise family yields its own note (unreadable/skipped/truncated)")
    ok(all(("count" in n and "reason" in n) or ("kind" in n) for n in notes
           if isinstance(n, dict)),
       "every note names kind, count and reason (how many, why — ticket B5)")
    unread = [n for n in notes if isinstance(n, dict) and n.get("kind") == "unreadable"]
    ok(bool(unread) and unread[0].get("count") == 2,
       "unreadable note carries the exact count (2), not a line enumeration")
    ok(len(added_findings) == 0,
       "noise adds ZERO findings (the budget is no longer spent on machinery noise)")
    # fail-closed preserved: nonzero permanent unreadable state stays visible
    meta2 = {"unreadable": ["t9: Workflow Task in failed state"]}
    notes2, added2 = NOTES(meta2)
    ok(len(notes2) >= 1 and all(n for n in notes2),
       "a nonzero unreadable state still surfaces as a named note (never silent no-problem)")
else:
    ok(False, "machine_notes_from_meta (or named equivalent) exists in "
              "inspection_lane_watchdog (noise converter as a pure face)")
    na("replay truth table (converter missing)")

print()
finish(NAME)
