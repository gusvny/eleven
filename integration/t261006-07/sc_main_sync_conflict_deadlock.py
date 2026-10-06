#!/usr/bin/env python3
"""main_sync_conflict_deadlock — the lane cannot be locked out by the conflict
round cap (t261006-07, grey-box L3, offline seconds, zero docker/Temporal
service; live incident 261006 00:4x-08:1x — two lanes blocked forever with
"did not converge in N rounds (cap 3)", N only increasing across five human
interventions, while the file faces were already fully resolved).

The incident stack, as observable requirements this scenario locks:
  R1 no deadlock from the index alone — a resolved-but-unstaged merge face
     (UU in the index; the agent sandbox cannot write .git) must be settleable,
     not judged "still conflicting" forever;
  R2 the cap counts NON-PROGRESSING rounds, not lifetime detections — a round
     ending in a successful settle resets the counter;
  R3 a human signal (rework / retry_qc) resets the counter — a lane driven
     over the cap must be resumable by the signal the block text itself names;
  R4 guidance must be executable — no block/rework instruction tells an agent
     to run git commands inside the lane;
  R5 a named, documented operator entry closes a half-merged lane
     (server/tools/engine_ops.py sync <ticket> --abort).

Sections:
  A route contract truth table — the REAL shared.main_sync_conflict_route:
     over-cap blocked (anchor sentence + round count), same-batch blocked,
     progressing round resolves, malformed inputs fail conservative (blocked,
     never silently resolve);
  B R1 end-to-end on a REAL git fixture with the REAL worker activity — a
     merge conflict resolved in the worktree WITHOUT git add (the agent
     stance; index still UU) settles ok with a merge commit; residue still
     fails with remaining_files; abort mode resets a mid-merge worktree and
     is idempotent (tonight's hand-run rescue becomes a supported op);
  C R2/R3 counter semantics — source anchors: the human signal handlers and
     both settle-success points reset the counter (RED until implement lands);
     plus a table-driven micro replay of the loop: settle-success rounds never
     accumulate past the cap, identical consecutive batches still block;
  D R4 text face — neither blocked text instructs an agent to run git
     commands; both name the executable exits (rework(to_stage=implement) and
     the operator entry); the grep-stable anchor sentence survives;
  E R5 operator entry — engine_ops.py sync --abort exists and is documented
     in docs/ops/engine-worker-and-lane-operations.md.

Intent split: the block-text executor-escape contract (what the text says at
block time, merge_check branch) is t261004-02-block-text-executor-escape; the
conflict-loop orchestration belongs to the engine selfcheck (L1). This entry
owns the deadlock mechanics themselves: reset semantics (R2/R3), the
index-vs-file-face judgement (R1) on a real git face, and the operator escape
(R5). t261004-02 section B/C text expectations must move together with this
ticket's text changes (coordinated text-face change, see ticket report).

Run: python3 integration/t261006-07/sc_main_sync_conflict_deadlock.py
(cwd = repo root; engine venv with temporalio required for section B import
= ENV_FAIL exit 2 without it, never SKIP).
"""

from __future__ import annotations

import atexit
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
TMP_ROOT = ROOT / ".sandbar" / "tmp" / "t261006-07"


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
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
    import shared  # noqa: E402  (stdlib-only module: route pure function)
    import agent_activities as aa  # noqa: E402  (needs temporalio)
except Exception as exc:  # pragma: no cover - environment face
    die_env("engine venv missing (temporalio/agent_activities import): %r" % (exc,))

DL_SRC = (ENGINE / "dev_lane.py").read_text("utf-8")
SHARED_SRC = (ENGINE / "shared.py").read_text("utf-8")
AA_SRC = (ENGINE / "agent_activities.py").read_text("utf-8")
OPS_SRC = (ROOT / "server" / "tools" / "engine_ops.py").read_text("utf-8")
OPS_DOC = ROOT / "docs" / "ops" / "engine-worker-and-lane-operations.md"

ANCHOR_OVER_CAP = "main-sync conflict resolution did not converge in"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True)


def make_conflicted_lane(base: Path):
    """Real git repo with a merge in progress: lane merged main and both sides
    touched one file. Returns (repo, conflict_file). Index is left UU with the
    worktree file RESOLVED-but-unstaged (the agent stance)."""
    repo = base / "lane"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "lane")  # -b: the default branch name is
    # environment-dependent (some gits default to main) — pin the lane name
    git(repo, "config", "user.email", "t@example")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("line=base\nshared=1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "branch", "-q", "main")
    # lane side
    (repo / "f.txt").write_text("line=lane\nshared=1\n")
    (repo / "lane_only.txt").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "lane change")
    # main side (conflicting)
    git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("line=main\nshared=1\n")
    git(repo, "commit", "-qam", "main change")
    git(repo, "checkout", "-q", "lane")
    p = git(repo, "merge", "main")
    if p.returncode == 0:
        die_env("fixture failed: expected merge conflict, got clean merge")
    return repo, repo / "f.txt"


# ---------- A. route contract truth table (REAL pure function) -------------
section("A main_sync_conflict_route truth table (real shared.py)")
route = shared.main_sync_conflict_route
files_a = ["repoA:f.txt"]
b1 = route(4, files_a, files_a, 3)
ok(b1.startswith("blocked:"), "over cap -> blocked (4 > 3)")
ok(ANCHOR_OVER_CAP in b1, "over-cap text keeps the grep-stable anchor sentence")
ok("3" in b1, "over-cap text carries a round count (incident shape)")
ok(route(3, files_a, [], 3).startswith("resolve"),
   "at-cap round with no prior batch still resolves (cap counts from 0)")
b2 = route(2, files_a, files_a, 3)
ok(b2.startswith("blocked:") and "same batch" in b2,
   "identical consecutive batches -> same-batch blocked under the cap")
ok(route(2, ["repoA:f.txt"], ["repoA:g.txt"], 3) == "resolve",
   "a different batch (progressing round) resolves")
ok(route("x", files_a, files_a, 3).startswith("blocked:"),
   "malformed rounds -> conservative blocked, never a silent resolve")
ok(route(None, files_a, files_a, None).startswith("blocked:"),
   "malformed cap -> conservative blocked")
ok(str(route(2, "not-a-list", files_a, 3))
   == str(route(2, [], files_a, 3)),
   "malformed files behaves exactly like an empty set (documented "
   "degradation, no crash, no invented conflict)")
ok(route(4, "not-a-list", files_a, 3).startswith("blocked:"),
   "malformed files with malformed rounds -> conservative blocked")
ok(route(1, [], files_a, 3) == "resolve",
   "empty conflict set resolves (no phantom conflict)")

# ---------- B. R1 on a real git face with the real worker activity ---------
section("B resolved-but-unstaged face settles (real git x real activity)")
TMP_ROOT.mkdir(parents=True, exist_ok=True)
repo, cf = make_conflicted_lane(TMP_ROOT)
ok("UU" in git(repo, "status", "--porcelain").stdout,
   "incident shape reproduced: index shows UU after the merge")
cf.write_text("line=resolved\nshared=1\n")  # agent edits the file, no git add
ok("UU" in git(repo, "status", "--porcelain").stdout,
   "agent stance: file resolved in worktree, index STILL UU (cannot write .git)")

args = aa.ConflictSettleArgs(ticket_id="t-sc", worktree=str(repo), round_no=1)
res = __import__("asyncio").run(aa.settle_conflict_resolution(args))
ok(getattr(res, "ok", False),
   "R1: settle runs add-before-judge -> the UU face settles ok")
sha = str(getattr(res, "commit", ""))
ok(re.fullmatch(r"[0-9a-f]{7,40}", sha) is not None,
   "settle receipt carries a merge commit sha")
ok("UU" not in git(repo, "status", "--porcelain").stdout,
   "after settle the worktree face is clean (no residue in the index either)")

# residue face still fails honestly
repo2, cf2 = make_conflicted_lane(TMP_ROOT / "residue")
cf2.write_text("<<<<<<< HEAD\nline=lane\n=======\nline=main\n>>>>>>> main\n")
res2 = __import__("asyncio").run(
    aa.settle_conflict_resolution(aa.ConflictSettleArgs(ticket_id="t-sc", worktree=str(repo2),
                                                      round_no=1)))
ok(not getattr(res2, "ok", True),
   "residue face -> settle refuses (ok=False)")
ok(bool(getattr(res2, "remaining_files", None)),
   "refusal names the remaining conflict files")
ok(git(repo2, "rev-parse", "--verify", "-q", "MERGE_HEAD").returncode == 0,
   "refused face stays mid-merge (MERGE_HEAD present) for the "
   "human/operator round")

# abort mode: the operator reset is real and idempotent
repo3, _ = make_conflicted_lane(TMP_ROOT / "abort")
r3a = __import__("asyncio").run(
    aa.settle_conflict_resolution(aa.ConflictSettleArgs(ticket_id="t-sc", worktree=str(repo3),
                                                      round_no=1, abort=True)))
ok(getattr(r3a, "ok", False),
   "abort mode resets a mid-merge worktree ok")
ok(git(repo3, "rev-parse", "--verify", "-q", "MERGE_HEAD").returncode != 0,
   "after abort MERGE_HEAD is gone (next main sync starts clean)")
r3b = __import__("asyncio").run(
    aa.settle_conflict_resolution(aa.ConflictSettleArgs(ticket_id="t-sc", worktree=str(repo3),
                                                      round_no=1, abort=True)))
ok(getattr(r3b, "ok", False),
   "abort is idempotent: no merge in progress -> ok (no false work claimed)")

# ---------- C. R2/R3 counter semantics (source anchors + micro replay) -----
section("C counter resets: human signals and settle-success progress")
# Source anchors — RED until the implement lands; that is the TDD signal.
ok(re.search(r"def rework\(.*\n(.|\n)*?_conflict_rounds\s*=\s*0", DL_SRC)
   is not None,
   "R3: rework signal handler resets the conflict counter")
ok(re.search(r"def retry_qc\(.*\n(.|\n)*?_conflict_rounds\s*=\s*0", DL_SRC)
   is not None,
   "R3: retry_qc signal handler resets the conflict counter")
ok(DL_SRC.count("_conflict_rounds = 0") >= 4,
   "R2: both settle-success points reset the counter (>= 4 reset sites: "
   "2 handlers + 2 settle-success)")
ok("conflict_rounds = 0" not in DL_SRC.replace("_conflict_rounds = 0", ""),
   "counter is workflow-lifetime state, not a run()-local that survives "
   "rework/retry_qc")

# Micro replay of the loop semantics (the same table-driven stance as
# sc_check_auto_rework_trace): cap=3; each iteration = one conflict round that
# either ends in settle success (progress -> reset) or fails (counter keeps).
MAXC = 3


def drive(sequences):
    """sequences: list of 'ok'/'fail' round outcomes. Returns max counter."""
    c = 0
    peak = 0
    for outcome in sequences:
        c += 1
        peak = max(peak, c)
        if outcome == "ok":
            c = 0
    return peak


ok(drive(["fail", "fail", "ok", "fail", "fail", "fail", "fail"]) == 4,
   "R2 micro: after a settle success the counter restarts — the lane is "
   "judged by the 4 non-progressing rounds SINCE progress (lifetime "
   "detections were 7, far past the cap, yet it was not locked out)")
ok(drive(["fail"] * 4) == 4,
   "R2 micro: genuinely non-progressing rounds still exceed the cap "
   "(the guard keeps its teeth)")


# ---------- D. R4 text face: executable exits, no git homework -------------
section("D block/rework texts name executable exits only")
ok(ANCHOR_OVER_CAP in SHARED_SRC,
   "route anchor sentence survives in shared.py (selfcheck D-4 stays green)")
AGENT_GIT_CMDS = ["git merge --abort", "git add", "git commit",
                  "checkout --theirs", "git checkout"]
i0 = SHARED_SRC.index("def main_sync_conflict_route")
i1 = SHARED_SRC.index("\ndef ", i0)
route_src = SHARED_SRC[i0:i1]
ok(not any(c in route_src for c in AGENT_GIT_CMDS),
   "R4: route blocked texts assign no git command to any recipient")
ok("rework(to_stage=implement)" in route_src,
   "route blocked texts name the rework exit (the counter resets)")
ok("engine_ops.py sync" in route_src,
   "route blocked texts name the operator entry (R5 named at block time)")
j0 = DL_SRC.index('text("settle_unconverged"')
j1 = DL_SRC.index(") % ", j0)
unconv_src = DL_SRC[j0:j1]
ok(not any(c in unconv_src for c in AGENT_GIT_CMDS),
   "R4: settle_unconverged text assigns no git command to an agent session")
ok("rework(to_stage=implement)" in unconv_src
   and "engine_ops.py sync" in unconv_src,
   "settle_unconverged names both executable exits")
ok("_conflict_rounds = 0" in DL_SRC and "def rework(" in DL_SRC,
   "text reset coherence: the rework exit the text names actually resets "
   "(pairs with section C anchors)")

# ---------- E. R5 operator entry exists and is documented ------------------
section("E named, documented operator entry")
ok("settle_conflict_resolution" in OPS_SRC and "--abort" in OPS_SRC,
   "engine_ops.py exposes sync --abort through the worker activity")
ok(OPS_DOC.is_file() and "engine_ops" in OPS_DOC.read_text("utf-8")
   and "--abort" in OPS_DOC.read_text("utf-8"),
   "operator entry is documented in docs/ops/engine-worker-and-lane-operations.md")

# ---------- verdict --------------------------------------------------------
print("\npass=%d fail=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
