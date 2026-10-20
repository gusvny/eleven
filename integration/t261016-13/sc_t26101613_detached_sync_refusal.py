#!/usr/bin/env python3
"""sc_t26101613_detached_sync_refusal.py — a pre-gate main sync on a DETACHED
lane checkout must never report success while the branch stays behind
(ticket t261016-13).

Run directly: python3 integration/t261016-13/sc_t26101613_detached_sync_refusal.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, real tmp git fixtures, zero docker/Temporal/
browser, never touches 3099.

Incident (ticket t261016-13, lane t261014-04): the pre-gate main sync
(prepare_conflict_resolution, the engine's single "merge a ref into the lane"
implementation) merges main INTO THE WORKTREE. The lane worktree was DETACHED
(a state the engine itself produces: land_to_line pins the proven revision with
git checkout --detach), so the merge landed on the detached HEAD and NO branch
moved. merge_check then judged the STALE BRANCH: branch vs main = 24 files,
worktree vs main = 1 file — the gate painted FALSE out-of-write-set reds from
main's own newer commits and bounced the ticket three times. The receipt's
lane_head reported the worktree HEAD, so the face showed a clean sync all along.

User-perceivable contract owned by this scenario (nothing a developer unit test
owns): after ONE sync, either the branch the gate judges contains main, or the
sync REFUSES BY NAME — and the face never claims a clean sync while the branch
lags. Judged through the public activity receipt (ok / up_to_date / error) and
public git facts (branch ref, merge-base), never internal helper names.

Subcases:

  A  the incident shape — detached worktree, stale branch, main ahead: one
     sync must refuse ok=False carrying the verbatim sentence
     "lane checkout is detached - the branch would not advance", the branch
     ref stays byte-identical (zero writes), and the receipt is NOT a clean
     sync. Pre-implementation tree red (TDD signal); green at the gate.

  B  the fast-path hole — detached HEAD that already CONTAINS main while the
     branch points elsewhere: the is-ancestor fast path must NOT return a
     clean success; the same named refusal fires. Red pre-implementation.

  C  attached lanes keep today's behaviour — the same shape attached: sync
     ok, the branch ref advances to the merge commit and contains main
     (branch == worktree HEAD, the invariant restored), a second sync answers
     up_to_date=True (idempotent fast path, the KI-209 recovery consumer).

  D  malformed input — args.branch naming a nonexistent ref must be a named
     refusal (receipt ok=False, reason names the branch), never an exception;
     and the refusal never mutates the repo.

  E  family tripwire — prepare_conflict_resolution is still the ONLY engine
     site that merges a ref into a lane worktree (only-implementation
     discipline): a second unguarded sync site is how this family recurs.

Environment: git absent or the engine module unimportable = ENV_FAIL exit 2.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

GIT = shutil.which("git")
if GIT is None:
    print("ENV_FAIL: git binary not on PATH (fixture repos cannot be built)")
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

try:
    import agent_activities as aa
    import shared as eng_shared
except Exception as exc:  # engine module unimportable = environment red
    print("ENV_FAIL: server/engine agent_activities module unavailable (%s)" % exc)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

REFUSAL = "lane checkout is detached - the branch would not advance"

PASS = 0
FAIL = 0
NA = 0


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


def sh(repo, *argv):
    p = subprocess.run([GIT, *argv], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s failed in %s: %s" % (" ".join(argv), repo,
                                                        p.stderr.strip()[:200]))
    return p.stdout.strip()


def build_repo():
    root = tempfile.mkdtemp(prefix="sc_t26101613_")
    sh(root, "init", "-q", "-b", "main")
    sh(root, "config", "user.email", "sc@test.invalid")
    sh(root, "config", "user.name", "sc")
    return root


def commit(repo, fname, body, msg):
    with open(os.path.join(repo, fname), "w") as fh:
        fh.write(body)
    sh(repo, "add", fname)
    sh(repo, "commit", "-q", "-m", msg)
    return sh(repo, "rev-parse", "HEAD")


def sync(repo, branch="lane"):
    """One pre-gate main sync through the public activity seam."""
    args = eng_shared.ConflictPrepArgs(ticket_id="t261016-13",
                                       worktree=repo,
                                       branch=branch,
                                       base_ref="main")
    return asyncio.run(aa.prepare_conflict_resolution(args))


def detached_lane_with_stale_branch(n_main_commits=3):
    """The t261014-04 shape: a lane branch with own work, main N commits ahead,
    worktree checked out DETACHED at the lane's own tip."""
    repo = build_repo()
    commit(repo, "base.txt", "base\n", "base")
    base_sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "-b", "lane", base_sha)
    lane_sha = commit(repo, "lanefile.txt", "lane\n", "lane work")
    sh(repo, "checkout", "-q", "main")
    for i in range(n_main_commits):
        commit(repo, "main_%d.txt" % i, "main %d\n" % i, "main commit %d" % i)
    sh(repo, "checkout", "-q", "--detach", lane_sha)
    return repo, lane_sha


# ---------- A. the incident shape: detached sync must refuse by name ----------
section("A detached lane + sync once -> named refusal, branch untouched "
        "(the t261014-04 shape)")
repo, lane_sha = detached_lane_with_stale_branch()
try:
    ok(subprocess.run([GIT, "symbolic-ref", "-q", "HEAD"], cwd=repo,
                      capture_output=True).returncode != 0,
       "A0 fixture worktree is detached at the lane tip (fixture sanity)")
    ok(sh(repo, "rev-parse", "lane") == lane_sha,
       "A0 branch ref is the stale lane tip (fixture sanity)")
    res = sync(repo)
    ok(not res.ok, "A1 the sync REFUSES (ok=False) — the face never claims a "
                   "clean sync while the branch lags (red pre-implementation)")
    ok(REFUSAL in (res.error or ""),
       "A2 the refusal carries the verbatim sentence %r (got: %r)"
       % (REFUSAL, (res.error or "")[:160]))
    ok(sh(repo, "rev-parse", "lane") == lane_sha,
       "A3 the branch ref is byte-identical after the refusal (zero writes)")
    ok(not os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD")),
       "A4 no merge was opened (all-or-nothing refusal)")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- B. the fast-path hole: detached HEAD that already contains main ----------
section("B detached HEAD already contains main, branch behind -> still refused")
repo, lane_sha = detached_lane_with_stale_branch()
try:
    # advance main to the detached HEAD's ancestor direction is wrong; instead
    # make the DETACHED HEAD contain main: merge main into the detached HEAD,
    # leaving the branch untouched — exactly the incident's end state.
    sh(repo, "merge", "-q", "--no-edit", "main")
    ok(subprocess.run([GIT, "merge-base", "--is-ancestor", "main", "HEAD"],
                      cwd=repo, capture_output=True).returncode == 0,
       "B0 the detached HEAD contains main (fast path would fire)")
    ok(sh(repo, "rev-parse", "lane") == lane_sha,
       "B0 the branch ref did NOT move (the incident's silent outcome)")
    res = sync(repo)
    ok(not res.ok, "B1 the is-ancestor fast path does NOT answer a clean "
                   "success on a detached checkout (red pre-implementation)")
    ok(REFUSAL in (res.error or ""), "B2 the refusal is the same named sentence")
    ok(sh(repo, "rev-parse", "lane") == lane_sha,
       "B3 the branch ref still untouched")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- C. attached lanes keep today's behaviour ----------
section("C attached lane: sync advances the branch and stays idempotent")
repo, lane_sha = detached_lane_with_stale_branch()
try:
    sh(repo, "checkout", "-q", "-B", "lane", lane_sha)  # re-attach (the rescue)
    res = sync(repo)
    ok(res.ok, "C1 the attached lane syncs clean (today's behaviour kept)")
    ok(not res.up_to_date, "C2 the first sync is a real merge, not up_to_date")
    head = sh(repo, "rev-parse", "HEAD")
    branch = sh(repo, "rev-parse", "lane")
    ok(head == branch,
       "C3 the branch ref equals the worktree HEAD (the verified tree IS the "
       "merged tree — the invariant the ticket names)")
    ok(subprocess.run([GIT, "merge-base", "--is-ancestor", "main", "lane"],
                      cwd=repo, capture_output=True).returncode == 0,
       "C4 the branch contains main (false-red family dissolved reader-side)")
    res2 = sync(repo)
    ok(res2.ok and res2.up_to_date,
       "C5 a second sync answers up_to_date (idempotent fast path intact, "
       "the KI-209 recovery consumer)")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- D. malformed input: nonexistent branch ref ----------
section("D branch naming a nonexistent ref -> named refusal, no exception")
repo, lane_sha = detached_lane_with_stale_branch()
try:
    sh(repo, "checkout", "-q", "-B", "lane", lane_sha)  # attached, behind main
    try:
        res = sync(repo, branch="lane/does-not-exist")
        ok(not res.ok, "D1 the sync refuses (ok=False), never a fake green")
        ok("does-not-exist" in (res.error or ""),
           "D2 the refusal NAMES the unreadable branch (got: %r)"
           % (res.error or "")[:160])
    except Exception as exc:
        ok(False, "D1/D2 malformed branch input raised instead of a named "
                  "refusal: %r" % (exc,))
    ok(sh(repo, "rev-parse", "HEAD") == lane_sha,
       "D3 the repo is untouched by the refusal")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- E. family tripwire: one implementation owns the lane merge ----------
section("E prepare_conflict_resolution is still the only lane-merge site")
eng_path = os.path.join(REPO, "server", "engine", "agent_activities.py")
with open(eng_path, "r", encoding="utf-8") as fh:
    src = fh.read()
merge_sites = re.findall(r"_git\(\s*\[\s*\"merge\",\s*\"(--?[a-z-]+)\"", src)
known = {"--no-edit", "--abort", "--squash", "--quit"}
unknown = sorted(set(merge_sites) - known)
sync_merges = merge_sites.count("--no-edit")
ok(sync_merges == 1,
   "E1 exactly ONE sync merge into the lane worktree (found %d) — the "
   "only-implementation discipline; a second is how the false-red family "
   "recurs" % sync_merges)
ok(not unknown,
   "E2 every git-merge site in the engine activity module is a known shape "
   "%s (unknown: %s) — a NEW merge shape must be reviewed against the same "
   "branch guard" % (sorted(known), unknown or "none"))

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
sys.exit(1 if FAIL else 0)
