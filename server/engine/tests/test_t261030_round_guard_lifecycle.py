#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261030-19 — the round slot survives a kill (KI-420 + KI-421).

Two measured holes, both observed live on 2026-10-29/30 while the
develop-buffer line was being certified:

- KI-420: a certification round killed mid-flight (SIGTERM/SIGKILL/timeout)
  left the guard file held for ever, so every later tick answered
  ``{"rounds": [], "end": {"state": "joined", "reason": "guard_held"}}`` —
  which reads like "another round is running" — and the line could never be
  certified again without a human calling ``guard_release`` by hand.
- KI-421: the killed tick's RUNNER kept running (spawned in its own session)
  and kept writing the counts of a round that no longer existed; when the
  scheduler later started a new round, both wrote ``current.json`` and its
  ``revision`` flapped between two trees (measured 8d38ece0 vs 99c65939).

This battery proves the fixes BY CONSTRUCTION with real processes: the cases
below kill real subprocesses (SIGKILL, no cleanup path) and then assert what a
reader and the next tick see. Nothing here stubs the liveness judgement — the
only stubbed seam is the certified suite itself (``runner``), which stays a
fake per the ticket's own constraint that the real suite belongs to the
integration gate.

What is pinned:

- the guard records its holder (run id, pid, process group, start stamp) and
  ``round_state`` distinguishes running / died / reclaimed / idle /
  never_ran;
- an acquire whose holder process is gone reclaims the slot BY NAME (stale
  holder, reason, adopter, when) and needs no human;
- the dead holder's registered RUNNERS are adopted and killed, and a runner
  that would not die stays ``adopt_pending`` (named, never assumed gone);
- a held record with no pid is never reclaimed on a guess;
- two concurrent acquirers: exactly one runs;
- every terminal path releases the guard (normal, runner error, runner
  timeout — the timeout case spawns a real runner process and asserts it is
  dead afterwards);
- no verdict rule changed: a green round is still green, a red round still
  opens its freeze.
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop"

#: A fake tick: acquires the guard, says so in a report file, then holds the
#: slot like a real round would. ``orphan`` mode also spawns a grandchild in
#: its own session (the shape of a real runner: ``start_new_session=True``) and
#: registers it in the guard. The process is meant to be KILLED while it holds
#: the slot: no cleanup path, no release, exactly the measured shape.
FAKE_TICK = r'''
import json
import os
import subprocess
import sys
import time

engine, guard_path, report = sys.argv[1], sys.argv[2], sys.argv[3]
mode = sys.argv[4] if len(sys.argv) > 4 else "hold"
sys.path.insert(0, engine)
import develop_certify as dc

state = dc.guard_acquire(guard_path, "fake-tick")
out = {"granted": state is not None, "pid": os.getpid(), "state": state}
if state is not None and mode == "orphan":
    orphan = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)"],
        start_new_session=True)
    dc.guard_attach_runner(guard_path, orphan.pid, orphan.pid)
    out["orphan_pid"] = orphan.pid
with open(report, "w", encoding="utf-8") as fh:
    json.dump(out, fh)
if state is None:
    sys.exit(0)
time.sleep(600)
'''

#: A claimant: waits on a shared start flag, then races for the slot. The
#: winner holds it (and is killed by the test); the losers record "not
#: granted" and exit.
FAKE_CLAIMANT = r'''
import json
import os
import sys
import time

engine, guard_path, report, go_flag = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, engine)
import develop_certify as dc

with open(report + ".ready", "w", encoding="utf-8") as fh:
    fh.write("1")
deadline = time.time() + 60
while not os.path.exists(go_flag) and time.time() < deadline:
    time.sleep(0.01)
state = dc.guard_acquire(guard_path, "claimant-%d" % os.getpid())
with open(report, "w", encoding="utf-8") as fh:
    json.dump({"granted": state is not None, "pid": os.getpid()}, fh)
if state is None:
    sys.exit(0)
time.sleep(600)
'''


# ---- fixtures and helpers --------------------------------------------------

def guard_path(tmp_path):
    """The anchor path the production tick uses (``<ledger dir>/tick-anchor``);
    the guard file itself lands beside it as ``delivery-guard.json``."""
    return str(tmp_path / "ledger" / "tick-anchor")


def guard_file(tmp_path):
    return tmp_path / "ledger" / dc.GUARD_NAME


def write_script(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def spawn(script, *args):
    return subprocess.Popen([sys.executable, str(script)] + [str(a) for a in args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)


def wait_for(path, budget_s=20.0):
    deadline = time.time() + budget_s
    while time.time() < deadline:
        if Path(path).exists():
            return True
        time.sleep(0.02)
    return False


def read_json(path):
    with open(str(path), encoding="utf-8") as fh:
        return json.load(fh)


def kill_hard(proc):
    """SIGKILL: no Python cleanup runs, so the slot is left exactly as a killed
    tick leaves it."""
    if proc.poll() is None:
        os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=20)


def dead(pid, budget_s=15.0):
    deadline = time.time() + budget_s
    while time.time() < deadline:
        if not dc._pid_alive(pid):
            return True
        time.sleep(0.02)
    return not dc._pid_alive(pid)


def ledger(tmp_path):
    return tmp_path / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def landing(repo="sandbar", rev="rev1", ticket="t1", at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": LINE, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def green_header(ran=10):
    return {"id": dc.mint_id("run"), "cases": {"ran": ran, "failed": 0,
                                               "env_failed": 0}}


def red_header(failed=3):
    return {"id": dc.mint_id("run"), "cases": {"ran": 10, "failed": failed,
                                               "env_failed": 0}}


# ---- the three reader states ----------------------------------------------

def test_never_ran_state_on_empty_slot(tmp_path):
    state = dc.round_state(guard_path(tmp_path))
    assert state["state"] == dc.GUARD_NEVER_RAN
    assert not dc.guard_held(guard_path(tmp_path))
    assert dc.guard_holder(guard_path(tmp_path)) is None


def test_guard_records_its_holder_and_reads_running(tmp_path):
    gp = guard_path(tmp_path)
    holder = dc.guard_acquire(gp, "engine-tick")
    assert holder is not None
    # identity: run id, pid, process group, start stamp, when it started
    assert holder["run_id"].startswith("roundtick-")
    assert holder["pid"] == os.getpid()
    assert isinstance(holder["pgid"], int) and holder["pgid"] > 0
    assert isinstance(holder["started_at"], int)
    assert holder["pid_started_stamp"], "the start stamp protects pid reuse"
    state = dc.round_state(gp)
    assert state["state"] == dc.GUARD_RUNNING
    assert state["holder"]["pid"] == os.getpid()
    assert state["holder"]["run_id"] == holder["run_id"]
    # a second acquire in the same live process is refused (at most one)
    assert dc.guard_acquire(gp, "second-claimant") is None
    released = dc.guard_release(gp)
    assert released["held"] is False
    assert released["last_round"]["run_id"] == holder["run_id"]
    after = dc.round_state(gp)
    assert after["state"] == dc.GUARD_IDLE    # a round ran and ended cleanly
    assert after["last_round"]["run_id"] == holder["run_id"]


def test_held_record_without_pid_is_never_reclaimed(tmp_path):
    """A record that cannot prove itself dead stays held (a pre-t261030-19
    record, or a truncated one) — the honest degrade, never a takeover."""
    gp = guard_path(tmp_path)
    guard_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    guard_file(tmp_path).write_text(
        json.dumps({"held": True, "by": "pre-t261030-19", "at": 1}),
        encoding="utf-8")
    assert dc.guard_held(gp) is True
    assert dc.guard_acquire(gp, "next-tick") is None
    state = dc.round_state(gp)
    assert state["state"] == dc.GUARD_RUNNING
    assert state["liveness"] == dc.GUARD_REASON_UNVERIFIABLE


def test_killed_round_is_reclaimed_by_name(tmp_path):
    """KI-420's exact shape: a real round process holding the slot is SIGKILLed
    (no release, no finally). The next acquire must reclaim it BY NAME."""
    gp = guard_path(tmp_path)
    script = write_script(tmp_path, "fake_tick.py", FAKE_TICK)
    report = tmp_path / "tick-report.json"
    tick = spawn(script, ENGINE, gp, report, "hold")
    assert wait_for(report), "fake tick never acquired the guard"
    info = read_json(report)
    assert info["granted"] is True
    assert dc.round_state(gp)["state"] == dc.GUARD_RUNNING
    kill_hard(tick)
    assert dead(info["pid"])

    # the killed tick left the record held; it is not a running round
    assert dc.guard_held(gp) is False
    died = dc.round_state(gp)
    assert died["state"] == dc.GUARD_DIED
    assert died["liveness"] == dc.GUARD_REASON_HOLDER_GONE
    assert died["holder"]["pid"] == info["pid"]
    assert died["holder"]["run_id"] == info["state"]["run_id"]

    # the next tick reclaims it by name — no human, no guard_release
    adopted = dc.guard_acquire(gp, "next-tick")
    assert adopted is not None
    reclaim = adopted["reclaimed"]
    assert reclaim["reason"] == dc.GUARD_REASON_HOLDER_GONE
    assert reclaim["stale"]["pid"] == info["pid"]
    assert reclaim["stale"]["run_id"] == info["state"]["run_id"]
    assert reclaim["by"] == "next-tick"
    assert reclaim["run_id"] == adopted["run_id"] != info["state"]["run_id"]
    assert isinstance(reclaim["at"], int)
    running = dc.round_state(gp)
    assert running["state"] == dc.GUARD_RUNNING
    assert running["holder"]["run_id"] == adopted["run_id"]
    assert running["reclaimed"]["stale"]["pid"] == info["pid"]

    # and after that round ends, the death-and-reclaim stays readable
    dc.guard_release(gp)
    receipt = dc.round_state(gp)
    assert receipt["state"] == dc.GUARD_RECLAIMED
    assert receipt["reclaimed"]["stale"]["pid"] == info["pid"]
    assert receipt["reclaimed"]["by"] == "next-tick"
    assert receipt["last_round"]["run_id"] == adopted["run_id"]


def test_three_states_are_distinguishable(tmp_path):
    gp = guard_path(tmp_path)
    never = dc.round_state(gp)["state"]
    script = write_script(tmp_path, "fake_tick.py", FAKE_TICK)
    report = tmp_path / "tick-report.json"
    tick = spawn(script, ENGINE, gp, report, "hold")
    assert wait_for(report)
    live = dc.round_state(gp)["state"]
    kill_hard(tick)
    died = dc.round_state(gp)["state"]
    assert dc.guard_acquire(gp, "next-tick") is not None
    reclaimed_running = dc.round_state(gp)["state"]
    dc.guard_release(gp)
    reclaimed_receipt = dc.round_state(gp)["state"]
    assert never == dc.GUARD_NEVER_RAN
    assert live == dc.GUARD_RUNNING
    assert died == dc.GUARD_DIED
    assert reclaimed_running == dc.GUARD_RUNNING
    assert reclaimed_receipt == dc.GUARD_RECLAIMED
    # the three the ticket names read differently, and the killed case never
    # reads as "joined"/"guard_held" the way it used to
    assert len({never, live, died, reclaimed_receipt}) == 4
    assert died != live
    # a stale slot never answers "a round is running" to the round entry
    assert dc.guard_held(gp) is False


def test_two_concurrent_acquirers_exactly_one_runs(tmp_path):
    gp = guard_path(tmp_path)
    script = write_script(tmp_path, "fake_claimant.py", FAKE_CLAIMANT)
    go = tmp_path / "go-flag"
    procs, reports = [], []
    for i in range(6):
        report = tmp_path / ("claim-%d.json" % i)
        reports.append(report)
        procs.append(spawn(script, ENGINE, gp, report, go))
    try:
        for report in reports:
            assert wait_for(Path(str(report) + ".ready"), 30), \
                "a claimant never reached the race"
        go.write_text("1", encoding="utf-8")
        granted = []
        for report in reports:
            assert wait_for(report, 30), "a claimant never recorded its answer"
            answer = read_json(report)
            if answer["granted"]:
                granted.append(answer["pid"])
        assert len(granted) == 1, "exactly one acquirer may hold the slot"
        holder = dc.round_state(gp)["holder"]
        assert holder["pid"] == granted[0]
        # the losers never released or overwrote the winner's record
        assert holder["pid"] == granted[0]
    finally:
        for proc in procs:
            kill_hard(proc)
    assert dead(granted[0])


def test_orphaned_runner_is_adopted_and_killed(tmp_path):
    """KI-421's exact shape: the tick dies with SIGKILL, its runner (own
    session) keeps running. The next acquire adopts the orphan and kills it —
    and names the adoption in the guard record."""
    gp = guard_path(tmp_path)
    script = write_script(tmp_path, "fake_tick.py", FAKE_TICK)
    report = tmp_path / "tick-report.json"
    tick = spawn(script, ENGINE, gp, report, "orphan")
    assert wait_for(report), "fake tick never acquired the guard"
    info = read_json(report)
    orphan = int(info["orphan_pid"])
    assert dc._pid_alive(orphan), "the fixture must leave a real orphan behind"
    assert dc.round_state(gp)["runners"][0]["pid"] == orphan
    kill_hard(tick)
    assert dead(info["pid"])
    assert dc._pid_alive(orphan), \
        "the orphan must outlive its tick, or the case proves nothing"

    adopted = dc.guard_acquire(gp, "next-tick")
    assert adopted is not None
    assert dead(orphan), "the reclaimed slot's orphan runner must be killed"
    results = adopted["reclaimed"]["adopted"]
    assert len(results) == 1
    assert results[0]["pid"] == orphan
    assert results[0]["result"] in ("gone", "terminated", "killed")
    assert adopted["reclaimed"]["adopt_pending"] == []


# ---- every terminal path releases the guard -------------------------------

def test_normal_round_releases_the_guard(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    gp = guard_path(tmp_path)
    out = dc.run_line_round(LINE, "change", gp,
                            lambda c: green_header(), reader(p), writer(p),
                            "round-engine", "booked-v1")
    assert out["rounds"][0]["state"] == dc.STATE_CERTIFIED
    assert out["rounds"][0]["verdict"] == "green"
    assert dc.guard_held(gp) is False
    assert dc.round_state(gp)["state"] == dc.GUARD_IDLE


def test_runner_error_path_releases_the_guard(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    gp = guard_path(tmp_path)

    def runner(_candidate):
        raise dc.CouldNotRun("suite_tree_missing")

    out = dc.run_line_round(LINE, "change", gp, runner, reader(p), writer(p),
                            "round-engine", "booked-v1")
    assert out["rounds"][0]["state"] == dc.STATE_GREW
    assert dc.guard_held(gp) is False


def test_runner_timeout_releases_the_guard_and_kills_the_runner(tmp_path,
                                                               monkeypatch):
    """A REAL runner process, a real timeout: the runner is reaped, the guard
    is released, and the spawned pid is gone afterwards."""
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    gp = guard_path(tmp_path)
    spawned = []
    real_attach = dc.guard_attach_runner

    def spy(path, pid, pgid=None):
        spawned.append(pid)
        return real_attach(path, pid, pgid)

    monkeypatch.setattr(dc, "guard_attach_runner", spy)
    cmd = "%s -c %s" % (shlex.quote(sys.executable),
                        shlex.quote("import time; time.sleep(120)"))
    env = {dc.RUNNER_CMD_ENV: cmd, dc.RUNNER_TIMEOUT_ENV: "1",
           dc.GUARD_ANCHOR_ENV: gp}
    runner = dc.resolve_runner(LINE, env)
    assert runner is not None
    out = dc.run_line_round(LINE, "change", gp, runner, reader(p), writer(p),
                            "round-engine", "booked-v1")
    assert out["rounds"][0]["state"] == dc.STATE_GREW
    assert "runner_timeout" in out["rounds"][0]["reason"]
    assert spawned, "the runner must register itself in the guard"
    assert dead(spawned[0]), "the timed-out runner must be dead"
    assert dc.guard_held(gp) is False


def test_cancel_path_releases_the_guard(tmp_path):
    """A cancelled round (the activity is cancelled mid-run) re-raises, and the
    slot is free afterwards — the cancel path is a terminal path too."""
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    gp = guard_path(tmp_path)

    def runner(_candidate):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        dc.run_line_round(LINE, "change", gp, runner, reader(p), writer(p),
                          "round-engine", "booked-v1")
    assert dc.guard_held(gp) is False
    assert dc.round_state(gp)["state"] == dc.GUARD_IDLE


def test_red_round_still_freezes(tmp_path):
    """No verdict rule changed: a red round is still red and still opens its
    freeze episode."""
    p = ledger(tmp_path)
    dc.append_rows([landing()], p)
    gp = guard_path(tmp_path)
    out = dc.run_line_round(LINE, "change", gp,
                            lambda c: red_header(), reader(p), writer(p),
                            "round-engine", "booked-v1")
    entry = out["rounds"][0]
    assert entry["state"] == dc.STATE_RED
    assert entry["verdict"] == "red"
    assert entry.get("freeze"), "a red round still opens a freeze episode"
    rows, bad = dc.read_rows(p)
    assert not bad
    assert [r for r in rows if r["kind"] == dc.KIND_FREEZE]
    assert dc.guard_held(gp) is False
