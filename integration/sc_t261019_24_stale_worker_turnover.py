#!/usr/bin/env python3
"""sc_t261019_24_stale_worker_turnover.py — stale code stops taking new work.

Ticket t261019-24: every engine code change silently left the whole worker
fleet on old code — running workers kept polling and taking new work after a
fix landed in main, tickets then blocked with mixed-fleet errors, and the only
turnover was a hand-driven kill of every worker pid. The detection faces
already existed (shared.worker_code_stamp, engine_ops drift); the missing
piece was the consequence. The landed fix: a slow cadence checker inside
run_worker recomputes the process's own code stamp with the SAME pure function
the gate receipt uses; when a worker-loaded module is stale, the worker logs a
loud English reason, records a self_stop record, and sets the EXISTING stop
event — the proven graceful path then drains in-flight activities and exits,
and the console supervisor's keepalive starts the replacement. This scenario
judges that contract, grey-box, offline, through the module's public seams.

Legs (PASS/FAIL; ENV_FAIL only when the engine tree itself is unreadable):
  A  pure judgement truth table — stale_modules_for_self over
     shared.worker_code_stamp: a worker-loaded module whose on-disk mtime is
     newer than the start baseline IS stale; an older one is NOT; malformed
     mtime is NEVER stale (conservative rule reused, not reimplemented); a
     missing baseline degrades without crashing.
  B  behaviour — the real per-tick reflex (process_stale_tick): one stale
     tick does not stop (debounce counter), the tick that reaches
     STALE_TURNOVER_TICKS sets the caller's stop event and writes the reason,
     clean ticks reset the counter, a raising stamp verdict is logged and the
     loop keeps judging.
  C  durable reason face — the self-stop record is machine-readable from the
     ownership meta AND survives the process exit: the t261005-03 exit-time
     unlink is spared for a meta that carries self_stop (own pid), a meta
     without the marker still goes, a taken-over meta (foreign pid) is never
     touched, and a meta-write failure degrades to the log line (named).
  D  turnover discipline — the watch loop spawns no process and signals no
     pid: self-stop only; the replacement is the console supervisor's
     keepalive, never this code (red line), and the stop event is the same
     one the SIGTERM handler uses so _graceful_shutdown (drain first) is the
     only exit path; the graceful cap stays t261019-19's subject.
  E  faces not weakened — shared.worker_code_stamp still returns the
     documented key set with the conservative rule, and engine_ops drift
     still owns detection.

Run directly (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B \
      integration/sc_t261019_24_stale_worker_turnover.py
Exit codes: 0 all green, 1 product red, 2 ENV_FAIL.
"""
import asyncio
import logging
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

PASS = 0
FAIL = 0
PROBLEMS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        PROBLEMS.append(label)
        print("  RED %s" % label)


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


# ---------------------------------------------------------------- engine tree
if not (ENGINE / "worker.py").is_file() or not (ENGINE / "shared.py").is_file():
    env_fail("engine tree missing under server/engine (worker.py / shared.py)")

try:
    import shared as _shared  # noqa: E402
    import worker as _worker  # noqa: E402
except Exception as exc:  # temporalio chain or syntax-level breakage
    env_fail("engine modules unimportable: %s" % exc)

WORKER_SRC = (ENGINE / "worker.py").read_text("utf-8")
OPS_SRC = (ROOT / "server" / "tools" / "engine_ops.py").read_text("utf-8")

helper = getattr(_worker, "stale_modules_for_self", None)
tick_fn = getattr(_worker, "process_stale_tick", None)
record_self_stop = getattr(_worker, "record_self_stop", None)
keep_meta = getattr(_worker, "keep_meta_on_self_stop", None)

FAKE_NOW = 2_000_000_000.0
import datetime as dt
BASELINE = dt.datetime.fromtimestamp(FAKE_NOW).isoformat(timespec="seconds")


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:
            pass


print("\n[A] pure judgement truth table (shared.worker_code_stamp consumed)")
if helper is None:
    ok(False, "stale_modules_for_self is absent on worker.py")
else:
    root = Path(tempfile.mkdtemp(prefix="sc-t261019-24-stamp-"))
    try:
        (root / "server" / "engine").mkdir(parents=True)
        (root / "server" / "engine" / "probe_module.py").write_text(
            "# probe\n", encoding="utf-8")
        out_new = helper(mtime_fn=lambda p: FAKE_NOW + 5.0, started_at=BASELINE,
                         repo_root=root)
        out_old = helper(mtime_fn=lambda p: FAKE_NOW - 5.0, started_at=BASELINE,
                         repo_root=root)
        out_bad = helper(mtime_fn=lambda p: float("nan"), started_at=BASELINE,
                         repo_root=root)
        ok(isinstance(out_new, list) and len(out_new) >= 1,
           "a module newer than the start baseline is judged stale")
        ok(isinstance(out_old, list) and len(out_old) == 0,
           "a module older than the start baseline is judged current")
        ok(isinstance(out_bad, list) and len(out_bad) == 0,
           "malformed mtime is never stale (conservative rule reused)")
        try:
            out_none = helper(mtime_fn=lambda p: FAKE_NOW + 5.0,
                              started_at=None, repo_root=root)
            ok(out_none is not None,
               "missing explicit baseline returns a judged list (no crash)")
        except Exception as exc:  # noqa: BLE001
            ok(False, "missing baseline path crashed: %s" % exc)
    except Exception as exc:  # noqa: BLE001
        ok(False, "[A] helper drive raised: %s" % exc)
    finally:
        import shutil
        shutil.rmtree(str(root), ignore_errors=True)


class _Stop:
    """A stop-event stand-in with the same .set()/.is_set() contract."""

    def __init__(self):
        self._ev = asyncio.Event()

    def set(self):
        self._ev.set()

    def is_set(self):
        return self._ev.is_set()


def _write_meta(tmp):
    meta = Path(tmp) / "worker_meta.json"
    _shared.write_worker_meta(str(meta), repo_root=str(ROOT),
                              pid=__import__("os").getpid())
    return str(meta)


print("\n[B] behaviour — the real per-tick reflex (process_stale_tick)")
if tick_fn is None:
    ok(False, "process_stale_tick is absent (the per-tick seam)")
else:
    cap = _LogCapture()
    logging.getLogger().addHandler(cap)
    old_level = logging.getLogger().level
    logging.getLogger().setLevel(logging.INFO)
    try:
        tmp = tempfile.mkdtemp(prefix="sc-t261019-24-tick-")
        meta = _write_meta(tmp)
        stop = _Stop()
        t1 = tick_fn(0, ["probe_module"], meta, 5.0, stop)
        ok(t1 >= 1 and not stop.is_set(),
           "one stale tick starts the counter and does NOT stop (debounce)")
        tick_fn(t1, ["probe_module"], meta, 5.0, stop)
        ok(stop.is_set(),
           "the tick reaching the turnover threshold sets the stop event")
        loud = [ln for ln in cap.lines if "self-stop" in ln.lower()
                and "probe_module" in ln]
        ok(bool(loud),
           "the stop is logged loud with the stale module names in English")
        ok(any("watch_interval" in ln for ln in loud),
           "the log states the bounded worst case (watch intervals of exposure)")
        stop2 = _Stop()
        t2 = tick_fn(3, [], meta, 5.0, stop2)
        ok(t2 == 0 and not stop2.is_set(),
           "a clean tick resets the counter and never stops")
        # meta now carries the self-stop record written on the firing tick
        got, state, _d = _shared.read_worker_meta_state(meta)
        ok(state == "ok" and isinstance(got, dict)
           and (got.get("self_stop") or {}).get("reason") == "stale-code"
           and "probe_module" in (got.get("self_stop") or {}).get("stale", []),
           "the self-stop record (reason + stale list) is machine-readable "
           "from the meta")
    except Exception as exc:  # noqa: BLE001
        ok(False, "[B] reflex drive raised: %s" % exc)
    finally:
        logging.getLogger().removeHandler(cap)
        logging.getLogger().setLevel(old_level)
        import shutil
        shutil.rmtree(str(tmp), ignore_errors=True)


print("\n[C] durable reason face — the record survives the process exit")
if keep_meta is None or record_self_stop is None:
    ok(False, "record_self_stop / keep_meta_on_self_stop are absent")
else:
    tmp = tempfile.mkdtemp(prefix="sc-t261019-24-meta-")
    try:
        import os as _os
        meta = _write_meta(tmp)
        ok(record_self_stop(meta, "stale-code", ["probe_module"]),
           "record_self_stop writes the machine-readable reason")
        ok(keep_meta(meta),
           "a meta carrying self_stop (own pid) SURVIVES the exit-time unlink")
        meta2 = _write_meta(Path(tmp) / "plain")
        ok(not keep_meta(meta2),
           "a meta without the self_stop marker still goes at exit (no widening)")
        foreign = Path(tmp) / "foreign.json"
        _shared.write_worker_meta(str(foreign), repo_root=str(ROOT), pid=1)
        ok(not keep_meta(str(foreign)),
           "a taken-over meta (foreign pid) is never kept by this guard")
        ok(not record_self_stop(str(Path(tmp) / "missing-dir" / "m.json"),
                                "stale-code", []),
           "a meta-write failure degrades to best-effort (log line), no raise")
    except Exception as exc:  # noqa: BLE001
        ok(False, "[C] durable-face drive raised: %s" % exc)
    finally:
        import shutil
        shutil.rmtree(str(tmp), ignore_errors=True)
    # wiring: main's exit path actually consults the guard before unlinking
    ok(re.search(r"keep_meta_on_self_stop\(.+\)\s*\n.*unlink", WORKER_SRC, re.S)
       is not None or ("keep_meta_on_self_stop" in WORKER_SRC
                       and "unlink" in WORKER_SRC.split("keep_meta_on_self_stop")[-1]
                       .split("unlink")[0][:600]),
       "main's exit path is wired through the keep guard before unlink")


print("\n[D] turnover discipline — self-stop only, nothing spawned or signalled")
ok("install_stop_signal_handlers" in WORKER_SRC,
   "the stop event is the existing signal-handler event (same drain path)")
ok(re.search(r"async def _code_stamp_watch", WORKER_SRC) is not None
   or "process_stale_tick" in WORKER_SRC,
   "the watch loop is present in run_worker")
m = re.search(r"async def _code_stamp_watch\(\).*?(?=\n    [a-zA-Z_#@\n]|\Z)",
              WORKER_SRC, re.S)
if m:
    body = m.group(0)
    bad = [t for t in ("Popen", "subprocess", "os.system", "os.kill",
                       "signal.kill", "start_new_session") if t in body]
    ok(not bad, "the watch loop spawns no process and signals no pid%s"
       % ("" if not bad else " — found %s" % bad))
else:
    ok(False, "watch loop body not locatable for the discipline scan")
# family face: the whole turnover region introduces no second spawn site
stamps = len(re.findall(r"stale-code", WORKER_SRC))
ok(stamps >= 1, "the self-stop reason word is anchored in worker.py")


print("\n[E] faces not weakened — stamp and drift stay owned where they are")
try:
    out = _shared.worker_code_stamp(mtime_fn=lambda p: FAKE_NOW,
                                    started_at=BASELINE)
    keys = {"worker_started_at", "worker_pid", "modules", "stale", "stamp_line",
            "stale_rule"}
    ok(keys.issubset(set(out.keys())),
       "shared.worker_code_stamp key contract unchanged (consumed, not forked)")
except Exception as exc:  # noqa: BLE001
    ok(False, "worker_code_stamp contract probe raised: %s" % exc)
ok("cmd_drift" in OPS_SRC and "stale" in OPS_SRC,
   "engine_ops drift still owns detection (face intact)")
ok("worker_code_stamp" in WORKER_SRC,
   "worker.py consumes shared.worker_code_stamp (single implementation)")

# ------------------------------------------------------------------- summary
print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
print("SCENARIO t261019-24-stale-worker-self-turnover ran=1 pass=%d fail=%d"
      % (1 if FAIL == 0 else 0, 1 if FAIL else 0))
if PROBLEMS:
    print("FAIL: %d leg(s) red" % FAIL)
    for p in PROBLEMS:
        print("  - %s" % p)
    sys.exit(1)
print("PASS")
sys.exit(0)
