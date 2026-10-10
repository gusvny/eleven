#!/usr/bin/env python3
"""sc_outcome_three_stages_withdrawal.py — a ticket's outcome says landed /
certified / delivered separately, and a withdrawal is work whose relation
guards main (t261009-23 spec items (c)(e), design goals 14/25-27).

Run directly:
python3 integration/t261009-23/sc_outcome_three_stages_withdrawal.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, real git fixture repos, zero docker/Temporal/
browser, never touches 3099/7233. Both ledgers (delivery + promotion) are
temp files; the real store is never written.

The user-perceivable contract this entry owns, judged through the public
faces develop_promote.ticket_outcome / record_relation / check_withdrawn:

  A  THE THREE STAGES STAY DISTINCT (c): ticket_outcome reports landed_at,
     certified_by and delivered_in as three INDEPENDENT fields — a ticket
     that ended at certification is NOT reported as delivered, and after a
     promotion only the delivered stage moves.

  B  WITHDRAWAL IS WORK, NOT A RECORD TYPE (e): a withdrawal is recorded as
     a rel- relation row (kind field withdraws, with a recorder and a
     reason) in the promotion ledger, and no revert record family appears
     anywhere.

  C  the promotion guard actually fires: check_withdrawn refuses — by name,
     citing the relation — a candidate whose landing re-introduces a
     withdrawn patch (patch identity = git diff-tree -p --root | git
     patch-id --stable); an unrelated landing is allowed, so the guard is
     neither absent nor a content freeze of everything.

  D  the relation is checked, not skipped: a withdraws relation naming a
     ticket with no landing is a loud WithdrawnTargetUnknown, never a silent
     skip that empties the guard.

  E  the guard never degrades: when the patch identity cannot be computed
     (injected failing patch-id face) the check refuses with a NAMED
     PatchIdUnavailable — an empty guard set would silently allow the very
     re-introduction spec (e) forbids.

Intent split: projection truth tables and patch-id unit computation belong
to developer L1 (test_t261009_23_promote.py); relation vocabulary and
corrections belong to the record-models family; this entry owns the
outcome-distinctness journey and the withdrawal-propagation face. Pre-
implementation tree = FAIL named (TDD signal); green required at the
integration gate / merge.

Environment: git absent = ENV_FAIL exit 2. develop_promote not landed = FAIL
named, exit 1 (TDD signal).
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

import develop_certify as dc  # noqa: E402

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


LINE = "buffer-line"
REPO_NAME = "sandbar"


def landing_row(ticket, rev, at):
    return {"kind": dc.KIND_LANDING, "id": dc.mint_id("ldg", at),
            "ticket": ticket, "line": LINE,
            "repos": [{"repo": REPO_NAME, "revision": rev}],
            "actor": "sc", "at": at}


def certify(rows, rev, at):
    rows.append(dc.build_certification(
        [{"repo": REPO_NAME, "revision": rev}],
        {"id": "run-" + dc.mint_id("x", at), "cases": {"ran": 2, "pass": 2}},
        booked_red="none", judged_by="sc", at_ms=at + 1, line=LINE))


def promote(ppath, cert, rev, tickets, at, drows=()):
    dp.append_rows([dp.build_promotion(
        cert["id"], LINE, tickets,
        [{"repo": REPO_NAME, "revision": rev}],
        [{"repo": REPO_NAME, "revision": rev}],
        signer="host", note="sc", at_ms=at, delivery_rows=drows)], ppath)


def patch_of(repo, rev):
    """The patch identity the guard is anchored to (the same recipe the
    module documents: diff-tree -p --root piped through patch-id --stable)."""
    diff = subprocess.run([GIT, "diff-tree", "-p", "--root", rev], cwd=repo,
                          capture_output=True, text=True)
    pid = subprocess.run([GIT, "patch-id", "--stable"], cwd=repo,
                         input=diff.stdout, capture_output=True, text=True)
    return pid.stdout.split()[0] if pid.stdout.split() else ""


# ---------- A. the three stages stay distinct ----------
section("A landed / certified / delivered are three answers, never one")
d = tmpdir("sc_t26100923_wd_")
repo = build_repo(tmpdir("sc_t26100923_git_"))
try:
    rev = sh(repo, "rev-parse", "HEAD")
    drows = [landing_row("t-a", rev, 1791510000000)]
    certify(drows, rev, 1791510001000)
    dpath = os.path.join(d, "delivery_ledger.jsonl")
    dc.append_rows(drows, dpath)
    drows, _bad = dc.read_rows(dpath)
    ppath = os.path.join(d, "promotions.jsonl")
    prows0, _bp = dc.read_rows(ppath)
    out = dp.ticket_outcome(drows + prows0, "t-a")
    ok(bool(out.get("landed_at")) and bool(out.get("certified_by"))
       and not out.get("delivered_in"),
       "A1 a ticket that ended at certification shows landed + certified but "
       "NOT delivered (a closed ticket is never mistaken for a delivered one)")
    ok("delivered_in" in out and "reverted_at" in out
       and "waiting_since" in out,
       "A2 the outcome carries the stage fields separately (independent "
       "fields, not one collapsed status enum)")
    ok(out.get("waiting_since") is None,
       "A3 a certified ticket is not reported as waiting (waiting vs stuck "
       "is sayable)")
    cert = [r for r in drows if r.get("kind") == dc.KIND_CERT][0]
    promote(ppath, cert, rev, ["t-a"], 1791510002000, drows=drows)
    prows1, _bq = dc.read_rows(ppath)
    out2 = dp.ticket_outcome(drows + prows1, "t-a")
    ok(str(out2.get("delivered_in", "")).startswith("prom-")
       and out2.get("landed_at") == out.get("landed_at")
       and out2.get("certified_by") == out.get("certified_by"),
       "A4 after the promotion only the delivered stage moves — the landing "
       "and certification answers are unchanged")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- B. withdrawal is work, not a record type ----------
section("B the withdrawal lands a relation; no revert record family appears")
d = tmpdir("sc_t26100923_wd2_")
repo = build_repo(tmpdir("sc_t26100923_git2_"))
try:
    rev = sh(repo, "rev-parse", "HEAD")
    dpath = os.path.join(d, "delivery_ledger.jsonl")
    dc.append_rows([landing_row("t-b", rev, 1791510100000)], dpath)
    ppath = os.path.join(d, "promotions.jsonl")
    rel = dp.record_relation("withdraws", from_ticket="t-withdraw-work",
                             to_ticket="t-b", recorded_by="host",
                             reason="the fix broke the build",
                             evidence={"what": "ticket", "ref": "t-b"},
                             at_ms=1791510102000)
    dp.append_rows([rel], ppath)
    prows, _bad = dc.read_rows(ppath)
    rels = [r for r in prows if str(r.get("id", "")).startswith("rel-")]
    ok(len(rels) == 1 and rels[0].get("kind") == "withdraws"
       and bool(rels[0].get("reason")) and bool(rels[0].get("recorded_by")),
       "B1 the withdrawal is recorded as a relation row (rel-, kind "
       "withdraws, with a recorder and a reason)")
    ok(not any(r.get("kind") in ("revert", "withdrawal") for r in prows)
       and not any(str(r.get("id", "")).startswith(("rvv-", "rv-"))
                   for r in prows),
       "B2 no revert record family exists in either ledger (spec (e): "
       "withdrawal is work, not a record type)")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- C. the promotion guard actually fires ----------
section("C re-introducing a withdrawn patch is refused by name")
repo = build_repo(tmpdir("sc_t26100923_git3_"))
try:
    bad_rev = commit(repo, "bad.txt", "the mistake\n", "the withdrawn landing")
    # the withdrawal: a LATER ticket's work undoes the landing (revert commit)
    undo_rev = subprocess.run([GIT, "rm", "-q", "bad.txt"], cwd=repo,
                              capture_output=True, text=True).returncode         if False else None
    subprocess.run([GIT, "rm", "-q", "bad.txt"], cwd=repo, capture_output=True)
    with open(os.path.join(repo, "undo.txt"), "w") as fh:
        fh.write("the undo ticket's own marker\n")
    sh(repo, "add", "undo.txt")
    sh(repo, "commit", "-q", "-m", "revert the withdrawn landing")
    # the re-introduction: the withdrawn patch comes back as NEW work
    # (cherry-pick = a fresh commit carrying the same content change)
    p = subprocess.run([GIT, "cherry-pick", bad_rev], cwd=repo,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("fixture cherry-pick failed: %s" % p.stderr[:200])
    again = sh(repo, "rev-parse", "HEAD")
    ok(patch_of(repo, again) == patch_of(repo, bad_rev),
       "C1 fixture sanity: the re-introduced revision carries the withdrawn "
       "landing's patch id")
    good_rev = commit(repo, "other.txt", "unrelated\n", "unrelated work")
    d = tmpdir("sc_t26100923_wd3_")
    dpath = os.path.join(d, "delivery_ledger.jsonl")
    dc.append_rows([landing_row("t-c", bad_rev, 1791510200000),
                    landing_row("t-again", again, 1791510200001),
                    landing_row("t-ok", good_rev, 1791510200002)], dpath)
    ppath = os.path.join(d, "promotions.jsonl")
    rel = dp.record_relation("withdraws", from_ticket="t-withdraw-work",
                             to_ticket="t-c", recorded_by="host",
                             reason="the fix broke the build",
                             evidence={"what": "ticket", "ref": "t-c"},
                             at_ms=1791510202000)
    dp.append_rows([rel], ppath)
    drows, _b1 = dc.read_rows(dpath)
    prows, _b2 = dc.read_rows(ppath)
    pid_fn = lambda revision, name: dp.patch_id(revision, repo)  # noqa: E731

    refused_, why = False, ""
    try:
        dp.check_withdrawn("t-again", drows + prows, pid_fn, REPO_NAME)
    except dp.PromoteError as exc:
        refused_, why = True, str(exc)
    ok(refused_ and "withdrawn_patch_present" in why,
       "C2 a candidate whose content re-introduces the withdrawn patch is "
       "refused by name (%r)" % why)
    ok("rel-" in why,
       "C3 the refusal cites the relation it rests on, never a bare no")
    allowed = True
    try:
        dp.check_withdrawn("t-ok", drows + prows, pid_fn, REPO_NAME)
    except dp.PromoteError:
        allowed = False
    ok(allowed, "C4 an unrelated landing is allowed (the guard is not a "
                "content freeze of everything)")
finally:
    shutil.rmtree(repo, ignore_errors=True)

# ---------- D. an unknown withdrawal target is loud, never a skip ----------
section("D a relation naming an unknown landing is a loud error")
d = tmpdir("sc_t26100923_wd4_")
ppath = os.path.join(d, "promotions.jsonl")
rel = dp.record_relation("withdraws", from_ticket="t-withdraw-work",
                         to_ticket="t-never-landed", recorded_by="host",
                         reason="r", evidence={"what": "ticket", "ref": "t-never-landed"},
                         at_ms=1791510300000)
dp.append_rows([rel], ppath)
prows, _bd = dc.read_rows(ppath)
loud = False
try:
    dp.withdrawn_patch_ids(prows, lambda r, n: "x",
                           REPO_NAME)
except dp.PromoteError as exc:
    loud = "withdrawn_target_unknown" in str(exc)
ok(loud, "D1 a withdraws relation whose target never landed raises "
         "WithdrawnTargetUnknown — the guard cannot silently shrink")

# ---------- E. degraded patch-id face refuses by name, never empty guard --
section("E a patch-id failure degrades to a named refusal, not an empty guard")
d = tmpdir("sc_t26100923_wd5_")
repo = build_repo(tmpdir("sc_t26100923_git5_"))
try:
    rev = sh(repo, "rev-parse", "HEAD")
    dpath = os.path.join(d, "delivery_ledger.jsonl")
    dc.append_rows([landing_row("t-e", rev, 1791510400000)], dpath)
    ppath = os.path.join(d, "promotions.jsonl")
    rel = dp.record_relation("withdraws", from_ticket="t-withdraw-work",
                             to_ticket="t-e", recorded_by="host", reason="r", evidence={"what": "ticket", "ref": "t-e"},
                             at_ms=1791510402000)
    dp.append_rows([rel], ppath)
    drows, _b1 = dc.read_rows(dpath)
    prows, _b2 = dc.read_rows(ppath)

    def broken_pid(revision, name):
        raise dp.PatchIdUnavailable("patch_id_simulated_outage")

    named = False
    try:
        dp.check_withdrawn("t-e", drows + prows, broken_pid, REPO_NAME)
    except dp.PatchIdUnavailable as exc:
        named = bool(str(exc).strip())
    ok(named, "E1 when the patch identity cannot be computed the check "
              "refuses with a named PatchIdUnavailable — an empty guard set "
              "would silently allow the re-introduction spec (e) forbids")
finally:
    shutil.rmtree(repo, ignore_errors=True)

for d in TMPDIRS:
    shutil.rmtree(d, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
sys.exit(0 if FAIL == 0 else 1)
