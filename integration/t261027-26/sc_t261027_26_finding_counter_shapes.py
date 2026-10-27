#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261027_26_finding_counter_shapes.py -- t261027-26 (KI-382), L2 behaviour.

Measured 261027 on t261026-18: the acceptance send-back counter reached 3 -> 4
while the machine gate was green and EVERY send-back report answered all four
acceptance items at the unchanged HEAD - no new finding, only the same sentence
again. The approved fix makes the counter count real findings only: a send-back
whose report names no failed acceptance item is recorded as an observation and
the ticket proceeds.

This entry owns the REPORT SHAPES the field produces and the instruction that
prescribes them - the join that no single-component test can express: the walk
through stage's own brief tells the agent how to name a failed item, and the
engine's detector must read exactly that prescription, must not read a passing
report as a finding (the KI-382 root cause: PASS rows whose evidence text says
fail-closed), and must keep "no finding named" distinguishable from "no report
at all" so an empty receipt can never become an observation that walks a broken
tree to the merge gate.

  A  THE KI-382 FIELD SHAPE IS NOT A FINDING: a markdown table answering four
     acceptance items, every verdict PASS, one evidence cell containing
     "fail-closed", plus the green machine-gate line and the unchanged HEAD -
     no failed item is named, so the detector reports no finding.
  B  A REAL FINDING STILL NAMES ITS ITEM: the same table with item 2 FAIL, an
     English prose line naming item 3, and the Chinese field forms all yield a
     finding that carries the item - the rule never turns the counter off.
  C  AN UNREADABLE RECEIPT IS NOT "NO FINDING": the detector marks absent /
     malformed report text as a malformed basis, not as a clean no-finding
     report, so the engine keeps its stop route (a receipt with no report must
     never be read as an observation).
  D  THE BRIEF AND THE DETECTOR SPEAK ONE VOCABULARY: the walkthrough stage
     brief (the instruction the agent actually receives) names the
     failed_item marker, and the detector reads that marker form - both
     directions, so the instruction cannot drift from the parser.

Intent split (no intent-level duplication): the per-shape unit truth table
(marker/table/prose matrix, 16-item bound, 300 kB bound, None/bytes/dict) and
the engine branch cases (no-finding -> observation -> merge_check, empty receipt
-> stop, environment refusal -> stop, different item each round -> send-back)
belong to developer L1 (server/engine/tests/test_t261027_26_acceptance_cap_lift.py,
T4/T6d-f). THIS entry uniquely owns the KI-382 measured field shape and the
brief-to-detector join.

Grey-box: the REAL detector (shared.acceptance_sendback_finding) and the REAL
stage brief the engine injects (dev_lane.DevLaneWorkflow.FLOW_BRIEF_SET) are
driven; no table internals are asserted. Offline seconds, stdlib + engine
modules, zero docker/Temporal-server/browser, never touches 3099/7233.

Pre-implementation tree: red by name (the named TDD signal - the detector and
the brief clause do not exist yet); green required at the integration gate /
merge. engine modules unimportable = ENV_FAIL exit 2.
"""
import os
import subprocess
import sys

REPO_RC = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
if REPO_RC.returncode != 0 or not REPO_RC.stdout.strip():
    print("ENV_FAIL t261027-26-walkthrough-finding-shapes: repo root unresolved")
    sys.exit(2)
REPO = REPO_RC.stdout.strip()
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, ENGINE)

PASS = 0
FAILS = []
ENVS = []


def check(name, cond, why=""):
    global PASS
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def env_fail(name, why):
    ENVS.append(name)
    print("ENV_FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, len(FAILS), len(ENVS)))
    if FAILS:
        print("FAIL t261027-26-walkthrough-finding-shapes (%d): %s"
              % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    if ENVS:
        print("ENV_FAIL t261027-26-walkthrough-finding-shapes: %s" % "; ".join(ENVS))
        sys.exit(2)
    print("PASS t261027-26-walkthrough-finding-shapes")
    sys.exit(0)


try:
    import shared
except Exception as e:  # noqa: BLE001
    env_fail("engine-modules", "shared.py unimportable: %s: %s" % (type(e).__name__, e))
    summary()

detector = getattr(shared, "acceptance_sendback_finding", None)
if not callable(detector):
    check("A0 the finding detector is on the shared face", False,
          "shared.acceptance_sendback_finding missing - the counter cannot ask "
          "whether the report names a failed item (the approved plan's deliverable 3)")
    summary()

HEAD = "ed0dc444"
GREEN = "machine gate: ran=2 pass=2"

# The measured KI-382 report shape: four acceptance items, every verdict PASS,
# evidence text that legitimately mentions fail-closed, unchanged HEAD.
PASS_TABLE = "\n".join([
    "Acceptance walkthrough at HEAD %s" % HEAD,
    "",
    "| # | acceptance item | verdict | evidence |",
    "|---|---|---|---|",
    "| 1 | ticket face shows the named way out | PASS | blocked text names op=ruling |",
    "| 2 | counter counts real findings | PASS | send-back reports name no item; gate fail-closed otherwise |",
    "| 3 | machine gate green | PASS | ran=2 pass=2 |",
    "| 4 | docs updated | PASS | ops doc section present |",
    "",
    GREEN,
    "HEAD unchanged: %s" % HEAD,
])
FAIL_TABLE = PASS_TABLE.replace(
    "| 2 | counter counts real findings | PASS |",
    "| 2 | counter counts real findings | FAIL |")

# ---------------------------------------------------------------------------
# A - the measured field shape is not a finding
# ---------------------------------------------------------------------------
a = detector("walkthrough complete, all items answered", PASS_TABLE)
check("A1 the KI-382 shape (four PASS items, fail-closed in an evidence cell) "
      "names no failed item",
      isinstance(a, dict) and a.get("named") is False,
      "detector=%r" % (a,))
check("A2 a passing report is not classified as an unreadable receipt",
      isinstance(a, dict) and str(a.get("basis") or "") != "malformed",
      "basis=%r (a readable PASS report must not look like a missing report)"
      % ((a or {}).get("basis"),))

# ---------------------------------------------------------------------------
# B - a real finding still names its item
# ---------------------------------------------------------------------------
b = detector("walkthrough found one failed item", FAIL_TABLE)
b_items = [str(x) for x in ((b or {}).get("items") or [])]
check("B1 a FAIL row names the failed acceptance item",
      isinstance(b, dict) and b.get("named") is True and "2" in b_items,
      "detector=%r" % (b,))
c = detector("", "acceptance item 3 failed: the ops doc section is missing")
check("B2 an English prose finding names the item",
      isinstance(c, dict) and c.get("named") is True,
      "detector=%r" % (c,))
d = detector("", "验收项 2 失败：票面未点名出路")
e = detector("", "第 2 条未通过：计数器仍按轮次累加")
check("B3 the Chinese field forms name the item",
      isinstance(d, dict) and d.get("named") is True
      and isinstance(e, dict) and e.get("named") is True,
      "zh1=%r zh2=%r" % (d, e))

# ---------------------------------------------------------------------------
# C - an unreadable receipt is not "no finding"
# ---------------------------------------------------------------------------
f = detector("", "")
g = detector(None, None)
h = detector(b"bytes", b"report")
i = detector({"summary": "x"}, {"report": "y"})
check("C1 absent report text is a malformed basis, never a clean no-finding report",
      all(isinstance(x, dict) and str(x.get("basis") or "") == "malformed"
          for x in (f, g, h, i)),
      "bases=%r" % ([((x or {}).get("basis")) for x in (f, g, h, i)],))
check("C2 malformed input never raises and never names a finding",
      all(isinstance(x, dict) and x.get("named") is False for x in (g, h, i)),
      "results=%r" % ([(x or {}).get("named") for x in (g, h, i)],))

# ---------------------------------------------------------------------------
# D - the brief and the detector speak one vocabulary
# ---------------------------------------------------------------------------
try:
    import dev_lane
    briefs = getattr(dev_lane.DevLaneWorkflow, "FLOW_BRIEF_SET", {}) or {}
    brief = str(briefs.get("acceptance_walkthrough") or "")
    check("D1 the walkthrough stage brief tells the agent how to name a failed item",
          "failed_item" in brief,
          "brief=%r" % (brief[:300],))
except Exception as e:  # noqa: BLE001
    brief = ""
    env_fail("dev-lane", "dev_lane unimportable: %s: %s" % (type(e).__name__, e))

if brief:
    m = detector("", "failed_item=2")
    n = detector("", "failed_items=none")
    check("D2 the detector reads exactly the marker the brief prescribes",
          isinstance(m, dict) and m.get("named") is True
          and isinstance(n, dict) and n.get("named") is False,
          "with_named=%r with_none=%r" % (m, n))

summary()
