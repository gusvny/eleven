#!/usr/bin/env python3
"""sc_t261009_01_clean_checkout_shared_faces.py -- t261009-01 acceptance 1.

Contract under test (user-visible): the three shared scenarios of closed
tickets (t260907-11-wb-anchor-faces, t260911-01-multirepo-diff-faces,
t260907-01-smoke-lane-green) are GREEN from a CLEAN CHECKOUT of the tracked
tree. They must not depend on untracked local state that only the main
working root happens to hold (ticket t261009-01 headline defect: every lane
gate carried their reds while the main root stayed green).

Grey-box L3, bounded, offline: one local clone of THIS repo at HEAD (a clone
carries tracked state only, by construction), then each of the three names is
re-run inside the clone through the runner's fail-closed targeted entry
(`--only`, t260924-09 contract). Assertions bind to the runner's public exit
contract (exit 0, no FAIL line naming the entry, INTEG_SUMMARY line present),
never to scenario internals. Harness self-check: the same entry run with a
bogus name must exit 2 without running anything -- proves the probe channel
is live and fail-closed, not silently green.

Three-state exit contract: FAIL>0 -> exit 1; environment missing (git/node
absent, clone fails) -> ENV_FAIL exit 2; else exit 0.
Pre-implement red is the expected TDD signal; must be green at
arbitrate/merge (the fixes are part of this ticket's tree).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

SHARED_NAMES = [
    "t260907-11-wb-anchor-faces",
    "t260911-01-multirepo-diff-faces",
    "t260907-01-smoke-lane-green",
]

passed = 0
failed = 0
env_fail = 0


def ok(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


def env_down(label):
    global env_fail
    env_fail += 1
    print(f"  ENV_FAIL {label}")


def section(t):
    print(f"\n== {t}")


def sh(cmd, cwd, timeout=600):
    return subprocess.run(
        cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout
    )


def main():
    repo = sh("git rev-parse --show-toplevel", os.getcwd())
    if repo.returncode != 0 or not shutil.which("git"):
        env_down("git unavailable / not a repo")
        return 2
    if not shutil.which("node"):
        env_down("node missing (shared scenarios are node/python entries)")
        return 2
    repo_root = repo.stdout.strip()
    head = sh("git rev-parse HEAD", repo_root)
    if head.returncode != 0:
        env_down("HEAD unresolvable")
        return 2

    tmp = tempfile.mkdtemp(prefix="t261009-01-clean-clone-")
    try:
        section("clone the tracked tree at HEAD (untracked state excluded by construction)")
        clone_dir = os.path.join(tmp, "clone")
        cl = sh(f'git clone --no-hardlinks --quiet "{repo_root}" "{clone_dir}"', tmp, timeout=900)
        ok(cl.returncode == 0, "local clone of the repo succeeds (clone fail = ENV)")
        if cl.returncode != 0:
            env_down(f"clone failed: {cl.stderr[-200:]}")
            return 2
        dirty = sh("git status --porcelain", clone_dir)
        ok(dirty.returncode == 0 and dirty.stdout.strip() == "",
           "clone worktree is clean (no inherited local state)")

        runner = "python3 integration/run_scenarios.py"
        section("harness self-check: the targeted entry is fail-closed")
        bogus = sh(f"{runner} --only no-such-scenario-zz", clone_dir, timeout=120)
        ok(bogus.returncode == 2, "bogus name exits 2 without running (t260924-09 fail-closed)")

        section("the three shared names are green from the clean clone")
        for name in SHARED_NAMES:
            r = sh(f"{runner} --only {name}", clone_dir, timeout=1200)
            fail_line = re.search(rf"^\s*(FAIL|ENV_FAIL)\b.*{re.escape(name)}", r.stdout, re.M)
            ok(
                r.returncode == 0 and fail_line is None and "INTEG_SUMMARY" in r.stdout,
                f"{name} green from clean clone (exit 0, no red line, summary present)",
            )
            if r.returncode != 0:
                tail = (r.stdout + r.stderr)[-400:]
                print(f"    [probe tail] {tail}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nSUMMARY pass={passed} fail={failed} env_fail={env_fail} na=0")
    if failed > 0:
        return 1
    if env_fail > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
