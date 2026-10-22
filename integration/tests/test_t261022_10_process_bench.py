#!/usr/bin/env python3
"""Unit battery for the docker-free process bench (ticket t261022-10).

Three seams, each judged by its own leg group. No docker, no temporal binary, no
Temporal server: the child-process legs use stub processes written here, so this
file runs on any checkout and finishes in seconds.

  seam 1  the free-port pick      (test_free_port_*)
  seam 2  the endpoint hand-off   (test_consumer_env_*)
  seam 3  the residue assertions  (test_residue_*, test_stop_*,
                                   test_reclaim_*, test_refused_*)

Seam 3 carries the two controls that make it an assertion and not decoration:
a POSITIVE control (a child that ignores SIGTERM proves the SIGKILL escalation,
so the down path is not "TERM and hope") and a NEGATIVE control (a live child is
reported dirty, so a green residue can never be vacuous).
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration"))

import process_bench as bench  # noqa: E402

MODULE = str(ROOT / "integration" / "process_bench.py")

#: Stub child: binds the port it is given, prints one readiness line, then
#: waits forever. SIGTERM keeps its default action (a well-behaved server).
_STUB_OBEDIENT = (
    "import socket, sys, threading\n"
    "port = int(sys.argv[1])\n"
    "s = socket.socket()\n"
    "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', port))\n"
    "s.listen(1)\n"
    "print('ready', flush=True)\n"
    "threading.Event().wait()\n"
)

#: Stub child that IGNORES SIGTERM: only SIGKILL can end it, which is exactly
#: the escalation proof the residue assertion needs.
_STUB_TERM_IGNORING = (
    "import signal, socket, sys, threading\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "port = int(sys.argv[1])\n"
    "s = socket.socket()\n"
    "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', port))\n"
    "s.listen(1)\n"
    "print('ready', flush=True)\n"
    "threading.Event().wait()\n"
)


#: Stub leader that starts a grandchild (same process group) and exits: the pid
#: probe alone would call this clean, the GROUP probe must not.
_STUB_FORKING = (
    "import subprocess, sys\n"
    "child = subprocess.Popen([sys.executable, '-c',\n"
    "                          'import threading; threading.Event().wait()'])\n"
    "print(child.pid, flush=True)\n"
)


def _spawn_stub(code, port):
    """Start a stub in its OWN session (pgid == pid, like the bench) and wait
    for its readiness line (a real signal, not a sleep)."""
    proc = subprocess.Popen([sys.executable, "-c", code, str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    line = proc.stdout.readline()
    if "ready" not in line:
        out = line + (proc.stdout.read() if proc.stdout else "")
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("stub child failed to come up: %r"
                             % out.strip()[-300:])
    return proc


def _cleanup(proc, port):
    """Unconditional teardown so a red leg leaks no process."""
    try:
        os.killpg(proc.pid, 9)
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    if proc.stdout:
        proc.stdout.close()
    bench.stop(port, proc.pid, term_s=0.2, kill_s=2.0)


# ---------------------------------------------------------------- seam 1 ----
def test_free_port_pick_returns_bindable_ports():
    ports = [bench.free_port() for _ in range(5)]
    assert len(set(ports)) == len(ports), "free_port returned a duplicate: %s" % ports
    for port in ports:
        assert isinstance(port, int) and port > 1024, port
        assert port not in (3099, 7233, 8233), \
            "the pick must never hand out a declared host port: %s" % port
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", port))
        finally:
            sock.close()


def test_free_port_pick_skips_a_port_that_is_taken():
    holder = socket.socket()
    try:
        holder.bind(("127.0.0.1", 0))
        taken = holder.getsockname()[1]
        picked = [bench.free_port() for _ in range(8)]
        assert taken not in picked, \
            "the kernel still holds %d, so a pick must not return it: %s" % (
                taken, picked)
    finally:
        holder.close()


# ---------------------------------------------------------------- seam 2 ----
def test_consumer_env_hands_over_the_bench_endpoint():
    base = {"PATH": "/bin", "KEEP_ME": "1"}
    env = bench.consumer_env(45678, base=base)
    assert env["SANDBAR_TARGET_HOST"] == "127.0.0.1:45678"
    assert env["SANDBAR_NAMESPACE"] == "default"
    assert env["KEEP_ME"] == "1"
    assert base == {"PATH": "/bin", "KEEP_ME": "1"}, \
        "the base environment must not be mutated"
    assert bench.endpoint(45678) == env["SANDBAR_TARGET_HOST"]


def test_consumer_env_overwrites_a_foreign_target_host():
    base = {"SANDBAR_TARGET_HOST": "127.0.0.1:7233",
            "SANDBAR_NAMESPACE": "sandbar-test"}
    env = bench.consumer_env(1, base=base)
    assert env["SANDBAR_TARGET_HOST"] == "127.0.0.1:1", \
        "the bench endpoint must win over an inherited production address"
    assert env["SANDBAR_NAMESPACE"] == "default"


def test_consumer_env_reaches_a_real_child_process(monkeypatch):
    monkeypatch.setenv("SANDBAR_BENCH_BASE_MARK", "inherited")
    port = bench.free_port()
    env = bench.consumer_env(port)
    out = subprocess.run(
        [sys.executable, "-c",
         "import os; print(os.environ['SANDBAR_TARGET_HOST']);"
         " print(os.environ['SANDBAR_BENCH_BASE_MARK'])"],
        env=env, capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr[-300:]
    lines = out.stdout.split()
    assert lines[0] == bench.endpoint(port), \
        "the child must receive the bench endpoint, got %r" % out.stdout
    assert lines[1] == "inherited", "the rest of the environment is inherited"


# ---------------------------------------------------------------- seam 3 ----
def test_residue_reports_a_live_child_as_dirty():
    port = bench.free_port()
    proc = _spawn_stub(_STUB_OBEDIENT, port)
    try:
        block = bench.residue(port, proc.pid)
        assert block["port_refuses"] is False, "a live listener must be seen"
        assert block["pid_alive"] is True
        assert block["group_alive"] is True
        assert proc.pid in block["survivors"], block
        assert bench.residue_clean(block) is False, \
            "a green residue on a live bench would be a vacuous assertion"
    finally:
        _cleanup(proc, port)


def test_residue_is_clean_after_a_normal_stop():
    port = bench.free_port()
    proc = _spawn_stub(_STUB_OBEDIENT, port)
    try:
        block = bench.stop(port, proc.pid, term_s=3.0, kill_s=2.0)
        assert block["escalated"] is False, \
            "a TERM-respecting child must not need SIGKILL: %s" % block
        assert block["port_refuses"] is True
        assert block["pid_alive"] is False
        assert block["group_alive"] is False
        assert block["clean"] is True, block
        assert bench.port_refuses(port) is True
    finally:
        _cleanup(proc, port)


def test_stop_escalates_to_sigkill_for_a_child_that_ignores_sigterm():
    port = bench.free_port()
    proc = _spawn_stub(_STUB_TERM_IGNORING, port)
    try:
        # The child really ignores SIGTERM: TERM alone leaves it standing.
        os.killpg(proc.pid, 15)
        assert bench.group_alive(proc.pid) is True, \
            "the fixture is broken: SIGTERM killed a child meant to ignore it"
        t0 = time.time()
        block = bench.stop(port, proc.pid, term_s=0.5, kill_s=3.0)
        elapsed = time.time() - t0
        assert block["escalated"] is True, \
            "SIGKILL escalation did not fire: %s" % block
        assert block["group_alive"] is False
        assert block["survivors"] == []
        assert block["clean"] is True, block
        assert elapsed < 4.0, "the escalation ran past its bound: %.2fs" % elapsed
    finally:
        _cleanup(proc, port)


def test_reclaim_removes_only_the_bench_temp_dir(tmp_path):
    ours = Path(tempfile.mkdtemp(prefix=bench.TEMP_PREFIX, dir=str(tmp_path)))
    assert bench.reclaim_db(str(ours / "temporal.db")) is True
    assert not ours.exists(), "the bench's own temp dir must be reclaimed"

    foreign = tmp_path / "not-ours"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("keep", encoding="utf-8")
    assert bench.reclaim_db(str(foreign / "temporal.db")) is False, \
        "a down path must never rmtree a directory it did not create"
    assert (foreign / "keep.txt").exists()
    assert bench.reclaim_db(None) is False


def test_refused_binary_starts_nothing_and_names_the_path(tmp_path):
    missing = tmp_path / "nowhere" / "temporal"
    root = tmp_path / "root"
    res = bench.start(bin_path=str(missing), root=str(root))
    assert res["ok"] is False, res
    assert "temporal binary not found" in res["reason"], res["reason"]
    assert str(missing) in res["reason"], "the reason must name the path tried"
    leftovers = list(root.iterdir()) if root.exists() else []
    assert leftovers == [], \
        "a refused start must leave no directory behind: %s" % leftovers


def test_refused_binary_command_exits_non_zero_named(tmp_path):
    missing = tmp_path / "nowhere" / "temporal"
    out = subprocess.run(
        [sys.executable, "-B", MODULE, "up", "--bin", str(missing)],
        capture_output=True, text=True, timeout=20)
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "ENV_FAIL" in out.stderr, out.stderr
    assert "temporal binary not found" in out.stderr, out.stderr
    assert '"ok": false' in out.stdout, out.stdout


def test_down_command_refuses_without_ids():
    out = subprocess.run([sys.executable, "-B", MODULE, "down"],
                         capture_output=True, text=True, timeout=20)
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "ENV_FAIL" in out.stderr and "--pid" in out.stderr, out.stderr


def test_residue_probe_is_group_wide_not_pid_wide():
    """A dead leader does not mean clean: a surviving grandchild in the same
    process group is residue, and only the group probe can see it."""
    proc = subprocess.Popen([sys.executable, "-c", _STUB_FORKING],
                            stdout=subprocess.PIPE, text=True,
                            start_new_session=True)
    grandchild = 0
    try:
        grandchild = int((proc.stdout.readline() or "0").strip() or 0)
        proc.wait(timeout=10)          # the leader is gone, the grandchild is not
        block = bench.residue(bench.free_port(), proc.pid)
        assert bench.pid_alive(proc.pid) is False, block
        assert block["group_alive"] is True, \
            "a surviving grandchild must read as residue: %s" % block
        assert grandchild in block["survivors"] or block["survivors"], block
        assert bench.residue_clean(block) is False, block
    finally:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        if grandchild:
            try:
                os.kill(grandchild, 9)
            except OSError:
                pass
        if proc.stdout:
            proc.stdout.close()


def test_a_bench_that_fails_boot_names_the_reason_and_cleans_up(tmp_path):
    """The other half of the bad-binary contract: a binary that starts and dies
    (a flag drift, a broken build) is a NAMED refusal carrying the child's own
    words, and it leaves no temp dir behind."""
    fake = tmp_path / "fake-temporal"
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'flag parse error: unknown flag --search-attribute' >&2\n"
        "exit 9\n", encoding="utf-8")
    fake.chmod(0o755)
    root = tmp_path / "root"
    res = bench.start(bin_path=str(fake), boot_s=3.0, root=str(root))
    assert res["ok"] is False, res
    assert "rc=9" in res["reason"], res["reason"]
    assert "unknown flag" in res["reason"], \
        "the refusal must carry the child's own words: %s" % res["reason"]
    leftovers = list(root.iterdir()) if root.exists() else []
    assert leftovers == [], \
        "a failed boot must reclaim its temp dir: %s" % leftovers
