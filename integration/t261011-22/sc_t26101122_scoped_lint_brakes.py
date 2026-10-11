#!/usr/bin/env python3
"""t261011-22 scenario: the lint SCOPE selector mechanism — a scoped run
proves less BY DECLARATION (named), never by silence, and a planted lesion
is judged in seconds instead of two full-tree battery runs.

Host order 261011 / host refinement: the anchor brake's proof is
"plant a lesion -> the rule goes red and names the file -> clean tree goes
green"; running the whole battery per invocation (~100 s, twice+) is not
what makes that proof. The plan lands a --scope-files selector in
integration/lint_tests.py. This scenario pins the selector's PUBLIC CLI
contract (grey-box L3; predicate truth tables of the scoped walks belong to
developer L1):

  S1  a lesion planted in the shared engine-test tree, judged through a
      run scoped to exactly that planted path, turns the lint RED and the
      output NAMES the planted file (the mechanism: red + named, preserved
      under the shrunken invoked surface);
  S2  the same scoped run carries the summary verdict line ("LINT done")
      so the brake's delta-vs-baseline semantics survive the shrinkage;
  S3  after reclaim a fresh scoped run is GREEN over the same path (clean
      tree goes green) and names the planted file nowhere — zero residue;
  S4  a malformed scope value (empty entry / ".." traversal) is a NAMED
      fail-closed error — a scoped run never silently proves nothing.

Write face: one uniquely named untracked lesion file under
server/engine/tests/ (the established t261004-20 family shape), reclaimed
in finally; no tracked file is touched, the git index is never touched
(KI-222 class). Exclusive pool: the lesion lives in the shared tree, so
no other lint-running pool may observe the window (t261004-34 contract).
cost: seconds (the whole point of the mechanism under test).

Pre-implement red expected (selector not landed yet) = TDD signal;
arbitrate/merge must be green.

Run: python3 integration/t261011-22/sc_t26101122_scoped_lint_brakes.py
(cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLANTED = REPO / "server" / "engine" / "tests" / "test_zz_t26101122_scoped_lesion.py"
PLANTED_REL = "server/engine/tests/" + PLANTED.name
LESION = (
    "def test_zz_t26101122_lesion():\n"
    "    assert '/Users/' + 'user/absolute/home/path' == '/Users/' + 'user/absolute/home/path'\n"
)

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish
_PLANTED = False


def run_lint(scope):
    cmd = [sys.executable, "integration/lint_tests.py"]
    if scope is not None:
        cmd.append("--scope-files=" + scope)
    p = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                       text=True, timeout=120)  # SANCTIONED-WAIT: subprocess guard ceiling for the lint gate (a hard kill bound, never a wait-for-arrival)
    return p.returncode, p.stdout + p.stderr


def main():
    global _PLANTED
    if not (REPO / "integration" / "lint_tests.py").is_file():
        _ck.env_fail("t261011-22-scoped-lint-brakes",
                     "integration/lint_tests.py missing at %s" % REPO)

    try:
        PLANTED.write_text(LESION, encoding="utf-8")
        _PLANTED = True

        # S1 the scoped run bites: red + names the planted file.
        rc1, out1 = run_lint(PLANTED_REL)
        ok(rc1 != 0, "S1.scoped-lesion-lint-red",
           "rc=%s; tail=%s (selector not landed yet = TDD signal)" % (rc1, out1[-300:]))
        ok(PLANTED.name in out1, "S1.red-names-planted-file",
           "scoped red output did not name %s; tail=%s" % (PLANTED.name, out1[-300:]))

        # S2 the scoped run still emits the summary verdict line.
        ok("LINT done" in out1, "S2.scoped-run-reaches-summary-line",
           "no 'LINT done' summary in scoped output; tail=%s" % out1[-300:])
    finally:
        if _PLANTED:
            PLANTED.unlink(missing_ok=True)
            _PLANTED = False

    # S3 clean again: scoped run over a REAL, CLEAN existing path is green and
    # names no lesion anywhere. (The reclaim deletes the lesion, so re-scoping
    # to the deleted path would conflate the clean-tree verdict with the
    # selector's honest missing-file note — the green half must judge a file
    # that exists.)
    clean_candidates = sorted(
        p for p in (REPO / "server" / "engine" / "tests").glob("test_*.py")
        if p.name != PLANTED.name)
    if not clean_candidates:
        _ck.env_fail("t261011-22-scoped-lint-brakes",
                     "no clean engine test file found to scope the green leg")
    CLEAN_REL = "server/engine/tests/" + clean_candidates[0].name
    rc3, out3 = run_lint(CLEAN_REL)
    ok(rc3 == 0, "S3.scoped-clean-green-after-reclaim",
       "rc=%s; tail=%s" % (rc3, out3[-300:]))
    # Zero residue = no lint ERROR/finding names the lesion after reclaim.
    # The selector's own named-absence WARN (a scope path not on the tree is
    # reported by name — the fail-closed-by-declaration face, kept on purpose)
    # may legitimately mention a reclaimed path when a scoped run re-targets
    # it, so the residue judgement reads ERROR lines, not the whole output
    # (acceptance walkthrough gen1: do not remove the warn face to go green).
    error_lines = [l for l in out3.splitlines() if l.startswith("ERROR")]
    ok(all(PLANTED.name not in l for l in error_lines),
       "S3.clean-run-names-nothing",
       "a lint ERROR names the lesion after reclaim: %s" % error_lines[:2])

    # S4 malformed scope value: named fail-closed error, never a silent pass.
    rc4, out4 = run_lint("server/engine/tests/../..")
    ok(rc4 != 0, "S4.malformed-scope-refused",
       "rc=%s (a traversal scope must be refused, not walked)" % rc4)
    ok("scope" in out4.lower(), "S4.refusal-names-the-scope-face",
       "refusal output does not mention the scope; tail=%s" % out4[-300:])

    return finish("t261011-22-scoped-lint-brakes")


if __name__ == "__main__":
    sys.exit(main())
