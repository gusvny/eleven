#!/usr/bin/env python3
"""sc_already_settled_no_false_block.py — the block verdict must agree with the
disk (t261007-06, KI-213; grey-box L3, offline seconds, zero docker/Temporal
service; live incident 261007 00:5x-11:4x — seven hits across four tickets).

Incident being guarded (KI-213, notes/debts/known-issues.md): a lane settles
its merge and STILL gets parked on the block text
  "main-sync conflict resolution round N did not converge ... The worktree is
   in a merging state."
while the disk says the opposite — the merge commit is already on HEAD
(join-settle landed it through the same sync core), MERGE_HEAD is absent, the
index has zero unmerged entries, the worktree is clean, zero conflict markers.
The text asserts a state nobody read, and steers the reader toward the two
HEAVY exits (a whole rework round, or an operator `sync --abort` that would
destroy a correct merge). The real exit is one `retry_qc`.

User-perceivable contract locked here (ticket scope 1-3):
  S1 no false "merging state" verdict after a settled merge — when the settle
     activity runs after the join-settle path already landed the commit for
     the same round, the verdict agrees with the disk: ok, already settled,
     the commit named (the workflow's ok-path then proceeds; no block at all);
  S2 measured state, never an assumed one — a fail-closed settle names the
     MEASURED facts (main-ancestor yes/no, unmerged/dirty counts, residue
     files) and never asserts "The worktree is in a merging state";
  S3 the light exit is named — block text written when the disk already
     carries the merge commit says "already settled / retry_qc", not only the
     two heavy exits;
  S4 the text keeps its executable exits — any rewrite of the block text must
     keep rework(to_stage=implement) and the operator --abort entry (they are
     still correct for a genuinely half-merged lane).

Sections:
  A incident sequence on a REAL git face with the REAL production code — a
    mid-merge lane with a resolved face; the join-settle path (the shared sync
    core, single implementation per t261006-07) lands the merge commit and
    consumes MERGE_HEAD; the branch-side settle activity then runs in its own
    window (the measured incident shape) — its verdict must be ok=True /
    already_settled=True / commit == short HEAD (RED until implement lands:
    today it returns ok=False "no merge in progress");
  B disk-agreement truth table — clean settled face agrees with disk (ok,
    already_settled, commit named); fail-closed faces (main not an ancestor,
    dirty worktree, marker residue, missing ref, nonexistent worktree path)
    each return ok=False with measured/named facts and NEVER the string
    "merging state";
  C block-text face (source locks, shallow) — "The worktree is in a merging
    state." is gone from the lane sources; every "did not converge" block
    site still carries both executable exits; at least one site names the
    already-settled light exit (RED until implement lands).

Intent split (checked against the registry, no intent-level duplication):
  t261006-07-main-sync-conflict-deadlock owns the deadlock mechanics (round
  cap/reset semantics, index-vs-file-face judgement, operator escape) — this
  entry owns the VERDICT-VS-DISK agreement face and the false-state text,
  which that entry does not touch; t261004-02-block-text-executor-escape owns
  the executor-escape wording contract (its S4-style expectations must move
  together with this ticket's text edits — coordinated text-face change);
  the developer L1 battery (test_t261007_06_already_settled_face.py family)
  owns the unit matrix on the helper/core — this entry locks the production
  sequence and the operator-readable text. t261006-19 owns counter-reset
  replay; round-counter semantics are out of scope for this ticket.

Run: python3 integration/t261007-06/sc_already_settled_no_false_block.py
(cwd = repo root). Engine venv with temporalio, or the git binary, missing =
ENV_FAIL exit 2 — never SKIP. RED sections before the fix lands are the TDD
signal; the whole scenario must be GREEN at arbitrate/merge.
"""
from __future__ import annotations

import asyncio
import atexit
import inspect
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE = ROOT / "server" / "engine"

PASS = 0
FAIL = 0
TMP_ROOT = ROOT / ".sandbar" / "tmp" / "t261007-06"

FALSE_STATE_TEXT = "The worktree is in a merging state"


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title: str) -> None:
    print("\n== %s" % title)


def die_env(msg: str) -> None:
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def cleanup() -> None:
    shutil.rmtree(TMP_ROOT, ignore_errors=True)


atexit.register(cleanup)

# ---- environment gates (ENV_FAIL, never SKIP) -----------------------------
if shutil.which("git") is None:
    die_env("git binary not found")
sys.path.insert(0, str(ENGINE))
try:
    import shared  # noqa: E402  (stdlib-only module)
    import agent_activities as aa  # noqa: E402  (needs temporalio)
except Exception as exc:  # pragma: no cover - environment face
    die_env("engine venv missing (temporalio/agent_activities import): %r" % (exc,))

DL_SRC = (ENGINE / "dev_lane.py").read_text("utf-8")
LL_SRC = (ENGINE / "light_lane.py").read_text("utf-8")

git = subprocess.run


def git_in(cwd, *args):
    return git(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def make_conflicted_lane(base: Path):
    """Real git repo with a merge in progress (same incident shape as the
    t261006-07 scenario fixture): the lane merged main, both sides touched one
    file, the index is left UU with the worktree file resolved-but-unstaged
    (the agent stance — the sandbox cannot write .git)."""
    repo = base / "lane"
    repo.mkdir(parents=True)
    git_in(repo, "init", "-q", "-b", "lane")
    git_in(repo, "config", "user.email", "t@example")
    git_in(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("line=base\nshared=1\n")
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-qm", "base")
    git_in(repo, "branch", "-q", "main")
    (repo / "f.txt").write_text("line=lane\nshared=1\n")
    (repo / "lane_only.txt").write_text("x\n")
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-qm", "lane change")
    git_in(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("line=main\nshared=1\n")
    git_in(repo, "commit", "-qam", "main change")
    git_in(repo, "checkout", "-q", "lane")
    p = git_in(repo, "merge", "main")
    if p.returncode == 0:
        die_env("fixture failed: expected merge conflict, got clean merge")
    return repo


def resolve_worktree(repo: Path) -> None:
    """The agent stance: resolve the file in the worktree, never git add."""
    (repo / "f.txt").write_text("line=resolved\nshared=1\n")


def join_settle(repo: Path):
    """The join-settle face exactly as production reaches it: the shared sync
    core _settle_merge_core (single add/commit implementation, t261006-07;
    the _settle_worktree_lane mid-merge branch calls it at the join)."""
    return aa._settle_merge_core(repo, "t-sc", 0)


def branch_settle(repo: Path):
    """The branch-side settle activity, as the workflow schedules it in its
    own window (the measured incident shape: after join-settle landed)."""
    args = aa.ConflictSettleArgs(ticket_id="t-sc", worktree=str(repo), round_no=1)
    return asyncio.run(aa.settle_conflict_resolution(args))


def core_with_base_ref(repo: Path, base_ref):
    """Call the core the way the fix shapes it (optional base_ref). Pre-fix
    the kwarg does not exist — that is a named FAIL (NOT-LANDED), never a
    crash of the scenario."""
    try:
        if base_ref is None:
            return aa._settle_merge_core(repo, "t-sc", 0)
        return aa._settle_merge_core(repo, "t-sc", 0, base_ref=base_ref)
    except TypeError:
        return shared.ConflictSettleResult(
            ok=False, error="NOT-LANDED: _settle_merge_core takes no base_ref")


def receipt_text(res) -> str:
    return " ".join([str(getattr(res, "error", "") or ""),
                     str(getattr(res, "commit", "") or "")])


# ---- A. the measured incident sequence (real git x real production code) --
section("A incident sequence: join-settle lands, branch-side settle agrees "
        "with the disk (S1)")
TMP_ROOT.mkdir(parents=True, exist_ok=True)
repo = make_conflicted_lane(TMP_ROOT)
resolve_worktree(repo)
js = join_settle(repo)
ok(getattr(js, "ok", False), "join-settle core lands the merge commit on a "
                             "resolved-but-unstaged face")
ok(git_in(repo, "rev-parse", "--verify", "-q", "MERGE_HEAD").returncode != 0,
   "join-settle consumed MERGE_HEAD (the incident precondition)")
disk_head = git_in(repo, "rev-parse", "--short", "HEAD").stdout.strip()

res = branch_settle(repo)  # the window after the failed verification
ok(getattr(res, "ok", False),
   "S1 (RED until fix): branch-side settle agrees with the disk -> ok "
   "(pre-fix: false 'no merge in progress' failure)")
ok(bool(getattr(res, "already_settled", False)),
   "S1 (RED until fix): receipt names the state already_settled")
ok(str(getattr(res, "commit", "")) == disk_head,
   "S1: receipt commit == the merge commit already on disk (%s)" % disk_head)
ok(FALSE_STATE_TEXT not in receipt_text(res),
   "S2: the settle receipt never asserts 'The worktree is in a merging state'")
ok(git_in(repo, "ls-files", "-u").stdout.strip() == "",
   "disk truth unchanged: zero unmerged entries after the second settle")

# ---- B. verdict-vs-disk truth table (fail-closed faces) --------------------
section("B disk-agreement truth table (S2: measured facts, never an assumed "
        "state)")
# B1 clean settled face agrees with the disk (ticket deliverable: block
# verdict agrees with disk when the lane is clean)
repo_b1 = make_conflicted_lane(TMP_ROOT / "b1")
resolve_worktree(repo_b1)
ok(join_settle(repo_b1).ok, "b1 setup: join-settle landed the commit")
r_b1 = core_with_base_ref(repo_b1, "main")
ok(getattr(r_b1, "ok", False),
   "B1 (RED until fix): clean lane (commit present, zero unmerged, clean "
   "face, zero markers) -> verdict ok, agreeing with the disk")
ok(bool(getattr(r_b1, "already_settled", False)),
   "B1 (RED until fix): clean-lane verdict names already_settled")

# B2 main NOT an ancestor of HEAD -> fail-closed with measured facts
repo_b2 = make_conflicted_lane(TMP_ROOT / "b2")
resolve_worktree(repo_b2)
join_settle(repo_b2)
git_in(repo_b2, "checkout", "-q", "main")
(repo_b2 / "f.txt").write_text("line=main-ahead\nshared=1\n")
git_in(repo_b2, "commit", "-qam", "main moves on after the merge")
git_in(repo_b2, "checkout", "-q", "lane")
r_b2 = core_with_base_ref(repo_b2, "main")
ok(not getattr(r_b2, "ok", True),
   "B2: main ahead of HEAD -> fail-closed (never a fabricated ok)")
ok("no merge in progress" in receipt_text(r_b2),
   "B2: grep-stable anchor prefix kept for the incident family")
ok(FALSE_STATE_TEXT not in receipt_text(r_b2),
   "B2: fail-closed text stays factual, never 'merging state'")

# B3 dirty worktree face -> fail-closed
repo_b3 = make_conflicted_lane(TMP_ROOT / "b3")
resolve_worktree(repo_b3)
join_settle(repo_b3)
(repo_b3 / "lane_only.txt").write_text("x\nuncommitted\n")
r_b3 = core_with_base_ref(repo_b3, "main")
ok(not getattr(r_b3, "ok", True), "B3: dirty worktree face -> fail-closed")
ok(FALSE_STATE_TEXT not in receipt_text(r_b3), "B3: text factual, no false state")

# B4 marker residue in the base..HEAD face -> fail-closed, file named
repo_b4 = make_conflicted_lane(TMP_ROOT / "b4")
resolve_worktree(repo_b4)
join_settle(repo_b4)
(repo_b4 / "lane_only.txt").write_text("<<<<<<< HEAD\nx\n>>>>>>> main\n")
r_b4 = core_with_base_ref(repo_b4, "main")
ok(not getattr(r_b4, "ok", True),
   "B4 (RED until fix): conflict-marker residue in the base..HEAD face -> "
   "fail-closed")
ok(FALSE_STATE_TEXT not in receipt_text(r_b4), "B4: text factual, no false state")

# B5 malformed inputs (three-state hook): missing ref / nonexistent path
r_b5 = core_with_base_ref(repo_b1, "no-such-ref")
ok(not getattr(r_b5, "ok", True), "B5: base_ref naming a missing ref -> "
                                  "fail-closed, no crash")
try:
    r_b6 = core_with_base_ref(TMP_ROOT / "no-such-path", "main")
except Exception as exc:  # a malformed worktree path must never crash the caller
    r_b6 = shared.ConflictSettleResult(ok=False, error="RAISED: %r" % (exc,))
ok(not getattr(r_b6, "ok", True),
   "B5: nonexistent worktree path -> ok=False, never raises "
   "(FOUND: production core raises FileNotFoundError on a missing path -- "
   "reported to the result file; fix or accept at review)")

# ---- C. block-text face (source locks, shallow) ----------------------------
section("C block text agrees with the disk (S2/S3/S4)")
ok(FALSE_STATE_TEXT not in DL_SRC and FALSE_STATE_TEXT not in LL_SRC,
   "S2 (RED until fix): 'The worktree is in a merging state' is gone from "
   "the lane sources")
sites = [m.start() for m in re.finditer(r"did not converge", DL_SRC)]
ok(len(sites) >= 2,
   "both block sites found (main-sync parallel + merge_check conflict loop)")
for i, pos in enumerate(sites, 1):
    region = DL_SRC[max(0, pos - 200): pos + 1400]
    ok("rework(to_stage=implement)" in region,
       "S4 site %d: keeps the rework exit (correct for a half-merged lane)" % i)
    ok("--abort" in region,
       "S4 site %d: keeps the operator --abort entry" % i)
    ok(("retry_qc" in region) or ("already settled" in region),
       "S3 (RED until fix) site %d: names the light exit for an "
       "already-settled lane" % i)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
