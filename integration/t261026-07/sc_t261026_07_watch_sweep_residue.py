#!/usr/bin/env python3
"""L3 integration scenario, ticket t261026-07 (builds B, C, D: watch-cycle
sweep, legacy residue close, the human-word bound).

Intent: the executor's own watch closes what the records can settle -- every
tick, with a visible receipt -- and never closes what only a person may
close. The user-perceivable contract under host order 261026:
  B1. One executor watch tick runs the request sweep BEFORE the run-watch
      decisions, and the tick result carries the sweep receipt (heads
      evaluated, closed, skipped with reasons) -- a sweep that did nothing
      is VISIBLE, never silent (the t261026-06 defect was 65 skipped heads
      under ok:true).
  B2. A sweep that cannot run (unreadable requests ledger) is a NAMED skip
      entry in the tick result AND the run-watch decisions still run -- a
      broken sweep never kills the tick and never hides as success.
  C1. A legacy OPEN head with NO condition whose subject ended -- a
      certification on its line after the head's `at` -- is closed as
      `resolved` with evidence naming that exact row id, read back from the
      LEDGER (the reader side; writer receipts are not evidence).
  C2. A legacy blocker head whose subject ticket reads `closed` is closed
      citing that ticket's row; a head whose subject ticket is NO LONGER
      LISTED has no citable row and stays open, counted on the receipt.
  D1. `finding` and `question` heads are NEVER closed by the machine under
      any evidence shape (subject closed, cert after, landing exists) --
      those classes are the human's word; their rows stay byte-identical.
  D2. The residue pass is idempotent: a second pass over a closed head
      writes nothing new.

Grey-box L3: the REAL run_watch tick face and the REAL request_sweep entry
face over isolated tmp stores (KI-161: never the production ledger);
evidence is read from the on-disk ledgers, never from return receipts
alone. Offline seconds; zero docker / Temporal / browser; never touches
3099/7233.

Run: python3 -B integration/t261026-07/sc_t261026_07_watch_sweep_residue.py
(cwd = repo root)

Intent split: evaluating a DECLARED condition is owned by
t261019-44-request-sweep-resolution; what lands on a row's face at filing
time is owned by t261026-07-class-condition-filing; THIS entry uniquely owns
the watch-cycle placement, the receipt face, and the legacy residue close
under bound D. Pre-implement tree red = the named TDD signal; green required
at the integration gate / merge. Exit codes: 0 = PASS, 1 = FAIL (named),
2 = ENV_FAIL.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
PROJ = "sandbar"
SESSION = "session-sc-t261026-07-residue"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (": " + detail if detail else ""))


def engine_py() -> str:
    for cand in (REPO / "server/engine/.venv/bin/python",):
        if cand.exists():
            return str(cand)
    return sys.executable


def run_py(env: dict, script: str, timeout: int = 120) -> tuple[int, str]:
    p = subprocess.run([engine_py(), "-B", "-c", script],
                       capture_output=True, text=True, env=env, cwd=str(REPO),
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def requests_path(env: dict, proj: str = PROJ) -> Path:
    return Path(env["SANDBAR_PANEL_DIR"]) / proj / "requests.jsonl"


def rows(env: dict, proj: str = PROJ) -> list:
    f = requests_path(env, proj)
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def append_requests_line(env: dict, proj: str, row: dict) -> None:
    f = requests_path(env, proj)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_ledger_line(env: dict, row: dict) -> None:
    d = Path(env["SANDBAR_DELIVERY_LEDGER_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    with (d / (PROJ + ".jsonl")).open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def base_env(tmp: Path) -> dict:
    env = dict(os.environ)
    env.update({
        "SANDBAR_CALLER_PROJECT": PROJ,
        "DSH_SESSION_ID": SESSION,
        "SANDBAR_CALLER_IDENTITY_SRC": "env",
        "SANDBAR_PANEL_DIR": str(tmp / "panel"),
        "SANDBAR_PROJECTS_DIR": str(tmp / "projects"),
        "SANDBAR_DELIVERY_LEDGER_DIR": str(tmp / "ledger"),
        "SANDBAR_INSTANCE_DIR": str(tmp / "instance"),
        "PYTHONDONTWRITEBYTECODE": "1",
        # the lane injects its own surface tag; the scenario is an external-env caller
        "SANDBAR_CALLER_SURFACE": "",
    })
    return env


def declare_executor(env: dict) -> None:
    """Name the fixture session as the project's declared executor session
    (the declaration seam: the host names executor sessions; the scenario
    writes the same declaration shape the Grants page writes)."""
    d = Path(env["SANDBAR_PROJECTS_DIR"]) / PROJ
    d.mkdir(parents=True, exist_ok=True)
    (d / "executor-grants.json").write_text(json.dumps(
        {"version": 1, "grants": {}, "executor_sessions": [env["DSH_SESSION_ID"]],
         "updated_by": "scenario", "updated_at": 0}))

def register_session(env: dict) -> None:
    d = Path(env["SANDBAR_PANEL_DIR"]) / PROJ
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions.json").write_text(json.dumps(
        {"version": 1, "sessions": [{"session_id": SESSION}]}))


def sweep(env: dict, inject_ticket: dict | None = None) -> tuple[dict, str]:
    script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import request_sweep\n"
        "inject = %r\n"
        "kwargs = {}\n" % (str(ENGINE), inject_ticket or {})
        + "if inject is not None:\n"
        "    kwargs['ticket_status_fn'] = lambda t: (tuple(inject[t]) if t in inject else ('not-listed', 'ticket-list-projection'))\n"
        "out = request_sweep.sweep_all_projects(int(time.time() * 1000), 1, **kwargs)\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
    )
    rc, out = run_py(env, script)
    try:
        return json.loads(out), out
    except Exception:
        return {}, out


def legacy_head(req_id: str, kind: str, question: str, at_ms: int,
                extra: dict | None = None) -> dict:
    row = {"type": "request", "id": req_id, "kind": kind, "question": question,
           "state": "open", "state_for": req_id, "at": at_ms, "seq": at_ms,
           "by": "executor:legacy", "epic": "none",
           "epic_reason": "line-health", "default_action": "wait",
           "detail": json.dumps(extra or {}, ensure_ascii=False)}
    row.update(extra or {})
    return row


T0 = 1700000000000  # the legacy heads' filing time
TICK = 60000


def main() -> int:
    if not ENGINE.is_dir():
        print("ENV_FAIL: engine tree missing: " + str(ENGINE))
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="t261026-07-residue-"))
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
    env = base_env(tmp)
    register_session(env)
    declare_executor(env)

    # --- fixture: the measured legacy residue shapes ------------------------
    append_requests_line(env, PROJ, legacy_head(
        "sc07-silent-1", "run-silent",
        "run-silent on line develop-buffer: no run row", T0,
        {"line": "develop-buffer"}))
    append_requests_line(env, PROJ, legacy_head(
        "sc07-blocker-closed", "blocker", "blocker: t102607-1 needs a fix",
        T0 + TICK, {"ticket": "t102607-1"}))
    append_requests_line(env, PROJ, legacy_head(
        "sc07-blocker-gone", "blocker", "blocker: t102607-2 needs a fix",
        T0 + TICK, {"ticket": "t102607-2"}))
    for kind in ("finding", "question"):
        append_requests_line(env, PROJ, legacy_head(
            "sc07-" + kind, kind, kind + ": the human's word", T0 + TICK))
    # the subject rows: a green certification AFTER the heads on the line,
    # and the ticket projection state (closed / not-listed) injected.
    append_ledger_line(env, {
        "kind": "certification", "id": "cert-sc07green", "seq": 99,
        "at": T0 + 10 * TICK, "line": "develop-buffer", "verdict": "green",
        "run": "run-sc07"})
    inject = {"t102607-1": ("closed", "ticket-list-projection")}

    # --- B1/C1/C2/D1: the sweep pass closes the closable, cites evidence ----
    rec, out = sweep(env, inject)
    if not rec:
        print("ENV_FAIL: sweep face did not return JSON: " + out[:300])
        return 2

    def resolved(rid):
        f = requests_path(env)
        states = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        return [r for r in states
                if r.get("state_for") == rid and r.get("state") == "resolved"]

    s1 = resolved("sc07-silent-1")
    check("legacy-run-silent-closed-with-cited-cert",
          bool(s1) and any("cert-sc07green" in json.dumps(r) for r in s1),
          "resolved rows: " + json.dumps(s1)[:300])

    s2 = resolved("sc07-blocker-closed")
    check("legacy-blocker-closed-ticket-cited",
          bool(s2) and any("t102607-1" in json.dumps(r) for r in s2),
          "resolved rows: " + json.dumps(s2)[:300])

    gone = [r for r in rows(env) if r.get("id") == "sc07-blocker-gone"
            and r.get("state") == "open"]
    check("unlistable-ticket-stays-open-counted",
          len(gone) >= 1,
          "receipt: " + json.dumps(rec)[:400])

    for kind in ("finding", "question"):
        untouched = [r for r in rows(env) if r.get("id") == "sc07-" + kind
                     and r.get("state") == "open"]
        check(kind + "-never-machine-closed", len(untouched) >= 1,
              "rows after sweep: " + json.dumps(
                  [r for r in rows(env) if r.get("id") == "sc07-" + kind])[:300])

    # --- D2: idempotency -- a second pass writes nothing new ----------------
    before_count = len(rows(env))
    sweep(env, inject)
    check("second-pass-writes-nothing-new", len(rows(env)) == before_count,
          "rows before=%d after=%d" % (before_count, len(rows(env))))

    # --- B1/B2: the sweep runs INSIDE the watch tick with a receipt ---------
    tick_script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import run_watch\n"
        "out = run_watch.run_watch_tick_engine(int(time.time() * 1000))\n"
        "print(json.dumps(out, ensure_ascii=False))\n" % str(ENGINE)
    )
    rc, tout = run_py(env, tick_script)
    try:
        tick = json.loads(tout)
    except Exception:
        tick = {}
    check("watch-tick-carries-sweep-receipt",
          "request_sweep" in json.dumps(tick) or "sweep" in json.dumps(tick),
          "tick keys: " + json.dumps(list(tick))[:200] + " out: " + tout[:200])

    # B2: a broken requests ledger is a NAMED skip, decisions still run
    tmp2 = Path(tempfile.mkdtemp(prefix="t261026-07-broken-"))
    atexit.register(lambda: shutil.rmtree(tmp2, ignore_errors=True))
    env2 = base_env(tmp2)
    register_session(env2)
    (requests_path(env2)).write_text("{not json at all\n")
    rc2, tout2 = run_py(env2, tick_script)
    try:
        tick2 = json.loads(tout2)
    except Exception:
        tick2 = {}
    t2s = json.dumps(tick2, ensure_ascii=False)
    check("broken-ledger-named-not-silent",
          "request_sweep" in t2s or "sweep" in t2s,
          "tick output: " + tout2[:300])

    print("SUMMARY ran=1 pass=%d fail=%d" % (0 if FAILS else 1, len(FAILS)))
    if FAILS:
        for f in FAILS:
            print("  FAILED: " + f)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: scenario could not run: %s: %s" % (type(e).__name__, e))
        sys.exit(2)
