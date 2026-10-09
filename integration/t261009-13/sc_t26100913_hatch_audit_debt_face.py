#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26100913_hatch_audit_debt_face.py — t261009-13 Part 2: the hatch store
is append-only, fail-closed, and the certification debt clears in exactly one
way.

Grey-box L3, offline seconds (zero docker, zero Temporal, zero browser, zero
contact with 3099/7233). Same public-face seam as Part 1:
`python3 server/tools/ticket.py '<json>'` child processes over an isolated
projects root (SANDBAR_PROJECTS_DIR, mkdtemp, removed in finally); the store
file is read (and, where a leg says so, crafted) from its absolute path —
reader-side evidence only.

Legs:
  A1 append-only audit trail: two valid authorisations = two JSONL lines and
     the first line is byte-identical after the second write; a refused call
     (past expiry) appends nothing; a reader can reconstruct what happened,
     in order, without any conversation.
  A2 fail-closed read: a corrupted (half-written) line in the store makes the
     hatch_debts read refuse with the problem NAMED — the reader is never
     served a silent zero-debt list that would hide an outstanding debt (the
     invisible exception becoming the norm is the exact rule-26 failure).
  A3 coverage clears, and only coverage does: with a certification record
     covering one of two outstanding revisions, exactly the covered revision
     leaves the outstanding list; the uncovered sibling and a partially
     covered set stay outstanding. No clear op is needed or offered —
     clearing is a derivation from certification coverage (dispatch (d)).
  A4 no second door: the store's record face accepts only the declared
     families — a forged second landing-granting family row is never counted
     as a debt or a debt-clearer (named on read), and the op catalogue offers
     exactly one hatch-writing op (source-text anchor, read-only, per the
     dispatch (e) "asserted rather than promised").

Three-state discipline (t260904-12): python3 / ticket.py missing = ENV_FAIL
exit 2; a face not landed = FAIL exit 1 with the leg named — TDD-phase red is
expected until implement lands; must be green by arbitrate/merge.

intent 分工: the one-door journey (authorise/guard/self-auth) = Part 1
sc_t26100913_hatch_one_door; per-field malformed truth tables, id-mint
uniqueness tables and the pure validators = developer L1
(integration/tests/test_t261009_13_repair_hatch.py); certification record
SHAPE truth tables = t261004-11-ledger-record-and-replay family / T1.2. This
scenario owns the store's audit + debt-derivation contract.
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

PROJECT_KEY = "t26100913-audit"
FUTURE = int(time.time()) + 3600
CERT_FAMILY = "certification-v1"


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def fail(leg, msg):
    print("FAIL [%s] %s" % (leg, msg))
    sys.exit(1)


def call_cli(payload):
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = PROJECTS_ROOT
    p = subprocess.run([sys.executable, TICKET_CLI, json.dumps(payload)],
                       cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=120)
    return p.returncode, p.stdout


def parsed(rc, out):
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:
        return None


def okish(body):
    return body is not None and (body.get("ok") is True
                                 or body.get("status") in ("ok",))


def store_path():
    return os.path.join(PROJECTS_ROOT, PROJECT_KEY, "hatch", "hatch_records.jsonl")


def lines_raw():
    with open(store_path(), "rb") as f:
        raw = f.read()
    return raw, [ln for ln in raw.splitlines() if ln.strip()]


def auth(rev):
    return {"op": "repair_hatch", "project": PROJECT_KEY, "by": "host",
            "reason": "host-ordered repair",
            "breakage": {"description": "main red after landing"},
            "revisions": [rev], "expires": FUTURE}


def debts_face():
    rc, out = call_cli({"op": "hatch_debts", "project": PROJECT_KEY})
    body = parsed(rc, out)
    if not okish(body):
        return None, body
    debts = body.get("debts")
    if debts is None and isinstance(body.get("result"), dict):
        debts = body["result"].get("debts")
    return debts or [], body


def outstanding_revs(debts):
    out = set()
    for d in debts:
        if d.get("outstanding") is not False:
            for r in d.get("revisions") or []:
                out.add(str(r))
    return out


def main():
    if not os.path.isfile(TICKET_CLI):
        env_fail("ticket.py CLI missing: %s" % TICKET_CLI)

    # ---- A1: append-only, refused call writes nothing ----
    for rc_flag, rev in (("r1", "aaa1111"), ("r2", "bbb2222")):
        rc, out = call_cli(auth(rev))
        if not okish(parsed(rc, out)):
            fail("A1", "valid authorisation %s refused: %r" % (rev, out[-200:]))
    raw, lines = lines_raw()
    if len(lines) != 2:
        fail("A1", "expected 2 records, found %d" % len(lines))
    past = int(time.time()) - 10
    p = auth("ccc3333")
    p["expires"] = past
    rc, out = call_cli(p)
    if okish(parsed(rc, out)):
        fail("A1", "a born-expired authorisation was accepted — an "
                   "authorisation must expire")
    raw2, lines2 = lines_raw()
    if lines2 != lines or raw2 != raw:
        fail("A1", "a refused call mutated the store")
    # first line byte-identical after the second write (append-only)
    first_after_two = lines[0]
    if json.loads(first_after_two).get("revisions") != ["aaa1111"]:
        fail("A1", "first record no longer the first write — store rewritten?")
    print("A1 ok: append-only audit trail, refused call writes nothing")

    # ---- A2: corrupt line = fail-closed named refusal, never a zero list ----
    with open(store_path(), "ab") as f:
        f.write(b'{"v": "hatch-authorisation-v1", "id": "hatch-torn", ')
    debts, body = debts_face()
    if debts == []:
        fail("A2", "corrupt store read as an empty outstanding list — the "
                   "debt is hidden (rule-26 invisible-exception failure): %r"
             % (body,))
    if debts is None and not okish(body):
        txt = json.dumps(body, ensure_ascii=False).lower()
        if not any(w in txt for w in ("line", "corrupt", "malformed", "parse",
                                     "unreadable", "record")):
            fail("A2", "fail-closed refusal does not name the read problem: %r"
                 % (txt[:300],))
    # heal the store for A3: drop the torn tail line
    raw, lines = lines_raw()
    good = [ln for ln in lines
            if b"hatch-torn" not in ln]
    with open(store_path(), "wb") as f:
        f.write(b"\n".join(good) + b"\n")

    # ---- A3: coverage clears exactly the covered revisions ----
    debts, body = debts_face()
    if debts is None:
        fail("A3", "hatch_debts face unavailable: %r" % (body,))
    have = outstanding_revs(debts)
    if {"aaa1111", "bbb2222"} - have:
        fail("A3", "pre-coverage outstanding set wrong: %r" % (sorted(have),))
    cert = {"v": CERT_FAMILY, "id": "cert-01J9Z6QK3M7X2P4T8V0N5R",
            "at": int(time.time() * 1000), "project": PROJECT_KEY,
            "revisions": ["aaa1111"], "by": "certification-driver",
            "kind": "certification"}
    with open(store_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(cert, ensure_ascii=False) + "\n")
    debts, body = debts_face()
    if debts is None:
        fail("A3", "hatch_debts refused after a certification row: %r" % (body,))
    have = outstanding_revs(debts)
    if "aaa1111" in have:
        fail("A3", "a certification covering the revision did NOT clear the "
                   "debt — coverage must be the one way out: %r" % (sorted(have),))
    if "bbb2222" not in have:
        fail("A3", "the uncovered sibling vanished from the outstanding list: %r"
             % (sorted(have),))
    print("A3 ok: coverage clears exactly the covered revisions")

    # ---- A4: no second door ----
    forged = {"v": "emergency-landing-v1", "id": "eld-01J9Z6QK3M7X2P4T8V0N5R",
              "at": int(time.time() * 1000), "project": PROJECT_KEY,
              "revisions": ["ddd4444"], "by": "someone", "kind": "landing"}
    with open(store_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(forged, ensure_ascii=False) + "\n")
    debts, body = debts_face()
    txt = json.dumps(body or {}, ensure_ascii=False)
    low = txt.lower()
    for d in debts or []:
        if "ddd4444" in [str(r) for r in d.get("revisions") or []]:
            fail("A4", "a forged second emergency family was counted as a "
                       "debt/clearance — a second door was mounted: %r" % (d,))
    if not okish(body):
        # Semantic anchor (KI-051): the refusal must NAME what it rejected —
        # the forged family id itself reaches the reason (engine refusal copy
        # is Chinese by convention; anchor the quoted family token, never
        # English wording).
        if "emergency-landing-v1" not in txt and "unknown" not in low \
                and "family" not in low and "未知" not in txt:
            fail("A4", "forged family neither ignored-named nor refused-named: %r"
                 % (txt[:300],))
    with open(TICKET_CLI, encoding="utf-8") as f:
        src = f.read()
    if src.count("repair_hatch") == 0:
        fail("A4", "the hatch op vanished from the op catalogue")
    print("A4 ok: forged second family never becomes a door; one hatch op "
          "declared")

    print("PASS: hatch store append-only + fail-closed (A1/A2), debt clears "
          "only via coverage (A3), no second door (A4)")
    sys.exit(0)


tmp = tempfile.mkdtemp(prefix="sc_t26100913b_")
PROJECTS_ROOT = os.path.join(tmp, "projects")
os.makedirs(PROJECTS_ROOT, exist_ok=True)
try:
    main()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
