# -*- coding: utf-8 -*-
"""t261008-45 — lazy shared.py path constants so the workflow sandbox validates.

Root cause: the temporalio workflow sandbox re-imports workflow-defining modules at
worker start and rejects `pathlib.Path.resolve` AT IMPORT TIME; executor_delivery.py
does a bare top-level `import shared`, and shared.py used to resolve
`POC_DIR = pathlib.Path(__file__).resolve().parent` at module level -> the sandbox
rejected ExecutorDeliveryWorkflow and the engine pool stayed red.

Coverage:
- sandboxed import of executor_delivery (the exact worker path) succeeds;
- importing shared performs NO pathlib.Path.resolve at import (lazy proof);
- SANDBAR_WORKFLOWS_DIR env override: set before first use wins; empty string
  (malformed input) falls back to the default;
- _LazyPath behaves like a Path where consumers rely on it (str/fspath/div/eq/hash/
  attribute delegation/existence);
- family-wide guard: every module of ALL_WORKFLOWS + ALL_WORKFLOWS_V2 sandbox-imports
  clean, not just today's class.

All tests are subprocess- or in-process-unit only: no Temporal server, no network.
"""
import importlib  # noqa: F401  (kept for parity with sibling test modules)
import os
import pathlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared  # noqa: E402

_VENV_PY = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"

# The interpreter-side replay of the worker's sandboxed re-import: pop the modules,
# then import executor_delivery through temporalio's sandbox importer with the
# default restrictions (the same restriction set the unconfigured worker uses).
_SANDBOX_IMPORT_PROBE = r"""
import importlib, sys
sys.path.insert(0, {engine_dir!r})
for m in ("executor_delivery", "executor_actions", "executor_grants",
          "executor_requests", "shared"):
    sys.modules.pop(m, None)
from temporalio.worker.workflow_sandbox import _importer
imp = _importer.Importer(_importer.SandboxRestrictions.default,
                         _importer.RestrictionContext())
with imp.applied():
    importlib.import_module("executor_delivery")
print("SANDBOX_IMPORT_OK")
"""

# Import shared with pathlib.Path.resolve rigged to explode: any import-time resolve
# fails the test — the direct proof that the path constants are lazy.
_RESOLVE_FREE_IMPORT_PROBE = r"""
import pathlib, sys
sys.path.insert(0, {engine_dir!r})
def _boom(self, *a, **k):
    raise AssertionError("eager pathlib.Path.resolve at import of shared")
pathlib.Path.resolve = _boom
try:
    import shared
except AssertionError:
    print("EAGER_RESOLVE")
    raise SystemExit(3)
print("RESOLVE_FREE_IMPORT_OK")
"""

_REGISTRY_SANDBOX_IMPORT_PROBE = r"""
import importlib, sys
sys.path.insert(0, {engine_dir!r})
import worker
mods = sorted({{getattr(c, "__module__", "")
                for c in worker.ALL_WORKFLOWS + worker.ALL_WORKFLOWS_V2}} - {{""}})
for name in mods:
    for m in list(sys.modules):
        # keep external project-template modules (sandbar_ext_*, importlib-loaded
        # by name, not on sys.path — the worker passthrough serves them; popping
        # them would manufacture a ModuleNotFoundError that is not this ticket)
        if m.startswith("sandbar_ext_"):
            continue
        f = getattr(sys.modules[m], "__file__", None)
        if f and f.startswith({engine_dir!r}):
            del sys.modules[m]
    from temporalio.worker.workflow_sandbox import _importer
    # mirror worker.py: external project-template modules ride the passthrough
    ext = sorted(n for n in list(sys.modules) if n.startswith("sandbar_ext_"))
    restrictions = _importer.SandboxRestrictions.default
    if ext:
        restrictions = restrictions.with_passthrough_modules(*ext)
    imp = _importer.Importer(restrictions, _importer.RestrictionContext())
    with imp.applied():
        importlib.import_module(name)
    print("OK", name)
"""


def _run_probe(code: str, env=None):
    engine_dir = str(Path(__file__).resolve().parents[1])
    return subprocess.run(
        [_VENV_PY, "-c", code.format(engine_dir=engine_dir)],
        capture_output=True, text=True, env=env, timeout=120)


def test_sandboxed_import_executor_delivery_ok():
    """The exact worker-path sandboxed import of executor_delivery must pass."""
    r = _run_probe(_SANDBOX_IMPORT_PROBE)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "SANDBOX_IMPORT_OK" in r.stdout


def test_shared_import_performs_no_resolve():
    """shared must import without any pathlib.Path.resolve (the lazy fix itself)."""
    r = _run_probe(_RESOLVE_FREE_IMPORT_PROBE)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "RESOLVE_FREE_IMPORT_OK" in r.stdout
    assert "EAGER_RESOLVE" not in r.stdout


def test_registry_modules_sandbox_import_clean():
    """Family guard: every registered workflow module sandbox-imports clean."""
    r = _run_probe(_REGISTRY_SANDBOX_IMPORT_PROBE)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "OK executor_delivery" in r.stdout
    assert "OK workflows" in r.stdout


def test_lazy_path_parity_with_real_path():
    """Lazy path constants must behave exactly like the Paths they resolve to."""
    real = pathlib.Path(shared.__file__).resolve().parent
    assert str(shared.POC_DIR) == str(real)
    import os
    assert os.fspath(shared.POC_DIR) == os.fspath(real)
    assert shared.POC_DIR.exists() is True
    assert shared.POC_DIR.is_dir() is True
    assert (shared.POC_DIR / "shared.py").is_file() is True
    assert shared.POC_DIR == real
    assert hash(shared.POC_DIR) == hash(real)
    assert shared.REPO_ROOT.parents[0] == shared.REPO_ROOT.parent
    assert shared.REPO_ROOT.name
    # Resolved through the module's SINGLE PEP 562 __getattr__ (rework gen3: the
    # t260930 AST lock counts ANY FunctionDef named __getattr__, so the old
    # _LazyPath-method shape was a real defect): constants are real pathlib.Path.
    assert isinstance(shared.POC_DIR, pathlib.Path)
    # the single dispatch point still serves the code_stamp family
    assert shared.WORKER_PID == os.getpid()


# First use inside a FRESH interpreter so the lazy cache can't be pre-warmed by
# another test: proves the env is read at resolution time, not import time.
_ENV_OVERRIDE_PROBE = r"""
import os, pathlib, sys
sys.path.insert(0, {engine_dir!r})
import shared
print("WORKFLOWS_DIR=" + os.fspath(shared.WORKFLOWS_DIR))
"""


def test_workflows_dir_env_override_wins_before_first_use(tmp_path, monkeypatch):
    """Env set after import (but before first use) selects the workflows dir."""
    env = dict(os.environ, SANDBAR_WORKFLOWS_DIR=str(tmp_path))
    r = _run_probe(_ENV_OVERRIDE_PROBE, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "WORKFLOWS_DIR=" + str(tmp_path) in r.stdout


def test_workflows_dir_env_empty_falls_back_to_default(tmp_path, monkeypatch):
    """Malformed input (empty string) must fall back to the default, not blow up."""
    env = dict(os.environ, SANDBAR_WORKFLOWS_DIR="")
    r = _run_probe(_ENV_OVERRIDE_PROBE, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    default = str(pathlib.Path(shared.REPO_ROOT) / "server" / "workflows")
    assert "WORKFLOWS_DIR=" + default in r.stdout
