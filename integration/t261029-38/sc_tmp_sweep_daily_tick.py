#!/usr/bin/env python3
"""sc_tmp_sweep_daily_tick — the tmp-fixture sweep's daily cadence face (ticket t261029-38, L3 grey-box).

What a user (or the daily inspection reader) can see on this face:

  A  Face selection. Only the daily inspection face ticks. A lane round, a manual run, a nested
     round (depth >= 2), a narrowed round and a disabled config are INERT: exit 0, a named line,
     no state write, no delete. Benign skips are green, so a per-ticket gate is never red by
     construction (host-accepted exit table).
  B  The tick and its receipt (deliverable 1+2). On the inspection face the tick writes one
     receipt pair: a header with mode / absolute root / backlog / delta and the top leaker family
     WITH its repo, and sections that name the sister repo (project-content), the cross-repo leaker
     (project-vision, by name), the excluded families (Chrome, ...) and the uncovered families.
     Report mode is the default and deletes nothing. A second tick inside the due window is a
     named exit-0 skip; --force runs it and the second receipt carries the count delta.
  C  Apply mode routes both guards (deliverable 1). After an explicit enable: an aged unheld
     whitelisted dir is reclaimed, a fresh dir survives (age guard), a dir held open by a live
     process survives and is named (holder guard), the foreign and excluded families survive.
     The holder process is never killed (the runner never passes --kill-carriers). A tick that
     overlaps another tick is a named exit-0 skip with no second receipt and no delete.
  D  Config inputs fail closed and named. A corrupt config, an unknown mode, an age below the
     tool floor and an unusable state dir produce the documented exit codes and delete nothing.
  E  The production face (acceptance item 1, daily inspection round only). The scheduled round
     ticks the host's REAL temp root with the REAL state dir and NO mode flag, so the host's
     config governs. It writes exactly ONE receipt per scheduled round: a forced second tick would
     replace the reader's period delta with a tick-to-tick number and halve the history, so the
     production tick calls must never pass --force (a source lock pins it). The reader face names
     the real root, the backlog, the period delta (a number against the previous scheduled
     receipt, or a named baseline on day one), the top leaker family with its repo and the
     cross-repo project-vision note; a skipped tick is a named N/A, never a stale receipt read as this
     round's proof. Any other round prints one named N/A line and writes nothing.

Intent split (no intent-level duplication):
  - the sweep tool's own CLI safety contract (whitelist x age x flock x cwd-carrier x excluded
    families) is t261002-13-tmp-backlog-sweep-safety; the open-fd holder case lands there;
  - the engine watermark alarm's owner receipt is t261002-13-tmp-alarm-owner-receipt;
  - producer zero residue is t261002-13-tmp-producer-zero-residue;
  - the pure runner faces (round_shape / due / staleness / delta math / malformed state / the
    full M-table) belong to the developer L1 battery
    integration/tests/test_t261029_38_tmp_sweep_receipt.py;
  - THIS entry owns the cadence CLI as a real process on a private root and a private state dir:
    face inertness, the real-face tick receipt, the count delta, the attribution, the apply-mode
    guard routing and the config-error exit codes.

Run directly: python3 integration/t261029-38/sc_tmp_sweep_daily_tick.py   (cwd = repo root)
Three states: PASS = exit 0, FAIL = exit 1, ENV_FAIL = exit 2 (a missing environment, never a
silent skip).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # integration/<ticket>/sc_*.py
PY = sys.executable
CADENCE = ROOT / "integration" / "tools" / "tmp_sweep_cadence.py"
SWEEP = ROOT / "integration" / "tools" / "sweep_tmp_fixtures.py"

PASS = 0
FAIL = 0

#: Shape keys the engine composes around a suite round. The scenario clears them and then sets
#: the exact face under test, so an inherited value can never decide the case.
SHAPE_KEYS = (
    "SANDBAR_INTEG_LEDGER_SOURCE", "SANDBAR_INTEG_LEDGER_OWNER", "SANDBAR_KNOWN_RED_EXCLUDE",
    "INTEG_RUN_DEPTH", "SANDBAR_SCENARIO_ONLY", "SANDBAR_INTEG_RUN_BUDGET_SEC",
    "SANDBAR_TMP_SWEEP_DIR",
)

#: Real composed inspection env (source of truth: server/engine/agent_activities.py
#: `_run_scenarios`, which injects the source, the known-red flag and the budget; verify_lane
#: adds the gate owner). The tick must fire under EXACTLY this shape.
INSPECTION_ENV = {
    "SANDBAR_INTEG_LEDGER_SOURCE": "inspection",
    "SANDBAR_INTEG_LEDGER_OWNER": "gate",
    "SANDBAR_KNOWN_RED_EXCLUDE": "1",
    "INTEG_RUN_DEPTH": "1",
    "SANDBAR_INTEG_RUN_BUDGET_SEC": "5400",
}

#: A per-ticket round, same other keys.
LANE_ENV = {
    "SANDBAR_INTEG_LEDGER_SOURCE": "lane:t261029-38",
    "SANDBAR_INTEG_LEDGER_OWNER": "gate",
    "SANDBAR_KNOWN_RED_EXCLUDE": "1",
    "INTEG_RUN_DEPTH": "1",
}


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def die_env(msg):
    print("ENV_FAIL: " + msg, file=sys.stderr)
    sys.exit(2)


def backdate(p, hours=8.0):
    old = time.time() - hours * 3600.0
    os.utime(p, (old, old))


def base_env(state_dir: Path, home_dir: Path, shape=None):
    env = {k: v for k, v in os.environ.items() if k not in SHAPE_KEYS}
    env["HOME"] = str(home_dir)
    env["SANDBAR_TMP_SWEEP_DIR"] = str(state_dir)
    env.update(shape or {})
    return env


#: The production state dir — the reader face a person opens on the host.
PROD_STATE = Path(os.path.expanduser("~")) / ".sandbar" / "tmp-sweep"


def prod_env():
    """The caller's own environment with the private-box knob removed.

    No `--root` and no `--state-dir` are passed with this env: the tick runs on the host's real
    temp root and the real state dir, which is the face acceptance item 1 asks for. No mode flag is
    passed either: the host's config governs (report by default, apply only after
    `enable --mode apply`), so this face can never silently override the host's choice.
    """
    env = {k: v for k, v in os.environ.items() if k != "SANDBAR_TMP_SWEEP_DIR"}
    env["HOME"] = os.path.expanduser("~")
    return env


# SANCTIONED-WAIT: a hard-kill ceiling only; the scenario asserts the exit and never waits it.
def run_cadence(args, env, timeout=180):
    return subprocess.run([PY, str(CADENCE)] + list(args), cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=timeout)


def receipts(state_dir: Path):
    return sorted(glob.glob(str(state_dir / "receipts" / "*.json")))


def newest_receipt_text(state_dir: Path):
    md = state_dir / "latest.md"
    return md.read_text(encoding="utf-8") if md.is_file() else ""


def newest_json(state_dir: Path):
    files = receipts(state_dir)
    if not files:
        return {}
    try:
        return json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def seed_root(root: Path, *, held=False, include_foreign=True, include_excluded=True):
    """Seed a private sweep root with the families this face must tell apart."""
    (root / "integ-e2e-fixture-a").mkdir(parents=True)
    (root / "integ-e2e-fixture-a" / "nested").mkdir()
    (root / "integ-e2e-fixture-b").mkdir()
    (root / "integ-e2e-fixture-c").mkdir()
    (root / "integ-e2e-fixture-fresh").mkdir()          # fresh: age guard
    (root / "project-content-integ-run-x.lock").write_text("lock")
    (root / "notes-gate-abcd1234").mkdir()              # uncovered family
    for p in (root / "integ-e2e-fixture-a", root / "integ-e2e-fixture-a" / "nested",
              root / "integ-e2e-fixture-b", root / "integ-e2e-fixture-c",
              root / "project-content-integ-run-x.lock", root / "notes-gate-abcd1234"):
        backdate(p)
    if include_foreign:
        (root / "t26101406-gate-abc123").mkdir()
        backdate(root / "t26101406-gate-abc123")
    if include_excluded:
        (root / "com.google.Chrome.aged").mkdir()
        backdate(root / "com.google.Chrome.aged")
    child = None
    if held:
        held_dir = root / "integ-e2e-fixture-held"
        held_dir.mkdir()
        (held_dir / "held.txt").write_text("x")
        backdate(held_dir)
        child = subprocess.Popen(
            [PY, "-c",
             "import sys,time\n"
             "f=open(sys.argv[1],'r')\n"
             "print('open',flush=True)\n"
             # SANCTIONED-WAIT: ceiling only; one readline proves the open fd, then stop() reaps it.
             "time.sleep(180)\n", str(held_dir / "held.txt")],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            child.stdout.readline()
        except Exception:  # pragma: no cover - defensive
            pass
    return child


def stop(child):
    if child is None:
        return
    try:
        child.terminate()
        child.wait(timeout=15)
    except Exception:  # pragma: no cover - defensive
        try:
            child.kill()
        except Exception:
            pass


def main():
    for path, what in ((CADENCE, "cadence runner"), (SWEEP, "sweep tool")):
        if not path.is_file():
            print("FAIL missing face: %s (%s) — pre-implement red is the TDD signal" % (what, path))
            print("PASS=%d FAIL=%d" % (0, 1))
            return 1
    for tool in ("lsof", "pgrep"):
        if shutil.which(tool) is None:
            die_env("%s is required for the holder-guard case" % tool)
    try:
        import fcntl  # noqa: F401
    except ImportError:
        die_env("fcntl unavailable (the runner's single-flight lock cannot run)")

    sys.path.insert(0, str(ROOT / "integration"))
    import lib_tmp_reclaim as lr  # noqa: E402

    boxes = []

    def box(prefix):
        parent = ROOT / "out"                      # gitignored scratch (never the host temp root,
        parent.mkdir(exist_ok=True)                # so the production tick cannot see these boxes)
        p = Path(lr.mkdtemp_reclaimed(prefix, str(parent)))
        boxes.append(p)
        (p / "home").mkdir(exist_ok=True)
        (p / "state").mkdir(exist_ok=True)
        return p

    try:
        # ---------------------------------------------------------------- A: face inertness
        print("A face inertness (exit 0, named, no state write, no delete)")
        a = box("t261029-38-a-")
        aroot = a / "root"
        aroot.mkdir()
        seed_root(aroot, include_foreign=False, include_excluded=False)
        inert_shapes = [
            ("A1 lane round", dict(LANE_ENV), []),
            ("A2 manual run", {}, []),
            ("A3 deep round", dict(INSPECTION_ENV, INTEG_RUN_DEPTH="2"), []),
            ("A4 narrowed round", dict(INSPECTION_ENV, SANDBAR_SCENARIO_ONLY="x"), []),
        ]
        for label, shape, extra in inert_shapes:
            r = run_cadence(["tick", "--root", str(aroot), "--state-dir", str(a / "state")]
                            + extra, base_env(a / "state", a / "home", shape))
            out = (r.stdout + r.stderr).lower()
            ok(r.returncode == 0, "%s: exit 0 (got %s)" % (label, r.returncode))
            ok(any(w in out for w in ("inert", "skipped", "manual", "lane", "depth", "narrow")),
               "%s: names why it did not tick" % label)
            ok(not [p for p in (a / "state").rglob("*") if p.is_file()],
               "%s: no state write" % label)
            ok((aroot / "integ-e2e-fixture-a").exists(),
               "%s: nothing deleted" % label)
        r = run_cadence(["disable"],
                        base_env(a / "state", a / "home", INSPECTION_ENV))
        ok(r.returncode == 0, "A5 disable returns 0")
        r = run_cadence(["tick", "--root", str(aroot), "--state-dir", str(a / "state")],
                        base_env(a / "state", a / "home", INSPECTION_ENV))
        ok(r.returncode == 0, "A5 disabled: exit 0 (got %s)" % r.returncode)
        ok("disabled" in (r.stdout + r.stderr).lower(), "A5 disabled: names it")
        ok((aroot / "integ-e2e-fixture-a").exists(), "A5 disabled: nothing deleted")

        # ---------------------------------------------------------------- B: the real-face tick
        print("B inspection face, report mode: receipt, delta, attribution")
        b = box("t261029-38-b-")
        broot, bstate = b / "root", b / "state"
        broot.mkdir()
        holder = seed_root(broot, held=True)
        try:
            r = run_cadence(["tick", "--root", str(broot), "--state-dir", str(bstate)],
                            base_env(bstate, b / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "B1 inspection tick exits 0 (got %s: %s)"
               % (r.returncode, (r.stdout + r.stderr)[-300:]))
            md = newest_receipt_text(bstate)
            ok(bool(md), "B2 receipt written (latest.md present)")
            ok(len(receipts(bstate)) == 1, "B2b exactly one machine receipt on the first run")
            ok("mode=report" in md or "mode: report" in md, "B3 header names report mode")
            ok(str(broot.resolve()) in md, "B4 header carries the absolute realpath root")
            ok("top leaker" in md.lower(), "B5 receipt names a top leaker family")
            ok("integ-e2e-fixture-" in md, "B5b top leaker prefix is this repo's family")
            ok("sandbar" in md, "B5c the family row carries its repo (sandbar)")
            ok(("baseline" in md.lower()) or ("no_previous" in md),
               "B6 first receipt is a baseline, not a fake delta")
            ok("project-vision" in md, "B7 cross-repo leaker named by repo")
            ok("sc_fpv_part_intake" in md, "B7b cross-repo note names the producer scenarios")
            ok("t26101406-gate-" in md, "B7c cross-repo note names the prefix")
            ok("com.google.Chrome." in md and "chrome" in md.lower(),
               "B8 excluded family named with its owner")
            ok("notes-gate" in md and "unknown" in md.lower(),
               "B9 uncovered family named, owner explicitly unknown")
            ok("integ-e2e-fixture-held" in md, "B10 live holder named in the receipt")
            ok(holder is not None and holder.poll() is None,
               "B11 report mode never kills the holder process")
            ok((broot / "integ-e2e-fixture-a").exists()
               and (broot / "integ-e2e-fixture-fresh").exists(),
               "B12 report mode deletes nothing")
            nun_line = next((ln for ln in md.splitlines() if "project-content-integ-run-" in ln), "")
            ok(bool(nun_line) and "sandbar" not in nun_line.lower(),
               "B13 sister-repo family is not attributed to this repo")
            j = newest_json(bstate)
            ok(str(j.get("root", "")).startswith("/"), "B14 machine receipt carries an absolute root")
            ok(str(j.get("mode", "")).lower() == "report", "B14b machine receipt names report mode")
            ok(any(isinstance(j.get(k), int) for k in ("swept", "swept_this_tick")),
               "B14c machine receipt carries a numeric swept count")

            # delta: add one aged whitelisted family member inside the due window, force a tick
            (broot / "integ-e2e-fixture-d").mkdir()
            backdate(broot / "integ-e2e-fixture-d")
            r = run_cadence(["tick", "--root", str(broot), "--state-dir", str(bstate), "--force"],
                            base_env(bstate, b / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "B15 forced second tick exits 0 (got %s)" % r.returncode)
            md2 = newest_receipt_text(bstate)
            ok(len(receipts(bstate)) == 2, "B15b second tick wrote a second receipt")
            ok(("\u0394" in md2) or ("delta" in md2.lower()),
               "B16 second receipt carries the count delta")

            # due gate: a plain tick now is inside the window -> named exit-0 skip
            r = run_cadence(["tick", "--root", str(broot), "--state-dir", str(bstate)],
                            base_env(bstate, b / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "B17 due-gated tick exits 0 (got %s)" % r.returncode)
            ok(len(receipts(bstate)) == 2, "B17b due-gated tick wrote no receipt")
            ok(any(w in (r.stdout + r.stderr).lower() for w in ("due", "window", "inside the window", "skipped")),
               "B17c due-window reason is named")

            # reader faces
            r = run_cadence(["status"],
                            base_env(bstate, b / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "B18 status exits 0")
            ok("report" in (r.stdout + r.stderr).lower(), "B18b status names the mode")
            ok(str(bstate) in (r.stdout + r.stderr), "B18c status names the state/receipt path")
            r = run_cadence(["report"],
                            base_env(bstate, b / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "B19 report exits 0")
            ok("top leaker" in (r.stdout + r.stderr).lower() or "project-vision" in (r.stdout + r.stderr),
               "B19b report prints the receipt content")
        finally:
            stop(holder)

        # ------------------------------------------------- C: the config governs + both guards
        # Defect class this pins (arbitration gen3): a scheduled call that passes `--mode` silently
        # defeats the host's `enable --mode apply`. The schedule must carry NO mode flag, and the
        # stored config decides: report -> nothing deleted, apply -> bounded delete.
        print("C config-governed mode: report keeps, apply deletes, both guards hold")
        src_text = Path(__file__).read_text(encoding="utf-8")
        tick_calls = [ln for ln in src_text.splitlines() if 'run_cadence(["tick"' in ln]
        ok(bool(tick_calls) and all('"--mode"' not in ln for ln in tick_calls),
           "C0 no tick call passes --mode (%d calls) — the host's enable governs the schedule"
           % len(tick_calls))
        c = box("t261029-38-c-")
        croot, cstate = c / "root", c / "state"
        croot.mkdir()
        cholder = seed_root(croot, held=True)
        try:
            r = run_cadence(["enable", "--mode", "report"],
                            base_env(cstate, c / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "C1a enable --mode report exits 0 (got %s)" % r.returncode)
            r = run_cadence(["tick", "--root", str(croot), "--state-dir", str(cstate)],
                            base_env(cstate, c / "home", INSPECTION_ENV))
            ok(r.returncode == 0 and (croot / "integ-e2e-fixture-a").exists(),
               "C1b a report config deletes nothing (the config governs, not a flag)")
            r = run_cadence(["enable", "--mode", "apply"],
                            base_env(cstate, c / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "C1 enable --mode apply exits 0 (got %s: %s)"
               % (r.returncode, (r.stdout + r.stderr)[-200:]))
            ok((cstate / "config.json").is_file(), "C1c enable wrote the config into the state dir")
            # --force only bypasses the 20 h due window (the report tick above consumed it);
            # the mode still comes from the config, which is the point of this section.
            r = run_cadence(["tick", "--root", str(croot), "--state-dir", str(cstate), "--force"],
                            base_env(cstate, c / "home", INSPECTION_ENV))
            ok(r.returncode == 0, "C2 apply tick exits 0 (got %s: %s)"
               % (r.returncode, (r.stdout + r.stderr)[-300:]))
            ok(not (croot / "integ-e2e-fixture-a").exists(),
               "C3 aged unheld whitelisted dir reclaimed")
            ok((croot / "integ-e2e-fixture-fresh").exists(),
               "C4 age guard: fresh whitelisted dir survives")
            ok((croot / "integ-e2e-fixture-held").exists(),
               "C5 holder guard: dir held open survives")
            ok(cholder is not None and cholder.poll() is None,
               "C6 the holder process is still alive (runner never --kill-carriers)")
            ok((croot / "t26101406-gate-abc123").exists(),
               "C7 foreign (cross-repo) dir survives: counted, never swept")
            ok((croot / "com.google.Chrome.aged").exists(),
               "C8 excluded family survives")
            md = newest_receipt_text(cstate)
            ok("mode=apply" in md or "mode: apply" in md, "C9 receipt names apply mode")
            ok("integ-e2e-fixture-held" in md, "C10 kept holder named in the apply receipt")
            j = newest_json(cstate)
            swept = j.get("swept", j.get("swept_this_tick"))
            ok(isinstance(swept, int) and swept >= 1, "C11 receipt reports what it swept")
        finally:
            stop(cholder)

        # ---------------------------------- C12-C16: two ticks at once (single-flight lock)
        # Failure surface a scheduler makes real: the daily tick and a human tick overlap. The
        # reader must see ONE report and no delete, with a named skip on the second caller. The
        # case holds the state-dir lock from a real child process, then ticks; it asserts the
        # public face only (exit 0, the named reason, no new receipt, nothing deleted) and then
        # proves the skip was contention by ticking again after the holder is stopped.
        lockdir = croot / "integ-e2e-fixture-lock"
        lockdir.mkdir()
        backdate(lockdir, 8.0)
        n_before = len(receipts(cstate))
        ready = c / "lock-ready"
        locker = subprocess.Popen(
            [PY, "-c",
             "import fcntl, os, sys, time\n"
             "p, ready = sys.argv[1], sys.argv[2]\n"
             "os.makedirs(os.path.dirname(p), exist_ok=True)\n"
             "fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o644)\n"
             "fcntl.flock(fd, fcntl.LOCK_EX)\n"
             "open(ready, 'w', encoding='utf-8').write('locked')\n"
             "time.sleep(120)\n",   # SANCTIONED-WAIT: the lock-holder child's own ceiling; the case polls the ready file and never waits this long
             str(cstate / "lock"), str(ready)],
            env=base_env(cstate, c / "home", INSPECTION_ENV),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 20.0
            while time.time() < deadline and not ready.exists() and locker.poll() is None:
                time.sleep(0.05)
            ok(ready.exists(), "C12 a second process holds the state-dir lock (contention face armed)")
            r = run_cadence(["tick", "--root", str(croot), "--state-dir", str(cstate), "--force"],
                            base_env(cstate, c / "home", INSPECTION_ENV))
            ok(r.returncode == 0,
               "C13 a tick blocked by a held lock is a named skip, never an error (got %s)"
               % r.returncode)
            ok("lock-held" in (r.stdout + r.stderr), "C13b the skip names lock-held")
            ok(len(receipts(cstate)) == n_before,
               "C14 the blocked tick wrote no receipt (one report per round)")
            ok(lockdir.exists(), "C15 the blocked tick deleted nothing")
        finally:
            stop(locker)
        r = run_cadence(["tick", "--root", str(croot), "--state-dir", str(cstate), "--force"],
                        base_env(cstate, c / "home", INSPECTION_ENV))
        ok(r.returncode == 0 and len(receipts(cstate)) == n_before + 1,
           "C16 after the holder stops the next tick proceeds (the skip was contention, not a "
           "broken tick)")

        # ---------------------------------------------------------------- D: config inputs
        print("D config inputs fail closed and named")
        d = box("t261029-38-d-")
        droot, dstate = d / "root", d / "state"
        droot.mkdir()
        seed_root(droot, include_foreign=False, include_excluded=False)
        (dstate / "config.json").write_text('{"mode": "apply"', encoding="utf-8")
        r = run_cadence(["tick", "--root", str(droot), "--state-dir", str(dstate)],
                        base_env(dstate, d / "home", INSPECTION_ENV))
        ok(r.returncode == 8, "D1 corrupt config -> exit 8 (got %s)" % r.returncode)
        ok("config" in (r.stdout + r.stderr).lower(), "D1b names the config")
        ok((droot / "integ-e2e-fixture-a").exists(), "D1c corrupt config deletes nothing")

        (dstate / "config.json").write_text('{"mode": "wipe"}', encoding="utf-8")
        r = run_cadence(["tick", "--root", str(droot), "--state-dir", str(dstate)],
                        base_env(dstate, d / "home", INSPECTION_ENV))
        ok(r.returncode == 8, "D2 unknown mode -> exit 8 (got %s)" % r.returncode)
        ok("wipe" in (r.stdout + r.stderr), "D2b names the unknown mode")
        ok((droot / "integ-e2e-fixture-a").exists(), "D2c nothing deleted")

        (dstate / "config.json").write_text('{"mode": "apply", "max_age_h": 0.5}',
                                           encoding="utf-8")
        r = run_cadence(["tick", "--root", str(droot), "--state-dir", str(dstate)],
                        base_env(dstate, d / "home", INSPECTION_ENV))
        ok(r.returncode == 8, "D3 age below the tool floor -> exit 8 (got %s)" % r.returncode)
        ok((droot / "integ-e2e-fixture-a").exists(), "D3b nothing deleted")

        bad_state = d / "state-is-a-file"
        bad_state.write_text("x", encoding="utf-8")
        r = run_cadence(["tick", "--root", str(droot), "--state-dir", str(bad_state)],
                        base_env(bad_state, d / "home", INSPECTION_ENV))
        ok(r.returncode == 5, "D4 unusable state dir -> exit 5 (got %s)" % r.returncode)
        ok("state" in (r.stdout + r.stderr).lower(), "D4b names the state failure")

        # ------------------------------------------------- E: the production face (real root)
        # Every case above proves the mechanism inside a private box. Acceptance item 1 needs the
        # real thing — but only the DAILY inspection round may touch it: a per-ticket gate round
        # (lane shape) or a human full run must stay inert, or every gate would rewrite the
        # production state dir. No `--mode` is passed: the host's config governs.
        print("E the production face (daily inspection round only): real root, real state dir")
        sys.path.insert(0, str(ROOT / "integration" / "tools"))
        import tmp_sweep_cadence as cad_e  # noqa: E402
        inert_why = cad_e.inert_reason()
        if inert_why:
            print("  N/A  E0 production face skipped: this round is not the daily inspection "
                  "face (%s)" % inert_why)
        else:
            penv = prod_env()
            prod_root = os.path.realpath(os.environ.get("TMPDIR") or "/tmp")
            # Causality and the reader face: capture what the state dir held BEFORE the scheduled
            # tick. A skipped tick (due gate / lock) must never be read as this round's receipt,
            # and the daily delta must not be replaced by a tick-to-tick delta from a forced
            # second tick (arbitration gen5: acceptance D1'').
            receipts_dir = PROD_STATE / "receipts"
            before_receipts = {str(p) for p in receipts_dir.glob("*.json")} if receipts_dir.is_dir() else set()
            js_path = PROD_STATE / "latest.json"
            md_path = PROD_STATE / "latest.md"
            latest_before = js_path.stat().st_mtime if js_path.is_file() else 0.0
            hist = PROD_STATE / "history.jsonl"
            hist_before = len(hist.read_text(encoding="utf-8").splitlines()) if hist.is_file() else 0
            # A hard-kill ceiling for one real scan of the host temp root (measured 15 s; the
            # call returns as soon as the tick finishes), not a sleep.
            r = run_cadence(["tick"], penv,  # SANCTIONED-WAIT: one real temp-root scan; the call returns when the tick finishes
                            timeout=120)
            out = (r.stdout + r.stderr)
            if r.returncode == cad_e.EXIT_WRITE:
                die_env("the production state dir is not writable (%s): %s"
                        % (PROD_STATE, out.strip()[-200:]))
            ok(r.returncode == 0, "E1 the daily face ticks the real root (got %s: %s)"
               % (r.returncode, out.strip()[-300:]))
            after_receipts = {str(p) for p in receipts_dir.glob("*.json")} if receipts_dir.is_dir() else set()
            new_receipts = sorted(after_receipts - before_receipts)
            if not new_receipts:
                print("  N/A  E2-E13 no new receipt this round (a named skip: %s) — the reader "
                      "face is not overwritten and no stale receipt is read as this round's proof"
                      % (" | ".join(ln.strip() for ln in out.strip().splitlines()[-2:])[:300]))
            else:
                ok(len(new_receipts) == 1,
                   "E2 exactly one receipt per scheduled round (a forced second tick would "
                   "replace the daily delta and halve the history)")
                ok(js_path.is_file() and md_path.is_file(),
                   "E2b the production receipt pair exists (%s)" % md_path)
                ok(js_path.is_file() and js_path.stat().st_mtime > latest_before,
                   "E3 the reader face was written by this round (not a stale file)")
                md = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
                try:
                    j = json.loads(js_path.read_text(encoding="utf-8")) if js_path.is_file() else {}
                except ValueError:
                    j = {}
                mode = str(j.get("mode") or "")
                ok(mode in ("report", "apply"),
                   "E4 the production receipt names the host-config mode (got %r)" % mode)
                ok(str(prod_root) in md,
                   "E5 the receipt names the REAL temp root (%s)" % prod_root)
                ok("backlog=" in md, "E5b the receipt carries the backlog count")
                ok(str(j.get("root", "")) == prod_root,
                   "E5c the machine receipt root is the real temp root")
                ok(("\u0394" in md) or ("delta=" in md) or ("baseline" in md.lower()),
                   "E6 the receipt carries a delta word (a number or the named baseline)")
                ok("top leaker" in md.lower(), "E7 the receipt names a top leaker family")
                ok(bool(j.get("top_leakers")) or "none" in md.lower(),
                   "E7b the top-leaker section is decided, never blank")
                ok("project-vision" in md and "sc_fpv_part_intake" in md,
                   "E8 the receipt records the cross-repo leaker by name")
                if mode == "report":
                    ok(int((j.get("counts") or {}).get("swept") or 0) == 0,
                       "E9 report mode deleted nothing on the real root")
                else:
                    flags = j.get("flags") or {}
                    ok(flags.get("kill_carriers") is False
                       and float(j.get("max_age_h") or 0.0) >= 1.0,
                       "E9 apply mode ran behind both guards (age gate >= 1 h, never "
                       "--kill-carriers)")
                # The reader's delta is the PERIOD delta: against the previous scheduled receipt,
                # or a named baseline on day one. A forced second tick must never replace it.
                delta = j.get("delta") or {}
                if delta.get("basis") == "previous":
                    ok(isinstance((delta.get("whitelisted") or {}).get("delta"), int),
                       "E10 the reader receipt carries the period delta (numeric, previous basis)")
                elif delta.get("reason") == "no_previous":
                    print("  N/A  E10 day one has no previous receipt (named baseline) — the "
                          "period delta starts with the next scheduled round")
                elif delta.get("reason") in ("root_changed", "unreadable_previous"):
                    print("  N/A  E10 baseline (%s) — the previous receipt is not comparable"
                          % delta.get("reason"))
                else:
                    ok(False, "E10 the period delta is decided (got %r)" % (delta,))
                hist_now = len(hist.read_text(encoding="utf-8").splitlines()) if hist.is_file() else 0
                ok(hist_now > hist_before,
                   "E11 the production history log gained this round's row")
                ok(str(PROD_STATE) in md, "E12 the receipt names its own state dir")
        # The source lock: the production-face tick calls (no --root) must never carry --force.
        # A forced second production tick replaces the reader's period delta (acceptance D1'').
        prod_ticks = [ln for ln in (Path(__file__).read_text(encoding="utf-8").splitlines())
                      if 'run_cadence(["tick"' in ln and "--root" not in ln]
        ok(bool(prod_ticks) and all('"--force"' not in ln for ln in prod_ticks),
           "E13 no production tick call passes --force (%d calls)" % len(prod_ticks))
    finally:
        for p in boxes:
            lr.reclaim_registered()
            shutil.rmtree(p, ignore_errors=True)

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
