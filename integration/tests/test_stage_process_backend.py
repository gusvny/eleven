#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stage_docker process-backend seam L1 (t261027-11).

Unit battery for the SANDBAR_STAGE_BACKEND=process seam: the selector, the
gates, the up payload (with a stub bench module — no real temporal binary,
no docker), the down payload, and the _boot_new_stage dispatch. The docker
default path is asserted untouched by absence: nothing in this battery sets
the env unless the case says so, and every stub is injected in-process and
removed in finally (全终态回收：正常/报错/超时路径都拆桩)。

Run: python3 -m pytest integration/tests/test_stage_process_backend.py -q
(stdlib-only, seconds, zero docker, zero network beyond loopback sleepers).
"""
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
INTEG = HERE.parent
sys.path.insert(0, str(INTEG))

import stage_docker as sd  # noqa: E402


class _StubBench:
    """In-process process_bench stand-in: start() spawns a real sleeper
    process group (so stop() has something to reap), stop() terminates it and
    reports a clean residue block — the same contract shape as the real
    module, without a temporal binary."""

    def __init__(self, start_refusal=None):
        self.refusal = start_refusal
        self.started = []
        self.stopped = []
        self.detached = []

    def default_bin(self):
        return "/nonexistent/temporal-for-gate-test"

    def start(self, port=None):
        if self.refusal:
            return {"ok": False, "reason": self.refusal}
        big = os.path.basename(__file__)
        proc = __import__("subprocess").Popen(
            # SANCTIONED-WAIT: 60s is the stub bench child's kill ceiling (stop() ends it long before)
            [sys.executable, "-c", "import time; time.sleep(60)"])
        self.started.append((port, proc.pid))
        return {"ok": True, "port": port, "pid": proc.pid,
                "start_s": 0.01, "db": "/tmp/stub-bench.db"}

    def detach(self, pid):
        self.detached.append(int(pid))
        return True

    def stop(self, port, pid, pgid=None, term_s=None, kill_s=None, db=None):
        import signal as _signal
        import subprocess as _sub
        self.stopped.append((port, pid))
        try:
            os.kill(int(pid), _signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(50):
            probe = _sub.run(["kill", "-0", str(pid)], capture_output=True)
            if probe.returncode != 0:
                break
            time.sleep(0.05)
        return {"stopped_s": 0.05, "escalated": False, "port_refuses": True,
                "pid_alive": False, "group_alive": False, "survivors": [],
                "db_removed": True, "clean": True}


def _env(**kw):
    env = {"SANDBAR_STAGE_LOCK_DIR": tempfile.mkdtemp(prefix="sb-pb-"),
           "SANDBAR_STAGE_BACKEND": "process"}
    env.update(kw)
    return env


class BackendSelectorTest(unittest.TestCase):
    def test_default_and_docker(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SANDBAR_STAGE_BACKEND", None)
            self.assertEqual(sd.stage_backend(), "docker")
            os.environ["SANDBAR_STAGE_BACKEND"] = "docker"
            self.assertEqual(sd.stage_backend(), "docker")

    def test_process_and_case_insensitive(self):
        with mock.patch.dict(os.environ, {"SANDBAR_STAGE_BACKEND": "Process"}):
            self.assertEqual(sd.stage_backend(), "process")

    def test_malformed_is_named_usage_red(self):
        with mock.patch.dict(os.environ, {"SANDBAR_STAGE_BACKEND": "podman"}):
            with self.assertRaises(sd.StageError) as cm:
                sd.stage_backend()
            self.assertEqual(cm.exception.kind, "usage")
            self.assertIn("podman", str(cm.exception))


class ProcessGateTest(unittest.TestCase):
    def test_dsh_service_refused(self):
        with mock.patch.dict(os.environ, _env()):
            with self.assertRaises(sd.StageError) as cm:
                sd._gates(["temporal", "dsh"])
            self.assertEqual(cm.exception.kind, "env")
            self.assertIn("process", str(cm.exception))

    def test_missing_binary_refused(self):
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module") as bm:
                bm.return_value.default_bin.return_value = "/no/such/bin"
                with self.assertRaises(sd.StageError) as cm:
                    sd._gates(["temporal"])
                self.assertEqual(cm.exception.kind, "env")
                self.assertIn("SANDBAR_TEMPORAL_BIN", str(cm.exception))

    def test_temporal_only_passes(self):
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module") as bm:
                bm.return_value.default_bin.return_value = __file__
                sd._gates(["temporal"])   # no raise


class UpProcessTest(unittest.TestCase):
    def _lease(self, project):
        lease = sd.new_lease(project, holder_pid=os.getpid(), services=["temporal"])
        lease["lease_id"] = "lid-1"
        return lease

    def test_flip_records_proc_ids_not_container_ids(self):
        stub = _StubBench()
        root = os.environ["SANDBAR_STAGE_LOCK_DIR"] = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module", return_value=stub), \
                 mock.patch.object(sd, "wait_temporal"), \
                 mock.patch.object(sd, "register_namespace",
                                   return_value=(True, "stub")):
                lease = self._lease("pb-flip")
                st = sd._up_process("pb-flip", ["temporal"],
                                    {"ports": {"temporal": 21042},
                                     "namespace": "pb-ns", "repo_dir": None},
                                    30, lease)
        try:
            self.assertEqual(st["state"], "up")
            self.assertEqual(st["ports"], {"temporal": 21042})
            self.assertNotIn("container_ids", st)
            self.assertEqual(len(st["proc_ids"]), 1)
            self.assertTrue(os.path.exists(st["lease_path"])
                            if "lease_path" in st else
                            sd.read_lease("pb-flip").get("proc_ids"))
        finally:
            for _, pid in stub.started:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_refusal_is_env_red_and_leaves_nothing(self):
        stub = _StubBench(start_refusal="temporal binary not found: x")
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module", return_value=stub):
                with self.assertRaises(sd.StageError) as cm:
                    sd._up_process("pb-ref", ["temporal"],
                                   {"ports": {"temporal": 21043}}, 30,
                                   self._lease("pb-ref"))
                self.assertEqual(cm.exception.kind, "env")
                self.assertIn("binary not found", str(cm.exception))
        self.assertEqual(stub.started, [])   # refusal creates nothing

    def test_failed_health_wait_stops_the_bench(self):
        stub = _StubBench()
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module", return_value=stub), \
                 mock.patch.object(sd, "wait_temporal",
                                   side_effect=sd.StageError("not ready", kind="env")):
                with self.assertRaises(sd.StageError):
                    sd._up_process("pb-stop", ["temporal"],
                                   {"ports": {"temporal": 21044}}, 30,
                                   self._lease("pb-stop"))
        self.assertEqual(len(stub.stopped), 1)   # the bench it started is reaped
        for _, pid in stub.started:
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def test_extra_explicit_port_is_usage_red(self):
        stub = _StubBench()
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module", return_value=stub):
                with self.assertRaises(sd.StageError) as cm:
                    sd._up_process("pb-x", ["temporal"],
                                   {"ports": {"temporal": 21045, "ui": 21046},
                                    "ports_explicit": True},
                                   30, self._lease("pb-x"))
                self.assertEqual(cm.exception.kind, "usage")
        self.assertEqual(stub.started, [])

    def test_band_ui_console_slots_are_dropped_honestly(self):
        """band 分配天然带 ui/console 相邻槽：process 台只消费 temporal 槽，
        不冒充绑定整个档位（实测 261027：band 槽位形状 {'console','temporal','ui'}）。"""
        stub = _StubBench()
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module", return_value=stub), \
                 mock.patch.object(sd, "wait_temporal"), \
                 mock.patch.object(sd, "register_namespace",
                                   return_value=(True, "stub")):
                st = sd._up_process("pb-band", ["temporal"],
                                    {"ports": {"temporal": 21051, "ui": 21052,
                                               "console": 21050},
                                     "namespace": "pb", "repo_dir": None},
                                    30, self._lease("pb-band"))
        try:
            self.assertEqual(st["ports"], {"temporal": 21051})
            self.assertEqual(len(stub.started), 1)
        finally:
            for _, pid in stub.started:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass


class DownProcessTest(unittest.TestCase):
    def test_down_without_lease_is_idempotent_ok(self):
        with mock.patch.dict(os.environ, _env()):
            res = sd._down_process("pb-none", None)
            self.assertTrue(res["down"])
            self.assertEqual(res["residue"], [])

    def test_down_stops_recorded_bench_and_releases(self):
        stub = _StubBench()
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            lease = sd.new_lease("pb-down", holder_pid=os.getpid(),
                                 services=["temporal"])
            lease.update({"state": "up", "proc_ids": [424242],
                          "ports": {"temporal": 21047},
                          "bench_db": "/tmp/stub.db"})
            sd.write_lease("pb-down", lease)
            with mock.patch.object(sd, "_bench_module", return_value=stub):
                res = sd._down_process("pb-down", lease)
            self.assertTrue(res["down"])
            self.assertEqual(res["residue"], [])
            self.assertEqual(stub.stopped, [(21047, 424242)])
            self.assertIsNone(sd.read_lease("pb-down"))

    def test_down_names_residue_when_not_clean(self):
        stub = _StubBench()
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            lease = sd.new_lease("pb-res", holder_pid=os.getpid(),
                                 services=["temporal"])
            lease.update({"state": "up", "proc_ids": [424243],
                          "ports": {"temporal": 21048}})
            sd.write_lease("pb-res", lease)
            dirty = {"stopped_s": 1.0, "escalated": True, "port_refuses": False,
                     "pid_alive": True, "group_alive": True,
                     "survivors": [99], "db_removed": False, "clean": False}
            with mock.patch.object(sd, "_bench_module", return_value=stub), \
                 mock.patch.object(stub, "stop", return_value=dirty):
                res = sd._down_process("pb-res", lease)
            self.assertTrue(res["residue"])   # named, never silent


class BootDispatchTest(unittest.TestCase):
    def test_cold_boot_routes_to_process_payload(self):
        stub = _StubBench()
        root = tempfile.mkdtemp(prefix="sb-pb-")
        flipped = {"state": "up", "ports": {"temporal": 21049},
                   "proc_ids": [1]}
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root,
                                              SANDBAR_TEMPORAL_BIN=sys.executable)):
            with mock.patch.object(sd, "_bench_module", return_value=stub), \
                 mock.patch.object(sd, "_gates"), \
                 mock.patch.object(sd, "_up_process", return_value=flipped) as up, \
                 mock.patch.object(sd, "claim_subnet",
                                   side_effect=AssertionError("docker leg reached")):
                st = sd._boot_new_stage("pb-route", ["temporal"],
                                        {"repo_dir": None, "namespace": "pb"},
                                        30, cold_cleanup=True)
        self.assertEqual(st, flipped)
        self.assertEqual(up.call_count, 1)



def _reset_lock_cache():
    """lock_root() caches the first root it resolves — tests that point the
    env at a fresh temp dir must clear the cache or they share one root."""
    sd._LOCK_ROOT_CACHE = None


class DetachAndSweepTest(unittest.TestCase):
    def _lease(self, project):
        lease = sd.new_lease(project, holder_pid=os.getpid(), services=["temporal"])
        lease["lease_id"] = "lid-2"
        return lease

    def test_up_detaches_the_bench_from_the_spawning_cli(self):
        """Arbitrate gen0 defect: the ensure CLI must exit to return its
        receipt — the bench may only survive that exit via detach; the lease
        (not the spawner) owns it afterwards."""
        stub = _StubBench()
        with mock.patch.dict(os.environ, _env()):
            with mock.patch.object(sd, "_bench_module", return_value=stub), \
                 mock.patch.object(sd, "wait_temporal"), \
                 mock.patch.object(sd, "register_namespace",
                                   return_value=(True, "stub")):
                st = sd._up_process("pb-det", ["temporal"],
                                    {"ports": {"temporal": 21053},
                                     "namespace": "pb", "repo_dir": None},
                                    30, self._lease("pb-det"))
        try:
            self.assertEqual(st["state"], "up")
            self.assertTrue(st.get("bench_detached"))
            self.assertEqual(stub.detached, [stub.started[0][1]])
        finally:
            for _, pid in stub.started:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass

    def test_sweep_harvests_a_dead_leases_bench(self):
        import signal as _signal
        stub = _StubBench()
        proc = __import__("subprocess").Popen(
            # SANCTIONED-WAIT: 60s is the stub bench child's kill ceiling (the sweep's stop() ends it)
            [sys.executable, "-c", "import time; time.sleep(60)"])
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            _reset_lock_cache()
            # lease_dead = expired AND holder gone: the holder pid must be a
            # DEAD pid (the bench pid itself stays alive as the thing to reap).
            lease = sd.new_lease("pb-sweep", holder_pid=999999999,
                                 services=["temporal"])
            lease.update({"state": "up", "proc_ids": [proc.pid],
                          "ports": {"temporal": 21054},
                          "ts": time.time() - 10_000,
                          "heartbeat_ts": time.time() - 10_000,
                          "ttl_sec": 90, "bench_db": "/tmp/stub.db"})
            sd.write_lease("pb-sweep", lease)
            with mock.patch.object(sd, "_bench_module", return_value=stub):
                rpt = sd._sweep_process_benches()
        try:
            self.assertEqual([r["project"] for r in rpt["stopped"]], ["pb-sweep"])
            self.assertEqual(stub.stopped, [(21054, proc.pid)])
            # The sweep does NOT unlink the dead record (enumerate_leases'
            # reclaim pass owns that decision); the bench is what it reaps.
            self.assertIsNotNone(sd.read_lease("pb-sweep"))
        finally:
            try:
                proc.send_signal(_signal.SIGKILL)
                proc.wait(timeout=5)
            except Exception:                              # noqa: BLE001
                pass

    def test_sweep_leaves_a_live_lease_alone(self):
        stub = _StubBench()
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            _reset_lock_cache()
            lease = sd.new_lease("pb-live", holder_pid=os.getpid(),
                                 services=["temporal"])
            lease.update({"state": "up", "proc_ids": [999999],
                          "ports": {"temporal": 21055}, "ttl_sec": 90})
            sd.write_lease("pb-live", lease)
            with mock.patch.object(sd, "_bench_module", return_value=stub):
                rpt = sd._sweep_process_benches()
        self.assertEqual(rpt["stopped"], [])
        self.assertEqual(stub.stopped, [])
        self.assertIsNotNone(sd.read_lease("pb-live"))

class HoldWriteGuardTest(unittest.TestCase):
    """R1'' (arbitrate gen2): a hold's stale heartbeat write must never land
    after down's unlink. The write-time re-check (state=downing / gone /
    foreign id -> stop writing) is asserted through the real hold subprocess."""

    def test_hold_does_not_overwrite_a_downing_lease(self):
        import subprocess as _sub
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            _reset_lock_cache()
            proj = "pb-holdguard"
            proc = _sub.Popen(
                [sys.executable, str(INTEG / "stage_docker.py"), "hold",
                 "--project", proj, "--anchor-pid", str(os.getpid()),
                 "--lease-id", "L1"],
                stdout=_sub.DEVNULL, stderr=_sub.DEVNULL)
            try:
                pidfile = pathlib.Path(root) / ("holder-%s.pid" % proj)
                deadline = time.time() + 15
                hold_pid = None
                while time.time() < deadline:
                    try:
                        got = int(pidfile.read_text().strip())
                        if got == proc.pid:
                            hold_pid = got
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.1)
                self.assertIsNotNone(hold_pid)
                lease = sd.new_lease(proj, holder_pid=hold_pid,
                                     services=["temporal"])
                lease.update({"lease_id": "L1", "state": "up", "ttl_sec": 90,
                              "ports": {"temporal": 21061}})
                sd.write_lease(proj, lease)
                time.sleep(0.6)                     # one heartbeat lands
                lease["state"] = "downing"          # the downing flip
                sd.write_lease(proj, lease)
                rc = proc.wait(timeout=10)
                self.assertEqual(rc, 0)             # terminal (2), no write
                self.assertEqual(sd.read_lease(proj)["state"], "downing")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)


class GuardedReleaseTest(unittest.TestCase):
    def test_no_resurrection_is_a_plain_release(self):
        stub = _StubBench()
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            _reset_lock_cache()
            lease = sd.new_lease("pb-gr0", holder_pid=os.getpid(),
                                 services=["temporal"])
            lease.update({"state": "downing", "proc_ids": [1],
                          "ports": {"temporal": 21062}})
            sd.write_lease("pb-gr0", lease)
            with mock.patch.object(sd, "_bench_module", return_value=stub):
                sd._release_lease_guarded("pb-gr0", lease, budget=0.5)
            self.assertIsNone(sd.read_lease("pb-gr0"))

    def test_single_stale_write_is_re_deleted(self):
        import threading
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            _reset_lock_cache()
            lease = sd.new_lease("pb-gr1", holder_pid=os.getpid(),
                                 services=["temporal"])
            lease.update({"state": "downing", "lease_id": "L2",
                          "ports": {"temporal": 21063}})

            def resurrect_once():
                time.sleep(0.15)
                lease["state"] = "up"               # the stale heartbeat write
                sd.write_lease("pb-gr1", lease)
            t = threading.Thread(target=resurrect_once)
            t.start()
            sd._release_lease_guarded("pb-gr1", lease, budget=1.5)
            t.join(timeout=5)
            self.assertIsNone(sd.read_lease("pb-gr1"))

    def test_persistent_resurrection_is_fail_visible(self):
        import threading
        root = tempfile.mkdtemp(prefix="sb-pb-")
        with mock.patch.dict(os.environ, _env(SANDBAR_STAGE_LOCK_DIR=root)):
            _reset_lock_cache()
            lease = sd.new_lease("pb-gr2", holder_pid=os.getpid(),
                                 services=["temporal"])
            lease.update({"state": "downing", "lease_id": "L3",
                          "ports": {"temporal": 21064}})
            stop = {"flag": False}

            def resurrect_forever():
                while not stop["flag"]:
                    lease["state"] = "up"
                    sd.write_lease("pb-gr2", lease)
                    time.sleep(0.05)
            t = threading.Thread(target=resurrect_forever)
            t.start()
            try:
                with self.assertRaises(sd.StageError) as cm:
                    sd._release_lease_guarded("pb-gr2", lease, budget=0.8)
                self.assertEqual(cm.exception.kind, "fail")
                self.assertIn("复活", str(cm.exception))
            finally:
                stop["flag"] = True
                t.join(timeout=5)
                sd.release_lease("pb-gr2")


class BenchPortCloseTest(unittest.TestCase):
    """Arbitrate gen4: process_bench.stop must AWAIT port refusal — down
    returning while the stage still accepts connections is the docker-era
    contract breach this battery pins shut (real child processes, real
    sockets, bounded waits)."""

    def _child(self, port, close_delay):
        import subprocess as _sub
        # backlog 128: a listen(1) queue makes macOS refuse the SECOND probe
        # connect, which port_refuses would read as a closed port (artifact).
        code = (
            "import socket,signal,sys,time\n"
            "s=socket.socket()\n"
            "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
            "s.bind(('127.0.0.1',%d))\n" % (port,) +
            "s.listen(128)\n"
            "def _term(*a):\n"
            "    time.sleep(%s);s.close();sys.exit(0)\n" % (close_delay,) +
            "signal.signal(signal.SIGTERM,_term)\n"
            "print('ready',flush=True)\n"
            # SANCTIONED-WAIT: 60s is the stub bench child's kill ceiling (stop() ends it long before)
            "time.sleep(60)\n")
        # start_new_session: pgid == pid, the same group semantics the real
        # bench spawn uses (stop signals the group; a shared group would make
        # the group probes read the TEST process, not the child).
        return _sub.Popen([sys.executable, "-c", code],
                          stdout=_sub.PIPE, text=True,
                          start_new_session=True)

    def test_stop_awaits_port_refusal(self):
        import process_bench as pb
        port = 21171
        proc = self._child(port, "0.3")
        try:
            self.assertEqual(proc.stdout.readline().strip(), "ready")
            with mock.patch.dict(os.environ, {pb.REGISTRY_ENV:
                                              tempfile.mkdtemp(prefix="sb-reg-")}):
                block = pb.stop(port=port, pid=proc.pid, term_s=5, kill_s=3)
            self.assertTrue(block["clean"])
            self.assertTrue(block["port_closed"])
            self.assertTrue(block["port_refuses"])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_await_port_refuses_times_out_on_open_port(self):
        import process_bench as pb
        import socket as _socket
            # a listener the test itself holds: nothing will close it
        sock = _socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)   # real-server backlog; listen(1) refuses probe #2 on macOS
        port = sock.getsockname()[1]
        try:
            t0 = time.time()
            self.assertFalse(pb._await_port_refuses(port, 0.4))
            self.assertGreaterEqual(time.time() - t0, 0.3)
        finally:
            sock.close()

    def test_await_port_refuses_returns_immediately_when_closed(self):
        import process_bench as pb
        t0 = time.time()
        self.assertTrue(pb._await_port_refuses(21199, 5))
        self.assertLess(time.time() - t0, 2)


class EscapedServerTest(unittest.TestCase):
    """Arbitrate gen5: the temporal server child escapes the signalled group
    and re-binds the port ~2.5s after leader death. Modelled here: the
    grandchild runs in its OWN session (escapes the group signal exactly like
    the real server spawn), and stop must still end it via the pre-signal tree
    snapshot + the stable-refusal window."""

    def test_stop_kills_an_escaped_server_grandchild(self):
        import subprocess as _sub
        import process_bench as pb
        port = 21185
        gc = (
            "import socket,signal,sys,time\n"
            "s=socket.socket()\n"
            "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
            "s.bind(('127.0.0.1',%d))\n" % port +
            "s.listen(128)\n"
            "def _t(*a):\n"
            "    time.sleep(0.4);s.close();sys.exit(0)\n"
            "signal.signal(signal.SIGTERM,_t)\n"
            "print('gc-ready',flush=True)\n"
            # SANCTIONED-WAIT: 60s is the stub grandchild's kill ceiling (stop() ends it long before)
            "time.sleep(60)\n")
        child = (
            "import subprocess,sys,time\n"
            "subprocess.Popen([sys.executable,'-c',%r],"
            "start_new_session=True)\n" % gc +
            "print('ready',flush=True)\n"
            # SANCTIONED-WAIT: 60s is the stub leader's kill ceiling (stop() ends it long before)
            "time.sleep(60)\n")
        proc = _sub.Popen([sys.executable, "-c", child],
                          stdout=_sub.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "ready")
            time.sleep(0.3)                      # grandchild binds
            with mock.patch.dict(os.environ, {pb.REGISTRY_ENV:
                                              tempfile.mkdtemp(prefix="sb-reg-")}):
                block = pb.stop(port=port, pid=proc.pid, term_s=5, kill_s=3)
            self.assertTrue(block["clean"])
            self.assertTrue(block["port_closed"])
            self.assertFalse(pb.port_refuses(port) is False and block["clean"])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
