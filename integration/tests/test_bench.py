#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bench acquirer face UT — re-pointed onto the process bench (t260904-02 intent,
t261028-14 re-pin).

WHY THE SHAPE CHANGED (t261028-14, KI-387 sweep): this battery was written
against integration/bench.py's slot pool — ``acquire_slot`` / ``bench_root`` /
``Slot`` / ``BenchBusy`` / ``MissingAsset``. That capability is RETIRED
(t260904-19): the bench today is ``integration/process_bench.py`` — one dev
server per free port, a JSON registry of started benches, a deadman shim, and a
residue judgement. The retirement is reported on ticket t261028-14; the pool is
NOT re-invented here. Every case below keeps one intent of the old battery and
holds it on a face that exists today:

- a busy acquirer is refused BY NAME and the refusal creates nothing
  (old: ``acquire_slot`` -> ``BenchBusy`` with the "槽满" text);
- releasing really releases — no stale holder state blocks the next acquirer
  (old: ``acquire_slot`` again right after ``release()``);
- residue cleanliness is JUDGED, never assumed: what still stands is named, and
  "clean" is only said when the port refuses AND the pid and the group are gone
  (old: the slot-root residual-state face);
- the book-keeping face never lies: a corrupt registry entry is kept as a
  record, NAMED by the sweep, then dropped — never a crash and never a silent
  empty list (old: "named, never a bare traceback");
- a reclaim never removes a directory this module did not create
  (old: the root-degrade guard — an unusable/foreign root is refused, not
  destroyed).

FORMER GAP, closed by t261029-31 (KI-389): this battery reported that
``process_bench.start(root=<unwritable>)`` raised a bare ``PermissionError``
(the public ``up --root`` CLI left with a traceback and exit 1) while the module
documents its refusals as ``{"ok": false, "reason": <named>}`` with exit 2, and
that an unwritable bench registry let the bench run unregistered. It
deliberately did not pin the defect as behaviour. Both faces are fixed now, and
their regression cases live in
``integration/tests/test_t261029_32_process_bench_failure_faces.py``; this file
keeps its acquirer/residue faces.

Faces: offline, seconds, no docker, no Temporal server, no network beyond a
loopback listener the test itself opens, and it never touches the console on
3099. Run: ``python3 -m pytest integration/tests/test_bench.py``.
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bench  # noqa: E402  (assert_not_production: still the product guard)
import process_bench as pb  # noqa: E402  (the bench that exists today)


class ProdGuardTest(unittest.TestCase):
    def test_prod_ports_rejected(self):
        for host in ("127.0.0.1:7233", "localhost:8233", "7233"):
            with self.assertRaises(bench.ProductionGuardError):
                bench.assert_not_production(host)

    def test_non_production_endpoint_ok_and_empty_rejected(self):
        self.assertEqual(bench.assert_not_production("127.0.0.1:19101"), "127.0.0.1:19101")
        with self.assertRaises(bench.ProductionGuardError):
            bench.assert_not_production("")


class _RegistryIsolated(unittest.TestCase):
    """Every case gets its own registry dir, so no host bench is ever swept."""

    def setUp(self):
        self.reg = pathlib.Path(tempfile.mkdtemp(prefix="bench-ut-reg-"))
        self.addCleanup(shutil.rmtree, str(self.reg), True)
        self._old_registry = os.environ.get(pb.REGISTRY_ENV)
        os.environ[pb.REGISTRY_ENV] = str(self.reg)
        self.addCleanup(self._restore_registry)

    def _restore_registry(self):
        if self._old_registry is None:
            os.environ.pop(pb.REGISTRY_ENV, None)
        else:
            os.environ[pb.REGISTRY_ENV] = self._old_registry


class BusyEndpointTest(_RegistryIsolated):
    """The acquirer: one bench per port. A busy endpoint is refused BY NAME."""

    def _hold_port(self):
        """Occupy an endpoint the way a running bench does (a real listener)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        self.addCleanup(sock.close)
        return sock, sock.getsockname()[1]

    def test_busy_endpoint_refused_by_name_and_creates_nothing(self):
        sock, port = self._hold_port()
        holder = pathlib.Path(tempfile.mkdtemp(prefix="bench-ut-root-"))
        self.addCleanup(shutil.rmtree, str(holder), True)
        root = holder / "bench-root"
        res = pb.start(bin_path=sys.executable, port=port, root=root, boot_s=0.1)
        self.assertFalse(res["ok"], res)
        # named: which check failed, and on which port — never a bare error
        self.assertIn("already in use", res["reason"])
        self.assertIn(str(port), res["reason"])
        # a refusal creates NOTHING: no root, no temp dir, no registry entry
        self.assertFalse(root.exists(), "the refusal created the root")
        self.assertEqual(pb.entries(), [])

    def test_reacquire_after_release(self):
        """Release leaves no holder state: the endpoint probe reads the live
        truth both ways, and the registry entry is gone, not stale."""
        sock, port = self._hold_port()
        res = pb.start(bin_path=sys.executable, port=port, boot_s=0.1)
        self.assertIn("already in use", res["reason"])
        sock.close()
        deadline = time.monotonic() + 5
        while not pb.port_refuses(port) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(pb.port_refuses(port),
                        "the released port still answers — a stale holder")
        # the book-keeping release: unregistering a bench removes it, and a
        # re-acquire is recorded again (no tombstone blocks the next one)
        self.assertTrue(pb.register(424242, 424242, port, self.reg / "x" / "temporal.db"))
        self.assertEqual([e.get("pid") for e in pb.entries()], [424242])
        self.assertTrue(pb.unregister(424242))
        self.assertEqual(pb.entries(), [])
        self.assertTrue(pb.register(424243, 424243, port, self.reg / "y" / "temporal.db"))
        self.assertEqual([e.get("pid") for e in pb.entries()], [424243])


class ResidueAndRegistryTest(_RegistryIsolated):
    """Residue is judged from evidence, and the registry never lies."""

    def test_residue_judges_what_survives(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        # a child in its own group, blocked on its stdin: it stands until the
        # case kills it, so no declared time bound is needed (the kill bounds it)
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.readline()"],
                                 stdin=subprocess.PIPE, start_new_session=True)
        self.addCleanup(child.wait)          # reap on every path
        pgid = os.getpgid(child.pid)
        try:
            # while both stand, "clean" is a LIE: the block names each survivor
            block = pb.residue(port, child.pid, pgid=pgid)
            self.assertFalse(block["port_refuses"], block)
            self.assertTrue(block["pid_alive"], block)
            self.assertTrue(block["group_alive"], block)
            self.assertIn(child.pid, block["survivors"], block)
            self.assertFalse(pb.residue_clean(block),
                             "residue_clean said clean while the port and the "
                             "process group both still stand (the false-已清 class)")
        finally:
            child.kill()
            child.stdin.close()
            sock.close()
        child.wait()
        deadline = time.monotonic() + 5
        while not pb.port_refuses(port) and time.monotonic() < deadline:
            time.sleep(0.05)
        gone = pb.residue(port, child.pid, pgid=pgid)
        self.assertTrue(pb.residue_clean(gone), gone)

    def test_corrupt_registry_entry_kept_and_named(self):
        """An unreadable entry is a RECORD, not a silent empty registry and not
        a crash: the sweep names it and removes it."""
        bad = self.reg / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        entries = pb.entries()
        self.assertEqual(len(entries), 1, entries)
        self.assertTrue(entries[0].get("corrupt"), entries)
        self.assertEqual(entries[0]["_path"], str(bad))
        swept = pb.sweep()
        self.assertEqual(len(swept), 1, swept)
        self.assertEqual(swept[0]["reason"], "unreadable registry entry")
        self.assertFalse(swept[0]["killed"])
        self.assertFalse(bad.exists(), "the corrupt record was not dropped")
        self.assertEqual(pb.entries(), [])

    def test_reclaim_dir_refuses_a_path_it_did_not_create(self):
        """The root guard: only a directory this module names may be removed."""
        keep = pathlib.Path(tempfile.mkdtemp(prefix="bench-ut-keep-"))
        self.addCleanup(shutil.rmtree, str(keep), True)
        (keep / "payload.txt").write_text("x", encoding="utf-8")
        self.assertFalse(pb.reclaim_dir(keep),
                         "a path this module did not create must be refused")
        self.assertTrue((keep / "payload.txt").is_file(), "the foreign dir was removed")
        mine = keep / (pb.TEMP_PREFIX + "ut")
        mine.mkdir()
        self.assertTrue(pb.reclaim_dir(mine))
        self.assertFalse(mine.exists())
        # already gone counts as reclaimed (the deadman removes it when the owner dies)
        self.assertTrue(pb.reclaim_dir(keep / (pb.TEMP_PREFIX + "gone")))


if __name__ == "__main__":
    unittest.main()
