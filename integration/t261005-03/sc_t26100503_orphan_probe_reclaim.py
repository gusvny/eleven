#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261005-03 scenario ③: reclamation has a home — the orphan probe makes the
count visible and the reclaim path refuses to kill anything that is not an
orphan (clause C, grey-box L3, offline, real child processes, zero docker).

Fixture readiness (t261030-43, the line's last certification blocker): every leg
below asserts about LIVE fixture children, so the fixture must WAIT for that
condition instead of assuming it. Each child announces itself on its own stdout
(`lane-child-ready pid=<pid>`, lib_t26100503.CHILD_READY_MARK) and then holds the
process open until the parent closes its stdin pipe — lifetime is parent-owned,
never a wall clock — and each leg re-checks liveness right before it probes. The
wait is bounded and injectable through the project's `SANDBAR_*_SECS` convention
(`SANDBAR_T26100503_CHILD_READY_SECS`, default 30 s), and its expiry is a NAMED
FAIL carrying the pid and the condition that never became true. Measured race
this replaces: the old child slept 120 s, a loaded round ran this case for 123.9 s
(round run-01M65ZKFPHSTWQ21A2EKD744KX), both children had already retired at the
O3 probe, and the resulting red read `children_alive=False rc=0` — a fixture race
booked as a product defect. The assertion itself is NOT relaxed: a live non-orphan
must still make `--apply` refuse.

User-perceivable contract (261005: 57 lane orphans accumulated for 15 days with
no probe; the hand sweep that finally killed them had to be careful NOT to kill
the resident and live workers):
- O1 `lane-orphans` over a fixture lane root answers with parseable JSON carrying
  a count, and the count is 0 although two REAL live processes with cwd under
  the fixture lane root exist — they have a living parent, so they are not
  orphans: the probe must not count healthy lane processes into the orphan
  family (the count is the number the host reads after terminal/replacement/
  restart events; tonight it read 57);
- O2 the reclaim default is DRY-RUN: running it against those same live children
  exits cleanly and kills NOTHING (every child still alive afterwards);
- O3 even with --apply, a process that fails the guard set (ppid==1 AND cwd
  under the lane root AND own user AND not named by a live worker pidfile) is
  refused, and the refusal names the pid — the tool must never widen into the
  resident/live-worker family the hand sweep protected;
- O4 a nonexistent lane root is refused with a named error (which path), never a
  raw traceback — a probe that crashes is a probe nobody runs.

Intent split: the positive kill path (a true ppid=1 orphan) needs a real
adoption event and belongs to the engine gate; the boot probe wiring and the
end-state zero-count readings are the acceptance-mapping evidence named in the
implementation handover (review condition C3). Subcommands declared by the
approved plan (lane-orphans / lane-reclaim) missing = FAIL named (TDD-phase red
expected; arbitrate/merge must be green). Engine unavailable = ENV_FAIL exit 2.

Run: PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
     integration/t261005-03/sc_t26100503_orphan_probe_reclaim.py  (cwd = repo root)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t26100503 import (  # noqa: E402
    ENGINE, LaneChild, check, env_fail, mk_lane_root, summary,
)

# Gate-host evidence (arbitrate gen3): the probe enumerates every ppid=1
# process with a per-pid cwd probe, so one CLI round takes tens of seconds on a
# real host and exceeded the old 20 s budget under gate concurrency (same commit
# failed at conc_width=3, passed serially). Budgets are per-ROUND ceilings, not
# assertions: generous, with a named FAIL instead of a crash if ever exceeded.
CHILD_STOP_S = 240


def venv_py() -> str:
    p = ENGINE / ".venv" / "bin" / "python"
    return str(p) if p.is_file() and os.access(str(p), os.X_OK) else sys.executable


class CliTimeout(Exception):
    pass


def run_cli(args, timeout=60):
    # L12 discipline (t260930-09 / t261004-26): every ticket-entry spawn goes
    # through the declared cleaning point so an inherited SANDBAR_CALLER_PROJECT
    # or narrowing knob from an outer lane round can never reach the probe face.
    from lib_env import clean_narrowing_env  # noqa: E402  (integration/ on sys.path)
    try:
        return subprocess.run([venv_py(), "-B", str(ENGINE / "client.py")] + args,
                              capture_output=True, text=True, timeout=timeout,
                              cwd=str(HERE.parents[1]), env=clean_narrowing_env())
    except subprocess.TimeoutExpired:
        raise CliTimeout("CLI round exceeded %ss: %s" % (timeout, args[0]))


def cli_supports(sub):
    from lib_env import clean_narrowing_env  # noqa: E402
    r = subprocess.run([venv_py(), "-B", str(ENGINE / "client.py"), "--help"],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(HERE.parents[1]), env=clean_narrowing_env())
    return r.returncode == 0 and sub in r.stdout


def kids_state(kids) -> str:
    """Per-child one-liners (pid, alive/exit code, readiness), so no leg ever
    reports a bare boolean about an anonymous child."""
    return " | ".join(k.state() for k in kids)


def require_alive(kids, leg: str) -> bool:
    """The leg's precondition, checked at the moment the leg probes: the fixture
    children it makes a claim about are alive NOW, each proven by its own ready
    line and by poll(). A child that died mid-case is NAMED (which pid, which
    exit code) instead of hollowing the safety assertion that follows — the
    claim below is still judged, not skipped."""
    dead = [k for k in kids if not k.alive]
    check("%s precondition: fixture children live when the leg probes them" % leg,
          not dead, kids_state(kids))
    return not dead


def main():
    if not (ENGINE / "client.py").is_file():
        env_fail("engine client.py missing under %s" % ENGINE)
    if not (cli_supports("lane-orphans") and cli_supports("lane-reclaim")):
        check("O0 planned reclaim subcommands present", False,
              "lane-orphans/lane-reclaim missing from client.py --help "
              "(pre-implement TDD red expected)")
        summary()
        return

    root = mk_lane_root("orphan")
    kids: list = []
    try:
        # --- F0 the fixture proves its own precondition before any leg runs ---
        # Spawn one child per pidfile shape, each appended only after it exists,
        # so a spawn failure can never leak the sibling that already started.
        for i in range(2):
            try:
                kids.append(LaneChild(root, with_pidfile=(i == 1)))
            except OSError as e:
                # A spawn refusal is a NAMED fixture failure, never an
                # unattributable traceback (same discipline as CliTimeout below).
                check("F0 fixture child %d spawns" % i, False,
                      "spawn failed (%s: %s)" % (type(e).__name__, e))
                summary()
        not_ready = [k for k in kids if not k.ready_ok]
        check("F0 both fixture children announce ready before the legs probe them",
              not not_ready,
              (kids_state(kids) if not not_ready else
               "condition never became true: " + kids_state(not_ready)))
        if not_ready:
            # A fixture whose own precondition never held cannot judge the
            # product: stop here BY NAME instead of booking a product red.
            summary()

        # --- O1 probe counts 0 orphans while healthy lane processes exist ---
        r = run_cli(["lane-orphans", str(root)], timeout=CHILD_STOP_S)
        # Environment gate (B2 named-channel discipline): if the scan face itself
        # cannot run here (sandbox denies ps/lsof), the probe must say so by name —
        # and this scenario must NOT go on to assert counting/safety faces it could
        # not observe (a failed scan must never produce vacuous green). A NAMED
        # denial that does not fake a count keeps the contract half that IS
        # observable; then ENV_FAIL exit 2 (three-state contract: no SKIP).
        probe_blob = r.stdout + r.stderr
        if '"ok": false' in r.stdout and (
                "PermissionError" in probe_blob or "'ps'" in probe_blob
                or "lsof" in probe_blob):
            named = ("ps" in probe_blob or "lsof" in probe_blob) \
                and "Traceback" not in probe_blob
            check("O-env probe names the scan denial (no traceback)", named,
                  "blob=%.200r" % probe_blob)
            print("ENV_FAIL: probe scan face denied by this environment (ps/lsof); "
                  "counting/safety faces not observable here")
            sys.exit(2)
        parsed = None
        try:
            # Tolerant parse (gate-host evidence 261005 gen1: strict
            # json.loads(stdout[first-brace:]) died on trailing stdout after the
            # receipt — "Extra data" turned a good receipt into count=None).
            # Decode the first balanced JSON value; if it carries no receipt keys
            # and more content follows, try the next value too.
            s = r.stdout.strip()
            dec = json.JSONDecoder()
            candidates = []
            rest = s
            for _ in range(3):
                if not rest.lstrip():
                    break
                obj, end = dec.raw_decode(rest.lstrip())
                candidates.append(obj)
                rest = rest.lstrip()[end:]
                if isinstance(obj, dict) and ("result" in obj or "count" in obj):
                    break
            parsed = next((c for c in candidates
                           if isinstance(c, dict) and ("result" in c or "count" in c)),
                          candidates[0] if candidates else None)
        except ValueError:
            parsed = None
        if parsed is None:
            check("O1 probe answers parseable JSON", False,
                  "rc=%d stdout=%.200r stderr=%.200r" % (r.returncode, r.stdout, r.stderr))
        else:
            # Grey-box binding (walkthrough 261005 gen1): the count is a first-class
            # key of the receipt's result payload ("ok":true,"result":{"count":N,…}),
            # not a top-level key of the ok-envelope; read the result level first,
            # keep a top-level fallback for the bare lane_reclaim --json face.
            res = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
            count = res.get("count",
                            parsed.get("count", parsed.get("orphans", parsed.get("total"))))
            check("O1 probe answers parseable JSON with a count",
                  isinstance(count, int), "count=%r keys=%s" % (count, sorted(res)[:8]))
            if isinstance(count, int) and count > 0:
                # Clause C demands the count READ ZERO after the end states. Rows
                # whose own probe failed (lsof/ps errors) are UNPROVABLE, not proven
                # orphans — if those are what the count is made of, the count can
                # never reach 0 on any real host. Name which face failed instead of
                # collapsing both causes into one red.
                rows = res.get("orphans") or parsed.get("orphans") or []
                unprovable = [x for x in rows if x.get("error")]
                check("O1 count is zero on a clean fixture root", False,
                      "count=%d unprovable_rows=%d proven=%d (two live lane-cwd "
                      "children in fixture; unprovable sample=%.160r)"
                      % (count, len(unprovable), count - len(unprovable),
                         (unprovable[0] if unprovable else {})))
            else:
                check("O1 healthy lane processes are NOT counted as orphans",
                      count == 0, "count=%r (two live lane-cwd children in fixture)"
                      % (count,))

        # --- O2 default is dry-run: nothing dies ---
        require_alive(kids, "O2")
        r = run_cli(["lane-reclaim", str(root)], timeout=CHILD_STOP_S)
        if '"ok": false' in r.stdout and (
                "PermissionError" in r.stdout or "'ps'" in r.stdout
                or "lsof" in r.stdout):
            print("ENV_FAIL: reclaim scan face denied by this environment (ps/lsof); "
                  "safety faces not observable here")
            sys.exit(2)
        alive = all(k.alive for k in kids)
        check("O2 dry-run kills nothing", alive,
              "rc=%d children=%s stdout=%.120r stderr=%.120r"
              % (r.returncode, kids_state(kids), r.stdout, r.stderr))

        # --- O3 --apply refuses non-orphans, refusal names the pid ---
        require_alive(kids, "O3")
        r = run_cli(["lane-reclaim", str(root), "--apply"], timeout=CHILD_STOP_S)
        alive = all(k.alive for k in kids)
        named = all(str(k.proc.pid) in (r.stdout + r.stderr) for k in kids)
        check("O3 --apply refuses non-orphans", alive,
              "rc=%d children=%s" % (r.returncode, kids_state(kids)))
        check("O3 refusals name the spared pids", named or not alive,
              "named=%s children=%s stdout=%.120r stderr=%.120r"
              % (named, kids_state(kids), r.stdout, r.stderr))

        # --- O4 nonexistent lane root: named refusal, no traceback ---
        ghost = str(root / "no-such-lane-root")
        r = run_cli(["lane-orphans", ghost], timeout=CHILD_STOP_S)
        blob = r.stdout + r.stderr
        check("O4 nonexistent root refused with a named error",
              ghost in blob and "Traceback" not in blob,
              "rc=%d blob=%.160r" % (r.returncode, blob))
    except CliTimeout as e:
        # A budget blowout is a named FAIL, never an anonymous crash traceback
        # (gate-host gen3 evidence: crash-on-timeout read as an unattributable red).
        check("CLI rounds within budget", False, str(e))
    finally:
        for k in kids:
            k.close()
    summary()


if __name__ == "__main__":
    main()
