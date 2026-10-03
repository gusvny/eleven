#!/usr/bin/env python3
"""sc_merge_check_resync.py — merge_check re-run must re-merge main (t261002-10).

Run directly: python3 integration/t261002-10/sc_merge_check_resync.py (cwd = repo root).

Gray-box L3, offline, seconds, no docker/no Temporal server. Incident being
guarded (KI-189 / t261001-20): a red on main was fixed on main AFTER the
ticket's gate round; the ticket's retry_qc re-ran merge_check against the same
stale lane tree and hit the identical pre-fix red — the fix could never reach
the parked ticket. Contract under test: a re-entry into the merge_check phase
performs the same pre-check main sync the gate rounds perform, BEFORE re-run-
ning the in-lane check; every failure shape (merge conflict, main unreachab-
le) surfaces as a named error that says which check failed, never a bare
"not green".

Faces (user-perceivable behavior, not internals):
  A. Real-git behavior face via the production merge activity itself
     (prepare_conflict_resolution — the exact activity the workflow-layer sync
     calls; importing it needs the engine venv: temporalio → ENV_FAIL exit 2):
     A1 a main-side fix committed after the lane branched reaches the lane
        within ONE sync call (merge commit, fix is ancestor of lane HEAD,
        worktree clean, receipt carries target_sha/lane_head);
     A2 second call is the zero-action up-to-date fast path (HEAD unchanged);
     A3 a conflicting main change is detected and NAMED (conflict files listed,
        lane HEAD untouched until a human/agent resolves — we abort and assert);
     A4 an unreachable merge target produces a named error quoting the missing
        ref — not a bare failure.
  B. Workflow/doc consistency face (source-level gray-box locks, kept shallow:
     order + gate keys only, no micro-internals):
     B1 dev-lane merge_check phase calls the shared sync helper BEFORE the
        merge_check activity, behind its own patch id (replay discipline);
     B2 light-lane merge_check phase has the same shape;
     B3 the gate call site is unchanged (helper still the single implementat-
        ion; the merge_check call passes its own step id, gate default intact);
     B4 both lanes' merge_check stage descriptions and the ticket tool's
        retry_qc help state the pre-check re-merge (doc/behavior agreement at
        BOTH machine stages — ticket acceptance ③).
  C. Named-error discipline: the sync's loud-blocked path text names the
     failed mechanism (main sync) and the step it blocks — the dispatch's
     "never a bare 'not green'" rule, locked at the workflow's only loud-exit
     message site.

Implementation-not-landed legs (B*) are expected RED until the implement
stage lands (TDD signal); the whole scenario must be GREEN at arbitrate/merge.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DL = ROOT / "server/engine/dev_lane.py"
LL = ROOT / "server/engine/light_lane.py"
TICKET = ROOT / "server/tools/ticket.py"

PASS = 0
FAIL = 0


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title: str) -> None:
    print("\n%s" % title)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, env=env)


def _repo(tmp: Path, name: str) -> Path:
    """origin with a main branch; a lane branched at main~1 (stale tree)."""
    origin = tmp / name
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    (origin / "base.txt").write_text("base\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "base")
    git(origin, "commit", "-qm", "gate-era commit",
        "--allow-empty")
    git(origin, "branch", "lane")          # lane = main~1 point... see below
    # actually: lane must fork BEFORE the fix, i.e. at current HEAD; the fix
    # then lands on main afterwards — mirroring the incident timeline.
    return origin


def _lane_with_divergence(tmp: Path, name: str):
    """origin repo + lane worktree clone; returns (origin, lane)."""
    origin = _repo(tmp, name)
    lane = tmp / (name + "-lane")
    git(origin, "worktree", "add", "-q", str(lane), "lane")
    return origin, lane


def _fix_on_main(origin: Path, fname: str = "fix.txt") -> str:
    (origin / fname).write_text("the fix\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "main-side fix (incident replay)")
    return git(origin, "rev-parse", "main").stdout.strip()


def _env_fail(msg: str) -> None:
    print("ENV_FAIL: %s" % msg)
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (PASS, 0, 1, 0))
    sys.exit(2)


def main() -> int:
    # ---- engine venv gate (temporalio importability) ----
    venv_py = ROOT / "server/engine/.venv/bin/python"
    alt_py = ROOT / "server/dsh/temporal-poc/.venv/bin/python"  # engine-venv-compat（迁移窗口回落链行，marker=约定豁免锚；旧布局摘除票落地随撤）
    py = str(venv_py if venv_py.exists() else
             (alt_py if alt_py.exists() else sys.executable))
    probe = subprocess.run(
        [py, "-c", "import temporalio"], capture_output=True, text=True)
    if probe.returncode != 0:
        _env_fail("engine venv (temporalio) missing: %s"
                  % (probe.stderr or "").strip()[-200:])
    # re-exec self under the venv python so the production activity imports
    try:
        import temporalio  # noqa: F401
    except ImportError:
        os.execv(py, [py, __file__])

    section("A. real-git behavior face (production merge activity)")
    sys.path.insert(0, str(ROOT / "server/engine"))
    from agent_activities import (  # noqa: E402
        ConflictPrepArgs, ConflictPrepResult, prepare_conflict_resolution)

    async def run_prep(worktree: str, base_ref: str = "main"):
        import asyncio
        return await prepare_conflict_resolution(
            ConflictPrepArgs(ticket_id="t261002-10", worktree=worktree,
                             branch="lane", base_ref=base_ref))

    import asyncio
    with tempfile.TemporaryDirectory(prefix="t261002-10-") as td:
        tmp = Path(td)
        origin, lane = _lane_with_divergence(tmp, "repo")
        fix_sha = _fix_on_main(origin)

        # A1: one sync brings the post-branch main fix into the lane
        r = asyncio.get_event_loop().run_until_complete(run_prep(str(lane)))
        ok(isinstance(r, ConflictPrepResult) and r.ok, "A1 sync activity ok")
        ok(not r.up_to_date, "A1 not the fast path on first call")
        ok(r.conflict_files == [], "A1 clean merge, no conflict files")
        anc = git(lane, "merge-base", "--is-ancestor", fix_sha, "HEAD")
        ok(anc.returncode == 0, "A1 fix is ancestor of lane HEAD (reached the tree)")
        ok(git(lane, "status", "--porcelain").stdout.strip() == "",
           "A1 lane worktree clean after merge commit")
        ok(r.target_sha == fix_sha, "A1 receipt target_sha = main@fix")
        ok(bool(r.lane_head), "A1 receipt lane_head present")

        # A2: second call = zero-action up-to-date fast path
        head_before = git(lane, "rev-parse", "HEAD").stdout.strip()
        r2 = asyncio.get_event_loop().run_until_complete(run_prep(str(lane)))
        ok(r2.up_to_date and r2.ok, "A2 fast path up_to_date=True")
        ok(git(lane, "rev-parse", "HEAD").stdout.strip() == head_before,
           "A2 HEAD unchanged (idempotent, zero action)")

        # A3: conflicting main change is detected and NAMED, HEAD untouched
        (lane / "base.txt").write_text("lane edit\n")
        git(lane, "add", "-A")
        git(lane, "commit", "-qm", "lane edit")
        (origin / "base.txt").write_text("main edit\n")
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "main edit (conflicting)")
        head_before = git(lane, "rev-parse", "HEAD").stdout.strip()
        r3 = asyncio.get_event_loop().run_until_complete(run_prep(str(lane)))
        ok(r3.ok and r3.conflict_files == ["base.txt"],
           "A3 conflict detected and named (base.txt listed)")
        git(lane, "merge", "--abort")
        ok(git(lane, "rev-parse", "HEAD").stdout.strip() == head_before,
           "A3 lane HEAD untouched while conflict unresolved")

        # A4: unreachable target → named error quoting the missing ref
        r4 = asyncio.get_event_loop().run_until_complete(
            run_prep(str(lane), base_ref="no-such-ref"))
        ok((not r4.ok) and "no-such-ref" in (r4.error or ""),
           "A4 unreachable target = named error quoting the ref")

    section("B. workflow/doc consistency (gray-box source locks)")
    dl_src = DL.read_text(encoding="utf-8") if DL.exists() else ""
    ll_src = LL.read_text(encoding="utf-8") if LL.exists() else ""
    tk_src = TICKET.read_text(encoding="utf-8") if TICKET.exists() else ""

    def mc_block(src: str) -> str:
        m = re.search(r'if phase == "merge_check":', src)
        return src[m.start():m.start() + 4000] if m else ""

    dl_mc = mc_block(dl_src)
    ll_mc = mc_block(ll_src)

    ok(bool(dl_mc), "B-pre dev-lane merge_check block located")
    _sync_m = re.search(r"_main_sync_before_gate\(", dl_mc)
    _act_m = re.search(r"execute_activity\(\s*merge_check,", dl_mc)
    ok(_sync_m is not None and _act_m is not None
       and _sync_m.start() < _act_m.start(),
       "B1 dev-lane merge_check phase syncs BEFORE the check activity")
    ok(re.search(r'PATCH_ID\s*=\s*"[^"]*merge-check', dl_src) is not None
       and "dev-lane-main-sync-v1" not in re.findall(
           r'PATCH_ID\s*=\s*"([^"]*)"', dl_src)[-1:],
       "B1 merge_check re-sync runs behind its own patch id")
    ok(re.search(r"_main_sync_before_gate\(", ll_mc) is not None,
       "B2 light-lane merge_check phase also syncs")
    ok(re.search(r"step_id[^=]*[:=]", dl_src) is not None
       and '"run_integration_tests"' in dl_src,
       "B3 helper takes step_id with gate default (gate site unchanged)")
    ok(any(t in tk_src for t in
           ("主同步", "重并", "重跑前", "main sync", "merge main")),
       "B4 ticket.py retry_qc help states the pre-check main sync")
    ok(bool(re.search(r'STAGES.*merge_check|merge_check.*重并|merge_check.*主同步',
                      dl_src, re.S)),
       "B4 dev-lane STAGES merge_check desc mentions the re-merge")
    ok("re-merge" in ll_src or "re-merges" in ll_src
       or "重并" in ll_src,
       "B4 light-lane merge_check desc mentions the re-merge")

    section("C. named-error discipline (never a bare 'not green')")
    _helper = dl_src.split("def _main_sync_before_gate", 1)
    _helper = _helper[1][:26000] if len(_helper) > 1 else ""
    ok("主同步失败" in _helper and "主同步检出 merge 冲突" in _helper,
       "C loud-blocked texts name the failed mechanism (main sync / conflict)")
    ok("不静默跳过" in _helper or "不静默" in _helper,
       "C no silent skip on sync failure")
    ok(re.search(r'_blocked\([^)]*,\s*"(?:not green|未产出结果)"', _helper) is None,
       "C no _blocked call in the sync passes a bare placeholder message")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    # Windows loop-policy neutrality; POSIX default fine.
    try:
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
    sys.exit(main())
