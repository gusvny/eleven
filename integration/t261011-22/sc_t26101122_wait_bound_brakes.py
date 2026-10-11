#!/usr/bin/env python3
"""t261011-22 scenario: the real-time-wait lint brake BITES, names the line,
honors its sanctioned exemption, and keeps its own hygiene.

Host order 261011: a test whose evidence is "I waited the real timeout" is
slow, load-dependent, and unfit for any round budget (the retired
t260912-03-authz-overlimit-accept burned 603 s waiting a 600 s REAL bound).
The family-level guard is a per-diff lint brake over added lines in
integration/ scenario scripts: a large real-time bound added to a scenario
turns the lint RED naming file:line, UNLESS the line carries an explicit
sanctioned-wait exemption with a reason. This scenario pins that contract
end to end over the REAL gate subprocess (grey-box L3, developer L1 owns the
predicate truth tables):

  R1  clean tree: the lint runs to its summary line and is green (baseline;
      also proves no pre-existing wait-bound debt of this shape in the
      current diff).
  R2  lesion precision: with TWO tracked scenario scripts transiently
      rewritten in one shot -- file A gaining an unsanctioned
      600-second real-time bound, file B gaining the same bound preceded by
      a sanctioned-wait exemption with a reason -- ONE lint run goes red,
      NAMES file A, and does NOT name file B (the exemption is honored and
      the red is precise: the reader learns which line is the offense, not
      just "something is slow"). The rewrites are byte-backed and restored
      in finally; the scenario never commits, never touches the index
      (KI-222 class).
  R3  restore hygiene: after byte rollback a fresh lint run is green again
      and names neither file (zero residue -- the guard consumes its own
      contract, t261009-51 precedent).

Cost note (declared honestly): the lint runs go through the --rules=L25
subset selector (t261011-22 host refinement), so the three runs are
seconds-scale. Serial pool: the lesion rewrites touch tracked files in the
shared tree, so no other lint-running pool may observe the window
(t261004-34 contract).

Run: python3 integration/t261011-22/sc_t26101122_wait_bound_brakes.py
(cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2.
Pre-implement red expected (the brake does not exist yet) = TDD signal;
arbitrate/merge must be green.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
# t261011-22 (host refinement, follow-up landed): a mechanism test runs the
# rule it plants for, never the whole ~20-rule battery — the three lint runs
# below are seconds-scale through the --rules subset selector.
LINT = [sys.executable, "integration/lint_tests.py", "--rules=L25"]
TARGET_A = REPO / "integration" / "sc_check_auto_rework_trace.py"
TARGET_B = REPO / "integration" / "sc_emit_surrogate_guard.py"

LESION_A = ("\n\n# t261011-22 transient lesion (restored in finally)\n"
            "time" "out=600\n")  # assembled at runtime: the lesion text must match the rule's declared shape without the raw literal living in this file's own added lines
LESION_B = ("\n\n# t261011-22 transient lesion (restored in finally)\n"
            "# SANCTIONED-WAIT: probe bounds for the t261011-22 family guard\n"
            "time" "out=900\n")

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish
_PLANTED = None
_BEFORE = {}


def _env_fail(msg):
    print("ENV_FAIL: %s" % msg, flush=True)
    return 2


def run_lint(timeout=300):  # SANCTIONED-WAIT: subprocess guard ceiling for the lint gate (a hard kill bound, never a wait-for-arrival)
    p = subprocess.run(LINT, cwd=str(REPO), capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr


def plant(path, text):
    if path not in _BEFORE:
        _BEFORE[path] = path.read_bytes()
    path.write_text(_BEFORE[path].decode("utf-8") + text, encoding="utf-8")
    _PLANTED = path  # noqa: F841  (restore is driven by _BEFORE)


def restore_all():
    for path, data in _BEFORE.items():
        path.write_bytes(data)
    _BEFORE.clear()


def main():
    if not (REPO / "integration" / "lint_tests.py").is_file():
        return _env_fail("integration/lint_tests.py missing at %s" % REPO)
    for t in (TARGET_A, TARGET_B):
        if not t.is_file():
            return _env_fail("lesion target scenario file missing: %s" % t)

    # R1 clean-tree baseline: green, runs to the summary verdict line.
    rc1, out1 = run_lint()
    ok(rc1 == 0, "R1.clean-tree-lint-green", "rc=%s; tail=%s" % (rc1, out1[-300:]))

    # Plant both lesions (same single window, one lint run judges both).
    plant(TARGET_A, LESION_A)
    plant(TARGET_B, LESION_B)
    rc2, out2 = run_lint()
    ok(rc2 != 0, "R2.lesion-lint-red", "rc=%s" % rc2)
    ok(TARGET_A.name in out2,
       "R2.red-names-offending-file",
       "red output did not name %s; tail=%s" % (TARGET_A.name, out2[-300:]))
    ok(TARGET_B.name not in out2,
       "R2.sanctioned-exemption-honored",
       "exempted file %s was named in a red run; tail=%s" % (TARGET_B.name, out2[-300:]))
    # The red must be attributable to a line: some line-number token appears
    # near the report (shape anchor, not wording -- t261009-51 precedent).
    import re
    ok(re.search(r"line\s*#?\s*\d+", out2, re.IGNORECASE) is not None
       or re.search(r":\d+", out2) is not None,
       "R2.red-reports-line-token",
       "no line-number token anywhere in the red output")

    # R3 restore hygiene: bytes back, lint green again, neither file named.
    restore_all()
    rc3, out3 = run_lint()
    ok(rc3 == 0, "R3.restore-lint-green", "rc=%s; tail=%s" % (rc3, out3[-300:]))
    ok(TARGET_A.name not in out3 and TARGET_B.name not in out3,
       "R3.restore-names-neither",
       "post-restore lint output still names a lesion file; tail=%s" % out3[-300:])

    return finish("t261011-22-wait-bound-brakes")


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        if _BEFORE:
            restore_all()
    sys.exit(rc)
