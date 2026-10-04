#!/usr/bin/env python3
"""t261004-34 scenario B: no shared-tree planting by a concurrently running
scenario.

Executor request -0003: integration/t261004-20/sc_test_anchor_brakes.py writes
a fixed-path probe into the lane's SHARED tree (server/engine/tests/) while
being registered in a cross-pool-concurrent pool, so any other scenario running
lint in that window sees the probe and the planting scenario's own cleanup
check sees foreign probes - false red on both sides (observed across the
t261004-25/-18/-19/-26 lanes). Ticket contract: no scenario that runs
concurrently with other pools may plant files into the shared repo tree;
planting is allowed only from a temp tree or from the `exclusive` pool (which
runs alone before the pools barrier).

Grey-box L3, registry + source-text face, offline, seconds, read-only:

- B1 the `t261004-20-test-anchor-brakes` entry exists in the SCENARIOS
     registry with a well-formed pool field;
- B2 if that scenario still plants into the shared tree (its source names the
     fixed repo-tree probe path), its pool MUST be `exclusive` - either half of
     the ticket contract satisfies this case; a serial/ro/engine pool with
     shared-tree planting is the incident shape and FAILS (red before the
     registry move lands - expected TDD signal);
- B3 no OTHER registered entry in a cross-pool-concurrent pool may run that
     planting script either.

Run: python3 integration/t261004-34/sc_no_concurrent_shared_tree_planting.py
(cwd = repo root). PASS 0 / FAIL 1 / ENV_FAIL 2 (registry unreadable).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
INTEG = os.path.join(REPO, "integration")
PLANTING_SCRIPT = "integration/t261004-20/sc_test_anchor_brakes.py"
ENTRY_NAME = "t261004-20-test-anchor-brakes"
# The fixed repo-tree probe path the planting scenario writes (incident shape).
SHARED_PROBE_RE = re.compile(r"REPO.*server.*engine.*tests|"
                             r"test_zz_t26100420_planted_anchor_case")
CROSS_POOL_CONCURRENT = {"main", "ro", "engine", "browser", "browser-free"}

FAILURES = []


def check(name, cond, detail=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                       (" | " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def main():
    if str(INTEG) not in sys.path:
        sys.path.insert(0, str(INTEG))
    try:
        import run_scenarios as rs  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: scenario registry unreadable: %s" % e)
        return 2

    entries = {e[0]: e for e in rs.SCENARIOS}
    print("== B1 registry entry present and well-formed")
    check("B1 anchor-brakes entry exists in SCENARIOS", ENTRY_NAME in entries,
          "known=%r" % [n for n in entries if "anchor" in n])
    if ENTRY_NAME not in entries:
        print("SUMMARY: fail=%d" % len(FAILURES))
        return 1
    entry = entries[ENTRY_NAME]
    pool = entry[3] if len(entry) > 3 else "main"
    check("B1b entry carries a pool field (%s)" % pool,
          isinstance(pool, str) and pool.strip() != "", "")

    print("== B2 shared-tree planting only from the exclusive pool")
    src_path = os.path.join(REPO, PLANTING_SCRIPT)
    if not os.path.isfile(src_path):
        check("B2 planting script missing from tree (contract vacuous)", False,
              "%s not found" % PLANTING_SCRIPT)
    else:
        with open(src_path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        plants_shared_tree = bool(SHARED_PROBE_RE.search(src))
        if not plants_shared_tree:
            check("B2 planting moved to a temp tree (preferred fix)", True, "")
        else:
            check("B2 shared-tree planter runs in the exclusive pool (got %r)"
                  % pool, pool == "exclusive", "")

    print("== B3 no concurrent-pool entry runs the planting script")
    offenders = []
    for name, e in entries.items():
        p = e[3] if len(e) > 3 else "main"
        cmd = str(e[2]) if len(e) > 2 else ""
        if PLANTING_SCRIPT in cmd and p in CROSS_POOL_CONCURRENT:
            offenders.append("%s(pool=%s)" % (name, p))
    check("B3 no concurrent-pool entry references the planter",
          not offenders, "offenders=%r" % offenders)

    if FAILURES:
        print("SUMMARY: fail=%d" % len(FAILURES))
        return 1
    print("SUMMARY: fail=0 env_fail=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
