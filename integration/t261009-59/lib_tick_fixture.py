#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_tick_fixture.py — shared fixtures for the t261009-59 scenarios.

Shared helper code (no sc_ prefix => not registered, lint L5 exempt), in the
same family as t261009-30's lib_round_fixture but for the TICK call site:
it builds REAL ledgers on disk (develop_certify.append_rows/read_rows, real
flock, real guard files) in a tmp dir and drives the tick face declared by
the approved plan — ``develop_certify.line_round_tick`` — with every seam
injected (load_lines, read_rows/append_rows, resolve_runner_fn, guard_path,
now_ms, backstop_ms), so the scenarios ask the tick the way the production
activity does: over real records, with a fake runner, offline, seconds,
zero docker/Temporal/browser, never touches 3099.

Every ledger mutation goes through develop_certify's own public writers —
the scenarios never hand-craft a seq or fake a guard file. Prior
certifications are produced by RUNNING a round (the landed t261009-30
entry), so the tick always faces the record shapes the real system writes.
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


def fail_tree(reason):
    print("FAIL %s" % reason)
    sys.exit(1)


def load_module():
    """Load server/engine/develop_certify.py by path. Unimportable for an
    external-dependency reason = ENV_FAIL; the file itself missing is a
    pre-implementation FAIL (named), not ENV_FAIL."""
    if not MODULE_PATH.is_file():
        fail_tree("develop_certify.py missing at %s (pre-implementation tree)"
                  % MODULE_PATH)
    try:
        spec = importlib.util.spec_from_file_location("develop_certify_itg50",
                                                      MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # ENV_FAIL: named, never a silent pass
        env_fail("develop_certify unimportable: %s" % e)


def tick_face(mod):
    """The tick entry point declared by the approved plan:
    develop_certify.py::line_round_tick. Missing = the wiring this ticket
    owes has not landed (pre-implementation red, named — TDD signal)."""
    face = getattr(mod, "line_round_tick", None)
    if face is None:
        fail_tree("line_round_tick missing from develop_certify "
                  "(pre-implementation tree: the tick call site is not wired)")
    return face


class DeclarationMissing(Exception):
    """The injected loader's refusal shape (the declaration face)."""


class FakeRunner:
    """The injected runner: records every candidate set it is handed,
    returns queued headers, may raise, may run a side effect."""

    def __init__(self, headers=None, error=None):
        self.calls = []
        self._headers = list(headers or [])
        self._error = error

    def __call__(self, candidate_repos):
        self.calls.append({"candidate": candidate_repos})
        if self._error is not None:
            e, self._error = self._error, None
            raise e
        if self._headers:
            return self._headers.pop(0)
        # 261014 (inline relative caliber): the round may call the runner ONE
        # MORE time per round than the scripted headers — the baseline run at
        # main's tip. That call is not the scenario-under-test (the scripted
        # headers drive the line runs); answer it with a clean empty baseline
        # (no deterministic fails, no flaky), so the relative comparison sees
        # the scripted line header's fails as the whole story. A scenario that
        # wants to exercise the baseline queues an extra header.
        return {"id": "run-baseline-fixture",
                "cases": {"ran": 10, "failed": 0, "env_failed": 0},
                "failed_names": []}


def green_header(ran=10, rid="run-x50fix"):
    return {"id": rid, "cases": {"ran": ran, "failed": 0, "env_failed": 0}}


class Ledger:
    """A REAL delivery ledger on disk with the shared writer/reader."""

    def __init__(self, dc, tmp, name="delivery.jsonl"):
        self.dc = dc
        self.path = Path(tmp) / name

    def append(self, rows):
        return self.dc.append_rows(rows, self.path)

    def read(self):
        return self.dc.read_rows(self.path)

    def bytes(self):
        return self.path.read_bytes() if self.path.is_file() else b""


def landing_row(ticket, revision, at_ms, line_id="default"):
    return {"kind": "landing", "id": "ldg-" + ticket, "ticket": ticket,
            "line": line_id, "repos": [{"repo": "sandbar",
                                        "revision": revision}],
            "actor": "landing-actor", "at": at_ms}


def green_round(dc, ledger, line_id, now_ms, judged_by="tick-fixture"):
    """Produce a REAL previous certification by running the landed round
    (never a hand-crafted row); ``now_ms`` pins the certification's ``at``
    so backstop windows are deterministic."""
    return dc.run_line_round(
        line_id, "change",
        ledger.path.parent / ("guard-anchor-%s.json" % line_id),
        lambda c: green_header(rid="run-x50" + line_id[:4]),
        lambda: dc.read_rows(ledger.path),
        lambda batch: dc.append_rows(batch, ledger.path),
        judged_by, "booked-v1", now_ms=now_ms)


def tick(mod, ledger, line_ids, resolve_runner, now_ms, backstop_ms,
         guard_path, project_key="p", load_lines=None):
    """Ask the tick the way the production activity does: every seam
    injected, nothing global touched.

    ``line_ids``: declared line identifiers (or an Exception instance — the
    injected loader raises it, the missing/corrupt-declaration face).
    ``resolve_runner``: dict {line_id: runner-or-None}, a callable
    (line_id -> runner-or-None), or None (no runner declared at all).
    """
    face = tick_face(mod)
    if load_lines is None:
        if isinstance(line_ids, BaseException):
            def load_lines(pk):
                raise line_ids
        else:
            def load_lines(pk):
                return {lid: object() for lid in line_ids}
    if resolve_runner is None:
        resolve_runner = {}
    if isinstance(resolve_runner, dict):
        table = dict(resolve_runner)

        def resolve(line, env):
            return table.get(line)
    else:
        resolve = lambda line, env: resolve_runner(line)  # noqa: E731
    try:
        return face(project_key, load_lines=load_lines,
                    read_rows=lambda: mod.read_rows(ledger.path),
                    append_rows=lambda batch: mod.append_rows(batch,
                                                              ledger.path),
                    resolve_runner_fn=resolve, guard_path=str(guard_path),
                    now_ms=now_ms, backstop_ms=backstop_ms)
    except TypeError as e:
        fail_tree("line_round_tick does not accept the declared seams "
                  "(project_key + load_lines/read_rows/append_rows/"
                  "resolve_runner_fn/guard_path/now_ms/backstop_ms): %s" % e)


def entries_for(result, line_id):
    """The tick result's per-line entries for one line. Grey-box: searches
    the PUBLIC result payload only."""
    out = []
    lines = result.get("lines") if isinstance(result, dict) else None
    for e in lines or []:
        if isinstance(e, dict) and (e.get("line") == line_id
                                    or e.get("line_id") == line_id):
            out.append(e)
    return out


def entry_texts(entry):
    """Every string value in one entry (recursing one level), so an
    assertion can look for a named fact without pinning its field name."""
    texts = []
    if not isinstance(entry, dict):
        return texts
    for v in entry.values():
        if isinstance(v, str):
            texts.append(v)
        elif isinstance(v, dict):
            texts.extend(entry_texts(v))
    return texts


def tmp_dir(prefix="t26100959-sc-"):
    d = tempfile.mkdtemp(prefix=prefix)
    _TMP_DIRS.append(d)
    return Path(d)
