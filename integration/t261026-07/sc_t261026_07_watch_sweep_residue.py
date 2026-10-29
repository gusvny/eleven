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
      LISTED has no citable projection row, so it stays open UNLESS the
      ticket's ARCHIVE proves terminal closure (t261028-25 -- the archive is
      consulted only then, and only a manifest the terminal-archive exit wrote
      counts). This fixture has no archive store for the cited ticket, so the
      head stays open and is counted on the receipt (bucket
      `not_listed_unarchived`).
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

Receipt anchor (t261029-29): B1/B2 assert the STRUCTURED receipt the product
emits (`tick["request_sweep"]` -> per-project object with resolved / skipped /
residue / unchanged / malformed_lines counters, plus a named skip or error when
the sweep cannot run), never a substring of the tick's JSON text — the old
`"sweep" in json.dumps(tick)` was satisfied by the tick's own human summary
line for ANY tick. Both legs carry a teeth leg that feeds the same predicate
mutated tick dicts (receipt dropped, replaced by the bare word, faked success,
decisions removed) and requires it to turn red.

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


def declare_line(env: dict, line: str = "develop-buffer") -> None:
    """Declare one develop line for the fixture project. The watch tick
    enumerates projects through `develop_certify.declared_line_projects()`,
    which lists only projects carrying `data/develop/lines.json` — with none
    declared the tick sweeps nothing and its `request_sweep` object is empty,
    so the receipt face B1/B2 pin would not be exercised at all (t261029-29)."""
    d = Path(env["SANDBAR_PROJECTS_DIR"]) / PROJ / "data" / "develop"
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(
        [{"version": 1, "line_id": line,
          "repositories": [{"name": PROJ, "branch": "main"}]}]))


def tick_of(env: dict) -> tuple:
    """One REAL executor watch tick (`run_watch.run_watch_tick_engine`) in the
    fixture env: (rc, tick dict or {}, raw output)."""
    script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import run_watch\n"
        "out = run_watch.run_watch_tick_engine(int(time.time() * 1000))\n"
        "print(json.dumps(out, ensure_ascii=False))\n" % str(ENGINE)
    )
    rc, out = run_py(env, script)
    for candidate in (out, *(out.splitlines() or [""])):
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return rc, parsed, out
    return rc, {}, out


def b1_receipt_defects(tick: dict) -> list:
    """Named defects of B1's contract — empty list means pass.

    t261029-29: B1 read `"request_sweep" in json.dumps(tick) or "sweep" in
    json.dumps(tick)`, and run_watch's own human summary line already contains
    the word "sweep" for EVERY tick — so the structured receipt could vanish and
    B1 stayed green (evidence that cannot fail). The contract asserted here is
    the STRUCTURE the product emits: `tick["request_sweep"]` is an object, the
    project's receipt carries the counters (`resolved`/`skipped`/`residue`/
    `unchanged`/`malformed_lines`), heads closed/skipped are named on it, and
    the tick-level close counter agrees with it while the run-watch decisions
    ran in the same tick. Pure function: the teeth leg feeds it mutated ticks."""
    d: list[str] = []
    rs = tick.get("request_sweep") if isinstance(tick, dict) else None
    if not isinstance(rs, dict):
        return ["tick.request_sweep is not an object (got %r)" % (type(rs).__name__,)]
    receipt = rs.get(PROJ)
    if not isinstance(receipt, dict):
        return ["no receipt object for project %r (receipts: %r)"
                % (PROJ, sorted(rs)[:5])]
    if receipt.get("ok") is not True:
        d.append("receipt.ok is not True: %r (error=%r)"
                 % (receipt.get("ok"), receipt.get("error")))
    for key in ("resolved", "skipped", "residue"):
        if not isinstance(receipt.get(key), list):
            d.append("receipt.%s is not a list: %r" % (key, receipt.get(key)))
    for key in ("residue_buckets",):
        if not isinstance(receipt.get(key), dict):
            d.append("receipt.%s is not an object: %r" % (key, receipt.get(key)))
    for key in ("unchanged", "malformed_lines"):
        if not isinstance(receipt.get(key), int) or isinstance(receipt.get(key), bool):
            d.append("receipt.%s is not an int counter: %r"
                     % (key, receipt.get(key)))
    # a head EVALUATED and CLOSED is named with the evidence that closed it
    closed = [e for e in (receipt.get("resolved") or []) if isinstance(e, dict)]
    if not any(e.get("id") == "sc07-b1-closable" and e.get("evidence")
               for e in closed):
        d.append("the closable head is not on receipt.resolved with evidence: %r"
                 % (closed,))
    # a head that could NOT be evaluated is a NAMED skip, never silence
    skipped = [e for e in (receipt.get("skipped") or []) if isinstance(e, dict)]
    if not any(e.get("id") == "sc07-b1-invalid-condition"
               and "condition_invalid" in str(e.get("reason") or "")
               for e in skipped):
        d.append("the invalid-condition head is not a named skip: %r" % (skipped,))
    # the broken ledger LINE is counted on the receipt, not dropped
    if int(receipt.get("malformed_lines") or 0) < 1:
        d.append("the malformed ledger line is not counted: %r"
                 % (receipt.get("malformed_lines"),))
    # the tick-level close counter summarises exactly these receipts
    total = tick.get("request_sweep_closed_total")
    closed_here = len(closed) + len([e for e in (receipt.get("residue") or [])
                                     if isinstance(e, dict)
                                     and e.get("bucket") == "closed"])
    if not isinstance(total, int) or isinstance(total, bool) \
            or total != closed_here or total < 1:
        d.append("request_sweep_closed_total=%r disagrees with the receipt "
                 "(%d closed)" % (total, closed_here))
    # the run-watch DECISIONS ran in the same tick (the sweep rides the tick)
    if not decisions_ran(tick):
        d.append("the run-watch decision pass did not run: projects=%r"
                 % ((tick.get("projects") or {}),))
    return d


def decisions_ran(tick: dict) -> bool:
    """Did the tick's decision pass reach the fixture line (feeding leg B1/B2)?"""
    projects = tick.get("projects") if isinstance(tick, dict) else None
    proj = projects.get(PROJ) if isinstance(projects, dict) else None
    lines = proj.get("lines") if isinstance(proj, dict) else None
    return (isinstance(lines, list) and len(lines) == 1
            and isinstance(lines[0], dict)
            and isinstance(lines[0].get("decision"), dict))


def b2_receipt_defects(tick: dict) -> list:
    """Named defects of B2's contract — empty list means pass.

    A sweep that cannot run is a NAMED, STRUCTURED per-project entry on the tick
    (`ok:false` and an error/skip string naming the unreadable ledger) and the
    run-watch decisions still ran. t261029-29 replaced the old bare `"sweep"`
    substring (true for any tick) with this contract."""
    d: list[str] = []
    rs = tick.get("request_sweep") if isinstance(tick, dict) else None
    if not isinstance(rs, dict):
        return ["tick.request_sweep is not an object (got %r)" % (type(rs).__name__,)]
    receipt = rs.get(PROJ)
    if not isinstance(receipt, dict):
        return ["no receipt object for project %r (receipts: %r)"
                % (PROJ, sorted(rs)[:5])]
    if receipt.get("ok") is not False:
        d.append("receipt.ok is not False for an unreadable ledger: %r"
                 % (receipt.get("ok"),))
    named = str(receipt.get("error") or receipt.get("skipped_all") or "")
    if not named:
        d.append("the broken sweep carries no named error/skip entry: %r"
                 % (receipt,))
    else:
        if not any(marker in named for marker in
                   ("request_sweep_failed", "ledger_unreadable",
                    "ledger_path_unresolvable")):
            d.append("the named entry does not say which failure face: %r"
                     % (named[:200],))
        if "requests.jsonl" not in named and "ledger" not in named:
            d.append("the named entry does not name the unreadable ledger: %r"
                     % (named[:200],))
    if not decisions_ran(tick):
        d.append("a broken sweep killed the run-watch decisions: projects=%r"
                 % ((tick.get("projects") or {}),))
    return d


def b1_tick_fixture(env: dict) -> None:
    """B1's tick env: one declared line, one closable head (a round row after
    it), one head whose condition is invalid, one malformed ledger line, and the
    delivery-ledger certification that closes the first head."""
    declare_line(env)
    append_requests_line(env, PROJ, {
        "type": "request", "id": "sc07-b1-closable", "kind": "run-silent",
        "question": "run-silent on line develop-buffer: no run row",
        "state": "open", "state_for": "sc07-b1-closable", "at": T0, "seq": T0,
        "by": "executor:legacy",
        "resolves_when": {"kind": "round_after", "line": "develop-buffer"}})
    append_requests_line(env, PROJ, {
        "type": "request", "id": "sc07-b1-invalid-condition", "kind": "run-silent",
        "question": "run-silent on line develop-buffer: no run row",
        "state": "open", "state_for": "sc07-b1-invalid-condition", "at": T0,
        "seq": T0, "by": "executor:legacy",
        "resolves_when": {"kind": "no_such_condition_kind"}})
    with requests_path(env).open("a") as fh:
        fh.write("{not json at all\n")
    append_ledger_line(env, {
        "kind": "certification", "id": "cert-sc07b1", "seq": 99,
        "at": T0 + 10 * TICK, "line": "develop-buffer", "verdict": "green",
        "run": "run-sc07b1", "repos": {PROJ: "0" * 40}})


def unreadable_requests_ledger(env: dict) -> Path:
    """B2's broken face: the requests ledger PATH is a directory, so the ledger
    cannot be read or appended to at all (not merely unparsable)."""
    path = requests_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    return path


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
    # t261029-29: the receipt is asserted as a STRUCTURE (counters, named heads,
    # named skip/error), never as a word that happens to be in the tick — the old
    # `"sweep" in json.dumps(tick)` was satisfied by the tick's own human summary
    # for ANY tick, so the receipt could disappear with B1 still green.
    tmp3 = Path(tempfile.mkdtemp(prefix="t261026-07-tick-"))
    atexit.register(lambda: shutil.rmtree(tmp3, ignore_errors=True))
    env_tick = base_env(tmp3)
    register_session(env_tick)
    b1_tick_fixture(env_tick)
    _rc_t, tick, tout = tick_of(env_tick)
    b1_defects = b1_receipt_defects(tick)
    check("watch-tick-carries-sweep-receipt", not b1_defects,
          "; ".join(b1_defects) + " | tick keys: " + json.dumps(list(tick))[:200]
          + " | out: " + tout[:300])

    # B1 teeth (t261029-29): the SAME predicate must turn red when the receipt is
    # dropped from the tick, and when it is replaced by the bare word the old form
    # accepted. Fed mutated tick dicts only — the real tick above is untouched.
    dropped = {k: v for k, v in tick.items() if k != "request_sweep"}
    bare_word = dict(dropped, request_sweep="sweep")
    old_form_green_on_dropped = ("request_sweep" in json.dumps(dropped)
                                or "sweep" in json.dumps(dropped))
    b1_teeth = (not b1_receipt_defects(dropped)
                and not b1_receipt_defects(bare_word)
                and old_form_green_on_dropped)
    check("sweep-receipt-lock-has-teeth", not b1_teeth,
          "dropped->%r bare-word->%r old-form-on-dropped=%r"
          % (b1_receipt_defects(dropped)[:2],
             b1_receipt_defects(bare_word)[:2], old_form_green_on_dropped))

    # B2: a sweep that CANNOT run is a NAMED per-project entry, decisions still run
    tmp2 = Path(tempfile.mkdtemp(prefix="t261026-07-broken-"))
    atexit.register(lambda: shutil.rmtree(tmp2, ignore_errors=True))
    env2 = base_env(tmp2)
    register_session(env2)
    declare_line(env2)
    unreadable_requests_ledger(env2)
    rc2, tick2, tout2 = tick_of(env2)
    b2_defects = b2_receipt_defects(tick2)
    check("broken-ledger-named-not-silent", not b2_defects,
          "; ".join(b2_defects) + " | tick keys: " + json.dumps(list(tick2))[:200]
          + " | out: " + tout2[:300])

    # B2 teeth (t261029-29): the predicate must turn red on a receipt that claims
    # success while the ledger is unreadable, on a tick without the receipt, and on
    # a tick whose decision pass never ran. Built around the REAL broken receipt so
    # the teeth do not depend on the parse above succeeding.
    real_receipt = ((tick2.get("request_sweep") or {}).get(PROJ)
                    if isinstance(tick2.get("request_sweep"), dict) else None)
    if not isinstance(real_receipt, dict):
        real_receipt = {"ok": False, "project": PROJ,
                        "error": "request_sweep_failed:requests ledger "
                                 "unreadable (requests.jsonl)"}
    good_projects = {PROJ: {"lines": [{"line": "develop-buffer",
                                       "decision": {"action": "none"}}]}}
    silent_success = {"projects": good_projects,
                      "request_sweep": {PROJ: {"ok": True, "project": PROJ,
                                               "resolved": [], "skipped": [],
                                               "unchanged": 0, "residue": [],
                                               "malformed_lines": 0,
                                               "residue_buckets": {}}},
                      "request_sweep_closed_total": 0,
                      "summary": "run_watch: 1 projects, 1 lines, sweep closed 0"}
    no_decisions = {"request_sweep": {PROJ: real_receipt},
                    "request_sweep_closed_total": 0,
                    "summary": "run_watch: 0 projects, 0 lines, sweep closed 0"}
    receipt_dropped = {"projects": good_projects,
                       "request_sweep_closed_total": 0,
                       "summary": "run_watch: 1 projects, 1 lines, sweep closed 0"}
    b2_mutants = (("faked-success", silent_success),
                  ("decisions-gone", no_decisions),
                  ("receipt-gone", receipt_dropped))
    b2_teeth = any(not b2_receipt_defects(t) for _label, t in b2_mutants)
    check("broken-ledger-lock-has-teeth", not b2_teeth,
          "; ".join("%s->%r" % (label, b2_receipt_defects(t)[:2])
                    for label, t in b2_mutants))

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
