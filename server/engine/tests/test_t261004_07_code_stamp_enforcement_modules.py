"""t261004-07: code stamp must cover the worker's enforcement modules.

Root cause (ticket body): t261004-05 fixed the integration red line matcher in
``server/engine/integration_discipline.py``, but a worker started before the fix
kept enforcing the old copy, and ``CODE_STAMP_MODULES`` (``shared.py``) did not
track that file — so the stamp reported ``stale=none`` while the red line ran
old code. Silent staleness of enforcement code is the bug.

This module pins three things:
1. every enforcement module the worker eagerly loads is in ``CODE_STAMP_MODULES``;
2. the stamp contract still holds: stale modules are named, and a missing or
   unreadable mtime is NOT stale but keeps its mtime field empty (named by the
   empty mtime, never silently dropped);
3. a tripwire: any repo-local module imported at top level by the worker's eager
   entry chain (``worker.py`` → ``activities.py``/``agent_activities.py``/``shared.py``)
   must be either tracked in ``CODE_STAMP_MODULES`` or named in
   ``UNTRACKED_WORKER_MODULES`` below together with the reason the omission is
   safe. Adding a new enforcement module to the worker path without either
   covering it or documenting it fails this test.

Run: ``python3 -m pytest server/engine/tests/test_t261004_07_code_stamp_enforcement_modules.py -q``
(stdlib + pytest only; no network, no real Temporal, no integration entry).
"""
import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared  # noqa: E402

TICKET = "t261004-07"
ENGINE_DIR = Path(__file__).resolve().parent.parent

#: Enforcement modules the worker eagerly loads and that decide a red line or a
#: gate verdict. All must be tracked in CODE_STAMP_MODULES.
ENFORCEMENT_MODULES = (
    "integration_discipline",   # t260921-04 red line matcher (agent stage discipline)
    "path_gates",               # write-set / path gate verdicts
    "authz_gates",              # authorization gate verdicts
    "dsh_pin",                  # dsh version hard gate (enforce_expected)
    "failure_protocol",         # failure attribution surface consumed by verdicts
)

#: Eager worker entry chain: files the worker process imports at startup whose
#: top-level repo-local imports this tripwire scans.
WORKER_ENTRY_FILES = ("worker.py", "activities.py", "agent_activities.py", "shared.py")

#: Repo-local modules reachable from the eager worker path but intentionally NOT
#: tracked. Each entry must say why leaving it out is safe (no red line / no gate
#: verdict depends on it being fresh in the worker process).
UNTRACKED_WORKER_MODULES = {
    "agent_runtime": "execution transport layer; no gate verdict or red line",
    "event_ledger": "append-only ledger write; no gate verdict",
    "ui_capture_stage": "UI rig lifecycle primitives; no gate verdict",
    "activities": "worker entry itself (this scan starts from it); tracking it "
                  "adds no signal beyond agent_activities/shared",
    "workflows": "re-export shell over TYPE_CHECKING imports; logic lives in "
                 "dev_lane/light_lane/inspection_flow (already tracked)",
    "workflows_v2": "lazy template registry read by activities; no red line",
    "ticket_worker": "child process supervisor; the child re-reads its own code",
    "inspection_decl": "instance plan resolution, pure data shaping",
    "inspection_scan": "inspection scan impl, not a stage gate",
    "inspection_scan_ms": "inspection scan impl, not a stage gate",
    "inspection_scan_doc": "inspection scan impl, not a stage gate",
    "inspection_scan_stage": "inspection scan impl, not a stage gate",
    "inspection_inspect": "walkthrough verdict helper (lazy import inside activity)",
    "inspection_deadman_helper": "unused placeholder; kept only if scan ever sees it",
    "dsh": "engine-external dsh package name, never a repo-local engine file",
    "temporalio": "external package",
    "sandbar_exec": "sandboxed exec helper (lazy import); transport, not verdict",
    "audit": "audit trail writer (client side); no worker gate verdict",
    "develop_certify": "t261009-50: the activities.py top-level import is the "
                       "scan tick's line-round ask; the module holds the "
                       "round body only (tick face, delivery-record writer, "
                       "red-ladder steps) and decides no red line and no "
                       "gate verdict",
}

TRACKED = {name for name, _rel in shared.CODE_STAMP_MODULES}


def _repo_local_top_level_imports(py_file: Path) -> set:
    """Repo-local module names imported at top level (column 0) of ``py_file``.

    Only column-0 ``import X`` / ``from X import ...`` counts: those run when the
    worker process imports the file. Lazy/TYPE_CHECKING imports are out of scope
    (a stale lazy import is re-read from disk on first use, so mtime staleness
    does not apply the same way)."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return set()
    names = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets = [node.module]
        for target in targets:
            root = target.split(".")[0]
            if (ENGINE_DIR / (root + ".py")).exists():
                names.add(root)
    return names


def test_enforcement_modules_are_tracked_by_code_stamp():
    missing = [n for n in ENFORCEMENT_MODULES if n not in TRACKED]
    assert not missing, (
        "enforcement modules not in CODE_STAMP_MODULES (a stale worker would run "
        "the old red line with stale=none): %s" % missing)


def test_stamp_reports_enforcement_modules_and_stale_names():
    stamp = shared.worker_code_stamp(
        mtime_fn=lambda p: 9e9, started_at="2020-01-01T00:00:00", pid=123)
    # t261004-07 regression: the enforcement modules must show up as stale when
    # their on-disk mtime is newer than the worker start baseline.
    for name in ENFORCEMENT_MODULES:
        assert name in stamp["stale"], (name, stamp["stale"])
        assert stamp["modules"][name]["stale"] is True
        assert stamp["modules"][name]["role"] == "worker-loaded"
    line = stamp["stamp_line"]
    assert "stale=" in line
    for name in ENFORCEMENT_MODULES:
        assert name in line, (name, line)
    # Line shape contract: the three grep anchors stay verbatim.
    assert "worker pid=123" in line and "started=" in line


def test_unreadable_mtime_is_not_stale_but_named():
    stamp = shared.worker_code_stamp(
        mtime_fn=lambda p: (_ for _ in ()).throw(ValueError("boom")),
        started_at="2020-01-01T00:00:00", pid=1)
    assert stamp["stale"] == []
    for name in ENFORCEMENT_MODULES:
        m = stamp["modules"][name]
        assert m["stale"] is False
        assert m["mtime"] == "", "unreadable mtime must be named via empty field"


def test_tripwire_worker_path_imports_covered_or_documented():
    """Fails when a new module joins the eager worker path without being either
    tracked in CODE_STAMP_MODULES or documented in UNTRACKED_WORKER_MODULES."""
    unknown = set()
    for fname in WORKER_ENTRY_FILES:
        for mod in _repo_local_top_level_imports(ENGINE_DIR / fname):
            if mod in TRACKED or mod in UNTRACKED_WORKER_MODULES:
                continue
            unknown.add("%s imports %s" % (fname, mod))
    assert not unknown, (
        "new worker-path module(s) not covered by the code stamp and not "
        "documented as safe-to-omit (add to CODE_STAMP_MODULES if it decides a "
        "red line or gate verdict, else to UNTRACKED_WORKER_MODULES with a "
        "reason): %s" % sorted(unknown))


def test_tripwire_sees_the_real_enforcement_imports():
    """Guard the tripwire itself: if agent_activities ever stops importing the
    matcher at top level, the scan premise changes and this must surface."""
    got = _repo_local_top_level_imports(ENGINE_DIR / "agent_activities.py")
    for name in ENFORCEMENT_MODULES:
        if name == "failure_protocol":
            continue  # imported by agent_activities too; keep check explicit below
        assert name in got, (name, sorted(got))
    assert "failure_protocol" in got


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
