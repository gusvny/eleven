# -*- coding: utf-8 -*-
"""t261009-64 — the withdrawal's two consumers.

What this battery pins:

1. ``build_promotion`` fires the landed withdrawal guard on the REAL
   builder (not a test-only helper). A candidate re-introducing a
   withdrawn landing's patch identity refuses BY NAME with all three
   facts: ``withdrawn_patch_present:<rel-id>:<ticket>:<patch-id>``
   (which withdrawal relation, which candidate ticket, which patch id).
2. The refusal-enrichment recompute is honest: when the injected
   ``patch_id_fn`` fails on the recompute (transient git failure), the
   original guard refusal (relation id only) is re-raised — the
   withdrawal diagnosis is never masked by the recompute failure
   (review condition 1).
3. Fail-closed: a ledger carrying any ``withdraws`` relation without an
   injected ``patch_id_fn`` refuses ``withdrawn_guard_unavailable`` —
   INCLUDING the over-refusal case where no candidate repo overlaps the
   withdrawal (a declared deviation from "no new refusal", scoped to
   withdrawal-bearing ledgers).
4. A withdrawal-FREE ledger is byte-for-byte unaffected: no new refusal,
   no new row shape (row key-set pinned against the pre-change shape).
5. Borrowed-implementation fault modes carried as-is, each named:
   (a) unknown withdrawal target -> WithdrawnTargetUnknown propagates;
   (b) unavailable patch id -> PatchIdUnavailable propagates;
   (c) a SUPERSEDED withdrawal still arms the guard (today's behaviour
       of ``withdrawn_patch_ids`` — pinned, not changed; future ticket);
   (d) per-repo guard: a candidate whose repo does not overlap the
       withdrawal builds clean when the adapter is injected.
6. ``ticket_wait_state`` returns the ``reverted`` face: ``withdrawn_by``
   names the withdrawal relation; the face outranks ``red_implicated``
   (a withdrawn landing's life is over regardless of later reds); the
   check sits AFTER the ``is_green_not_injected`` refusal (a caller with
   certs on the line and no run reader is still refused by name);
   ``needs_slot`` answers False for the face.

External-input discipline: relation rows and the ``patch_id_fn`` adapter
are external input — malformed rows, a raising adapter, and adapter
callable-shifts are all fixture cases here, never a real external source.
Pure unit tests over in-memory fixtures; no git, no network, no
integration entry (UT discipline).

Performance note (review condition 2): ``check_withdrawn`` rebuilds the
whole guard set per (ticket, repo) call, so the builder now does
O(tickets x repos) guard constructions — fine at ledger scale. The seam
for a future perf pass is hoisting ``withdrawn_patch_ids`` out of the
builder loop (see build_promotion's docstring).
"""
import unittest

import develop_certify as dc
import develop_promote as dp

PID_WITHDRAWN = "pid-withdrawn"


def LANDING(idx, ticket="t1", repo="r", revision="rev1", at=1000):
    return {"kind": dc.KIND_LANDING, "id": "ldg-%03d" % idx,
            "ticket": ticket, "line": "default",
            "repos": [{"repo": repo, "revision": revision}],
            "actor": "engine", "at": at}


def CERT(idx, revision="rev1", run="run-a", at=2000):
    return {"kind": dc.KIND_CERT, "id": "cert-%03d" % idx, "line": "default",
            "repos": [{"repo": "r", "revision": revision}], "run": run,
            "booked_red": "none", "judged_by": "integration", "at": at}


def WITHDRAWS(idx, to_t, at=4000, supersedes=None):
    row = {"kind": dc.REL_KIND_WITHDRAWS, "id": "rel-%03d" % idx,
           "from": "fix-1", "to": to_t, "recorded_by": "integration",
           "reason": "red landed", "at": at,
           "evidence": {"what": "ticket", "ref": to_t}}
    if supersedes is not None:
        row["supersedes_relation"] = supersedes
    return row


def stamped(rows):
    """In-memory stand-in for the shared writer's seq stamping: the faces
    order rows by ``seq``, so fixture ledgers carry one. Malformed rows
    stay malformed (only dict rows get a seq)."""
    out = []
    for i, r in enumerate(rows):
        if isinstance(r, dict):
            r = dict(r)
            r["seq"] = i + 1
        out.append(r)
    return out


def PROMOTE_KW(tickets=("t1",), revision="rev1"):
    return dict(cert_id="cert-001", line="default", tickets=list(tickets),
                main_before=[{"repo": "r", "revision": "old"}],
                main_after=[{"repo": "r", "revision": revision}],
                signer="integration")


def pid_fn(mapping):
    """Adapter stub: revision -> patch id per ``mapping``; unknown
    revision -> PatchIdUnavailable (the guard never guesses)."""
    def _fn(revision, repo):
        try:
            return mapping[revision]
        except KeyError:
            raise dp.PatchIdUnavailable("patch_id_unknown:%s" % revision)
    return _fn


def clean_ledger():
    return stamped([LANDING(1, "t1"), CERT(1)])


def withdrawn_ledger(withdrawn_ticket="t0", repo="r", revision="rev0"):
    return stamped([LANDING(1, "t1"), CERT(1),
                    LANDING(2, withdrawn_ticket, repo=repo, revision=revision),
                    WITHDRAWS(1, withdrawn_ticket)])


class BuildPromotionGuardTest(unittest.TestCase):
    """Change 1: the promotion path fires the guard."""

    def test_refusal_names_relation_ticket_and_patch_id(self):
        # the candidate's own landing carries the withdrawn revision
        rows = stamped([LANDING(1, "t1", revision="rev0"),
                        CERT(1, revision="rev0"),
                        LANDING(2, "t0", revision="rev0"),
                        WITHDRAWS(1, "t0")])
        with self.assertRaises(dp.PromotionRefused) as cm:
            dp.build_promotion(delivery_rows=rows, patch_id_fn=pid_fn(
                {"rev0": PID_WITHDRAWN}), **PROMOTE_KW(revision="rev0"))
        self.assertEqual(str(cm.exception),
                         "withdrawn_patch_present:rel-001:t1:%s"
                         % PID_WITHDRAWN)

    def test_recompute_failure_falls_back_to_rel_id_only(self):
        rows = stamped([LANDING(1, "t1", revision="rev0"),
                        CERT(1, revision="rev0"),
                        LANDING(2, "t0", revision="rev0"),
                        WITHDRAWS(1, "t0")])
        calls = []

        def flaky(revision, repo):
            # succeeds through the guard's own calls, fails on the
            # builder's enrichment recompute (callable-shift fixture)
            calls.append(revision)
            if len(calls) > 2:
                raise dp.PatchIdUnavailable("patch_id_transient")
            return PID_WITHDRAWN

        with self.assertRaises(dp.PromotionRefused) as cm:
            dp.build_promotion(delivery_rows=rows, patch_id_fn=flaky,
                               **PROMOTE_KW(revision="rev0"))
        self.assertEqual(str(cm.exception),
                         "withdrawn_patch_present:rel-001")

    def test_guard_unavailable_without_adapter(self):
        with self.assertRaises(dp.PromotionRefused) as cm:
            dp.build_promotion(delivery_rows=withdrawn_ledger(),
                               **PROMOTE_KW())
        self.assertEqual(str(cm.exception), "withdrawn_guard_unavailable")

    def test_over_refusal_declared_no_overlap_no_adapter(self):
        # withdrawal on repo "a", candidate on repo "b", no adapter:
        # still refuses — the declared over-refusal (review gen0 #3)
        kw = PROMOTE_KW()
        kw["main_after"] = [{"repo": "b", "revision": "rev1"}]
        rows = stamped([LANDING(1, "t1", repo="b"),
                        dict(CERT(1), repos=[{"repo": "b",
                                              "revision": "rev1"}]),
                        LANDING(2, "t0", repo="a", revision="rev0"),
                        WITHDRAWS(1, "t0")])
        with self.assertRaises(dp.PromotionRefused) as cm:
            dp.build_promotion(delivery_rows=rows, **kw)
        self.assertEqual(str(cm.exception), "withdrawn_guard_unavailable")

    def test_non_overlapping_repo_with_adapter_builds_clean(self):
        # fault mode (d): the guard is per-repo; candidate on repo b with
        # the adapter injected computes nothing and builds clean
        kw = PROMOTE_KW()
        kw["main_after"] = [{"repo": "b", "revision": "rev1"}]
        rows = stamped([LANDING(1, "t1", repo="b"),
                        dict(CERT(1), repos=[{"repo": "b",
                                              "revision": "rev1"}]),
                        LANDING(2, "t0", repo="a", revision="rev0"),
                        WITHDRAWS(1, "t0")])
        row = dp.build_promotion(delivery_rows=rows,
                                 patch_id_fn=pid_fn({"rev1": "pid-b"}),
                                 **kw)
        self.assertEqual(row["tickets"], ["t1"])

    def test_withdrawal_free_ledger_row_shape_unchanged(self):
        # spec (3): a withdrawal-free ledger is byte-for-byte unaffected —
        # the row carries exactly the pre-change key set
        row = dp.build_promotion(delivery_rows=clean_ledger(), **PROMOTE_KW())
        self.assertEqual(
            sorted(row.keys()),
            ["at", "authority", "certification", "id", "kind", "line",
             "main_after", "main_before", "note", "on_behalf_of", "repos",
             "signer", "tickets"])

    def test_withdrawal_free_ledger_ignores_broken_adapter(self):
        # no withdrawals -> the adapter is never consulted, even a raising
        # one (byte-for-byte unaffected path)
        def boom(revision, repo):
            raise dp.PatchIdUnavailable("patch_id_never")

        row = dp.build_promotion(delivery_rows=clean_ledger(),
                                 patch_id_fn=boom, **PROMOTE_KW())
        self.assertEqual(row["certification"], "cert-001")

    def test_unknown_withdrawn_target_propagates(self):
        # fault mode (a): a withdraws relation naming a ticket with no
        # landing refuses loudly through the builder
        rows = stamped(clean_ledger() + [WITHDRAWS(1, "ghost")])
        with self.assertRaises(dp.WithdrawnTargetUnknown):
            dp.build_promotion(delivery_rows=rows, patch_id_fn=pid_fn({}),
                               **PROMOTE_KW())

    def test_unavailable_patch_id_propagates(self):
        # fault mode (b): the adapter cannot compute the withdrawn patch
        rows = stamped(clean_ledger() + [
            LANDING(2, "t0", revision="rev0"), WITHDRAWS(1, "t0")])
        with self.assertRaises(dp.PatchIdUnavailable):
            dp.build_promotion(delivery_rows=rows, patch_id_fn=pid_fn({}),
                               **PROMOTE_KW())

    def test_superseded_withdrawal_still_arms_guard(self):
        # fault mode (c): withdrawn_patch_ids reads ALL withdraws rows, not
        # current_relations — a corrected withdrawal still refuses. Pinned
        # as TODAY'S behaviour (out of this ticket's scope to change).
        rows = stamped(
            [LANDING(1, "t1", revision="rev0"), CERT(1, revision="rev0"),
             LANDING(2, "t0", revision="rev0"),
             WITHDRAWS(1, "t0", at=4000),
             WITHDRAWS(2, "t0", at=5000, supersedes="rel-001")])
        with self.assertRaises(dp.PromotionRefused) as cm:
            dp.build_promotion(delivery_rows=rows, patch_id_fn=pid_fn(
                {"rev0": PID_WITHDRAWN}), **PROMOTE_KW(revision="rev0"))
        self.assertTrue(str(cm.exception).startswith(
            "withdrawn_patch_present:rel-002:"))

    def test_malformed_rows_typo_kind_is_not_a_guard(self):
        # external-input discipline: a non-dict row or a TYPO of the
        # withdraws kind must not flip the fail-closed switch nor crash
        # the builder
        rows = stamped(clean_ledger() + ["not-a-row",
                                         {"kind": "withdrawn"}])
        row = dp.build_promotion(delivery_rows=rows, **PROMOTE_KW())
        self.assertEqual(row["tickets"], ["t1"])

    def test_kind_true_but_malformed_withdraws_refuses_loud(self):
        # a row CARRYING the withdraws kind but malformed (no id, no to)
        # is still a withdrawal claim: fail-closed without an adapter, and
        # WithdrawnTargetUnknown with one — never silently ignored
        rows = stamped(clean_ledger() + [{"kind": dc.REL_KIND_WITHDRAWS}])
        with self.assertRaises(dp.PromotionRefused) as cm:
            dp.build_promotion(delivery_rows=rows, **PROMOTE_KW())
        self.assertEqual(str(cm.exception), "withdrawn_guard_unavailable")
        with self.assertRaises(dp.WithdrawnTargetUnknown):
            dp.build_promotion(delivery_rows=rows,
                               patch_id_fn=pid_fn({"rev1": "pid-b"}),
                               **PROMOTE_KW())


class RevertedWaitStateTest(unittest.TestCase):
    """Change 2: the ``reverted`` waiting face is reachable and honest."""

    def base(self, rows):
        return dc.ticket_wait_state(rows, "default", rows[0], None,
                                    now_ms=5000)

    def test_withdrawn_ticket_shows_reverted_naming_relation(self):
        rows = stamped([LANDING(1, "t1"), WITHDRAWS(9, "t1")])
        state = self.base(rows)
        self.assertEqual(state["state"], dc.WAIT_REVERTED)
        self.assertEqual(state["withdrawn_by"], "rel-009")
        self.assertEqual(state["waiting_for"], "rel-009")
        self.assertFalse(dc.needs_slot(state))

    def test_reverted_outranks_red_implicated(self):
        red = CERT(1, revision="rev1", at=2000)
        rows = stamped([LANDING(1, "t1"), red, WITHDRAWS(9, "t1", at=100)])
        state = dc.ticket_wait_state(rows, "default", rows[0],
                                     lambda run: False, now_ms=5000)
        self.assertEqual(state["state"], dc.WAIT_REVERTED)

    def test_is_green_refusal_precedes_reverted(self):
        # review gen1 #4: the reverted check never silently precedes the
        # declared validation contract
        rows = stamped([LANDING(1, "t1"), CERT(1), WITHDRAWS(9, "t1",
                                                             at=100)])
        with self.assertRaises(dc.CertifyError) as cm:
            dc.ticket_wait_state(rows, "default", rows[0], None, now_ms=5000)
        self.assertEqual(str(cm.exception), "is_green_not_injected")

    def test_superseded_withdrawal_still_flips_face(self):
        # the certify-side selector reads current_relations, so a CORRECTED
        # withdrawal drops out and the superseding row is the one named on
        # the face (the promote-side guard differs — fault mode (c))
        rows = stamped([LANDING(1, "t1"),
                        WITHDRAWS(1, "t1", at=100),
                        WITHDRAWS(2, "t1", at=200, supersedes="rel-001")])
        state = self.base(rows)
        self.assertEqual(state["withdrawn_by"], "rel-002")

    def test_other_ticket_withdrawal_does_not_leak(self):
        rows = stamped([LANDING(1, "t1"), LANDING(2, "t2"),
                        WITHDRAWS(9, "t2", at=100)])
        state = self.base(rows)
        self.assertEqual(state["state"], dc.WAIT_WAITING)
        self.assertNotIn("withdrawn_by", state)

    def test_malformed_relation_rows_never_crash(self):
        rows = stamped([LANDING(1, "t1"), "torn", None,
                        {"kind": "withdraws"},
                        {"kind": dc.REL_KIND_WITHDRAWS, "id": "not-rel"}])
        state = self.base(rows)
        self.assertEqual(state["state"], dc.WAIT_WAITING)


if __name__ == "__main__":
    unittest.main()
