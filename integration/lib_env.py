#!/usr/bin/env python3
"""Shared helper for three-state scenario verdicts (t260904-12: no SKIP inside
the integration gate, final ruling section 7.3).

Scenario-level states are only PASS / FAIL / ENV_FAIL / N/A (leg-level); the
exit-code contract:
  0 = all green; 1 = some FAIL (product red, including all-legs N/A — nothing
      to verify is a scenario design/coverage problem, fix the scenario rather
      than the environment);
  2 = some ENV_FAIL (environment red: nothing got verified, the cause belongs
      to the environment, and the SUMMARY/output names what is missing).

Discipline (against a SKIP-hole comeback):
- a missing environment (dependency, test stage, credentials, playwright, ...)
  always goes through env_fail(), never exit 0;
- na() is only for legs conditioned on **system state** (not on the test
  environment, e.g. "with this feature flag absent the leg has no object");
  a scenario whose legs are all N/A is product red per the contract (exit 1) —
  fail_if_all_na() below is where that verdict is enforced;
- malformed/exception paths are equally not allowed to go silently green:
  prefer an explicit FAIL red.

mjs-side equivalent = integration/t260904-05/lib_browser.mjs makeResults()
(same state vocabulary pass/fail/env_fail/na + summarize() with the same
exit-code priority).
"""
import sys

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ENV_FAIL = 2


def env_fail(reason):
    """Missing environment: print what exactly is absent, exit 2 (ENV_FAIL,
    environment red). Never exit 0."""
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


def na(reason):
    """A leg conditioned on system state has no object (not a missing
    environment). Only emits the marker; whether the scenario is all-N/A is
    judged uniformly by fail_if_all_na() over the scenario's leg table."""
    print("N/A: %s" % reason)


def fail_if_all_na(total_legs, na_legs, scenario=""):
    """A scenario whose legs are all N/A is red (product red, exit 1): having
    nothing to verify is a scenario design/coverage problem.
    total_legs = total legs in the scenario; na_legs = how many are N/A."""
    if total_legs > 0 and na_legs >= total_legs:
        print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题，修场景而非补环境）%s" % scenario)
        sys.exit(1)
