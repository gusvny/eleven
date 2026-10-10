# -*- coding: utf-8 -*-
"""t261009-55 UT: worker-owned meta extras merge (console boot generation + polling).

- merge_worker_meta_extras: merges console_boot/polling into the worker's own meta;
  pid-guarded (never clobbers the replacement's fingerprint); draining-guarded (a
  late refresher tick never resurrects a released slot); atomic; best-effort
  (malformed/missing/unreadable meta -> False, never raises).
- console_boot_id: reads SANDBAR_CONSOLE_BOOT; blank/unset -> "" (the named
  transitional limitation: a boot-less meta keeps the pre-t261009-55 ensure rules).

All fixtures are files in a temp dir — no real processes, no Temporal, no console.
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


class MetaExtrasMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = mkdtemp_reclaimed("t261009-55-merge-")

    def test_merge_adds_boot_and_polling(self):
        p = str(self.tmp / "m.meta")
        shared.write_worker_meta(p, repo_root="/tmp", pid=os.getpid())
        ok = worker.merge_worker_meta_extras(
            p, {"console_boot": "123-456", "polling": True})
        self.assertTrue(ok)
        merged = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertEqual(merged["console_boot"], "123-456")
        self.assertIs(merged["polling"], True)
        self.assertEqual(merged["pid"], os.getpid())   # base keys intact
        self.assertTrue(merged["repo_root"].endswith("/tmp"))

    def test_merge_is_idempotent_across_ticks(self):
        p = str(self.tmp / "m.meta")
        shared.write_worker_meta(p, repo_root="/tmp", pid=os.getpid())
        for polling in (True, False, True):
            self.assertTrue(worker.merge_worker_meta_extras(p, {"polling": polling}))
        merged = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertIs(merged["polling"], True)
        self.assertEqual(merged["pid"], os.getpid())

    def test_pid_guard_never_clobbers_new_owner(self):
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=os.getpid() + 4242)   # another owner's meta
        self.assertFalse(worker.merge_worker_meta_extras(p, {"polling": False}))
        merged = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertNotIn("polling", merged)      # untouched

    def test_draining_guard_keeps_released_slot(self):
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=os.getpid(), state=shared.WORKER_META_STATE_DRAINING)
        self.assertFalse(worker.merge_worker_meta_extras(p, {"polling": True}))
        merged = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertNotIn("polling", merged)
        self.assertEqual(merged["state"], "draining")

    def test_malformed_inputs_fail_closed_and_quiet(self):
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=1, raw="{not json")   # junk
        self.assertFalse(worker.merge_worker_meta_extras(p, {"polling": True}))
        self.assertFalse(worker.merge_worker_meta_extras(
            str(self.tmp / "absent.meta"), {"polling": True}))
        self.assertFalse(worker.merge_worker_meta_extras(None, {"polling": True}))
        self.assertFalse(worker.merge_worker_meta_extras(p, {}))          # no extras
        self.assertFalse(worker.merge_worker_meta_extras(p, "not-a-dict"))  # malformed extras
        # the junk file itself is untouched
        self.assertEqual(Path(p).read_text(encoding="utf-8"), "{not json")

    def test_bootless_meta_keeps_legacy_shape(self):
        # A meta written by a pre-t261009-55 worker (or after a failed merge) must
        # stay readable under the legacy rules — the extras are additive only.
        p = str(self.tmp / "m.meta")
        _write_meta(p, pid=os.getpid())
        merged = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertNotIn("console_boot", merged)
        self.assertNotIn("polling", merged)


class ConsoleBootIdTest(unittest.TestCase):
    def test_reads_env(self):
        old = os.environ.get(worker.CONSOLE_BOOT_ENV)
        try:
            os.environ[worker.CONSOLE_BOOT_ENV] = "77-abc"
            self.assertEqual(worker.console_boot_id(), "77-abc")
            os.environ[worker.CONSOLE_BOOT_ENV] = "   "
            self.assertEqual(worker.console_boot_id(), "")   # blank = unset
        finally:
            if old is None:
                os.environ.pop(worker.CONSOLE_BOOT_ENV, None)
            else:
                os.environ[worker.CONSOLE_BOOT_ENV] = old

    def test_unset_is_empty_not_none(self):
        old = os.environ.pop(worker.CONSOLE_BOOT_ENV, None)
        try:
            self.assertEqual(worker.console_boot_id(), "")
        finally:
            if old is not None:
                os.environ[worker.CONSOLE_BOOT_ENV] = old


if __name__ == "__main__":
    unittest.main()
