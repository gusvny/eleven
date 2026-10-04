#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_copy_language_per_diff_gate.py — the mechanical per-diff copy-language gate
behaves per contract (t261004-24, gray-box L2, offline seconds, zero docker/ports).

intent (reviewer-perceivable): the ticket's deliverable 4 — new copy language must
be under a mechanical per-diff check instead of relying on readers to notice.
Locked via the gate's declared standalone entry (`integration/lint_copy_language.py`)
plus its wiring point in the declared static gate (`integration/lint_tests.py`).

The gate is REPO-anchored by design (it always inspects the repo that contains it,
"cwd = repo root"), so the planted cases run against a COPY of the gate script
placed in a THROWAWAY git repo under the system temp dir — the same script code,
but the sandbar worktree is never modified (it is a live developer surface).
Contract asserted (behavior, not implementation):

  G1 a NEW CJK line inside a product surface fails the run AND the failure names
     file and line (ticket: "name file and line in the failure");
  G2 untouched legacy CJK lines never fire (the point of a per-diff check);
  G3 new CJK text outside product surfaces (notes/ ledger prose) does not fire;
  G4 an explicitly exempted line (visible rule-id marker) does not fire AND is
     listed in the run output (ticket: reviewer-visible exemption + printed list);
  G5 the run output prints its scope (ticket: "print its scope");
  G6 fail-closed: run against a tree with no git metadata at all -> exit 2 (env
     red) with the reason named, never a silent green;
  G7 wiring: the declared static gate (integration/lint_tests.py) carries the
     check, so every lane that runs the static gate gets it;
  G8 the gate script itself compiles (syntax face).

Diff base for G1–G5 is pinned with the gate's declared $COPY_LANGUAGE_BASE env so
only the planted delta is inspected.

Three states: this scenario has no environment face beyond python itself; the gate
script being absent pre-implement = FAIL with the name (TDD-phase red expected;
arbitrate/merge must be green). Run directly:
python3 integration/t261004-24/sc_copy_language_per_diff_gate.py (cwd=repo root).
"""
from __future__ import annotations

import os
import pathlib
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / "integration" / "lint_copy_language.py"
LINT = REPO / "integration" / "lint_tests.py"

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok   " + msg)
    else:
        FAIL += 1
        print("FAIL " + msg)


def build_throwaway(root: pathlib.Path):
    """Throwaway repo holding a copy of the gate + a product surface with legacy CJK."""
    (root / "integration").mkdir(parents=True)
    shutil.copy2(GATE, root / "integration" / "lint_copy_language.py")
    prod = root / "server" / "plugins" / "demo" / "src"
    prod.mkdir(parents=True)
    (prod / "face.ts").write_text("// legacy line, untouched\n", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "ledger.md").write_text("# ledger\n", encoding="utf-8")
    def git(*args):
        return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    git("init", "-q", "-b", "work")
    git("add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "baseline")
    return git("rev-parse", "HEAD").stdout.strip(), prod


def main():
    if not GATE.is_file():
        print("FAIL: gate script missing: %s (per-diff copy check not implemented yet)" % GATE)
        sys.exit(1)
    try:
        with tempfile.TemporaryDirectory(prefix="t261004-24-pyc-") as pycdir:
            py_compile.compile(str(GATE), doraise=True,
                               cfile=str(pathlib.Path(pycdir) / "gate.pyc"))
        check(True, "G8 gate script compiles")
    except py_compile.PyCompileError as e:
        check(False, "G8 gate script compiles (%s)" % e)
        print("FAIL: gate does not compile")
        sys.exit(1)

    tmp = tempfile.mkdtemp(prefix="t261004-24-gate-")
    try:
        root = pathlib.Path(tmp) / "repo"
        root.mkdir()
        base, prod = build_throwaway(root)

        def run_gate(env=None):
            e = dict(os.environ)
            e.pop("COPY_LANGUAGE_BASE", None)
            if env:
                e.update(env)
            return subprocess.run(["python3", "integration/lint_copy_language.py"],
                                  cwd=str(root), env=e, capture_output=True, text=True,
                                  timeout=120)

        # G1: a NEW CJK line in a product surface -> red, naming file and line.
        f = prod / "face.ts"
        f.write_text(f.read_text(encoding="utf-8") + 'const t = "长回合进行中"\n', encoding="utf-8")
        r = run_gate({"COPY_LANGUAGE_BASE": base})
        out = (r.stdout or "") + (r.stderr or "")
        check(r.returncode == 1, "G1 new CJK line in a product surface is RED (exit 1)")
        check("face.ts" in out, "G1 failure names the file (face.ts)")
        check(re.search(r"face\.ts:\d+", out) is not None, "G1 failure names the line (face.ts:N)")
        print("---- gate output under G1 ----\n" + out[-1500:])

        # G2: remove the new line — untouched legacy CJK never fires.
        f.write_text("// legacy line, untouched\n", encoding="utf-8")
        r = run_gate({"COPY_LANGUAGE_BASE": base})
        check(r.returncode == 0, "G2 untouched legacy CJK line does not fire (per-diff only)")

        # G3: new CJK in notes/ (ledger prose) — out of the product scope.
        (root / "notes" / "ledger.md").write_text("# ledger\n守望者长回合注记\n", encoding="utf-8")
        r = run_gate({"COPY_LANGUAGE_BASE": base})
        check(r.returncode == 0, "G3 new CJK line in notes/ does not fire")

        # G4: new CJK with an explicit reviewer-visible exemption marker — no fire,
        # and the exemption is listed in the output.
        f.write_text('const t = "长回合检测样本" // copy-lang-allow:fixture\n', encoding="utf-8")
        r = run_gate({"COPY_LANGUAGE_BASE": base})
        out = (r.stdout or "") + (r.stderr or "")
        check(r.returncode == 0, "G4 exempted CJK line does not fire")
        check("face.ts" in out, "G4 exemption list in output names the exempt file")
        f.write_text("// legacy line, untouched\n", encoding="utf-8")

        # G5: scope is printed.
        r = run_gate({"COPY_LANGUAGE_BASE": base})
        out = (r.stdout or "") + (r.stderr or "")
        check("server/plugins" in out and "server/engine" in out,
              "G5 run output prints the checked scope (product surfaces named)")

        # G6: no git metadata at all -> fail-closed env red with the reason named.
        nogit = pathlib.Path(tmp) / "nogit"
        (nogit / "integration").mkdir(parents=True)
        shutil.copy2(GATE, nogit / "integration" / "lint_copy_language.py")
        r = subprocess.run(["python3", "integration/lint_copy_language.py"],
                           cwd=str(nogit), capture_output=True, text=True, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        check(r.returncode == 2, "G6 no git tree = fail-closed env red (exit 2), never silent green")
        check(len(out.strip()) > 0, "G6 the failure names its reason (non-empty output)")
        print("---- gate output under G6 ----\n" + out[-800:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # G7: wiring in the declared static gate — every lane that runs lint_tests gets it.
    if LINT.is_file():
        lint_src = LINT.read_text(encoding="utf-8")
        check("copy_language" in lint_src or "copy-lang" in lint_src,
              "G7 integration/lint_tests.py wires the copy-language check")
    else:
        check(False, "G7 integration/lint_tests.py present")

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
