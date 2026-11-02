#!/usr/bin/env python3
"""Lane-side contract of the suite prelude (ticket t261102-40).

A fixture lane copies ``integration/run_scenarios.py`` verbatim, so the lane must
also carry the files the runner's prelude reads and imports. Keeping that list in
one place is the rule this module exists for: every lane used to keep its own
hand-written copy set, the sets drifted, and the nested run crashed instead of
degrading (the incident this ticket fixes).

Three members:

* ``copy_prelude_assets(integ_dir)`` copies ``PRELUDE_FILES`` into a lane's
  ``integration/`` directory. A missing source is a NAMED ``AssertionError``; the
  function never skips a file silently.
* ``pin_bench_registry(env, lane_root)`` points a nested run's bench registry at
  the lane. The default registry lives in the shared temp directory, so a fixture
  must never sweep a host-wide registry (KI-161 discipline: never the production
  store).
* ``nested_suite_env(extra, lane_root)`` builds the env for a nested suite run.
  It clears the three test-target keys a parent round states for its children,
  because a nested suite must resolve its own target: the parent's statement
  would send the nested prelude down the ambient branch and hide the very
  degradation this ticket proves. A caller that wants a stated target injects its
  own through ``extra`` (strip-then-inject, the same rule as ``lib_env``).

The order inside ``nested_suite_env`` is load-bearing: clean, then clear the
inherited target, then apply the caller's extras, then pin the registry. Applying
the extras before the clear would strip a caller's declared target.
"""
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import lib_env  # noqa: E402  (one cleaning point, lint L12)

#: The files the runner's prelude reads or imports. ``run_scenarios.py`` itself is
#: copied by each lane together with its own registry injection, so it is not
#: listed here.
PRELUDE_FILES = (
    "process_bench.py",             # imported by _bench_module()
    "bench_deadman.py",             # the shim process_bench starts, one line below
    "batch_stage_exceptions.json",   # read by batch_exception_entries()
)

#: The three keys a parent suite round states on its children (run_scenarios.py
#: TEST_TARGET_ENV / TEST_TARGET_SOURCE_ENV / TEST_NAMESPACE_ENV).
SUITE_TARGET_ENV_NAMES = (
    "SANDBAR_TARGET_HOST",
    "SANDBAR_SUITE_STATED_TARGET",
    "SANDBAR_NAMESPACE",
)

#: The bench registry knob and the lane-local directory name (process_bench.py
#: REGISTRY_ENV / registry_dir()).
BENCH_REGISTRY_ENV = "SANDBAR_BENCH_REGISTRY"
REGISTRY_DIRNAME = ".sandbar-bench-registry"

#: The nested prelude bound the fixtures assert (t261102-40 rule 3). The worst
#: lawful prelude is one bounded docker probe (20 s, the batch leg's own bound)
#: plus the stub stage sweep and the runner import (about 2 s), so 30 s leaves
#: host slack. The pre-fix wall was 140.2 s (the gate's number). The 120 s cap a
#: fixture passes to `subprocess.run` stays a HANG guard, never a performance
#: assertion.
PRELUDE_BOUND_S = 30.0


def copy_prelude_assets(integ_dir):
    """Copy the prelude files from the real ``integration/`` into a lane.

    Returns the names copied. Raises ``AssertionError`` naming the file when the
    real tree does not carry it: a lane that silently drops an asset is the
    defect class this helper exists to stop.
    """
    dst_dir = Path(integ_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in PRELUDE_FILES:
        src = _HERE / name
        if not src.is_file():
            raise AssertionError(
                "lane prelude asset missing from the real tree: %s - the lane "
                "cannot carry the runner's file contract" % src)
        shutil.copy2(str(src), str(dst_dir / name))
        copied.append(name)
    return copied


def pin_bench_registry(env, lane_root):
    """Point a nested run's bench registry at the lane root (never the host default)."""
    if lane_root is None:
        raise ValueError(
            "pin_bench_registry: lane_root is required - a nested bench must not "
            "use the host-wide registry")
    env[BENCH_REGISTRY_ENV] = str(Path(lane_root) / REGISTRY_DIRNAME)
    return env


def nested_suite_env(extra=None, lane_root=None):
    """Env for a nested suite run: cleaned, target cleared, extras, registry pin.

    ``extra`` is applied AFTER the clear, so a lane that wants a stated target
    keeps its own value. ``lane_root`` is required: without it the bench registry
    would fall back to the host-wide directory.
    """
    env = lib_env.clean_narrowing_env()
    for name in SUITE_TARGET_ENV_NAMES:
        env.pop(name, None)
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return pin_bench_registry(env, lane_root)
