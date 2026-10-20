"""t261019-24 worker stale-code self-turnover (pure-function + meta faces, zero Temporal).

A worker imports the engine once at startup; after a fix lands, a stale worker kept
taking new work as if it were current (the 261019 mixed-fleet incidents). The added
consequence, drain-first: on STALE_TURNOVER_TICKS consecutive stale stamp verdicts the
worker records a self_stop reason, sets the SAME stop event SIGTERM uses, and the
existing graceful path (drain within graceful_shutdown_timeout, supervisor respawn)
takes over. These tests pin:

  - worker.stale_modules_for_self — injectable wrapper over shared.worker_code_stamp:
    stale / clean / malformed-mtime-never-stale / raising-stamp (external-input
    discipline: all shapes via injected mtime_fn, no disk, no real source tree);
  - worker.process_stale_tick — the debounce state machine: clean resets, first stale
    tick waits, second fires exactly once (log + meta + stop event, never a second
    fire), zero negative watch_interval cannot fire early;
  - worker.record_self_stop / keep_meta_on_self_stop — the postmortem face survives
    the exit (review comment 1): meta kept when it carries self_stop and our pid;
    unlinked-path preserved when no marker or a taken-over meta;
  - worker.mark_meta_draining — carries the self_stop record across the draining
    rewrite (write_worker_meta builds a fixed payload and would drop it);
  - wiring tripwires — run_worker creates the watch task on the existing watch
    cadence, reaps it in _graceful_shutdown, and main consults
    keep_meta_on_self_stop before the exit unlink.

UT discipline: no network, no Temporal, no real git, no real engine tree touched.
"""
import inspect
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import shared  # noqa: E402
import worker  # noqa: E402


class _StopFlag:
    """Loop-free stand-in for the production stop event.

    WHY not asyncio.Event: on py3.9 constructing an Event outside a running loop calls
    get_event_loop(), which raises 'Event loop is closed' when an earlier async test in
    the same process closed the ambient loop — the tick tests then failed ONLY inside
    the full suite (order-dependent, reproduced on the lane). process_stale_tick
    touches only set()/is_set(), which is exactly this stand-in's face; the production
    wiring (the REAL asyncio.Event the SIGTERM handler returns) is pinned by the source
    tripwires below, not by instantiating one here."""

    def __init__(self):
        self._set = False
        self.set_calls = 0

    def set(self):
        self._set = True
        self.set_calls += 1

    def is_set(self):
        return self._set


# ---------- stale_modules_for_self (injectable stamp wrapper) ----------

def _mtime(times_by_name):
    """mtime_fn stub: engine module name -> mtime; unknown names get 0.0 (old)."""
    def _fn(path):
        name = pathlib.Path(str(path)).name
        return float(times_by_name.get(name, 0.0))
    return _fn


def _stamp_names(_repo):
    """Tracked module file basenames (from the shared table, not hardcoded)."""
    return [pathlib.Path(rel).name for _n, rel in shared.CODE_STAMP_MODULES]


def test_stale_wrapper_reports_stale_modules():
    names = _stamp_names("x")
    # baseline (start) before every file except one pushed past it
    times = {n: 1000.0 for n in names}
    late_file = names[0]
    late_module = next(name for name, rel in shared.CODE_STAMP_MODULES
                       if pathlib.Path(rel).name == late_file)
    times[late_file] = 5000.0
    start = shared._dt.datetime.fromtimestamp(2000.0).isoformat(timespec="seconds")
    stale = worker.stale_modules_for_self(mtime_fn=_mtime(times), started_at=start,
                                          repo_root="/fake/repo")
    assert stale == [late_module]


def test_stale_wrapper_clean_when_all_files_older_than_baseline():
    names = _stamp_names("x")
    times = {n: 1000.0 for n in names}
    start = shared._dt.datetime.fromtimestamp(2000.0).isoformat(timespec="seconds")
    assert worker.stale_modules_for_self(mtime_fn=_mtime(times), started_at=start,
                                         repo_root="/fake/repo") == []


def test_stale_wrapper_malformed_mtime_never_stale():
    """Conservative stamp rule reused verbatim: unreadable mtime is never stale."""

    def bad_mtime(path):
        raise OSError("permission denied")

    start = shared._dt.datetime.fromtimestamp(2000.0).isoformat(timespec="seconds")
    assert worker.stale_modules_for_self(mtime_fn=bad_mtime, started_at=start,
                                         repo_root="/fake/repo") == []


def test_stale_wrapper_verify_lane_role_excluded():
    """verify_lane is a gate subprocess, not worker-loaded: never in the self verdict."""
    names = _stamp_names("x")
    times = {n: 1000.0 for n in names}
    late = "verify_lane.py" if "verify_lane.py" in times else None
    if late is None:
        pytest.skip("verify_lane not in CODE_STAMP_MODULES")
    times[late] = 5000.0
    start = shared._dt.datetime.fromtimestamp(2000.0).isoformat(timespec="seconds")
    stale = worker.stale_modules_for_self(mtime_fn=_mtime(times), started_at=start,
                                          repo_root="/fake/repo")
    assert all(pathlib.Path(n).name != late for n in stale)


def test_stale_wrapper_propagates_stamp_failure():
    """A raising stamp is the caller's problem: the wrapper must not swallow it into a
    fake-clean verdict (the watch loop owns the retry)."""
    import shared as _s
    def boom(*a, **k):
        raise RuntimeError("stamp exploded")
    orig = _s.worker_code_stamp
    _s.worker_code_stamp = boom
    try:
        with pytest.raises(RuntimeError):
            worker.stale_modules_for_self()
    finally:
        _s.worker_code_stamp = orig


# ---------- process_stale_tick (debounce state machine) ----------

def _make_meta(tmp_path):
    meta = tmp_path / "worker.pid.meta"
    meta.write_text(json.dumps({"version": 1, "pid": 12345,
                                "repo_root": str(tmp_path), "ts": 1,
                                "state": "serving"}), "utf-8")
    return str(meta)


def _run_tick(ticks, stale, tmp_path, monkeypatch):
    stop = _StopFlag()
    meta = _make_meta(tmp_path)
    monkeypatch.setattr(worker, "record_self_stop",
                        lambda p, reason, st: _record_capture(p, reason, st))
    new_ticks = worker.process_stale_tick(ticks, stale, meta, 30.0, stop)
    return new_ticks, stop, meta


def _record_capture(path, reason, stale):
    data = json.loads(pathlib.Path(path).read_text("utf-8"))
    data["self_stop"] = {"reason": reason, "stale": list(stale)}
    pathlib.Path(path).write_text(json.dumps(data), "utf-8")
    return True


def test_tick_clean_resets_debounce(tmp_path, monkeypatch):
    n, stop, _meta = _run_tick(1, [], tmp_path, monkeypatch)
    assert n == 0 and not stop.is_set()


def test_tick_first_stale_waits(tmp_path, monkeypatch):
    n, stop, meta = _run_tick(0, ["shared"], tmp_path, monkeypatch)
    assert n == 1
    assert not stop.is_set()
    assert "self_stop" not in json.loads(pathlib.Path(meta).read_text("utf-8"))


def test_tick_second_stale_fires_exactly_once(tmp_path, monkeypatch):
    stop = _StopFlag()
    meta = tmp_path / "worker.pid.meta"
    meta.write_text(json.dumps({"version": 1, "pid": 12345,
                                "repo_root": str(tmp_path), "ts": 1,
                                "state": "serving"}), "utf-8")
    calls = []

    def rec(p, reason, stale):
        calls.append((p, reason, list(stale)))
        return True

    monkeypatch.setattr(worker, "record_self_stop", rec)
    t1 = worker.process_stale_tick(0, ["shared"], str(meta), 30.0, stop)
    t2 = worker.process_stale_tick(t1, ["shared"], str(meta), 30.0, stop)
    assert t1 == 1 and t2 == worker.STALE_TURNOVER_TICKS
    assert stop.is_set()
    assert stop.set_calls == 1
    assert len(calls) == 1
    assert calls[0][1] == "stale-code" and calls[0][2] == ["shared"]


def test_tick_zero_is_not_early_fire(tmp_path, monkeypatch):
    """A malformed/negative previous count must not skip the debounce."""
    stop = _StopFlag()
    meta = tmp_path / "worker.pid.meta"
    meta.write_text(json.dumps({"version": 1, "pid": 12345,
                                "repo_root": str(tmp_path), "ts": 1,
                                "state": "serving"}), "utf-8")
    monkeypatch.setattr(worker, "record_self_stop", lambda *a: True)
    n = worker.process_stale_tick(0, ["shared"], str(meta), 30.0, stop)
    assert n == 1 and not stop.is_set()


def test_tick_never_fires_without_stamp_verdict(tmp_path, monkeypatch):
    stop = _StopFlag()
    monkeypatch.setattr(worker, "record_self_stop",
                        lambda *a: pytest.fail("must not record on a clean tick"))
    assert worker.process_stale_tick(5, [], str(tmp_path), 30.0, stop) == 0
    assert not stop.is_set()


# ---------- record_self_stop / keep_meta_on_self_stop (postmortem face) ----------

def _write_meta(tmp_path, pid=4321, **extra):
    meta = tmp_path / "worker.pid.meta"
    doc = {"version": 1, "pid": pid, "repo_root": str(tmp_path), "ts": 1,
           "state": "serving"}
    doc.update(extra)
    meta.write_text(json.dumps(doc), "utf-8")
    return str(meta)


def test_record_self_stop_writes_reason_and_stale_list(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getpid", lambda: 4321)
    meta = _write_meta(tmp_path)
    assert worker.record_self_stop(meta, "stale-code", ["shared", "dev_lane"]) is True
    doc = json.loads(pathlib.Path(meta).read_text("utf-8"))
    assert doc["self_stop"]["reason"] == "stale-code"
    assert doc["self_stop"]["stale"] == ["shared", "dev_lane"]
    assert doc["state"] == "serving"  # the stop itself stays the graceful path's job


def test_record_self_stop_best_effort_on_missing_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getpid", lambda: 4321)
    assert worker.record_self_stop(str(tmp_path / "absent.meta"), "stale-code",
                                   ["shared"]) is False


def test_keep_meta_when_self_stop_present(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getpid", lambda: 4321)
    meta = _write_meta(tmp_path, pid=4321,
                       self_stop={"reason": "stale-code", "stale": ["shared"]})
    assert worker.keep_meta_on_self_stop(meta) is True


def test_meta_unlinked_normally_without_self_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getpid", lambda: 4321)
    meta = _write_meta(tmp_path, pid=4321)
    assert worker.keep_meta_on_self_stop(meta) is False


def test_never_keep_a_taken_over_meta(tmp_path, monkeypatch):
    """Another worker owns the meta now: the keep-decision must not pin ITS file to us."""
    monkeypatch.setattr(__import__("os"), "getpid", lambda: 4321)
    meta = _write_meta(tmp_path, pid=9999,
                       self_stop={"reason": "stale-code", "stale": ["shared"]})
    assert worker.keep_meta_on_self_stop(meta) is False


def test_malformed_meta_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__("os"), "getpid", lambda: 4321)
    meta = tmp_path / "worker.pid.meta"
    meta.write_text("not json at all", "utf-8")
    assert worker.keep_meta_on_self_stop(str(meta)) is False


def test_absent_meta_is_not_kept(tmp_path):
    assert worker.keep_meta_on_self_stop(str(tmp_path / "absent.meta")) is False
    assert worker.keep_meta_on_self_stop(None) is False


# ---------- mark_meta_draining carries self_stop across the rewrite ----------

def test_draining_rewrite_preserves_self_stop(tmp_path, monkeypatch):
    pid = 4321
    monkeypatch.setattr(__import__("os"), "getpid", lambda: pid)
    meta = _write_meta(tmp_path, pid=pid,
                       self_stop={"reason": "stale-code", "stale": ["shared"]})
    assert worker.mark_meta_draining(meta) is True
    doc = json.loads(pathlib.Path(meta).read_text("utf-8"))
    assert doc["state"] == shared.WORKER_META_STATE_DRAINING
    assert doc["self_stop"] == {"reason": "stale-code", "stale": ["shared"]}


def test_draining_without_self_stop_unchanged_shape(tmp_path, monkeypatch):
    pid = 4321
    monkeypatch.setattr(__import__("os"), "getpid", lambda: pid)
    meta = _write_meta(tmp_path, pid=pid)
    assert worker.mark_meta_draining(meta) is True
    doc = json.loads(pathlib.Path(meta).read_text("utf-8"))
    assert doc["state"] == shared.WORKER_META_STATE_DRAINING
    assert "self_stop" not in doc


# ---------- wiring tripwires ----------

def test_run_worker_wiring():
    src = inspect.getsource(worker.run_worker)
    assert "asyncio.create_task(_code_stamp_watch())" in src
    # the watch rides the SAME cadence and the SAME stop event as the existing loops
    assert "while not stop.is_set():" in src
    assert "process_stale_tick(stale_ticks, stale, meta_path,\n" in src
    # the graceful epilogue reaps the watch task too
    assert "stamp_task=stamp_task)" in src


def test_graceful_shutdown_reaps_stamp_task():
    src = inspect.getsource(worker._graceful_shutdown)
    assert "stamp_task.cancel()" in src


def test_main_consults_keep_guard_before_unlink():
    src = inspect.getsource(worker.main)
    assert "keep_meta_on_self_stop" in src


def test_no_process_starting_path_added():
    """Red line: the turnover must never start or signal another process."""
    for fn in (worker.process_stale_tick, worker.record_self_stop,
               worker.keep_meta_on_self_stop, worker.stale_modules_for_self):
        src = inspect.getsource(fn)
        # strip the docstring: it may NAME the mechanism (e.g. SIGTERM) without
        # invoking anything — the ban is on executable references.
        body = src.split('"""', 2)[-1]
        for banned in ("subprocess", "os.kill", "Popen", "SIGTERM", "system("):
            assert banned not in body, (fn.__name__, banned)


def test_stop_event_is_the_signal_handlers_event():
    """The watch must set the same event SIGTERM sets — one drain path only."""
    src = inspect.getsource(worker.run_worker)
    assert "install_stop_signal_handlers()" in src
    assert "watch_interval, stop)" in src
