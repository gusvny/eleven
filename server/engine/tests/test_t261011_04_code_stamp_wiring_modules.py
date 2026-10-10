"""t261011-04: the code stamp must cover the workflow body and the wiring.

Root cause (ticket body): t261009-50 (d4837baf) landed the line-round wiring in
``workflows.py`` (dispatch-scan body calls ``line_round_tick_engine``) and
``activities.py`` (top-level import + activity registration), but neither file
was in ``shared.CODE_STAMP_MODULES`` — so a worker whose loaded copy predated
the wiring reported ``stale=none`` while a fired dispatcher-scan produced a
complete, plausible scan return value with NO ``line_rounds`` key at all
(silent stale worker, measured live 261011). Precedent: t261004-07 (same class,
enforcement modules).

This module pins, at the pure stamp-computation layer (L1):
1. the four wiring/body modules (``workflows``, ``activities``,
   ``develop_certify``, ``develop_line``) are tracked in ``CODE_STAMP_MODULES``
   and surface as stale, by name, when their on-disk mtime is newer than the
   worker's start baseline — in ``stale``, in ``modules[name]``, and in the
   one-line stamp the operator face renders;
2. the stamp contract still holds for them: unreadable/missing mtime is NOT
   stale but keeps its mtime field empty (named by the empty field);
3. guard rails on the wiring markers themselves: if the tick call/registration
   moves out of ``workflows.py``/``activities.py`` the test names it instead of
   passing silently (same discipline as the t261004-07 tripwire guard).

Run: ``python3 -m pytest server/engine/tests/test_t261011_04_code_stamp_wiring_modules.py -q``
(stdlib + pytest only; no network, no real Temporal, no integration entry).
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared  # noqa: E402

TICKET = "t261011-04"

#: The wiring/body modules this ticket adds to the stamp.
WIRING_MODULES = ("workflows", "activities", "develop_certify", "develop_line")

TRACKED = dict(shared.CODE_STAMP_MODULES)

#: Engine dir, for the wiring-marker guard rails.
ENGINE_DIR = Path(__file__).resolve().parent.parent

OLD_BASELINE = "2020-01-01T00:00:00"  # predates any on-disk mtime => all stale


def test_wiring_modules_are_tracked_with_worker_paths():
    for name in WIRING_MODULES:
        assert name in TRACKED, (
            "%s is not in CODE_STAMP_MODULES: a worker stale only on the wiring "
            "reports stale=none (t261011-04 regression)" % name)
        assert TRACKED[name] == "server/engine/%s.py" % name


def test_stale_wiring_module_is_named_on_the_stamp():
    stamp = shared.worker_code_stamp(
        mtime_fn=lambda p: 9e9, started_at=OLD_BASELINE, pid=123)
    for name in WIRING_MODULES:
        assert name in stamp["stale"], (name, stamp["stale"])
        m = stamp["modules"][name]
        assert m["stale"] is True
        assert m["role"] == "worker-loaded", (name, m["role"])
        assert m["path"].endswith("server/engine/%s.py" % name)
    # The operator-facing one-liner must name the module, not just a count.
    for name in WIRING_MODULES:
        assert name in stamp["stamp_line"], (name, stamp["stamp_line"])


def test_baseline_after_mtime_is_not_stale():
    # A fresh worker (baseline newer than any mtime we hand out) is clean.
    stamp = shared.worker_code_stamp(
        mtime_fn=lambda p: 0.0, started_at="2030-01-01T00:00:00", pid=7)
    for name in WIRING_MODULES:
        assert name not in stamp["stale"]
        assert stamp["modules"][name]["stale"] is False


def test_unreadable_mtime_is_not_stale_but_named_by_empty_field():
    stamp = shared.worker_code_stamp(
        mtime_fn=lambda p: (_ for _ in ()).throw(ValueError("boom")),
        started_at=OLD_BASELINE, pid=1)
    assert stamp["stale"] == []
    for name in WIRING_MODULES:
        m = stamp["modules"][name]
        assert m["stale"] is False
        assert m["mtime"] == ""


def test_missing_file_is_not_stale_and_does_not_crash():
    # Malformed environment: repo root without the engine files at all.
    stamp = shared.worker_code_stamp(repo_root="/nonexistent-t261011-04",
                                     started_at=OLD_BASELINE, pid=2)
    for name in WIRING_MODULES:
        assert name not in stamp["stale"], (name, stamp["stale"])
        assert stamp["modules"][name]["mtime"] == ""
        assert stamp["modules"][name]["stale"] is False


def test_partial_mtime_failures_do_not_poison_the_rest():
    # Only `workflows` unreadable: the other wiring modules must still be named.
    def _mt(p):
        if str(p).endswith("workflows.py"):
            raise ValueError("boom")
        return 9e9

    stamp = shared.worker_code_stamp(mtime_fn=_mt, started_at=OLD_BASELINE, pid=3)
    assert "workflows" not in stamp["stale"]
    for name in WIRING_MODULES:
        if name != "workflows":
            assert name in stamp["stale"], (name, stamp["stale"])


def _repo_local_top_level_imports(py_file: Path) -> set:
    """Same rule as the t261004-07 tripwire: column-0 imports only."""
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


def test_wiring_markers_still_live_where_the_stamp_expects_them():
    """If the tick call/registration moves, this names it instead of passing.

    The stamp entries above are only meaningful while workflows.py carries the
    dispatch-scan body branch and activities.py carries the tick registration.
    """
    wf_text = (ENGINE_DIR / "workflows.py").read_text(encoding="utf-8")
    assert "line_round_tick_engine" in wf_text, (
        "workflows.py no longer references line_round_tick_engine: the stamp "
        "entry's justification is stale — move/extend the CODE_STAMP_MODULES "
        "entry with the ticket that moved the wiring")
    act_text = (ENGINE_DIR / "activities.py").read_text(encoding="utf-8")
    assert "line_round_tick_engine" in act_text, (
        "activities.py no longer references line_round_tick_engine")
    assert "develop_certify" in _repo_local_top_level_imports(
        ENGINE_DIR / "activities.py"), (
        "activities.py stopped importing develop_certify at top level")
    # develop_line is lazily imported (from develop_certify) — the tripwire scan
    # cannot see it, which is exactly why it is tracked explicitly.
    assert "develop_line" not in _repo_local_top_level_imports(
        ENGINE_DIR / "activities.py")
    assert "develop_line" in TRACKED


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
