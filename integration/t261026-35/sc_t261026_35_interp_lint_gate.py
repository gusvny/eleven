# -*- coding: utf-8 -*-
"""L3 integration scenario, ticket t261026-35.

Intent: the mechanical interpreter lint is wired into the REAL static gate
and is NOT vacuous (ticket t261026-35 spec point 3: a case proving the lint
catches an injected offender and the fixed registry passes). The public face
asserted is the gate command itself -- `python3 integration/lint_tests.py`
and its exit code / named output -- never an internal callable:
  A. The real tree is green: the seconds-fast static gate exits 0.
  B. Not vacuous: in a real `git clone --shared` of this tree (a full copy
     with a real .git, fully outside this worktree), an injected registry
     entry -- a bare `python3` cmd over a probe script that imports the
     engine module shared via the server/engine path insert, the exact
     finding-261026 shape -- turns the copied gate red, and the red NAMES
     the L29 rule and the offender.
  C. The fix shape passes: the same injected entry relaunched through
     `sh integration/py_interp.sh ...` is green again in the same copy.

Intent split: the in-memory injected-registry truth tables (offender red,
py_interp shape green, malformed cmd / missing script / syntax error /
scenario-local module shadowing an engine name all named, never silent) are
the developer L1 battery (test_lint_interp.py); THIS entry uniquely owns the
real-gate face -- the lint is reachable through the real gate command and
fires on a real registry in a real tree. Pre-implement tree red on B (no L29
rule yet, so the injected offender passes) = the named TDD signal; green
required at the integration gate.

Exit codes: 0 = PASS, 1 = FAIL (named), 2 = ENV_FAIL.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"

OFFENDER_ID = "t261026-35-lint-vacuity-offender"
PROBE_REL = "integration/t261026-35/sc_t261026_35_vacuity_probe.py"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (": " + detail if detail else ""))


def run_gate(cwd: Path):
    return subprocess.run([sys.executable, "integration/lint_tests.py"],
                          cwd=str(cwd), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)


def main() -> int:
    if shutil.which("git") is None:
        print("ENV_FAIL: git unavailable, the fixture clone cannot be built")
        return 2

    # A: the real tree's static gate is green.
    r = run_gate(REPO)
    check("A real-tree static gate green", r.returncode == 0,
          "rc=%s tail=%r" % (r.returncode, (r.stdout + r.stderr)[-400:]))

    # Fixture: a full clone of this tree (real .git, outside the worktree).
    tmp = Path(tempfile.mkdtemp(prefix="t26102635-lintgate-"))
    clone = tmp / "clone"
    if not subprocess.run(["git", "clone", "-q", "--shared", str(REPO),
                           str(clone)], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
        print("ENV_FAIL: git clone of the tree under test failed")
        return 2
    # The clone carries only COMMITTED state; the gate judges the landing
    # union, so mirror the working tree's integration/ (the face under test)
    # over the clone before injecting -- the same files the real gate sees.
    for item in INTEG.rglob("*"):
        if "__pycache__" in item.parts or ".sandbar" in item.parts:
            continue
        dst = clone / "integration" / item.relative_to(INTEG)
        if item.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            shutil.copy2(item, dst)

    # The engine-importing probe (the finding-261026 shape), written into
    # the clone at the registered path.
    probe = clone / PROBE_REL
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import shared  # the real engine module, found through the insert\n"
        "print('probe-ok')\n" % str(clone / "server" / "engine")
    )

    # Inject the offender entry + its anchor row into the clone only.
    reg = clone / "integration" / "run_scenarios.py"
    src = reg.read_text()
    entry = (
        '    ("%s",\n'
        '     "Lint vacuity control injected by sc_t261026_35_interp_lint_gate '
        '(ticket t261026-35): a bare-interpreter cmd over an engine-importing '
        'probe must be red under the L29 rule; green when relaunched through '
        'py_interp.sh. Not a real scenario - a probe.",\n'
        '     "python3 %s", "ro", "fast"),\n'
    ) % (OFFENDER_ID, PROBE_REL)
    marker = "SCENARIOS = [\n"
    if marker not in src:
        print("ENV_FAIL: clone registry has no SCENARIOS list head")
        return 2
    reg.write_text(src.replace(marker, marker + entry, 1))
    anchors_path = clone / "integration" / "test_anchors.json"
    anchors = json.loads(anchors_path.read_text())
    anchors["scenarios"][PROBE_REL] = {
        "anchor": "contract",
        "note": "t261026-35 L29 vacuity probe injected by the gate scenario",
        "sync_path": "",
    }

    anchors_path.write_text(json.dumps(anchors, indent=2, ensure_ascii=False) + "\n")

    # B: the injected offender turns the copied gate red, naming the rule
    # and the offender. Pre-implement (no L29 rule yet) this leg is RED --
    # the named TDD signal.
    r = run_gate(clone)
    out = r.stdout + r.stderr
    check("B injected offender red at the real gate, named L29 + offender id",
          r.returncode != 0 and "L29" in out and OFFENDER_ID in out,
          "rc=%s tail=%r" % (r.returncode, out[-400:]))

    # C: the fix shape (launch through py_interp.sh) is green again. The
    # launcher becomes a cmd token here, so its anchor row lands with it
    # (L16 coverage = cmd tokens; a dead entry would be a second, unrelated
    # red that would mask the L29 question in leg B).
    anchors = json.loads(anchors_path.read_text())
    anchors["scenarios"]["integration/py_interp.sh"] = {
        "anchor": "contract",
        "note": "t261026-35 launcher declared for the injected clone face",
        "sync_path": "",
    }
    anchors_path.write_text(json.dumps(anchors, indent=2, ensure_ascii=False) + "\n")
    reg.write_text(reg.read_text().replace(
        '"python3 %s"' % PROBE_REL,
        '"sh integration/py_interp.sh %s"' % PROBE_REL, 1))
    r = run_gate(clone)
    check("C same entry through py_interp.sh green at the real gate",
          r.returncode == 0,
          "rc=%s tail=%r" % (r.returncode, (r.stdout + r.stderr)[-400:]))

    shutil.rmtree(tmp, ignore_errors=True)
    if FAILS:
        print("FAIL summary: %d red" % len(FAILS))
        return 1
    print("PASS summary: interp lint gate green and not vacuous")
    return 0


if __name__ == "__main__":
    sys.exit(main())
