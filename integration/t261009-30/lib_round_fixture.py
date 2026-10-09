#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_round_fixture.py — shared fixtures for the t261009-30 scenarios.

Shared helper code (no sc_ prefix => not registered, lint L5 exempt). It
builds REAL ledgers on disk (develop_certify.append_rows/read_rows, real
flock, real guard files) in a tmp dir, plus plain landing rows and a
recording fake runner, so the scenarios drive the round engine through the
same record shapes the delivered system uses — offline, seconds, zero
docker/Temporal/browser, never touches 3099.

Every builder goes through the module's own public writers (append_rows,
guard_acquire) — the scenarios never hand-craft a seq or fake a guard file.
"""

import atexit
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

_TMP_DIRS = []


def _reclaim_tmp():
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_reclaim_tmp)

ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE_DIR = ROOT / "server" / "engine"
MODULE_PATH = ENGINE_DIR / "develop_certify.py"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


if not ENGINE_DIR.is_dir():
    env_fail("engine tree missing at %s" % ENGINE_DIR)


def load_module():
    """Load server/engine/develop_certify.py by path. Returns None when the
    file itself is absent (pre-implementation tree — a FAIL, not ENV_FAIL;
    an unimportable file for an external-dependency reason raises and the
    caller turns it into ENV_FAIL)."""
    if not MODULE_PATH.is_file():
        return None
    spec = importlib.util.spec_from_file_location("develop_certify_itg30",
                                                  MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def round_entry(mod):
    """The round entry point declared by the approved plan:
    server/engine/develop_certify.py::run_line_round. Missing = the wiring
    this ticket owes has not landed (pre-implementation red, named)."""
    return getattr(mod, "run_line_round", None)


def line_repos(revision):
    return [{"repo": "sandbar", "revision": revision}]


def landing_row(ticket, revision, at_ms, actor="landing-actor"):
    return {"kind": "landing", "id": "ldg-" + ticket, "ticket": ticket,
            "line": "default", "repos": line_repos(revision),
            "actor": actor, "at": at_ms}


def run_header(rid, ran, failed=0, env_failed=0):
    return {"id": rid, "cases": {"ran": ran, "failed": failed,
                                 "env_failed": env_failed}}


class FakeRunner:
    """The injected runner seam (the landed contract: runner(candidate_repos)
    -> run header): records every candidate set it is handed, returns queued
    headers, may raise, and may run a side effect (the chaining scenario
    lands a ticket mid-round with it)."""

    def __init__(self, headers=None, error=None, side_effect=None,
                 error_once=False):
        self.calls = []
        self._headers = list(headers or [])
        self._error = error
        self._error_once = error_once
        self._side_effect = side_effect

    def __call__(self, candidate_repos):
        self.calls.append({"candidate": candidate_repos})
        if self._side_effect is not None:
            self._side_effect()
        if self._error is not None:
            e, self._error = self._error, None if self._error_once else self._error
            raise e
        return self._headers.pop(0)


def round_fixture(at_ms=1700000000000):
    """A tmp project store: a real delivery ledger (empty) and a guard home.
    Returns (tmpdir, ledger_path, guard_path)."""
    tmp = tempfile.mkdtemp(prefix="sandbar-itg30-")
    _TMP_DIRS.append(tmp)
    root = Path(tmp)
    ledger = root / "delivery.jsonl"
    guard_dir = root / "guard"
    guard_dir.mkdir()
    return root, ledger, str(guard_dir / "guard.json")


def append(mod, ledger, rows):
    res = mod.append_rows(rows, str(ledger))
    if res["rejected"]:
        raise AssertionError("fixture rows rejected: %r" % (res["rejected"],))
    return res


def round_call(mod, ledger, guard, runner, trigger="change", **kw):
    """One run_line_round invocation wired to the REAL ledger store on disk
    through its injected seams (the landed signature: injected read_rows /
    append_rows callables, judged_by, booked_red)."""
    return mod.run_line_round(
        line=kw.pop("line", "default"), trigger=trigger, guard_path=guard,
        runner=runner,
        read_rows=lambda: mod.read_rows(str(ledger)),
        append_rows=lambda batch: mod.append_rows(batch, str(ledger)),
        judged_by="itg30", booked_red="br@itg30", **kw)
