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

Isolation this gives:
- one free host port picked by the kernel (127.0.0.1:<port>), so the bench
  never competes for 7233/8233 and never touches the production server;
- a private SQLite file under a temp directory this module creates (prefix
  sandbar-bench-), used as the child's cwd, removed on the down path;
- the engine's search-attribute set (ProjectKey, EpicCode, InspectionInstance,
  InspectionPeriod, InspectionFixture, InspectionSlotTakenAt, all Keyword), so
  engine queries and ticket-start SA writes resolve instead of failing with
  "no mapping defined for search attribute";
- reaping by process GROUP: the child is started with start_new_session=True,
  so its pgid equals its pid and killpg reaches anything it spawned.

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
- no lease bookkeeping: nothing hands the bench out, nothing sweeps it. The
  caller owns the handle; a caller that dies without down leaves the process
  running (in-process users get the atexit backstop below).
- reaping by process group only: a child that leaves its group survives, and a
  pid/pgid that has been reused by an unrelated process cannot be told apart
  from the bench (the down path trusts the ids it is handed).

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

TEMP_PREFIX = "sandbar-bench-"
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
POLL_S = 0.05

#: Popen handles of benches started BY THIS PROCESS, keyed by pid. A process
#: only reaps its own child, so the handle lives here: without it the stopped
#: child stays a zombie and the residue assertion would read "still alive"
#: forever. A bench started by another process (the `up` CLI) is not in here.
_HANDLES = {}


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
    parent = pathlib.Path(str(db)).expanduser().resolve().parent
    if not parent.name.startswith(TEMP_PREFIX):
        return False
    shutil.rmtree(str(parent), ignore_errors=True)
    return not parent.exists()


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


def start(bin_path=None, boot_s=None, root=None, port=None):
    """Start one bench; return the contract dict {ok, port, pid, start_s, db}.

    A refusal returns {"ok": False, "reason": <named>} and leaves NOTHING
    behind: the binary is checked before any directory or process is created,
    and a boot that fails is stopped and its temp dir removed before returning.
    """
    bin_path = str(bin_path or default_bin())
    boot_s = BOOT_S if boot_s is None else float(boot_s)

    # Fail-closed floor FIRST: a bad binary must cost nothing and start nothing.
    if not os.path.exists(bin_path):
        return {"ok": False, "reason": "temporal binary not found: %s" % bin_path}
    if os.path.isdir(bin_path):
        return {"ok": False, "reason": "temporal binary path is a directory: %s"
                % bin_path}
    if not os.access(bin_path, os.X_OK):
        return {"ok": False, "reason": "temporal binary not executable: %s"
                % bin_path}

    mkdir_kw = {"prefix": TEMP_PREFIX}
    if root is not None:
        pathlib.Path(str(root)).mkdir(parents=True, exist_ok=True)
        mkdir_kw["dir"] = str(root)
    db_dir = pathlib.Path(tempfile.mkdtemp(**mkdir_kw))
    db_file = db_dir / "temporal.db"
    log_path = db_dir / "server.log"

    if port is None:
        port = free_port()
    else:
        port = int(port)
        if not port_refuses(port):
            return {"ok": False, "reason": "requested port %d is already in use" % port}
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
    log_fh = open(str(log_path), "wb")
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                stdout=log_fh, stderr=log_fh,
                                cwd=str(db_dir), start_new_session=True)
    except OSError as exc:
        log_fh.close()
        shutil.rmtree(str(db_dir), ignore_errors=True)
        return {"ok": False, "reason": "temporal bench spawn failed (%s): %s"
                % (type(exc).__name__, exc)}
    finally:
        if not log_fh.closed:
            log_fh.close()

    ok, detail = wait_ready(bin_path, port, boot_s, proc=proc,
                            log_path=log_path)
    if not ok:
        _HANDLES[proc.pid] = {"proc": proc, "port": port, "db": str(db_file)}
        stop(port, proc.pid, db=str(db_file))
        return {"ok": False, "reason": detail}

    _HANDLES[proc.pid] = {"proc": proc, "port": port, "db": str(db_file)}
    return {"ok": True, "port": port, "pid": proc.pid,
            "start_s": round(time.time() - t0, 2), "db": str(db_file)}


def stop(port, pid, pgid=None, term_s=None, kill_s=None, db=None):
    """Stop the bench and judge the residue.

    Order: SIGTERM the process group, wait up to term_s, then SIGKILL and wait
    up to kill_s, reap our own child, remove the private temp dir, and probe
    the port and the children from OUTSIDE (kernel and sockets, never the
    stopped process's own word). Returns the residue block plus stopped_s and
    escalated (escalated=True is the proof that a TERM-ignoring child was
    killed, not asked).
    """
    term_s = TERM_S if term_s is None else float(term_s)
    kill_s = KILL_S if kill_s is None else float(kill_s)
    pgid = int(pid) if pgid is None else int(pgid)
    t0 = time.time()
    _signal_group(pgid, signal.SIGTERM)
    escalated = False
    if not _await_gone(pid, pgid, term_s):
        escalated = True
        _signal_group(pgid, signal.SIGKILL)
        _await_gone(pid, pgid, kill_s)
    _reap_own_child(pid, kill_s)
    block = residue(port, pid, pgid)
    block["stopped_s"] = round(time.time() - t0, 2)
    block["escalated"] = escalated
    block["db_removed"] = reclaim_db(db)
    block["clean"] = residue_clean(block)
    return block


def detach(pid):
    """Hand a bench over to another process (the `up` CLI path).

    Drops this process's Popen handle so the atexit backstop does not kill a
    bench that is meant to outlive the process which started it. The caller
    then owns the handle and must run `down`.
    """
    return _HANDLES.pop(int(pid), None) is not None


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
    print("ENV_FAIL: unknown command %r (use up | down | status)" % cmd,
          file=sys.stderr, flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
