#!/usr/bin/env python3
"""sc_t26101205_fix_pins.py — t261012-05 的自有锚场景（ticket-own scenario, ro pool）.

Why this entry exists (rework ruling 261016): the narrowed develop-buffer lane
gate proves a ticket through its OWN scenarios union the declared fast set. This
ticket touched only integration test assets, all living in pools the ticket's own
declaration skips (engine/exclusive), so its gate face was a ZERO-RUN round —
correctly flagged as information-free by the stall detector. This entry gives the
lane gate something of its own to run: the case-level assertions of the FIX-group
repairs, judged offline in seconds (pure source parsing, zero docker/Temporal/
browser, never touches 3099/7233). It is a guard over the delivered-tree states
this ticket produced, not a duplicate of any repaired scenario's runtime face:

  A1 capture twins: the required-view pins (SEVEN_VIEWS in both baselines) are a
     subset of the live view files declared in server/ui-check/capture.mjs
     (BOARD_VIEWS + the default VIEWS entries) — the exact drift that made both
     red (console-epics / console-new-ticket retired with their icons).
  A2 auto-rework-trace: the product face the case pins holds today — exactly 12
     `self._auto_rework(` sites in dev_lane.py, zero direct
     `self._rework = ReworkRequest(`, exactly one queued
     `self._queue_rework(ReworkRequest(`, and the STAGE_MEMO_HISTORY_CAP integer
     module constant present (the exec-namespace extraction's anchor).
  A3 ticket-session-restore: the S9 URL-aware named-exemption faces are in place
     (the agent-usage ghost-row GHOST exemption and the stage-engine-channel
     STAGE_CHANNEL exemption) — the case judges, never silently degrades.
  A4 inspect-contract: the id-width assertion is 16 with a hex charset check in
     the case, and the product mint face FINDING_ID_HEX == 16 in
     inspection_inspect.py — the three-side agreement the merged pin anchors.
  A5 pw-path-resolution: every CONSUMERS entry in the guard file exists on disk —
     the retirement-sweep discipline face (three deleted entries caused its red).
  A6 own-set is runnable: the five self-judging ro scenarios this ticket repaired
     (no-skip-guard, inspect-contract, terminology-l7, l10-launch-gate,
     multitab-guard) are registered with pool "ro", so the narrowed gate's own
     set for this ticket is non-empty by construction.
  A7 ENV group supply seam: each of the ten ENVIRONMENT-group cases resolves its
     console through integration/lib_stage_console.mjs (imports ensureStageConsole
     or lib_browser), and that lib emits the documented stdout contract token
     (`ENV_FAIL: docker daemon unreachable ...`) — the fail-loud conversion face.

Malformed / drifted inputs degrade loudly: a missing file or a missing anchor is
a named FAIL, never a silent pass (guard self-proof discipline). Zero network,
zero ports, zero 3099. Real-time waits: none.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))  # integration/t261012-05 -> repo root

_PASSES: list[str] = []
_FAILS: list[str] = []


def ok(cond: bool, msg: str) -> None:
    if cond:
        _PASSES.append(msg)
        print("  ok %s" % msg)
    else:
        _FAILS.append(msg)
        print("  FAIL %s" % msg)


def read(rel: str) -> str:
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


# ---------- A1 capture twins: required views ⊆ live product views ----------

CAPTURE = "server/ui-check/capture.mjs"
E2E = "integration/baselines/sc_capture_chat_e2e.mjs"
ACTIVE = "integration/baselines/sc_capture_chat_active.mjs"

# Live view files: every view name capture.mjs actually produces. Three
# declaration forms exist (t261012-05 acceptance fix, gen10): the `{ file: "..." }`
# object entries (BOARD_VIEWS + the default VIEWS list + fixture-only entries),
# the dedicated constant assignments (`const REFRESH_SHOT = "console-refresh.png"`)
# and the dedicated shoot calls (`await shoot("console-chat.png")`) — the chat
# and refresh views have no `file:` object entry, so a file:-only extraction
# false-flagged them as stale even though the gate produces all seven views.
# Comment text is stripped first: capture.mjs's retirement note mentions the
# retired view names, and comments are not declarations (the subset direction
# only widens, so a missed form hides a stale pin — the three forms above are
# the exhaustive declaration surface, verified against the live file).
cap = re.sub(r"//[^\n]*", "", read(CAPTURE))
live_views = set(re.findall(r'\bfile:\s*"([^"]+\.png)"', cap))
live_views |= set(re.findall(r'\bshoot\(\s*"([^"]+\.png)"', cap))
live_views |= set(re.findall(r'=\s*"([^"]+\.png)"', cap))
ok(len(live_views) >= 7, "A1 capture.mjs declares >=7 view files (got %d)" % len(live_views))
for rel in (E2E, ACTIVE):
    src = read(rel)
    m = re.search(r"SEVEN_VIEWS = \[(.*?)\]", src, re.S)
    ok(m is not None, "A1 %s carries the SEVEN_VIEWS pin" % os.path.basename(rel))
    if m:
        pinned = set(re.findall(r'"([^"]+\.png)"', m.group(1)))
        ok(len(pinned) == 7, "A1 %s pins exactly 7 views (got %d)" % (os.path.basename(rel), len(pinned)))
        stale = sorted(pinned - live_views)
        ok(not stale, "A1 %s required views all exist in capture.mjs (stale: %s)"
           % (os.path.basename(rel), stale or "none"))

# ---------- A2 auto-rework-trace: the pinned product face holds ----------

DEV_LANE = "server/engine/dev_lane.py"
dl = read(DEV_LANE)
n_sites = len(re.findall(r"self\._auto_rework\(", dl))
# t261019-24 arbitration (261019): main's declaration-driven merge_check self-heal
# batch (ea3def75 + b3d8e5e4) added the 13th legitimate self._auto_rework site
# (mechanical self-heal for a stale DECLARED build output + the generic
# declaration-driven remedy). Count pin 12 -> 13; the next new site must be
# named here again.
# t261019-25 arbitrate gen2: 12 -> 13 — main b3d8e5e4 (261019 merge_check
# self-healing, merged at f787cc8) added the declaration-driven remediable-red
# _auto_rework call site; same bump convention as the t261009-17 bump.
# (conflict resolution: both sides pinned the SAME value 13 — both provenances kept.)
# t261020 (integration): 13 -> 14 — the line-landing conflict rewind merged at
# dcf05f27 added one _auto_rework call site (a conflicted develop-buffer landing
# re-merges through the gate that re-syncs the line, bounded and patch-guarded).
# Same bump convention as the t261009-17 and t261019-25 bumps.
ok(n_sites == 14, "A2 dev_lane.py has exactly 14 _auto_rework call sites (got %d)" % n_sites)
ok(not re.search(r"self\._rework = ReworkRequest\(", dl),
   "A2 dev_lane.py has zero direct ReworkRequest assignments (t261009-47/KI-212 queue shape)")
ok(len(re.findall(r"self\._queue_rework\(\s*ReworkRequest\(", dl)) == 1,
   "A2 dev_lane.py has exactly one queued ReworkRequest construction (merge human-gate reject)")
ok(re.search(r"^STAGE_MEMO_HISTORY_CAP\s*=\s*\d+", dl, re.M) is not None,
   "A2 STAGE_MEMO_HISTORY_CAP integer constant present (exec-namespace extraction anchor)")

# ---------- A3 ticket-session-restore: named-exemption faces in place ----------

sr = read("integration/baselines/sc_ticket_session_restore.mjs")
ok("GHOST" in sr and "agent-usage" in sr,
   "A3 S9 keeps the named agent-usage ghost-row exemption")
ok("STAGE_CHANNEL" in sr and "/api/wf/concurrency" in sr,
   "A3 S9 keeps the named stage-engine-channel exemption (concurrency/sessions)")

# ---------- A4 inspect-contract: 16-hex pin three-side agreement ----------

ic = read("integration/t260916-22/sc_inspection_inspect_contract.py")
ok(re.search(r'len\(i\) == 16 and all\(c in "0123456789abcdef"', ic) is not None,
   "A4 case asserts id == 16 hex chars (t261009-69 widening, merged pin)")
ii = read("server/engine/inspection_inspect.py")
m_hex = re.search(r'FINDING_ID_HEX\s*=\s*(\d+)', ii)
ok(m_hex is not None and m_hex.group(1) == "16",
   "A4 product mint face FINDING_ID_HEX == 16 (got %s)" % (m_hex.group(1) if m_hex else "absent"))

# ---------- A5 pw-path-resolution: consumer list sweep discipline ----------

pw = read("integration/t260912-01/sc_t260912_01_pw_path_resolution.mjs")
m_consumers = re.search(r"const CONSUMERS = \[(.*?)\]", pw, re.S)
ok(m_consumers is not None, "A5 CONSUMERS list present in the guard file")
if m_consumers:
    consumers = re.findall(r'"([^"]+\.mjs)"', m_consumers.group(1))
    missing = [c for c in consumers if not os.path.isfile(os.path.join(REPO, "integration", c))]
    ok(bool(consumers) and not missing,
       "A5 every CONSUMERS file exists on disk (%d entries; missing: %s)"
       % (len(consumers), missing or "none"))
    ok(all("t260903-07" not in c and "t260904-07" not in c and "t260905-09" not in c
           for c in consumers),
       "A5 the 261002-retired scenario files stay out of the list (sweep landed)")

# ---------- A6 the ticket's own runnable set is non-empty (ro pool) ----------

reg = read("integration/run_scenarios.py")
own_ro = [
    "t260904-12-no-skip-guard",  # the SKIP-semantics guard entry this ticket repaired
    "t260916-22-inspect-contract",
    "t260920-03-terminology-l7-gate",
    "t260929-09-l10-launch-gate-mechanism",
    "t260905-05-multitab-guard-assets",
]
for name in own_ro:
    m_entry = re.search(r'\("%s",.*?"(ro)",' % re.escape(name), reg, re.S)
    ok(m_entry is not None, "A6 %s registered in the ro pool (narrowed-gate runnable)" % name)

# ---------- A7 ENV group: supply seam + fail-loud contract token ----------

ENV_CASES = [
    "integration/t260901-13/sc_evidence_lightbox_dom.mjs",
    "integration/t260915-05/sc_ticket_detail_lane_map_dom.mjs",
    "integration/t260926-05/sc_inspection_report_ui_dom.mjs",
    "integration/t260916-04/sc_ticket_detail_lane_map_everblocked_dom.mjs",
    "integration/t260904-06/sc_spec_card_dom.mjs",
    "integration/t260925-18/sc_ui_english_spec_markdown.mjs",
    "integration/t260916-05/sc_inspection_detail_lane_map_dom.mjs",
    "integration/t260905-05/sc_modal_dialog_semantics.mjs",
    "integration/t260911-05/sc_ki048_status_card_dom.mjs",
    "integration/t260904-05/sc_ledger_adversarial_boot.mjs",
]
for rel in ENV_CASES:
    src = read(rel)
    seam = ("ensureStageConsole" in src) or ("lib_browser" in src)
    ok(seam, "A7 %s resolves its console through the shared supply seam"
       % os.path.basename(rel))

lsc = read("integration/lib_stage_console.mjs")
ok("ENV_FAIL: docker daemon unreachable" in lsc,
   "A7 console supply emits the documented stdout ENV_FAIL contract token")
ok("SANDBAR_TEST_CONSOLE=http://" in lsc,
   "A7 console supply ENV_FAIL names how to provide the asset (SANDBAR_TEST_CONSOLE)")

# ---------- summary ----------

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (len(_PASSES), len(_FAILS)))
sys.exit(1 if _FAILS else 0)
