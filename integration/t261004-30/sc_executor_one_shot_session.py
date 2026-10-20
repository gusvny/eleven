#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_executor_one_shot_session.py — one-shot executor session contract scenario
(t261004-30, grey-box L2/L3, integration-role asset).

intent (what it verifies — user-perceivable promises from the ticket, not
implementation details)
    Bounded small work must not queue behind the resident session's long turn.
    The perceivable contract, locked here end to end:
      - PER-OBJECT lock: the same ticket / request / alert key never has two
        one-shot sessions at once; different objects run in parallel;
      - the parallel cap is ONE setting — the project concurrency declaration;
        changing that one value changes the cap (no second knob exists);
      - a lock is released on EVERY exit path (normal / error / timeout /
        cancel); an abnormal exit is reclaimed by timeout;
      - short sessions never talk to the human: their questions are request
        rows, their writes pass the SAME executor grant gate (fail-closed with
        named reasons), and their output lands in the settle note + action
        ledger (channel_kind=one_shot is additive and readers stay tolerant);
      - retention: 7 days, a one-page summary before deletion, and a session
        still referenced (watchdog config / authorization declaration /
        unanswered request owner) is never deleted.
    Design source: notes/discussions/261004-executor-short-session-wake-design.md.
    Intent split vs existing coverage: wake DELIVERY mechanics belong to
    t260929-04 entries (sc_wake_*); the three-state executor ledger counters
    belong to t260904-12; the executor grant-gate matrix belongs to
    t260911-20/sc_executor_authority_gate — none of those lock object-keyed
    exclusivity, the single-knob cap, exit-path release, or retention with
    reference protection. This entry owns those.

high-level steps (how it reaches and asserts)
    W1-W6  watchdog one-shot core through the fixture harness (one-JSON-per-
           line stdin/stdout protocol, injected clock, tmp isolation — same
           seam as lib_watchdog_harness). New protocol commands declared here
           (implement lands them in server/plugins/watchdog/harness.mjs):
             oneshot_admit {project, unit, limit, now}      -> {ok, reason?}
             oneshot_release {project, object_key, mode}    -> {ok}  (mode in
               normal|error|timeout|cancel)
             oneshot_reclaim {project, object_key, now}     -> {ok, reclaimed}
             oneshot_config {project, one_shot}             -> {ok}  (sets the
               one_shot config block; unknown keys must be refused)
             oneshot_reap {project, now, retention_days, references,
                           summarize_fail}                  -> {ok, deleted,
               summaries, skipped}
    E1-E4  engine face with REAL files in a tmp projects root: settle CLI
           happy path (settle-note row appended, append-only), gate fail-
           closed for an undeclared session (zero rows), malformed argv
           (exit 2, {field, error}), and additive channel_kind tolerance on
           the action-ledger reader path.
    Final line SUMMARY pass=N fail=M env_fail=K na=J; fail>0 -> exit 1;
    missing environment -> exit 2 (never a silent green).

Three-state: node missing = ENV_FAIL exit 2; harness protocol command / one
shot module / settle CLI not landed = FAIL exit 1 naming what is absent
(TDD-phase red is expected; arbitrate/merge must be green).
Run directly: python3 integration/t261004-30/sc_executor_one_shot_session.py
(cwd = repo root).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration" / "t260928-28"))
from lib_watchdog_harness import Harness  # noqa: E402

ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE))

# lib_watchdog_harness counts legs into its own module globals (its ok()).
import lib_watchdog_harness as _wd  # noqa: E402

ok = _wd.ok  # watchdog legs count into the shared module's counters
SETTLE_CLI = ENGINE / "executor_oneshot.py"

passed = failed = env_failed = na = 0  # engine-leg counters


def pok(cond, label, detail=""):
    """ok() for engine-side legs (local counters)."""
    global passed, failed
    if cond:
        passed += 1
        print("  ok   %s" % label)
    else:
        failed += 1
        print("  FAIL %s %s" % (label, str(detail)[:300]))


# ---------------------------------------------------------------------------
# engine-side fixture: a tmp projects root with a declared executor session
# ---------------------------------------------------------------------------

def engine_env(tmp_root: pathlib.Path, project: str, declare_session: str = "") -> dict:
    proj = tmp_root / "projects" / project
    (proj / "ledger").mkdir(parents=True, exist_ok=True)
    if declare_session:
        decl = proj / "executor_sessions.json"
        decl.write_text(json.dumps(
            {"sessions": [{"id": declare_session, "kind": "one_shot"}]}),
            encoding="utf-8")
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(tmp_root / "projects")
    env["PYTHONPATH"] = str(ENGINE) + os.pathsep + env.get("PYTHONPATH", "")
    return env


# ---------------------------------------------------------------------------
# W legs — watchdog one-shot core through the harness
# ---------------------------------------------------------------------------

def watchdog_legs(h: Harness) -> None:
    P = "alpha"

    # W1 — per-object exclusivity (the ticket's core promise)
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-1"},
              limit=9, now=1_000)
    ok(r.get("ok"), "W1 first admit of ticket:t-1 accepted", r)
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-1"},
              limit=9, now=1_010)
    ok(not r.get("ok") and "lock" in json.dumps(r).lower(),
       "W1 second concurrent admit of the SAME object refused, reason names the lock", r)
    for unit in ({"kind": "ticket", "id": "t-2"},
                 {"kind": "request", "id": "r-9"},
                 {"kind": "alert", "key": "k-1"}):
        r = h.cmd("oneshot_admit", project=P, unit=unit, limit=9, now=1_020)
        ok(r.get("ok"), "W1 different object %s admitted in parallel" % json.dumps(unit), r)
    h.cmd("oneshot_release", project=P, object_key="ticket:t-1", mode="normal")
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-1"},
              limit=9, now=1_030)
    ok(r.get("ok"), "W1 object free again after release", r)
    # fixture bookkeeping: retire the W1 leftover locks so the W3 cap legs
    # count from exactly one live session (alert k-1 stays held) -- otherwise
    # the "five fit under 5 / sixth refused" arithmetic cannot be reached.
    for gone in ("ticket:t-1", "ticket:t-2", "request:r-9"):
        h.cmd("oneshot_release", project=P, object_key=gone, mode="normal")

    # W2/W3 — the cap is ONE setting: the project concurrency declaration
    for unit in ({"kind": "ticket", "id": "t-3"},
                 {"kind": "ticket", "id": "t-4"},
                 {"kind": "ticket", "id": "t-5"}):
        h.cmd("oneshot_admit", project=P, unit=unit, limit=5, now=2_000)
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-6"},
              limit=5, now=2_010)
    ok(r.get("ok"), "W3 five active one-shot sessions fit under limit=5", r)
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-7"},
              limit=5, now=2_020)
    ok(not r.get("ok") and "cap" in json.dumps(r).lower(),
       "W3 sixth admit refused, reason names the cap", r)
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-7"},
              limit=6, now=2_030)
    ok(r.get("ok"),
       "W3 raising THE SAME single declaration to 6 admits — no second knob", r)
    h.cmd("oneshot_release", project=P, object_key="ticket:t-7", mode="normal")
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "t-8"},
              limit=0, now=2_040)
    ok(r.get("ok"), "W3 limit=0 means unlimited (declared form supported)", r)

    # W3b — the one_shot config block carries no cap and fails closed on
    # unknown keys (a cap hiding in the watchdog config = second knob = red)
    r = h.cmd("oneshot_config", project=P,
              one_shot={"enabled": True, "retention_days": 7,
                        "lock_timeout_ms": 1800000})
    ok(r.get("ok"), "W3b one_shot block with factory keys accepted", r)
    r = h.cmd("oneshot_config", project=P,
              one_shot={"enabled": True, "retention_days": 7,
                        "lock_timeout_ms": 1800000, "parallel_cap": 4})
    ok(not r.get("ok"), "W3b a parallel_cap key inside one_shot config is refused "
                        "(fail closed — the cap lives only in the shared declaration)", r)

    # W4 — every exit mode releases the lock
    for i, mode in enumerate(("normal", "error", "timeout", "cancel")):
        key = "ticket:exit-%d" % i
        r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "exit-%d" % i},
                  limit=9, now=3_000 + i)
        ok(r.get("ok"), "W4 admit before %s exit (%s)" % (mode, key), r)
        h.cmd("oneshot_release", project=P, object_key=key, mode=mode)
        r = h.cmd("oneshot_admit", project=P,
                  unit={"kind": "ticket", "id": "exit-%d" % i}, limit=9, now=3_050 + i)
        ok(r.get("ok"), "W4 lock released after %s exit (re-admit succeeds)" % mode, r)
        # fixture bookkeeping: retire the re-admitted lock so the section's
        # own re-admits do not consume the cap the later legs count on
        h.cmd("oneshot_release", project=P, object_key=key, mode="normal")

    # W5 — stale-lock reclaim by timeout
    h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "stale"},
          limit=9, now=4_000)
    h.cmd("oneshot_config", project=P,
          one_shot={"enabled": True, "retention_days": 7, "lock_timeout_ms": 600_000})
    r = h.cmd("oneshot_reclaim", project=P, object_key="ticket:stale", now=4_100)
    ok(r.get("ok") and not r.get("reclaimed"),
       "W5 fresh lock (heartbeat inside lock_timeout_ms) is NOT reclaimed", r)
    r = h.cmd("oneshot_reclaim", project=P, object_key="ticket:stale",
              now=4_000 + 600_001)
    ok(r.get("ok") and r.get("reclaimed"),
       "W5 lock past lock_timeout_ms IS reclaimed (a stuck session cannot hold an object forever)", r)
    r = h.cmd("oneshot_admit", project=P, unit={"kind": "ticket", "id": "stale"},
              limit=9, now=4_000 + 600_002)
    ok(r.get("ok"), "W5 reclaimed object admits a new session", r)

    # W6 — retention: 7 days, summary before delete, references protected
    # (timestamps are MILLISECONDS per the reap contract: cutoff = now_ms -
    # retention_days * 86400 * 1000)
    refs_none = {"watchdog_config": [], "authz_declarations": [], "open_request_owners": []}
    refs_some = {"watchdog_config": ["os-1"], "authz_declarations": ["os-2"],
                 "open_request_owners": ["os-3"]}
    now_ms = 100 * 86400 * 1000
    r = h.cmd("oneshot_reap", project=P, now=now_ms, retention_days=7,
              sessions=[{"id": "os-%d" % i, "ended_at": (100 - 8) * 86400 * 1000}
                        for i in (1, 2, 3, 4)],
              references=refs_some, summarize_fail=False)
    ok(r.get("ok") and sorted(r.get("deleted", [])) == ["os-4"]
       and r.get("summaries") == ["os-4"],
       "W6 referenced sessions (config/authz/open-request owner) never deleted; "
       "the unreferenced expired one IS deleted and got its summary first", r)
    r = h.cmd("oneshot_reap", project=P, now=now_ms, retention_days=0,
              sessions=[{"id": "os-4", "ended_at": (100 - 8) * 86400 * 1000}],
              references=refs_none, summarize_fail=False)
    ok(r.get("ok") and r.get("deleted") == [],
       "W6 retention_days=0 disables reaping entirely", r)
    r = h.cmd("oneshot_reap", project=P, now=now_ms, retention_days=7,
              sessions=[{"id": "os-9", "ended_at": (100 - 8) * 86400 * 1000}],
              references=refs_none, summarize_fail=True)
    ok(r.get("ok") and r.get("deleted") == [] and r.get("skipped") == ["os-9"],
       "W6 summarize failure aborts that deletion (never deletes without its summary)", r)


# ---------------------------------------------------------------------------
# E legs — engine face, real files in a tmp projects root
# ---------------------------------------------------------------------------

def engine_legs() -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="oneshot-it-"))
    try:
        if not SETTLE_CLI.is_file():
            pok(False, "E0 settle CLI landed",
                "missing %s (implement stage delivers it; TDD red expected)" % SETTLE_CLI)
            return

        # E1 — happy path: a one-shot session writes its settle note
        env = engine_env(tmp, "alpha", declare_session="os-e1")
        unit = json.dumps({"op": "settle", "project": "alpha",
                           "session": "os-e1", "ticket": "t-42",
                           "result": "deleted 1 out-of-face file"})
        p = subprocess.run([sys.executable, str(SETTLE_CLI), unit],
                           capture_output=True, text=True, env=env, timeout=60)
        receipt = {}
        try:
            receipt = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
        except Exception:
            pass
        pok(p.returncode == 0 and receipt.get("ok"), "E1 settle accepted for a declared "
            "one-shot session (receipt ok=true with the row)", p.stdout[-200:] + p.stderr[-200:])
        note = tmp / "projects" / "alpha" / "ledger" / "executor-settle.jsonl"
        pok(note.is_file(), "E1 settle-note JSONL exists under the project ledger root", note)
        rows = [json.loads(l) for l in note.read_text(encoding="utf-8").splitlines() if l.strip()] \
            if note.is_file() else []
        pok(len(rows) == 1 and rows[0].get("session") == "os-e1"
            and rows[0].get("ticket") == "t-42",
            "E1 exactly one settle row, stamped with the resolved session id", rows)

        # E2 — fail-closed: an undeclared session id is refused with a named
        # reason and writes NOTHING (same gate as the resident session)
        env2 = engine_env(tmp, "alpha")
        unit2 = json.dumps({"op": "settle", "project": "alpha",
                            "session": "os-ghost", "ticket": "t-42", "result": "x"})
        p = subprocess.run([sys.executable, str(SETTLE_CLI), unit2],
                           capture_output=True, text=True, env=env2, timeout=60)
        try:
            receipt = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            receipt = {}
        pok(p.returncode != 0 and not receipt.get("ok")
            and receipt.get("field") and receipt.get("error"),
            "E2 undeclared session refused: non-zero exit, field+error named", receipt)
        rows2 = [json.loads(l) for l in note.read_text(encoding="utf-8").splitlines()
                 if l.strip()] if note.is_file() else []
        pok(len(rows2) == 1, "E2 the refusal wrote zero rows (no half-rows)", len(rows2))

        # E3 — malformed argv: fail closed, never silently green
        for label, bad in (("invalid JSON", "{not json"),
                           ("unknown op", json.dumps({"op": "shout", "project": "alpha"})),
                           ("missing session", json.dumps({"op": "settle", "project": "alpha"}))):
            p = subprocess.run([sys.executable, str(SETTLE_CLI), bad],
                               capture_output=True, text=True, env=env, timeout=60)
            try:
                receipt = json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:
                receipt = {}
            pok(p.returncode == 2 and not receipt.get("ok")
                and receipt.get("field") and receipt.get("error"),
                "E3 malformed argv (%s) -> exit 2 with field+error" % label, receipt)

        # E4 — channel_kind=one_shot is additive on the action ledger and the
        # reader path tolerates it (public contract: one-shot writes land in
        # the action ledger under the same gate)
        import executor_actions  # noqa: E402
        executor_actions.reset_for_test()
        actions_dir = tmp / "actions"
        os.environ["SANDBAR_EXECUTOR_ACTIONS_DIR"] = str(actions_dir)
        receipt = executor_actions.record_executor_action(
            "alpha", op="file.delete", ticket="t-42", session="os-e1",
            channel="one_shot", decision="allowed",
            extra={"channel_kind": "one_shot"})
        path = executor_actions.actions_path("alpha")
        ok(receipt.get("appended") and path.is_file(),
           "E4 action row with channel_kind=one_shot recorded through the public "
           "append path (receipt appended=true)", receipt)
        rows4 = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                 if l.strip()] if path and path.is_file() else []
        ok(len(rows4) == 1, "E4 the ledger stays one-row-per-gated-attempt and readable", rows4)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    h = Harness()
    h.start()
    try:
        watchdog_legs(h)
    finally:
        h.stop()
    engine_legs()
    total_pass = _wd.PASS + passed
    total_fail = _wd.FAIL + failed
    # t260904-12 three-state contract line (gate has no SKIP; all-N/A = red)
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (total_pass, total_fail, env_failed, na))
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
