"""t261005-03 clause C UT: the orphan probe and the guarded reclaim.

All fixtures are injected ps/cwd rows — no real processes are spawned, probed, or
killed. The guard matrix (review C1) pins every false-kill mode the 261005 hand sweep
left implicit:

- pid reuse after a crash   → the row is judged on its own probe (cwd/cmdline), carried;
- a serving lane worker after its console exited → protected by the pidfile/meta set;
- a pidfile naming a recycled pid → over-protects at worst (skip), never condemns;
- a non-worker process inside a lane (agent/pytest) → cmdline guard skips it;
- another user's process    → skipped (never signals other users);
- an unprovable probe row (cwd error) → listed, never condemned (named unverifiable).
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lane_reclaim  # noqa: E402

LANE = "/tmp/fake-repo/.lane"
WORKER_CMD = "python worker.py --daemon --pidfile /x/worker-t1.pid"


def _row(pid=100, ppid=1, cwd=LANE + "/t1", cmd=WORKER_CMD, user="me", **kw):
    r = {"pid": pid, "ppid": ppid, "user": user, "lstart": "Mon 1 00:00:00 2026",
         "command": cmd, "cwd": cwd, "cwd_under_lane": True, "own_user": True}
    r.update(kw)
    return r


def _classify(rows, tmp, protected=frozenset()):
    return lane_reclaim.classify_orphans(rows, LANE, tmp, current_user="me",
                                         protected_pids=set(protected))


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.mkdtemp())

    def mkdtemp(self):
        from tempfile import mkdtemp
        return mkdtemp(prefix="t261005-03-reclaim-")

    def test_clean_orphan_is_condemned(self):
        out = _classify([_row()], self.tmp)
        self.assertEqual(out[0]["verdict"], "condemn")

    def test_non_worker_cmdline_is_skipped(self):
        out = _classify([_row(cmd="claude --cwd /tmp/fake-repo/.lane/t1")], self.tmp)
        self.assertEqual(out[0]["verdict"], "skip")
        self.assertIn("worker.py", out[0]["reason"])

    def test_cwd_outside_lane_is_skipped(self):
        out = _classify([_row(cwd="/tmp/elsewhere", cwd_under_lane=False)], self.tmp)
        self.assertEqual(out[0]["verdict"], "skip")

    def test_probe_failure_is_never_condemned(self):
        out = _classify([_row(cwd="", error="lsof timed out - cwd cannot be proven")], self.tmp)
        self.assertEqual(out[0]["verdict"], "skip")
        self.assertIn("cannot be proven", out[0]["reason"])

    def test_other_users_process_is_skipped(self):
        out = _classify([_row(user="root")], self.tmp)
        self.assertEqual(out[0]["verdict"], "skip")
        self.assertIn("not the current user", out[0]["reason"])

    def test_pidfile_protected_pid_is_skipped(self):
        # The resident worker and healthy lane workers stay untouched (the 261005
        # hand-sweep rule: only orphans died).
        out = _classify([_row(pid=100)], self.tmp, protected={100})
        self.assertEqual(out[0]["verdict"], "skip")
        self.assertIn("pidfile/meta", out[0]["reason"])

    def test_stale_pidfile_overprotects_never_condemns(self):
        # A stale pidfile naming a recycled pid can only over-protect (skip) — the
        # conservative direction; it never turns a non-orphan into a condemn.
        out = _classify([_row(pid=7, cmd="bash -c sleep")], self.tmp, protected={7})
        self.assertEqual(out[0]["verdict"], "skip")

    def test_parent_alive_is_never_even_a_candidate(self):
        # scan-level rule: ppid==1 is the orphan radius; a child of a live console is
        # not scanned at all (classified rows here only mirror the scan's filter).
        rows = [_row(pid=1, ppid=59295)]
        self.assertEqual([r for r in rows if r["ppid"] == 1], [])


class CountFaceTest(unittest.TestCase):
    """Arbitration gen2: the COUNT is provable orphans only. A ppid=1 daemon whose
    lsof cwd probe failed stays in the receipt (named) but OUTSIDE the count — the
    acceptance zero reading must be deliverable on a real host. A proven orphan is
    never demoted."""

    def test_error_row_outside_count(self):
        rows = [_row(pid=100),
                _row(pid=200, cwd="", cwd_under_lane=False, error="lsof failed (rc=1)")]
        provable = [r for r in rows if lane_reclaim.is_provable_orphan(r)]
        unprovable = [r for r in rows
                      if r.get("error") and not r.get("cwd_under_lane")]
        self.assertEqual([r["pid"] for r in provable], [100])
        self.assertEqual([r["pid"] for r in unprovable], [200])

    def test_proven_orphan_is_never_demoted(self):
        self.assertTrue(lane_reclaim.is_provable_orphan(_row()))
        self.assertFalse(lane_reclaim.is_provable_orphan(
            _row(cwd="/tmp/elsewhere", cwd_under_lane=False)))
        self.assertFalse(lane_reclaim.is_provable_orphan(
            _row(cwd="", error="probe down")))

    def test_main_receipt_split(self):
        import json as _json
        from tempfile import mkdtemp
        # receipt-level split via the pure pieces main() composes (no real ps)
        rows = [_row(pid=100), _row(pid=200, cwd="", cwd_under_lane=False, error="lsof down")]
        classified = _classify(rows, Path(mkdtemp(prefix="t261005-03-cnt-")))
        orphans = [r for r in classified if lane_reclaim.is_provable_orphan(r)]
        unprovable = [r for r in classified
                      if r.get("error") and not r.get("cwd_under_lane")]
        self.assertEqual(len(orphans), 1)
        self.assertEqual(len(unprovable), 1)
        self.assertNotIn(200, [r["pid"] for r in orphans])


class ProtectedPidsTest(unittest.TestCase):
    def test_pidfiles_and_meta_name_pids(self):
        from tempfile import mkdtemp
        d = Path(mkdtemp(prefix="t261005-03-prot-"))
        (d / "worker-t1.pid").write_text("4242\n")
        (d / "worker-t2.meta").write_text('{"version":1,"pid":4343,"repo_root":"/x"}')
        (d / "broken.pid").write_text("not-a-pid")
        self.assertEqual(lane_reclaim._protected_pids(d), {4242, 4343})

    def test_missing_dir_is_empty(self):
        self.assertEqual(lane_reclaim._protected_pids("/nonexistent-dir-xyz"), set())


class ReclaimTest(unittest.TestCase):
    def test_dry_run_kills_nothing(self):
        killed = []

        def _kill(pid, sig):
            killed.append(pid)
        out = lane_reclaim.reclaim(
            [{"pid": 100, "verdict": "condemn"}, {"pid": 5, "verdict": "skip",
                                                  "reason": "x"}],
            apply=False, kill_fn=_kill)
        self.assertEqual(killed, [])
        self.assertEqual(out[0]["action"], "would_kill(dry-run)")
        self.assertEqual(out[1]["action"], "skipped")

    def test_apply_sigterms_only_condemned(self):
        killed = []
        out = lane_reclaim.reclaim(
            [{"pid": 100, "verdict": "condemn"}, {"pid": 5, "verdict": "skip",
                                                  "reason": "x"}],
            apply=True, kill_fn=lambda pid, sig: killed.append(pid))
        self.assertEqual(killed, [100])
        self.assertEqual(out[0]["action"], "sigterm_sent")

    def test_apply_handles_already_gone_and_errors(self):
        def _kill(pid, sig):
            if pid == 1:
                raise ProcessLookupError()
            raise OSError(1, "denied")
        out = lane_reclaim.reclaim(
            [{"pid": 1, "verdict": "condemn"}, {"pid": 2, "verdict": "condemn"}],
            apply=True, kill_fn=_kill)
        self.assertEqual(out[0]["action"], "already_gone")
        self.assertEqual(out[1]["action"], "error")


class ScanFilterTest(unittest.TestCase):
    def test_scan_keeps_only_ppid1_and_names_unverifiable(self):
        def ps():
            return [{"pid": 100, "ppid": 1, "user": "me", "lstart": "x",
                     "command": WORKER_CMD},
                    {"pid": 200, "ppid": 59295, "user": "me", "lstart": "x",
                     "command": WORKER_CMD}]
        out = lane_reclaim.scan_orphans(
            LANE, ps_rows_fn=ps,
            cwd_fn=lambda pid: {"cwd": LANE + "/t1"},
            uid=os.getuid())
        self.assertEqual([r["pid"] for r in out], [100])
        self.assertTrue(out[0]["cwd_under_lane"])

    def test_malformed_ps_lines_are_skipped(self):
        def ps():
            return [{"pid": "x", "ppid": 1, "user": "me", "lstart": "a b c d e",
                     "command": "w"}]
        self.assertEqual(lane_reclaim.scan_orphans(
            LANE, ps_rows_fn=ps, cwd_fn=lambda pid: {"cwd": "/"}, uid=os.getuid()), [])


if __name__ == "__main__":
    unittest.main()
