#!/usr/bin/env python3
"""sc_t26100931_dismiss_journal_contract.py — the ticket dismissal journal and
operation contract (t261009-31).

Run directly: python3 integration/t261009-31/sc_t26100931_dismiss_journal_contract.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal/browser, never
touches 3099.

User story (ticket t261009-31, host order): three failed tickets sit in the left
column forever because the dwell rule treats every non-closed status as open.
The host asked for a dismissal — a human takes the row off the board and it
disappears. This ticket delivers the engine half: an append-only journal, a
reversible last-row-wins reader, and dismiss/restore operations that are a
HUMAN action and never a workflow signal. The dwell rule and the UI control
belong to the staged UI ticket.

This scenario owns the journal + operation contract, judged through the public
functions of server/engine/ticket_dismiss.py (dismiss_ticket / restore_ticket,
approved in the create_plan stage) and through the journal reader's observable
state — never through private helpers, so a contract-preserving refactor (e.g.
renaming internal helpers, reordering refusal checks) must not break it.

Contract faces asserted:

  A  a successful dismissal appends exactly one row
     {at, ticket_id, who, reason, action="dismiss"} and changes NOTHING else
     in a watched workspace root (the journal is the only persisted record;
     never a workflow signal).
  B  refusal matrix, every refusal NAMED and ZERO-WRITE (dir digest identical):
     empty reason (never defaulted), whitespace-only reason, empty who,
     over-bound who (>64), over-bound reason (>2000), unknown ticket,
     repeat-dismiss, restore-when-not-dismissed.
  C  reversibility: dismissal state is decided by the LAST row for the ticket —
     dismiss -> restore -> dismiss again is allowed. Refusing on "any dismiss
     row exists" would contradict the reversibility the ticket was specced for
     (review_plan comment 1).
  D  malformed journal: bad lines are skipped PER LINE but COUNTED, never
     swallowed (a dismissal row is a human disposition voucher); the file stays
     appendable; state still follows the last valid row for that ticket.
  E  an empty/blank ticket_id row is nobody's voucher — it never matches any
     ticket (malformed-row defense carried over from the void face).
  F  an append failure (journal path unwritable) is SURFACED, never a receipt
     that says dismissed with no row written.
  G  module isolation: ticket_dismiss imports neither the inspection family nor
     client.py nor tools/ticket (no inspection dependency, per the dispatch
     spec).

Pre-implementation tree: red is the expected TDD signal; green required at the
integration gate / merge. Engine tree missing = ENV_FAIL exit 2.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MODULE_PATH = ROOT / "server" / "engine" / "ticket_dismiss.py"
ENGINE_DIR = str(ROOT / "server" / "engine")
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)  # the module lazy-imports shared (declared)

PASS = 0
FAIL = 0
NA = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def na(label, reason):
    global NA
    NA += 1
    print("  N/A %s (%s)" % (label, reason))


def section(title):
    print("\n%s" % title)


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


if not (ROOT / "server" / "engine").is_dir():
    env_fail("engine tree missing at %s" % (ROOT / "server" / "engine"))


def load_module():
    if not MODULE_PATH.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ticket_dismiss_itg31", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = load_module()
section("module presence")
ok(MOD is not None, "A0 server/engine/ticket_dismiss.py exists and imports"
   if MOD else "A0 server/engine/ticket_dismiss.py missing (pre-implementation tree, expected TDD red)")

if MOD is not None:

    def find_fn(*names):
        for n in names:
            f = getattr(MOD, n, None)
            if callable(f):
                return f
        return None

    DISMISS = find_fn("dismiss_ticket", "dismiss")
    RESTORE = find_fn("restore_ticket", "restore")
    READER = find_fn("dismissed_row", "last_row", "read_ticket_dismiss_journal", "read_dismiss_journal")

    def call(fn, ticket_id, who, reason, jdir, known):
        """Best-effort keyword adapter over the public op signature: bind the
        journal dir, the known-id roster and the three value slots by parameter
        NAME family so the scenario stays bound to the contract, not to one
        frozen signature."""
        if fn is None:
            return ("error", "operation function missing")
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            sig = None
        kwargs = {}
        pos = []
        if sig is not None:
            taken = 0
            for p in sig.parameters.values():
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                n = p.name.lower()
                if "dir" in n or "journal" in n or "root" in n or "path" in n:
                    kwargs[p.name] = str(jdir)
                elif "known" in n or "roster" in n or "ids" in n:
                    kwargs[p.name] = known
                elif "ticket" in n or n == "id" or n == "tid":
                    kwargs[p.name] = ticket_id
                elif n == "who" or "operator" in n or "by" == n:
                    kwargs[p.name] = who
                elif "reason" in n or "note" in n:
                    kwargs[p.name] = reason
                else:
                    pos.append(p.name)
        try:
            res = fn(ticket_id, who, reason, **kwargs) if not kwargs else fn(**kwargs)
            if isinstance(res, dict):
                okflag = res.get("ok", res.get("dismissed", res.get("restored")))
                if okflag is None:
                    okflag = not any(k in res for k in ("error", "refused", "reason_error"))
                msg = res.get("error") or res.get("refused") or res.get("message") or ""
                if not isinstance(msg, str):
                    msg = json.dumps(msg, ensure_ascii=False)
                return ("ok" if okflag else "error", msg)
            return ("ok", str(res))
        except Exception as exc:  # refusal raised as a named error is a contract shape
            return ("error", "%s: %s" % (type(exc).__name__, exc))

    def interpret(res):
        state, msg = res
        named = bool(str(msg).strip())
        return state == "ok", named, str(msg)

    def dir_digest(root):
        h = hashlib.sha256()
        for p in sorted(Path(root).rglob("*")):
            h.update(str(p.relative_to(root)).encode())
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()

    def journal_rows(jdir):
        p = Path(jdir) / "ticket-dismiss.jsonl"
        if not p.is_file():
            return []
        rows = []
        for line in p.read_text("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"__malformed__": True})
        return rows

    WHO = "host"
    REASON = "dead ticket, host ordered it off the board"
    KNOWN = ["t261009-31", "t260929-11", "t261006-16", "t261005-07"]

    # ---------- A. happy path: one row, nothing else changes ----------
    section("A a dismissal is one journal row and nothing else")
    work = tempfile.mkdtemp(prefix="itg31-dismiss-")
    jdir = os.path.join(work, "state")
    os.makedirs(jdir)
    watch = {}  # watched workspace root: everything except the journal itself
    before_all = dir_digest(work)
    res = call(DISMISS, "t260929-11", WHO, REASON, jdir, KNOWN)
    good, named, msg = interpret(res)
    ok(good, "A1 dismiss of a known ticket succeeds (%s)" % (msg or "ok"))
    rows = [r for r in journal_rows(jdir) if not r.get("__malformed__")]
    ok(len(rows) == 1, "A2 exactly one journal row written (got %d)" % len(rows))
    if rows:
        r0 = rows[0]
        ok(str(r0.get("ticket_id")) == "t260929-11", "A3 row names the ticket")
        ok(str(r0.get("who")) == WHO, "A4 row records who")
        ok(str(r0.get("reason")) == REASON, "A5 row records the reason verbatim")
        ok(str(r0.get("action")) == "dismiss", "A6 row action=dismiss")
        ok("at" in r0, "A7 row carries at")
    else:
        ok(False, "A3-A7 row shape (no row written)")
    after_all = dir_digest(work)
    ok(before_all != after_all, "A8 the journal is the persisted record (workspace changed)")
    ok(sorted(str(p.relative_to(work)) for p in Path(work).rglob("*") if p.is_file())
       == ["state/ticket-dismiss.jsonl"],
       "A9 exactly one new file exists: the journal (never a workflow write)")

    # ---------- B. refusal matrix, named + zero-write ----------
    section("B refusals are named and zero-write")
    cases = [
        ("B1 empty reason refused by name, never defaulted", "t261006-16", WHO, ""),
        ("B2 whitespace-only reason refused by name", "t261006-16", WHO, "   "),
        ("B3 empty who refused by name", "t261006-16", "", REASON),
        ("B4 over-bound who (65 chars) refused by name", "t261006-16", "w" * 65, REASON),
        ("B5 over-bound reason (2001 chars) refused by name", "t261006-16", WHO, "r" * 2001),
        ("B6 unknown ticket refused by name", "t269999-99", WHO, REASON),
        ("B7 repeat-dismiss refused by name (last row already dismiss)", "t260929-11", WHO, REASON),
    ]
    for label, tid, w, rs in cases:
        d0 = dir_digest(jdir)
        res = call(DISMISS, tid, w, rs, jdir, KNOWN)
        good, named, msg = interpret(res)
        ok(not good and named, "%s (got: %s)" % (label, msg or "SILENT/OK"))
        ok(dir_digest(jdir) == d0, "%s -- zero-write" % label.split(" refused")[0])

    # ---------- C. reversibility: last row wins ----------
    section("C reversibility: last row for the ticket decides")
    d0 = dir_digest(jdir)
    res = call(RESTORE, "t260929-11", WHO, "host restored it for re-triage", jdir, KNOWN)
    good, named, _ = interpret(res)
    ok(good, "C1 restore after dismiss succeeds")
    res = call(RESTORE, "t260929-11", WHO, "second restore attempt", jdir, KNOWN)
    good, named, msg = interpret(res)
    ok(not good and named, "C2 restore-when-not-dismissed refused by name (%s)" % (msg or "SILENT/OK"))
    res = call(DISMISS, "t260929-11", WHO, "dismissed again after restore", jdir, KNOWN)
    good, _, msg = interpret(res)
    ok(good, "C3 re-dismiss after restore is ALLOWED (last-wins, not ever-dismissed) (%s)" % (msg or "refused"))
    rows = [r for r in journal_rows(jdir) if not r.get("__malformed__")]
    last = [r for r in rows if r.get("ticket_id") == "t260929-11"][-1:]
    ok(last and last[0].get("action") == "dismiss", "C4 the last row for the ticket is the state")
    if READER is not None:
        try:
            allrows = READER(jdir) if len(inspect.signature(READER).parameters) >= 1 else None
            ok(True, "C5 reader callable on the journal dir (contract entry present)")
        except Exception as exc:
            ok(False, "C5 reader raised on a valid journal: %s" % exc)
    else:
        na("C5 reader entry point", "reader function not discoverable by contract name")

    # ---------- D. malformed journal ----------
    section("D malformed lines are counted, never swallowed")
    d1 = os.path.join(work, "state-malformed")
    os.makedirs(d1)
    jp = Path(d1) / "ticket-dismiss.jsonl"
    jp.write_text(
        "{not json at all\n"
        + json.dumps({"at": 1.0, "ticket_id": "t261006-16", "who": "host",
                      "reason": "first dismiss", "action": "dismiss"}) + "\n"
        + "[1,2,3]\n"
        + "\n"
        + json.dumps({"at": 2.0, "ticket_id": "t261006-16", "who": "host",
                      "reason": "host restored it", "action": "restore"}) + "\n",
        encoding="utf-8")
    if READER is not None:
        try:
            sigp = inspect.signature(READER).parameters
            if any("malformed" in n for n in sigp):
                out = READER(d1, with_malformed=True)
                got = out[1] if isinstance(out, tuple) and len(out) > 1 else None
                ok(got == 2, "D1 two bad lines COUNTED (got %r)" % got)
            else:
                out = READER(d1)
                ok(isinstance(out, list) and len(out) == 2,
                   "D1 reader tolerates malformed lines and returns the valid rows (got %r)" % (out,))
        except Exception as exc:
            ok(False, "D1 reader raised on a malformed journal: %s" % exc)
        # the file stays appendable after malformed content
        res = call(DISMISS, "t261005-07", WHO, REASON, d1, KNOWN)
        good, _, msg = interpret(res)
        ok(good, "D2 a malformed existing file stays appendable (%s)" % (msg or "refused"))
        if good:
            ok((Path(d1) / "ticket-dismiss.jsonl").read_text("utf-8").startswith("{not json"),
               "D3 append never rewrote the malformed head")
    else:
        na("D1-D3 malformed-journal reader face", "reader function not discoverable")

    # ---------- E. empty ticket_id row is nobody's voucher ----------
    section("E an empty ticket_id row never matches")
    d2 = os.path.join(work, "state-emptytid")
    os.makedirs(d2)
    jp = Path(d2) / "ticket-dismiss.jsonl"
    jp.write_text(json.dumps({"at": 1.0, "ticket_id": "", "who": "host",
                              "reason": "corrupt row", "action": "dismiss"}) + "\n",
                  encoding="utf-8")
    if READER is not None:
        try:
            out = READER(d2)
            rows2 = out[0] if isinstance(out, tuple) else out
            ok(isinstance(rows2, list) and len(rows2) == 1,
               "E1 corrupt row is still read back (counted, not dropped silently)")
        except Exception as exc:
            ok(False, "E1 reader raised on the corrupt row: %s" % exc)
    else:
        na("E1 corrupt-row read-back", "reader function not discoverable")
    res = call(DISMISS, "t261005-07", WHO, REASON, d2, KNOWN)
    good, _, _ = interpret(res)
    ok(good, "E2 a corrupt empty-ticket_id row does not shadow a real dismissal")

    # ---------- F. append failure is surfaced ----------
    section("F a failed append is never a success receipt")
    d3 = os.path.join(work, "state-blocked")
    os.makedirs(d3)
    (Path(d3) / "ticket-dismiss.jsonl").mkdir()  # journal path occupied by a dir
    res = call(DISMISS, "t260929-11", WHO, REASON, d3, KNOWN)
    good, _, msg = interpret(res)
    ok(not good and bool(str(msg).strip()),
       "F1 occupied journal path -> named failure, never ok (%s)" % (msg or "SILENT OK"))

    # ---------- G. module isolation ----------
    section("G no inspection dependency, never a workflow signal")
    src = MODULE_PATH.read_text("utf-8")
    import_lines = [l.strip() for l in src.splitlines()
                    if l.strip().startswith(("import ", "from "))]
    banned = ("inspection", "client", "dev_lane", "agent_activities", "workflows")
    bad_imports = [l for l in import_lines if any(b in l for b in banned)]
    ok(not bad_imports, "G1 no inspection/client/workflow imports (hits: %s)" % bad_imports)
    # a rejection WORD in a docstring ("never a workflow signal") is honest copy,
    # not a signal — judge call-shaped usage, not vocabulary
    for needle in (r"\bsignal\s*\(", r"\bterminate\s*\(", r"cancel_notice"):
        ok(re.search(needle, src) is None, "G2 no call-shaped workflow %s" % needle.strip("\\b("))

    shutil.rmtree(work, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
sys.exit(1 if FAIL else 0)
