#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261016-11 scenario 1: a merge_check carrier case never writes the tree it
runs in (grey-box L3, offline seconds, stdlib + the existing offline t18
harness, zero docker/Temporal/browser, never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
ticket t261016-11, host order 261016 requirement (1): "a case that drives the
real merge_check face must run against a FIXTURE tree; it must never write to
the tree under test." Measured incident: round-20261016T020002Z, commit
bb73e620 authored INSIDE the round's own clone by the t18 carrier t03, which
passed worktree=str(root) to the real merge_check activity; the foreign
repair deleted 1160 lines of landed line content from the tree under test and
every later case in that round judged a broken tree.

This entry is the SYSTEM-level regression the spec asks for: it runs the REAL
carrier harness (integration/t260901-18/sc_check.sh, the host-named carrier
entry) from the real tree, and asserts the tree is byte-identical afterwards
(HEAD unmoved, status porcelain empty on both sides) - no commit, no
deletion - while the harness itself still reports its carrier legs PASS (the
fixture-tree path proves the face still works). Writer receipts are not
evidence: the tree is read back from git on the reader side, before and
after.

- A the carriers leave the tree untouched: HEAD sha and `git status
  --porcelain` output are identical before and after the harness run, and the
  harness exits 0 with PASS lines for t03-mergecheck-wiring,
  t04-mergecheck-failclosed and t05-two-sided-baseline.
- B the control is real: if the tree is mutated (the pre-fix shape), A fails
  by diffing the two snapshots - the failure names what changed, so a red
  here is attributable and never "not checked".

Intent split (no intent-level duplication): the harness's internal payload
assertions (merge-base, write-set passthrough, reason codes) belong to the
t18 carrier legs themselves; the pure line-not-lane and importer-refusal
judgments belong to the sibling t261016-11 scenarios and to developer L1;
this entry uniquely owns "the carrier run, end to end, writes nothing into
the tree it runs in".

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). git or bash unavailable, or the harness entry missing = ENV_FAIL.
Pre-fix tree red = the named TDD signal; green required at the integration
gate / merge.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "t260901-18"))
from t18lib import tree_snapshot, assert_tree_untouched  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "integration" / "t260901-18" / "sc_check.sh"
CARRIER_LEGS = (
    "t03-mergecheck-wiring",
    "t04-mergecheck-failclosed",
    "t05-two-sided-baseline",
)
# t261019 ruling (option a): the carrier harness must leave the LANDED LINE
# content byte-identical too — these paths are line-tip content this ticket
# does not own; any mutation here is the self-write defect recurring.
PROTECTED_PATHS = (
    "integration/t261016-09",
    "server/plugins",
)
FAILS = []


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=600, **kw)  # SANCTIONED-WAIT: a ceiling on the offline carrier harness run, no condition is waited on
    except OSError as e:
        env_fail("cannot spawn %s: %s" % (cmd[0], e))
    except subprocess.TimeoutExpired:
        env_fail("%s exceeded 600s budget" % " ".join(cmd[:3]))


def snapshot(tag):
    """t260901-18's canonical tree_snapshot face (HEAD sha + porcelain)."""
    return tree_snapshot(REPO)


def check(name, cond, detail=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


def main():
    if not HARNESS.is_file():
        env_fail("carrier harness missing: %s" % HARNESS)
    run(["git", "--version"])
    run(["bash", "-c", "true"])

    before = snapshot("before")
    p = run(["bash", str(HARNESS), "all"], cwd=str(REPO))
    after = snapshot("after")

    check("carrier-harness-green",
          p.returncode == 0,
          "rc=%d tail=%s" % (p.returncode, (p.stderr or p.stdout)[-300:]))
    for leg in CARRIER_LEGS:
        check("carrier-leg-pass-%s" % leg,
              "PASS %s" % leg in p.stdout,
              "missing PASS line for %s" % leg)
    check("tree-untouched-by-carriers", before == after,
          "tree changed: %s" % _diff(before, after))
    assert_tree_untouched(before, after, "carrier-harness")
    # path-scoped application of the same snapshot face (tree_snapshot is
    # whole-tree; the protected paths are line-tip content judged per path)
    for path in PROTECTED_PATHS:
        st = run(["git", "status", "--porcelain", "--", path], cwd=str(REPO))
        check("protected-path-untouched-%s" % path.replace("/", "-"),
              st.returncode == 0 and not (st.stdout or "").strip(),
              (st.stderr or st.stdout or "")[:200])

    if FAILS:
        print("FAIL t261016-11-carrier-no-self-write (%d)" % len(FAILS))
        sys.exit(1)
    print("PASS t261016-11-carrier-no-self-write")
    sys.exit(0)


def _diff(before, after):
    b = before.splitlines()
    a = after.splitlines()
    out = []
    for line in a:
        if line not in b:
            out.append("+%s" % line)
    for line in b:
        if line not in a:
            out.append("-%s" % line)
    return " | ".join(out[:10])


if __name__ == "__main__":
    main()
