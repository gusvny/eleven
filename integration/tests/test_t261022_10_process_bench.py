#!/usr/bin/env python3
"""Unit battery for the docker-free process bench (ticket t261022-10).

Four seams, each judged by its own leg group. No docker, no temporal binary, no
Temporal server: the child-process legs use stub processes written here, so this
file runs on any checkout and finishes in seconds.

  seam 1  the free-port pick      (test_free_port_*)
  seam 2  the endpoint hand-off   (test_consumer_env_*)
  seam 3  the residue assertions  (test_residue_*, test_stop_*,
                                   test_reclaim_*, test_refused_*)
  seam 4  the bench dies with its owner (ticket t261022-15):
                                   (test_deadman_*, test_sigterm_*,
                                    test_sweep_*, test_up_detaches_*)

Seam 3 carries the two controls that make it an assertion and not decoration:
a POSITIVE control (a child that ignores SIGTERM proves the SIGKILL escalation,
so the down path is not "TERM and hope") and a NEGATIVE control (a live child is
reported dirty, so a green residue can never be vacuous).

Seam 4 judges the bench from OUTSIDE the owner: the owner is a separate process,
it is killed, and this process decides on the bench pid, the port and the temp
dir. The sweep legs plant registry entries by hand, so the backstop is judged on
its own and not as a side effect of the deadman. One leg is the real temporal
server and skips with a named reason when the binary is missing (ENV gap).
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration"))

import process_bench as bench  # noqa: E402

MODULE = str(ROOT / "integration" / "process_bench.py")


@pytest.fixture(autouse=True)
def bench_registry(tmp_path, monkeypatch):
    """Never let a leg touch the host's real bench registry."""
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    monkeypatch.setenv(bench.REGISTRY_ENV, str(registry))
    return registry

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
        holder.listen(1)          # a bound socket without listen still refuses
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


# ---------------------------------------------------------------- seam 4 ----
# The bench dies with its owner (ticket t261022-15). Every leg judges the bench
# from OUTSIDE the owner: a separate process starts it, this process kills the
# owner, and the bench pid, the port and the temp dir are read from here.

#: A stand-in for `temporal server start-dev`: binds the given port, then waits.
#: SIGTERM keeps its default action, so it behaves like an obedient server.
_FAKE_TEMPORAL = '''"""Fake temporal CLI: a bench that binds its port and waits."""
import socket, sys, time
argv = sys.argv[1:]
if argv and argv[0] == "server":
    port = int(argv[argv.index("--port") + 1])
    db = argv[argv.index("--db-filename") + 1]
    open(db, "a").close()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(16)
    print("fake bench ready", flush=True)
    while True:
        time.sleep(0.2)
print("fake operator ok", flush=True)
'''

#: How long the owner process idles before it gives up. This is NOT a bound the
#: battery waits for: every leg kills the owner, and the small default just stops
#: a stray owner from living forever. Injectable for a slow host.
OWNER_IDLE_S = float(os.environ.get("SANDBAR_BENCH_OWNER_IDLE_S") or 30)

#: The owner process: starts one bench through the real module, reports the
#: handle, then idles until this battery kills it.
_OWNER = '''
import json, sys, time
sys.path.insert(0, %r)
import process_bench as bench
res = bench.start(bin_path=%r, boot_s=%.1f)
print(json.dumps(res), flush=True)
if not res.get("ok"):
    sys.exit(2)
# SANCTIONED-WAIT: a keep-alive idle, not a waited bound (the leg kills the
# owner); the length is injectable through SANDBAR_BENCH_OWNER_IDLE_S.
time.sleep(float(%r))
'''


@pytest.fixture
def fake_temporal(tmp_path):
    """An executable stand-in for the temporal CLI (no binary, no server)."""
    script = tmp_path / "fake_temporal.py"
    script.write_text(_FAKE_TEMPORAL, encoding="utf-8")
    wrapper = tmp_path / "temporal"
    wrapper.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                       % (sys.executable, script), encoding="utf-8")
    wrapper.chmod(0o755)
    return str(wrapper)


#: The module CLI's ceiling. Injectable, and seconds-scale by default: the real
#: `up` answers in about 0.3 s, so this is a hang detector, not patience.
CLI_TIMEOUT_S = float(os.environ.get("SANDBAR_BENCH_CLI_TIMEOUT_S") or 60)


def _run_cli(argv, timeout_s=None):
    """Run the module CLI under an injectable ceiling, naming the check on a hang."""
    bound = CLI_TIMEOUT_S if timeout_s is None else float(timeout_s)
    try:
        return subprocess.run([sys.executable, "-B", MODULE] + [str(a) for a in argv],
                              capture_output=True, text=True, timeout=bound)
    except subprocess.TimeoutExpired:
        raise AssertionError("the bench CLI did not answer within %.1fs: %s"
                             % (bound, " ".join(str(a) for a in argv)))


def _rmtree(path):
    """Best-effort reclaim of a temp dir a red leg may have left behind."""
    shutil.rmtree(str(path), ignore_errors=True)


def test_a_taken_requested_port_refuses_before_anything_is_created(
        tmp_path, fake_temporal):
    """The requested-port feature (merged from main), judged where this ticket
    moved it: a taken port refuses by name and creates no temp dir either, so a
    refusal still costs nothing."""
    holder = socket.socket()
    try:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)          # a bound socket without listen still refuses
        taken = holder.getsockname()[1]
        root = tmp_path / "root"
        res = bench.start(bin_path=fake_temporal, port=taken, boot_s=3.0,
                          root=str(root))
        assert res["ok"] is False, res
        assert "already in use" in res["reason"], res["reason"]
        assert str(taken) in res["reason"], res["reason"]
        assert (list(root.iterdir()) if root.exists() else []) == [], \
            "a port refusal must leave no temp dir behind"
    finally:
        holder.close()


def _await_true(pred, bound_s):
    """The elapsed time as soon as pred() holds, else None after the bound."""
    t0 = time.time()
    while time.time() - t0 < float(bound_s):
        if pred():
            return time.time() - t0
        time.sleep(0.02)
    return None


def _start_owner(tmp_path, bin_path, boot_s=20.0):
    """Start a bench in a SEPARATE owner process; return (owner, handle)."""
    script = tmp_path / "owner.py"
    script.write_text(_OWNER % (str(ROOT / "integration"), bin_path, boot_s,
                                OWNER_IDLE_S), encoding="utf-8")
    # Own session: the owner is then the leader of its own process group, the
    # same shape a bench-running case has, so a budget kill of that group is the
    # kill this battery must survive (ticket t261022-15).
    owner = subprocess.Popen([sys.executable, "-B", str(script)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
    line = owner.stdout.readline()
    try:
        handle = json.loads(line)
    except ValueError:
        handle = {}
    assert handle.get("ok"), ("the owner process did not start a bench: %r"
                              % (line or "").strip()[-400:])
    return owner, handle


def _kill_quietly(handle):
    """Best-effort teardown, so a red leg leaks no bench."""
    if not handle:
        return
    try:
        bench.stop(handle["port"], handle["pid"], db=handle["db"],
                   term_s=0.5, kill_s=3.0)
    except Exception:                                        # noqa: BLE001
        pass
    try:
        os.unlink(str(bench._entry_path(handle["pid"])))
    except OSError:
        pass


def _dead_pid():
    """A pid that is certainly gone (a child this process has reaped)."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    return proc.pid


def _plant(registry, pid, pgid, port=None, db_dir=None, owner_pid=None,
           detached=False):
    """Plant one registry entry by hand (the backstop is judged on its own)."""
    entry = {"pid": pid, "pgid": pgid, "port": port or 0,
             "db_dir": str(db_dir) if db_dir else "",
             "started_at": time.time(), "owner_pid": owner_pid or 0,
             "detached": detached}
    path = registry / ("%d.json" % pid)
    path.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
    return path


def test_deadman_reaps_the_bench_when_the_owner_is_sigkilled(tmp_path,
                                                             fake_temporal,
                                                             bench_registry):
    """(a) SIGKILL the owner: the bench pid, the port and the temp dir go too."""
    owner, handle = _start_owner(tmp_path, fake_temporal)
    pid, port = handle["pid"], handle["port"]
    db_dir = Path(handle["db"]).parent
    try:
        assert bench.pid_alive(pid) is True, "no bench: the fixture is broken"
        assert bench.port_refuses(port) is False, "no listener: broken fixture"
        entry = bench._entry_path(pid)
        assert entry.exists(), "a started bench must register itself"

        # The budget-kill shape: SIGKILL the owner's whole process group.
        os.killpg(owner.pid, signal.SIGKILL)
        owner.wait(timeout=5)
        gone_s = _await_true(lambda: not bench.pid_alive(pid), 5.0)
        assert gone_s is not None, "the bench outlived its SIGKILLed owner"
        assert gone_s <= 2.0, ("the deadman took %.2fs (acceptance: about 2 s)"
                               % gone_s)
        assert bench.group_alive(pid) is False, \
            "a member of the bench group survived the deadman"
        assert bench.port_refuses(port) is True, "the port still serves"
        assert _await_true(lambda: not db_dir.exists(), 3.0) is not None, \
            "the temp dir was not reclaimed: %s" % db_dir
        assert entry.exists() is False, \
            "the deadman must drop the registry entry it handled"
    finally:
        _kill_quietly(handle)
        owner.stdout.close()
        owner.stderr.close()


def test_sigterm_handler_reaps_the_bench(tmp_path, fake_temporal):
    """(b) An ordinary kill: the owner's handler runs the same teardown and the
    owner still dies BY the signal (the handler must not swallow a kill)."""
    owner, handle = _start_owner(tmp_path, fake_temporal)
    pid, port = handle["pid"], handle["port"]
    db_dir = Path(handle["db"]).parent
    try:
        os.kill(owner.pid, signal.SIGTERM)
        rc = owner.wait(timeout=30)
        assert rc == -signal.SIGTERM, \
            "the owner did not die by SIGTERM (rc=%s)" % rc
        gone_s = _await_true(lambda: not bench.pid_alive(pid), 5.0)
        assert gone_s is not None, "the bench outlived its SIGTERMed owner"
        assert bench.port_refuses(port) is True, "the port still serves"
        assert _await_true(lambda: not db_dir.exists(), 3.0) is not None, \
            "the temp dir was not reclaimed: %s" % db_dir
    finally:
        _kill_quietly(handle)
        owner.stdout.close()
        owner.stderr.close()


def test_the_kill_handler_tears_down_then_defers_to_the_previous_handler(
        fake_temporal, monkeypatch):
    """The handler path on its own: teardown runs, then the signal goes on to
    whatever handler was there before (a module must not hide a kill)."""
    monkeypatch.setattr(bench, "_IN_TEARDOWN", False)
    handle = bench.start(bin_path=fake_temporal)
    try:
        assert handle["ok"], handle
        assert bench._HANDLERS_ON is True, "no handlers: atexit-only teardown"
        assert signal.getsignal(signal.SIGTERM) is bench._on_kill_signal
        seen = []
        monkeypatch.setitem(bench._PREV_HANDLERS, signal.SIGTERM,
                            lambda signum, frame: seen.append(signum))
        bench._on_kill_signal(signal.SIGTERM, None)
        assert seen == [signal.SIGTERM], \
            "the handler must defer to the previous handler, not swallow it"
        assert bench.pid_alive(handle["pid"]) is False
        assert bench.port_refuses(handle["port"]) is True
        assert not Path(handle["db"]).parent.exists()
    finally:
        _kill_quietly(handle)


def test_sweep_reaps_a_planted_orphan_and_names_it(bench_registry):
    """(c) A bench whose owner is gone is swept, and the sweep says what went."""
    dead = _dead_pid()
    port = bench.free_port()
    db_dir = Path(tempfile.mkdtemp(prefix=bench.TEMP_PREFIX))
    stub = _spawn_stub(_STUB_OBEDIENT, port)
    entry = _plant(bench_registry, stub.pid, stub.pid, port=port,
                   db_dir=db_dir, owner_pid=dead)
    try:
        swept = bench.sweep()
        assert len(swept) == 1, swept
        record = swept[0]
        assert record["pid"] == stub.pid, record
        assert "orphan" in record["reason"], record
        assert str(dead) in record["reason"], \
            "the record must name the owner it found gone: %s" % record
        assert record["killed"] is True, record
        assert record["db_removed"] is True, record
        assert bench.group_alive(stub.pid) is False, \
            "the orphan group survived the sweep"
        assert bench.port_refuses(port) is True, "the port still serves"
        assert not db_dir.exists(), "the temp dir survived the sweep"
        assert not entry.exists(), "the swept entry is still on the registry"
    finally:
        _cleanup(stub, port)
        _rmtree(db_dir)


def test_sweep_reaps_a_group_whose_leader_is_gone(bench_registry):
    """A dead leader with a survivor in its group is the leak shape; the group
    probe must catch it, not the pid probe."""
    dead = _dead_pid()
    port = bench.free_port()
    db_dir = Path(tempfile.mkdtemp(prefix=bench.TEMP_PREFIX))
    stub = _spawn_stub(_STUB_OBEDIENT, port)
    _plant(bench_registry, dead, stub.pid, port=port, db_dir=db_dir,
           owner_pid=dead)
    try:
        swept = bench.sweep()
        assert len(swept) == 1, swept
        record = swept[0]
        assert record["reason"].startswith("stale: pid"), record
        assert "group" in record["reason"], record
        assert record["killed"] is True, record
        assert bench.group_alive(stub.pid) is False
        assert not db_dir.exists()
    finally:
        _cleanup(stub, port)
        _rmtree(db_dir)


def test_sweep_drops_a_stale_entry_and_reclaims_its_temp_dir(bench_registry):
    """Nothing left to kill: the entry and the temp dir still go."""
    dead = _dead_pid()
    db_dir = Path(tempfile.mkdtemp(prefix=bench.TEMP_PREFIX))
    entry = _plant(bench_registry, dead, dead, db_dir=db_dir, owner_pid=dead)
    swept = bench.sweep()
    assert len(swept) == 1, swept
    record = swept[0]
    assert "are gone" in record["reason"], record
    assert record["killed"] is False, record
    assert record["db_removed"] is True, record
    assert not db_dir.exists()
    assert not entry.exists()


def test_sweep_drops_and_names_an_unreadable_entry(bench_registry):
    """A half-written entry must not block the sweep, and must not vanish
    silently either."""
    path = bench_registry / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    swept = bench.sweep()
    assert len(swept) == 1, swept
    assert "unreadable" in swept[0]["reason"], swept[0]
    assert not path.exists()


def test_sweep_leaves_a_bench_whose_owner_is_alive(bench_registry):
    """The sweep is a backstop for dead owners, never a killer of live work."""
    port = bench.free_port()
    stub = _spawn_stub(_STUB_OBEDIENT, port)
    entry = _plant(bench_registry, stub.pid, stub.pid, port=port,
                   owner_pid=os.getpid())
    try:
        assert bench.sweep() == [], "a live owner's bench must be left alone"
        assert bench.group_alive(stub.pid) is True
        assert entry.exists()
    finally:
        _cleanup(stub, port)


def test_start_sweeps_before_it_starts_and_says_so(bench_registry,
                                                   fake_temporal, capsys):
    """Every start sweeps, and the sweep is never silent."""
    dead = _dead_pid()
    port = bench.free_port()
    db_dir = Path(tempfile.mkdtemp(prefix=bench.TEMP_PREFIX))
    stub = _spawn_stub(_STUB_OBEDIENT, port)
    _plant(bench_registry, dead, stub.pid, port=port, db_dir=db_dir,
           owner_pid=dead)
    handle = None
    try:
        handle = bench.start(bin_path=fake_temporal)
        assert handle["ok"], handle
        err = capsys.readouterr().err
        assert str(stub.pid) in err, \
            "the sweep must name what it removed (stderr was %r)" % err[-400:]
        assert "bench sweep" in err, err[-400:]
        assert bench.group_alive(stub.pid) is False
        assert not db_dir.exists()
    finally:
        _kill_quietly(handle)
        _cleanup(stub, port)
        _rmtree(db_dir)


def test_a_killed_watcher_leaves_a_bench_the_next_start_sweeps(
        fake_temporal, bench_registry):
    """The measured leak shape: only the watcher dies, the bench keeps serving.
    The registry backstop must reclaim it on the next bench activity."""
    handle = bench.start(bin_path=fake_temporal)
    pid, port = handle["pid"], handle["port"]
    db_dir = Path(handle["db"]).parent
    second = None
    try:
        proc = bench._HANDLES.pop(pid)["proc"]   # the owner that started it
        os.kill(pid, signal.SIGKILL)
        proc.wait(timeout=5)               # a zombie counts as alive: reap it
        assert _await_true(lambda: not bench.pid_alive(pid), 3.0) is not None
        assert bench.port_refuses(port) is False, \
            "the fixture is broken: the bench should still serve (the leak)"
        second = bench.start(bin_path=fake_temporal)
        assert second["ok"], second
        assert bench.port_refuses(port) is True, "the leaked port still serves"
        assert bench.group_alive(pid) is False, "the leaked group survives"
        assert _await_true(lambda: not db_dir.exists(), 3.0) is not None, \
            "the leaked temp dir was not reclaimed"
    finally:
        _kill_quietly(second)
        _kill_quietly(handle)
        _rmtree(db_dir)


def test_up_detaches_and_down_still_reaps(bench_registry, fake_temporal):
    """A manual bench is unaffected: it outlives `up`, the sweep leaves it, and
    `down` reaps it with no escalation."""
    up = _run_cli(["up", "--bin", fake_temporal])
    assert up.returncode == 0, (up.stdout, up.stderr)
    handle = json.loads(up.stdout.strip().splitlines()[-1])
    pid, port = handle["pid"], handle["port"]
    try:
        assert bench.pid_alive(pid) is True, "the bench must outlive the up CLI"
        entry = json.loads(bench._entry_path(pid).read_text(encoding="utf-8"))
        assert entry["detached"] is True, entry
        assert bench.sweep() == [], "a handed-over bench must not be swept"
        assert bench.group_alive(pid) is True

        down = _run_cli(["down", "--port", port, "--pid", pid,
                         "--db", handle["db"]])
        assert down.returncode == 0, (down.stdout, down.stderr)
        block = json.loads(down.stdout.strip().splitlines()[-1])
        assert block["clean"] is True, block
        assert block["escalated"] is False, \
            "a handed-over obedient bench must not need SIGKILL: %s" % block
        assert block["port_refuses"] is True and block["db_removed"] is True
        assert not bench._entry_path(pid).exists()
    finally:
        _kill_quietly(handle)


def test_the_real_temporal_bench_dies_with_its_owner(tmp_path):
    """The same proof on the real server. The binary is gitignored and
    provisioned per checkout, so a missing one is a NAMED skip (an ENV gap),
    never a silent green."""
    binary = bench.default_bin()
    if not os.path.exists(binary):
        pytest.skip("ENV gap: temporal binary missing (%s) — set "
                    "SANDBAR_TEMPORAL_BIN to run this leg" % binary)
    owner, handle = _start_owner(tmp_path, binary, boot_s=60.0)
    pid, port = handle["pid"], handle["port"]
    db_dir = Path(handle["db"]).parent
    try:
        assert bench.port_refuses(port) is False, "the real bench is not up"
        os.kill(owner.pid, signal.SIGKILL)
        owner.wait(timeout=10)
        gone_s = _await_true(lambda: not bench.pid_alive(pid), 6.0)
        assert gone_s is not None, "the real bench outlived its dead owner"
        assert gone_s <= 3.0, ("the real bench took %.2fs to go" % gone_s)
        assert bench.port_refuses(port) is True, "the real port still serves"
        assert _await_true(lambda: not db_dir.exists(), 5.0) is not None, \
            "the real bench's temp dir was not reclaimed"
    finally:
        _kill_quietly(handle)
        owner.stdout.close()
        owner.stderr.close()
