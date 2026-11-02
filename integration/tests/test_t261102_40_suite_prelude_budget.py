#!/usr/bin/env python3
"""t261102-40 — the suite prelude's budget and the lane side of its contract.

The end-to-end round (``integration/t261102-40/sc_t261102_40_prelude_named_degrade.py``)
proves the journey. This battery proves the parts a nested round cannot pin
cheaply, offline, in seconds:

* the docker probe is bounded at the batch leg's own bound and memoized once per
  round, so a daemon that does not answer no longer burns the 120 s prune timeout;
* the probe answer matrix (rc≠0, rc=0 with empty stdout, a missing docker binary,
  a timeout) each skips the prunes with one NAMED stderr line and no stdout line;
* the 5-15 s boundary: a daemon that answers inside the bound still yields both
  prunes and the batch stage (the answer is injected, never slept);
* ``lib_suite_prelude``: the three prelude files copied byte-identical, the
  nested env clearing the inherited test-target statement while honouring a
  declared one, the lane-private registry pin, and the named refusal without a
  lane root;
* the lane contract of the three asset-carrying builders (each lane differs from
  the real runner by exactly the injected registry line), the cap comment
  carrying the measured numbers, and the L16 anchor row plus its count.
"""
import contextlib
import difflib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
if str(INTEG) not in sys.path:
    sys.path.insert(0, str(INTEG))

import lib_env  # noqa: E402
import lib_suite_prelude as prelude  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load("rs_t261102_40_under_test", INTEG / "run_scenarios.py")


def _capture(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        value = fn(*a, **kw)
    return value, out.getvalue(), err.getvalue()


def _receipt(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ------------------------------------------------------- the bounded probe ---
class DockerProbeTest(unittest.TestCase):
    """One bounded probe per round feeds both the hygiene and the batch leg."""

    def setUp(self):
        self._probe = dict(rs._DOCKER_PROBE)
        self._batch = dict(rs._BATCH_STATE)
        rs._DOCKER_PROBE.update({"done": False, "up": False, "took": 0.0})

    def tearDown(self):
        rs._DOCKER_PROBE.clear()
        rs._DOCKER_PROBE.update(self._probe)
        rs._BATCH_STATE["project"] = self._batch["project"]
        rs._BATCH_STATE["consumers"] = self._batch["consumers"]

    def test_the_bound_is_the_batch_legs_own_bound(self):
        self.assertEqual(rs._DOCKER_PROBE_S, 20.0,
                         "the probe keeps today's batch-leg bound (20 s)")
        seen = []

        def fake(timeout_s=20):
            seen.append(timeout_s)
            return False

        with mock.patch.object(rs, "_docker_daemon_up", side_effect=fake):
            self.assertFalse(rs._docker_probe()["up"])
            self.assertFalse(rs._docker_probe()["up"])
        self.assertEqual(seen, [20.0],
                         "one probe per process: a second caller reuses the verdict")

    def test_a_daemon_that_answers_inside_the_bound_yields_both_prunes(self):
        """The 5-15 s boundary: the answer is injected, never slept."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append((list(cmd), kw.get("timeout")))
            return _receipt(stdout="")

        with mock.patch.object(rs, "_docker_daemon_up",
                               side_effect=lambda timeout_s=20: True), \
                mock.patch.object(rs.subprocess, "run", side_effect=fake_run):
            _, out, err = _capture(rs._docker_hygiene)
        self.assertEqual(out, "", "the hygiene leg never writes to stdout")
        self.assertEqual(err, "", "a healthy daemon needs no skip line")
        self.assertEqual([c[1] for c in calls], [120, 60],
                         "both prunes keep today's bounds")
        self.assertEqual([c[0][1] for c in calls], ["container", "network"])

    def test_no_answer_skips_the_prunes_and_names_the_skip(self):
        with mock.patch.object(rs, "_docker_daemon_up",
                               side_effect=lambda timeout_s=20: False), \
                mock.patch.object(rs.subprocess, "run",
                                  side_effect=AssertionError("no prune may run")):
            _, out, err = _capture(rs._docker_hygiene)
        self.assertEqual(out, "", "stdout stays byte-stable for the cases that read it")
        self.assertIn("docker-hygiene:", err)
        self.assertIn("did not answer within 20s", err)
        self.assertIn("skipped this round", err)
        self.assertIn("never a gate", err)

    def test_the_probe_matrix_is_total(self):
        cases = [
            ("rc!=0", _receipt(stdout="", returncode=1), False),
            ("empty stdout", _receipt(stdout="  \n", returncode=0), False),
            ("answer", _receipt(stdout="29.4.0\n", returncode=0), True),
        ]
        for label, proc, want in cases:
            with mock.patch.object(rs.subprocess, "run", side_effect=lambda *a, **k: proc):
                self.assertIs(rs._docker_daemon_up(), want, label)
        for label, exc in (("missing docker", OSError("no docker")),
                           ("timeout", rs.subprocess.TimeoutExpired("docker", 20))):
            with mock.patch.object(rs.subprocess, "run", side_effect=exc):
                self.assertFalse(rs._docker_daemon_up(), label)

    def test_the_verdict_is_shared_with_the_batch_leg(self):
        seen = []

        def fake(timeout_s=20):
            seen.append(timeout_s)
            return False

        entry = ("fx-entry", "intent", "python3 integration/fx.py", "engine")
        with mock.patch.object(rs, "_docker_daemon_up", side_effect=fake):
            _capture(rs._docker_hygiene)
            ok, out, _ = _capture(rs.batch_preboot, [entry])
        self.assertTrue(ok, "no daemon is a named skip, not a refusal")
        self.assertEqual(seen, [20.0],
                         "the hygiene leg and the batch leg share one probe")
        self.assertIn("docker daemon 未就绪", out)

    def test_an_answering_daemon_lets_the_batch_leg_set_up(self):
        ensure = _receipt(stdout=json.dumps({"project": "p", "state": "up",
                                             "ports": {"temporal": 21101}}) + "\n")
        entry = ("fx-entry", "intent", "python3 integration/fx.py", "engine")
        with mock.patch.object(rs, "_docker_daemon_up",
                               side_effect=lambda timeout_s=20: True), \
                mock.patch.object(rs.subprocess, "run", return_value=ensure) as run:
            ok, out, _ = _capture(rs.batch_preboot, [entry])
        self.assertTrue(ok, "an answering daemon keeps today's batch stage")
        self.assertTrue(rs._BATCH_STATE["project"], "the batch project is recorded")
        self.assertIn("ensure", run.call_args[0][0])
        self.assertNotIn("未就绪", out)


# ------------------------------------------------ the nested-suite env face ---
class NestedEnvTest(unittest.TestCase):
    """The nested env clears the inherited statement and pins the registry."""

    KEYS = prelude.SUITE_TARGET_ENV_NAMES

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for key in self.KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_the_nested_env_clears_the_inherited_statement(self):
        for key in self.KEYS:
            os.environ[key] = "inherited-%s" % key
        env = prelude.nested_suite_env({}, "/tmp/lane-x")
        for key in self.KEYS:
            self.assertNotIn(key, env,
                             "a nested suite resolves its own target: %s" % key)

    def test_a_declared_statement_survives_the_clear(self):
        os.environ[prelude.SUITE_TARGET_ENV_NAMES[0]] = "inherited"
        env = prelude.nested_suite_env(
            {"SANDBAR_TARGET_HOST": "127.0.0.1:12345"}, "/tmp/lane-x")
        self.assertEqual(env["SANDBAR_TARGET_HOST"], "127.0.0.1:12345",
                         "strip then inject: a declared target wins")

    def test_the_registry_is_pinned_under_the_lane(self):
        env = prelude.nested_suite_env({}, "/tmp/lane-y")
        self.assertEqual(env[prelude.BENCH_REGISTRY_ENV],
                         "/tmp/lane-y/%s" % prelude.REGISTRY_DIRNAME,
                         "a fixture never sweeps the host-wide registry")

    def test_a_missing_lane_root_is_a_named_refusal(self):
        with self.assertRaises(ValueError) as ctx:
            prelude.nested_suite_env({}, None)
        self.assertIn("lane_root is required", str(ctx.exception))

    def test_the_shared_cleaning_point_still_keeps_the_three_names(self):
        """The clearing lives in the helper, not in lib_env (plan option b)."""
        for key in self.KEYS:
            os.environ[key] = "kept-%s" % key
        env = lib_env.clean_narrowing_env()
        for key in self.KEYS:
            self.assertIn(key, env,
                          "lib_env must not strip it: other cases name what they "
                          "strip (%s)" % key)


# ------------------------------------------------------ the prelude assets ---
class PreludeAssetsTest(unittest.TestCase):

    def test_the_three_assets_copy_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "integration"
            copied = prelude.copy_prelude_assets(dst)
            self.assertEqual(sorted(copied), sorted(prelude.PRELUDE_FILES))
            self.assertEqual(sorted(prelude.PRELUDE_FILES),
                             ["batch_stage_exceptions.json", "bench_deadman.py",
                              "process_bench.py"])
            for name in prelude.PRELUDE_FILES:
                self.assertEqual((dst / name).read_bytes(),
                                 (INTEG / name).read_bytes(), name)

    def test_a_missing_source_is_named_never_skipped(self):
        saved = prelude.PRELUDE_FILES
        prelude.PRELUDE_FILES = saved + ("no_such_prelude_file.py",)
        try:
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(AssertionError) as ctx:
                    prelude.copy_prelude_assets(Path(td) / "integration")
            self.assertIn("no_such_prelude_file.py", str(ctx.exception))
        finally:
            prelude.PRELUDE_FILES = saved


# --------------------------------------------------------- the lane family ---
class LaneContractTest(unittest.TestCase):
    """Each asset-carrying lane carries the prelude files, one copy spelling."""

    def _lane(self, key, root):
        if key == "t261024-40":
            lib = _load("lib_lane_261024_40_t102",
                        INTEG / "t261024-40" / "lib_t26102440_lane.py")
            return lib.build_lane(root, [("fx-main", "main")])
        if key == "t261025-02":
            lib = _load("lib_lane_261025_02_t102",
                        INTEG / "t261025-02" / "lib_t26102502_lane.py")
            return lib.build_lane(root)
        lib = _load("lib_lane_260913_03_t102",
                    INTEG / "t260913-03" / "lib_pool_exclude_lane.py")
        return lib.build_lane(root, [("fx-main", "main", True)])

    def test_every_asset_lane_carries_the_prelude_files(self):
        src_lines = Path(rs.__file__).read_text(
            encoding="utf-8").splitlines(keepends=True)
        for key in ("t261024-40", "t261025-02", "t260913-03"):
            with tempfile.TemporaryDirectory() as td:
                lane = self._lane(key, Path(td))
                integ = Path(lane["lane"]) / "integration"
                for name in prelude.PRELUDE_FILES:
                    self.assertTrue((integ / name).is_file(),
                                    "%s lane must carry %s" % (key, name))
                    self.assertEqual((integ / name).read_bytes(),
                                     (INTEG / name).read_bytes(),
                                     "%s lane copies %s verbatim" % (key, name))
                got = (integ / "run_scenarios.py").read_text(
                    encoding="utf-8").splitlines(keepends=True)
                added = [ln for ln in difflib.unified_diff(src_lines, got, n=0)
                         if ln.startswith("+") and not ln.startswith("+++")]
                self.assertEqual(len(added), 2,
                                 "the runner copy differs by the injected "
                                 "registry line and its blank line only (%s)" % key)
                self.assertTrue(added[0].startswith("+SCENARIOS = "),
                                "the ONE difference is the injected registry (%s)"
                                % key)

    def test_the_lane_libs_call_the_shared_helper(self):
        """One spelling: each lane calls the helper or re-exports the driver
        that does (t261025-02 re-exports SIB.run_executor, which nests it)."""
        for rel in ("integration/t261024-40/lib_t26102440_lane.py",
                    "integration/t261025-02/lib_t26102502_lane.py",
                    "integration/t260913-03/lib_pool_exclude_lane.py"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("copy_prelude_assets", text, rel)
            self.assertTrue(
                "nested_suite_env" in text or "run_executor = SIB.run_executor" in text,
                "%s must build the nested env through the one helper" % rel)


# ------------------------------------------------- caps and the anchor rows ---
class CapCommentLockTest(unittest.TestCase):

    def test_the_cap_stays_a_hang_guard_with_the_measured_numbers(self):
        lib = (INTEG / "t261024-40" / "lib_t26102440_lane.py").read_text(
            encoding="utf-8")
        cap = 120
        self.assertIn("timeout=%d" % cap, lib,
                      "the %d s cap stays (the hang guard, not a performance assertion)" % cap)
        self.assertIn("140.2", lib, "the gate's measured pre-fix wall is recorded")
        self.assertIn("about 5x", lib, "the cap is stated relative to the measurement")
        runner = (INTEG / "run_scenarios.py").read_text(encoding="utf-8")
        for token in ("140.2", "0.21", "0.04", "2.97", "120 s", "_DOCKER_PROBE_S"):
            self.assertIn(token, runner, "the measured numbers travel with the code")


    def test_the_nested_prelude_bound_has_one_spelling(self):
        self.assertEqual(prelude.PRELUDE_BOUND_S, 30.0)
        for rel in ("integration/t261024-40/lib_t26102440_lane.py",
                    "integration/t261102-40/lib_t26110240_lane.py"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertRegex(
                text, r"PRELUDE_BOUND_S = (suite_prelude|PRELUDE)\.PRELUDE_BOUND_S",
                "%s must take the bound from the one contract module" % rel)


class AnchorManifestTest(unittest.TestCase):
    OWN = "t261102-40-prelude-named-degrade"
    REL = "integration/t261102-40/sc_t261102_40_prelude_named_degrade.py"

    def test_the_own_entry_is_registered_with_its_pool_and_budget(self):
        names = [e[0] for e in rs.SCENARIOS]
        self.assertIn(self.OWN, names)
        row = rs.SCENARIOS[names.index(self.OWN)]
        self.assertEqual(rs.pool_of(row), "ro")
        self.assertEqual(rs.entry_budget_s(row), 240)
        self.assertIn(self.REL, str(row[2]))

    def test_the_anchor_row_and_the_count_agree(self):
        man = json.loads((INTEG / "test_anchors.json").read_text(encoding="utf-8"))
        self.assertIn(self.REL, man["scenarios"])
        self.assertEqual(man["scenarios"][self.REL]["anchor"], "behaviour")
        self.assertEqual(man["_header"]["labelled_counts"]["scenarios"],
                         len(man["scenarios"]),
                         "the hand-kept count matches the rows it counts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
