#!/usr/bin/env python3
"""sc_t26101610_dismiss_inspection_population.py — the dismiss existence gate
must honour the inspection store, not only the engine ticket-list (t261016-10).

Run directly: python3 integration/t261016-10/sc_t26101610_dismiss_inspection_population.py
(cwd = repo root).

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal-server/browser,
never touches 3099/7233.

User story (host report 261016, verbatim): clicking Dismiss on a failed
INSPECTION row answered
    ValueError: unknown ticket: t261008-17 is not in the engine ticket
    population — check the id, never guess
and the row STAYED on the board. The host's requirement, verbatim: "when I
press it, do not show this ticket in the UI any more". The id t261008-17 is a
RESERVED id a re-run superseded — it exists only in the inspection store
(the period pointer's supersedes_ticket_id + the spawn journal), nowhere as a
ticket. The existence gate (server/tools/ticket.py::_known_ticket_ids) reads
the engine ticket-list ONLY, so the refusal was correct for what it checked,
and the click did nothing the user can see.

This scenario owns what no existing entry owns (intent split):
  - t261009-31-dismiss-journal-contract owns the journal write/read contract
    and the zero-write refusal matrix over the dev-lane population — NOT
    re-asserted here beyond the one shape check proving the inspection
    disposition lands in the SAME journal.
  - t261009-31-dismiss-reader-face owns the `dismissed`/`dismissed_note`
    read-face augmentation; t261009-54 owns the route seam; t261009-43 owns
    the client row-leave/dwell/fold faces — all untouched by this ticket.
  - THIS entry owns the existence-gate population: an inspection-store-provable
    id (reserved, superseded, terminated, collapsed) is dismissible; an id in
    neither population is refused BY NAME naming both checked sources; the
    dev-lane path and its human+reason rules are unchanged; malformed
    inspection-store input degrades, never crashes, never guesses.

Contract faces asserted:

  A  the host regression (the t261008-17 shape): with the engine ticket-list
     UNAVAILABLE (ok:false — the fail-closed source) and a fixture inspection
     store carrying pointer {ticket_id, supersedes_ticket_id} + a spawn-journal
     row, the dismiss op on the reserved id answers ok, the audit journal FILE
     read back from disk carries exactly one row
     {at, ticket_id, who, reason, action="dismiss"}, restore appends the
     second row (last-row-wins), and a re-dismiss after the restore is allowed
     (reversibility contract unchanged).
  B  the dev-lane path is unchanged: an id proven by the ticket-list alone
     dismisses with the same journal shape, and the human+reason rules hold —
     agent-role who refused, empty reason refused, missing who refused, every
     refusal ZERO-WRITE (journal digest identical).
  C  population coverage per source: the pointer's live ticket_id, the
     supersedes id, the spawn-journal id, and the reopen trio
     (terminated_ticket_id / new_ticket_id / collapsed_ticket_ids) are ALL
     dismissible — every id the inspection store can vouch for.
  D  malformed input tolerance (external-input discipline): a corrupt pointer
     file and corrupt spawn/reopen journal lines are skipped (never a crash),
     and a well-formed id remains dismissible — the corrupt pointer does not
     take the store's whole testimony down.
  E  fail-closed stays fail-closed: an id in NEITHER population is refused by
     name, the refusal naming BOTH checked sources (engine ticket population
     AND the inspection store) — never a bare "unknown", never a guess; with
     both sources unreadable the op is still refused, never silently allowed;
     every refusal is zero-write.

Process-boundary stubs (the only stubbed piece): the Temporal client spawn
behind ticket.py's list face is replaced by a fixture receipt — the same
stub philosophy as t261009-54's passthrough admin. The dismissal logic, the
gate wiring and the journal are the REAL production code.

Pre-implementation tree red is the expected TDD signal; green required at the
integration gate / merge. server/tools/ticket.py missing = ENV_FAIL exit 2.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "server" / "tools" / "ticket.py"

WHO = "host"
REASON = "host dismissed the dead row"
AGENT_WHO = "developer"  # shared.AUTHZ_AGENT_ROLE_NAMES member — never a human

# Fixture ids shaped like the reported case (t-family, clearly synthetic).
T_LIVE = "t1610-27"        # pointer ticket_id — the period's live ticket
T_RESERVED = "t1610-17"    # pointer supersedes_ticket_id + spawn row (host shape)
T_SPAWN = "t1610-21"       # spawn-journal-only id
T_TERM = "t1610-31"        # reopen terminated_ticket_id
T_NEW = "t1610-32"         # reopen new_ticket_id
T_C1, T_C2 = "t1610-33", "t1610-34"  # reopen collapsed_ticket_ids
T_DEV = "t1610-d1"         # ticket-list-only dev-lane id
T_GHOST = "t1610-ghost"    # in neither population

PASS = FAIL = ENV_FAIL = NA = 0


def section(title: str) -> None:
    print("\n== %s" % title)


def ok(good: bool, label: str) -> None:
    global PASS, FAIL
    if good:
        PASS += 1
        print("  PASS %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def env_fail(reason: str) -> None:
    global ENV_FAIL
    ENV_FAIL += 1
    print("ENV_FAIL: %s" % reason)


def _fixture_store(root: str, *, corrupt: bool = False) -> str:
    """Build a fixture inspection store (pointer + spawn + reopen journals)."""
    insp = os.path.join(root, "inspection")
    os.makedirs(insp, exist_ok=True)
    pointer = {"ticket_id": T_LIVE, "supersedes_ticket_id": T_RESERVED,
               "instance_id": "simplify-face", "period": "20261008"}
    if corrupt:
        (Path(insp) / "inspection-simplify-face-20261008.ticket").write_text(
            "{not json at all", encoding="utf-8")
    else:
        (Path(insp) / "inspection-simplify-face-20261008.ticket").write_text(
            json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
    spawn_lines = [
        json.dumps({"at": 1.0, "instance_id": "simplify-face",
                    "period": "20261008", "ticket_id": T_RESERVED,
                    "deduped": False}),
        "this line is not json",
        json.dumps({"at": 2.0, "instance_id": "simplify-face",
                    "period": "20261009", "ticket_id": T_SPAWN}),
    ]
    if corrupt:
        spawn_lines.insert(1, "\x00\x01 binary garbage")
    (Path(insp) / "inspection-spawn.jsonl").write_text(
        "\n".join(spawn_lines) + "\n", encoding="utf-8")
    reopen_lines = [
        "}{ broken",
        json.dumps({"at": 3.0, "terminated_ticket_id": T_TERM,
                    "new_ticket_id": T_NEW,
                    "collapsed_ticket_ids": [T_C1, T_C2]}),
    ]
    (Path(insp) / "inspection-reopen.jsonl").write_text(
        "\n".join(reopen_lines) + "\n", encoding="utf-8")
    return insp


JOURNAL_NAME = "ticket-dismiss.jsonl"


def _digest(root: str) -> str:
    p = Path(root) / "journal" / JOURNAL_NAME
    if not p.exists():
        return "absent"
    return hashlib.sha256(p.read_bytes()).hexdigest()


_HARNESS = r"""
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("ticket_tool_t26101610", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
if os.environ.get("SC_STUB_LIST") == "ok":
    ids = json.loads(os.environ["SC_STUB_IDS"])
    m._poc = lambda sub, p, caller=None: {"ok": True, "result": {"tickets": [{"id": i} for i in ids]}}
elif os.environ.get("SC_STUB_LIST") == "down":
    m._poc = lambda sub, p, caller=None: {"ok": False, "error": "list unavailable (fixture)"}
args = json.loads(sys.argv[2])
try:
    out = m.run(args)
except Exception as e:  # the CLI contract: refusal = named error, non-zero exit
    out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
print(json.dumps(out, ensure_ascii=False))
"""


def call(root: str, op: str, tid: str, *, who=WHO, reason=REASON,
         list_mode: str = "down", list_ids: str = "[]"):
    """One op through the REAL ticket.run in a harness subprocess.

    list_mode: 'down' = the list face is unobtainable (fail-closed source),
    'ok' = the list face serves the fixture ids. The journal and the
    inspection store are pinned per-call via env (the declared override seam).
    """
    env = dict(os.environ)
    env["SANDBAR_DISMISS_DIR"] = os.path.join(root, "journal")
    env["SANDBAR_INSPECTION_DIR"] = os.path.join(root, "inspection")
    env["SC_STUB_LIST"] = list_mode
    env["SC_STUB_IDS"] = list_ids
    env.pop("SANDBAR_CALLER_PROJECT", None)
    args = {"op": op, "id": tid, "who": who, "by": who, "reason": reason}
    proc = subprocess.run(
        [sys.executable, "-c", _HARNESS, str(TOOL), json.dumps(args)],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(REPO))  # SANCTIONED-WAIT: one bounded harness subprocess per op, hard 120 s ceiling, a hang is named, never a poll
    if proc.returncode not in (0, 1) and not proc.stdout.strip():
        return {"ok": False, "error": "harness crashed: %s" % proc.stderr[-400:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "error": "no receipt: %s" % (proc.stderr[-400:] or proc.stdout[-200:])}


def journal_rows(root: str):
    j = Path(root) / "journal" / "ticket-dismiss.jsonl"
    if not j.exists():
        return []
    rows = []
    for line in j.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main() -> int:
    if not TOOL.exists():
        env_fail("server/tools/ticket.py missing at %s" % TOOL)
        print("\nSUMMARY pass=%d fail=%d env_fail=%d na=%d" % (PASS, FAIL, ENV_FAIL, NA))
        return 2

    work = tempfile.mkdtemp(prefix="sc-t26101610-")
    try:
        # ---------- A. the host regression: reserved id, list face down ----------
        section("A the t261008-17 shape: list face down, inspection store proves the id")
        root_a = os.path.join(work, "a")
        _fixture_store(root_a)
        res = call(root_a, "dismiss", T_RESERVED, list_mode="down")
        ok(res.get("ok") is True,
           "A1 dismiss of the reserved id answers ok (got %s)" % (res.get("error") or res.get("ok")))
        rows = journal_rows(root_a)
        ok(len(rows) == 1 and rows and rows[0].get("action") == "dismiss"
           and rows[0].get("ticket_id") == T_RESERVED
           and rows[0].get("who") == WHO and rows[0].get("reason") == REASON
           and isinstance(rows[0].get("at"), float),
           "A2 journal FILE carries exactly one full dismiss row (rows=%s)" % len(rows))
        res = call(root_a, "restore", T_RESERVED, reason="undo", list_mode="down")
        ok(res.get("ok") is True, "A3 restore of the inspection-row dismissal answers ok")
        rows = journal_rows(root_a)
        ok(len(rows) == 2 and rows[-1].get("action") == "restore",
           "A4 restore appended the second row, last-row-wins (rows=%s)" % len(rows))
        res = call(root_a, "dismiss", T_RESERVED, list_mode="down")
        ok(res.get("ok") is True,
           "A5 re-dismiss after restore is allowed (reversibility unchanged)")

        # ---------- B. the dev-lane path is unchanged ----------
        section("B dev-lane path unchanged: same journal, same human+reason rules")
        root_b = os.path.join(work, "b")
        os.makedirs(os.path.join(root_b, "inspection"))  # empty store
        base = call(root_b, "dismiss", T_DEV, list_mode="ok",
                    list_ids=json.dumps([T_DEV, "t1610-d2"]))
        ok(base.get("ok") is True,
           "B1 ticket-list-proven id dismisses (got %s)" % (base.get("error") or base.get("ok")))
        rows = journal_rows(root_b)
        ok(len(rows) == 1 and rows[0].get("action") == "dismiss"
           and rows[0].get("ticket_id") == T_DEV,
           "B2 same journal shape for the dev-lane dismissal")
        d0 = _digest(os.path.join(root_b, "journal"))
        for label, kwargs in (
                ("agent-role who refused", {"who": AGENT_WHO}),
                ("empty reason refused", {"reason": ""}),
                ("missing who refused", {"who": ""})):
            res = call(root_b, "dismiss", "t1610-d2", list_mode="ok",
                       list_ids=json.dumps([T_DEV, "t1610-d2"]), **kwargs)
            ok(res.get("ok") is False and bool(str(res.get("error") or "").strip()),
               "B3 %s (err=%s)" % (label, str(res.get("error"))[:80]))
        ok(_digest(os.path.join(root_b, "journal")) == d0,
           "B4 every refusal was zero-write (journal digest identical)")

        # ---------- C. every inspection-source id is dismissible ----------
        section("C population coverage: every id the inspection store vouches for")
        root_c = os.path.join(work, "c")
        _fixture_store(root_c)
        for tid, label in ((T_LIVE, "pointer live ticket_id"),
                           (T_RESERVED, "pointer supersedes id"),
                           (T_SPAWN, "spawn-journal id"),
                           (T_TERM, "reopen terminated id"),
                           (T_NEW, "reopen new id"),
                           (T_C1, "collapsed id 1"), (T_C2, "collapsed id 2")):
            res = call(root_c, "dismiss", tid, reason="coverage %s" % tid,
                       list_mode="down")
            ok(res.get("ok") is True,
               "C %s (%s) dismissible (got %s)" % (label, tid, res.get("error") or "ok"))

        # ---------- D. malformed inspection-store input degrades ----------
        section("D malformed store input: skipped per file/line, never a crash")
        root_d = os.path.join(work, "d")
        _fixture_store(root_d, corrupt=True)
        res = call(root_d, "dismiss", T_RESERVED, list_mode="down")
        ok(res.get("ok") is True,
           "D1 corrupt pointer + garbage journal lines: well-formed id still "
           "dismissible via the remaining testimony (got %s)" % (res.get("error") or "ok"))
        res2 = call(root_d, "dismiss", T_SPAWN, reason="spawn leg", list_mode="down")
        ok(res2.get("ok") is True, "D2 the second spawn row survived the garbage line")
        rows = journal_rows(root_d)
        ok(all(r.get("ticket_id") in (T_RESERVED, T_SPAWN) for r in rows),
           "D3 no phantom rows from the corrupt input (rows=%s)" % len(rows))

        # ---------- E. fail-closed refusals name both sources ----------
        section("E id in neither population: refused by name, never a guess")
        root_e = os.path.join(work, "e")
        _fixture_store(root_e)
        d0 = _digest(os.path.join(root_e, "journal"))
        res = call(root_e, "dismiss", T_GHOST, list_mode="ok",
                   list_ids=json.dumps([T_DEV]))
        err = str(res.get("error") or "")
        ok(res.get("ok") is False, "E1 ghost id refused (err=%s)" % err[:100])
        ok("inspection" in err.lower(),
           "E2 the refusal names the inspection store it checked")
        ok("ticket" in err.lower(),
           "E3 the refusal names the engine ticket population it checked")
        ok(_digest(os.path.join(root_e, "journal")) == d0, "E4 refusal was zero-write")
        res = call(root_e, "dismiss", T_GHOST, list_mode="down")
        ok(res.get("ok") is False and bool(str(res.get("error") or "").strip()),
           "E5 both sources unreadable -> still refused, never silently allowed "
           "(err=%s)" % str(res.get("error"))[:100])
        ok(_digest(os.path.join(root_e, "journal")) == d0, "E6 that refusal too was zero-write")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\nSUMMARY pass=%d fail=%d env_fail=%d na=%d" % (PASS, FAIL, ENV_FAIL, NA))
    if ENV_FAIL:
        return 2
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
