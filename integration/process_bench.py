#!/usr/bin/env python3
"""Docker-free process bench: one Temporal dev server held as a plain process.

Why this exists (host order 261022): the integration suite's expensive case
classes need a real Temporal server, and today every one of them buys it by
booting a docker stage (integration/stage_docker.py). A dev server started as a
plain process with its own SQLite file and a free port is up in about 0.1 s,
serves the same gRPC front end, and is reaped by a process-group signal. This
module is that bench as a reusable asset: the runner-up/tear-down code, an
injectable endpoint, and residue assertions a scenario can judge.

Usage (cwd = repo root):
  python3 integration/process_bench.py up
      prints ONE JSON line {ok, port, pid, start_s, db} (db = the private
      SQLite file path); exit 0. A refusal prints the named reason on stderr
      and exits 2, having created nothing.
  python3 integration/process_bench.py down --port P --pid N [--db <file>]
      SIGTERMs the process group, escalates to SIGKILL after a bounded wait,
      prints {stopped_s, escalated, port_refuses, pid_alive, group_alive,
      survivors, db_removed, clean} and exits 0 only when clean is true
      (residue = exit 3, a named red).
  python3 integration/process_bench.py status --port P --pid N
      prints the same residue block without stopping anything (read-only).
  python3 integration/process_bench.py sweep [--include-detached]
      sweeps the registry now and prints one JSON line {swept, left}. A bench
      whose owner is gone, or whose pid is gone, is killed and its temp dir
      removed; a handed-over (manual `up`) bench is reported and left alone
      unless --include-detached says otherwise. Exit 0 always: this is a
      report, not a verdict.

Isolation this gives:
- one free host port picked by the kernel (127.0.0.1:<port>), so the bench
  never competes for 7233/8233 and never touches the production server;
- a private SQLite file under a temp directory this module creates (prefix
  sandbar-bench-), used as the child's cwd, removed on the down path;
- the engine's search-attribute set (ProjectKey, EpicCode, InspectionInstance,
  InspectionPeriod, InspectionFixture, InspectionSlotTakenAt, all Keyword), so
  engine queries and ticket-start SA writes resolve instead of failing with
  "no mapping defined for search attribute";
- reaping by process GROUP: the bench group leader is the deadman shim, so
  its pgid equals its pid and killpg reaches anything the bench spawned;
- the bench DIES WITH ITS OWNER (ticket t261022-15). The owner holds one end of
  a pipe and the deadman shim (integration/bench_deadman.py) holds the other,
  so the kernel closes the pipe when the owner dies, however it dies. The shim
  then kills the bench group, removes the temp dir and the registry entry. A
  supervisor cannot do this job: a supervisor keeps a child alive on purpose,
  and none of supervisord/s6/runit gives "die with the owner";
- a REGISTRY of started benches (JSON per bench under the registry dir) and a
  sweep: every start and every down first sweeps entries whose bench is gone or
  whose owner is gone, kills a surviving group, reclaims the temp dir and says
  what it removed (never silent).

Reaping boundary: which kill reaps the bench, and which does not.
- the owner exits, returns or raises        -> atexit -> full teardown;
- SIGTERM or SIGHUP to the owner only       -> handler -> the same teardown
  (atexit cannot see them, and this is the path an ordinary `kill` takes);
- SIGKILL to the owner, or a budget kill of the owner's whole process group
  -> the deadman: the shim is in its own session, so a group kill misses it,
  and it sees EOF within ~0.1 s and reaps the bench;
- SIGKILL to the shim itself, or the shim dying with the host -> the bench
  survives, and the next start or down sweeps the registry entry and kills the
  group. This is a backstop, so it needs a later bench activity on that host;
- a bench started by `up` and then handed over (detach) is NOT swept on
  purpose: it must outlive its starter, and its owner runs `down`. The sweep
  reports such an entry and leaves it standing; `sweep --include-detached` is
  the operator hatch for a manual bench nobody wants any more.

Isolation this does NOT give:
- no filesystem isolation beyond the temp db dir: the server process sees the
  whole host filesystem (the repo, $HOME, /tmp). This is not a container and it
  is not a sandbox.
- no network isolation: the server listens on the host's network namespace at
  127.0.0.1:<port>; any local process can connect, and nothing is namespaced.
- no namespace isolation per scenario: the bench serves the dev server's own
  namespaces (default only). Two benches on one host are isolated by port and
  db file only.
- no resource caps: cpu, memory and disk are whatever the host has.
- no lease bookkeeping: nothing hands the bench out. The registry below records
  which benches exist and which process owns each one, and the sweep reclaims
  the ones whose owner died; the caller still owns the handle and must run
  `down` when it finishes normally.
- reaping by process group only: a child that leaves its group survives, and a
  pid/pgid that has been reused by an unrelated process cannot be told apart
  from the bench. The down path and the sweep trust the ids they are handed, so
  a reused pid in a registry entry could make a sweep kill a stranger's group.

Case classes that CANNOT move onto this bench (docker-only, stay on
integration/stage_docker.py):
- stage lease / sweep: the stage hands out a leased identity per project and
  the sweep reclaims stale stages from that lease; a bare process has no lease,
  no project identity and nothing for the sweep to reclaim.
- agent-runtime container mode (SANDBAR_AGENT_RUNTIME=docker): each ticket's
  agent runs inside the built sandbar-agent image with the container mount
  layout and sandbox; a host process cannot provide the image, the mounts or
  the filesystem isolation that mode asserts.
"""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SHIM = HERE / "bench_deadman.py"

TEMP_PREFIX = "sandbar-bench-"
#: Where each started bench records itself, so a later start or down can find a
#: bench whose owner died. Injectable: a test points it at its own temp dir.
REGISTRY_ENV = "SANDBAR_BENCH_REGISTRY"
NAMESPACE = "default"
SEARCH_ATTRIBUTE_TYPE = "Keyword"
#: The engine's search attributes (single source copied from
#: integration/t260905-03/lib_inspection.py's registration list, all Keyword).
#: A bench missing any of them makes engine SA queries and ticket-start writes
#: fail by name, so the flag list is part of the bench contract, not a detail.
SEARCH_ATTRIBUTES = (
    "ProjectKey",
    "EpicCode",
    "InspectionInstance",
    "InspectionPeriod",
    "InspectionFixture",
    "InspectionSlotTakenAt",
)

#: Bounds are injectable: a test or a scenario buys its evidence with a small
#: bound, never by sleeping a production value (the L25 wait-bound discipline).
BOOT_S = float(os.environ.get("SANDBAR_BENCH_BOOT_S") or 20.0)
TERM_S = float(os.environ.get("SANDBAR_BENCH_TERM_S") or 8.0)
KILL_S = float(os.environ.get("SANDBAR_BENCH_KILL_S") or 5.0)
PROBE_S = float(os.environ.get("SANDBAR_BENCH_PROBE_S") or 0.25)
#: The sweep is a backstop, not a stage: a stale bench gets a short TERM first.
SWEEP_TERM_S = float(os.environ.get("SANDBAR_BENCH_SWEEP_TERM_S") or 1.0)
SWEEP_KILL_S = float(os.environ.get("SANDBAR_BENCH_SWEEP_KILL_S") or 2.0)
POLL_S = 0.05

#: Popen handles of benches started BY THIS PROCESS, keyed by pid. A process
#: only reaps its own child, so the handle lives here: without it the stopped
#: child stays a zombie and the residue assertion would read "still alive"
#: forever. A bench started by another process (the `up` CLI) is not in here.
_HANDLES = {}

#: Previous SIGTERM/SIGHUP handlers, so the module can put them back. The
#: handlers are installed on the first start, never on import.
_PREV_HANDLERS = {}
_HANDLERS_ON = False
_IN_TEARDOWN = False


def registry_dir():
    """The bench registry directory: $SANDBAR_BENCH_REGISTRY, else the temp dir."""
    raw = os.environ.get(REGISTRY_ENV)
    if raw:
        return pathlib.Path(raw).expanduser()
    return pathlib.Path(tempfile.gettempdir()) / "sandbar-bench-registry"


def _entry_path(pid):
    return registry_dir() / ("%d.json" % int(pid))


def _write_entry(entry):
    """Write one registry entry atomically (a reader never sees half a file)."""
    directory = registry_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _entry_path(entry["pid"])
    tmp = path.with_name("%s.tmp%d" % (path.name, os.getpid()))
    try:
        tmp.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return None
    return path


def entries():
    """Every registry entry, oldest file name first; a corrupt file is kept as a
    record so the sweep can name it and drop it."""
    directory = registry_dir()
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entry = {"pid": 0, "corrupt": True}
        if not isinstance(entry, dict):
            entry = {"pid": 0, "corrupt": True}
        entry["_path"] = str(path)
        out.append(entry)
    return out


def register(pid, pgid, port, db):
    """Record a started bench so a later start or down can find it again."""
    db_dir = pathlib.Path(str(db)).expanduser().resolve().parent
    return _write_entry({"pid": int(pid), "pgid": int(pgid), "port": int(port),
                         "db_dir": str(db_dir),
                         "started_at": round(time.time(), 3),
                         "owner_pid": os.getpid(), "detached": False})


def unregister(pid):
    """Drop the entry of a bench this process stopped."""
    try:
        _entry_path(pid).unlink()
    except OSError:
        return False
    return True


def _mark_detached(pid):
    path = _entry_path(pid)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(entry, dict):
        return False
    entry["detached"] = True
    entry["detached_at"] = round(time.time(), 3)
    entry["owner_pid"] = 0
    return _write_entry(entry) is not None


def reclaim_dir(dir_path):
    """Remove a bench temp dir, and ONLY one this module created.

    A dir that is already gone counts as reclaimed (the deadman shim removes it
    when the owner dies, so the sweep often finds the clean-up already done).
    """
    if not dir_path:
        return False
    path = pathlib.Path(str(dir_path)).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return False
    if not path.name.startswith(TEMP_PREFIX):
        return False
    if not path.exists():
        return True
    shutil.rmtree(str(path), ignore_errors=True)
    return not path.exists()


def _sweep_one(entry, term_s, kill_s, include_detached=False):
    """Judge one registry entry and clean it up when it is stale.

    Returns a record {pid, pgid, port, owner_pid, reason, killed, db_removed}
    for every entry this call handled, or None for an entry that is still in
    use (a live bench with a live owner, or a handed-over manual bench).
    """
    path = entry.get("_path")
    if entry.get("corrupt"):
        try:
            os.unlink(str(path))
        except (OSError, TypeError):
            pass
        return {"pid": 0, "pgid": 0, "port": 0, "owner_pid": 0,
                "reason": "unreadable registry entry", "killed": False,
                "db_removed": False}
    pid = int(entry.get("pid") or 0)
    pgid = int(entry.get("pgid") or pid or 0)
    owner = int(entry.get("owner_pid") or 0)
    detached = bool(entry.get("detached"))
    alive = bool(pid) and pid_alive(pid)
    group = bool(pgid) and group_alive(pgid)
    if alive and detached and not include_detached:
        return None                     # a manual bench must outlive `up`
    if alive and owner and pid_alive(owner):
        return None                     # the owner is alive: still in use
    killed = False
    if alive and not group:
        # The leader lives but the group probe says nothing: kill the leader on
        # its own, otherwise a stale single process would stay forever.
        reason = ("orphan: owner %s is gone, pid %d is alive"
                  % (owner or "unknown", pid))
        _signal_group(pid, signal.SIGTERM)
        _await_gone(pid, pid, term_s)
        if _still_standing(pid, pid):
            _signal_group(pid, signal.SIGKILL)
            _await_gone(pid, pid, kill_s)
        killed = True
    elif alive and group:
        reason = "orphan: owner %s is gone, group %d is alive" % (
            owner or "unknown", pgid)
        _signal_group(pgid, signal.SIGTERM)
        _await_gone(pid, pgid, term_s)
        if _still_standing(pid, pgid):
            _signal_group(pgid, signal.SIGKILL)
            _await_gone(pid, pgid, kill_s)
        killed = True
    elif group:
        reason = "stale: pid %d is gone, group %d survives" % (pid, pgid)
        _signal_group(pgid, signal.SIGTERM)
        _await_gone(pid, pgid, term_s)
        if _still_standing(pid, pgid):
            _signal_group(pgid, signal.SIGKILL)
            _await_gone(pid, pgid, kill_s)
        killed = True
    else:
        reason = "stale: pid %d and group %d are gone" % (pid, pgid)
    db_removed = reclaim_dir(entry.get("db_dir"))
    try:
        os.unlink(str(path))
    except (OSError, TypeError):
        pass
    return {"pid": pid, "pgid": pgid, "port": int(entry.get("port") or 0),
            "owner_pid": owner, "reason": reason, "killed": killed,
            "db_removed": db_removed, "detached": detached}


def sweep(include_detached=False, term_s=None, kill_s=None, skip_pid=None):
    """Sweep the registry; return one record per entry handled (never silent).

    Called by every start and every down, so a bench whose owner died without
    the deadman (a shim killed by SIGKILL, or a bench from before this ticket)
    is reaped by the next bench activity on the host. The record names the pid,
    the reason and whether the temp dir went, and the same lines go to stderr.
    A down passes skip_pid: the bench it is about to stop is not a stale entry.
    """
    term_s = SWEEP_TERM_S if term_s is None else float(term_s)
    kill_s = SWEEP_KILL_S if kill_s is None else float(kill_s)
    swept = []
    for entry in entries():
        if skip_pid is not None and int(entry.get("pid") or 0) == int(skip_pid):
            continue
        try:
            record = _sweep_one(entry, term_s, kill_s,
                                include_detached=include_detached)
        except Exception as exc:                         # noqa: BLE001
            record = {"pid": int(entry.get("pid") or 0), "pgid": 0,
                      "port": int(entry.get("port") or 0), "owner_pid": 0,
                      "reason": "sweep failed: %s: %s"
                                % (type(exc).__name__, exc),
                      "killed": False, "db_removed": False}
        if record is None:
            continue
        swept.append(record)
    for record in swept:
        print("WARN: bench sweep handled pid=%s port=%s killed=%s "
              "db_removed=%s reason=%s"
              % (record["pid"], record["port"], record["killed"],
                 record["db_removed"], record["reason"]),
              file=sys.stderr, flush=True)
    return swept


def default_bin():
    """The temporal CLI: $SANDBAR_TEMPORAL_BIN, else the repo's own copy."""
    return (os.environ.get("SANDBAR_TEMPORAL_BIN")
            or str(REPO / "server" / "engine" / "bin" / "temporal"))


def endpoint(port):
    """The gRPC address the bench serves on (what SANDBAR_TARGET_HOST wants)."""
    return "127.0.0.1:%d" % int(port)


def free_port():
    """Pick a port the kernel says is free right now.

    The socket is closed before returning, so the port is NOT reserved: a small
    race window remains between the pick and the child's bind (documented, not
    papered over). Two calls in a row may return the same port.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def consumer_env(port, base=None, namespace=NAMESPACE):
    """The environment a consumer needs to talk to this bench.

    Returns a NEW dict: the base (default = os.environ) is copied, never
    mutated, and SANDBAR_TARGET_HOST/SANDBAR_NAMESPACE are overwritten with the
    bench endpoint. This is the endpoint hand-off: one function, so a scenario
    cannot pin half the address.
    """
    env = dict(os.environ if base is None else base)
    env["SANDBAR_TARGET_HOST"] = endpoint(port)
    env["SANDBAR_NAMESPACE"] = namespace
    return env


def port_refuses(port, probe_s=None):
    """True when nothing accepts a TCP connection on 127.0.0.1:<port>."""
    probe_s = PROBE_S if probe_s is None else float(probe_s)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(probe_s)
    try:
        sock.connect(("127.0.0.1", int(port)))
    except OSError:
        return True
    finally:
        sock.close()
    return False


def pid_alive(pid):
    """True when the pid exists (a zombie counts as existing — the parent has
    not reaped it yet, which is exactly what the residue check must see)."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def group_alive(pgid):
    """True when any process remains in the process group."""
    try:
        os.killpg(int(pgid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def survivors(pgid):
    """Best-effort list of the pids still in the group (empty when the group is
    gone or when `ps` cannot enumerate). Naming only: the verdict comes from
    group_alive, so a host without ps still gets a real assertion."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,pgid="],
                             capture_output=True, text=True,
                             timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    pids = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            if int(parts[1]) == int(pgid):
                pids.append(int(parts[0]))
    return pids


def _reap_if_own_zombie(pid):
    """Reap pid when it is OUR dead-but-unreaped child (a zombie).

    A zombie is a reaping duty of the parent, not residue of the bench: without
    this the group probe reads "still alive" forever and a correct down would be
    judged dirty. waitpid returns (0, 0) for a live child and raises
    ChildProcessError for a process that is not ours, so this never touches
    anyone else's state.
    """
    try:
        got, _status = os.waitpid(int(pid), os.WNOHANG)
    except (ChildProcessError, OSError):
        return False
    return got == int(pid)


def residue(port, pid, pgid=None, probe_s=None):
    """The residue block: what is still standing after a down.

    Two independent probes, because each alone can lie:
    - the PORT probe connects to the endpoint; a live listener means the server
      (or something) still serves there;
    - the CHILD probe asks the kernel about the process group and the pid; a
      live group means the server or a descendant survived.
    clean = the port refuses AND the pid is gone AND the group is empty.
    """
    pgid = int(pid) if pgid is None else int(pgid)
    _reap_if_own_zombie(pid)
    alive = group_alive(pgid)
    return {
        "port_refuses": port_refuses(port, probe_s),
        "pid_alive": pid_alive(pid),
        "group_alive": alive,
        "survivors": survivors(pgid) if alive else [],
    }


def residue_clean(block):
    """True when the residue block shows nothing left standing."""
    return (bool(block.get("port_refuses"))
            and not block.get("pid_alive")
            and not block.get("group_alive"))


def _signal_group(pgid, sig):
    try:
        os.killpg(int(pgid), sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def _still_standing(pid, pgid):
    """True when the bench (or a descendant) is genuinely still running.

    A zombie is NOT standing: it is dead and only waits for its parent to reap
    it. Measured fault in the first cut of this module: an obedient child that
    died at once on SIGTERM stayed in the process group as a zombie, the group
    probe kept reading "alive", and the down path escalated to SIGKILL and
    waited out BOTH bounds (5.05 s where the true stop took 0.02 s). Reaping
    our own child first makes the escalation signal mean what it says.
    """
    if not group_alive(pgid):
        return False
    _reap_if_own_zombie(pid)
    if not group_alive(pgid):
        return False
    # A dead group member that is OUR child stays in the group as a zombie, so
    # the group probe would read "alive" forever and the sweep would escalate
    # against a corpse. Reap any member this process owns (a foreign pid returns
    # ChildProcessError and is left alone).
    for member in survivors(pgid):
        _reap_if_own_zombie(member)
    return group_alive(pgid)


def _await_gone(pid, pgid, bound_s):
    deadline = time.time() + float(bound_s)
    while time.time() < deadline:
        if not _still_standing(pid, pgid):
            return True
        time.sleep(POLL_S)
    return not _still_standing(pid, pgid)


def _reap_own_child(pid, bound_s):
    """Reap our own stopped child so residue is not a zombie artefact."""
    handle = _HANDLES.pop(int(pid), None)
    if not handle:
        return False
    try:
        handle["proc"].wait(timeout=float(bound_s))
    except subprocess.TimeoutExpired:
        return False
    return True


def reclaim_db(db):
    """Remove the bench's private temp dir, and ONLY that.

    The directory is removed when its name carries TEMP_PREFIX (the one this
    module created). Any other path is left untouched and reported as not
    removed: a down path that can rmtree an arbitrary caller-supplied path is a
    footgun, not a feature.
    """
    if not db:
        return False
    try:
        parent = pathlib.Path(str(db)).expanduser().resolve().parent
    except OSError:
        return False
    return reclaim_dir(parent)


def _log_tail(log_path, lines=6):
    try:
        text = pathlib.Path(log_path).read_text(encoding="utf-8",
                                                 errors="replace")
    except OSError:
        return "<no bench log>"
    rows = [ln for ln in text.splitlines() if ln.strip()]
    return " | ".join(rows[-lines:]) if rows else "<empty bench log>"


def _cli_probe(bin_path, port, timeout_s=2.0):
    """One real gRPC round trip through the temporal CLI against the bench."""
    try:
        out = subprocess.run(
            [bin_path, "operator", "namespace", "describe",
             "--namespace", NAMESPACE, "--address", endpoint(port)],
            capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    if out.returncode == 0:
        return True, "grpc handshake ok"
    tail = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()
    return False, "grpc not ready rc=%s %s" % (
        out.returncode, tail[-1] if tail else "")


def wait_ready(bin_path, port, boot_s=None, proc=None, log_path=None):
    """Wait until the bench serves gRPC, or name why it did not.

    A TCP accept alone is not readiness (the port binds before the namespace
    machinery answers), so each poll asks the server for a namespace describe:
    a real round trip through the same gRPC front end consumers use.
    """
    boot_s = BOOT_S if boot_s is None else float(boot_s)
    deadline = time.time() + boot_s
    last = "no probe ran"
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False, ("bench exited rc=%s during boot (%s)"
                           % (proc.returncode, _log_tail(log_path)))
        if port_refuses(port):          # nothing listening yet
            last = "port %d not accepting yet" % int(port)
        else:
            ok, detail = _cli_probe(bin_path, port)
            if ok:
                return True, detail
            last = detail
        time.sleep(POLL_S)
    return False, "bench not ready within %.1fs: %s" % (boot_s, last)


def _spawn(argv, db_dir, log_path):
    """Start argv in a NEW session under the deadman shim.

    The shim is the session leader of the bench group, so:
    - the module's group signals reach both the shim and the bench;
    - the shim holds the read end of the owner's deadman pipe, so the bench
      dies with the owner even when the owner is SIGKILLed.

    Returns {"proc", "pid", "pgid", "dead_w"}; dead_w is the owner end of the
    pipe and must be closed on a normal stop, or written to on a hand-over.
    """
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, False)
    shim = [sys.executable, "-B", str(SHIM), str(read_fd), str(db_dir),
            str(registry_dir())] + list(argv)
    log_fh = open(str(log_path), "ab")
    try:
        proc = subprocess.Popen(shim, stdin=subprocess.DEVNULL,
                                stdout=log_fh, stderr=log_fh,
                                cwd=str(db_dir), start_new_session=True,
                                pass_fds=(read_fd,))
    except OSError:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
        log_fh.close()
    return {"proc": proc, "pid": proc.pid, "pgid": proc.pid,
            "dead_w": write_fd}


def start(bin_path=None, boot_s=None, root=None, port=None):
    """Start one bench; return the contract dict {ok, port, pid, start_s, db}.

    A refusal returns {"ok": False, "reason": <named>} and leaves NOTHING
    behind: the binary is checked before any directory or process is created,
    and a boot that fails is stopped and its temp dir removed before returning.

    Every start first sweeps the registry (see sweep), so a bench whose owner
    died without the deadman is reaped by the next bench activity.
    """
    bin_path = str(bin_path or default_bin())
    boot_s = BOOT_S if boot_s is None else float(boot_s)
    try:
        sweep()
    except Exception:                                    # noqa: BLE001
        pass

    # Fail-closed floor FIRST: a bad binary must cost nothing and start nothing.
    if not os.path.exists(bin_path):
        return {"ok": False, "reason": "temporal binary not found: %s" % bin_path}
    if os.path.isdir(bin_path):
        return {"ok": False, "reason": "temporal binary path is a directory: %s"
                % bin_path}
    if not os.access(bin_path, os.X_OK):
        return {"ok": False, "reason": "temporal binary not executable: %s"
                % bin_path}

    # The port comes before ANY directory: a requested port that is taken must
    # cost nothing either (ticket t261022-10's "a refusal creates nothing").
    if port is None:
        port = free_port()
    else:
        port = int(port)
        if not port_refuses(port):
            return {"ok": False,
                    "reason": "requested port %d is already in use" % port}

    mkdir_kw = {"prefix": TEMP_PREFIX}
    if root is not None:
        pathlib.Path(str(root)).mkdir(parents=True, exist_ok=True)
        mkdir_kw["dir"] = str(root)
    db_dir = pathlib.Path(tempfile.mkdtemp(**mkdir_kw))
    db_file = db_dir / "temporal.db"
    log_path = db_dir / "server.log"
    ui_port = free_port()
    argv = [bin_path, "server", "start-dev",
            "--ip", "127.0.0.1",
            "--port", str(port),
            "--ui-port", str(ui_port),
            "--namespace", NAMESPACE,
            "--db-filename", str(db_file),
            "--log-level", "error"]
    for name in SEARCH_ATTRIBUTES:
        argv += ["--search-attribute", "%s=%s" % (name, SEARCH_ATTRIBUTE_TYPE)]

    t0 = time.time()
    try:
        handle = _spawn(argv, db_dir, log_path)
    except OSError as exc:
        shutil.rmtree(str(db_dir), ignore_errors=True)
        return {"ok": False, "reason": "temporal bench spawn failed (%s): %s"
                % (type(exc).__name__, exc)}
    _install_signal_handlers()
    register(handle["pid"], handle["pgid"], port, db_file)
    _HANDLES[handle["pid"]] = {"proc": handle["proc"], "port": port,
                               "db": str(db_file), "pgid": handle["pgid"],
                               "dead_w": handle["dead_w"]}

    ok, detail = wait_ready(bin_path, port, boot_s, proc=handle["proc"],
                            log_path=log_path)
    if not ok:
        stop(port, handle["pid"], pgid=handle["pgid"], db=str(db_file))
        return {"ok": False, "reason": detail}

    return {"ok": True, "port": port, "pid": handle["pid"],
            "start_s": round(time.time() - t0, 2), "db": str(db_file)}


def stop(port, pid, pgid=None, term_s=None, kill_s=None, db=None):
    """Stop the bench and judge the residue.

    Order: sweep stale registry entries, SIGTERM the process group, wait up to
    term_s, then SIGKILL and wait up to kill_s, reap our own child, close the
    deadman pipe, drop the registry entry, remove the private temp dir, and
    probe the port and the children from OUTSIDE (kernel and sockets, never the
    stopped process's own word). Returns the residue block plus stopped_s and
    escalated (escalated=True is the proof that a TERM-ignoring child was
    killed, not asked).
    """
    term_s = TERM_S if term_s is None else float(term_s)
    kill_s = KILL_S if kill_s is None else float(kill_s)
    pgid = int(pid) if pgid is None else int(pgid)
    handle = _HANDLES.get(int(pid))
    if handle and handle.get("pgid"):
        pgid = int(handle["pgid"])
    try:
        sweep(skip_pid=int(pid))     # this bench is being stopped, not swept
    except Exception:                                    # noqa: BLE001
        pass
    t0 = time.time()
    _signal_group(pgid, signal.SIGTERM)
    escalated = False
    if not _await_gone(pid, pgid, term_s):
        escalated = True
        _signal_group(pgid, signal.SIGKILL)
        _await_gone(pid, pgid, kill_s)
    _close_deadman(pid)
    _reap_own_child(pid, kill_s)
    unregister(pid)
    block = residue(port, pid, pgid)
    block["stopped_s"] = round(time.time() - t0, 2)
    block["escalated"] = escalated
    block["db_removed"] = reclaim_db(db)
    block["clean"] = residue_clean(block)
    return block


def _close_deadman(pid):
    """Close the owner end of the deadman pipe (the shim then reads EOF)."""
    handle = _HANDLES.get(int(pid))
    fd = handle.get("dead_w") if handle else None
    if fd is None:
        return False
    handle["dead_w"] = None
    try:
        os.close(int(fd))
    except OSError:
        return False
    return True


def detach(pid):
    """Hand a bench over to another process (the `up` CLI path).

    Drops this process's Popen handle so the atexit backstop does not kill a
    bench that is meant to outlive the process which started it, writes ONE
    byte on the deadman pipe (the shim then stops watching the owner), and
    marks the registry entry detached so the sweep leaves the bench alone. The
    caller then owns the handle and must run `down`.
    """
    handle = _HANDLES.pop(int(pid), None)
    if not handle:
        return False
    fd = handle.get("dead_w")
    if fd is not None:
        try:
            os.write(int(fd), b"D")
        except OSError:
            pass
        try:
            os.close(int(fd))
        except OSError:
            pass
    _mark_detached(pid)
    return True


def _reap_all():
    """atexit backstop: a caller that dies mid-scenario leaks no bench."""
    for pid in list(_HANDLES):
        handle = _HANDLES.get(pid)
        if not handle:
            continue
        try:
            stop(handle["port"], pid, db=handle["db"])
        except Exception:                                  # noqa: BLE001
            pass


def _on_kill_signal(signum, frame):
    """SIGTERM/SIGHUP: the same teardown as atexit, then die as asked.

    atexit cannot run on SIGKILL, and that is the deadman's job. This handler
    covers the ordinary kill, which must not leak a bench either.
    """
    global _IN_TEARDOWN
    if not _IN_TEARDOWN:
        _IN_TEARDOWN = True
        try:
            _reap_all()
        except Exception:                                # noqa: BLE001
            pass
    prev = _PREV_HANDLERS.get(signum)
    if callable(prev):
        prev(signum, frame)
        return
    if prev == signal.SIG_IGN:
        return                        # the owner ignores this signal on purpose
    try:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    except (OSError, ValueError):
        pass


def _install_signal_handlers():
    """Install the kill handlers on the first start (never on import)."""
    global _HANDLERS_ON
    if _HANDLERS_ON:
        return False
    installed = False
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            _PREV_HANDLERS[sig] = signal.getsignal(sig)
            signal.signal(sig, _on_kill_signal)
            installed = True
        except (ValueError, OSError):    # not the main thread, or unsupported
            _PREV_HANDLERS.pop(sig, None)
    _HANDLERS_ON = installed
    return installed


atexit.register(_reap_all)


def _opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
        return None
    return default


def main(argv):
    cmd = argv[0] if argv else "up"
    if cmd in ("up", "start"):
        boot_raw = _opt(argv, "--boot-s")
        port_raw = _opt(argv, "--port")
        res = start(bin_path=_opt(argv, "--bin"),
                    boot_s=float(boot_raw) if boot_raw else None,
                    root=_opt(argv, "--root"),
                    port=int(port_raw) if port_raw else None)
        print(json.dumps(res), flush=True)
        if not res.get("ok"):
            print("ENV_FAIL: %s" % res.get("reason"), file=sys.stderr,
                  flush=True)
            return 2
        # The bench outlives this process by design: the caller runs `down`.
        detach(res["pid"])
        return 0
    if cmd in ("down", "stop"):
        port, pid = _opt(argv, "--port"), _opt(argv, "--pid")
        if not port or not pid:
            print("ENV_FAIL: down needs --port <port> and --pid <pid> "
                  "(both come from the up output)", file=sys.stderr, flush=True)
            return 2
        term_raw, kill_raw = _opt(argv, "--term-s"), _opt(argv, "--kill-s")
        db_arg = _opt(argv, "--db")
        block = stop(int(port), int(pid),
                     term_s=float(term_raw) if term_raw else None,
                     kill_s=float(kill_raw) if kill_raw else None,
                     db=db_arg)
        print(json.dumps(block), flush=True)
        if db_arg and not block["db_removed"]:
            # Never silent: the port/pid/group face is clean but the temp dir is
            # still there. A foreign path is left alone on purpose (see
            # reclaim_db), so this is a warning, not a refusal.
            print("WARN: the temp dir was not reclaimed (%s) — its name is not a "
                  "bench temp dir this module created; nothing was deleted"
                  % db_arg, file=sys.stderr, flush=True)
        if not block["clean"]:
            print("FAIL: bench residue after down — port_refuses=%s pid_alive=%s "
                  "group_alive=%s survivors=%s"
                  % (block["port_refuses"], block["pid_alive"],
                     block["group_alive"], block["survivors"]),
                  file=sys.stderr, flush=True)
            return 3
        return 0
    if cmd in ("status", "residue"):
        port, pid = _opt(argv, "--port"), _opt(argv, "--pid")
        if not port or not pid:
            print("ENV_FAIL: status needs --port <port> and --pid <pid>",
                  file=sys.stderr, flush=True)
            return 2
        block = residue(int(port), int(pid))
        block["clean"] = residue_clean(block)
        print(json.dumps(block), flush=True)
        return 0 if block["clean"] else 3
    if cmd in ("sweep", "reap"):
        swept = sweep(include_detached="--include-detached" in argv)
        left = [{"pid": entry.get("pid"), "port": entry.get("port"),
                 "detached": bool(entry.get("detached"))}
                for entry in entries()]
        print(json.dumps({"swept": swept, "left": left}), flush=True)
        return 0
    print("ENV_FAIL: unknown command %r (use up | down | status | sweep)" % cmd,
          file=sys.stderr, flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
