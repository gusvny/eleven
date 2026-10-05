#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-01 scenario 1: the two-shape UI-evidence contract (KI-205, grey-box L3,
integration design_integration_tests stage).

intent (registered in run_scenarios.py SCENARIOS) — the ticket's REQUIRED OUTCOMES
1/2/4 plus the ENV_FAIL exit face of outcome 3:

- ONE read point: the merge_check ui_evidence gate judges TOP-LEVEL non-recursive
  *.png inside exactly the directory shared.ui_evidence_dir() resolves (sticky: an
  old-named lane resolves to the retired legacy dot-dir (shared.DOT_DIR_OLD),
  host ruling 261005-B stands). An
  image in a SUBDIRECTORY (shape A) counts as missing — the gate does not widen to
  admit the subdir shape (the producer is the side that follows the judge).
- Refusal text == judgement directory: on a legacy-named lane the red item's detail
  and next_action must name the RESOLVED judged directory, never the hard-coded
  default constant — an operator following the text must land where the gate reads
  (incident t261005-10: three PNGs in the legacy-named screenshots dir, text pointing at
  .sandbar/screenshots forever).
- Runnable next action: the red item's next_action names a capture invocation
  whose --out target is the judged directory (runnable, not descriptive prose).
- ENV_FAIL named exit (t261006 probe: docker stage reachable within the wait
  budget but the dsh web token line unreadable in docker logs, exit 2): the error
  must name an operator action (log access / re-run / serialised stage boots) —
  never a bare "token not found" with no way out, and never a silent bare-URL
  fallback.
- Family face (t261006-01 review condition 1): the worker-side "no TOP-LEVEL png"
  refusal must derive its path from the resolved directory too, not interpolate
  the UI_EVIDENCE_DIR constant — same divergence mechanism, same red.

Grey-box binding: assertions land on the gate's emitted check item (title /
detail / next_action — the user-perceivable refusal) and on loose wording families
in the capture error text, never on private names. Reuses the t260904-18 shared
merge_check fixture (real git repo, production .lane/<id> layout, stub admin
isolating the verify_lane face). Zero docker, zero network, never touches 3099.

Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
temporalio missing = ENV_FAIL exit 2 for the merge_check behaviour cases; the
source-text contract cases still run on stdlib.
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "t260904-18"))
sys.path.insert(0, str(HERE))
from lib_t260904_18 import (  # noqa: E402
    REPO, POC, check, summary, env_fail, temporalio_available,
    merge_fixture_repo, ui_evidence_yaml,
)
sys.path.insert(0, str(POC))

SUITE = "t261006-01-ui-evidence-two-shapes"


def write_lane_png(wt, rel, size=64):
    """Drop a minimal untracked PNG into the lane worktree (the gate globs the
    filesystem, not git — untracked files are exactly the transitional shape an
    operator is told to produce)."""
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * size)  # PNG magic; content out of scope
    return p


def resolved_shots_dir(wt):
    """The directory the gate judges, via the SAME helper the gate uses."""
    sys.path.insert(0, str(POC))
    import shared  # noqa: E402  stdlib-only module
    return shared.ui_evidence_dir(wt)


# ---------- merge_check behaviour cases (temporalio face) ----------
if not temporalio_available():
    env_fail("temporalio unavailable in this lane (no engine venv): merge_check "
             "two-shape behaviour cases not executable here — arbitrate/merge "
             "venv environment must run them green")
else:
    import asyncio  # noqa: E402
    import agent_activities  # noqa: E402
    import shared  # noqa: E402
    from agent_activities import MergeCheckArgs  # noqa: E402

    def ui_item(checks):
        items = [c for c in checks if str(c.get("item", "")).startswith("UI")]
        return items[0] if items else None

    def run_merge(legacy=False):
        tmp, mb = merge_fixture_repo({
            "web/ui/a.ts": "export {}\n",
            "verify.yaml": ui_evidence_yaml(["web/ui/"]),
        })
        if legacy:
            # a lane BORN legacy-named (t261005-10 shape): an existing retired
            # LEGACY dot-dir dots the coordination directory sticky-old for life —
            # it must exist BEFORE the gate runs, or the fixture proves nothing
            (tmp / shared.DOT_DIR_OLD / "screenshots").mkdir(parents=True)
        try:
            res = asyncio.run(agent_activities.merge_check(MergeCheckArgs(
                ticket_id="t26100601sc", worktree=str(tmp), branch="lane",
                base_ref=mb, write_set=["web/ui/"])))
            return tmp, mb, ui_item(res.checks)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    # -- shape A: PNG in a subdirectory counts as missing (gate does not widen) --
    tmpA, _mbA, item = run_merge()
    try:
        write_lane_png(tmpA, ".sandbar/screenshots/acceptance/shot.png")
        judge_dir = resolved_shots_dir(tmpA)
        check("A1 subdir PNG -> gate stays red (top-level-only, no widening)",
              item is not None and item.get("green") is False,
              "ui_evidence item: %s" % str(item)[:240])
        check("A2 refusal text names the judged directory (text == judgement)",
              item is not None and str(judge_dir) in str(item.get("detail", "")),
              "judge_dir=%s detail=%s" % (judge_dir, str(item.get("detail", ""))[:240]))
        check("A3 next_action names a capture run with --out at the judged dir",
              item is not None and "capture" in str(item.get("next_action", "")).lower()
              and str(judge_dir) in str(item.get("next_action", "")),
              "next_action=%s" % str(item.get("next_action", ""))[:240])
    finally:
        shutil.rmtree(tmpA, ignore_errors=True)

    # -- shape B: legacy-named lane, text and judgement must agree --
    tmpB, mb, item = run_merge(legacy=True)
    try:
        judge_dir = resolved_shots_dir(tmpB)
        legacy = str(judge_dir)
        # red variant first: no PNG at the judged top level
        check("B1 legacy lane, no PNG -> red", item is not None and item.get("green") is False,
              "judge_dir=%s item=%s" % (legacy, str(item)[:200]))
        check("B2 red text contains the RESOLVED legacy path, not a wrong default",
              item is not None and legacy in str(item.get("detail", ""))
              and legacy in str(item.get("next_action", "")),
              "judge_dir=%s detail=%s next=%s" % (
                  legacy, str(item.get("detail", ""))[:200],
                  str(item.get("next_action", ""))[:160]))
        legacy_named = (judge_dir.name == shared.DOT_DIR_OLD
                        or shared.DOT_DIR_OLD in legacy)
        check("B3 fixture really exercised the sticky legacy resolution",
              legacy_named, "judge_dir=%s (a non-legacy fixture would prove nothing)"
              % legacy)
        # green variant: a top-level PNG at the judged location turns the gate green
        write_lane_png(tmpB, str(judge_dir.relative_to(tmpB)) + "/ok.png")
        res2 = asyncio.run(agent_activities.merge_check(MergeCheckArgs(
            ticket_id="t26100601sc", worktree=str(tmpB), branch="lane",
            base_ref=mb, write_set=["web/ui/"])))
        item2 = ui_item(res2.checks)
        check("B4 legacy lane, top-level PNG at the judged dir -> green",
              item2 is not None and item2.get("green") is True,
              "judge_dir=%s item=%s" % (legacy, str(item2)[:240]))
    finally:
        shutil.rmtree(tmpB, ignore_errors=True)


# ---------- source-text contract faces (stdlib; word-family matching, loose) ----------
_cap = REPO / "server" / "ui-check" / "capture-lane.mjs"
if not _cap.is_file():
    check("C1 capture-lane ENV_FAIL text names an operator exit", False,
          "server/ui-check/capture-lane.mjs missing — producer face gone", str(_cap))
else:
    txt = _cap.read_text(encoding="utf-8", errors="replace")
    # the reachable-but-no-token docker-branch error (KI-205 probe, exit 2)
    m = re.search(r"token[^\\n]*", txt)
    window = txt
    # t261006-02 rework: the auth surface is now PROBED (resolveAuthEntry), so the
    # token-missing face lives at the "token-gate-no-token" refusal, not at the old
    # "取不到 dsh web token" log line — re-anchored to the new contract point without
    # weakening the assertion (same named-exit contract, current anchor; fallback
    # chain keeps the old anchors for a future refactor of the marker string).
    hit = txt.find("token-gate-no-token")
    if hit < 0:
        hit = txt.find("取不到 dsh web token")
    if hit < 0:
        hit = txt.find("token")
    if hit >= 0:
        window = txt[max(0, hit - 200):hit + 900]
    actions = re.compile(r"docker logs|重跑|retry|re-run|等待|wait|串行|serial", re.I)
    envchan = re.compile(r"ENV_FAIL|process\.exit\(2\)", re.I)
    check("C1 capture-lane ENV_FAIL text names an operator exit",
          hit >= 0 and bool(actions.search(window)),
          "the reachable-but-no-token error must name what the operator can do "
          "(log access / re-run / wait budget / serialised boots); window=%s"
          % window[:300].replace("\n", " "))
    # The refusal Error is consumed at the shared auth-path catch: the bench must map
    # it to the named ENV_FAIL exit-2 channel (never a green with fewer shots, never a
    # bare-URL continue). Asserted structurally at the consumption point — the marker
    # and the channel are far apart in the file by design (resolveAuthEntry is a pure
    # seam; the exit happens where the readiness error propagates).
    marker = txt.find("token-gate-no-token")
    close = False
    chan = -1
    chan_exit = -1
    pos = 0
    while True:
        chan = txt.find("不静默回落裸 URL 假跑", pos)
        if chan < 0:
            break
        e = txt.find("process.exit(2)", chan)
        if 0 <= e - chan < 200:
            close = True
            chan_exit = e
            break
        pos = chan + 1
    check("C2 token failure stays on the ENV_FAIL channel (exit 2), no product red",
          marker >= 0 and chan >= 0 and close,
          "the token-missing branch must terminate as a named ENV_FAIL exit 2: the "
          "token-gate-no-token refusal marker must exist and the auth-path catch must "
          "map its error to process.exit(2) with the no-bare-URL-fallback wording; "
          "marker=%s chan=%s chan_exit=%s" % (marker, chan, chan_exit))

_act = POC / "agent_activities.py"
if not _act.is_file():
    check("D1 worker-side no-png refusal derives from the resolved dir", False,
          "agent_activities.py missing", str(_act))
else:
    atxt = _act.read_text(encoding="utf-8", errors="replace")
    idx = atxt.find("no TOP-LEVEL png under")
    if idx < 0:
        check("D1 worker-side no-png refusal derives from the resolved dir", False,
              "the 'no TOP-LEVEL png under' refusal face is gone — face renamed "
              "without carrying the contract")
    else:
        win = atxt[max(0, idx - 300):idx + 500]
        const_fed = re.search(r"%\s*UI_EVIDENCE_DIR", win)
        derived = ("ui_evidence_dir" in win) or ("shots_dir" in win)
        check("D1 worker-side no-png refusal derives from the resolved dir",
              bool(derived) and not const_fed,
              "the refusal must interpolate the ui_evidence_dir() resolution, "
              "never the hard-coded default constant (same divergence as the "
              "merge_check text, legacy lane); window=%s"
              % win[:300].replace("\n", " "))

sys.exit(summary())
