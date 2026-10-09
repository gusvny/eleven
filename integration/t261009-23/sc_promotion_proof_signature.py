#!/usr/bin/env python3
"""sc_promotion_proof_signature.py — a promotion is one named human signature
resting on a named certification, and the record outlives main's history
(t261009-23 spec items (a)(b)(d), design goals 11/14/23-27).

Run directly: python3 integration/t261009-23/sc_promotion_proof_signature.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, real git fixture repos, zero docker/Temporal/
browser, never touches 3099/7233. Both ledgers (delivery + promotion) are
temp files; the real store is never written.

The user-perceivable contract this entry owns (developer L1 owns truth
tables); judged through the public face develop_promote.build_promotion /
record_promotion and the shared append/read store faces:

  A  NO CONTENT WITHOUT A PROOF (b): a promotion that cannot name a
     certification is refused BY NAME (promotion_without_named_certification)
     — never defaulted, never inferred.

  B  an unresolvable proof is still no proof: a certification id that is not
     in the delivery ledger refuses by name (certification_not_in_ledger:…)
     — naming *something* is not proving something.

  C  ONE SIGNATURE, THREE FIELDS (a): a missing signer refuses
     (promotion_missing_signer); on_behalf_of without authority — and the
     reverse — refuses (delegation_incomplete); a recorded delegation keeps
     signer / on_behalf_of / authority as three separate, machine-checkable
     fields on the row.

  D  the promotion is accountable for its batch: a ticket with no landing
     inside the certified revision refuses (tickets_not_covered:<ticket>);
     a main_after that is not the certified revision refuses
     (main_after_not_certified_revision) — main cannot move somewhere the
     proof does not reach.

  E  THE BATCH IS THE HUMAN'S SURFACE (d): on the happy path the row read
     back FROM THE PROMOTION LEDGER FILE ON DISK (reader side, not the
     return value — the writer's ok is not the evidence) carries the
     certification, the tickets, main before/after, the signer, the
     delegation fields and the moment, under a prom- id.

  F  the record survives a rewrite of main's history: after the fixture
     repo's main is reset/recommitted away (the withdrawal shape), the
     promotion ledger on disk is byte-identical — the durable account of
     what a person approved does not live in main.

Intent split: validator matrices, is_green truth tables and projection unit
cases belong to developer L1; this entry owns the reader journey (write one
face, read the file on disk) and the history-rewrite survival face. Pre-
implementation tree = FAIL named (TDD signal); green required at the
integration gate / merge.

Environment: git absent = ENV_FAIL exit 2. develop_promote not landed = FAIL
named, exit 1 (TDD signal, not an environment problem).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

GIT = shutil.which("git")
if GIT is None:
    print("ENV_FAIL: git binary not on PATH (fixture repos cannot be built)")
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

import develop_certify as dc  # noqa: E402  (landed with t261009-19)

try:
    import develop_promote as dp  # noqa: E402
except Exception as exc:
    print("FAIL: develop_promote not landed (TDD signal, pre-implementation "
          "tree): %s" % exc)
    print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
    sys.exit(1)

PASS = 0
FAIL = 0
NA = 0
TMPDIRS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


def tmpdir(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    TMPDIRS.append(d)
    return d


def sh(repo, *argv):
    p = subprocess.run([GIT, *argv], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(argv),
                                                  p.stderr.strip()[:200]))
    return p.stdout.strip()


def build_repo(root):
    sh(root, "init", "-q", "-b", "main")
    sh(root, "config", "user.email", "sc@test.invalid")
    sh(root, "config", "user.name", "sc")
    with open(os.path.join(root, "f.txt"), "w") as fh:
        fh.write("base\n")
    sh(root, "add", "f.txt")
    sh(root, "commit", "-q", "-m", "base")
    return root


def commit(repo, fname, body, msg):
    with open(os.path.join(repo, fname), "w") as fh:
        fh.write(body)
    sh(repo, "add", fname)
    sh(repo, "commit", "-q", "-m", msg)
    return sh(repo, "rev-parse", "HEAD")


def landing_row(ticket, rev, at):
    return {"kind": dc.KIND_LANDING, "id": dc.mint_id("ldg", at),
            "ticket": ticket, "line": LINE,
            "repos": [{"repo": REPO_NAME, "revision": rev}],
            "actor": "sc", "at": at}


def refused(callable_, *a, **kw):
    """Call a public face; return (refused, reason). A PromotionRefused (or
    any PromoteError) is a refusal; a silent success is (False, '')."""
    try:
        callable_(*a, **kw)
    except dp.PromoteError as exc:
        return True, str(exc)
    return False, ""


LINE = "buffer-line"
REPO_NAME = "sandbar"
AT = 1791500000000


DROWS = []


def seeded():
    """A real temp delivery ledger: one landing + one certification over it,
    appended for real through the shared append face (seq assigned)."""
    global DROWS
    d = tmpdir("sc_t26100923_prom_")
    dpath = os.path.join(d, "delivery_ledger.jsonl")
    repo = build_repo(tmpdir("sc_t26100923_git_"))
    rev = sh(repo, "rev-parse", "HEAD")
    cert = dc.build_certification(
        [{"repo": REPO_NAME, "revision": rev}],
        {"id": "run-" + dc.mint_id("x", AT), "cases": {"ran": 3, "pass": 3}},
        booked_red="none", judged_by="sc", at_ms=AT + 1, line=LINE)
    dc.append_rows([landing_row("t-1", rev, AT), cert], dpath)
    DROWS, _bad = dc.read_rows(dpath)
    cert = [r for r in DROWS if r.get("kind") == dc.KIND_CERT][0]
    return repo, rev, cert


def build_kw(cert, rev, **over):
    kw = dict(cert_id=cert["id"], line=LINE, tickets=["t-1"],
              delivery_rows=DROWS,
              main_before=[{"repo": REPO_NAME, "revision": rev}],
              main_after=[{"repo": REPO_NAME, "revision": rev}],
              signer="host", on_behalf_of=None, authority=None,
              note="sc", at_ms=AT + 999)
    kw.update(over)
    return kw


# ---------- A. no content without a proof ----------
section("A a promotion that cannot name a certification refuses BY NAME")
repo, rev, cert = seeded()
try:
    refused_, why = refused(dp.build_promotion,
                            **build_kw(cert, rev, cert_id=None))
    ok(refused_, "A1 promotion without a certification is refused, never "
                 "defaulted (pre-implementation tree is red here: TDD signal)")
    ok("certification" in why,
       "A2 the refusal names WHICH check failed (%r)" % why)
finally:
    pass

# ---------- B. naming a ghost certification is still no proof ----------
section("B an unresolvable certification id refuses by name too")
refused_, why = refused(dp.build_promotion,
                        **build_kw(cert, rev, cert_id="cert-does-not-exist"))
ok(refused_, "B1 a certification id absent from the delivery ledger is "
             "refused (naming something is not proving something)")
ok("not_in_ledger" in why,
   "B2 the refusal names the ledger-resolution check, not a bare no (%r)"
   % why)

# ---------- C. one signature, three fields ----------
section("C signer / delegation / authority are three checks, not one")
r1, w1 = refused(dp.build_promotion, **build_kw(cert, rev, signer=""))
ok(r1 and "signer" in w1,
   "C1 a promotion with no signer refuses by name (%r)" % w1)
r2, _ = refused(dp.build_promotion,
                **build_kw(cert, rev, on_behalf_of="delegate-a"))
r3, _ = refused(dp.build_promotion,
                **build_kw(cert, rev, authority="stand-in order"))
ok(r2 and r3, "C2 on_behalf_of alone and authority alone each refuse — half "
              "a delegation is not a delegation")
row = dp.build_promotion(**build_kw(cert, rev, on_behalf_of="delegate-a",
                                    authority="stand-in order"))
ok(row["signer"] == "host" and row["on_behalf_of"] == "delegate-a"
   and row["authority"] == "stand-in order",
   "C3 a recorded delegation keeps the three fields separate and "
   "machine-checkable (spec (a))")

# ---------- D. the batch is accountable ----------
section("D tickets covered and main_after must match the certification")
r4, w4 = refused(dp.build_promotion,
                 **build_kw(cert, rev, tickets=["t-1", "t-uncovered"]))
ok(r4 and "tickets_not_covered:t-uncovered" in w4,
   "D1 a ticket with no landing inside the certification refuses, naming "
   "the ticket (%r)" % w4)
other = build_repo(tmpdir("sc_t26100923_git2_"))
commit(other, "h.txt", "a genuinely different change\n", "other work")
other_rev = sh(other, "rev-parse", "HEAD")
r5, w5 = refused(dp.build_promotion,
                 **build_kw(cert, rev,
                            main_after=[{"repo": REPO_NAME,
                                         "revision": other_rev}]))
ok(r5 and "main_after" in w5,
   "D2 main_after that is not the certified revision refuses by name — "
   "main cannot move somewhere the proof does not reach (%r)" % w5)

# ---------- E. the human's surface, read back from disk ----------
section("E the record on disk carries the whole batch")
pdir = tmpdir("sc_t26100923_led_")
ppath = os.path.join(pdir, "promotions.jsonl")
before, _b0 = dc.read_rows(ppath)
res = dp.record_promotion(dp.build_promotion(**build_kw(cert, rev)), ppath)
rows, _bx = dc.read_rows(ppath)
ok(len(rows) == len(before) + 1,
   "E1 exactly one new row landed in the promotion ledger file (read back "
   "from disk, reader side — the writer's ok is not the evidence)")
prom = [r for r in rows if str(r.get("id", "")).startswith("prom-")]
ok(len(prom) == 1, "E2 the promotion row carries a prom- id")
p = prom[0]
ok(p.get("certification") == cert["id"]
   and p.get("tickets") == ["t-1"]
   and p.get("main_before") and p.get("main_after")
   and p.get("signer") == "host" and "at" in p and "authority" in p,
   "E3 the record names the certification, the tickets, main before/after, "
   "the signer, the delegation/authority and the moment (spec (d), the "
   "human's whole surface in one row)")

# ---------- F. the record survives a rewrite of main's history ----------
section("F a withdrawal's rewrite of main does not touch the promotion record")
commit(repo, "g.txt", "more work\n", "second commit on main")
sh(repo, "checkout", "-q", "-b", "undo")
sh(repo, "reset", "-q", "--hard", "HEAD~1")
sh(repo, "checkout", "-q", "main")
sh(repo, "reset", "-q", "--hard", "main~1")
commit(repo, "f.txt", "rewritten\n", "history rewritten on main")
rows_after, _bz = dc.read_rows(ppath)
ok(rows_after == rows,
   "F1 the promotion ledger on disk is byte-identical after main's history "
   "was rewritten (the durable account of what a person approved does not "
   "live in main)")

for d in TMPDIRS:
    shutil.rmtree(d, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
sys.exit(0 if FAIL == 0 else 1)
