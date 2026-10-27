#!/usr/bin/env python3
"""Docker-free process bench, end to end (ticket t261022-10).

The scenario that proves integration/process_bench.py as a whole: a Temporal dev
server comes up as a plain process on a free port with the engine's search
attributes and a private SQLite file, an EXISTING read-only scenario runs green
against the injected endpoint, the bench goes down by process-group signal, and
the residue is judged from the outside (port + children), not from the stopped
process's own word.

Legs:
  L0  the bench comes up         - the up contract {ok, port, pid, start_s, db},
                                   a host-free port, and a fast start (a docker
                                   stage takes minutes; this must not);
  L1  the db is private          - inside a sandbar-bench-* temp dir, outside the
                                   repo (the isolation the module claims);
  L2  the endpoint serves        - a real gRPC round trip answers, and the bench
                                   carries the engine's whole search-attribute
                                   set (the flag list is a contract, not detail);
  L3  the endpoint hand-off      - the ENGINE's own resolution
                                   (shared.TARGET_HOST) reads the bench address,
                                   never the production default, and the child
                                   scenario is given the same environment;
  L4  an existing scenario green - t260907-04-dispatcher-lock-fallback runs as a
                                   subprocess on that environment and exits 0
                                   with its own SUMMARY green;
  L5  down leaves no residue     - group SIGTERM, port refuses, no survivor, db
                                   reclaimed, the obedient stop never escalates
                                   to SIGKILL and lands inside its declared
                                   window, and a FRESH process re-probes the
                                   same verdict (reader side, not the writer's);
  L6  the escalation exists      - a child that ignores SIGTERM is SIGKILLed, so
                                   L5's green is not "TERM and hope";
  L7  a bad binary costs nothing - a refused start names the path and starts
                                   nothing.

Honest scope of L4: the measured scenario is hermetic and does NOT open a
Temporal connection by itself. L4 therefore proves the runtime accepts the
injected endpoint environment and keeps its own contract green; the live
connection proofs are L2 (a real gRPC round trip) and L3 (the engine's own
address resolution). This scenario does not claim more than that.

Offline, seconds, no docker, no browser, never touches the console port (3099)
nor the production Temporal ports (7233/8233): the bench binds a kernel-picked
free port only.

Three states: all legs green = PASS exit 0; a broken leg = FAIL exit 1; the
temporal binary missing = ENV_FAIL exit 2 (named, never silently green).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEG = HERE.parent
ROOT = INTEG.parent
sys.path.insert(0, str(INTEG))

import lib_env               # noqa: E402
import process_bench as bench  # noqa: E402

MODULE = str(INTEG / "process_bench.py")
EXISTING = str(INTEG / "t260907-04" / "sc_dispatcher_lock_fallback.py")
PRODUCTION_ADDRESSES = ("127.0.0.1:7233", "127.0.0.1:8233", "127.0.0.1:3099")
#: A child's own process ceiling (injectable): the bench is the point, not
#: patience with a hung child.
CHILD_TIMEOUT_S = float(os.environ.get("SANDBAR_BENCH_CHILD_TIMEOUT_S") or 240)

#: L5's bounded allowance for an OBEDIENT stop's wall time (ticket t261027-18).
#: stopped_s measures two different facts at once: the TERM wait on the child,
#: and the post-TERM bookkeeping after it (deadman close, child reap, the port
#: probe, the temp-dir reclaim). Only the first is bounded by the module's own
#: escalation bound (process_bench.TERM_S, 8.0 s by default), so a stop under
#: round load legitimately runs past it with escalated still false: the same
#: tree measured stopped_s=1.10 s standalone (this case, one host) and 16.1 s
#: inside a full round (the red this ticket fixes), the down receipt clean in
#: both runs. A second measurement under load can be worse than the first, so
#: the window is the round-load figure times a declared factor of 2 (32.2 s),
#: with 2 x TERM_S (16.0 s) as the floor so the module's own escalation bound
#: always sits inside the window. This is a load ceiling, not a performance
#: contract: the no-SIGKILL assertion carries the correctness, and a stop that
#: truly hangs runs past the escalation bound and reds THAT one.
STOP_STANDALONE_S = 1.1     # measured: obedient stop alone on this host
STOP_ROUND_LOAD_S = 16.1    # measured: the same stop inside a full round
STOP_LOAD_FACTOR = 2.0
STOP_WINDOW_S = max(bench.TERM_S * 2, STOP_ROUND_LOAD_S * STOP_LOAD_FACTOR)

_SA_TYPES = ("Keyword", "KeywordList", "Text", "Int", "Double", "Bool",
             "Datetime")

#: A stub child that IGNORES SIGTERM: only SIGKILL ends it. This is the
#: escalation evidence for L6 (no docker, no sleep literal).
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


class Rec(object):
    """Leg counters and the three-state exit (lib_env is the single vocabulary)."""

    def __init__(self):
        self.passed = self.failed = self.env_failed = 0

    def check(self, cond, label):
        if cond:
            self.passed += 1
            print("  ok %s" % label, flush=True)
        else:
            self.failed += 1
            print("  FAIL %s" % label, flush=True)
        return bool(cond)

    def env_fail(self, reason):
        self.env_failed += 1
        print("  ENV_FAIL: %s" % reason, flush=True)

    def finish(self):
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0"
              % (self.passed, self.failed, self.env_failed), flush=True)
        if self.failed:
            sys.exit(lib_env.EXIT_FAIL)
        if self.env_failed:
            sys.exit(lib_env.EXIT_ENV_FAIL)
        sys.exit(lib_env.EXIT_PASS)


def _run(argv, env=None, timeout_s=None):
    """Run a child; a timeout comes back as rc -1 with a named reason."""
    bound = CHILD_TIMEOUT_S if timeout_s is None else float(timeout_s)
    try:
        out = subprocess.run(argv, capture_output=True, text=True, env=env,
                             timeout=bound)
    except subprocess.TimeoutExpired:
        return -1, "", "timeout after %.1fs" % bound
    return out.returncode, out.stdout or "", out.stderr or ""


def _tail(text, limit=200):
    return (text or "").strip()[-limit:]


def _sa_names(bin_path, port):
    """The search-attribute names the bench actually serves (CLI, real RPC)."""
    rc, out, err = _run([bin_path, "operator", "search-attribute", "list",
                         "--namespace", bench.NAMESPACE,
                         "--address", bench.endpoint(port)], timeout_s=30)
    if rc != 0:
        return None, _tail(out + err) or "rc=%s" % rc
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in _SA_TYPES:
            names.add(parts[0])
    return names, ""


def main():
    rec = Rec()
    bin_path = bench.default_bin()
    print("== environment", flush=True)
    if not os.path.exists(bin_path):
        rec.env_fail("temporal binary missing (%s) — the bench cannot run; "
                     "it is provisioned per checkout (gitignored bin/)" % bin_path)
        rec.finish()
    if not os.access(bin_path, os.X_OK):
        rec.env_fail("temporal binary not executable: %s" % bin_path)
        rec.finish()
    print("  temporal binary: %s" % bin_path, flush=True)

    handle = None
    stub = None
    try:
        # ---- L0: the bench comes up -------------------------------------
        print("== L0 the bench comes up", flush=True)
        t0 = time.time()
        handle = bench.start(bin_path=bin_path)
        wall = time.time() - t0
        if not handle.get("ok"):
            rec.env_fail("bench did not start: %s" % handle.get("reason"))
            rec.finish()
        rec.check(sorted(handle) == ["db", "ok", "pid", "port", "start_s"],
                  "up prints exactly the declared contract keys (%s)"
                  % sorted(handle))
        rec.check(isinstance(handle["port"], int) and handle["port"] > 1024,
                  "a kernel-picked free port (%s)" % handle["port"])
        rec.check(bench.endpoint(handle["port"]) not in PRODUCTION_ADDRESSES,
                  "the bench is not a production/console address (%s)"
                  % bench.endpoint(handle["port"]))
        rec.check(isinstance(handle["pid"], int) and handle["pid"] > 1,
                  "the bench pid is reported (%s)" % handle["pid"])
        rec.check(handle["start_s"] < 15.0,
                  "the bench is up in seconds (start_s=%s, wall=%.2fs)"
                  % (handle["start_s"], wall))

        # ---- L1: the private db -----------------------------------------
        print("== L1 the private db is the only filesystem isolation", flush=True)
        db_file = Path(handle["db"])
        rec.check(db_file.exists(), "the private sqlite file exists: %s" % db_file)
        rec.check(db_file.parent.name.startswith(bench.TEMP_PREFIX),
                  "it lives in a bench temp dir (%s)" % db_file.parent.name)
        try:
            db_file.resolve().relative_to(ROOT)
            inside_repo = True
        except ValueError:
            inside_repo = False
        rec.check(not inside_repo, "the temp dir is outside the repo tree")

        # ---- L2: the endpoint serves, with the engine SA set ------------
        print("== L2 the endpoint serves the engine search attributes", flush=True)
        names, why = _sa_names(bin_path, handle["port"])
        if names is None:
            rec.check(False, "search-attribute list answered (%s)" % why)
        else:
            missing = [n for n in bench.SEARCH_ATTRIBUTES if n not in names]
            rec.check(not missing,
                      "all %d engine search attributes are registered (missing=%s)"
                      % (len(bench.SEARCH_ATTRIBUTES), missing))
        probe_rc, _probe_out, probe_err = _run(
            [bin_path, "operator", "namespace", "describe",
             "--namespace", bench.NAMESPACE,
             "--address", bench.endpoint(handle["port"])], timeout_s=30)
        rec.check(probe_rc == 0,
                  "a real gRPC round trip answers on the endpoint (rc=%s %s)"
                  % (probe_rc, _tail(probe_err, 120)))

        # ---- L3: the endpoint hand-off through the engine's own face ----
        print("== L3 the engine resolves the injected endpoint", flush=True)
        child_env = bench.consumer_env(handle["port"])
        py = ROOT / "server" / "engine" / ".venv" / "bin" / "python"
        engine_py = str(py) if py.exists() else sys.executable
        rc, out, err = _run(
            [engine_py, "-B", "-c",
             "import sys; sys.path.insert(0, 'server/engine');"
             " import shared;"
             " print(shared.TARGET_HOST); print(shared.NAMESPACE)"],
            env=child_env, timeout_s=60)
        lines = out.split()
        rec.check(rc == 0 and len(lines) >= 2,
                  "the engine module imports under the injected env (rc=%s %s)"
                  % (rc, _tail(err, 120)))
        if len(lines) >= 2:
            rec.check(lines[0] == bench.endpoint(handle["port"]),
                      "shared.TARGET_HOST is the bench endpoint (%s)" % lines[0])
            rec.check(lines[0] not in PRODUCTION_ADDRESSES,
                      "never the production Temporal address (%s)" % lines[0])
            rec.check(lines[1] == bench.NAMESPACE,
                      "shared.NAMESPACE is the bench namespace (%s)" % lines[1])

        # ---- L4: an existing read-only scenario green on that endpoint --
        print("== L4 t260907-04-dispatcher-lock-fallback green on the endpoint",
              flush=True)
        t0 = time.time()
        rc, out, err = _run([sys.executable, "-B", EXISTING], env=child_env)
        child_wall = time.time() - t0
        if rc == 2:
            rec.env_fail("the child scenario reported an environment red: %s"
                         % _tail(out + err, 300))
        else:
            summary = [ln for ln in out.splitlines() if ln.startswith("SUMMARY ")]
            rec.check(rc == 0,
                      "the child scenario exits 0 (rc=%s) in %.1fs"
                      % (rc, child_wall))
            rec.check(bool(summary), "the child scenario prints its SUMMARY line")
            if summary:
                fields = dict(part.split("=", 1)
                              for part in summary[-1].split()[1:]
                              if "=" in part)
                rec.check(fields.get("fail") == "0"
                          and fields.get("env_fail") == "0"
                          and int(fields.get("pass") or 0) > 0,
                          "its own legs are green (%s)" % summary[-1])
            bad = [ln for ln in out.splitlines()
                   if ln.lstrip().startswith("FAIL ") or ln.startswith("ENV_FAIL")]
            rec.check(not bad,
                      "no FAIL/ENV_FAIL line in its output (%s)" % bad[:2])

        # ---- L5: down leaves no residue --------------------------------
        print("== L5 down leaves no residue (judged from the outside)", flush=True)
        block = bench.stop(handle["port"], handle["pid"], db=handle["db"])
        rec.check(block["clean"] is True,
                  "down reports a clean residue: %s"
                  % json.dumps({k: block[k] for k in
                                ("port_refuses", "pid_alive", "group_alive",
                                 "survivors")}))
        rec.check(block["port_refuses"] is True,
                  "the port refuses connections after down (%s)"
                  % bench.endpoint(handle["port"]))
        rec.check(block["pid_alive"] is False and block["group_alive"] is False,
                  "no surviving child in the process group (survivors=%s)"
                  % block["survivors"])
        rec.check(block["db_removed"] is True,
                  "the private temp dir is reclaimed")
        rec.check(block["escalated"] is False,
                  "an obedient server was never escalated to SIGKILL "
                  "(escalated=%s)" % block["escalated"])
        rec.check(block["stopped_s"] <= STOP_WINDOW_S,
                  "the obedient stop lands inside its declared window "
                  "(measured stopped_s=%.2f, declared window=%.1fs = %g x %.1fs "
                  "round-load stop, TERM_S %.1fs floor)"
                  % (block["stopped_s"], STOP_WINDOW_S, STOP_LOAD_FACTOR,
                     STOP_ROUND_LOAD_S, bench.TERM_S))
        print("  evidence L5 stop: %s"
              % json.dumps({"stopped_s": block["stopped_s"],
                            "window_s": round(STOP_WINDOW_S, 2),
                            "basis": {"standalone_s": STOP_STANDALONE_S,
                                      "round_load_s": STOP_ROUND_LOAD_S,
                                      "load_factor": STOP_LOAD_FACTOR,
                                      "term_s": bench.TERM_S},
                            "escalated": block["escalated"],
                            "port_refuses": block["port_refuses"],
                            "group_alive": block["group_alive"],
                            "survivors": block["survivors"]},
                           sort_keys=True), flush=True)
        rc, out, err = _run([sys.executable, "-B", MODULE, "status",
                             "--port", str(handle["port"]),
                             "--pid", str(handle["pid"])], timeout_s=60)
        reread = {}
        try:
            reread = json.loads(out.strip().splitlines()[-1])
        except Exception:                                        # noqa: BLE001
            reread = {}
        rec.check(rc == 0 and reread.get("clean") is True,
                  "a FRESH process reads the same clean verdict (rc=%s %s)"
                  % (rc, _tail(out, 160)))
        handle = None

        # ---- L6: the SIGKILL escalation really exists -------------------
        print("== L6 a TERM-ignoring child is killed, not asked", flush=True)
        port = bench.free_port()
        stub = subprocess.Popen([sys.executable, "-c", _STUB_TERM_IGNORING,
                                 str(port)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                start_new_session=True)
        ready = stub.stdout.readline() if stub.stdout else ""
        if "ready" not in ready:
            rec.check(False, "the TERM-ignoring stub came up (%r)" % ready)
        else:
            os.killpg(stub.pid, 15)
            rec.check(bench.group_alive(stub.pid) is True,
                      "SIGTERM alone leaves the stubborn child standing")
            esc = bench.stop(port, stub.pid, term_s=0.5, kill_s=3.0)
            rec.check(esc["escalated"] is True,
                      "the down path escalated to SIGKILL: %s"
                      % json.dumps({k: esc[k] for k in
                                    ("escalated", "stopped_s", "group_alive")}))
            rec.check(esc["clean"] is True and esc["survivors"] == [],
                      "and the group is empty afterwards (survivors=%s)"
                      % esc["survivors"])
            stub = None

        # ---- L7: a bad binary costs nothing ----------------------------
        print("== L7 a bad binary is refused by name and starts nothing",
              flush=True)
        spare = Path(tempfile.mkdtemp(prefix="sandbar-bench-badbin-"))
        try:
            bogus = spare / "no-such-dir" / "temporal"
            rc, out, err = _run([sys.executable, "-B", MODULE, "up",
                                 "--bin", str(bogus)], timeout_s=60)
            rec.check(rc != 0, "the CLI refuses a missing binary (rc=%s)" % rc)
            named = "ENV_FAIL" in err and "temporal binary not found" in err
            rec.check(named, "the refusal is named (stderr: %s)" % _tail(err))
            leftovers = sorted(p.name for p in spare.iterdir())
            rec.check(leftovers == [],
                      "nothing half-started was left behind (%s)" % leftovers)
        finally:
            shutil.rmtree(str(spare), ignore_errors=True)
    finally:
        if stub is not None:
            try:
                os.killpg(stub.pid, 9)
            except OSError:
                pass
            try:
                stub.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if handle is not None and handle.get("ok"):
            bench.stop(handle["port"], handle["pid"], db=handle["db"])
    rec.finish()


if __name__ == "__main__":
    main()
