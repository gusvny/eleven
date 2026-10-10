"""sc_t26100941_fixture_contract_gate.py — t261009-41, grey-box L2, offline.

The drift guard is actually exercised in the gate (KI-046/049 family: a test
in place is not a test in effect). The ticket's C1 deliverable is a pytest
contract: regenerate the engine-projection fixture from the real
freeze_state / ticket_wait_state / ticket_outcome and assert it equals the
committed file the node seam consumes. If the engine ever changes an outcome
rule, THAT test must be the one that goes red — this scenario guarantees the
red is seen in the integration gate, not only in a developer's local run.

Missing/renamed contract file = FAIL named (a deliverable absent is a product
red, not an environment red). pytest unimportable and no engine venv fallback
= ENV_FAIL exit 2. Pre-implement tree: red expected (TDD signal); green
required at the integration gate / merge.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CONTRACT = os.path.join(HERE, "test_model_fixture_contract.py")


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def main():
    if not os.path.isfile(CONTRACT):
        fail("fixture-contract pytest not delivered at %s (C1 deliverable "
             "absent — implement not done)" % os.path.relpath(CONTRACT, ROOT))
    py = None
    for cand in ("server/engine/.venv/bin/python",
                 "server/dsh/temporal-poc/.venv/bin/python", sys.executable):  # engine-venv-compat 回落链（t260907-10 行级豁免）
        p = os.path.join(ROOT, cand)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            py = p
            break
        if cand is sys.executable:
            py = cand
    r = subprocess.run(
        [py, "-m", "pytest", CONTRACT, "-q", "--no-header", "-x"],
        cwd=ROOT, capture_output=True, text=True)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
    print(tail)
    if "No module named" in tail and "pytest" in tail:
        env_fail("pytest unimportable even via engine venv fallback")
    if r.returncode != 0:
        fail("fixture-contract pytest red (engine projection vs committed "
             "fixture drift, or fixture not yet generated)")
    print("ok fixture-contract gate green (%s)" % os.path.relpath(CONTRACT, ROOT))


if __name__ == "__main__":
    main()
