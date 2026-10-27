# -*- coding: utf-8 -*-
"""t261003-05 — registry interpreter resolution for engine-importing scenarios.

Incident: `t261002-13-tmp-alarm-owner-receipt` really scans the engine's
`activities.scan_tmp_fixture_dirs` (needs temporalio), but its registry cmd ran
a bare `python3` — every gate round landed an ENV_FAIL in 0.1 s (a phantom
env-red; the scenario's own assertions never ran).

The convention has since moved twice and this battery follows it (t261026-35,
Integration finding 261026): the per-entry inline shim
`PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B ...`
resolved cwd-relative and had no tier past it, so a line-round clone without its
own venv still died with "No module named temporalio". Today there is ONE rule,
`integration/py_interp.sh` (enforced by lint L29: an engine-importing python leg
must launch through it, never through a bare interpreter). Its tiers are
$SANDBAR_POC_PYTHON > the tree's venv > the main checkout's venv > python3, and
it names the chosen interpreter on stderr.

This battery pins three faces against the REAL shim (no copy of its logic):
  1. registry face: the entry's cmd launches through `sh integration/py_interp.sh`
     — never a bare interpreter, never the retired inline shim;
  2. shim semantics, driven end to end with real processes: the tree venv wins
     when it exists, a tree with no venv falls through to python3, and a
     set-but-unusable pointer is NAMED on stderr and falls through (never a
     silent pick, never a hard failure);
  3. asset face: the cmd's scenario script exists in the tree (a renamed script
     must not leave a dumb entry behind).

The three-state contract is not re-verified here (running a scenario script is
the integration no-run face): with no usable venv the scenario itself still
ENV_FAILs with exit 2, carried by the scenario's docstring and the gate round.
"""
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
RUN_SCENARIOS = REPO / "integration" / "run_scenarios.py"
PY_INTERP = "integration/py_interp.sh"
SCENARIO = REPO / "integration" / "t261002-13" / "sc_tmp_alarm_owner_receipt.py"
ENTRY = "t261002-13-tmp-alarm-owner-receipt"
VENV_PY = "server/engine/.venv/bin/python"

#: The ONE interpreter rule (t261026-35). Its cmd shape is a launch through the
#: shim; every other engine-importing entry carries the same prefix.
SHIM = "sh %s " % PY_INTERP


def _registry_cmds():
    """Read the registry mechanically from the tree under test (never hand-copied).

    ast is used to take only the SCENARIOS literal, without exec-ing the module
    body (its module-level code needs the rest of the import face and would blow
    up with an unrelated NameError).
    """
    import ast
    tree = ast.parse(RUN_SCENARIOS.read_text(encoding="utf-8"))
    rows = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "SCENARIOS" for t in node.targets
        ):
            rows = ast.literal_eval(node.value)
            break
    assert rows is not None, "SCENARIOS table not found in run_scenarios.py"
    return {row[0]: row[2] for row in rows}


def test_registry_entry_uses_the_suite_interpreter_rule():
    """The entry must launch through the one resolution rule, never an ambient
    python (the incident shape) and never the retired inline shim."""
    cmd = _registry_cmds()[ENTRY]
    assert cmd.startswith(SHIM), \
        "registry entry must launch through %s, got: %r" % (PY_INTERP, cmd)
    assert SCENARIO.name in cmd
    # the incident shape itself: a bare interpreter, whatever python it resolves to
    assert not cmd.startswith("python3 "), "bare python3 is the defect being pinned"
    assert not cmd.startswith("python "), "bare python is the defect being pinned"
    # the retired per-entry inline shim: a second copy of the resolution logic is
    # exactly the drift L29 replaced with one rule
    assert "PY=" not in cmd, "the inline venv-fallback shim is retired (one rule only)"
    # ...and the rule it delegates to must keep its floor: no venv, no env
    # pointer still resolves, or the entry silently requires an ambient python.
    shim = (REPO / PY_INTERP).read_text(encoding="utf-8")
    assert 'py="python3"' in shim, "the python3 floor must stay inside the rule"
    assert "server/engine/.venv/bin/python" in shim, \
        "the tree-venv tier must stay inside the rule"


def test_scenario_file_exists():
    assert SCENARIO.is_file(), "cmd points at a missing scenario file (dumb entry)"


def _resolve(argv_tail=("-c", "import sys;print(sys.executable)"), pointer=None,
             cwd=None):
    """Run the REAL shim and return (chosen interpreter line on stderr, stdout).

    The ambient $SANDBAR_POC_PYTHON is dropped so the case judges its own tiers.
    """
    env = dict(os.environ)
    env.pop("SANDBAR_POC_PYTHON", None)
    if pointer is not None:
        env["SANDBAR_POC_PYTHON"] = str(pointer)
    r = subprocess.run(["sh", str(REPO / PY_INTERP)] + list(argv_tail),
                       cwd=str(cwd or REPO), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    named = [ln for ln in r.stderr.splitlines() if ln.startswith("py_interp: interpreter=")]
    assert len(named) == 1, "the rule must name its pick once: %r" % r.stderr
    return named[0].split("=", 1)[1], r.stdout.strip()


def test_shim_prefers_engine_venv_when_present():
    if not (REPO / VENV_PY).is_file():
        import pytest
        pytest.skip("engine venv absent in this tree")
    chosen, out = _resolve()
    assert chosen.endswith(VENV_PY), chosen
    assert out.endswith(VENV_PY), "the interpreter that actually ran must be the venv one"


def test_shim_falls_back_when_no_venv_in_tree(tmp_path):
    """A clone/worktree with no venv of its own and no checkout to borrow from
    drops to python3 — loudly (the floor that keeps a bare tree runnable)."""
    chosen, out = _resolve(cwd=tmp_path)
    assert chosen == "python3", chosen
    assert os.path.basename(out).startswith("python3"), out


def test_shim_falls_back_when_pointer_not_executable(tmp_path):
    """An unusable $SANDBAR_POC_PYTHON is NAMED on stderr, never silently taken
    and never a hard refusal (t261011-18 could-not-run naming discipline)."""
    stub = tmp_path / "python"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o644)  # exists but not executable: -x says false
    env = dict(os.environ)
    env.pop("SANDBAR_POC_PYTHON", None)
    env["SANDBAR_POC_PYTHON"] = str(stub)
    r = subprocess.run(["sh", str(REPO / PY_INTERP),
                        "-c", "import sys;print(sys.executable)"],
                       cwd=str(tmp_path), capture_output=True, text=True,
                       timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    assert str(stub) in r.stderr, "an unusable pointer must be named: %r" % r.stderr
    assert "py_interp: interpreter=python3" in r.stderr, r.stderr
    assert os.path.basename(r.stdout.strip()).startswith("python3"), r.stdout
