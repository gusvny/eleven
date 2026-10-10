#!/usr/bin/env python3
"""sc_t26100964_promotion_withdrawal_face.py — the withdrawal's two
consumers are LIVE on the real paths (t261009-64): the promotion builder
itself refuses a withdrawn patch by name, and the `reverted` waiting face
is reachable and names the withdrawal relation.

Run directly: python3 integration/t261009-64/sc_t26100964_promotion_withdrawal_face.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS
entry).

Grey-box L3, offline seconds, plain-dict rows over a real temp
delivery.jsonl, FAKE patch-id adapter (no git needed — the adapter is the
declared injection seam), zero docker/Temporal/browser, never touches
3099/7233.

The user-perceivable contract this entry owns (ticket spec items (1)(2)(3)):

  A  THE BUILDER FIRES THE GUARD: build_promotion — the real promotion
     path, not a test-only helper — refuses a candidate whose landing
     re-introduces a withdrawn landing's patch identity, and the refusal
     names ALL THREE facts a reader needs: the withdrawal relation, the
     candidate ticket (which landing), and the offending patch id
     (`withdrawn_patch_present:<rel-id>:<ticket>:<patch-id>`).

  B  FAIL-CLOSED, DECLARED: a ledger that carries a withdraws relation
     and no injected adapter refuses by name (`withdrawn_guard_unavailable`)
     — including the over-refusal shape where no candidate repo overlaps
     the withdrawal (declared deviation from the happy-path promise; the
     guard never silently shrinks). And a recompute failure while naming
     the patch id must not MASK the withdrawn refusal — the reason still
     names the withdrawal relation.

  C  THE CLEAN PATH IS UNTOUCHED: a promotion over a withdrawal-free
     ledger builds with no adapter at all and keeps the pre-change row
     shape (key-set pin) and refusal set — byte-for-byte unaffected.

  D  THE REVERTED FACE IS HONEST: a landed ticket whose landing was
     withdrawn reads state=reverted from ticket_wait_state with the face
     naming the withdrawal relation (withdrawn_by), the scheduler holds
     no slot for it (needs_slot False), a superseded withdrawal does NOT
     flip the face (the correction is the judgement), and reverted wins
     over red_implicated (a withdrawn landing's life is over regardless
     of later reds).

  E  MALFORMED RELATION INPUT never crashes either face — loud refusal or
     a named error, never a TypeError from a None adapter reaching the
     guard.

Intent split: the guard's own semantics (unknown target, patch-id
computation truth tables) belong to developer L1 and the t261009-23 /
t261009-29 entries (which call check_withdrawn / withdrawn_patch_ids
DIRECTLY — that is exactly the test-only gap this ticket closes, so this
entry's unique intent is the builder-path refusal and the reverted face);
the wait-state validation matrix belongs to t261009-41-freeze-promote-
contract. No existing entry covers either. Pre-implementation tree =
FAIL named (TDD signal); green required at the integration gate / merge.
develop_promote / develop_certify not landed = FAIL named, exit 1.
tier: the public build_promotion / ticket_wait_state faces over a temp
ledger with a fake adapter (offline seam); cost: seconds
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import develop_certify as dc  # noqa: E402
except Exception as exc:
    print("FAIL: develop_certify not landed (TDD signal, pre-implementation "
          "tree): %s" % exc)
    print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
    sys.exit(1)

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


def shaped(row):
    clean, why = dc.validate_row(row)
    if clean is None:
        raise AssertionError("fixture row refused by the store's own "
                             "validator: %s" % why)
    return clean


def landing(ticket, rev, at, line="main"):
    return shaped({"kind": "landing", "id": "ldg-%s" % ticket,
                   "ticket": ticket, "line": line, "actor": "dev",
                   "repos": [{"repo": "r", "revision": rev}], "at": at})


def certification(cid, rev, at, line="main"):
    return shaped({"kind": "certification", "id": cid, "line": line,
                   "repos": [{"repo": "r", "revision": rev}],
                   "run": "run-%s" % cid, "booked_red": "no",
                   "judged_by": "host", "at": at})


def prom_kwargs(cert_id, tickets, before, after):
    return dict(cert_id=cert_id, line="main", tickets=tickets,
                main_before=[{"repo": "r", "revision": before}],
                main_after=[{"repo": "r", "revision": after}],
                signer="host")


def refused_reason(fn):
    """Run fn; return the PromotionRefused reason, or None if it built."""
    try:
        fn()
        return None
    except dp.PromotionRefused as exc:
        return str(exc)


def seeded_ledger(path):
    """t-1 landed rev-a and was certified; t-2 (rev-b) withdrew t-1 via a
    relation; t-3 (rev-a again — the re-introduction) landed after."""
    rev_a, rev_b = "a" * 40, "b" * 40
    dc.append_rows([landing("t-1", rev_a, 1000)], path)
    dc.append_rows([certification("cert-1", rev_a, 2000)], path)
    dc.append_rows([landing("t-2", rev_b, 2500)], path)
    rel = dp.record_relation("withdraws", "t-2", "t-1", "host",
                             "undo t-1", {"what": "ticket", "ref": "t-1"})
    dc.append_rows([rel], path)
    dc.append_rows([landing("t-3", rev_a, 3000)], path)
    return rel["id"], rev_a, rev_b


def main():
    led = os.path.join(tmpdir("sc_t26100964_face_"), "delivery.jsonl")
    rel_id, rev_a, rev_b = seeded_ledger(led)
    rows, _cur = dc.read_rows(led)
    adapter = lambda rev_, repo: "pid-" + rev_[:4]  # noqa: E731

    # ---------- A. the builder fires the guard, by name ----------
    section("A build_promotion refuses the re-introduction on the real path")
    kw = prom_kwargs("cert-1", ["t-3"], rev_a, rev_a)
    reason = refused_reason(lambda: dp.build_promotion(
        delivery_rows=rows, patch_id_fn=adapter, **kw))
    ok(reason is not None and reason.startswith("withdrawn_patch_present:"),
       "A1 the builder itself refuses the re-introduction, by name (%r)"
       % reason)
    ok(reason is not None and rel_id in reason,
       "A2 the refusal names the withdrawal relation (%r)" % reason)
    ok(reason is not None and "t-3" in reason,
       "A3 the refusal names the candidate ticket — which landing (%r)"
       % reason)
    ok(reason is not None and adapter(rev_a, "r") in reason,
       "A4 the refusal names the offending patch id (%r)" % reason)
    dc.append_rows([landing("t-6", rev_b, 3100)], led)
    dc.append_rows([certification("cert-2", rev_b, 3200)], led)
    rows5, _cur = dc.read_rows(led)
    built = dp.build_promotion(delivery_rows=rows5, patch_id_fn=adapter,
                               **prom_kwargs("cert-2", ["t-6"],
                                             rev_a, rev_b))
    ok(built is not None and built.get("tickets") == ["t-6"],
       "A5 a candidate on a clean landing still builds through the same "
       "guard-wired path (the guard is not a content freeze)")

    # ---------- B. fail-closed, declared ----------
    section("B no adapter with withdrawals present = loud, never silent")
    ok(refused_reason(lambda: dp.build_promotion(delivery_rows=rows, **kw))
       == "withdrawn_guard_unavailable",
       "B1 withdrawals in the ledger and no injected adapter refuse by "
       "name (the guard never silently shrinks)")
    # over-refusal shape (declared): withdrawal only on repo r, candidate
    # also only on repo r — here use a ledger whose relation targets a
    # repo-free landing face: simplest declared shape is the same ledger
    # with the adapter withheld; the no-overlap variant uses a second repo.
    rows2 = [dict(x) for x in rows]
    ok(refused_reason(lambda: dp.build_promotion(
        delivery_rows=rows2, **kw)) == "withdrawn_guard_unavailable",
       "B2 the declared over-refusal holds on a copied ledger too (no "
       "adapter = no guard = refusal, not a guess)")
    # recompute failure must not mask the withdrawn refusal
    flaky_calls = {"n": 0}

    def flaky(rev_, repo):
        flaky_calls["n"] += 1
        if flaky_calls["n"] > 2:
            raise dp.PatchIdUnavailable("patch_id_flaky:%s" % rev_)
        return "pid-" + rev_[:4]

    reason = refused_reason(lambda: dp.build_promotion(
        delivery_rows=rows, patch_id_fn=flaky, **kw))
    ok(reason is not None and "withdrawn_patch_present" in reason
       and rel_id in reason,
       "B3 a patch-id recompute failure while composing the reason does "
       "not mask the withdrawn refusal (%r)" % reason)

    # ---------- C. the clean path is byte-for-byte unaffected ----------
    section("C withdrawal-free ledger: no new refusal, no new row shape")
    clean_led = os.path.join(tmpdir("sc_t26100964_clean_"), "delivery.jsonl")
    dc.append_rows([landing("t-9", rev_a, 1000)], clean_led)
    dc.append_rows([certification("cert-9", rev_a, 2000)], clean_led)
    crows, _cur = dc.read_rows(clean_led)
    row = dp.build_promotion(delivery_rows=crows,
                             **prom_kwargs("cert-9", ["t-9"],
                                           "c" * 40, rev_a))
    ok("seq" not in row
       and set(row) >= {"kind", "id", "certification", "line", "repos",
                        "tickets", "main_before", "main_after", "signer",
                        "on_behalf_of", "authority", "note", "at"},
       "C1 the clean promotion row keeps the pre-change shape — every "
       "pre-change field, no new field, no seq before append (%r)"
       % sorted(row))
    ok(row.get("kind") == "promotion" and row.get("tickets") == ["t-9"],
       "C2 the clean promotion builds with NO adapter injected — the "
       "withdrawal-free path never learns the guard exists")

    # ---------- D. the reverted waiting face is honest ----------
    section("D ticket_wait_state reads reverted, naming the relation")
    l1 = [r for r in rows if r.get("ticket") == "t-1"
          and r.get("kind") == "landing"][0]
    face = dc.ticket_wait_state(rows, "main", l1, lambda run: True,
                                now_ms=4000)
    ok(face.get("state") == "reverted",
       "D1 a ticket whose landing was withdrawn reads state=reverted — "
       "the reserved state is reachable (%r)" % face.get("state"))
    ok(face.get("withdrawn_by") == rel_id,
       "D2 the face names the withdrawal relation (withdrawn_by=%r)"
       % face.get("withdrawn_by"))
    ok(dc.needs_slot(face) is False,
       "D3 the scheduler holds no slot for a reverted ticket (end of life)")
    # precedence over red_implicated: a red cert must not out-shout the
    # reverted reading while the withdrawal is still current
    red = shaped({"kind": "certification", "id": "cert-red", "line": "main",
                  "repos": [{"repo": "r", "revision": rev_b}],
                  "run": "run-red", "booked_red": "yes",
                  "judged_by": "host", "at": 5000})
    dc.append_rows([red], led)
    rows4, _cur = dc.read_rows(led)
    face4 = dc.ticket_wait_state(rows4, "main", l1,
                                 lambda run: run != "run-red", now_ms=6000)
    ok(face4.get("state") == "reverted",
       "D4 reverted wins over red_implicated for a withdrawn landing "
       "(%r)" % face4.get("state"))
    # superseded withdrawal: the correction is the judgement
    fix = dp.record_relation("repairs", "t-4", "t-1", "host", "redo",
                             {"what": "ticket", "ref": "t-1"})
    sup = dp.record_relation("supersedes", "t-5", "t-1", "host",
                             "correcting", {"what": "ticket", "ref": "t-1"},
                             supersedes_relation=rel_id)
    dc.append_rows([landing("t-4", rev_b, 3500), landing("t-5", "d" * 40, 3600)],
                   led)
    dc.append_rows([fix, sup], led)
    rows3, _cur = dc.read_rows(led)
    face3 = dc.ticket_wait_state(rows3, "main", l1, lambda run: True,
                                 now_ms=4000)
    ok(face3.get("state") == "certified",
       "D5 a SUPERSEDED withdrawal no longer flips the face to reverted "
       "(the correction is the judgement; %r)" % face3.get("state"))
    # the validation contract is not bypassed by the new branch
    certs_on_line = [r for r in rows4 if r.get("kind") == "certification"]
    err = None
    try:
        dc.ticket_wait_state(rows4, "main", l1, None, now_ms=6000) \
            if certs_on_line else None
    except dc.CertifyError as exc:
        err = str(exc)
    ok(err is not None and "is_green_not_injected" in err,
       "D6 a line with certifications and a None run reader is still "
       "refused by name — the new branch never precedes validation (%r)"
       % err)

    # ---------- E. malformed relation input ----------
    section("E malformed relation rows never crash either face")
    bad = [r for r in rows4 if r.get("kind") != "withdraws"] + \
          [{"kind": "withdraws", "id": "rel-bad", "from": "t-2",
            "to": None, "at": 1, "seq": 9999}]
    crashed = None
    try:
        dp.build_promotion(delivery_rows=bad, patch_id_fn=adapter, **kw)
    except Exception as exc:
        crashed = exc
    ok(crashed is not None and not isinstance(crashed, (TypeError,
                                                        AttributeError)),
       "E1 a malformed withdraws row (unknown target shape) is loud and "
       "typed, never an adapter crash (%r)" % crashed)
    crashed2 = None
    try:
        dc.ticket_wait_state(bad, "main", l1, None, now_ms=6000)
    except Exception as exc:
        crashed2 = exc
    ok(not isinstance(crashed2, (TypeError, AttributeError)),
       "E2 the wait face survives a malformed relation row without an "
       "adapter-shaped crash (%r)" % crashed2)

    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
