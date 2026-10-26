# -*- coding: utf-8 -*-
"""L3 integration scenario, ticket t261026-06.

Intent: the request sweep's `ticket_closed` condition is EVALUATED, not
always skipped -- the reader channel the sweep uses is the engine's real admin
entry point, and a dead reader is LOUD (named once, top level) instead of 65
silent per-head skips under a bare ok:true. User-perceivable contract under
the ticket:
  1. A head whose `ticket_closed` ticket reads closed through the sweep's
     ticket-list projection RESOLVES, and the ledger (reader side) carries a
     resolved state row whose evidence NAMES the source projection.
  2. A head whose ticket is not closed does not resolve (no fabricated green).
  3. When the reader entry is MISSING/unreachable, the receipt names the
     missing path at the top level; per-head skips still carry the stable
     `ticket_reader_unavailable:` reason; ok stays true (a skip is a named
     outcome, per the module contract) -- but the dead channel is no longer
     indistinguishable from ordinary per-head skips.
  4. A reader answer of ok:false / no tickets row is unavailable-or-empty BY
     NAME: it never resolves anything.
  5. The REAL CLI face (server/engine/request_sweep.py, real admin entry)
     fabricates nothing in an isolated sandbox: heads whose tickets are not in
     the sandbox registry stay open.

Grey-box L3: the REAL request_thread.py CLI (filing) + the REAL
default_ticket_status_fn subprocess channel (pointed at a fixture stub admin
entry by setting shared.ADMIN_PY after import -- the declared seam), and the
REAL sweep CLI entry, over isolated tmp ledgers (SANDBAR_PANEL_DIR /
SANDBAR_DELIVERY_LEDGER_DIR / SANDBAR_PROJECTS_DIR -- KI-161: never the
production ledger). Offline seconds, zero docker/Temporal/browser, never
touches 3099/7233. Pre-implement tree red on legs A/B = the named TDD signal
(today's tree reads server/tools/admin.py, which does not exist); green
required at the integration gate.

Exit codes: 0 = PASS, 1 = FAIL (named), 2 = ENV_FAIL.
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
FIXTURE_SESSION = "session-sc-t26102606-fixture"

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


def base_env(tmp: Path) -> dict:
    env = dict(os.environ)
    env.update({
        "SANDBAR_CALLER_PROJECT": PROJ,
        "DSH_SESSION_ID": FIXTURE_SESSION,
        "SANDBAR_CALLER_IDENTITY_SRC": "env",
        "SANDBAR_PANEL_DIR": str(tmp / "panel"),
        "SANDBAR_PROJECTS_DIR": str(tmp / "projects"),
        "SANDBAR_DELIVERY_LEDGER_DIR": str(tmp / "ledger"),
        "SANDBAR_INSTANCE_DIR": str(tmp / "instance"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    (tmp / "panel" / PROJ).mkdir(parents=True, exist_ok=True)
    (tmp / "panel" / PROJ / "sessions.json").write_text(json.dumps(
        {"version": 1, "sessions": [{"session_id": FIXTURE_SESSION}]}))
    return env


def cli(env: dict, op_json: str) -> tuple[int, str]:
    p = subprocess.run([engine_py(), "-B", str(ENGINE / "request_thread.py"), op_json],
                       capture_output=True, text=True, env=env, cwd=str(REPO), timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sweep_sandbox(env: dict, admin_entry: Path | None) -> tuple[int, str]:
    """Run the REAL default_ticket_status_fn channel: sweep_all_projects in a
    subprocess with shared.ADMIN_PY set (after import, the declared seam) to
    the given entry -- a fixture stub when testing the channel, a path that
    does not exist when testing the loud failure. No injected fn: the default
    reader resolution IS the behavior under test."""
    script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import shared\n"
        "shared.ADMIN_PY = %r\n"
        "import request_sweep\n"
        "out = request_sweep.sweep_all_projects(int(time.time() * 1000), 1)\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
        % (str(ENGINE), str(admin_entry))
    )
    p = subprocess.run([engine_py(), "-B", "-c", script],
                       # SANCTIONED-WAIT: 120s safety bound on a seconds-scale offline subprocess.
                       capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sweep_real_cli(env: dict) -> tuple[int, str]:
    # SANCTIONED-WAIT: 120s safety bound on a seconds-scale offline CLI subprocess (the real sweep entry over tmp fixtures), never a polling wait.
    p = subprocess.run([engine_py(), "-B", str(ENGINE / "request_sweep.py"),
                        json.dumps({"project": PROJ})],
                       capture_output=True, text=True, env=env, cwd=str(REPO),
                       # SANCTIONED-WAIT: 120s safety bound on a seconds-scale offline CLI subprocess, never a polling wait.
                       timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def rows(env: dict, key: str) -> list:
    f = Path(env["SANDBAR_PANEL_DIR"]) / key / "requests.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def file_head(env: dict, subject: str, ticket: str) -> dict:
    rc, out = cli(env, json.dumps({
        "op": "file", "project": PROJ, "kind": "question", "subject": subject,
        "question": subject, "detail": "auto",
        "default_action": "wait for the line to move", "by": "executor:test",
        "source_ticket": "t261026-06", "epic": "none",
        "epic_reason": "line-health question",
        "resolves_when": {"kind": "ticket_closed", "ticket": ticket}}))
    check("fixture-file-" + subject, rc == 0, out[:400])
    try:
        return json.loads(out).get("row", {})
    except Exception:
        return {}


def make_stub(path: Path, payload: dict | str, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write(%r)\n"
        "sys.exit(%d)\n" % (payload if isinstance(payload, str)
                            else json.dumps(payload), exit_code)
    )
    path.write_text(body)
    path.chmod(0o755)


def main() -> int:
    if not ENGINE.is_dir():
        print("ENV_FAIL: engine tree missing: " + str(ENGINE))
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="t26102606-"))
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
    env = base_env(tmp)

    # fixture: two open heads declaring ticket_closed on distinct tickets.
    h_closed = file_head(env, "q-tc-closed", "t261026-77")
    h_open = file_head(env, "q-tc-open", "t261026-78")
    if not h_closed or not h_open:
        print("FAIL fixture: head filing did not land; cannot judge reader legs")
        return 1

    stub = tmp / "fixture_repo" / "server" / "admin.py"
    make_stub(stub, {"ok": True, "result": {"tickets": [
        {"id": "t261026-77", "status": "closed"},
        {"id": "t261026-78", "status": "running"},
    ]}})

    # -- A: the real default reader channel, pointed at a working admin entry,
    # resolves the closed-ticket head; evidence names the source projection;
    # the open-ticket head is untouched.
    rc, out = sweep_sandbox(env, stub)
    check("A1-sweep-ok", rc == 0, out[:600])
    try:
        receipt = json.loads(out.splitlines()[-1])
    except Exception:
        receipt = {}
    resolved_ids = {r.get("id") for r in (receipt.get("projects", {}).get(PROJ, {})
                                          .get("resolved") or [])}
    check("A2-closed-head-resolves", h_closed.get("id") in resolved_ids,
          "resolved=%r" % (resolved_ids,))
    ledger_rows = rows(env, PROJ)
    ev = [r.get("evidence", "") for r in ledger_rows
          if r.get("state_for") == h_closed.get("id")
          and r.get("state") == "resolved"]
    check("A3-evidence-names-source",
          any("ticket-list-projection" in e for e in ev), "evidence=%r" % (ev,))
    check("A4-open-head-untouched",
          h_open.get("id") not in resolved_ids
          and not [r for r in ledger_rows if r.get("state_for") == h_open.get("id")])

    # -- B: a MISSING reader entry is LOUD: the receipt names the missing path
    # at the top level, per-head skips keep the stable reason prefix, nothing
    # resolves, ok stays true (named outcome, not silent success).
    missing = tmp / "no_such_repo" / "server" / "admin.py"
    rc, out = sweep_sandbox(env, missing)
    check("B1-sweep-runs", rc == 0, out[:600])
    try:
        receipt_b = json.loads(out.splitlines()[-1])
    except Exception:
        receipt_b = {}
    proj_b = receipt_b.get("projects", {}).get(PROJ, {})
    flat = json.dumps(receipt_b, ensure_ascii=False)
    check("B2-receipt-names-missing-path", str(missing) in flat, flat[:600])
    # after A, the closed head is TERMINAL (silently skipped), so exactly the
    # open head remains; the per-head reason format is pinned stable as
    # `ticket_reader_unavailable:<ticket>` (review conditional comment 1).
    skips = proj_b.get("skipped") or []
    check("B3-heads-skip-named",
          [s.get("id") for s in skips] == [h_open.get("id")]
          and skips and skips[0].get("reason") ==
          "ticket_reader_unavailable:" + "t261026-78",
          "skips=%r" % (skips[:4],))
    check("B4-nothing-resolves", not (proj_b.get("resolved") or []))
    check("B5-ok-still-true-named-outcome", receipt_b.get("ok") is True)

    # -- C: a reader that answers ok:false (or a non-ticket payload) never
    # resolves: unavailable-or-empty BY NAME, no fabricated green.
    stub_bad = tmp / "bad_repo" / "server" / "admin.py"
    make_stub(stub_bad, {"ok": False, "error": "unknown project"})
    rc, out = sweep_sandbox(env, stub_bad)
    check("C1-sweep-runs", rc == 0, out[:400])
    try:
        receipt_c = json.loads(out.splitlines()[-1])
    except Exception:
        receipt_c = {}
    proj_c = receipt_c.get("projects", {}).get(PROJ, {})
    check("C2-no-fabricated-resolution", not (proj_c.get("resolved") or []),
          out[:400])

    # -- D: the REAL CLI face over the sandbox registry fabricates nothing:
    # neither fixture ticket exists there, so NEITHER head gains a NEW
    # resolution (run A's resolution of the closed head is already on the
    # ledger -- only rows written by THIS run count).
    before_d = len([r for r in rows(env, PROJ) if r.get("state") == "resolved"])
    rc, out = sweep_real_cli(env)
    check("D1-real-cli-runs", rc == 0, out[:400])
    after = rows(env, PROJ)
    resolved_now = [r for r in after if r.get("state") == "resolved"][before_d:]
    check("D2-real-face-fabricates-nothing", not resolved_now,
          "rows=%r" % (resolved_now,))

    if FAILS:
        print("RESULT FAIL (%d)" % len(FAILS))
        for f in FAILS:
            print("  - " + f)
        return 1
    print("RESULT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
