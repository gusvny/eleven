# -*- coding: utf-8 -*-
"""L3 integration scenario, ticket t261026-35.

Intent: the suite python leg resolves through ONE rule and names its choice
(ticket t261026-35, integration finding 261026: registered scenarios whose
target script imports an engine module were launched with the system python3
and ENV_FAILed every round with "No module named temporalio"). The
user-perceivable contract of integration/py_interp.sh:
  1. SANDBAR_POC_PYTHON, when set to an executable file, is honored verbatim
     (the t261011-18 hand-over seam).
  2. Otherwise the tree under test's server/engine/.venv/bin/python wins
     (cwd-relative, executable check).
  3. Otherwise the main checkout venv wins, resolved through the git common
     directory -- reachable from a worktree lane without touching the real
     .git.
  4. Otherwise plain python3.
  Every launch NAMES the chosen interpreter on stderr. A set-but-unusable
  pointer is never silently executed: its path is named on stderr.
  5. End to end: an engine-importing probe (temporalio via the server/engine
     path insert -- the exact shape of the two chronically ENV_FAIL
     scenarios) runs GREEN under the launcher's choice from the repo root,
     and the same probe under the bare system python3 fails (the control
     that proves the journey is real, not vacuous).

Grey-box L3: the REAL launcher script driven as a subprocess over real git
fixture trees (a fixture main repo + a git worktree of it -- nothing under
the real .git is written), offline seconds, zero docker/Temporal/browser,
never touches 3099/7233. Pre-implement tree red (py_interp.sh missing) =
the named TDD signal; green required at the integration gate.

Exit codes: 0 = PASS, 1 = FAIL (named), 2 = ENV_FAIL.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
PY_INTERP = INTEG / "py_interp.sh"
ENGINE = REPO / "server" / "engine"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (": " + detail if detail else ""))


def git(*args: str, cwd: Path) -> bool:
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def chosen_from(stderr: str, cwd: Path) -> str:
    """Parse the name line and resolve it against the run cwd.

    The contract is 'names the chosen interpreter on stderr in one line'
    (py_interp: interpreter=<path>); the path may be cwd-relative, so the
    comparison happens on the absolute resolution, never on the raw text.
    """
    for line in stderr.splitlines():
        if line.startswith("py_interp: interpreter="):
            p = line.split("=", 1)[1].strip()
            return os.path.realpath(p if os.path.isabs(p) else cwd / p)
    return ""


def run_interp(cwd: Path, probe: Path, extra_env: dict | None = None):
    env = dict(os.environ)
    env.pop("SANDBAR_POC_PYTHON", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["sh", str(PY_INTERP), str(probe)], cwd=str(cwd),
                          env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)


def make_stub_venv(root: Path, token: str) -> Path:
    py = root / "server" / "engine" / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\necho %s\n" % token)
    py.chmod(0o755)
    return py


def git_tree(path: Path) -> Path:
    path.mkdir(parents=True)
    git("init", "-q", ".", cwd=path)
    (path / "seed.txt").write_text("seed\n")
    git("add", "-A", cwd=path)
    git("-c", "user.email=f@x", "-c", "user.name=f", "commit", "-qm", "init",
        cwd=path)
    return path


def main() -> int:
    if not PY_INTERP.exists():
        # Named FAIL, not ENV_FAIL: the launcher is a deliverable of this
        # ticket, its absence is the pre-implement TDD red.
        check("launcher present", False,
              "integration/py_interp.sh missing (pre-implement tree red; "
              "green required at the integration gate)")
        print("FAIL summary: %d red" % len(FAILS))
        return 1
    if shutil.which("git") is None:
        print("ENV_FAIL: git unavailable, fixture trees cannot be built")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="t26102635-journey-"))
    probe = tmp / "probe_ok.py"
    probe.write_text("print('PROBE-OK')\n")

    # Fixture world: a main repo whose venv stub exists, plus a worktree of
    # it that carries NO venv of its own (the lane-worktree shape).
    fmain = git_tree(tmp / "fmain")
    main_stub = make_stub_venv(fmain, "FMAIN-VENV-STUB")
    git("worktree", "add", "-q", str(tmp / "fwt"), cwd=fmain)
    fwt = tmp / "fwt"

    # A: the tree under test's own venv wins over the main-checkout tier.
    own = git_tree(tmp / "fown")
    own_stub = make_stub_venv(own, "OWN-VENV-STUB")
    r = run_interp(own, probe)
    check("A tree-under-test venv chosen and named",
          r.returncode == 0 and r.stdout.strip() == "OWN-VENV-STUB"
          and chosen_from(r.stderr, own) == os.path.realpath(own_stub),
          "rc=%s stderr=%r stdout=%r" % (r.returncode, r.stderr[-300:], r.stdout[-100:]))

    # B: no cwd venv -> the main-checkout venv through the git common dir.
    r = run_interp(fwt, probe)
    check("B main-checkout venv chosen from a worktree and named",
          r.returncode == 0 and r.stdout.strip() == "FMAIN-VENV-STUB"
          and chosen_from(r.stderr, fwt) == os.path.realpath(main_stub),
          "rc=%s stderr=%r stdout=%r" % (r.returncode, r.stderr[-300:], r.stdout[-100:]))

    # C: env seam honored verbatim when usable ...
    env_stub = tmp / "env_pointer.py"
    env_stub.write_text("#!/bin/sh\necho ENV-POINTER-STUB\n")
    env_stub.chmod(0o755)
    r = run_interp(fwt, probe, {"SANDBAR_POC_PYTHON": str(env_stub)})
    check("C1 SANDBAR_POC_PYTHON honored verbatim and named",
          r.returncode == 0 and r.stdout.strip() == "ENV-POINTER-STUB"
          and chosen_from(r.stderr, fwt) == os.path.realpath(env_stub),
          "rc=%s stderr=%r stdout=%r" % (r.returncode, r.stderr[-300:], r.stdout[-100:]))
    # ... and named, never silently executed, when unusable. A refusal
    # (nonzero exit) is an acceptable named outcome; a silent fall-through
    # without naming the rejected pointer is not.
    bad = str(tmp / "no-such-pointer")
    r = run_interp(fwt, probe, {"SANDBAR_POC_PYTHON": bad})
    fell_through = (r.returncode == 0
                    and chosen_from(r.stderr, fwt) == os.path.realpath(main_stub))
    refused = r.returncode != 0
    check("C2 unusable pointer named on stderr, never silently used",
          bad in r.stderr and (fell_through or refused),
          "rc=%s stderr=%r" % (r.returncode, r.stderr[-300:]))

    # D: nothing anywhere -> plain python3, named.
    bare = git_tree(tmp / "fbare")
    r = run_interp(bare, probe)
    dline = next((l.split("=", 1)[1].strip() for l in r.stderr.splitlines()
                  if l.startswith("py_interp: interpreter=")), "")
    check("D bare python3 fallback named",
          dline == "python3",
          "rc=%s stderr=%r" % (r.returncode, r.stderr[-300:]))

    # E: the real journey from the repo root -- an engine-importing probe
    # (the chronic ENV_FAIL shape) runs green under the launcher's choice;
    # the same probe under the bare system python3 fails.
    imp = tmp / "probe_engine_import.py"
    imp.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import temporalio\n"
        "print('IMPORT-OK')\n" % str(ENGINE)
    )
    r = run_interp(REPO, imp)
    check("E1 engine-import probe green under the launcher from the repo root",
          r.returncode == 0 and "IMPORT-OK" in r.stdout,
          "rc=%s stderr=%r stdout=%r" % (r.returncode, r.stderr[-300:], r.stdout[-100:]))
    rc = subprocess.run([sys.executable, str(imp)], cwd=str(REPO),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True)
    check("E2 control: same probe red under the bare system python3",
          rc.returncode != 0,
          "rc=%s stderr=%r (system python3 unexpectedly has temporalio; "
          "the control leg is vacuous)" % (rc.returncode, rc.stderr[-200:]))

    shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print("FAIL summary: %d red" % len(FAILS))
        return 1
    print("PASS summary: interp resolution journey green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
