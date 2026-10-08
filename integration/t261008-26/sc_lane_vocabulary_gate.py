#!/usr/bin/env python3
"""sc_lane_vocabulary_gate.py — lane vocabulary gate, both faces (t261008-26, KI-226).

Run directly: python3 integration/t261008-26/sc_lane_vocabulary_gate.py (cwd = repo
root), or through the engine's venv fallback chain (see the SCENARIOS entry).

Grey-box L2/L3, offline seconds, zero docker/Temporal/browser, never touches 3099.
Incident (KI-226, 261008): eight tickets created with lane="land" came back ok:true
with no worktree, no branch, no base_ref — the engine silently degraded the unknown
lane to the main tree, so the tickets ran stage after stage producing nothing and
never going blocked. The fix (t261008-26) is one lane vocabulary, fail-closed on both
faces:

  A  creation side  — derive_lane_workspace refuses any resolved lane outside the
     vocabulary with the offending value named verbatim (the user's ok receipt can no
     longer hide a dead shape); an empty explicit lane keeps falling back to the
     template lane.
  B  workflow side  — lane_workspace_gate_error refuses an unrecognised meta.lane on
     the same vocabulary (hand-written payloads, old payloads, future entry points)
     while every legitimate non-worktree shape it accepts today stays untouched.
  C  hard constraint — ZERO DISTURBANCE: main-lane tickets, dir-workspace tickets and
     no-lane workflows keep their exact today behaviour (negative assertions, not a
     claim); an unrecognised lane must never be "rescued" into a worktree.
  D  single source — both faces judge the SAME declared vocabulary (LANES, exactly
     {main, worktree}); a face that re-invents its own set drifts and must turn red.

Malformed input is judged fail-closed: case and whitespace variants of a legal value
are unknown lanes, not convenience spellings ('Worktree', ' worktree', 'wt', 'land').
Engine module unavailable = ENV_FAIL exit 2. Pre-fix tree = red (TDD signal); green
required at the integration gate / merge.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import shared
except Exception as exc:  # engine module unimportable = environment red, not product red
    print("ENV_FAIL: server/engine shared module unavailable (%s)" % exc)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


derive = shared.derive_lane_workspace
gate = shared.lane_workspace_gate_error

UNKNOWN = ("land", "wt", "dev", "Worktree", " worktree", "main-tree")

# ---------- A. creation side: unknown resolved lane refused, value named ----------
section("A derive_lane_workspace — creation-side vocabulary gate")
for lane in UNKNOWN:
    try:
        derive("t261008-26-x", project_root=None, lane=lane, template_lane="main")
        ok(False, "unknown explicit lane %r refused at creation" % lane)
    except ValueError as e:
        msg = str(e)
        ok(lane in msg, "refusal of %r names the value verbatim" % lane)
    except Exception as e:  # wrong exception type = contract broken
        ok(False, "unknown lane %r raises ValueError (got %s)" % (lane, type(e).__name__))

# review-plan comment 1: the check is unconditional on the RESOLVED lane — a caller
# cannot smuggle an off-vocabulary lane through by matching it in template_lane.
try:
    derive("t261008-26-x", project_root=None, lane="land", template_lane="land")
    ok(False, "explicit lane 'land' matching template_lane 'land' still refused")
except ValueError:
    ok(True, "explicit lane 'land' matching template_lane 'land' still refused")

# spec L1: an EMPTY explicit lane keeps falling back to the template lane.
lane, ws, worktree, branch = derive("t261008-26-x", project_root="/p", lane="",
                                    template_lane="worktree")
ok(lane == "worktree" and bool(worktree) and bool(branch)
   and isinstance(ws, dict) and ws.get("type") == "worktree",
   "empty explicit lane falls back to the worktree template (full lane shape)")
lane, ws, worktree, branch = derive("t261008-26-x", project_root=None, lane="",
                                    template_lane="main")
ok(lane == "main" and ws is None and not worktree and not branch,
   "empty explicit lane falls back to the main template (no worktree rendered)")

# ---------- B. workflow side: same vocabulary, named error ----------
section("B lane_workspace_gate_error — gate learns the vocabulary")
for lane in UNKNOWN:
    msg = gate({"lane": lane})
    ok(bool(msg) and lane in msg,
       "gate returns a named error for unrecognised lane %r" % lane)

# ---------- C. zero disturbance: every legitimate shape passes unchanged ----------
section("C gate negative assertions — legitimate non-worktree tickets untouched")
ok(gate({}) == "", "no-lane workflow (content-studio shape) passes unchanged")
ok(gate({"lane": ""}) == "", "explicitly empty lane passes unchanged")
ok(gate({"lane": "main"}) == "", "main-lane ticket passes unchanged")
ok(gate({"lane": "main",
         "workspace": {"type": "dir", "path": "/p/.ticket-ws/t261008-26-x"}}) == "",
   "main lane + dir-workspace ticket passes unchanged")
FULL_WT = {"lane": "worktree",
           "workspace": {"type": "worktree", "path": "/p/.lane/t261008-26-x"},
           "worktree": "/p/.lane/t261008-26-x",
           "branch": "lane/t261008-26-x"}
ok(gate(dict(FULL_WT)) == "", "full worktree-lane shape passes unchanged")
ok(gate({"lane": "worktree",
         "workspace": {"type": "worktree", "path": "/p/.lane/x",
                       "repo_worktrees": [{"repo": "", "name": "r", "branch": "lane/r"}]},
         "worktree": "/p/.lane/x", "branch": "lane/x"}) == "",
   "multi-repo worktree shape passes unchanged")

section("C2 existing shape checks still fire (none removed by the vocabulary change)")
ok(bool(gate({"lane": "worktree"})),
   "worktree lane with no workspace still refused")
ok(bool(gate({"lane": "worktree",
              "workspace": {"type": "worktree", "path": "/p/.lane/x"},
              "worktree": "", "branch": "lane/x"})),
   "worktree lane with EMPTY worktree still refused (the hidden-shape receipt face)")
ok(bool(gate({"lane": "worktree",
              "workspace": {"type": "worktree", "path": "/p/.lane/x"},
              "worktree": "/p/other", "branch": "lane/x"})),
   "worktree != workspace.path still refused")
ok(bool(gate({"lane": "worktree",
              "workspace": {"type": "worktree", "path": "/p/.lane/x"},
              "worktree": "/p/.lane/x", "branch": ""})),
   "worktree lane with empty branch still refused")

# ---------- D. one vocabulary, one source ----------
section("D single-source vocabulary")
lanes = getattr(shared, "LANES", None)
ok(lanes == ("main", "worktree"),
   "declared vocabulary is exactly (main, worktree), actual %r" % (lanes,))
ok(isinstance(getattr(shared, "LANE_MAIN", None), str) and shared.LANE_MAIN == "main",
   "main lane named once as a constant, value 'main'")

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
