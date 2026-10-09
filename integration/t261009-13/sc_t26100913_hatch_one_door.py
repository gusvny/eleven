#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100913_hatch_one_door.py — t261009-13 Part 1: the repair hatch is one
host-authorised door that a ticket can never open.

Grey-box L3, offline seconds (zero docker, zero Temporal, zero browser, zero
contact with 3099/7233). Drives the PUBLIC op face only: `python3
server/tools/ticket.py '<json>'` as a child process, with an isolated projects
root (SANDBAR_PROJECTS_DIR, mkdtemp, removed in finally). Assertions land on
user-perceivable behavior: the receipt, the on-disk record read back from its
absolute path (reader-side evidence — the writer's ok:true is never proof), and
the hatch_debts read face. Perceived behavior change under test (buffer design
rule 26 / goal 26, slice 1 a+b): today a repair is ad hoc and its why lives in
a conversation; slice 1 makes it one op that demands who/why/breakage/
revisions/expiry and refuses a call that originates from a ticket's own path.

Legs:
  H1 host authorisation journey: a valid repair_hatch from a non-ticket cwd
     answers ok and lands EXACTLY ONE record at the project store path; the
     record, read back from the file (not the receipt), carries who, the
     breakage, the revision set, the expiry and the moment — the act is
     auditable without reading any conversation.
  H2 the same act is visible as an outstanding certification debt on the
     hatch_debts read face (count 1, the debt names the revision and the
     authority) — the debt exists from the moment the door opens.
  H3 ticket origin refused BY NAME: the identical payload fired with the child
     cwd inside a `.lane/` worktree path is refused with a reason naming the
     ticket-path rule, and the store is byte-identical afterwards (a refused
     call writes nothing); the same payload from the repo root succeeds
     (control: the guard judges the ORIGIN, not the payload).
  H4 no self-authorisation: who = an agent role name, and who with the
     `-agent` suffix (mixed case), are each refused by name and write nothing —
     a ticket/agent may never open the hatch for itself (the same rule the
     existing authorize op carries, mirrored at this layer).

Three-state discipline (t260904-12): python3 or the ticket.py entry missing =
ENV_FAIL exit 2; the op face not landed (unknown-op / no refusal name / no
record) = FAIL exit 1 with the leg named — TDD-phase red is expected until
implement lands; must be green by arbitrate/merge.

intent 分工: field-by-field malformed truth tables, append-only byte
discipline, fail-closed corrupt-line and coverage-clearing semantics belong to
sc_t26100913_hatch_audit_debt_face (same ticket) and developer L1
(integration/tests/test_t261009_13_repair_hatch.py); this scenario owns only
the one-door journey: authorised, recorded, origin-guarded, agent-proof.
Reason text anchors are semantic (KI-051 discipline): a leg's refusal must
NAME its rule, never a bare crash — exact wording is not pinned.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TICKET_CLI = os.path.join(REPO, "server", "tools", "ticket.py")

PROJECT_KEY = "t26100913-hatch"
FUTURE_EXPIRY = int(time.time()) + 3600


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def fail(leg, msg):
    print("FAIL [%s] %s" % (leg, msg))
    sys.exit(1)


def call_cli(payload, cwd):
    """One public-face round: returns (rc, stdout-text). Non-JSON / crash is
    surfaced to the caller, never swallowed."""
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = PROJECTS_ROOT
    env.pop("SANDBAR_TASK_QUEUE", None)
    p = subprocess.run([sys.executable, TICKET_CLI, json.dumps(payload)],
                       cwd=cwd, env=env, capture_output=True, text=True,
                       timeout=120)
    return p.returncode, p.stdout


def parsed(rc, out):
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:
        return None


def store_path():
    return os.path.join(PROJECTS_ROOT, PROJECT_KEY, "hatch", "hatch_records.jsonl")


def read_store_bytes():
    p = store_path()
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def valid_payload(who="host"):
    return {"op": "repair_hatch", "project": PROJECT_KEY, "by": who,
            "reason": "red main after buffer landing, host ordered repair",
            "breakage": {"description": "engine ticket-list starves under "
                                        "query load (KI-018 family)"},
            "revisions": ["abc1234"],
            "expires": FUTURE_EXPIRY}


def main():
    if not os.path.isfile(TICKET_CLI):
        env_fail("ticket.py CLI missing: %s" % TICKET_CLI)
    if shutil.which("python3") is None and sys.executable is None:
        env_fail("python3 unavailable")

    # ---- H1: host authorisation lands one auditable record (reader-side) ----
    rc, out = call_cli(valid_payload(), cwd=REPO)
    body = parsed(rc, out)
    if body is None:
        fail("H1", "op face produced no JSON receipt (rc=%s, tail=%r)"
             % (rc, out[-300:]))
    if body.get("ok") is not True and body.get("status") not in ("ok",):
        fail("H1", "valid host authorisation refused: %r" % (body,))
    raw = read_store_bytes()
    if raw is None:
        fail("H1", "no record file at the project store path %s — the writer "
                   "says ok but the reader sees nothing (t261004-27 lesson)"
             % store_path())
    lines = [ln for ln in raw.decode("utf-8", "replace").splitlines() if ln.strip()]
    if len(lines) != 1:
        fail("H1", "expected exactly one record, found %d" % len(lines))
    try:
        rec = json.loads(lines[0])
    except Exception as e:
        fail("H1", "record is not one JSON line: %s" % e)
    for field in ("by", "revisions", "expires", "at", "id"):
        if not rec.get(field):
            fail("H1", "record missing auditable field %r (have keys %s)"
                 % (field, sorted(rec.keys())))
    if "abc1234" not in [str(r) for r in rec["revisions"]]:
        fail("H1", "record does not name the revision it will land: %r"
             % (rec["revisions"],))
    brk = rec.get("breakage") or {}
    if not (brk.get("description") or brk.get("known_issue")):
        fail("H1", "record does not name the breakage it repairs: %r" % (brk,))
    if str(rec.get("by") or "") != "host":
        fail("H1", "recorded authority is not the host identity: %r"
             % (rec.get("by"),))

    # ---- H2: the act reads back as an outstanding certification debt ----
    rc, out = call_cli({"op": "hatch_debts", "project": PROJECT_KEY}, cwd=REPO)
    body = parsed(rc, out)
    if body is None:
        fail("H2", "hatch_debts read face produced no JSON receipt")
    if body.get("ok") is not True and body.get("status") not in ("ok",):
        fail("H2", "hatch_debts refused a plain read: %r" % (body,))
    debts = (body.get("debts") or body.get("result", {}).get("debts")
             if isinstance(body.get("result"), dict) else body.get("debts"))
    if debts is None and isinstance(body.get("result"), dict):
        debts = body["result"].get("debts")
    if not debts:
        fail("H2", "the debt the door just opened is not on the outstanding "
                   "list: %r" % (body,))
    d = debts[0]
    if "abc1234" not in [str(r) for r in (d.get("revisions") or [])]:
        fail("H2", "outstanding debt does not name the revision: %r" % (d,))
    if d.get("outstanding") is False:
        fail("H2", "an uncovered debt reads as covered: %r" % (d,))

    # ---- H3: ticket-origin cwd refused by name, store untouched ----
    before = read_store_bytes()
    fake_lane = os.path.join(tmp, "fakerepo", ".lane", "t261009-13-fakelane")
    os.makedirs(fake_lane, exist_ok=True)
    rc, out = call_cli(valid_payload(), cwd=fake_lane)
    body = parsed(rc, out)
    refused_txt = (json.dumps(body, ensure_ascii=False) if body else out)
    if body is not None and (body.get("ok") is True
                             or body.get("status") in ("ok",)):
        fail("H3", "a call originating from a ticket path succeeded — the "
                   "hatch is reachable from a ticket: %r" % (body,))
    low = refused_txt.lower()
    if not ("lane" in low or "ticket" in low):
        fail("H3", "refusal does not name the ticket-path rule: %r"
             % (refused_txt[:300],))
    if read_store_bytes() != before:
        fail("H3", "the refused ticket-origin call changed the store")
    rc, out = call_cli(valid_payload(who="host-2"), cwd=REPO)
    body = parsed(rc, out)
    if body is None or not (body.get("ok") is True
                            or body.get("status") in ("ok",)):
        fail("H3", "control: the same payload from the repo root must pass "
                   "(the guard judges origin, not payload): %r" % (body,))

    # ---- H4: no self-authorisation (agent role name / -agent suffix) ----
    before = read_store_bytes()
    for bad in ("developer", "integration", "Host-Agent", "lane-agent"):
        rc, out = call_cli(valid_payload(who=bad), cwd=REPO)
        body = parsed(rc, out)
        txt = (json.dumps(body, ensure_ascii=False) if body else out).lower()
        if body is not None and (body.get("ok") is True
                                 or body.get("status") in ("ok",)):
            fail("H4", "who=%r was accepted — an agent opened the hatch" % bad)
        if not ("agent" in txt or "role" in txt or "author" in txt):
            fail("H4", "who=%r refused without naming the self-authorisation "
                       "rule: %r" % (bad, txt[:300]))
    if read_store_bytes() != before:
        fail("H4", "a refused self-authorisation changed the store")

    print("PASS: repair hatch is one host-authorised door — recorded "
          "reader-side (H1), outstanding debt visible (H2), ticket origin "
          "refused by name (H3), agent identities refused (H4)")
    sys.exit(0)


tmp = tempfile.mkdtemp(prefix="sc_t26100913_")
PROJECTS_ROOT = os.path.join(tmp, "projects")
os.makedirs(PROJECTS_ROOT, exist_ok=True)
try:
    main()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
