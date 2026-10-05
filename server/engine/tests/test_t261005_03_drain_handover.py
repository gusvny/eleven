"""t261005-03 clause A UT: drain must hand over.

- shared: meta carries state (serving/draining); a meta written before the key existed
  reads as serving (backward compatible); an invalid state is rejected at the writer.
- worker.guard_single_worker: a live pidfile pid with a DRAINING meta (exact pid match)
  admits the takeover; serving/missing/malformed meta keeps the conservative refusal.
- worker.mark_meta_draining: writes draining only for its own pid (ownership-guarded —
  after a takeover the meta belongs to the replacement); a write failure is best-effort
  (returns False, never raises).

Fault-mode tradeoff vs the borrowed harness (review C1): selfcheck_worker_graceful_stop
covers signal transport and the in-flight activity disposition of the real shutdown
path; this module adds what that harness does NOT see — the SLOT handover (draining
meta write, guard admission) — and pins them with fake pidfiles, no real processes.
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402

import shared  # noqa: E402
import worker  # noqa: E402


def _write_meta(path, pid, state=None, extra=None, raw=None):
    if raw is not None:
        Path(path).write_text(raw, encoding="utf-8")
        return
    payload = {"version": 1, "pid": pid, "repo_root": "/tmp", "ts": 1}
    if state is not None:
        payload["state"] = state
    if extra:
        payload.update(extra)
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


class MetaStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = mkdtemp_reclaimed("t261005-03-drain-")

    def test_roundtrip_draining(self):
        p = str(self.tmp / "m.meta")
        payload = shared.write_worker_meta(p, repo_root="/tmp", pid=7,
                                           state=shared.WORKER_META_STATE_DRAINING)
        self.assertEqual(payload["state"], "draining")
        meta, state, _ = shared.read_worker_meta_state(p)
        self.assertEqual(state, "ok")
        self.assertEqual(meta["state"], "draining")

    def test_default_state_is_serving(self):
        p = str(self.tmp / "m.meta")
        payload = shared.write_worker_meta(p, repo_root="/tmp", pid=7)
        self.assertEqual(payload["state"], "serving")

    def test_meta_without_state_key_reads_serving(self):
        # A meta written by an OLD worker (before the key existed) — read side takes
        # keys on demand; consumers must see serving, i.e. today's behavior.
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=7, state=None)
        meta, state, _ = shared.read_worker_meta_state(p)
        self.assertEqual(state, "ok")
        self.assertEqual(meta["state"], "serving")

    def test_unknown_state_value_is_surfaced_not_normalized(self):
        # Fail conservative: a typo'd state is passed through verbatim; consumers treat
        # anything != 'draining' as serving — the slot never opens on a typo.
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=7, state="drainning")
        meta, state, _ = shared.read_worker_meta_state(p)
        self.assertEqual(state, "ok")
        self.assertEqual(meta["state"], "drainning")

    def test_invalid_state_rejected_at_writer(self):
        with self.assertRaises(ValueError):
            shared.worker_meta_payload(repo_root="/tmp", pid=1, state="zombie")

    def test_malformed_meta_still_malformed(self):
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=0, raw="{not json")
        meta, state, _ = shared.read_worker_meta_state(p)
        self.assertIsNone(meta)
        self.assertEqual(state, "malformed")


class GuardTakeoverTest(unittest.TestCase):
    """guard_single_worker with a LIVE pid (this test process) holding the pidfile."""

    def setUp(self):
        self.tmp = mkdtemp_reclaimed("t261005-03-guard-")
        self.pidfile = str(self.tmp / "worker-t1.pid")
        live = os.getpid()  # a pid that IS alive, without spawning anything
        Path(self.pidfile).write_text(str(live), encoding="utf-8")
        self.live_pid = live

    def _meta_path(self):
        return self.pidfile + ".meta"

    def test_draining_meta_admits_takeover(self):
        _write_meta(self._meta_path(), pid=self.live_pid, state="draining")
        self.assertIsNone(worker.guard_single_worker(self.pidfile))

    def test_serving_meta_still_refuses(self):
        _write_meta(self._meta_path(), pid=self.live_pid, state="serving")
        refusal = worker.guard_single_worker(self.pidfile)
        self.assertIsInstance(refusal, str)
        self.assertIn(str(self.live_pid), refusal)

    def test_meta_without_state_still_refuses(self):
        # Old worker (no state key) — behavior unchanged, conservative refusal.
        _write_meta(self._meta_path(), pid=self.live_pid, state=None)
        self.assertIsInstance(worker.guard_single_worker(self.pidfile), str)

    def test_meta_pid_mismatch_still_refuses(self):
        # The draining marker of ANOTHER pid must not open this slot (exact-match rule).
        _write_meta(self._meta_path(), pid=self.live_pid + 1, state="draining")
        self.assertIsInstance(worker.guard_single_worker(self.pidfile), str)

    def test_missing_meta_still_refuses(self):
        self.assertIsInstance(worker.guard_single_worker(self.pidfile), str)

    def test_malformed_meta_still_refuses(self):
        _write_meta(self._meta_path(), pid=0, raw="{{{")
        self.assertIsInstance(worker.guard_single_worker(self.pidfile), str)


class MarkMetaDrainingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = mkdtemp_reclaimed("t261005-03-mark-")
        self.meta = str(self.tmp / "m.meta")

    def test_marks_own_pid_draining(self):
        shared.write_worker_meta(self.meta, repo_root="/tmp", pid=os.getpid())
        self.assertTrue(worker.mark_meta_draining(self.meta))
        meta, state, _ = shared.read_worker_meta_state(self.meta)
        self.assertEqual(state, "ok")
        self.assertEqual(meta["state"], "draining")
        self.assertEqual(meta["pid"], os.getpid())

    def test_refuses_foreign_owner(self):
        # After a takeover the meta names the replacement — the draining worker must
        # not clobber it.
        shared.write_worker_meta(self.meta, repo_root="/tmp", pid=os.getpid() + 1)
        self.assertFalse(worker.mark_meta_draining(self.meta))
        meta, _, _ = shared.read_worker_meta_state(self.meta)
        self.assertEqual(meta["state"], "serving")

    def test_missing_meta_is_noop(self):
        self.assertFalse(worker.mark_meta_draining(self.meta))

    def test_none_path_is_noop(self):
        self.assertFalse(worker.mark_meta_draining(None))

    def test_unwritable_path_is_best_effort_false(self):
        # A directory in place of the file: the write fails, the helper returns False
        # (named in the log) instead of blocking the shutdown path.
        shared.write_worker_meta(self.meta, repo_root="/tmp", pid=os.getpid())
        bad = str(self.tmp)  # a directory path — open() fails
        self.assertFalse(worker.mark_meta_draining(bad))


class ShutdownWiringTest(unittest.TestCase):
    """Source-level anchor: the real shutdown path marks draining BEFORE stopping the
    pollers (entry of _graceful_shutdown), and run_worker passes its meta path."""

    def test_graceful_shutdown_marks_draining_first(self):
        import inspect
        src = inspect.getsource(worker._graceful_shutdown)
        assert "mark_meta_draining(meta_path)" in src
        assert src.index("mark_meta_draining(meta_path)") < src.index("_log_shutdown_disposition()")

    def test_run_worker_passes_meta_path(self):
        import inspect
        src = inspect.getsource(worker.run_worker)
        assert "_graceful_shutdown(workers, run_tasks, watch_task, meta_path=meta_path)" in src


if __name__ == "__main__":
    unittest.main()
