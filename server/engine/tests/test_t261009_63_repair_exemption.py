#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 unit tests for t261009-63 (the `repairs` relation grows its two
consumers: the freeze/landing exemption asks WHICH landing is repaired, and
the repaired side says who repaired it — with no relation, no exemption).

Behaviours, each with a receipt:

1. The freeze exemption is DERIVED FROM A CURRENT ``repairs`` relation that
   names a landing on the line (by landing id, by the repaired ticket, or
   by patch identity via the explicit ``patch_ids`` map) — never from the
   ticket's own kind alone. No relation on a frozen line is refused BY
   NAME (``freeze_repair_relation_missing``); wrong kind, foreign ``from``,
   a cross-line target (the face's own scoping — relations stay
   project-level facts, design goal 15), a superseded relation and an
   unmapped patch id are each refused by name, never guessed into an
   exemption.
2. The beneficiary side is readable: ``ticket_outcome`` reports
   ``repaired_by``/``repaired_at`` for ALL THREE target forms; a
   patch-id-named relation without a map lands in ``repaired_unresolved``
   instead of going silent; a repair never changes ``ending``.
3. An unfrozen line answers exactly as before for every declared kind,
   with or without a relation; a relation never mints a kind.

External-input discipline: hand-written relation rows (including malformed
ones) over plain-dict ledgers and a REAL temp delivery ledger read back
FROM DISK; no external source. Integration entries are NOT run here.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402

LINE = "develop"
OTHER_LINE = "docs"
EV_TICKET = {"what": "ticket", "ref": "t1"}


def landing(ticket="t1", line=LINE, lid=None, at=1000):
    return {"kind": "landing", "id": lid or "ldg-a01", "ticket": ticket,
            "line": line, "repos": [{"repo": "sandbar", "revision": "rev1"}],
            "actor": "test", "at": at}


def repair(**kw):
    base = {"id": "rel-r01", "from": "t2", "to": "t1",
            "kind": dc.REL_KIND_REPAIRS, "recorded_by": "host",
            "reason": "fixes t1's landing", "evidence": dict(EV_TICKET),
            "at": 1791510000000}
    base.update(kw)
    return base


def frozen_rows():
    """A frozen line: one landing, a red certification, the freeze episode
    and its open state (episode + change records, the may_land input)."""
    lrow = landing()
    cert = {"kind": "certification", "id": "cert-01", "line": LINE,
            "repos": lrow["repos"], "run": "run-01", "seq": 2, "at": 2000}
    ep = {"kind": "freeze", "id": "frz-01", "line": LINE,
          "cause": "cert-01", "seq": 3, "at": 3000}
    chg = {"kind": "freeze_change", "id": "frzc-01", "line": LINE,
           "freeze": "frz-01", "change": "attribution",
           "value": "boundary, culprit not isolated", "seq": 4, "at": 3001}
    return [lrow, cert, ep, chg], lrow


class ExemptionGrantedTest(unittest.TestCase):
    """The exemption exists only through a current relation naming the line.

    Every ``repair`` row under test is appended to the rows first: the
    face judges a CURRENT ledger row, never a detached dict."""

    @staticmethod
    def may(rows, rel, kind="fix", **kw):
        ledger = list(rows) + ([rel] if isinstance(rel, dict) else [])
        return dc.may_land(ledger, LINE, kind, ticket=kw.pop("ticket", "t2"),
                           repair=rel, **kw)

    def test_frozen_ticket_named_relation_grants(self):
        rows, _ = frozen_rows()
        assert self.may(rows, repair()) is True

    def test_frozen_landing_named_relation_grants(self):
        rows, _ = frozen_rows()
        assert self.may(rows, repair(to="ldg-a01")) is True

    def test_frozen_patch_named_relation_grants_with_map(self):
        rows, _ = frozen_rows()
        rel = repair(to="patch:abc", evidence={"what": "patch_id",
                                               "ref": "p-123"})
        assert self.may(rows, rel, patch_ids={"ldg-a01": "p-123"}) is True

    def test_unfrozen_line_unchanged_with_and_without_relation(self):
        rows, _ = frozen_rows()
        rows.append({"kind": "freeze_change", "id": "frzc-02",
                     "line": LINE, "freeze": "frz-01", "change": "closed",
                     "seq": 5, "at": 4000})
        assert dc.may_land(rows, LINE, "fix") is True
        assert dc.may_land(rows, LINE, "chore") is True
        assert self.may(rows, repair()) is True


class ExemptionRefusedTest(unittest.TestCase):
    """No relation, no exemption — every gap refused BY NAME."""

    @staticmethod
    def may(rows, rel, kind="fix", **kw):
        ledger = list(rows) + ([rel] if isinstance(rel, dict) else [])
        return dc.may_land(ledger, LINE, kind, ticket=kw.pop("ticket", "t2"),
                           repair=rel, **kw)

    def test_kind_only_self_declaration_refused_by_name(self):
        rows, _ = frozen_rows()
        with self.assertRaises(dc.CertifyError) as cm:
            dc.may_land(rows, LINE, "fix")
        self.assertIn("freeze_repair_relation_missing", str(cm.exception))

    def test_wrong_relation_kind_refused(self):
        rows, _ = frozen_rows()
        wrong = repair(kind=dc.REL_KIND_WITHDRAWS)
        with self.assertRaises(dc.CertifyError) as cm:
            self.may(rows, wrong)
        self.assertIn("repair_relation_not_repairs", str(cm.exception))

    def test_foreign_from_refused(self):
        rows, _ = frozen_rows()
        with self.assertRaises(dc.CertifyError) as cm:
            self.may(rows, repair(), ticket="t3")
        self.assertIn("repair_from_not_ticket", str(cm.exception))

    def test_missing_ticket_name_refused(self):
        rows, _ = frozen_rows()
        with self.assertRaises(dc.CertifyError) as cm:
            dc.may_land(list(rows) + [repair()], LINE, "fix",
                        repair=repair())
        self.assertIn("repair_ticket_missing", str(cm.exception))

    def test_detached_relation_refused(self):
        # a relation NOT in the ledger grants nothing: the exemption reads
        # the recorded fact, not the caller's say-so
        rows, _ = frozen_rows()
        with self.assertRaises(dc.CertifyError) as cm:
            dc.may_land(rows, LINE, "fix", ticket="t2", repair=repair())
        self.assertIn("repair_relation_superseded", str(cm.exception))

    def test_cross_line_target_refused(self):
        # The same-line requirement is THIS face's scoping, not a relation
        # rule: relations are project-level facts (design goal 15), but the
        # freeze on LINE comes from a red on LINE — a repair of ANOTHER
        # line's landing is simply not an exemption for LINE.
        rows, _ = frozen_rows()
        rows.append(landing(ticket="t7", line=OTHER_LINE, lid="ldg-c01",
                            at=500))
        with self.assertRaises(dc.CertifyError) as cm:
            self.may(rows, repair(to="t7"))
        self.assertIn("repair_target_unresolved", str(cm.exception))

    def test_superseded_relation_refused(self):
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-r00", at=1))
        rows.append(repair(id="rel-r02", supersedes_relation="rel-r01",
                           at=2))
        with self.assertRaises(dc.CertifyError) as cm:
            self.may(rows, repair())
        self.assertIn("repair_relation_superseded", str(cm.exception))

    def test_patch_named_without_map_refused(self):
        rows, _ = frozen_rows()
        rel = repair(to="patch:abc", evidence={"what": "patch_id",
                                               "ref": "p-123"})
        with self.assertRaises(dc.CertifyError) as cm:
            self.may(rows, rel)
        self.assertIn("repair_target_unresolved", str(cm.exception))

    def test_malformed_repair_inputs_refused(self):
        rows, _ = frozen_rows()
        for bad in ({}, None, "rel-r01", repair(to=None),
                    repair(to=None, evidence={"what": "patch_id"})):
            with self.assertRaises(dc.CertifyError):
                self.may(rows, bad)

    def test_patch_ids_not_map_refused(self):
        rows, _ = frozen_rows()
        with self.assertRaises(dc.CertifyError) as cm:
            dc.may_land(list(rows) + [repair()], LINE, "fix", ticket="t2",
                        repair=repair(), patch_ids="ldg-a01")
        self.assertIn("patch_ids_not_map", str(cm.exception))

    def test_relation_never_mints_a_kind(self):
        rows, _ = frozen_rows()
        # a declared non-exempt kind on a frozen line answers False —
        # with or without a relation
        assert self.may(rows, repair(), kind="chore") is False
        # an undeclared kind is refused by name, never by the relation
        with self.assertRaises(dc.CertifyError) as cm:
            self.may(rows, repair(), kind="fxi")
        self.assertIn("ticket_kind_undeclared", str(cm.exception))


class BeneficiaryFaceTest(unittest.TestCase):
    """The repaired side says who repaired it — in all three forms."""

    def test_ticket_named_relation_reports_repaired_by(self):
        rows, _ = frozen_rows()
        rows.append(repair())
        out = dp.ticket_outcome(rows, "t1")
        self.assertEqual(out["repaired_by"], "t2")
        self.assertEqual(out["repaired_at"], 1791510000000)

    def test_landing_named_relation_reports_repaired_by(self):
        rows, _ = frozen_rows()
        rows.append(repair(to="ldg-a01"))
        out = dp.ticket_outcome(rows, "t1")
        self.assertEqual(out["repaired_by"], "t2")

    def test_patch_named_with_map_reports_repaired_by(self):
        rows, _ = frozen_rows()
        rows.append(repair(to="patch:abc",
                           evidence={"what": "patch_id", "ref": "p-123"}))
        out = dp.ticket_outcome(rows, "t1",
                                patch_ids={"ldg-a01": "p-123"})
        self.assertEqual(out["repaired_by"], "t2")
        self.assertEqual(out["repaired_unresolved"], [])

    def test_patch_named_without_map_is_visible_not_silent(self):
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-r77", to="patch:abc",
                           evidence={"what": "patch_id", "ref": "p-123"}))
        out = dp.ticket_outcome(rows, "t1")
        self.assertIsNone(out["repaired_by"])
        self.assertEqual(out["repaired_unresolved"], ["rel-r77"])

    def test_invalid_at_winner_keeps_by_drops_at(self):
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-r02", at=None))
        out = dp.ticket_outcome(rows, "t1")
        self.assertEqual(out["repaired_by"], "t2")
        self.assertIsNone(out["repaired_at"])

    def test_ties_broken_by_at_then_id(self):
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-r09", **{"from": "t3"},
                           at=1791510000001))
        out = dp.ticket_outcome(rows, "t1")
        self.assertEqual(out["repaired_by"], "t3")
        self.assertEqual(out["repaired_at"], 1791510000001)

    def test_at_tie_with_two_candidates_breaks_by_relation_id(self):
        # Two CURRENT relations at the SAME at, the higher relation id
        # appended LAST: the id tie-break must decide, never file order
        # (arbitration t261009-63 gen1, scenario case C9). The first tie
        # pin above only ever ran one candidate, so the comparison branch
        # never executed — this is the widened regression pin.
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-aaa", **{"from": "t-fix"},
                           at=1791510000000))
        rows.append(repair(id="rel-zzz", **{"from": "t-fix2"},
                           at=1791510000000))
        self.assertEqual(dp.ticket_outcome(rows, "t1")["repaired_by"],
                         "t-fix2")
        # the mirror append order answers the same winner
        rows2, _ = frozen_rows()
        rows2.append(repair(id="rel-zzz", **{"from": "t-fix2"},
                            at=1791510000000))
        rows2.append(repair(id="rel-aaa", **{"from": "t-fix"},
                            at=1791510000000))
        self.assertEqual(dp.ticket_outcome(rows2, "t1")["repaired_by"],
                         "t-fix2")

    def test_superseded_repair_drops_out_of_beneficiary_face(self):
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-r00", **{"from": "t3"}, at=1))
        rows.append(repair(id="rel-r02", supersedes_relation="rel-r00"))
        out = dp.ticket_outcome(rows, "t1")
        self.assertEqual(out["repaired_by"], "t2")

    def test_repair_never_changes_ending(self):
        rows, _ = frozen_rows()
        plain = dp.ticket_outcome([r for r in rows
                                   if r.get("kind") != dc.REL_KIND_REPAIRS],
                                  "t1")
        rows.append(repair())
        with_rel = dp.ticket_outcome(rows, "t1")
        self.assertEqual(plain["ending"], with_rel["ending"])
        self.assertEqual(plain["withdrawn_at"], with_rel["withdrawn_at"])

    def test_unrelated_ticket_is_not_credited(self):
        rows, _ = frozen_rows()
        out = dp.ticket_outcome(rows, "t-other")
        self.assertIsNone(out["repaired_by"])
        self.assertEqual(out["repaired_unresolved"], [])


class DiskAnchoredTest(unittest.TestCase):
    """Both consumers agree over a REAL ledger read back from disk."""

    def test_round_trip_ledger_both_faces_agree(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "delivery.jsonl"
            rows0, lrow = frozen_rows()
            dc.append_rows(rows0, path)
            rel = dp.record_relation(
                dc.REL_KIND_REPAIRS, "t2", "t1", "host",
                "fixes t1's landing", EV_TICKET)
            dc.append_rows([rel], path)
            back, bad = dc.read_rows(path)
            self.assertEqual(bad, [])
            # freeze face: the disk-read relation grants the exemption
            self.assertTrue(dc.may_land(back, LINE, "fix", ticket="t2",
                                        repair=rel))
            # beneficiary face: the same disk-read rows credit the repair
            out = dp.ticket_outcome(back, "t1")
            self.assertEqual(out["repaired_by"], "t2")
            # and the selector sees it too
            self.assertEqual([r["id"] for r in
                              dp.repairing_relations(back, "t2")],
                             [rel["id"]])

    def test_repairing_relations_selector_shape(self):
        rows, _ = frozen_rows()
        rows.append(repair(id="rel-r05", kind=dc.REL_KIND_WITHDRAWS))
        rows.append(repair())
        sel = dp.repairing_relations(rows, "t2")
        self.assertEqual([r["id"] for r in sel], ["rel-r01"])
        self.assertEqual(dp.repairing_relations(rows, "nobody"), [])


if __name__ == "__main__":
    unittest.main()
