#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-46 gate scenario: supply contention waits sized to a real bench
bring-up (gray-box L2, offline injection, zero docker).

User story (ticket t261008-46): the gate supply item runs
`stage_docker.py ensure --project sandbar-test-integ --keep --services full`.
Under multi-lane concurrency the mutex loser carries a flat
SANDBAR_STAGE_WAIT_BUDGET_S (default 120s), but the winner may legitimately be
doing a minutes-scale full-service cold boot. The loser's budget is routinely
exceeded -> honest ENV_FAIL -> supply red -> the round runs zero scenarios ->
a human hand-makes a retry. The fix (plan v2, conditionally passed at
review_plan gen1): contention waits that target a WORKING peer (ensure-mutex
flock loop, _wait_booting) are bounded by a new progress-aware ceiling knob
SANDBAR_STAGE_WORKING_PEER_CEILING_S (default 660s = the holder's own 600s
health-wait ceiling + one grace minute); waits where the peer is provably NOT
working (daemon probe, capacity-0 fuse lock, heartbeat-stall grace) keep the
flat base budget.

User-perceivable behaviour this scenario locks (assertions anchor CLI process
exit code / stderr naming / wall clock / lock and lease files only — never
internal structure):

  C1  ensure-mutex flock contended, holder RENEWING its booting lease (a
      held flock proves the holder alive; the renewal proves it WORKING) ->
      the waiter rides PAST the base budget up to the ceiling, then exits 2
      (ENV_FAIL) naming the ceiling knob. Pre-fix this reds at the base
      budget (TDD signal).
  C1b flock contended, bare holder with NO lease (no observable renewal) ->
      fast honest red at the BASE budget naming the base knob (t260920-01
      guard: the ceiling must not apply to a peer that shows no progress).
  C2  ensure-mutex flock contended, holder legitimately working and releasing
      within the ceiling -> the waiter acquires the lock and proceeds to the
      next gate (dead-docker injection names docker); NO budget/ceiling red.
  C3  booting window (no lock holder, peer lease state=booting):
      C3a heartbeat being RENEWED (observed change, not static freshness) ->
          waiter rides past the base budget to the
          ceiling, exits 2 naming the ceiling knob, and never double-boots
          (peer lease file untouched, holder child unharmed);
      C3b static/stale lease (no observed renewal) while the holder pid is
      still alive -> waiter
          bails FAST at the base budget (regression anchor: the ceiling must
          not apply to a stalled peer).
  C4  flat-window leak regression: with the ceiling knob set very high, the
      daemon probe still honest-reds within the base budget (the extension
      must not leak into kept-flat windows).
  C5  cleanup: locks/leases reclaimable, all injected children reaped, tmp
      lock root removed (tmp hygiene).

Intent split (no intent-level duplication):
  - t260920-01-supply-ensure-wait-cap owns the flat base-budget contract of
    the contended wait (bounded, named, honest red) — this scenario re-uses
    its injection shape but owns the NEW two-tier semantics: which bound
    fires for a working peer vs an unknowable/stalled one.
  - t260920-01-supply-wait-budget-probe owns the daemon-probe window's
    process contract; C4 here only asserts the ceiling does NOT leak into it.
  - Malformed-knob fallback for SANDBAR_STAGE_WORKING_PEER_CEILING_S is a
    pure-function face owned by the developer L1 battery (a fallback to the
    660s default cannot be wall-clock bounded offline), same split as the
    t260920-01 probe scenario made for the budget knob.

Injection: SANDBAR_STAGE_LOCK_DIR -> tmp isolated lock root (never the real
/tmp/sandbar-test-stages); real flock holder children via python subprocesses
(t260920-01 precedent); injected small knobs (base 2s, ceiling 5s) so the
wall clock mechanically distinguishes which bound fired; PATH-prefixed
immediately-failing fake docker pins the "next gate" semantics without a real
daemon. Fully offline, zero docker. No env-fail subcases (contention red is
the behaviour under test, not a missing environment). Red before the fix is
implemented is the expected TDD signal; must be green at arbitrate/merge.

Run: python3 -B integration/t261008-46/sc_supply_working_peer_ceiling.py
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STAGE = REPO / "integration" / "stage_docker.py"

PROJECT = "t26100846-ceiling"
LOCK_NAME = "ensure-%s.lock" % PROJECT
LEASE_NAME = "project-%s.json" % PROJECT
BASE_S = "2"        # SANDBAR_STAGE_WAIT_BUDGET_S (flat base, unchanged contract)
CEILING_S = "5"     # SANDBAR_STAGE_WORKING_PEER_CEILING_S (new, this ticket)
CEILING_KNOB = "SANDBAR_STAGE_WORKING_PEER_CEILING_S"
BASE_KNOB = "SANDBAR_STAGE_WAIT_BUDGET_S"
CLI_TIMEOUT_S = "12"  # --timeout backstop; wall clock separates it from both bounds

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


def base_env(lock_root, extra=None):
    env = dict(os.environ)
    env["SANDBAR_STAGE_LOCK_DIR"] = str(lock_root)
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = BASE_S
    env[CEILING_KNOB] = CEILING_S
    env.update(extra or {})
    return env


def inject_dead_docker(env, lock_root):
    """PATH-prefix an immediately-failing fake docker: the uncontended path's
    NEXT gate (docker presence) is judgeable in seconds on any machine, never
    depending on a real daemon state (t260920-01 precedent)."""
    bindir = lock_root / "fakedocker"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "docker"
    if not fake.exists():
        fake.write_text("#!/bin/sh\necho fake-docker-unavailable >&2\nexit 1\n",
                        encoding="utf-8")
        fake.chmod(0o755)
    env = dict(env)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    return env


def run_stage(args, env, timeout_s=90):
    t0 = time.time()
    p = subprocess.run([sys.executable, str(STAGE)] + args,
                       cwd=str(REPO), capture_output=True, text=True,
                       timeout=timeout_s, env=env)
    return p, time.time() - t0


def run_ensure(lock_root, extra_env=None):
    return run_stage(["ensure", "--project", PROJECT, "--services", "temporal",
                      "--timeout", CLI_TIMEOUT_S],
                     base_env(lock_root, extra_env))


def spawn_holder(lock_root, hold_s, lease_to_release=None):
    """A real flock holder child: takes the ensure lock, prints 'held', sleeps,
    exits by itself (kernel releases the flock on death — t260920-01 shape).
    With lease_to_release, the child also unlinks the project lease before
    exiting — the delivered-winner shape (its boot is over, the lease goes)."""
    src = lock_root / "holder.py"
    src.write_text(
        "import fcntl, os, sys, time\n"
        "f = open(sys.argv[1], 'w')\n"
        "fcntl.flock(f, fcntl.LOCK_EX)\n"
        "print('held', flush=True)\n"
        "time.sleep(float(sys.argv[2]))\n"
        "if sys.argv[3] != '-':\n"
        "    try: os.unlink(sys.argv[3])\n"
        "    except FileNotFoundError: pass\n",
        encoding="utf-8")
    return subprocess.Popen([sys.executable, str(src), str(lock_root / LOCK_NAME),
                             str(hold_s),
                             str(lock_root / lease_to_release) if lease_to_release else "-"],
                            stdout=subprocess.PIPE, text=True)


def spawn_winner(lock_root, hold_s, period_s=0.3):
    """Self-contained winner sim for the C2 face: takes the ensure flock,
    writes a booting lease (its own pid as holder), RENEWS the heartbeat until
    it finishes, then deletes the lease and exits — the delivered-winner shape
    (real winners: hold leg heartbeats; boot over, lease goes). One process,
    so no external heartbeater can resurrect the lease after delivery."""
    src = lock_root / "winner.py"
    src.write_text(
        "import fcntl, json, os, sys, time\n"
        "f = open(sys.argv[1], 'w')\n"
        "fcntl.flock(f, fcntl.LOCK_EX)\n"
        "lease_path = sys.argv[4]\n"
        "now = time.time()\n"
        "lease = {'lease_id': 'winner-%d' % now, 'project': sys.argv[5],\n"
        "         'holder': {'ticket': 't261008-46', 'pid': os.getpid()},\n"
        "         'anchor_pid': None, 'anchor_token': None, 'state': 'booting',\n"
        "         'services': ['temporal'], 'ports': {}, 'subnet': None,\n"
        "         'owner_root': sys.argv[6], 'ts': now, 'heartbeat_ts': now,\n"
        "         'ttl_sec': 2.0}\n"
        "end = now + float(sys.argv[2])\n"
        "print('held', flush=True)\n"
        "while time.time() < end:\n"
        "    lease['heartbeat_ts'] = time.time()\n"
        "    tmp = lease_path + '.w'\n"
        "    open(tmp, 'w').write(json.dumps(lease))\n"
        "    os.replace(tmp, lease_path)\n"
        "    time.sleep(float(sys.argv[3]))\n"
        "try: os.unlink(lease_path)\n"
        "except FileNotFoundError: pass\n",
        encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(src), str(lock_root / LOCK_NAME), str(hold_s),
         str(period_s), str(lock_root / LEASE_NAME), PROJECT, str(REPO)],
        stdout=subprocess.PIPE, text=True)


def spawn_sleeper(lock_root, hold_s):
    """A live process WITHOUT the ensure flock: used as a lease holder pid for
    the booting-window faces (the ensure lock itself must stay free so the
    waiter reaches the _wait_booting window rather than the flock loop)."""
    src = lock_root / "sleeper.py"
    src.write_text("import sys, time\ntime.sleep(float(sys.argv[1]))\n",
                   encoding="utf-8")
    return subprocess.Popen([sys.executable, str(src), str(hold_s)])


def write_lease(lock_root, holder_pid, state, hb_age_s):
    """Fixture helper: a lease record in the product shape (same field set the
    hold leg writes). Setup only — assertions never read this file's internals
    beyond existence/untouchedness."""
    now = time.time()
    lease = {
        "lease_id": "%s-%d-test" % (PROJECT, int(now)),
        "project": PROJECT,
        "holder": {"ticket": "t261008-46", "pid": int(holder_pid)},
        "anchor_pid": None,
        "anchor_token": None,
        "state": state,
        "services": ["temporal"],
        "ports": {},
        "subnet": None,
        "owner_root": str(REPO),
        "ts": now,
        "heartbeat_ts": now - hb_age_s,
        "ttl_sec": 2.0,
    }
    (lock_root / LEASE_NAME).write_text(json.dumps(lease), encoding="utf-8")
    return lease


def spawn_heartbeater(lock_root, period_s=0.3, total_s=15):
    """Keeps the booting lease's heartbeat fresh from a live child process
    (the child's own pid is the lease holder pid — genuinely alive)."""
    src = lock_root / "heartbeater.py"
    src.write_text(
        "import json, os, sys, time\n"
        "p = sys.argv[1]\n"
        "lease = json.load(open(p))\n"
        "lease['holder']['pid'] = os.getpid()\n"
        "end = time.time() + float(sys.argv[2])\n"
        "while time.time() < end:\n"
        "    lease['heartbeat_ts'] = time.time()\n"
        "    tmp = p + '.hb'\n"
        "    open(tmp, 'w').write(json.dumps(lease))\n"
        "    os.replace(tmp, p)\n"
        "    time.sleep(float(sys.argv[3]))\n",
        encoding="utf-8")
    return subprocess.Popen([sys.executable, str(src), str(lock_root / LEASE_NAME),
                             str(total_s), str(period_s)])


lock_root = Path(tempfile.mkdtemp(prefix="t26100846-ceiling-"))
procs = []
try:
    # ---- C1: flock contended, holder RENEWING its booting lease -> ride to ceiling ----
    # (verify gen3 semantics: progress = OBSERVED lease renewal; a bare lock
    # holder with no lease shows no progress and bails at the base budget —
    # that regression face is C1b below.)
    h1 = spawn_holder(lock_root, 30)
    procs.append(h1)
    held = h1.stdout.readline().strip() if h1.stdout else ""
    ok(held == "held" and h1.poll() is None,
       "C0 setup: real holder has the ensure flock (got %r)" % held[:20])
    # The renewing holder needs a lease to renew: write the initial booting
    # lease BEFORE starting the heartbeater (the heartbeater loads the file at
    # startup — without it the child dies instantly and the face degenerates
    # to the bare-lock shape).
    write_lease(lock_root, h1.pid, "booting", hb_age_s=0)
    hb1 = spawn_heartbeater(lock_root)   # holder's lease is being renewed = working
    procs.append(hb1)
    time.sleep(0.6)  # first observed renewal must land inside the base budget
    p1, w1 = run_ensure(lock_root)
    out1 = (p1.stdout or "") + (p1.stderr or "")
    ok(p1.returncode == 2, "C1 contended flock exits 2 honest red (rc=%s)" % p1.returncode)
    ok(w1 >= 4.0, "C1a rides PAST base budget %.0fs (wall=%.1fs — pre-fix reds at %.0fs)"
       % (int(BASE_S), w1, int(BASE_S)))
    ok(w1 <= 9.0, "C1b still bounded by ceiling %.0fs, not CLI timeout %ss (wall=%.1fs)"
       % (int(CEILING_S), CLI_TIMEOUT_S, w1))
    ok(CEILING_KNOB in out1, "C1c red names WHICH bound fired (ceiling knob named)")
    ok(PROJECT in out1, "C1d red names what we waited for (project present)")
    ok(h1.poll() is None, "C1e holder untouched (not killed, lock not stolen)")

    # ---- C1b: bare lock holder, NO lease (no observable renewal) -> BASE red ----
    if h1.poll() is None:
        h1.kill()
        h1.wait(timeout=10)
    if hb1.poll() is None:
        hb1.kill()
        hb1.wait(timeout=10)
    try:
        (lock_root / LEASE_NAME).unlink()
    except FileNotFoundError:
        pass
    h1b = spawn_holder(lock_root, 30)
    procs.append(h1b)
    heldb = h1b.stdout.readline().strip() if h1b.stdout else ""
    ok(heldb == "held", "C1b setup: bare holder has the lock, no lease (got %r)" % heldb[:20])
    p1b, w1b = run_ensure(lock_root)
    out1b = (p1b.stdout or "") + (p1b.stderr or "")
    ok(p1b.returncode == 2, "C1b bare-lock contention exits 2 honest red (rc=%s)" % p1b.returncode)
    ok(w1b <= 4.0, "C1b-1 no progress -> fast bail at BASE %.0fs, ceiling NOT applied "
       "(wall=%.1fs)" % (int(BASE_S), w1b))
    ok(BASE_KNOB in out1b, "C1b-2 base red names the base budget knob (t260920-01 guard)")

    # ---- C2: flock contended, working holder releases in time -> ride through ----
    if h1b.poll() is None:
        h1b.kill()
        h1b.wait(timeout=10)
    h2 = spawn_winner(lock_root, 3)   # delivers (renews + releases) inside the ceiling
    procs.append(h2)
    time.sleep(0.6)  # first renewal must land inside the base budget
    held2 = h2.stdout.readline().strip() if h2.stdout else ""
    ok(held2 == "held", "C2 setup: working holder took the lock (got %r)" % held2[:20])
    p2, w2 = run_ensure(lock_root, extra_env=inject_dead_docker({}, lock_root))
    out2 = (p2.stdout or "") + (p2.stderr or "")
    ok(p2.returncode == 2 and "docker" in out2,
       "C2 working holder: waiter acquires lock and proceeds to next gate "
       "(rc=%s, tail=%s)" % (p2.returncode, out2[-120:].replace("\n", " ")))
    ok(CEILING_KNOB not in out2, "C2b no ceiling red on a delivered boot")
    ok(h2.poll() is not None and h2.returncode == 0,
       "C2c holder finished naturally (returncode=%r)" % h2.returncode)

    # ---- C3a: booting window, heartbeat fresh -> ride to the ceiling ----
    lease_holder = spawn_sleeper(lock_root, 30)
    procs.append(lease_holder)
    write_lease(lock_root, lease_holder.pid, "booting", hb_age_s=0)
    hb = spawn_heartbeater(lock_root)
    procs.append(hb)
    time.sleep(0.6)  # let the heartbeater stamp its pid + first beat
    lease_before = (lock_root / LEASE_NAME).read_text(encoding="utf-8")
    p3, w3 = run_ensure(lock_root, extra_env=inject_dead_docker({}, lock_root))
    out3 = (p3.stdout or "") + (p3.stderr or "")
    ok(p3.returncode == 2, "C3a fresh booting red exits 2 (rc=%s)" % p3.returncode)
    ok(w3 >= 4.0, "C3a-1 fresh boot rides PAST base %.0fs (wall=%.1fs)" % (int(BASE_S), w3))
    ok(CEILING_KNOB in out3, "C3a-2 red names the ceiling bound")
    lease_after = (lock_root / LEASE_NAME).read_text(encoding="utf-8") \
        if (lock_root / LEASE_NAME).exists() else ""
    ok(lease_after != "" and hb.poll() is None,
       "C3a-3 peer lease still present (never reclaimed/double-booted), holder alive")

    # ---- C3b: booting window, heartbeat STALE (holder alive) -> base-budget bail ----
    if hb.poll() is None:
        hb.kill()
        hb.wait(timeout=10)
    stale_holder = spawn_sleeper(lock_root, 30)
    procs.append(stale_holder)
    write_lease(lock_root, stale_holder.pid, "booting", hb_age_s=10)  # ttl 2s -> stale
    try:
        (lock_root / LOCK_NAME).unlink()
    except FileNotFoundError:
        pass
    p4, w4 = run_ensure(lock_root)
    out4 = (p4.stdout or "") + (p4.stderr or "")
    ok(p4.returncode == 2, "C3b stale-heartbeat booting red exits 2 (rc=%s)" % p4.returncode)
    ok(w4 <= 4.0, "C3b-1 fast bail at BASE budget %.0fs, ceiling not applied to a "
       "stalled peer (wall=%.1fs)" % (int(BASE_S), w4))
    ok(stale_holder.poll() is None, "C3b-2 stalled holder untouched")

    # ---- C4: flat-window leak regression (daemon probe) ----
    p5, w5 = run_stage(["daemon-probe"],
                       inject_dead_docker(base_env(lock_root,
                                                   {CEILING_KNOB: "999"}), lock_root))
    ok(p5.returncode == 2, "C4 daemon probe still honest red with a huge ceiling "
       "(rc=%s)" % p5.returncode)
    ok(w5 <= int(BASE_S) + 3, "C4b ceiling knob does NOT leak into the flat window "
       "(wall=%.1fs, base=%ss)" % (w5, BASE_S))

    # ---- C5: cleanup — lock reclaimable, children reaped, tmp root removed ----
finally:
    for pr in procs:
        if pr.poll() is None:
            pr.kill()
            try:
                pr.wait(timeout=10)
            except Exception:
                pass
    reclaimed = False
    try:
        fd = os.open(str(lock_root / LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        reclaimed = True
    except OSError:
        pass
    ok(reclaimed, "C5 lock reclaimable after teardown (no residue holder)")
    shutil.rmtree(lock_root, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
