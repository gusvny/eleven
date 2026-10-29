#!/usr/bin/env python3
"""Failure-face battery for the process bench (ticket t261029-31, KI-389;
re-homed here by t261029-35).

Two fail-open shapes are judged here, plus the control that proves the fix
changed nothing that already worked:

  face A  an unwritable --root     -> named refusal, exit 2, nothing started
  face B  an unwritable registry   -> named refusal, nothing left running
  face C  a writable root+registry -> today's receipt, today's files

Why the file sits under server/engine/tests (t261029-35): the quickmanual gate
runs its declared battery as `pytest server/engine/tests -q <node>`, so a battery
under integration/tests is never collected there — pytest takes the lane root as
rootdir and integration/conftest.py's `pytest_plugins` is then a non-top-level
declaration, which newer pytest refuses before any case runs. The cases below
are unchanged by the move; only this docstring and the repo-root arithmetic are.

Every face is judged from the OUTSIDE: the registry (the face that makes a
bench findable), the port (does anything still serve?) and the temp dir tree.
The old shapes were (a) a bare PermissionError with exit 1 on an unwritable
root, and (b) a receipt saying ok:true for a bench that was never registered
and so invisible to the residue sweep. A test that reads only the module's
return value would have passed on both, so each case also reads the filesystem
and the socket.

The stub that stands in for the temporal CLI is the same stand-in the
t261022-10 battery uses (bind the port, answer operator subcommands rc 0, wait),
with one addition: it appends its own invocation to a log, so "nothing was
started" is a positive statement and not the absence of evidence.

Faces: offline, seconds-scale, no docker, no Temporal server, no network beyond
a loopback listener the stub opens, and it never touches the console on 3099.
Every case asserts in teardown that it left no bench, no registry entry and no
temp dir behind.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "integration"))

import process_bench as bench  # noqa: E402

MODULE = str(ROOT / "integration" / "process_bench.py")

#: Stand-in for `temporal server start-dev`: binds its port, writes its db file,
#: waits. Other subcommands answer rc 0, like `operator namespace describe`.
#: Every invocation is appended to __LOG__ so a case can say "the binary never
#: ran" instead of "I saw no process".
_STUB = '''"""Stub temporal CLI for the failure-face battery."""
import socket, sys, time
log = __LOG__
try:
    log.write(" ".join(sys.argv[1:3]) + chr(10))
    log.close()
except OSError:
    pass
argv = sys.argv[1:]
if argv and argv[0] == "server":
    port = int(argv[argv.index("--port") + 1])
    db = argv[argv.index("--db-filename") + 1]
    open(db, "a").close()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(16)
    print("stub bench ready", flush=True)
    while True:
        time.sleep(0.2)
print("stub operator ok", flush=True)
'''

#: Bound for a CLI leg (the module answers in well under a second).
CLI_TIMEOUT_S = 60.0


@pytest.fixture(autouse=True)
def env_state(tmp_path, monkeypatch):
    """Per-case isolation plus the teardown assertion every case owes.

    The registry is per-case (no host bench is ever swept), the wait bounds are
    injected (L25: evidence bought with small bounds, never a production sleep),
    and the teardown flips permissions back, kills anything the case leaked, and
    then asserts the case left nothing behind.
    """
    state = {"tmp": tmp_path, "registry": tmp_path / "registry",
             "pids": [], "modes": []}
    state["registry"].mkdir()
    monkeypatch.setenv(bench.REGISTRY_ENV, str(state["registry"]))
    monkeypatch.setattr(bench, "TERM_S", 1.0)
    monkeypatch.setattr(bench, "KILL_S", 2.0)
    monkeypatch.setattr(bench, "PORT_CLOSE_S", 3.0)
    monkeypatch.setattr(bench, "PORT_STABLE_S", 0.25)
    monkeypatch.setattr(bench, "SWEEP_TERM_S", 0.5)
    monkeypatch.setattr(bench, "SWEEP_KILL_S", 1.0)
    yield state

    # --- teardown: give the tmp tree back its permissions, kill a leak, assert
    for path, mode in reversed(state["modes"]):
        try:
            os.chmod(str(path), mode)
        except OSError:
            pass
    for pid in state["pids"]:
        if bench.pid_alive(pid):
            try:
                os.killpg(int(pid), signal.SIGKILL)
            except OSError:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except OSError:
                    pass
    deadline = time.time() + 5.0
    while time.time() < deadline and any(bench.pid_alive(p) for p in state["pids"]):
        time.sleep(0.05)
    survivors = [p for p in state["pids"] if bench.pid_alive(p)]
    assert survivors == [], "the case left a bench process behind: %s" % survivors
    assert bench._HANDLES == {}, \
        "the case left a bench handle behind: %s" % sorted(bench._HANDLES)
    leaked = sorted(str(p) for p in state["tmp"].rglob(bench.TEMP_PREFIX + "*"))
    assert leaked == [], "the case left bench temp dirs behind: %s" % leaked
    assert bench.entries() == [], \
        "the case left registry entries behind: %s" % bench.entries()


def _lock(state, path):
    """chmod a directory read-only and remember to give the mode back."""
    path.mkdir(parents=True, exist_ok=True)
    state["modes"].append((path, os.stat(str(path)).st_mode & 0o777))
    os.chmod(str(path), 0o555)
    return path


def _fake_temporal(tmp_path):
    """An executable stand-in for the temporal CLI, plus its invocation log."""
    log = tmp_path / "stub-invocations.log"
    script = tmp_path / "stub_temporal.py"
    script.write_text(_STUB.replace("__LOG__", "open(%r, 'a')" % str(log)),
                      encoding="utf-8")
    wrapper = tmp_path / "temporal"
    wrapper.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                       % (sys.executable, script), encoding="utf-8")
    wrapper.chmod(0o755)
    return str(wrapper), log


def _cli(argv, env_extra, timeout_s=CLI_TIMEOUT_S):
    """Run the module CLI under an injectable ceiling with a controlled env."""
    env = dict(os.environ)
    env.update({
        "SANDBAR_BENCH_TERM_S": "1",
        "SANDBAR_BENCH_KILL_S": "2",
        "SANDBAR_BENCH_PORT_CLOSE_S": "3",
        "SANDBAR_BENCH_PORT_STABLE_S": "0.25",
        "SANDBAR_BENCH_SWEEP_TERM_S": "0.5",
        "SANDBAR_BENCH_SWEEP_KILL_S": "1",
    })
    env.update(env_extra)
    return subprocess.run([sys.executable, "-B", MODULE] + [str(a) for a in argv],
                          capture_output=True, text=True, timeout=float(timeout_s),
                          env=env)


def _last_json(stdout):
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    assert lines, "the CLI printed no receipt on stdout: %r" % stdout
    return json.loads(lines[-1])


def _wait_refuses(port, bound_s=5.0):
    deadline = time.time() + bound_s
    while time.time() < deadline:
        if bench.port_refuses(port):
            return True
        time.sleep(0.05)
    return bench.port_refuses(port)


# ---------------------------------------------------------------- face A ----
def test_unwritable_root_refuses_by_name_and_starts_nothing(env_state, tmp_path):
    """A root this process cannot write into is a NAMED refusal, and the bench
    binary is never executed."""
    binary, log = _fake_temporal(tmp_path)
    root = _lock(env_state, tmp_path / "locked-root")

    res = bench.start(bin_path=binary, root=str(root), boot_s=5.0)

    assert res["ok"] is False, res
    reason = res["reason"]
    assert "root" in reason, reason
    assert str(root.resolve()) in reason, \
        "the refusal must name the path it judged: %s" % reason
    assert "not writable" in reason, \
        "the refusal must name the check that failed: %s" % reason
    assert "pid" not in res and "port" not in res, \
        "a refusal must not hand out a bench handle: %s" % res
    # nothing started: the binary never ran, no entry, no temp dir
    assert not log.exists(), \
        "the bench binary ran on a refused root: %s" % log.read_text(
            encoding="utf-8", errors="replace")
    assert bench.entries() == []
    assert bench._HANDLES == {}
    assert sorted(p.name for p in root.iterdir()) == []
    assert list(env_state["tmp"].rglob(bench.TEMP_PREFIX + "*")) == []


def test_unwritable_root_cli_leaves_with_a_receipt_not_a_traceback(env_state, tmp_path):
    """The old face: a bare PermissionError traceback and exit 1. The new face:
    the module's documented {"ok": false, "reason": ...} and exit 2."""
    binary, log = _fake_temporal(tmp_path)
    root = _lock(env_state, tmp_path / "locked-root")

    out = _cli(["up", "--bin", binary, "--root", str(root)],
               {"SANDBAR_BENCH_REGISTRY": str(env_state["registry"])})

    assert out.returncode == 2, \
        "a refusal exits 2, never 1 (rc=%s, stderr=%r)" % (
            out.returncode, out.stderr[-400:])
    assert "Traceback" not in out.stderr, out.stderr[-600:]
    assert "ENV_FAIL" in out.stderr, out.stderr[-400:]
    receipt = _last_json(out.stdout)
    assert receipt["ok"] is False, receipt
    assert str(root.resolve()) in receipt["reason"], receipt["reason"]
    assert "not writable" in receipt["reason"], receipt["reason"]
    assert not log.exists(), "the refused CLI still executed the bench binary"
    assert bench.entries() == []


def test_missing_root_under_an_unwritable_parent_refuses_by_name(env_state, tmp_path):
    """A root that does not exist is created only when its parent can take it;
    otherwise it is the same named refusal and nothing is created."""
    binary, log = _fake_temporal(tmp_path)
    parent = _lock(env_state, tmp_path / "locked-parent")
    root = parent / "sub" / "deeper"

    res = bench.start(bin_path=binary, root=str(root), boot_s=5.0)

    assert res["ok"] is False, res
    reason = res["reason"]
    assert str(root.resolve()) in reason, reason
    assert str(parent.resolve()) in reason, \
        "the refusal must name the parent that cannot take the root: %s" % reason
    assert "not writable" in reason, reason
    assert not root.exists() and not root.parent.exists(), \
        "a refused start created the root's parents"
    assert not log.exists()
    assert bench.entries() == []


def test_a_root_that_is_a_file_refuses_by_name(env_state, tmp_path):
    """The other root fault: a path that exists but is not a directory. It must
    be named as such, not reported as a permission problem."""
    binary, log = _fake_temporal(tmp_path)
    root = tmp_path / "not-a-dir"
    root.write_text("x", encoding="utf-8")

    res = bench.start(bin_path=binary, root=str(root), boot_s=5.0)

    assert res["ok"] is False, res
    assert "not a directory" in res["reason"], res["reason"]
    assert str(root) in res["reason"], res["reason"]
    assert not log.exists()
    assert bench.entries() == []


# ---------------------------------------------------------------- face B ----
def test_unwritable_registry_refuses_instead_of_running_unregistered(env_state, tmp_path):
    """Policy: REFUSE. An unregistered bench cannot be found by the residue
    sweep, so it must not be left running - and the receipt must say which
    registry path failed and how."""
    binary, _log = _fake_temporal(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    port = bench.free_port()
    _lock(env_state, env_state["registry"])

    res = bench.start(bin_path=binary, root=str(root), port=port, boot_s=5.0)

    assert res["ok"] is False, res
    reason = res["reason"]
    assert "registry" in reason, reason
    assert str(env_state["registry"]) in reason, \
        "the refusal must name the registry path: %s" % reason
    assert "not writable" in reason or "cannot be created" in reason, \
        "the refusal must name the check that failed: %s" % reason
    assert "unregistered" in reason, \
        "the receipt must say the bench was refused BECAUSE it could not be " \
        "registered: %s" % reason
    assert "pid" not in res, "a refusal must not hand out a bench handle: %s" % res
    # nothing left running: the port the bench would have served must refuse,
    # no temp dir survives, and no registry entry exists.
    assert _wait_refuses(port), \
        "the refused bench is still serving on port %d" % port
    assert list(root.iterdir()) == [], \
        "the refused bench left its temp dir: %s" % list(root.iterdir())
    assert bench.entries() == []
    assert bench._HANDLES == {}


def test_unwritable_registry_cli_leaves_with_exit_2(env_state, tmp_path):
    """The same policy through the CLI face (the shape a scenario sees)."""
    binary, _log = _fake_temporal(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    registry = env_state["registry"]
    _lock(env_state, registry)

    out = _cli(["up", "--bin", binary, "--root", str(root)],
               {"SANDBAR_BENCH_REGISTRY": str(registry)})

    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr[-400:])
    assert "Traceback" not in out.stderr, out.stderr[-600:]
    receipt = _last_json(out.stdout)
    assert receipt["ok"] is False, receipt
    assert str(registry) in receipt["reason"], receipt["reason"]
    assert "unregistered" in receipt["reason"], receipt["reason"]
    assert list(root.iterdir()) == [], \
        "the refused CLI left a bench temp dir: %s" % list(root.iterdir())


def test_a_writable_registry_is_still_written_atomically(env_state, tmp_path):
    """Control for face B: the refusal above is about the registry refusing the
    write, not about the write being optional. On a writable registry the entry
    lands, and its shape is today's."""
    binary, _log = _fake_temporal(tmp_path)
    root = tmp_path / "root"
    root.mkdir()

    res = bench.start(bin_path=binary, root=str(root), boot_s=5.0)
    assert res["ok"] is True, res
    env_state["pids"].append(res["pid"])
    try:
        entry = json.loads(bench._entry_path(res["pid"]).read_text(encoding="utf-8"))
        assert set(entry) == {"pid", "pgid", "port", "db_dir", "started_at",
                              "owner_pid", "detached"}, entry
        assert entry["detached"] is False, entry
        assert entry["port"] == res["port"], entry
    finally:
        bench.stop(res["port"], res["pid"], db=res["db"])


# ---------------------------------------------------------------- face C ----
def test_happy_path_receipt_and_files_are_unchanged(env_state, tmp_path):
    """The writable-root path is byte-for-byte today's contract: one receipt
    {ok, port, pid, start_s, db}, one temp dir under the root, one registry
    entry; then one down reaps all three."""
    binary, log = _fake_temporal(tmp_path)
    root = tmp_path / "root"

    res = bench.start(bin_path=binary, root=str(root), boot_s=10.0)
    assert res["ok"] is True, res
    env_state["pids"].append(res["pid"])
    assert set(res) == {"ok", "port", "pid", "start_s", "db"}, \
        "the up receipt is a contract: %s" % sorted(res)
    db_file = Path(res["db"])
    assert db_file.name == "temporal.db", res
    assert db_file.parent.parent == root.resolve(), \
        "the bench temp dir must live under --root: %s (root %s)" % (
            db_file.parent, root)
    assert db_file.parent.name.startswith(bench.TEMP_PREFIX), db_file.parent
    assert bench.port_refuses(res["port"]) is False, "the bench is not serving"

    entry_path = bench._entry_path(res["pid"])
    assert entry_path.exists(), \
        "a started bench must be registered (invisible = unsweepable)"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    assert set(entry) == {"pid", "pgid", "port", "db_dir", "started_at",
                          "owner_pid", "detached"}, entry
    assert (entry["pid"], entry["pgid"], entry["port"], entry["detached"]) == (
        res["pid"], res["pid"], res["port"], False), entry
    assert Path(entry["db_dir"]) == db_file.parent.resolve(), entry
    assert entry["owner_pid"] == os.getpid(), entry
    assert log.exists(), "the stub must have run (the case is not vacuous)"
    assert "server" in log.read_text(encoding="utf-8"), log.read_text(encoding="utf-8")

    block = bench.stop(res["port"], res["pid"], db=res["db"])
    env_state["pids"].remove(res["pid"])
    assert block["clean"] is True, block
    assert block["port_refuses"] is True and block["pid_alive"] is False, block
    assert block["db_removed"] is True, block
    assert not entry_path.exists(), "the down path must drop the registry entry"
    assert not db_file.parent.exists(), "the down path must reclaim the temp dir"
    assert bench.entries() == []
    # the root the caller handed over is kept; only the bench dir inside it goes
    assert root.is_dir() and list(root.iterdir()) == []
