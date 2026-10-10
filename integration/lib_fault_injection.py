#!/usr/bin/env python3
"""lib_fault_injection — the ONE declaration of fault-injection fixtures (t261009-52).

Failure record (KI-222, 261008 + 261010 escalation): the brake scenario
`integration/t261004-20/sc_test_anchor_brakes.py` plants a one-line fixture under
`server/engine/tests/` to prove lint bites, and a finally-block is not enough —
an interrupted run (SIGINT/SIGTERM) left the file behind, and an add-everything
settle committed it into a ticket's lane history, where merge_check went red on
L16/L17 findings that were the fixture's, not the ticket's.

This module is the single source of truth that makes a planted fixture
RECOGNISABLE BY NAME to every consumer:

  - `integration/lint_tests.py` (L16/L17): when a fired finding names a file
    recognised here, the message says it is a leftover fault-injection fixture
    from <scenario> instead of leaving the reader to conclude the product is
    broken. The findings stay red — no tooth is filed (L16/L17 keep biting).
  - `server/engine/agent_activities.py` (settle / settle_conflict_resolution):
    before any `git add -A`, a dirty file recognised here refuses the settle by
    name (`fault-injection fixture from <scenario>`). It is NOT a gate on
    ordinary files: anything not declared here behaves exactly as before.

Pure stdlib, no repo writes at import, no import of other repo modules (both
consumers pull this file in from different roots). Every function is total:
malformed input is answered, never raised.
"""

from typing import Dict, List, Tuple

#: Repo-relative fixture path -> owning scenario name. ONE entry per planted
#: fixture; the planting scenario self-checks its own entry at start, and a
#: unit test cross-checks the scenario source against this registry, so drift
#: fails loudly in both directions (registry rot is the failure this exists for).
FIXTURES: Dict[str, str] = {
    "server/engine/tests/test_zz_t26100420_planted_anchor_case.py":
        "t261004-20-test-anchor-brakes",
}

#: Settle-side refusal reason code (mirrors the gate_red_detail key shape).
REASON_CODE = "fault_injection_fixture"

#: Settle-side next_action (the reader-facing way out, same channel as the
#: path-gate refusals).
NEXT_ACTION = ("re-run the owning scenario to clean up, or delete the named "
               "fixture file, then re-settle")


def fixture_scenario(rel_path: object) -> str:
    """Owning scenario name for a repo-relative path, or "" when not a fixture.

    Total on malformed input: None / non-str / empty / absolute / `..` escape /
    backslash forms all answer "" — a consumer must never crash on a dirty
    status line.
    """
    if not isinstance(rel_path, str) or not rel_path:
        return ""
    p = rel_path.replace("\\", "/")
    if p.startswith("/") or p.startswith("../") or "/../" in p or p.endswith("/.."):
        return ""
    return FIXTURES.get(p, "")


def fixture_leaks(paths: object) -> List[Tuple[str, str]]:
    """Ordered (rel_path, scenario) pairs for every recognised fixture in a
    dirty list. Order of the input is preserved; all hits are reported, not
    just the first. Non-list input (None, str, …) -> [] — the caller decides
    what a missing judgement means; this function never invents one."""
    if not isinstance(paths, (list, tuple)):
        return []
    out = []
    for p in paths:
        sc = fixture_scenario(p)
        if sc:
            out.append((p, sc))
    return out


def refusal_note(leaks: List[Tuple[str, str]]) -> str:
    """The ONE settle-side refusal text: names each file and its scenario.
    One line per leak so `LINT done`-style summaries stay scannable."""
    parts = ["fault-injection fixture from %s: %s" % (sc, p) for p, sc in leaks]
    return ("settle refused — %s; %s" % ("; ".join(parts), NEXT_ACTION))


def planting_lock_path(repo_root: object):
    """The exclusive same-tree planting lock (acceptance rework, measured
    261010: two concurrent brake runs resurrect a reclaimed fixture and make
    the lint verdict unstable over identical input). Lives under the repo's
    own .sandbar evidence area — gitignored, so the guard never dirties the
    tree it protects."""
    import pathlib
    return pathlib.Path(str(repo_root)) / ".sandbar" / "t26100420_brakes.lock"


def acquire_planting_lock(repo_root: object):
    """Take the planting lock (non-blocking) for the caller's chosen window,
    or refuse BY NAME (SystemExit). Returns the open file handle — holding it
    open IS holding the lock; close it to release. Total on lock-busy: a
    refusal, never a collision."""
    import fcntl
    lock = planting_lock_path(repo_root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(
            "refused: another fault-injection run already holds %s — "
            "concurrent same-tree fixture planting collides (measured 261010: "
            "fixture resurrection after a green reclaim, lint verdict "
            "instability over identical input); run them one at a time" % lock)
    return fh


def lint_fixture_note(rel_path: object) -> str:
    """The ONE lint-side note for a recognised fixture file ("" otherwise).
    Appended next to the L16/L17 finding: the finding keeps its red, the reader
    learns the red is a leftover injection fixture, not a product fault."""
    sc = fixture_scenario(rel_path)
    if not sc:
        return ""
    return ("leftover fault-injection fixture from %s (planted by the brake "
            "scenario; not product code — re-run the scenario or delete the "
            "file)" % sc)
