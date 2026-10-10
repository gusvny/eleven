# -*- coding: utf-8 -*-
"""t261009-66 — relations read in both directions from the one stored side,
and the promotion record names the repairs it contains.

What this battery pins:

1. ``relations_of`` answers "what are this ticket's relations" from BOTH
   directions over one ledger: ``as_actor`` (the STORED side — rows whose
   ``from`` is the ticket) and ``as_benefited`` (the DERIVED side — rows
   whose ``to`` resolves to the ticket, every entry marked
   ``"derived": True``). No second stored row is written anywhere.
2. All three ``to`` target forms resolve on the benefited side: ticket id,
   ``ldg-`` landing id (via the landing row), and patch identity (via the
   caller-supplied ``patch_ids`` map). Cross-line resolution holds —
   relations are project-level facts.
3. Corrections (t261009-62): a superseded relation never appears as
   current through the reader, from either direction; a supersedes CYCLE
   makes both rows non-current.
4. Fail-soft honesty: malformed rows (non-dict, missing ``rel-`` id,
   unknown kind) never crash the reader; a patch-id-named relation
   without the ``patch_ids`` map lands in ``unresolved`` by relation id —
   never guessed into an answer.
5. The reader is ONE implementation: ``develop_promote.relations_of`` IS
   ``develop_certify.relations_of`` (same object, no second direction
   logic).
6. ``build_promotion`` names the repairs it contains: the current
   ``repairs`` AND ``withdraws`` relations recorded by covered tickets are
   read back from ``delivery_rows`` (the ledger, not a return value) onto
   the ``repairs`` field; uncovered tickets' remedies are not named; a
   remedy-free promotion carries ``"repairs": []``; a duplicate ticket in
   the candidate list names each relation once; the row validates through
   the shared writer's ``validate_row``, and a legacy promotion row
   without the field still validates (append-only ledger, old rows
   byte-identical).

External-input discipline: hand-written ledger rows and a ``patch_ids``
map are the external input — malformed rows are fixture cases here, never
a real external source. Pure unit tests over in-memory fixtures; no git,
no network, no integration entry (UT discipline).
"""
import unittest

import develop_certify as dc
import develop_promote as dp


def LANDING(idx, ticket="t1", repo="r", revision="rev1", at=1000,
            line="default"):
    return {"kind": dc.KIND_LANDING, "id": "ldg-%03d" % idx,
            "ticket": ticket, "line": line,
            "repos": [{"repo": repo, "revision": revision}],
            "actor": "engine", "at": at}


def CERT(idx, revision="rev1", run="run-a", at=2000):
    return {"kind": dc.KIND_CERT, "id": "cert-%03d" % idx, "line": "default",
            "repos": [{"repo": "r", "revision": revision}], "run": run,
            "booked_red": "none", "judged_by": "integration", "at": at}


def REL(idx, kind, from_t, to, at=4000, evidence=None, supersedes=None):
    row = {"kind": kind, "id": "rel-%03d" % idx, "from": from_t, "to": to,
           "recorded_by": "integration", "reason": "the story", "at": at,
           "evidence": evidence or {"what": "ticket", "ref": to}}
    if supersedes is not None:
        row["supersedes_relation"] = supersedes
    return row


def stamped(rows):
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


ACTOR_KINDS = (dc.REL_KIND_WITHDRAWS, dc.REL_KIND_REPAIRS,
               dc.REL_KIND_SUPERSEDES)


def ids(entries):
    return [e["id"] for e in entries]


class RelationsOfTest(unittest.TestCase):
    """Spec item (1): one reader, both directions, derived side labelled."""

    def test_actor_side_lists_stored_direction(self):
        rows = [REL(1, dc.REL_KIND_REPAIRS, "fix-1", "t1")]
        face = dc.relations_of(rows, "fix-1")
        self.assertEqual(ids(face["as_actor"][dc.REL_KIND_REPAIRS]),
                         ["rel-001"])
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]), [])
        self.assertEqual(face["unresolved"], [])

    def test_benefited_side_is_derived_and_labelled(self):
        rows = [REL(1, dc.REL_KIND_REPAIRS, "fix-1", "t1")]
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]),
                         ["rel-001"])
        entry = face["as_benefited"][dc.REL_KIND_REPAIRS][0]
        self.assertIs(entry["derived"], True)
        self.assertEqual(ids(face["as_actor"][dc.REL_KIND_REPAIRS]), [])

    def test_benefited_side_via_landing_id(self):
        rows = stamped([LANDING(1, "t1"),
                        REL(1, dc.REL_KIND_REPAIRS, "fix-1", "ldg-001")])
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]),
                         ["rel-001"])

    def test_benefited_side_via_patch_identity_map(self):
        rows = stamped([LANDING(1, "t1", revision="rev1"),
                        REL(1, dc.REL_KIND_REPAIRS, "fix-1", "pid-x",
                            evidence={"what": "patch_id", "ref": "pid-x"})])
        face = dc.relations_of(rows, "t1", patch_ids={"ldg-001": "pid-x"})
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]),
                         ["rel-001"])
        # without the map the patch-named relation stays honest: unresolved
        face2 = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face2["as_benefited"][dc.REL_KIND_REPAIRS]), [])
        self.assertEqual(face2["unresolved"], ["rel-001"])

    def test_cross_line_resolution(self):
        # relations are project-level facts (goal 15): the repair targets a
        # landing on ANOTHER line and still credits the ticket here
        rows = stamped([LANDING(1, "t1", line="other"),
                        REL(1, dc.REL_KIND_REPAIRS, "fix-1", "ldg-001")])
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]),
                         ["rel-001"])

    def test_withdraws_and_supersedes_both_directions(self):
        rows = [REL(1, dc.REL_KIND_WITHDRAWS, "fix-1", "t1"),
                REL(2, dc.REL_KIND_SUPERSEDES, "t2", "t1")]
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_WITHDRAWS]),
                         ["rel-001"])
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_SUPERSEDES]),
                         ["rel-002"])
        self.assertEqual(ids(face["as_actor"][dc.REL_KIND_WITHDRAWS]), [])
        actor = dc.relations_of(rows, "fix-1")
        self.assertEqual(ids(actor["as_actor"][dc.REL_KIND_WITHDRAWS]),
                         ["rel-001"])

    def test_superseded_relation_not_current(self):
        # t261009-62: a correction is a NEW row; the corrected relation must
        # not appear as current from EITHER direction
        rows = [REL(1, dc.REL_KIND_REPAIRS, "fix-1", "t-wrong"),
                REL(2, dc.REL_KIND_REPAIRS, "fix-1", "t1",
                    supersedes="rel-001")]
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]),
                         ["rel-002"])
        wrong = dc.relations_of(rows, "t-wrong")
        self.assertEqual(ids(wrong["as_benefited"][dc.REL_KIND_REPAIRS]), [])

    def test_supersedes_cycle_both_non_current(self):
        rows = [REL(1, dc.REL_KIND_REPAIRS, "fix-1", "t1",
                    supersedes="rel-002"),
                REL(2, dc.REL_KIND_REPAIRS, "fix-1", "t1",
                    supersedes="rel-001")]
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]), [])

    # ---- malformed input (external-input rule) -------------------------

    def test_malformed_rows_never_crash(self):
        rows = [None, 42, {"kind": dc.REL_KIND_REPAIRS},  # no rel- id
                {"kind": dc.REL_KIND_REPAIRS, "id": "ldg-001",
                 "from": "fix-1", "to": "t1"},          # wrong id prefix
                REL(1, "weird-kind", "fix-1", "t1"),    # unregistered kind
                REL(2, dc.REL_KIND_REPAIRS, "fix-1", None),  # unusable to
                REL(3, dc.REL_KIND_REPAIRS, "fix-1", "t1")]
        face = dc.relations_of(rows, "t1")
        self.assertEqual(ids(face["as_benefited"][dc.REL_KIND_REPAIRS]),
                         ["rel-003"])

    def test_empty_and_junk_ledgers(self):
        self.assertEqual(dc.relations_of([], "t1")["as_actor"],
                         {k: [] for k in ACTOR_KINDS})
        self.assertEqual(dc.relations_of([None], "t1")["unresolved"], [])

    def test_bad_ticket_refused_by_name(self):
        with self.assertRaises(dc.CertifyError) as ctx:
            dc.relations_of([], "")
        self.assertIn("relations_of_bad_ticket", str(ctx.exception))
        with self.assertRaises(dc.CertifyError):
            dc.relations_of([], None)

    def test_promote_reexport_is_same_object(self):
        # spec item (3): ONE implementation — no second direction logic
        self.assertIs(dp.relations_of, dc.relations_of)


class PromotionRepairsTest(unittest.TestCase):
    """Spec item (2): the promotion record names the repairs it contains."""

    def remedy_ledger(self):
        # the remedy ticket (fix-1) is itself COVERED by the promotion —
        # that is the design sentence: the record names the remedy work
        # that rode with it. The repair names the covered landing ldg-001
        # (rev1), so the certification still covers both landings.
        return stamped([LANDING(1, "t1"), LANDING(2, "fix-1"), CERT(1),
                        REL(1, dc.REL_KIND_REPAIRS, "fix-1", "ldg-001",
                            at=3500)])

    def test_promotion_names_repair_of_covered_ticket(self):
        # remedy work rides the same promotion: the covered remedy ticket
        # (fix-1) recorded the repair naming the covered landing
        rows = self.remedy_ledger()
        row = dp.build_promotion(delivery_rows=rows,
                                 **PROMOTE_KW(tickets=("t1", "fix-1")))
        self.assertEqual(row["repairs"],
                         [{"id": "rel-001", "from": "fix-1", "to": "ldg-001",
                           "kind": dc.REL_KIND_REPAIRS}])
        # and the row validates through the shared writer
        clean, why = dc.validate_row(row)
        self.assertIsNotNone(clean)

    def test_promotion_names_withdrawn_remedy_too(self):
        # withdrawal is work too: it rides under the same field, kind named.
        # The withdrawal's FROM is the covered ticket (its work withdraws
        # t0's landing), so the candidate itself never hits the guard.
        rows = stamped([LANDING(1, "t0", revision="rev0"),
                        LANDING(2, "t1"),
                        CERT(1),
                        REL(1, dc.REL_KIND_WITHDRAWS, "t1", "t0")])
        row = dp.build_promotion(
            delivery_rows=rows,
            patch_id_fn=lambda rev, repo: "pid-%s" % rev,
            **PROMOTE_KW())
        self.assertEqual(len(row["repairs"]), 1)
        self.assertEqual(row["repairs"][0]["kind"], dc.REL_KIND_WITHDRAWS)

    def test_uncovered_tickets_remedy_not_named(self):
        rows = stamped([LANDING(1, "t1"), CERT(1),
                        REL(1, dc.REL_KIND_REPAIRS, "fix-1", "t-other")])
        row = dp.build_promotion(delivery_rows=rows, **PROMOTE_KW())
        self.assertEqual(row["repairs"], [])

    def test_remedy_free_promotion_carries_empty_list(self):
        row = dp.build_promotion(delivery_rows=stamped(
            [LANDING(1, "t1"), CERT(1)]), **PROMOTE_KW())
        self.assertEqual(row["repairs"], [])
        clean, why = dc.validate_row(row)
        self.assertIsNotNone(clean)

    def test_duplicate_ticket_names_relation_once(self):
        rows = self.remedy_ledger()
        kw = PROMOTE_KW(tickets=("t1", "fix-1", "fix-1"))
        row = dp.build_promotion(delivery_rows=rows, **kw)
        self.assertEqual(ids(row["repairs"]), ["rel-001"])

    def test_superseded_remedy_not_named(self):
        rows = stamped([LANDING(1, "t1"), LANDING(2, "fix-1"), CERT(1),
                        REL(1, dc.REL_KIND_REPAIRS, "fix-1", "ldg-001"),
                        REL(2, dc.REL_KIND_REPAIRS, "fix-1", "ldg-001",
                            supersedes="rel-001")])
        row = dp.build_promotion(delivery_rows=rows,
                                 **PROMOTE_KW(tickets=("t1", "fix-1")))
        self.assertEqual(ids(row["repairs"]), ["rel-002"])

    def test_legacy_row_without_field_validates(self):
        # append-only ledger: old promotion rows stay byte-identical and
        # valid — the new field is optional at read time
        legacy = {"kind": dc.KIND_PROMOTION, "id": "prom-001",
                  "certification": "cert-001", "line": "default",
                  "repos": [{"repo": "r", "revision": "rev1"}],
                  "tickets": ["t1"],
                  "main_before": [{"repo": "r", "revision": "old"}],
                  "main_after": [{"repo": "r", "revision": "rev1"}],
                  "signer": "integration", "at": 5000}
        clean, why = dc.validate_row(legacy)
        self.assertIsNotNone(clean)

    def test_field_validated_by_name(self):
        base = dp.build_promotion(delivery_rows=stamped(
            [LANDING(1, "t1"), CERT(1)]), **PROMOTE_KW())
        bad = dict(base)
        bad["repairs"] = "nope"
        self.assertIsNone(dc.validate_row(bad)[0])
        bad2 = dict(base)
        bad2["repairs"] = [{"id": "prom-001", "from": "a", "to": "b",
                            "kind": dc.REL_KIND_REPAIRS}]
        self.assertIsNone(dc.validate_row(bad2)[0])
        bad3 = dict(base)
        bad3["repairs"] = [{"id": "rel-001", "from": "a", "to": "b",
                            "kind": "weird"}]
        self.assertIsNone(dc.validate_row(bad3)[0])


if __name__ == "__main__":
    unittest.main()
