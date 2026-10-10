# -*- coding: utf-8 -*-
"""L1/L2 unit tests for t261009-62 (relation evidence, recorder permission,
correction by a NEW record).

Three behaviours, each with a receipt:

1. Every relation row carries ``evidence`` in the one declared shape
   (``{"what": <subject>, "ref": <non-empty str>}``); an evidence-less or
   malformed relation is refused BY NAME at write time.
2. The recorder permission is a per-kind table; a relation whose benefit
   falls on the recorder's own ticket (``ticket:<from>``) is refused by
   name, and a recorder that cannot be evaluated fails closed.
3. A wrong relation is corrected by a NEW row naming the old row's id via
   ``supersedes_relation``; the resolver ``current_relations`` drops the
   older row from the current view while the file keeps it byte-identical
   (proven by reading the ledger back from DISK, not from a return value).

External-input discipline: hand-written ledger lines with junk evidence
types are read back and refused on append; no real external source.
Integration entries are NOT run here.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402

EV = {"what": "ticket", "ref": "t1"}


def legacy_row(**kw):
    """A pre-t261009-62 row: no evidence key at all (the on-disk old state)."""
    row = rel_row()
    del row["evidence"]
    row.update(kw)
    return row


def rel_row(**kw):
    base = {"id": "rel-x01", "from": "t2", "to": "t1",
            "kind": dc.REL_KIND_WITHDRAWS, "recorded_by": "host",
            "reason": "undo t1", "evidence": dict(EV), "at": 1791510000000}
    base.update(kw)
    return base


class RelationEvidenceTest(unittest.TestCase):
    """Behaviour 1: evidence is required, in the declared shape."""

    def test_valid_evidence_round_trips(self):
        row = dp.record_relation("withdraws", "t2", "t1", "host", "undo", EV)
        self.assertEqual(dc.validate_row(row), (row, ""))
        self.assertEqual(row["evidence"], EV)

    def test_every_declared_subject_is_accepted(self):
        for what in dc.RELATION_EVIDENCE_WHATS:
            row = dp.record_relation("withdraws", "t2", "t1", "host", "undo",
                                     {"what": what, "ref": "x"})
            self.assertEqual(dc.validate_row(row), (row, ""), what)

    def test_evidence_less_row_refused_by_name(self):
        cases = [
            (rel_row(evidence=None), "relation_missing_evidence"),
            (rel_row(evidence={}), "relation_evidence_what_unknown:None"),
            (rel_row(evidence="rev1"), "relation_missing_evidence"),
            (rel_row(evidence=["rev1"]), "relation_missing_evidence"),
            (rel_row(evidence=7), "relation_missing_evidence"),
            (rel_row(evidence={"what": "mood", "ref": "x"}),
             "relation_evidence_what_unknown:'mood'"),
            (rel_row(evidence={"what": "revision"}),
             "relation_evidence_ref_invalid"),
            (rel_row(evidence={"what": "revision", "ref": ""}),
             "relation_evidence_ref_invalid"),
            (rel_row(evidence={"what": "revision", "ref": "   "}),
             "relation_evidence_ref_invalid"),
            (rel_row(evidence={"what": "revision", "ref": 3}),
             "relation_evidence_ref_invalid"),
            (rel_row(evidence={"what": "revision", "ref": "x", "junk": 1}),
             ""),  # extra keys ride along: shape is a minimum, not a seal
        ]
        for row, why in cases:
            clean, got = dc.validate_row(row)
            self.assertEqual(got, why, row)
            if why:
                self.assertIsNone(clean)

    def test_record_relation_requires_evidence_argument(self):
        with self.assertRaises(TypeError):
            dp.record_relation("withdraws", "t2", "t1", "host", "undo")


class RecorderPermissionTest(unittest.TestCase):
    """Behaviour 2: the per-kind recorder table; self-benefit refused by
    name; fail closed when the rule cannot be evaluated."""

    def test_every_kind_has_a_rule(self):
        for kind in dc.RELATION_KINDS:
            self.assertIn(kind, dc.RELATION_RECORDER_RULES)

    def test_self_benefiting_recorder_refused_by_name(self):
        for kind in dc.RELATION_KINDS:
            # the builder refuses loudly...
            with self.assertRaises(dp.PromoteError) as cm:
                dp.record_relation(kind, "t2", "t1", "ticket:t2", "undo",
                                   dict(EV))
            self.assertIn("relation_self_benefit:t2", str(cm.exception))
            # ...and the validator names the refusal for a direct row too
            row = rel_row(kind=kind, recorded_by="ticket:t2")
            self.assertEqual(dc.validate_row(row),
                             (None, "relation_self_benefit:t2"), kind)

    def test_other_ticket_form_and_bare_actors_pass(self):
        for by in ("ticket:t3", "host", "integration", "patrol"):
            row = dp.record_relation("withdraws", "t2", "t1", by, "undo",
                                     dict(EV))
            self.assertEqual(dc.validate_row(row), (row, ""), by)

    def test_malformed_ticket_recorder_fails_closed(self):
        for by in ("ticket:", "ticket:  "):
            row = rel_row(recorded_by=by)
            clean, why = dc.validate_row(row)
            self.assertIn(why, ("relation_recorder_malformed",
                                "relation_missing_recorded_by"), by)
            self.assertIsNone(clean)

    def test_ruleless_kind_refuses(self):
        row = rel_row()
        rules = dict(dc.RELATION_RECORDER_RULES)
        del rules[row["kind"]]
        old = dc.RELATION_RECORDER_RULES
        dc.RELATION_RECORDER_RULES = rules
        try:
            self.assertEqual(dc.validate_row(row),
                             (None, "relation_recorder_rule_missing:%s"
                              % row["kind"]))
        finally:
            dc.RELATION_RECORDER_RULES = old


class SupersedesRelationTest(unittest.TestCase):
    """Behaviour 3: correction by a NEW record, resolved at read."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.ledger = self.dir / "delivery.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _append(self, rows):
        return dp.append_rows(rows, self.ledger)

    def test_correction_row_local_checks(self):
        good = dp.record_relation("withdraws", "t2", "t1", "host", "undo",
                                  dict(EV))
        clean, why = dc.validate_row(
            dict(good, supersedes_relation="rel-x99"))
        self.assertEqual((clean is not None, why), (True, ""))
        for bad, why in ((dict(good, supersedes_relation="t1"),
                          "relation_supersedes_not_rel"),
                         (dict(good, supersedes_relation=good["id"]),
                          "relation_supersedes_self"),
                         (dict(good, supersedes_relation=""),
                          "relation_supersedes_not_rel"),
                         (dict(good, supersedes_relation=7),
                          "relation_supersedes_not_rel")):
            clean, got = dc.validate_row(bad)
            self.assertEqual(got, why, bad)
            self.assertIsNone(clean)

    def test_current_view_after_correction_reads_back_from_disk(self):
        wrong = dp.record_relation("repairs", "t2", "t1", "host",
                                   "wrong attribution", dict(EV),
                                   at_ms=1791510000000)
        self._append([wrong])
        right = dp.record_relation("repairs", "t3", "t1", "host",
                                   "correct attribution", dict(EV),
                                   supersedes_relation=wrong["id"],
                                   at_ms=1791510010000)
        self._append([right])

        # read the FILE back from disk, not the append return values
        raw = self.ledger.read_text(encoding="utf-8")
        self.assertIn(wrong["id"], raw)
        self.assertIn(right["id"], raw)
        rows, _bad = dc.read_rows(self.ledger)

        # the old row stays byte-identical in the file
        old_line = [l for l in raw.splitlines() if wrong["id"] in l][0]
        self.assertEqual(json.loads(old_line)["reason"], "wrong attribution")
        on_disk = [r for r in rows if r.get("id") == wrong["id"]][0]
        self.assertEqual(on_disk["reason"], "wrong attribution")

        # ... and is non-current in every reader of the current state
        current = dp.current_relations(rows)
        self.assertEqual([r["id"] for r in current], [right["id"]])

    def test_unsuperseded_rows_stay_current(self):
        a = dp.record_relation("withdraws", "t2", "t1", "host", "a", dict(EV))
        b = dp.record_relation("repairs", "t3", "t1", "host", "b", dict(EV))
        self._append([a, b])
        rows, _ = dc.read_rows(self.ledger)
        self.assertEqual({r["id"] for r in dp.current_relations(rows)},
                         {a["id"], b["id"]})

    def test_superseded_then_superseded_chain_resolves(self):
        r1 = dp.record_relation("repairs", "t2", "t1", "host", "v1", dict(EV),
                                at_ms=1)
        self._append([r1])
        r2 = dp.record_relation("repairs", "t3", "t1", "host", "v2", dict(EV),
                                supersedes_relation=r1["id"], at_ms=2)
        self._append([r2])
        r3 = dp.record_relation("repairs", "t4", "t1", "host", "v3", dict(EV),
                                supersedes_relation=r2["id"], at_ms=3)
        self._append([r3])
        rows, _ = dc.read_rows(self.ledger)
        self.assertEqual([r["id"] for r in dp.current_relations(rows)],
                         [r3["id"]])

    def test_supersedes_cycle_both_non_current(self):
        # Decided, pinned outcome (review condition 2a): in a cycle each row
        # names the other, so NEITHER stands as current — the file's honest
        # state is that neither claim wins; the raw rows keep the history.
        a = dp.record_relation("repairs", "t2", "t1", "host", "a", dict(EV),
                               at_ms=1)
        self._append([a])
        b = dp.record_relation("repairs", "t3", "t1", "host", "b", dict(EV),
                               supersedes_relation=a["id"], at_ms=2)
        self._append([b])
        a2 = dp.record_relation("repairs", "t4", "t1", "host", "a2", dict(EV),
                                supersedes_relation=b["id"], at_ms=3)
        self._append([a2])
        rows, _ = dc.read_rows(self.ledger)
        current_ids = {r["id"] for r in dp.current_relations(rows)}
        # b is superseded by a2; a is superseded by b — a stays current only
        # if nothing supersedes it, but b does, so a is out too.
        self.assertNotIn(b["id"], current_ids)
        self.assertNotIn(a["id"], current_ids)
        self.assertIn(a2["id"], current_ids)

    def test_dangling_pointer_stays_current(self):
        # Decided, pinned outcome (review condition 2b): row-local write
        # checks cannot see the ledger, so a supersedes_relation naming an
        # id no row carries is accepted at write; at read it never matches,
        # so the correcting row simply stays current.
        r = dp.record_relation("repairs", "t2", "t1", "host", "r", dict(EV),
                               supersedes_relation="rel-nonexistent")
        self._append([r])
        rows, _ = dc.read_rows(self.ledger)
        self.assertEqual([x["id"] for x in dp.current_relations(rows)],
                         [r["id"]])

    def test_resolver_skips_junk_without_revalidating(self):
        # Review condition 1: the resolver filters on (a) parseable dict
        # with a rel- id and (b) the supersedes linkage ONLY. A LEGACY row
        # written before evidence existed must stay visible here — a
        # write-time rule going silent at read time would be the
        # writer-says-ok/reader-can't-see failure class.
        legacy = legacy_row(id="rel-legacy01")
        current = dp.current_relations([legacy, "junk", 3, None,
                                        {"kind": "withdraws", "to": "t1"}])
        self.assertEqual([r["id"] for r in current], ["rel-legacy01"])

    def test_legacy_rows_survive_append_validation_discipline(self):
        # Append-time validation is where the new rules live; the reader of
        # existing bytes is untouched. Legacy-shape rows on disk (no
        # evidence) still parse through read_rows.
        self.ledger.write_text(
            json.dumps(legacy_row(id="rel-legacy01")) + "\n",
            encoding="utf-8")
        rows, bad = dc.read_rows(self.ledger)
        self.assertEqual(bad, [])
        self.assertEqual(rows[0]["id"], "rel-legacy01")
        self.assertNotIn("evidence", rows[0])
        # ... while the same shape cannot be APPENDED any more:
        result = dp.append_rows([legacy_row(id="rel-legacy02")],
                                self.ledger)
        self.assertEqual(result["written"], 0)
        self.assertEqual(result["rejected"][0]["reason"],
                         "relation_missing_evidence")


if __name__ == "__main__":
    unittest.main()
