#!/usr/bin/env python3
"""t261009-60 — a "no leftovers" assertion must not read a machine-global namespace.

KI-01M4J0JGYJWCJ1Z2XD3KW431FV, second instance: an engine unit test globbed the
SHARED system temp dir for `bundle-freshness-*` while any other lane running the
gate legitimately creates exactly those directories — it passed alone and reded
whenever the fleet was busy, blocking four tickets at merge_check in one night.
The fix is test-side scoping (point the temp root at the test's own sandbox),
not a roster exemption.

Grey-box L3, offline seconds, pure stdlib + one subprocess pytest run, zero
docker/Temporal-server/browser, never touches 3099. Exit codes: 0 PASS,
1 FAIL (named), 2 ENV_FAIL.

Faces (pre-implement red is the TDD signal; green required at merge):
  A busy-fleet immunity, end to end: with a FOREIGN live `bundle-freshness-*`
    directory planted in the machine temp root (exactly what a concurrent lane
    creates), the real engine test file runs green under pytest in a
    subprocess — the planted dir is the old assertion's exact false-red shape.
  B order-independence: the same planted decoy, with the named file run AFTER
    another engine test file that consumes tempfile first (gettempdir() caches
    its answer per process) — still green. Locks the cache-bypass half of the
    fix; an env-only patch would flake here.
  C scoping contract (source-text face): the named test file contains no
    `gettempdir()` reference at all — the leftover assertion must be rooted in
    the test's own sandbox, never re-globbed against the machine temp root.
  D sweep teeth: the same scanner over a directory reds on a SYNTHETIC offender
    file with file:line named, and stays silent on a clean directory — the
    class cannot quietly regrow anywhere in server/engine/tests/.
  E no escape hatch: neither the known-red baseline nor any roster row books
    the named test nodeid — the permanent answer is the fix, not an exemption.

Intent split: the unit-level truth table (scoped root, unreaped-dir teeth,
decoy-in-own-root red) belongs to developer L1 inside the named test file;
this entry owns the busy-fleet journey (a foreign dir in the machine temp
during a real pytest run), the order-dependence face, and the suite-wide
sweep guard.

Engine tree / venv pytest / named test file missing = ENV_FAIL exit 2.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
TESTS = ENGINE / "tests"
NAMED = TESTS / "test_t261009_42_bundle_freshness.py"
ORDER_LEAD = TESTS / "test_t260904_18_gate_pure.py"
BASELINE = REPO / "integration" / "known-red-baseline.json"
NODEID = "test_t261009_42_bundle_freshness.py::test_rebuild_temp_copy_reaped_on_every_path"
DECOY_PREFIX = "bundle-freshness-sc2601009-60-"

FAILS = []


def py():
    p = ENGINE / ".venv" / "bin" / "python"
    return p if p.exists() else Path(sys.executable)


def find_offenders(dirpath: Path):
    """Return file:line for every 'no leftovers' assertion globbed from a
    machine-global temp root in *.py under dirpath (the sweep scanner)."""
    hits = []
    for f in sorted(dirpath.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # shape: [p for p in <tempfile.gettempdir() root>.glob(...)] compared to []
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == "gettempdir":
                    hits.append("%s:%d gettempdir() reference" % (f, n.lineno))
    return hits


def run_pytest(args, decoy_root: Path):
    decoy = Path(tempfile.mkdtemp(prefix=DECOY_PREFIX, dir=str(decoy_root)))
    try:
        r = subprocess.run([str(py()), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
                           + args,
                           cwd=str(ENGINE), capture_output=True, text=True, timeout=600)
        return r.returncode, (r.stdout + r.stderr)[-4000:]
    finally:
        shutil.rmtree(decoy, ignore_errors=True)


def main():
    if not ENGINE.exists() or not NAMED.exists():
        print("ENV_FAIL: engine tree or named test file missing: %s" % NAMED)
        return 2
    r = subprocess.run([str(py()), "-m", "pytest", "--version"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("ENV_FAIL: no pytest in engine interpreter: %s" % r.stderr[-300:])
        return 2

    machine_tmp = Path(tempfile.gettempdir())

    # --- A: busy-fleet immunity (foreign live bundle-freshness-* dir planted)
    code, out = run_pytest(["tests/" + NAMED.name], machine_tmp)
    if code != 0:
        FAILS.append("A: named file red WITH a foreign bundle-freshness-* dir in the "
                     "machine temp root (the KI false-red shape is alive): %s" % out[-1500:])
    elif "failed" in out and "1 failed" in out:
        FAILS.append("A: pytest reported a failure: %s" % out[-800:])

    # --- B: order independence (tempfile consumed first in the same process)
    if ORDER_LEAD.exists():
        code, out = run_pytest(["tests/" + ORDER_LEAD.name, "tests/" + NAMED.name],
                               machine_tmp)
        if code != 0:
            FAILS.append("B: named file red when run after a tempfile-consuming file "
                         "(gettempdir cache defeated the scoping): %s" % out[-1500:])

    # --- C: scoping contract on the named file
    refs = [h for h in find_offenders(TESTS) if h.startswith(str(NAMED))]
    if refs:
        FAILS.append("C: named file still references gettempdir() (machine-global "
                     "namespace): %s" % refs)

    # --- D: sweep teeth on the scanner itself
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "test_synthetic_offender.py"
        bad.write_text(
            "import tempfile\nfrom pathlib import Path\n"
            "def test_x():\n"
            "    leftovers = [p for p in Path(tempfile.gettempdir()).glob('k-*')]\n"
            "    assert leftovers == []\n", encoding="utf-8")
        got = find_offenders(Path(td))
        if not got:
            FAILS.append("D: scanner stayed silent on a synthetic offender (no teeth)")
        elif not got[0].endswith(":4 gettempdir() reference"):
            FAILS.append("D: scanner finding not file:line named: %s" % got)
    # clean face: a dir with an already-scoped leftover assertion is quiet
    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "test_scoped_ok.py"
        good.write_text(
            "def test_x(tmp_path):\n"
            "    assert list(tmp_path.glob('k-*')) == []\n", encoding="utf-8")
        got = find_offenders(Path(td))
        if got:
            FAILS.append("D: scanner flagged a properly scoped test: %s" % got)

    # --- E: no roster row / no baseline booking for the named nodeid
    if BASELINE.exists():
        blob = BASELINE.read_text(encoding="utf-8")
        if NODEID.split("::")[0] in blob:
            FAILS.append("E: known-red baseline carries a row touching %s — the "
                         "permanent answer is the test fix, not a booking" % NODEID)

    if FAILS:
        print("FAIL t261009-60-leftover-assert-scope:")
        for f in FAILS:
            print("  - %s" % f)
        return 1
    print("PASS t261009-60-leftover-assert-scope: A busy-fleet decoy immunity green; "
          "B order-independence green; C no gettempdir in named file; "
          "D scanner teeth proven on synthetic offender; E no baseline/roster booking")
    return 0


if __name__ == "__main__":
    sys.exit(main())
