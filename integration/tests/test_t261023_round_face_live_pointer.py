#!/usr/bin/env python3
"""L1: a dead round's live pointer must not hide the round that is running.

Measured (host report 261023 "正在跑的也要显示出来"): `rounds/current.json` still
named a round from 2026-10-12 whose runner had died. Every later round called
publish(), saw a "foreign" pointer and published NO live face - for ten days no
running round was visible to the console, and the certification tab looked empty
while a round was actually measuring.

The rule pinned here: a pointer whose owner pid is gone is STALE and may be
taken over; a pointer whose owner is alive still owns it (never steal a live
round's face).
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
sys.path.insert(0, INTEG)

import lib_round_face as L  # noqa: E402


class PointerOwnerAlive(unittest.TestCase):
    def test_own_pid_is_alive(self):
        self.assertTrue(L._pointer_owner_alive("round-20260101T000000Z-%d" % os.getpid()))

    def test_dead_pid_is_stale(self):
        self.assertFalse(L._pointer_owner_alive("round-20261012T143943Z-54475"))

    def test_id_without_pid_is_stale(self):
        self.assertFalse(L._pointer_owner_alive("round-20261012T143943Z"))
        self.assertFalse(L._pointer_owner_alive(""))
        self.assertFalse(L._pointer_owner_alive(None))


class TakeoverWritesTheLiveFace(unittest.TestCase):
    def test_stale_pointer_is_taken_over(self):
        d = tempfile.mkdtemp(prefix="roundface-")
        rd = os.path.join(d, "rounds")
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, L.CURRENT_NAME), "w", encoding="utf-8") as f:
            f.write('{"run_id": "round-20261012T143943Z-54475"}')
        w = L.FaceWriter(d, "round-20260101T000000Z-%d" % os.getpid(), "develop-buffer", {})
        w.publish()
        with open(os.path.join(rd, L.CURRENT_NAME), encoding="utf-8") as f:
            self.assertIn(str(os.getpid()), f.read())

    def test_live_pointer_is_not_stolen(self):
        d = tempfile.mkdtemp(prefix="roundface-")
        rd = os.path.join(d, "rounds")
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, L.CURRENT_NAME), "w", encoding="utf-8") as f:
            f.write('{"run_id": "round-20260101T000000Z-%d"}' % os.getpid())
        w = L.FaceWriter(d, "round-20260102T000000Z-%d" % (os.getpid() + 1), "develop-buffer", {})
        w.publish()
        with open(os.path.join(rd, L.CURRENT_NAME), encoding="utf-8") as f:
            self.assertIn(str(os.getpid()), f.read())
            self.assertNotIn(str(os.getpid() + 1), f.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
