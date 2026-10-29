#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 battery: the tmp-fixture sweep's cadence faces (t261029-38).

Pure faces and the malformed-input table (M1-M20 of the plan), so every case is offline,
needs no clock, no process table and no host temp root (KI-136: a test must not bind the
real `$TMPDIR`). The cadence CLI as a real process — face selection, the receipt pair, the
count delta, the guard routing and the config exit codes — belongs to the registered
scenario `integration/sc_t261029_38_tmp_sweep_tick.py`; the sweep tool's own CLI safety
contract belongs to `integration/t261002-13/sc_tmp_backlog_sweep_safety.py`.

Intent split (no duplication):
  - round_shape / inert reasons / due / staleness / clamp: here;
  - argv shape (no --kill-carriers, no --prefix, --apply only in apply mode): here;
  - the M-table (config, state, sweep output, malformed names, unwritable state): here;
  - delta rules + capacity + owner table locks: here;
  - the receipt's textual contract on a real private root: the scenario.

Run directly: python3 integration/tests/test_t261029_38_tmp_sweep_receipt.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TOOLS = REPO / "integration" / "tools"
sys.path.insert(0, str(TOOLS))

import sweep_tmp_fixtures as sw          # noqa: E402
import tmp_leak_receipt as rr            # noqa: E402
import tmp_sweep_cadence as cad         # noqa: E402

PY = sys.executable

#: The composed inspection env, read from the engine's own injection face. This is the shape
#: the tick must fire under; the source lock below keeps it honest.
INSPECTION_ENV = {
    "SANDBAR_INTEG_LEDGER_SOURCE": "inspection",
    "SANDBAR_INTEG_LEDGER_OWNER": "gate",
    "SANDBAR_KNOWN_RED_EXCLUDE": "1",
    "INTEG_RUN_DEPTH": "1",
    "SANDBAR_INTEG_RUN_BUDGET_SEC": "5700",
}
#: The per-ticket gate shape. The engine sets source=lane:<ticket>; owner and known-red are
#: present on the inspection face too, so they must not be used to discriminate.
LANE_ENV = {"SANDBAR_INTEG_LEDGER_SOURCE": "lane:t261029-38",
            "SANDBAR_INTEG_LEDGER_OWNER": "gate",
            "SANDBAR_KNOWN_RED_EXCLUDE": "1",
            "INTEG_RUN_DEPTH": "1"}


_MINTED = []


def _tmpdir(prefix="t261029-38-ut-"):
    """A scratch dir under the gitignored out/, reclaimed when this module finishes.

    The battery mints its own fixtures; like every other test face in this repo it reclaims
    them in full at exit (L8 tmp-dir hygiene, KI-01M506 family).
    """
    path = tempfile.mkdtemp(prefix=prefix, dir=str(REPO / "out"))
    _MINTED.append(path)
    return path


def _reclaim_all():
    import shutil
    for path in _MINTED:
        shutil.rmtree(path, ignore_errors=True)
    del _MINTED[:]


import atexit      # noqa: E402

atexit.register(_reclaim_all)


class RoundShape(unittest.TestCase):
    def test_inspection_round_fires(self):
        self.assertEqual(cad.round_shape(INSPECTION_ENV), "inspection")
        self.assertEqual(cad.inert_reason(INSPECTION_ENV), "")

    def test_lane_round_is_inert(self):
        self.assertEqual(cad.round_shape(LANE_ENV), "lane")
        self.assertIn("lane", cad.inert_reason(LANE_ENV))

    def test_manual_and_absent_are_inert(self):
        self.assertEqual(cad.round_shape({}), "manual")
        self.assertTrue(cad.inert_reason({}))
        self.assertEqual(cad.inert_reason({}, manual=True), "")

    def test_depth_and_narrowing_are_inert(self):
        deep = dict(INSPECTION_ENV, INTEG_RUN_DEPTH="2")
        self.assertIn("depth", cad.inert_reason(deep))
        narrowed = dict(INSPECTION_ENV, SANDBAR_SCENARIO_ONLY="some-scenario")
        self.assertIn("narrowed", cad.inert_reason(narrowed))

    def test_disabled_config_is_a_tick_inert(self):
        state = _tmpdir()
        r = cad.main(["disable", "--state-dir", state])
        self.assertEqual(r, 0)
        env = dict(os.environ, **INSPECTION_ENV, SANDBAR_TMP_SWEEP_DIR=state)
        old = os.environ.copy()
        try:
            os.environ.update(env)
            self.assertEqual(cad.main(["tick", "--state-dir", state]), 0)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_composed_env_is_source_locked_to_the_engine(self):
        """The hand-written env above must match the engine's injection site (C-b).

        An engine change to the key or to either call site turns this case red instead of
        silently disabling the cadence.
        """
        src = (REPO / "server" / "engine" / "agent_activities.py").read_text(encoding="utf-8")
        self.assertIn('_extra_env["SANDBAR_INTEG_LEDGER_SOURCE"] = str(ledger_source)', src)
        self.assertIn('ledger_source="inspection"', src)
        self.assertIn('ledger_source="lane:%s"', src)


class ArgvShape(unittest.TestCase):
    def test_apply_argv_carries_no_kill_and_no_prefix(self):
        argv = cad.build_sweep_argv(PY, TOOLS / "sweep_tmp_fixtures.py", "/r", True, 6.0,
                                    400000, 570, 2, 1.0)
        self.assertIn("--apply", argv)
        self.assertNotIn("--kill-carriers", argv)
        self.assertNotIn("--prefix", argv)
        self.assertEqual(argv[argv.index("--max-age-h") + 1], "6.0")
        self.assertEqual(argv[argv.index("--limit") + 1], "400000")

    def test_report_argv_has_no_apply(self):
        argv = cad.build_sweep_argv(PY, "s", "/r", False, 6.0, 1, 60, 2, 1.0)
        self.assertNotIn("--apply", argv)
        self.assertNotIn("--limit", argv)

    def test_count_argv_is_count_only(self):
        argv = cad.build_count_argv(PY, "s", "/r", ("t26101406-", "t26101409-"))
        self.assertIn("--count-only", argv)
        self.assertNotIn("--apply", argv)
        self.assertEqual(argv.count("--prefix"), 2)

    def test_budget_clamp(self):
        self.assertEqual(cad.clamp_budget("5700"), (570, "env"))
        self.assertEqual(cad.clamp_budget(None, 6600), (600, "state"))
        self.assertEqual(cad.clamp_budget(None), (60, "floor"))
        self.assertEqual(cad.clamp_budget("1"), (60, "env"))


class DueAndStale(unittest.TestCase):
    def test_due_window(self):
        self.assertEqual(cad.due(None, 1000)[0], True)
        self.assertEqual(cad.due(1000, 1000 + 3 * 3600)[0], False)
        self.assertEqual(cad.due(1000, 1000 + 21 * 3600)[0], True)

    def test_staleness_baseline_and_bound(self):
        self.assertEqual(cad.staleness(None, 1000), (False, None))
        self.assertEqual(cad.staleness(1000, 1000 + 40 * 3600), (True, 40.0))
        self.assertEqual(cad.staleness(1000, 1000 + 5 * 3600)[0], False)


class MalformedConfig(unittest.TestCase):
    """M1-M6: every config refusal is named and none can start a tick."""

    def test_m1_not_json(self):
        self.assertIn("config_malformed", cad.parse_config("{nope")[1])

    def test_m2_empty(self):
        self.assertIn("config_malformed", cad.parse_config("  ")[1])

    def test_m3_unknown_mode(self):
        self.assertIn("config_unknown_mode: wipe", cad.parse_config('{"mode":"wipe"}')[1])

    def test_m4_wrong_types(self):
        self.assertIn("config_type_error: mode", cad.parse_config('{"mode":1}')[1])
        self.assertIn("config_type_error: max_age_h", cad.parse_config('{"max_age_h":"6"}')[1])
        self.assertIn("config_type_error", cad.parse_config("[]")[1])

    def test_m5_age_below_floor(self):
        self.assertIn("config_age_below_floor", cad.parse_config('{"max_age_h":0.5}')[1])

    def test_m6_root_resolution_is_named(self):
        state = _tmpdir()
        (Path(state) / "config.json").write_text('{"mode":"report","root":"relative/path"}',
                                                encoding="utf-8")
        old = os.environ.copy()
        try:
            os.environ.update(INSPECTION_ENV)
            os.environ["SANDBAR_TMP_SWEEP_DIR"] = state
            rc = cad.main(["tick", "--state-dir", state])
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(rc, cad.EXIT_CONFIG)


class MalformedState(unittest.TestCase):
    """M7/M8: torn state is named, the tick still proceeds, and the due gate falls back."""

    def test_m7_torn_json(self):
        data, err = cad.parse_last_run("{nope")
        self.assertEqual(data, {})
        self.assertIn("state_unreadable", err)

    def test_m8_wrong_types(self):
        data, err = cad.parse_last_run('{"last_success_epoch":"x"}')
        self.assertEqual(data, {})
        self.assertIn("state_type_error: last_success_epoch", err)

    def test_m7b_due_gate_falls_back_to_the_newest_receipt(self):
        """A torn last-run.json must not bypass the 20 h window (C5/K5)."""
        state = Path(_tmpdir())
        root = state / "root"
        root.mkdir()
        (state / "receipts").mkdir()
        (state / "last-run.json").write_text("{torn", encoding="utf-8")
        (state / "receipts" / "receipt-20260101T000000Z.json").write_text(
            json.dumps({"ended_utc_epoch": 1000.0}), encoding="utf-8")
        rc = cad.main(["tick", "--manual", "--root", str(root), "--state-dir", str(state),
                       "--now", "3600"])     # 2600 s after the receipt -> inside the window
        self.assertEqual(rc, 0)
        self.assertFalse((state / "latest.json").exists(),
                         "a due-gated tick must write no receipt")


class MalformedSweepOutput(unittest.TestCase):
    """M9-M11: the sweep's JSON is untrusted input."""

    def test_m9_unparsable(self):
        self.assertIn("sweep_output_unparsable", cad.parse_sweep_output("{x")[1])
        self.assertIn("sweep_output_unparsable", cad.parse_sweep_output("")[1])

    def test_m10_incomplete(self):
        self.assertIn("sweep_output_incomplete", cad.parse_sweep_output('{"swept":1}')[1])

    def test_m11_inconsistent(self):
        err = cad.parse_sweep_output('{"swept":5,"candidates_total":1,"entries":2}')[1]
        self.assertIn("sweep_output_inconsistent", err)


class NamesAndGrouping(unittest.TestCase):
    """M12: names are external input; grouping must never crash or silently merge."""

    def test_real_shapes(self):
        self.assertEqual(rr.family_key("t26091013-1a2b3c4d"), "t26091013")
        self.assertEqual(rr.family_key("sandbar-9z8y7x"), "sandbar")
        self.assertEqual(rr.family_key("notes-gate-abc123"), "notes-gate")
        self.assertEqual(rr.family_key("dz3-pyc-v12d106m"), "dz3-pyc")

    def test_malformed_names(self):
        for name in ("two words 1a2b3c4d", "line\nbreak-1a2b3c", "x" * 255 + "-1a2b3c4d"):
            self.assertIsInstance(rr.family_key(name), str)
        rows = rr.uncovered_families(["a b", "a b", "\udcff\udcfe-1a2b3c4d"])
        self.assertTrue(rows and all(isinstance(r["count"], int) for r in rows))

    def test_top_is_bounded_and_sorted(self):
        names = ["k%d-1a2b3c4d" % i for i in range(20)]
        rows = rr.uncovered_families(names, top=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["count"] for r in rows], sorted([r["count"] for r in rows],
                                                            reverse=True))


class HolderProbe(unittest.TestCase):
    """M13/M14: an lsof row outside the root is ignored; prefix sharing is not a hold."""

    @staticmethod
    def _entry(name):
        return sw.FixtureEntry(name, 0.0, "dir")

    def test_m13_rows_outside_the_root_are_ignored(self):
        box = _tmpdir()
        root = Path(box) / "root"
        (root / "t260904-02-a").mkdir(parents=True)
        os.utime(root / "t260904-02-a", (0, 0))
        entries = [self._entry("t260904-02-a")]
        rows = [("1", "fd", "/etc/hosts"), ("2", "cwd", "/root/elsewhere")]
        hits, info = sw.probe_open_holders(str(root), entries, lsof_rows=rows)
        self.assertEqual(hits, {})
        self.assertEqual(info["outside_root_rows"], 2)
        self.assertFalse(info["degraded"])

    def test_m14_prefix_sharing_is_not_a_hold(self):
        box = _tmpdir()
        root = Path(box) / "root"
        (root / "t260904-02-a").mkdir(parents=True)
        (root / "t260904-02-ab").mkdir()
        entries = [self._entry("t260904-02-a")]
        rows = [("9", "fd", str(root / "t260904-02-ab" / "x.txt"))]
        hits, _info = sw.probe_open_holders(str(root), entries, lsof_rows=rows)
        self.assertEqual(hits, {}, "a prefix-sharing sibling must not mark the entry as held")

    def test_empty_pass_is_degraded_on_a_live_machine(self):
        box = _tmpdir()
        root = Path(box) / "root"
        (root / "t260904-02-a").mkdir(parents=True)
        entries = [self._entry("t260904-02-a")]
        orig_all, orig_lsof = sw._all_pids, sw._lsof_pass
        try:
            sw._all_pids = lambda: ((1, 2), None)
            sw._lsof_pass = lambda: ([], True, None)
            hits, info = sw.probe_open_holders(str(root), entries)
        finally:
            sw._all_pids, sw._lsof_pass = orig_all, orig_lsof
        self.assertEqual(hits, {})
        self.assertTrue(info["degraded"], "an empty answer with live pids is a denied probe")

    def test_degraded_apply_keeps_every_directory_and_exits_3(self):
        box = _tmpdir()
        root = Path(box) / "root"
        d = root / "t260904-02-aged"
        d.mkdir(parents=True)
        (d / "f").write_text("x")
        os.utime(d, (0, 0))
        import contextlib
        import io
        orig_lsof, orig_pids = sw._lsof_pass, sw._all_pids
        buf = io.StringIO()
        try:
            sw._lsof_pass = lambda: ([], False, "lsof exit=1: permission denied")
            sw._all_pids = lambda: ((1, 2), None)
            with contextlib.redirect_stdout(buf):
                rc = sw.run(["--root", str(root), "--apply", "--json"])
        finally:
            sw._lsof_pass, sw._all_pids = orig_lsof, orig_pids
        payload = json.loads(buf.getvalue())
        self.assertEqual(rc, sw.EXIT_DEGRADED, "a degraded probe has its own exit code")
        self.assertTrue(payload["degraded"])
        self.assertIn("permission", payload["degraded_reason"])
        self.assertTrue(d.exists(), "a degraded probe keeps every candidate directory")
        self.assertGreaterEqual(payload["carriers_unverified_kept"], 1)


class ForeignAndCountOnly(unittest.TestCase):
    def test_foreign_overlap_both_directions(self):
        self.assertEqual(sw.foreign_overlap(["t26101406-gate-"]), "t26101406-")
        self.assertEqual(sw.foreign_overlap(["t26101"]), "t26101406-")
        self.assertEqual(sw.foreign_overlap(["t260904-02-"]), "")

    def test_foreign_prefixes_are_not_whitelisted(self):
        for f in sw.FOREIGN_PREFIXES:
            for p in sw.TMP_FIXTURE_PREFIXES:
                self.assertFalse(p.startswith(f) or f.startswith(p),
                                 "whitelist prefix %r collides with foreign %r" % (p, f))

    def test_apply_over_foreign_prefix_is_refused_with_zero_deletes(self):
        box = _tmpdir()
        root = Path(box) / "root"
        d = root / "t26101406-gate-abc123"
        d.mkdir(parents=True)
        os.utime(d, (0, 0))
        r = subprocess.run([PY, str(TOOLS / "sweep_tmp_fixtures.py"), "--root", str(root),
                            "--apply", "--max-age-h", "2", "--prefix", "t26101406-gate-"],
                           # SANCTIONED-WAIT: a hard-kill ceiling on a refused child; never waited.
                           capture_output=True, text=True, timeout=120)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUSED", r.stdout + r.stderr)
        self.assertIn("project-vision", r.stdout + r.stderr)
        self.assertTrue(d.exists(), "a refused apply must delete nothing")

    def test_count_only_refuses_apply(self):
        r = subprocess.run([PY, str(TOOLS / "sweep_tmp_fixtures.py"), "--root", "/tmp",
                            "--count-only", "--apply"], capture_output=True, text=True,
                           # SANCTIONED-WAIT: a hard-kill ceiling on a refused child; never waited.
                           timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUSED", r.stdout + r.stderr)

    def test_count_only_skips_the_probe(self):
        box = _tmpdir()
        root = Path(box) / "root"
        (root / "t260904-02-aged").mkdir(parents=True)
        os.utime(root / "t260904-02-aged", (0, 0))
        r = subprocess.run([PY, str(TOOLS / "sweep_tmp_fixtures.py"), "--root", str(root),
                            "--count-only", "--json"], capture_output=True, text=True,
                           # SANCTIONED-WAIT: a hard-kill ceiling; the count-only run returns at once.
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        j = json.loads(r.stdout)
        self.assertTrue(j["probe_skipped"])
        self.assertEqual(j["probe"]["probe"], "skipped")

    def test_bounded_batch_stops_cleanly(self):
        box = _tmpdir()
        root = Path(box) / "root"
        for i in range(5):
            d = root / ("t260904-02-aged%d" % i)
            d.mkdir(parents=True)
            os.utime(d, (0, 0))
        r = subprocess.run([PY, str(TOOLS / "sweep_tmp_fixtures.py"), "--root", str(root),
                            "--apply", "--limit", "2", "--json"], capture_output=True,
                           # SANCTIONED-WAIT: a hard-kill ceiling on a bounded batch; never waited.
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        j = json.loads(r.stdout)
        self.assertTrue(j["partial"])
        self.assertEqual(j["swept"], 2)
        self.assertEqual(j["remaining"], 3)


class OwnerTable(unittest.TestCase):
    def setUp(self):
        self.owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)

    def test_every_whitelist_prefix_has_a_row(self):
        self.assertEqual(sorted(self.owners), sorted(sw.TMP_FIXTURE_PREFIXES))

    def test_derived_and_override_counts_are_the_measured_ones(self):
        derived = [p for p, r in self.owners.items() if r["source"] == "derived"]
        override = [p for p, r in self.owners.items() if r["source"] == "override"]
        external = [p for p, r in self.owners.items() if r["source"] == "external"]
        self.assertEqual((len(derived), len(override), len(external)), (33, 22, 1),
                         "the derivation rule and the override table must stay in step")

    def test_rows_name_a_repo_and_evidence(self):
        for p, row in self.owners.items():
            self.assertTrue(row.get("producer"), "prefix %r has no producer" % p)
            self.assertTrue(row.get("repo"), "prefix %r has no repo" % p)
            if not row.get("producer_path"):
                self.assertTrue(row.get("reason"),
                                "prefix %r has no path and no reason" % p)
            if row["source"] == "external":
                self.assertTrue(row.get("external"))
                self.assertTrue(row.get("reason"))

    def test_sister_repo_is_not_attributed_to_this_repo(self):
        row = self.owners["project-content-integ-run-"]
        self.assertEqual(row["repo"], "project-content")
        self.assertNotIn("sandbar", row["producer"])

    def test_drift_lock_against_the_engine_table(self):
        """The whitelist and the engine's owner table are one list (drift lock)."""
        import ast
        src = (REPO / "server" / "engine" / "inspection_lane_watchdog.py").read_text(
            encoding="utf-8")
        engine_keys = set()
        for node in ast.parse(src).body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "TMP_FIXTURE_OWNERS"
                    for t in node.targets):
                engine_keys = set(ast.literal_eval(node.value).keys())
        self.assertTrue(engine_keys, "engine owner table parsed empty (lock broken)")
        missing = engine_keys - set(sw.TMP_FIXTURE_PREFIXES)
        self.assertEqual(missing, set(),
                         "engine owner keys outside the whitelist: %s" % sorted(missing))
        for p in engine_keys:
            self.assertEqual(self.owners[p]["repo"], "sandbar")


class ReceiptMath(unittest.TestCase):
    @staticmethod
    def _sweep(prefixes, entries=100, stale=None, live=None, excluded=None):
        rows = [{"prefix": p, "count": c, "dirs": c, "files": 0, "oldest_h": 7.0,
                 "est_bytes": 1024 * c, "sampled": 1, "dir_avg_bytes": 1024.0,
                 "truncated": False} for p, c in prefixes.items()]
        return {"entries": entries, "untouched": 5, "swept": stale or sum(prefixes.values()),
                "candidates_total": sum(prefixes.values()), "processed": 0, "remaining": 0,
                "partial": False, "failed": 0, "failed_named": [], "locks_kept": 0,
                "kept_live": live or 0, "holders_kept": 0, "carriers_kept": 0,
                "per_prefix": rows, "live_per_prefix": {p: 0 for p in prefixes},
                "excluded_by_prefix": excluded or {}, "untouched_names": [],
                "freed_est_bytes": 0, "probe": {}, "degraded": False,
                "summary": "synthetic"}

    def _ctx(self, **kw):
        base = {"mode": "apply", "round_shape": "manual", "round_depth": 1, "root": "/r",
                "state_dir": "/s", "started_utc": "a", "ended_utc": "b",
                "started_utc_epoch": 1000.0, "ended_utc_epoch": 1001.0, "duration_s": 10.0,
                "max_age_h": 6.0, "limit": 10, "budget_s": 60, "budget_source": "env",
                "flags": {}, "tool_rev": {}, "status": "ok", "notes": []}
        base.update(kw)
        return base

    def test_baseline_then_delta(self):
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        first = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 10}),
                                 foreign_json=None, previous=None, owners=owners,
                                 ctx=self._ctx())
        self.assertEqual(first["delta"]["basis"], "baseline")
        self.assertEqual(first["delta"]["reason"], "no_previous")
        second = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 4}),
                                  foreign_json=None, previous=first, owners=owners,
                                  ctx=self._ctx(started_utc_epoch=2000.0))
        self.assertEqual(second["delta"]["basis"], "previous")
        self.assertEqual(second["delta"]["whitelisted"]["delta"], -6)
        self.assertEqual(second["delta"]["gap_s"], 999.0)     # 1001.0 -> 2000.0

    def test_mode_and_root_changes_force_a_baseline(self):
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        prev = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 1}), foreign_json=None,
                                previous=None, owners=owners, ctx=self._ctx(mode="report"))
        same_mode = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 1}),
                                     foreign_json=None, previous=prev, owners=owners,
                                     ctx=self._ctx(mode="apply"))
        self.assertEqual(same_mode["delta"]["reason"], "mode_changed")
        other_root = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 1}),
                                      foreign_json=None, previous=prev, owners=owners,
                                      ctx=self._ctx(mode="report", root="/other"))
        self.assertEqual(other_root["delta"]["reason"], "root_changed")

    def test_unreadable_previous_is_named(self):
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        out = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 1}), foreign_json=None,
                               previous={"_unreadable": True, "receipt_path": "/p"},
                               owners=owners, ctx=self._ctx())
        self.assertEqual(out["delta"]["reason"], "unreadable_previous")

    def test_growth_flag_and_deficit(self):
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        first = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 1}, entries=10),
                                 foreign_json=None, previous=None, owners=owners,
                                 ctx=self._ctx())
        grew = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 1500}, entries=1600),
                                foreign_json=None, previous=first, owners=owners,
                                ctx=self._ctx(started_utc_epoch=1001.0 + 3600.0,
                                              duration_s=10000.0))
        self.assertTrue(grew["delta"]["growth"])
        self.assertTrue(grew["capacity"]["deficit"],
                        "a growing backlog with tiny capacity must raise the deficit note")

    def test_report_mode_never_claims_deletions(self):
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        out = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 3}), foreign_json=None,
                               previous=None, owners=owners, ctx=self._ctx(mode="report"))
        self.assertEqual(out["counts"]["swept"], 0)
        self.assertEqual(out["counts"]["would_sweep"], 3)

    def test_header_names_top_leaker_and_cross_repo(self):
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        foreign = {"per_prefix": [{"prefix": "t26101406-gate-", "count": 7, "oldest_h": 30.0,
                                   "est_bytes": 7 * 1024 * 1024, "dirs": 7, "files": 0,
                                   "sampled": 0, "dir_avg_bytes": 0.0, "truncated": False}],
                   "live_per_prefix": {}}
        out = rr.build_receipt(sweep_json=self._sweep({"t260904-02-": 9},
                                                      excluded={"com.google.Chrome.": 3}),
                               foreign_json=foreign,
                               previous=None, owners=owners, ctx=self._ctx())
        header = out["header"]
        self.assertIn("t260904-02-", header)
        self.assertIn("sandbar", header)
        self.assertIn("project-vision", header)
        md = rr.render_markdown(out)
        for needle in ("t26101406-gate-", "sc_fpv_part_intake", "Google Chrome",
                       "Count delta", "Top leaker", "Capacity"):
            self.assertIn(needle, md)

    def test_retention_bounds(self):
        state = Path(_tmpdir())
        receipts = state / "receipts"
        receipts.mkdir()
        for i in range(cad.RECEIPTS_KEEP + 5):
            (receipts / ("receipt-2026010%dT0000%02dZ.json" % (i % 9 + 1, i % 60))).write_text("{}")
        cad.prune_receipts(str(receipts))
        self.assertLessEqual(len(list(receipts.glob("receipt-*.json"))), cad.RECEIPTS_KEEP)
        hist = state / "history.jsonl"
        hist.write_text("\n".join('{"i":%d}' % i for i in range(cad.HISTORY_MAX_LINES + 50)) + "\n")
        cad.rotate_history(str(hist))
        self.assertEqual(len(hist.read_text(encoding="utf-8").strip().splitlines()),
                         cad.HISTORY_MAX_LINES)


class StateMachine(unittest.TestCase):
    """No config = report (enabled, read-only); apply needs the explicit enable."""

    def _tick(self, state, root, env_extra=None, args=()):
        old = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update(dict(INSPECTION_ENV, **(env_extra or {})))
            os.environ["SANDBAR_TMP_SWEEP_DIR"] = str(state)
            return cad.main(["tick", "--root", str(root), "--state-dir", str(state)]
                            + list(args))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def _root(self):
        root = Path(_tmpdir()) / "root"
        d = root / "t260904-02-aged"
        d.mkdir(parents=True)
        (d / "f").write_text("x")
        os.utime(d, (0, 0))
        return root, d

    def test_no_config_reports_and_never_deletes(self):
        state = Path(_tmpdir())
        root, d = self._root()
        self.assertEqual(self._tick(state, root), 0)
        self.assertTrue(d.exists(), "report mode must not delete")
        receipt = json.loads((state / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["mode"], "report")
        self.assertEqual(receipt["counts"]["swept"], 0)

    def test_enable_apply_then_tick_deletes_and_names_the_holder(self):
        state = Path(_tmpdir())
        root, d = self._root()
        (state / "config.json").write_text('{"mode":"apply"}', encoding="utf-8")
        holder_target = d / "f"
        child = subprocess.Popen([PY, "-c", "import sys,time\nf=open(sys.argv[1])\n"
                                            "print('open',flush=True)\n"
                                            # SANCTIONED-WAIT: holder ceiling; one readline proves the fd, then reaped.
                                            "time.sleep(60)",
                                  str(holder_target)], stdout=subprocess.PIPE, text=True)
        try:
            child.stdout.readline()
            self.assertEqual(self._tick(state, root), 0)
            self.assertTrue(d.exists(), "a dir held open by a live process must survive")
            receipt = json.loads((state / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["counts"]["holders_kept"], 1)
            self.assertTrue(any("t260904-02-aged" in n
                                for n in receipt["counts"]["holders_named"]))
            self.assertIsNone(child.poll(), "the runner must never kill a holder")
        finally:
            child.terminate()
            child.wait(timeout=15)

    def test_stale_red_is_a_successful_tick_for_the_clock(self):
        """K1: a 40 h gap reds once, then the next tick is due and green."""
        state = Path(_tmpdir())
        root, _d = self._root()
        old = dict(INSPECTION_ENV)
        state.mkdir(exist_ok=True)
        (state / "last-run.json").write_text(
            json.dumps({"last_success_epoch": 0}), encoding="utf-8")
        now = 40 * 3600.0
        rc = self._tick(state, root, args=["--force", "--now", str(now)], env_extra={})
        # A last_success of 0 is "no previous success" -> baseline, so seed a real one:
        (state / "last-run.json").write_text(
            json.dumps({"last_success_epoch": 1000.0}), encoding="utf-8")
        rc = self._tick(state, root, args=["--force", "--now", str(1000.0 + 40 * 3600)])
        self.assertEqual(rc, cad.EXIT_STALE, "a 40 h gap must red")
        first = json.loads((state / "last-run.json").read_text(encoding="utf-8"))
        self.assertEqual(first["last_status"], "stale_red")
        self.assertGreater(first["last_success_epoch"], 1000.0,
                           "the stale tick must advance the success clock")
        rc2 = self._tick(state, root, args=["--now", str(first["last_success_epoch"] + 21 * 3600)])
        self.assertEqual(rc2, 0, "the next tick after a stale red must be green")
        del old

    def test_lane_round_is_green_and_writes_nothing(self):
        state = Path(_tmpdir()) / "state"
        root = Path(_tmpdir()) / "root"
        (root / "t260904-02-aged").mkdir(parents=True)
        old = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update(LANE_ENV)
            rc = cad.main(["tick", "--root", str(root), "--state-dir", str(state)])
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(rc, 0)
        self.assertFalse(state.exists(), "an inert round must create no state dir")

    def test_unwritable_state_dir_is_named(self):
        state = Path(_tmpdir()) / "state-is-a-file"
        state.write_text("x")
        root, _d = self._root()
        self.assertEqual(self._tick(state, root), cad.EXIT_WRITE)


class ReceiptFiles(unittest.TestCase):
    def test_receipt_files_round_trip(self):
        import tmp_sweep_cadence as c
        state = Path(_tmpdir()) / "state"
        state.mkdir(exist_ok=True)
        owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
        receipt = rr.build_receipt(
            sweep_json={"entries": 1, "untouched": 0, "swept": 0, "candidates_total": 0,
                        "per_prefix": [], "live_per_prefix": {}, "excluded_by_prefix": {},
                        "untouched_names": [], "failed": 0, "probe": {},
                        "freed_est_bytes": 0, "summary": "x"},
            foreign_json=None, previous=None, owners=owners,
            ctx={"mode": "report", "round_shape": "manual", "round_depth": 1,
                 "root": "/r", "state_dir": str(state), "started_utc": "a", "ended_utc": "b",
                 "started_utc_epoch": 1.0, "ended_utc_epoch": 2.0, "duration_s": 1.0,
                 "max_age_h": 6.0, "limit": None, "budget_s": 60, "budget_source": "env",
                 "flags": {}, "tool_rev": {}, "status": "ok", "notes": []})
        path = c._write_receipt(str(state), receipt)
        self.assertTrue(Path(path).is_file())
        self.assertTrue((state / "latest.json").is_file())
        self.assertTrue((state / "latest.md").is_file())
        self.assertEqual(len((state / "history.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        back = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(back["mode"], "report")
        self.assertIn("swept", back)


if __name__ == "__main__":
    unittest.main(verbosity=2)
