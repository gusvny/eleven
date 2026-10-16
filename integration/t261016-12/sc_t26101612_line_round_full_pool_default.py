#!/usr/bin/env python3
"""t261016-12 scenario: the line round defaults to EVERY pool; narrowing is
opt-in and always announced (grey-box L3, offline seconds, zero docker).

intent (operator-perceivable; host order 261016 '(b) 改一行代码：默认就是「跑全池」'):
every live worker has NO SANDBAR_LINE_ROUND_EXCLUDE_POOLS, and the runner
declares (exclude_pools_value docstring) that the default runs every pool —
the certification round. Until the constant flip lands, the code contradicts
that declaration: the absent-var case returned "exclusive", so EVERY round
was NARROWED, wrote no run record, and no landing could ever be certified
(delivery ledger seq 77 receipt). This scenario judges the runner through its
PUBLIC face only (exclude_pools_value / suite_argv with an injected env — the
same functions main() consults), never internal helpers:

  A THE INCIDENT DEFAULT (fails on today's tree, passes after the flip):
    with the var ABSENT the declared exclusion is empty, the suite command
    carries NO --exclude-pools, and stderr carries NO narrowing announcement
    — a full, certifiable round, not a narrowed one.
  B the operator narrows: var = a pool name → the exclusion is that name,
    the suite command carries --exclude-pools <name>, and stderr names the
    round NARROWED and unable to mint a certification (stable substrings
    only; the copy is user-facing text, not a contract).
  C an empty value = every pool: suite command byte-identical to A's, no
    announcement — the "only lawful full-pool form" keeps working.
  D malformed input: a whitespace-only value narrows nothing (same argv and
    stderr as A), never a crash, never a phantom exclusion.

high-level steps: import the real integration/line_round_runner.py from the
tree under test; for each env form call exclude_pools_value(env) and
suite_argv(env) with stderr captured; compare argv lists byte-for-byte where
identity is the contract. Intent split (no intent-level duplication): the
narrowed-round-writes-no-record chain belongs to t261013-04-line-round-run-record
(its leg B owns the skip-reason face); the exclusion-switch consumption matrix
on the verify_lane gate belongs to t260913-03-pool-exclude-switch-forms; the
value/argv truth table at unit level belongs to the developer's L1 battery —
this entry uniquely owns the operator-visible default journey (which round is
certifiable with a bare worker environment) on the real runner module.

Pre-implement tree: A/D red = the named TDD signal; green required at the
integration gate / merge. line_round_runner.py missing or unimportable =
ENV_FAIL exit 2. Never touches 3099/7233.
"""
import contextlib
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import line_round_runner as R  # noqa: E402

ENV_KEY = "SANDBAR_LINE_ROUND_EXCLUDE_POOLS"
TAG = "t261016-12-line-round-full-pool-default"

failures = []


def check(ok, name, detail=""):
    print("%s [%s] %s%s" % ("PASS" if ok else "FAIL", TAG, name,
                            (" :: " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def observe(env):
    """Reader-side view an operator gets for one env form: (declared
    exclusion, suite argv, stderr text) through the runner's public face."""
    argv = None
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        argv = R.suite_argv(env)
    return R.exclude_pools_value(env), list(argv), err.getvalue()


try:
    # ---------------- A: the incident default — bare worker env ----------------
    absent = {k: v for k, v in os.environ.items() if k != ENV_KEY}
    declared_a, argv_a, err_a = observe(absent)
    check(declared_a == "",
          "A1 absent var declares NO exclusion (default = every pool)",
          "declared=%r" % declared_a)
    check(not any("--exclude-pools" == t for t in argv_a),
          "A2 bare-env suite command carries no narrowing flag",
          "argv=%r" % (argv_a,))
    check("NARROWED" not in err_a and "NO certification" not in err_a,
          "A3 bare-env round is NOT announced narrowed / record-less",
          "stderr=%r" % err_a)

    # ---------------- B: the operator narrows a diagnostic round ----------------
    named = dict(absent)
    named[ENV_KEY] = "exclusive"
    declared_b, argv_b, err_b = observe(named)
    check(declared_b == "exclusive", "B1 explicit value is the exclusion",
          "declared=%r" % declared_b)
    check(argv_b == argv_a + ["--exclude-pools", "exclusive"],
          "B2 suite command carries --exclude-pools <name>",
          "argv=%r" % (argv_b,))
    check("NARROWED" in err_b and "NO certification" in err_b
          and "exclusive" in err_b,
          "B3 narrowed round still names itself unable to certify",
          "stderr=%r" % err_b)

    # ---------------- C: empty value = every pool, identical to A ----------------
    empty = dict(absent)
    empty[ENV_KEY] = ""
    declared_c, argv_c, err_c = observe(empty)
    check(declared_c == "", "C1 empty value declares no exclusion",
          "declared=%r" % declared_c)
    check(argv_c == argv_a, "C2 argv byte-identical to the absent form",
          "argv=%r vs %r" % (argv_c, argv_a))
    check(err_c == err_a, "C3 no narrowing announcement (same stderr as A)",
          "stderr=%r" % err_c)

    # ---------------- D: malformed input — whitespace-only value ----------------
    ws = dict(absent)
    ws[ENV_KEY] = "   "
    declared_d, argv_d, err_d = observe(ws)
    check(declared_d == "", "D1 whitespace-only value narrows nothing",
          "declared=%r" % declared_d)
    check(argv_d == argv_a and err_d == err_a,
          "D2 whitespace-only behaves as the absent form, never crashes",
          "argv=%r stderr=%r" % (argv_d, err_d))
except Exception as e:  # noqa: BLE001 — a broken runner surface is a named FAIL
    failures.append("runner-surface-exception")
    print("FAIL [%s] runner public face raised :: %r" % (TAG, e))

if failures:
    print("SUMMARY %s FAIL %s" % (TAG, ",".join(failures)))
    sys.exit(1)
print("SUMMARY %s PASS all-faces" % TAG)
sys.exit(0)
