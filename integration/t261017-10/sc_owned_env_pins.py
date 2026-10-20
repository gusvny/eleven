#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_owned_env_pins.py —— t261017-10 line-round env pins must not defeat the
cases that test them (incident regression, grey-box L3).

intent (user-perceivable behaviour; source = host order 261012 acceptance):
  A case that TESTS an env-driven behaviour must own that environment. The line
  round pins SANDBAR_LEDGER_REUSE=0 and exports
  SANDBAR_INTEG_LEDGER_SOURCE=lane:line-round into the whole suite process tree;
  measured on the line head, with ONLY those two pins added, the delivered
  t260930-01-ledger-reuse-round and t261009-11-run-record-drivers go red,
  because the pin leaks through the fixture env helper into the spawned real
  runner. This case locks the acceptance face directly:
    A. the reuse case, run as a real subprocess with the round's two pins in its
       environment, is GREEN (rc=0, no FAIL line in its verdict summary);
    B. the drivers case, same round-shaped env, is GREEN;
    C. each case SAYS SO BY NAME: with a contradicting inherited pin present,
       its stdout names the pin (SANDBAR_LEDGER_REUSE,
       SANDBAR_INTEG_LEDGER_SOURCE) as owned/scrubbed — no silent scrub and no
       false green (stdout only: the kill-switch leg's named reason lives on
       stderr by contract and must not satisfy this);
    D. malformed inherited values (empty / whitespace-only pin values) do not
       change the verdict — the scrub is value-blind, the case stays green.

Intent split (no intent-level duplication):
  the reuse keys and kill-switch face belong to t260930-01-ledger-reuse-round;
  the run-record store/CLI contract belongs to t261009-11-run-record-store; the
  drivers journey belongs to t261009-11-run-record-drivers; the line-round
  run-record relay belongs to t261013-04. This case does not re-assert any of
  those faces — it only locks that the two named cases keep their verdicts
  under the round's own pins and name what they own. Fixture technique
  (subprocess over the delivered cases) is shared; shared steps are not shared
  intent.

Three states: git or the named case files missing = ENV_FAIL exit 2; any
assertion miss = FAIL exit 1. Red on the pre-fix tree is the expected TDD
signal; green at arbitrate/merge is required. Offline seconds-scale, zero
docker / Temporal-server / browser, never touches 3099.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NAME = "t261017-10-owned-env-pins"

sys.path.insert(0, os.path.dirname(HERE))
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

PINS = {"SANDBAR_LEDGER_REUSE": "0",
        "SANDBAR_INTEG_LEDGER_SOURCE": "lane:line-round"}
CASES = {
    "t260930-01-ledger-reuse-round":
        "integration/t260930-01/sc_ledger_reuse_round.py",
    "t261009-11-run-record-drivers":
        "integration/t261009-11/sc_run_record_drivers.py",
}
TIMEOUT_S = 1200


def _git_ok():
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                       capture_output=True, text=True, timeout=15)
    return r.returncode == 0


def _run_case(script, pins):
    """Run a delivered case as a real subprocess with `pins` in its env.

    The env is this process's own env plus the pins — the round shape: the
    proof round exports its pins and the case inherits them unless it owns
    its env."""
    env = dict(os.environ)
    env.update(pins)
    env.setdefault("PYTHONPYCACHEPREFIX", os.path.join(os.environ.get("TMPDIR", "/tmp"), "t26101710-pyc"))
    try:
        p = subprocess.run([sys.executable, "-B", script], cwd=REPO,
                           env=env, capture_output=True, text=True,
                           timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout or ""), (e.stderr or "")
    return p.returncode, p.stdout or "", p.stderr or ""


def _verdict_line(out):
    return " ".join(l for l in out.splitlines() if l.startswith("SUMMARY "))


def main():
    if not _git_ok():
        env_fail(NAME, "git repository not resolvable at %s (all legs assert "
                       "real-case runs over the delivered tree)" % REPO)
    for label, script in CASES.items():
        if not os.path.isfile(os.path.join(REPO, script)):
            env_fail(NAME, "delivered case file missing: %s" % script)

    outs = {}
    for label, script in CASES.items():
        rc, out, err = _run_case(script, PINS)
        outs[label] = out
        ok(rc == 0 and "fail=0" in _verdict_line(out) and "ENV_FAIL" not in out,
           "%s green under the round's own pins" % label,
           "rc=%s verdict=%r stderr_tail=%r"
           % (rc, _verdict_line(out)[-200:], (err or "")[-300:]))

    for label in CASES:
        out = outs[label]
        ok(all(name in out for name in PINS),
           "%s names the inherited pins it owns (stdout, by name)" % label,
           "stdout_tail=%r" % out[-300:])

    rc, out, err = _run_case(CASES["t261009-11-run-record-drivers"],
                             {"SANDBAR_LEDGER_REUSE": "",
                              "SANDBAR_INTEG_LEDGER_SOURCE": "   "})
    ok(rc == 0 and "fail=0" in _verdict_line(out),
       "malformed inherited pin values do not flip the drivers verdict",
       "rc=%s verdict=%r stderr_tail=%r"
       % (rc, _verdict_line(out)[-200:], (err or "")[-300:]))

    finish(NAME)


if __name__ == "__main__":
    main()
