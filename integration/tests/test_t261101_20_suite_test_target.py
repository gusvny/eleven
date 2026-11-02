#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261101-20 — the suite's test-target hand-off, at the seam of its own module.

The defect: ``integration/run_scenarios.py`` stated
``SANDBAR_TARGET_HOST=127.0.0.1:17233`` for every scenario child while nothing
listened on that address (the docker test bench retired 261027). The statement
was false, and any case that took it at its word booked a NAMED ENV_FAIL.

What this battery drives (the REAL run_scenarios module, a FAKE bench module -
no process, no port, no Temporal, offline seconds):

A an address the environment states is kept verbatim: no marker, no bench;
B with no ambient statement the suite starts the bench ON the address it
  states (TEST_TARGET_DEFAULT, the value lib_inspection whitelists and the
  stripping case compares literally) and every child env carries the address,
  the ``SANDBAR_SUITE_STATED_TARGET`` marker and the namespace the bench serves;
C an address that already answers is stated and never stopped;
D a bench that REFUSES states NOTHING and names the failed check — the child
  env gets no address at all, so the case that needs one books its own named
  ENV_FAIL and never a dead address;
E the teardown judges the residue from the outside (port refuses, pid gone,
  temp dir reclaimed) and publishes a non-clean block as RESIDUE;
F the wiring and the cross-face constants are locked by source, so a refactor
  cannot drop the provision, the injection or the teardown silently, and a
  changed address reds HERE instead of failing a child at runtime.

Standalone (``unittest``, like the other batteries the registry runs with plain
``python3``), and collected by pytest as well. No integration entry is executed
here (developer-stage enforcement honoured).
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load("rs_t261101_20_under_test", "integration/run_scenarios.py")
pb = _load("pb_t261101_20_under_test", "integration/process_bench.py")


def _empty_state():
    return {"resolved": False, "value": "", "source": "", "note": "",
            "port": 0, "pid": 0, "db": "", "start_s": None,
            "down": None, "stopped": False}


class FakeBench(object):
    """The three faces run_scenarios needs from process_bench, recorded."""

    NAMESPACE = "default"

    def __init__(self, refuses=True, start=None, stop_block=None):
        self.refuses = refuses
        self.start_result = start if start is not None else {
            "ok": True, "port": 17233, "pid": 4242, "start_s": 0.12,
            "db": "/tmp/sandbar-bench-test/temporal.db"}
        self.stop_block = stop_block if stop_block is not None else {
            "clean": True, "port_refuses": True, "pid_alive": False,
            "db_removed": True, "stopped_s": 1.0, "escalated": False}
        self.probes = []
        self.starts = []
        self.stops = []

    def port_refuses(self, port, probe_s=None):
        self.probes.append(port)
        return self.refuses

    def start(self, port=None, **kw):
        self.starts.append(port)
        return dict(self.start_result)

    def stop(self, port=None, pid=None, db=None, **kw):
        self.stops.append({"port": port, "pid": pid, "db": db})
        return dict(self.stop_block)


class TargetCase(unittest.TestCase):
    """One fresh resolution per test; stderr is captured for the receipt lines."""

    def setUp(self):
        self._saved_state = rs._TEST_TARGET
        self._saved_bench = rs._BENCH
        self._saved_env = {k: os.environ.get(k) for k in
                           (rs.TEST_TARGET_ENV, rs.TEST_TARGET_SOURCE_ENV,
                            rs.TEST_NAMESPACE_ENV)}
        for key in self._saved_env:
            os.environ.pop(key, None)
        rs._TEST_TARGET = _empty_state()

    def tearDown(self):
        rs._TEST_TARGET["stopped"] = True
        rs._TEST_TARGET = self._saved_state
        rs._BENCH = self._saved_bench
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # -- helpers -----------------------------------------------------------
    def use(self, fake=None, **kw):
        fake = fake if fake is not None else FakeBench(**kw)
        rs._BENCH = {"mod": fake}
        return fake

    def captured(self, fn):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            value = fn()
        return value, buf.getvalue()


# ---------------------------------------------------------------- A ambient --
class AmbientStatementTest(TargetCase):

    def test_an_address_the_environment_states_is_kept_verbatim(self):
        fake = self.use()
        os.environ[rs.TEST_TARGET_ENV] = "127.0.0.1:12345"
        st, err = self.captured(rs._provision_test_target)
        self.assertEqual(st["source"], "ambient")
        self.assertEqual(st["value"], "127.0.0.1:12345")
        self.assertEqual(fake.starts, [])
        self.assertEqual(fake.stops, [])
        self.assertEqual(fake.probes, [],
                         "no probe is needed when the environment states it")
        self.assertIn("[provision] SANDBAR_TARGET_HOST=127.0.0.1:12345", err)

    def test_an_ambient_statement_marks_nothing_and_is_never_stopped(self):
        fake = self.use()
        os.environ[rs.TEST_TARGET_ENV] = "127.0.0.1:12345"
        self.captured(rs._provision_test_target)
        child = {}
        rs._apply_test_target_env(child)
        self.assertEqual(child, {},
                         "a deployment statement is not re-stated by the suite")
        self.captured(rs._teardown_test_target)
        self.assertEqual(fake.stops, [],
                         "a target the suite did not start is never stopped")


# ------------------------------------------------------------------ B bench --
class BenchProvisionTest(TargetCase):

    def test_the_suite_brings_the_bench_up_on_the_address_it_states(self):
        fake = self.use(refuses=True)
        st, err = self.captured(rs._provision_test_target)
        self.assertEqual(st["source"], "bench")
        self.assertEqual(st["value"], rs.TEST_TARGET_DEFAULT)
        self.assertEqual(rs.TEST_TARGET_DEFAULT, "127.0.0.1:17233")
        self.assertEqual(fake.probes, [17233],
                         "the probe asks about the stated address")
        self.assertEqual(fake.starts, [17233],
                         "the bench is started ON the stated address - not a "
                         "random free port, because lib_inspection whitelists "
                         "this value and the stripping case compares it")
        self.assertEqual(st["pid"], 4242)
        self.assertTrue(st["db"].endswith("temporal.db"))
        self.assertIn("the suite started the process bench", err)
        self.assertIn("pid=4242", err)

    def test_every_child_env_carries_the_bench_the_marker_and_the_namespace(self):
        self.use(refuses=True)
        self.captured(rs._provision_test_target)
        child = {}
        rs._apply_test_target_env(child)
        self.assertEqual(child[rs.TEST_TARGET_ENV], "127.0.0.1:17233")
        self.assertEqual(child[rs.TEST_TARGET_SOURCE_ENV], "127.0.0.1:17233",
                         "the provenance marker is the value the suite stated: "
                         "a case whose tested face IS the target strips it")
        self.assertEqual(child[rs.TEST_NAMESPACE_ENV], "default",
                         "the bench serves one namespace; a child that asks "
                         "for another would die with 'Namespace not found'")
        self.assertEqual(rs.TEST_TARGET_NAMESPACE, pb.NAMESPACE,
                         "the stated namespace is the one the bench serves")

    def test_a_child_that_already_states_a_namespace_keeps_it(self):
        self.use(refuses=True)
        self.captured(rs._provision_test_target)
        child = {rs.TEST_NAMESPACE_ENV: "sandbar-test"}
        rs._apply_test_target_env(child)
        self.assertEqual(child[rs.TEST_NAMESPACE_ENV], "sandbar-test")

    def test_the_resolution_happens_once_per_process(self):
        fake = self.use(refuses=True)
        self.captured(rs._provision_test_target)
        self.captured(rs._provision_test_target)
        self.assertEqual(fake.starts, [17233],
                         "a second call reuses the first resolution")


# ----------------------------------------------------------------- C reused --
class AlreadyAnsweringTest(TargetCase):

    def test_an_address_that_already_answers_is_stated_and_never_stopped(self):
        fake = self.use(refuses=False)
        st, err = self.captured(rs._provision_test_target)
        self.assertEqual(st["source"], "reused")
        self.assertEqual(st["value"], "127.0.0.1:17233")
        self.assertEqual(fake.starts, [],
                         "a live bench is not this suite's to replace")
        child = {}
        rs._apply_test_target_env(child)
        self.assertEqual(child[rs.TEST_TARGET_SOURCE_ENV], "127.0.0.1:17233")
        self.captured(rs._teardown_test_target)
        self.assertEqual(fake.stops, [],
                         "a bench the suite did not start is never stopped")
        self.assertIn("already answers", err)


# ----------------------------------------------------------------- D absent --
class RefusedBenchTest(TargetCase):

    def test_a_refused_bench_states_nothing_and_names_the_failed_check(self):
        self.use(refuses=True,
                 start={"ok": False,
                        "reason": "temporal binary not found: /repo/x"})
        st, err = self.captured(rs._provision_test_target)
        self.assertEqual(st["source"], "absent")
        self.assertEqual(st["value"], "",
                         "no address is stated when no bench answers")
        self.assertIn("temporal binary not found: /repo/x", st["note"])
        self.assertIn("NO TEST TARGET", err)
        self.assertIn("temporal binary not found: /repo/x", err)
        child = {}
        rs._apply_test_target_env(child)
        self.assertEqual(child, {},
                         "the child is never handed a dead address; it states "
                         "its own named ENV_FAIL instead")
        face = rs._test_target_face()
        self.assertIsNone(face["value"])
        self.assertEqual(face["source"], "absent")
        self.assertEqual(face["absent_reason"], st["note"])

    def test_a_refused_bench_leaves_nothing_to_stop(self):
        fake = self.use(refuses=True, start={"ok": False, "reason": "no binary"})
        self.captured(rs._provision_test_target)
        self.captured(rs._teardown_test_target)
        self.assertEqual(fake.stops, [],
                         "a refused bench starts nothing, so nothing stops")


# --------------------------------------------------------------- E teardown --
class TeardownResidueTest(TargetCase):

    def test_the_teardown_judges_the_residue_from_the_outside(self):
        fake = self.use(refuses=True)
        self.captured(rs._provision_test_target)
        block, err = self.captured(rs._teardown_test_target)
        self.assertEqual(fake.stops,
                         [{"port": 17233, "pid": 4242,
                           "db": "/tmp/sandbar-bench-test/temporal.db"}])
        self.assertTrue(block["clean"])
        for token in ("port_refuses=True", "pid_alive=False",
                      "db_removed=True", "clean=True"):
            self.assertIn(token, err,
                          "the receipt carries the residue facts: %s" % token)
        self.assertTrue(rs._test_target_face()["down"]["clean"])

    def test_a_non_clean_teardown_is_published_as_residue(self):
        self.use(refuses=True,
                 stop_block={"clean": False, "port_refuses": False,
                             "pid_alive": True, "db_removed": False,
                             "stopped_s": 9.0, "escalated": True})
        self.captured(rs._provision_test_target)
        block, err = self.captured(rs._teardown_test_target)
        self.assertFalse(block["clean"], "the residue verdict is not swallowed")
        self.assertIn("RESIDUE after down", err)
        self.assertIn("clean=False", err)
        self.assertFalse(rs._test_target_face()["down"]["port_refuses"])

    def test_the_teardown_is_idempotent(self):
        fake = self.use(refuses=True)
        self.captured(rs._provision_test_target)
        self.captured(rs._teardown_test_target)
        self.captured(rs._teardown_test_target)
        self.assertEqual(len(fake.stops), 1,
                         "the pool tail, atexit and the budget exit share one "
                         "idempotent stop")


# --------------------------------------------------- F wiring + cross faces --
def _src():
    return (REPO / "integration" / "run_scenarios.py").read_text(
        encoding="utf-8")


class WiringSourceLockTest(unittest.TestCase):

    def test_the_provision_runs_in_the_prelude_before_any_pool_starts(self):
        src = _src()
        prelude = src.index('_prelude_leg_s["test_target_s"]')
        first_drain = src.index("for e in exclusives:")
        self.assertLess(prelude, first_drain,
                        "the target is resolved before the first entry runs, "
                        "so the whole round shares one answer")
        self.assertIn("_provision_test_target()", src)

    def test_the_child_env_is_built_by_the_one_injection_site(self):
        src = _src()
        body = src[src.index("def _run_entry("):]
        body = body[:body.index("\ndef ")]
        self.assertIn("_apply_test_target_env(child_env)", body)
        self.assertNotIn("child_env[TEST_TARGET_ENV] = TEST_TARGET_DEFAULT", src,
                         "the flat dead-address default must not come back")
        self.assertEqual(
            src.count('child_env[TEST_TARGET_ENV] = st["value"]'), 1,
            "the address reaches a child in one place only")
        self.assertEqual(
            src.count('child_env[TEST_TARGET_SOURCE_ENV] = st["value"]'), 1,
            "the marker is written in one place only")

    def test_the_teardown_is_reachable_from_every_exit(self):
        src = _src()
        self.assertGreaterEqual(src.count("_teardown_test_target()"), 4,
                                "the pool tail, the atexit registration and "
                                "both os._exit paths")
        self.assertIn("atexit.register(_teardown_test_target)", src)
        # The two hard exits carry a pinned reclamation pair of their own
        # (server/engine/tests/test_t260927_tmp_fixture_family.py B6: neither
        # os._exit may bypass reclaim_tmp_artifacts). This call must stay
        # OUTSIDE that pair - slipped between them, it reads to the lock as a
        # dropped reclamation. Keep the order and say so here.
        self.assertIn("_teardown_test_target()\n    batch_teardown()\n"
                      "    reclaim_tmp_artifacts()\n    os._exit(130)", src)
        self.assertIn("_teardown_test_target()\n    batch_teardown()\n", src)
        self.assertEqual(
            src.count("batch_teardown()\n    reclaim_tmp_artifacts()"), 1,
            "the pinned batch_teardown -> reclaim pair stays adjacent")

    def test_the_round_receipt_carries_the_target_it_used(self):
        src = _src()
        self.assertIn('_summary["test_target"] = _test_target_face()', src)
        self.assertIn('_report["test_target"] = _test_target_face()', src)
        face = rs._test_target_face()
        for key in ("env", "value", "source", "namespace", "absent_reason",
                    "down"):
            self.assertIn(key, face)

    def test_the_stated_address_still_matches_every_consumer(self):
        """The address is a cross-file contract: change it and THIS reds,
        instead of a child refusing it by name at runtime."""
        lib = (REPO / "integration" / "t260905-03" /
               "lib_inspection.py").read_text(encoding="utf-8")
        self.assertIn('TEST_TARGET_HOST = "%s"' % rs.TEST_TARGET_DEFAULT, lib,
                      "lib_inspection whitelists this exact address and "
                      "refuses any other value")
        # t261026-08 strips the suite's statement only when it IS this address;
        # a random free port would silently stop it stripping. t260929-07
        # compares the marker VALUE, so it strips whatever the suite states.
        strict = ("integration/t261026-08/"
                  "sc_t261026_08_request_sweep_ticket_channel.py")
        self.assertIn('"%s"' % rs.TEST_TARGET_DEFAULT,
                      (REPO / strict).read_text(encoding="utf-8"))

    def test_the_prelude_leg_persists_on_a_valid_run_header(self):
        """The receipt must survive the run record, not only the stdout line:
        an additive numeric leg is accepted by the store's closed schema."""
        sl = _load("sl_t261101_20_under_test", "integration/scenario_ledger.py")
        hdr = rs.build_run_header(
            "run-test0000000000000000000", "ab" * 20, "cd" * 32, 3, "",
            "lane:line-round", 1791506200000, 12.5,
            {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0},
            prelude_s=1.5, prelude_legs={"test_target_s": 0.2})
        clean, why = sl.validate_run_header(hdr)
        self.assertIsNone(why)
        self.assertIsNotNone(clean)
        self.assertEqual(hdr["prelude_legs"]["test_target_s"], 0.2)

    def test_the_marker_name_and_its_two_readers_agree(self):
        self.assertEqual(rs.TEST_TARGET_SOURCE_ENV,
                         "SANDBAR_SUITE_STATED_TARGET")
        for rel in ("integration/t260929-07/"
                    "sc_watchdog_board_reader_real_shape.py",
                    "integration/t261026-08/"
                    "sc_t261026_08_request_sweep_ticket_channel.py"):
            self.assertIn('"SANDBAR_SUITE_STATED_TARGET"',
                          (REPO / rel).read_text(encoding="utf-8"))


# --------------------------------------- G named degrade of a missing bench ----
# t261102-40: `_bench_module` must never raise out of the prelude. These cases
# drive the REAL module over a tree that carries no `process_bench.py` (the
# incident shape) and over a module that is present but broken (a code fault).


def _load_abs(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        value = fn()
    return value, buf.getvalue()


class NamedDegradeTest(unittest.TestCase):
    """An unavailable bench module is a NAMED absence, never an exception."""

    _STATE = ("resolved", "value", "source", "note", "port", "pid", "db",
              "start_s", "down", "stopped")

    def setUp(self):
        self._saved_state = rs._TEST_TARGET
        self._saved_bench = dict(rs._BENCH)
        self._saved_mod = sys.modules.get("process_bench", "absent")
        self._saved_env = {k: os.environ.get(k) for k in
                           (rs.TEST_TARGET_ENV, rs.TEST_TARGET_SOURCE_ENV,
                            rs.TEST_NAMESPACE_ENV)}
        for key in self._saved_env:
            os.environ.pop(key, None)
        rs._TEST_TARGET = _empty_state()
        sys.modules.pop("process_bench", None)

    def tearDown(self):
        rs._TEST_TARGET = self._saved_state
        rs._BENCH.clear()
        rs._BENCH.update(self._saved_bench)
        if self._saved_mod == "absent":
            sys.modules.pop("process_bench", None)
        else:
            sys.modules["process_bench"] = self._saved_mod
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_a_missing_module_degrades_to_the_named_absence(self):
        """The incident shape: the tree carries the runner, not the bench."""
        with tempfile.TemporaryDirectory() as td:
            tree = Path(td)
            shutil.copy2(REPO / "integration" / "run_scenarios.py",
                         tree / "run_scenarios.py")
            mod = _load_abs("rs_t261102_40_missing_bench", tree / "run_scenarios.py")
            # The lane's import root holds no process_bench.py: take the real
            # integration/ off sys.path so the copy sees the incident shape
            # instead of the checkout's own module.
            saved_path = list(sys.path)
            sys.modules.pop("process_bench", None)
            sys.path[:] = [p for p in sys.path
                           if Path(p or ".").resolve() != (REPO / "integration")]
            try:
                self.assertIsNone(
                    mod._bench_module(),
                    "a missing module returns None, it never raises")
                note = mod._BENCH["absent"]
                self.assertIn("process_bench.py missing at", note)
                self.assertIn("ModuleNotFoundError", note)
                st, err = _capture(mod._provision_test_target)
            finally:
                sys.path[:] = saved_path
            self.assertEqual(st["source"], "absent")
            self.assertEqual(st["value"], "")
            self.assertEqual(st["note"], note)
            self.assertIn("NO TEST TARGET for scenario children:", err)
            self.assertIn("process_bench.py missing at", err)
            child = {}
            mod._apply_test_target_env(child)
            self.assertEqual(child, {},
                             "a missing module never hands a child an address")
            face = mod._test_target_face()
            self.assertEqual(face["source"], "absent")
            self.assertIsNone(face["value"])
            self.assertEqual(face["absent_reason"], note)

    def test_a_broken_module_is_named_as_a_code_fault(self):
        """Present but failing at import: the note must not read as 'missing'."""
        sys.modules["process_bench"] = None      # import raises ImportError
        rs._BENCH.clear()
        rs._BENCH.update({"mod": None, "absent": ""})
        self.assertIsNone(rs._bench_module())
        note = rs._BENCH["absent"]
        self.assertIn("process_bench.py present at", note)
        self.assertIn("but failed to import", note)
        self.assertRegex(note, r"(ImportError|ModuleNotFoundError)")
        self.assertNotIn("missing", note)
        st, err = _capture(rs._provision_test_target)
        self.assertEqual(st["source"], "absent")
        self.assertEqual(st["note"], note)
        self.assertIn("NO TEST TARGET for scenario children:", err)

    def test_an_ambient_statement_wins_without_any_import(self):
        sys.modules["process_bench"] = None      # a would-be import raises
        rs._BENCH.clear()
        rs._BENCH.update({"mod": None, "absent": ""})
        os.environ[rs.TEST_TARGET_ENV] = "127.0.0.1:12345"
        st, err = _capture(rs._provision_test_target)
        self.assertEqual(st["source"], "ambient")
        self.assertEqual(st["value"], "127.0.0.1:12345")
        self.assertEqual(st["note"], "")
        self.assertIn("the environment states it", err)

    def test_the_teardown_names_a_module_that_vanished_after_a_start(self):
        """The guard covers 'imported, then lost' - the only reachable state."""
        rs._TEST_TARGET = {
            "resolved": True, "value": "127.0.0.1:17233", "source": "bench",
            "note": "", "port": 17233, "pid": 4242,
            "db": "/tmp/sandbar-bench-test/temporal.db", "start_s": 0.12,
            "down": None, "stopped": False}
        sys.modules["process_bench"] = None
        rs._BENCH.clear()
        rs._BENCH.update({"mod": None, "absent": ""})
        block, err = _capture(rs._teardown_test_target)
        self.assertFalse(block["clean"], "the residue verdict is not swallowed")
        self.assertIn("failed to import", block["error"])
        self.assertIn("RESIDUE after down", err)
        self.assertIn("no longer available", err)
        again, _ = _capture(rs._teardown_test_target)
        self.assertEqual(again, block, "the teardown stays idempotent")

    def test_the_source_carries_both_wordings(self):
        src = _src()
        self.assertIn("process_bench.py missing at %s (%s: %s)", src)
        self.assertIn(
            "process_bench.py present at %s but failed to import (%s: %s)", src)
        self.assertIn("except Exception as exc:", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
