#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-07: main-sync conflict cap deadlock fix (R1-R5) unit tests.

Live incident (integration night report, t261005-06 / t261005-10): conflict_rounds
was a run()-local counter reset only at workflow start — rework/retry_qc resumed
the same loop and never reset it, so once >3 it stayed >3 forever; the route only
read the index UU shape (the agent sandbox cannot write the real .git), so a
resolved-but-unstaged file face still read as conflicting; and the implement join
unconditionally skipped a mid-merge worktree. Stacked, the better the file face,
the less escapable the lane — the only rescue was a hand-run worker activity.

The fix, locked here layer by layer (the ticket's R1-R5):
  R1 judge the file face, not the index: a blocked route runs one settle first
     (add-before-judge); the join mid-merge guard settles a clean face through
     the shared sync core _settle_merge_core (single-implementation discipline —
     never a second add/commit sequence).
  R2 the cap counts non-progressing rounds: settle success = progress = reset
     (the same-batch guard keeps its teeth).
  R3 a human signal resets: rework / retry_qc reset the counter (a rework
     rejected by the cross-project gate never mutates it).
  R4 executable guidance: no blocked text assigns an in-lane git command.
  R5 named operator entry: `server/tools/engine_ops.py sync <ticket-id>
     --abort` (existing, documented in docs/ops).

Run: server/engine/.venv/bin/python -B -m pytest \\
      server/engine/tests/test_t261006_07_conflict_deadlock.py -q
"""
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402
from shared import (ConflictSettleArgs, main_sync_blocked_settle_plan,  # noqa: E402
                    main_sync_conflict_route)


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _ok_git(repo: Path, *args: str) -> str:
    p = _git(repo, *args)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


@pytest.fixture()
def mid_merge(tmp_path: Path) -> Path:
    """Real repo in the "merge in progress + one UU file" shape (main/lane both
    touched one file)."""
    r = tmp_path / "repo"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    f = r / "conflict.txt"
    f.write_text("base\n", encoding="utf-8")
    _ok_git(r, "add", "-A")
    _ok_git(r, "commit", "-m", "base")
    default = _ok_git(r, "rev-parse", "--abbrev-ref", "HEAD")
    _ok_git(r, "checkout", "-b", "lane")
    f.write_text("lane side\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "lane change")
    _ok_git(r, "checkout", default)
    f.write_text("main side\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "main change")
    _ok_git(r, "checkout", "lane")
    p = _git(r, "merge", default)
    assert p.returncode != 0, "fixture produced no conflict"
    return r


def _resolve_without_add(repo: Path) -> None:
    """Resolve the conflict in the agent stance: edit the file, NEVER git add
    (the sandbox cannot write the real .git, so the index keeps showing UU)."""
    f = repo / "conflict.txt"
    f.write_text("lane side\nmain side\n", encoding="utf-8")
    st = _ok_git(repo, "status", "--porcelain")
    assert "UU" in st, "precondition: the index must stay UU (agent sandbox stance)"


def asyncio_run_settle(repo: Path):
    import asyncio
    return asyncio.run(aa.settle_conflict_resolution(
        ConflictSettleArgs(ticket_id="t261006-07", worktree=str(repo),
                           branch="lane", base_ref="main", round_no=9)))


# ---------------- R1: settle first / judge the file face ----------------

def test_settle_first_plan_matrix():
    assert main_sync_blocked_settle_plan("blocked:anything", True) == "settle_first"
    assert main_sync_blocked_settle_plan("blocked:", True) == "settle_first"


@pytest.mark.parametrize("route,mip", [
    ("resolve", True),          # not a blocked verdict -> never settle on its behalf
    ("", True),                 # empty route
    (None, True),               # not a str
    (42, True),                 # not a str
    ("blocked:x", False),       # no merge in progress = nothing to close out
    ("blocked:x", None),        # merge_in_progress not a bool -> conservative block
    ("blocked:x", "yes"),       # not a bool (a truthy string does not pass either)
])
def test_settle_first_plan_malformed_fail_closed(route, mip):
    """Review note 1, the single rule: route not blocked:* or merge_in_progress
    not bool/False -> always "block" (an unparsable reason never settles)."""
    assert main_sync_blocked_settle_plan(route, mip) == "block"


def test_resolved_face_settles_despite_uu_index(mid_merge):
    """R1 core: a clean file face with a UU index settles ok and lands the merge
    commit (never judged "still conflicting" from the index alone)."""
    r = mid_merge
    _resolve_without_add(r)
    res = asyncio_run_settle(r)
    assert res.ok is True, ("a resolved file face must judge ok (UU is only an "
                            "index shape): %s" % res.error)
    assert res.commit
    assert _git(r, "rev-parse", "--verify", "MERGE_HEAD").returncode != 0, \
        "after the merge commit lands, MERGE_HEAD must be consumed"
    content = _ok_git(r, "show", "HEAD:conflict.txt")
    assert "<<<<<<<" not in content and "lane side" in content and "main side" in content


def test_unresolved_face_still_rejected(mid_merge):
    """Counter-case: marker residue -> settle refuses and names the files (the
    file-face criterion is not a leniency gate)."""
    r = mid_merge
    assert (r / "conflict.txt").read_text("utf-8").startswith("<<<<<<<")
    res = asyncio_run_settle(r)
    assert res.ok is False and res.remaining_files == ["conflict.txt"]


# ---------------- Mechanism 3 close-out: the join's mid-merge guard ----------------

def _join_settle(repo: Path) -> str:
    orig = aa.REPO_ROOT
    aa.REPO_ROOT = repo
    try:
        return aa._settle_worktree_lane(repo, "t261006-07", "implement", 2, face="join")
    finally:
        aa.REPO_ROOT = orig


def test_join_settles_resolved_mid_merge_face(mid_merge):
    """A resolved file face: the join settles the merge commit (the old dead end,
    now a close-out path)."""
    r = mid_merge
    _resolve_without_add(r)
    head_before = _ok_git(r, "rev-parse", "HEAD")
    note = _join_settle(r)
    assert "zero residue" in note and "t261006-07" in note, note
    assert _git(r, "rev-parse", "--verify", "MERGE_HEAD").returncode != 0
    assert _ok_git(r, "rev-parse", "HEAD") != head_before, "the join must land the merge commit"


def test_join_still_skips_residue_face(mid_merge):
    """Residue remains: the old guardrail verbatim (no add, no commit — markers
    are never committed as content)."""
    r = mid_merge
    head_before = _ok_git(r, "rev-parse", "HEAD")
    note = _join_settle(r)
    assert "merge in progress" in note and "settle_conflict_resolution" in note
    assert _git(r, "rev-parse", "--verify", "MERGE_HEAD").returncode == 0
    assert _ok_git(r, "rev-parse", "HEAD") == head_before, "the guardrail must still not commit"


def test_join_and_activity_share_one_core():
    """Single-implementation discipline: the join's mid-merge branch and
    settle_conflict_resolution share _settle_merge_core (never a second copy of
    the add/commit sequence)."""
    src = Path(aa.__file__).read_text("utf-8")
    assert src.count("def _settle_merge_core(") == 1
    guard = src.split("    p = _git([\"rev-parse\", \"--verify\", \"MERGE_HEAD\"], cwd)",
                     1)[1].split("    notes: List[str] = []", 1)[0]
    assert "_settle_merge_core(cwd" in guard, "the join guardrail must go through the shared core"
    # settle_conflict_resolution's non-abort path goes through the core too (the
    # old inline body has moved out)
    act = src.split("async def settle_conflict_resolution(", 1)[1]
    act = act.split("def _settle_merge_core(", 1)[0]
    assert "return _settle_merge_core(wt, args.ticket_id, args.round_no)" in act
    assert '"add", "-A"' not in act, "the activity body must not keep a second add sequence"
    core = src.split("def _settle_merge_core(", 1)[1].split("\n\ndef ", 1)[0]
    assert core.count('"add", "-A"') == 1, "the add sequence lives only in the shared core"


# ---------------- R3: a human signal resets the counter ----------------

def _ut_shell(rounds: int = 5, prev=("a:x",)):
    """UT shell (no __init__, the test_260929 shape): only the state slots the
    signal handlers touch."""
    wl = dev_lane.DevLaneWorkflow.__new__(dev_lane.DevLaneWorkflow)
    wl.meta = {}
    wl.timeline = []
    wl._rework = None
    wl._retry_token = 0
    wl._conflict_rounds = rounds
    wl._prev_conflict_files = list(prev)
    wl._log = lambda *a, **k: None
    wl._now_iso = lambda: "2026-10-06T00:00:00Z"
    wl._cross_project_gate = lambda *a, **k: True
    return wl


def test_rework_signal_resets_conflict_counter_over_cap():
    """R3 positive: the lane sits over the cap (5>3); after the human rework the
    next round must be allowed to resolve instead of blocking again."""
    wl = _ut_shell(rounds=5)
    wl.rework(shared.ReworkRequest(who="host", target_stage="implement", note="human"))
    assert wl._conflict_rounds == 0 and wl._prev_conflict_files == []
    assert wl._rework is not None, "the signal payload itself is unaffected by the reset"
    assert main_sync_conflict_route(
        wl._conflict_rounds + 1, ["a:y"], wl._prev_conflict_files, 3) == "resolve", \
        "the round after the reset must allow resolve (not hit the cap block again)"


def test_retry_qc_signal_resets_conflict_counter_over_cap():
    wl = _ut_shell(rounds=12, prev=["a:x"])
    wl.retry_qc("host")
    assert wl._conflict_rounds == 0 and wl._prev_conflict_files == []
    assert wl._retry_token == 1, "retry_qc's own semantics unchanged (token still +1)"


def test_rejected_rework_never_resets_counter():
    """Review note 2: a rework rejected by the cross-project gate never silently
    mutates the guard counters."""
    wl = _ut_shell(rounds=5)
    wl._cross_project_gate = lambda *a, **k: False
    wl.rework(shared.ReworkRequest(who="host", target_stage="implement", note="x"))
    assert wl._rework is None, "rejected = not accepted (existing semantics)"
    assert wl._conflict_rounds == 5 and wl._prev_conflict_files, "a rejection must not reset"


# ---------------- R2: the cap counts non-progressing rounds ----------------

def test_cap_still_counts_non_progressing_rounds():
    """Same-batch guard unchanged: a genuinely spinning lane (same batch twice)
    still blocks."""
    out = main_sync_conflict_route(2, ["a", "b"], ["b", "a"], cap=3)
    assert out.startswith("blocked:") and "same batch" in out
    # over-cap still blocks (reset happens only on progress / a human signal)
    out2 = main_sync_conflict_route(4, ["c"], ["b"], cap=3)
    assert out2.startswith("blocked:") and \
        "main-sync conflict resolution did not converge in 3 rounds" in out2


def test_settle_success_points_reset_counter():
    """Source anchor: every settle-success path (main-sync helper / merge_check
    branch) plus the auto-escape path resets the counter — settle success never
    accumulates."""
    src = Path(dev_lane.__file__).read_text("utf-8")
    # Reset-site census: run() init x1, abort paths x2, helper settle-success x1,
    # auto-escape x1, merge_check green x1, merge_check settle-success x1, human
    # signals x2 (rework/retry_qc) = 9.
    assert src.count("self._conflict_rounds = 0") == 9, \
        "reset-site count drifted = some path misses a reset or double-resets; audit each"
    # On the success path the reset must precede the _auto_rework advance.
    helper = src.split("async def _main_sync_before_gate(", 1)[1].split(
        "    @workflow.run", 1)[0]
    seg = helper.split("_ok_round = self._conflict_rounds", 1)[1]
    assert seg.index("self._conflict_rounds = 0") < seg.index("self._auto_rework(")


# ---------------- R4/R5: executable exits + named operator entry ----------------

def test_blocked_texts_name_executable_exits_only():
    dl = Path(dev_lane.__file__).read_text("utf-8")
    sh = Path(shared.__file__).read_text("utf-8")
    # R4: no text assigns an in-lane git command to an agent (the old "run git
    # merge --abort inside the lane" must be retired; the git merge --abort in
    # the abort activity is a worker action, a different thing).
    assert "git merge --abort inside" not in dl
    assert "git merge --abort inside" not in sh
    # R5: the named operator entry (the existing engine_ops.py sync --abort,
    # documented in docs/ops) is named at every relevant block text.
    assert sh.count("engine_ops.py sync") == 2, "route text single point: assembly + docstring"
    assert dl.count("engine_ops.py sync") >= 2, "both did-not-converge texts name the operator entry"
    for src in (dl, sh):
        assert "rework(to_stage=implement)" in src
    # R4 anchor kept (selfcheck D-4 depends on it): the over-cap anchor sentence
    # survives in the route text verbatim.
    route = main_sync_conflict_route(4, ["a"], ["b"], cap=3)
    assert "main-sync conflict resolution did not converge in 3 rounds" in route


def test_dev_lane_helper_wires_settle_first_on_blocked_route():
    """Wiring anchor: inside the route-blocked branch, ask the settle-first plan
    first; on success auto-escape with a distinct one-line note (review note 3:
    an auto-escape must not be confusable with a normal resolution round)."""
    src = Path(dev_lane.__file__).read_text("utf-8")
    i = src.index("if _route.startswith(\"blocked:\"):")
    seg = src[i:src.index("self._prev_conflict_files = files_sig", i)]
    assert "main_sync_blocked_settle_plan(" in seg
    assert seg.index("main_sync_blocked_settle_plan(") < \
        seg.index("await self._blocked("), "settle first, block after"
    # Replay safety: the auto-escape adds an activity call to a path old
    # histories recorded as a bare _blocked — it must be patch-gated.
    assert "workflow.patched(MAIN_SYNC_SETTLE_FIRST_PATCH_ID)" in seg, \
        "the settle-first branch must be patch-gated (in-flight replay compat)"
    assert dev_lane.MAIN_SYNC_SETTLE_FIRST_PATCH_ID == "t261006-07-main-sync-settle-first"
    assert "overtaken by a successful settle" in seg, "an auto-escape needs its own observable note"
    assert seg.index("overtaken by a successful settle") < \
        seg.index("await self._blocked(")
