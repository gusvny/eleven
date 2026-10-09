#!/usr/bin/env python3
"""sc_t26100917_moved_main_not_human.py — a main ref that advanced during a
lane's main-sync must NOT stop the ticket for a human (t261009-17,
KI-01M4FKAWY0EP59PY0V0QZWWGV5).

Run directly: python3 integration/t261009-17/sc_t26100917_moved_main_not_human.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches 3099.

Incident (KI-01M4FKAWY0EP59PY0V0QZWWGV5): seven innocent tickets in one afternoon
stopped at main-sync with "conflict resolution round 1 did not converge
(worker-side commit verification failed)" while all four measured facts said the
merge commit was already on disk — MERGE_HEAD absent, unmerged entries 0, dirty
files 0, marker residue none — and the only unmet measurement was "main is NOT an
ancestor of HEAD", because the convergence check compares the LIVE main ref while
the lane merged main@X and an integration-session commit later advanced main to Y.
Each stop wasted a human send-back on a fact no human can act on; worse, the
integration role's own ledger commits (which must land immediately) were the very
trigger — "the more diligent the gatekeeper, the more victims".

This scenario owns the user-perceivable contract no developer unit test owns:
a lane whose merge commit is already on disk must settle GREEN against the
revision it actually merged, even after main moved; and the shapes that DO stop
must be shapes a human can act on, with the measured facts named in the copy.

Judged through the public activity seam (settle_conflict_resolution receipt:
ok / already_settled / error), NOT through internal helper names — a
contract-preserving refactor (e.g. judging against a recorded merge base
instead of the merge commit's second parent) must not break this.

Subcases:

  A  moved-main converges — the exact incident shape rebuilt on a real tmp git
     repo: lane HEAD is a merge commit whose second parent is main@X, main has
     since advanced to Y, tree clean, no unmerged entries, no residue. The
     settle receipt must be ok=True already_settled=True (no human stop). This
     is the KI regression case; on the pre-implementation tree it is red (TDD
     signal), green required at the integration gate / merge.

  B  blocked copy names the measured facts — a shape that legitimately stops
     (a real unresolved merge) must carry WHICH measurement failed and what is
     true (ticket requirement 3, the "report errors precisely" lesson), never a
     bare "verification failed" that reads as if the lane did something wrong.

  C  human-actionable shapes still stop — unmerged entries present, or marker
     residue in the changed face: ok=False, never already_settled. The fix must
     not widen the green face past the clean shape.

  D  stray merged base does not fake-green — a lane whose merge commit's second
     parent is NOT part of main history (it merged a stray commit) must not be
     reported as settled: the merged-base shortcut is only valid when the base
     really belongs to main.

Environment: git absent or the engine module unimportable = ENV_FAIL exit 2.
"""

from __future__ import annotations

import asyncio
import os
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
    root = tempfile.mkdtemp(prefix="sc_t26100917_")
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


def settle(repo, base_ref="main"):
    args = eng_shared.ConflictSettleArgs(ticket_id="t261009-17",
                                         worktree=repo,
                                         branch="lane",
                                         base_ref=base_ref,
                                         round_no=1)
    return asyncio.run(aa.settle_conflict_resolution(args))


# ---------- A. the exact incident shape: main advanced, lane already merged ----------
section("A moved main converges — incident shape KI-01M4FKAWY0EP59PY0V0QZWWGV5")
repo = build_repo()
try:
    commit(repo, "base.txt", "base\n", "base")
    base_sha = sh(repo, "rev-parse", "HEAD")
    # the lane lands its own work on a branch off the shared base
    sh(repo, "checkout", "-q", "-b", "lane", base_sha)
    commit(repo, "lanefile.txt", "lane\n", "lane work")
    # main advances to X (what the lane will merge in)
    sh(repo, "checkout", "-q", "main")
    commit(repo, "mainfile.txt", "x\n", "main advances to X")
    x_sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "lane")
    sh(repo, "merge", "-q", "--no-ff", "-m", "lane merges main@X", x_sha)
    parents = sh(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    ok(len(parents) >= 3, "lane HEAD is a merge commit with >=2 parents")
    ok(parents[-1] == x_sha, "merge commit's second parent IS main@X (fixture sanity)")
    # after the lane merged, an integration-session commit advances main to Y
    sh(repo, "checkout", "-q", "main")
    commit(repo, "ledger.txt", "ledger row\n", "integration ledger commit (Y)")
    y_sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "lane")
    ok(sh(repo, "rev-parse", "main") == y_sha, "live main is now Y (fixture sanity)")
    res = settle(repo)
    ok(res.ok, "A1 settle receipt ok=True after main moved X->Y (pre-implementation "
              "tree is red here: TDD signal, the incident itself)")
    ok(res.already_settled, "A2 receipt already_settled=True (no new round, no human stop)")
    # the KI's four measured facts really are the clean shape on this fixture
    ok(not os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD")),
       "A3 MERGE_HEAD absent (fixture matches the incident shape)")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- B. a legit stop names the measured facts ----------
section("B a shape that stops names WHICH measurement failed and what is true")
repo = build_repo()
try:
    commit(repo, "base.txt", "base\n", "base")
    sh(repo, "checkout", "-q", "-b", "lane")
    commit(repo, "shared.txt", "lane side\n", "lane edit")
    lane_sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "main")
    commit(repo, "shared.txt", "main side\n", "main edit")
    main_sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "lane")
    p = subprocess.run([GIT, "merge", "main"], cwd=repo, capture_output=True, text=True)
    ok(p.returncode != 0, "fixture merge genuinely conflicts (fixture sanity)")
    res = settle(repo)
    ok(not res.ok, "B1 a real unresolved merge is NOT settled (green face not widened)")
    ok(bool(res.remaining_files), "B2 the open merge names its unresolved files "
                                  "(the copy says WHAT is still unresolved)")
    # abort the open merge: now MERGE_HEAD is gone but the lane genuinely lacks
    # main@Y (no merge commit on disk, HEAD still differs) — the one "absent
    # merge commit" shape a human may be asked about, per ticket requirement (2)
    sh(repo, "merge", "--abort")
    res2 = settle(repo)
    ok(not res2.ok, "B3 absent merge commit + HEAD differs from main stops")
    ok("measured:" in (res2.error or "")
       and "unmerged entries:" in (res2.error or "")
       and "marker residue:" in (res2.error or ""),
       "B4 the stop copy names WHICH measurement failed and what is true "
       "(report errors precisely, ticket requirement 3)")
    ok(not res2.already_settled, "B5 already_settled stays False for this shape")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- C. human-actionable residue on an otherwise clean tree still stops ----------
section("C marker residue on an otherwise clean face still stops")
repo = build_repo()
try:
    commit(repo, "base.txt", "base\n", "base")
    x_sha = commit(repo, "f.txt", "x\n", "main@X")
    sh(repo, "checkout", "-q", "-b", "lane", "HEAD")
    commit(repo, "lanefile.txt", "lane\n", "lane work")
    sh(repo, "merge", "-q", "--no-ff", "-m", "merge main@X", x_sha)
    with open(os.path.join(repo, "lanefile.txt"), "a") as fh:
        fh.write("<<<<<<< HEAD\nstray marker\n>>>>>>> main\n")
    # commit the residue so the tree is CLEAN and the shape is exactly the
    # incident shape plus residue — only the residue measurement may stop it
    sh(repo, "add", "lanefile.txt")
    sh(repo, "commit", "-q", "-m", "residue committed (tree clean, shape dirty)")
    sh(repo, "checkout", "-q", "main")
    commit(repo, "ledger.txt", "ledger\n", "main moves to Y")
    sh(repo, "checkout", "-q", "lane")
    res = settle(repo)
    ok(not res.ok, "C1 residue present -> NOT settled even with main moved")
    ok(not res.already_settled, "C2 already_settled stays False for the residue shape")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- D. stray merged base must not fake-green ----------
section("D a merged base outside main history is not 'settled'")
repo = build_repo()
try:
    commit(repo, "base.txt", "base\n", "base")
    base_sha = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "-q", "-b", "stray", base_sha)
    stray_sha = commit(repo, "stray.txt", "stray\n", "stray commit, never on main")
    sh(repo, "checkout", "-q", "main")
    commit(repo, "mainfile.txt", "main\n", "main advances (lane does NOT merge this)")
    sh(repo, "checkout", "-q", "-b", "lane", base_sha)
    commit(repo, "lanefile.txt", "lane\n", "lane work")
    sh(repo, "merge", "-q", "--no-ff", "-m", "merge stray", stray_sha)
    sh(repo, "rev-parse", "main")
    ok(sh(repo, "rev-parse", "main") != stray_sha,
       "second parent is NOT in main history (fixture sanity)")
    res = settle(repo)
    ok(not res.already_settled,
       "D1 a lane that merged a non-main commit is NOT waved through as settled")
finally:
    shutil.rmtree(repo, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
sys.exit(1 if FAIL else 0)
