#!/usr/bin/env python3
"""t261009-12 Defect B — the lint verdict must be reproducible or name its condition.

Grey-box L3, real `integration/lint_tests.py` subprocess on the real tree, offline,
seconds, zero docker/browser, never touches 3099. Measured defect: two runs seconds
apart printed `LINT done: 0 error / 1 warn` and then `20 error` for nominally the
same inputs — the tool's judged input set is a function of live git state (the
`git ls-files -c -o` untracked set, per-consumer diff bases) while a busy fleet
mutates that state, and on any git read failure the target builder silently
degrades to a full rglob. The user acceptance: for identical inputs the verdict is
identical, and whenever the inputs are not stable the tool's own output names the
condition — two verdicts must never print for the same inputs without saying why.

  A  two consecutive runs on the untouched tree print byte-identical final
     `LINT done:` lines (reproducibility on identical inputs).
  B  fault injection — a PATH shim git that fails exactly `ls-files` (other git
     calls pass through to the real binary): the run must NAME the degraded
     input condition in its own output; a bare `LINT done: N error / M warn`
     with no condition named is the defect face.
  C  under the same shim, two runs again agree byte-for-byte (the named
     condition does not reintroduce run-to-run verdict drift).
  D  no residue: the shim lives in a temp dir removed in finally; the real tree
     is never written.

Pre-implement red on B/C is the expected TDD signal; arbitrate/merge must be
green. python/git absent = ENV_FAIL exit 2.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINT = os.path.join(REPO, "integration", "lint_tests.py")

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    tag = "PASS" if cond else "FAIL"
    print("%s %s%s" % (tag, name, (" — " + detail) if (detail and not cond) else ""))
    if not cond:
        FAILURES.append(name)


def run_lint(path_extra=None):
    env = dict(os.environ)
    if path_extra:
        env["PATH"] = path_extra + os.pathsep + env.get("PATH", "")
    p = subprocess.run([sys.executable, "-B", LINT], capture_output=True,
                       text=True, timeout=600, cwd=REPO, env=env)
    done = [ln for ln in (p.stdout or "").splitlines()
            if ln.startswith("LINT done:")]
    return p, (done[-1] if done else None)


def make_shim():
    """A git shim failing exactly `ls-files`; every other call execs the real git."""
    real = shutil.which("git")
    if not real:
        return None, None
    d = tempfile.mkdtemp(prefix="t26100912-gitshim-")
    shim = os.path.join(d, "git")
    with open(shim, "w") as f:
        f.write("#!/bin/sh\n"
                "case \" $* \" in *\\ ls-files\\ *)\n"
                "  echo \"git-shim: ls-files injected failure\" >&2; exit 1 ;;\n"
                "esac\n"
                "exec %s \"$@\"\n" % real)
    os.chmod(shim, 0o755)
    return d, shim


if not shutil.which("git") or not os.path.exists(LINT):
    print("ENV_FAIL: git or integration/lint_tests.py missing")
    sys.exit(2)

shim_dir = None
try:
    # ---- A: identical inputs -> identical verdict ----
    p1, done1 = run_lint()
    p2, done2 = run_lint()
    check("A1 run 1 prints a final verdict", done1 is not None, p1.stdout[-300:])
    check("A2 run 2 prints a final verdict", done2 is not None, p2.stdout[-300:])
    check("A3 two runs on the same tree agree byte-for-byte", done1 == done2,
          "%r vs %r" % (done1, done2))

    # ---- B/C: degraded git input must be named, and stay reproducible ----
    shim_dir, _ = make_shim()
    if not shim_dir:
        print("ENV_FAIL: cannot build git shim (real git missing)")
        sys.exit(2)
    ps1, ds1 = run_lint(shim_dir)
    ps2, ds2 = run_lint(shim_dir)
    out1 = ps1.stdout or ""
    named = ("unstable" in out1) or ("degraded" in out1) or ("ls-files" in out1
                                                             and "fail" in out1)
    check("B1 degraded input set is named in the tool's own output", bool(named),
          out1[-400:])
    check("B2 verdict line itself carries the condition",
          ds1 is not None and ("unstable" in ds1 or "degraded" in ds1), str(ds1))
    check("C1 runs under the same injected condition agree byte-for-byte",
          ds1 == ds2, "%r vs %r" % (ds1, ds2))
    check("D1 shim run leaves rc defined and output non-empty",
          isinstance(ps1.returncode, int) and out1 != "")
finally:
    if shim_dir:
        shutil.rmtree(shim_dir, ignore_errors=True)

print("t261009-12-lint-verdict-stable-or-named: %d checks, %d failed"
      % (CHECKS[0], len(FAILURES)))
sys.exit(1 if FAILURES else 0)
