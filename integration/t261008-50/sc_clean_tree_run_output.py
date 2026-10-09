#!/usr/bin/env python3
"""Clean-tree contract for scenario run output (t261008-50, grey-box L3).

User-visible contract under test: a scenario run regenerates evidence into
integration/<ticket>/{shots,out,evidence}/, and that must never turn
`git status --porcelain` dirty on main (261008 incident: tracked run output
blocked every other lane's merge gate). The two hand-preserved carrier dirs
(integration/t261004-25/evidence, integration/t261004-28/evidence) are
deliverables, not run output, and must stay tracked and not ignored.

Exit codes follow the three-state protocol: 0 = pass, 1 = fail (product red),
2 = env fail. Offline seconds, zero docker, never touches 3099. Net-zero side
effect: every file this scenario creates is removed before exit.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CARRIERS = ("integration/t261004-25/evidence", "integration/t261004-28/evidence")

failures = []


def fail(case, detail):
    failures.append("%s: %s" % (case, detail))
    print("FAIL %s: %s" % (case, detail))


def git(args):
    return subprocess.run(["git", "-C", str(REPO)] + args,
                          capture_output=True, text=True)


def check_ignored(path):
    """True when git names an ignore rule for path (negation counts as a hit)."""
    r = git(["check-ignore", "-v", "--", path])
    return r.returncode == 0 and r.stdout.strip() != ""


def porcelain():
    return [l for l in git(["status", "--porcelain"]).stdout.splitlines() if l.strip()]


def main():
    if shutil.which("git") is None:
        print("ENV_FAIL: git is not on PATH; the clean-tree contract is unjudgeable")
        return 2
    r = git(["rev-parse", "--show-toplevel"])
    if r.returncode != 0:
        print("ENV_FAIL: %s is not inside a git work tree (%s)" % (REPO, r.stderr.strip()))
        return 2

    # A. Simulated run output: fresh files under the ticket's real run-output
    #    dirs integration/t261008-50/{shots,out,evidence}/ (png, non-png stray,
    #    name with a space) must be ignored (never appear in porcelain).
    out_root = REPO / "integration" / "t261008-50"
    probes = [
        "shots/face-a.png",
        "shots/notes.txt",
        "out/step one.log",
        "evidence/face-b.png",
    ]
    pre_existing = {d: (out_root / d).is_dir() for d in ("shots", "out", "evidence")}
    created = []
    try:
        for rel in probes:
            p = out_root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"probe\n")
            created.append(p)
            if not check_ignored(str(p.relative_to(REPO))):
                fail("A", "fresh run output not ignored: %s" % rel)
        dirty = [l for l in porcelain()
                 if any(("/%s/" % d) in l for d in pre_existing)]
        if dirty:
            fail("A", "porcelain dirty after simulated run output: %r" % dirty)
        else:
            print("pass A: simulated run output ignored, porcelain clean (%d probes)" % len(probes))

        # B. Carrier carve-out exercised, not assumed: carrier files stay
        #    tracked AND are not reported as ignored (the ! negation fires).
        for carrier in CARRIERS:
            cdir = REPO / carrier
            if not cdir.is_dir():
                fail("B", "carrier dir missing: %s" % carrier)
                continue
            listed = git(["ls-files", "--", carrier]).stdout.split()
            if not listed:
                fail("B", "carrier has no tracked files: %s" % carrier)
            for name in listed:
                if check_ignored(name):
                    fail("B", "tracked carrier file reported as ignored: %s" % name)
            if listed:
                print("pass B: carrier tracked and not ignored: %s (%d files)"
                      % (carrier, len(listed)))
    finally:
        # Net-zero side effect: remove the probe files, then remove each output
        # dir only if this scenario created it (pre-existing dirs are left as
        # found). No git state was touched, so plain removal restores the tree.
        for p in created:
            p.unlink(missing_ok=True)
        for name, existed in pre_existing.items():
            if not existed:
                shutil.rmtree(out_root / name, ignore_errors=True)

    # C. Rule-drift guard on the public face: the .gitignore block must still
    #    carry the three output-dir rules and the two carrier negations. A
    #    removed rule turns red with the missing line named.
    gi = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    required = [
        "integration/*/shots/",
        "integration/*/out/",
        "integration/*/evidence/*",
        "!integration/t261004-25/evidence/*",
        "!integration/t261004-28/evidence/*",
    ]
    c_failures_before = len([f for f in failures if f.startswith("C")])
    for line in required:
        if line not in gi:
            fail("C", ".gitignore missing required rule: %s" % line)
    if len([f for f in failures if f.startswith("C")]) == c_failures_before:
        print("pass C: .gitignore block intact (%d rules)" % len(required))

    if failures:
        print("SUMMARY: %d failure(s)" % len(failures))
        return 1
    print("SUMMARY pass=3 fail=0 env_fail=0")
    return 0


if __name__ == "__main__":
    os.chdir(REPO)
    sys.exit(main())
