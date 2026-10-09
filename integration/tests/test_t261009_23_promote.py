# -*- coding: utf-8 -*-
"""L1 unit tests for server/engine/develop_promote.py (ticket t261009-23).

Truth tables for: the promotion record (signer / on_behalf_of / authority as
three machine-checkable fields; refusal by name, never defaulted; main_after
== certified revision), the three-stage ticket outcome projection (landed /
certified / delivered independent, cursor carried), the withdrawal relation
and the patch-identity promotion guard (named failures, never an empty
guard), and the promotion-ledger store face (flock append, duplicate
refusal, malformed-line loudness, no rewrite).

External-input discipline: every consumer of ledger bytes, relation rows,
run verdicts or git output gets malformed-input cases here, with fixtures —
never a real external source, never an integration entry.

Runs with the engine venv (server/engine/.venv) like the rest of
integration/tests; a real `git init` fixture repo is created in a temp dir
for the patch-id cases.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402


def LANDING(idx, ticket="t1", line="default", repo="r", revision=None,
            seq=None, at=1791507005123):
    row = {"kind": dc.KIND_LANDING, "id": "ldg-x%03d" % idx, "ticket": ticket,
           "line": line, "repos": [{"repo": repo,
                                    "revision": revision or ("rev%d" % idx)}],
           "actor": "engine", "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


def CERT(idx, line="default", run="run-a", revision="rev1",
         seq=None, at=1791508000000):
    row = {"kind": dc.KIND_CERT, "id": "cert-x%03d" % idx, "line": line,
           "repos": [{"repo": "r", "revision": revision}], "run": run,
           "booked_red": "none", "judged_by": "integration", "at": at}
    if seq is not None:
        row["seq"] = seq
    return row


def PROM(**kw):
    base = dict(cert_id="cert-x001", line="default", tickets=["t1"],
                main_before=[{"repo": "r", "revision": "old"}],
                main_after=[{"repo": "r", "revision": "rev1"}],
                signer="integration", at_ms=1791512000000)
    base.update(kw)
    return base


def try_build(delivery_rows, **kw):
    try:
        dp.build_promotion(delivery_rows=delivery_rows, **kw)
        return None
    except dp.PromotionRefused as exc:
        return exc.args[0]


class TempCase(unittest.TestCase):
    """Temp-dir plumbing reclaimed in tearDown (lint L8)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.delivery = self.dir / "delivery.jsonl"
        self.promo = dp.promotion_path("proj", ledger_dir=str(self.dir))

    def tearDown(self):
        self._tmp.cleanup()

    def append_delivery(self, rows):
        res = dc.append_rows(rows, self.delivery)
        self.assertEqual(res["rejected"], [], res)
        return res

    def seeded(self):
        self.append_delivery([LANDING(1, "t1", seq=1),
                              LANDING(2, "t2", seq=2, revision="rev2"),
                              CERT(1, revision="rev1", seq=3),
                              CERT(2, run="run-b", revision="rev2", seq=4)])
        rows, _ = dc.read_rows(self.delivery)
        return rows

    def rows(self):
        rows, bad = dc.read_rows(self.delivery)
        self.assertEqual(bad, [])
        return rows


class TestPromotionRecord(TempCase):
    """Spec (a) + (b) + (d): one signature, named and traceable; no content
    without a proof; the record is the durable account."""

    def test_happy_path_with_delegation(self):
        rows = self.seeded()
        row = dp.build_promotion(delivery_rows=rows, **PROM(
            on_behalf_of="host", authority="host order 261009"))
        self.assertEqual(row["kind"], "promotion")
        self.assertEqual(row["signer"], "integration")
        self.assertEqual(row["on_behalf_of"], "host")
        self.assertEqual(row["authority"], "host order 261009")
        self.assertEqual(row["certification"], "cert-x001")
        self.assertEqual(row["tickets"], ["t1"])
        self.assertEqual(row["repos"], [{"repo": "r", "revision": "rev1"}])
        self.assertEqual(row["main_before"], [{"repo": "r", "revision": "old"}])
        self.assertEqual(row["main_after"], [{"repo": "r", "revision": "rev1"}])
        self.assertTrue(row["id"].startswith("prom-"))
        res = dp.append_rows([row], self.delivery)
        self.assertEqual(res["written"], 1)
        # durable, in an append-only ledger — never in main
        back, bad = dp.read_promotion_rows(self.delivery)
        self.assertEqual(bad, [])
        self.assertEqual(back[-1]["id"], row["id"])
        # the shared writer stamped the promotion into the ONE seq space
        self.assertEqual(back[-1]["seq"], 5)

    def test_no_signature_without_delegation_fields(self):
        rows = self.seeded()
        row = dp.build_promotion(delivery_rows=rows, **PROM())
        self.assertIsNone(row["on_behalf_of"])
        self.assertIsNone(row["authority"])

    def test_no_certification_named_is_refused_by_name(self):
        rows = self.seeded()
        self.assertEqual(try_build(rows, **PROM(cert_id=None)),
                         "promotion_without_named_certification")
        self.assertEqual(try_build(rows, **PROM(cert_id="")),
                         "promotion_without_named_certification")
        self.assertEqual(try_build(rows, **PROM(cert_id="ldg-x001")),
                         "promotion_without_named_certification")
        # never defaulted: nothing was appended — the seeded rows are all
        # that is in the ledger
        self.assertEqual(len(self.rows()), 4)

    def test_certification_must_exist_and_be_green(self):
        rows = self.seeded()
        self.assertEqual(try_build(rows, **PROM(cert_id="cert-nope")),
                         "certification_not_in_ledger:cert-nope")
        red = try_build(rows, **PROM(cert_id="cert-x001", is_green=lambda r: False))
        self.assertEqual(red, "certification_not_green:cert-x001")
        ok = try_build(rows, **PROM(cert_id="cert-x001", is_green=lambda r: True))
        self.assertIsNone(ok)

    def test_tickets_must_be_covered(self):
        rows = self.seeded()
        self.assertEqual(try_build(rows, **PROM(tickets=["t9"])),
                         "tickets_not_covered:t9")
        # a landing at a revision the certification did not cover
        self.assertEqual(try_build(rows, **PROM(tickets=["t2"])),
                         "tickets_not_covered:t2")
        both = try_build(rows, **PROM(tickets=["t1", "t9"]))
        self.assertEqual(both, "tickets_not_covered:t9")

    def test_main_after_must_equal_certified_revision(self):
        rows = self.seeded()
        self.assertEqual(try_build(rows, **PROM(
            main_after=[{"repo": "r", "revision": "zzz"}])),
            "main_after_not_certified_revision")

    def test_signer_required_and_delegation_fields_stand_together(self):
        rows = self.seeded()
        self.assertEqual(try_build(rows, **PROM(signer="")),
                         "promotion_missing_signer")
        self.assertEqual(try_build(rows, **PROM(on_behalf_of="host")),
                         "delegation_incomplete")
        self.assertEqual(try_build(rows, **PROM(authority="order 7")),
                         "delegation_incomplete")
        self.assertEqual(try_build(rows, **PROM(on_behalf_of="", authority="x")),
                         "delegation_on_behalf_of_invalid")


class TestStoreFace(TempCase):
    """The delivery ledger IS the promotion ledger now (t261009-29): one
    writer, one seq space."""

    def test_append_assigns_monotonic_seq_and_refuses_duplicates(self):
        rows = self.seeded()
        rel = dp.record_relation("withdraws", "t2", "t1", "integration", "undo")
        r1 = dp.append_rows([rel], self.delivery)
        # the promotion's seq continues the DELIVERY ledger's space
        self.assertEqual(r1["seqs"], [5])
        r2 = dp.append_rows([rel], self.delivery)
        self.assertEqual(r2["written"], 0)
        self.assertTrue(r2["rejected"][0]["reason"].startswith("duplicate_id:"))

    def test_unknown_kind_refused_by_name(self):
        row = {"id": "zzz-1", "at": 1}
        res = dp.append_rows([row], self.delivery)
        self.assertEqual(res["rejected"][0]["reason"], "kind_unknown:None")

    def test_malformed_ledger_blocks_append_loudly(self):
        self.delivery.parent.mkdir(parents=True, exist_ok=True)
        self.delivery.write_text("{not json}\n", encoding="utf-8")
        rel = dp.record_relation("withdraws", "t2", "t1", "integration", "undo")
        with self.assertRaises(dp.PromoteError):
            dp.append_rows([rel], self.delivery)

    def test_validate_row_truth_table(self):
        good = dp.record_relation("withdraws", "t2", "t1", "integration", "undo")
        self.assertEqual(dp.validate_row(good), (good, ""))
        cases = [
            (None, "row_not_object"),
            # t261009-29: one shared validator — the refusal names are the
            # delivery ledger's kind table now, not the old family dispatch.
            ({}, "kind_unknown:None"),
            (dict(good, kind="reverts"), "kind_unknown:'reverts'"),  # no revert type
            (dict(good, kind="revenge"), "kind_unknown:'revenge'"),
            (dict(good, to=""), "relation_missing_to"),
            (dict(good, recorded_by=""), "relation_missing_recorded_by"),
            (dict(good, reason=""), "relation_missing_reason"),
            (dict(good, at="now"), "at_not_ms"),
        ]
        for row, why in cases:
            self.assertEqual(dp.validate_row(row), (None, why), row)

    def test_no_revert_record_type_exists(self):
        # spec (e): a withdrawal is work + a relation; the schema cannot
        # even express a revert record — anything named like one falls out
        # as an unknown relation kind or an unknown family.
        self.assertNotIn("revert", (dp.RELATION_KINDS))
        self.assertEqual(dp.validate_row({"id": "rev-1", "kind": "revert"}),
                         (None, "kind_unknown:'revert'"))


class TestWithdrawalGuard(TempCase):
    """Spec (e): the ledger keeps the relation; the promotion check refuses
    a candidate that re-introduces a withdrawn patch."""

    def _git_repo(self):
        repo = self.dir / "repo"
        repo.mkdir()
        def g(*args):
            p = subprocess.run(["git"] + list(args), cwd=str(repo),
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            return p
        g("init", "-q", "-b", "main")
        g("config", "user.email", "ut@example.com")
        g("config", "user.name", "ut")
        revs = []
        for i, text in enumerate(["one\n", "two\n", "three\n"]):
            (repo / "f.txt").write_text(text, encoding="utf-8")
            g("add", "-A")
            g("commit", "-qm", "c%d" % i)
            revs.append(g("rev-parse", "HEAD").stdout.strip())
        return repo, revs

    def _seed(self, revs, repo):
        name = "repo"
        self.append_delivery([
            LANDING(1, "t1", repo=name, revision=revs[0], seq=1),
            LANDING(2, "t2", repo=name, revision=revs[1], seq=2),
            LANDING(3, "t3", repo=name, revision=revs[2], seq=3),
            CERT(1, revision=revs[2], seq=4),
        ])
        delivery, _ = dc.read_rows(self.delivery)
        dp.append_rows([dp.record_relation(
            "withdraws", "t2", "t1", "integration", "undo t1", at_ms=1)],
            self.delivery)
        rows, _ = dc.read_rows(self.delivery)
        return rows

    def test_reintroducing_withdrawn_patch_is_refused_by_name(self):
        repo, revs = self._git_repo()
        by_name = {"repo": str(repo)}.get
        fn = lambda rev, name: dp.patch_id(rev, by_name(name))  # noqa: E731
        rows = self._seed(revs, repo)
        try:
            dp.check_withdrawn("t1", rows, fn, "repo")
            self.fail("re-introduction was allowed")
        except dp.PromotionRefused as exc:
            self.assertTrue(exc.args[0].startswith("withdrawn_patch_present:rel-"))
        # the withdrawal's own landing and an unrelated one are clean
        self.assertIsNotNone(dp.check_withdrawn("t2", rows, fn, "repo"))
        self.assertIsNotNone(dp.check_withdrawn("t3", rows, fn, "repo"))

    def test_guard_failure_is_named_never_empty(self):
        repo, revs = self._git_repo()
        rows = self._seed(revs, repo)
        def boom(rev, name):
            raise dp.PatchIdUnavailable("patch_id_difftree_failed:%s" % rev)
        with self.assertRaises(dp.PatchIdUnavailable):
            dp.check_withdrawn("t1", rows, boom, "repo")

    def test_unknown_withdrawn_target_is_loud(self):
        rows = self.seeded()
        dp.append_rows([dp.record_relation(
            "withdraws", "t2", "t-ghost", "integration", "undo", at_ms=1)],
            self.delivery)
        rows, _ = dc.read_rows(self.delivery)
        with self.assertRaises(dp.WithdrawnTargetUnknown):
            dp.withdrawn_patch_ids(rows, lambda rev, name: "p", "r")

    def test_patch_id_failure_modes_are_named(self):
        repo, revs = self._git_repo()
        for bad in ("", None):
            with self.assertRaises(dp.PatchIdUnavailable):
                dp.patch_id(bad, str(repo))
        with self.assertRaises(dp.PatchIdUnavailable):
            dp.patch_id("deadbeef", str(repo))  # unknown object -> diff-tree non-zero
        with self.assertRaises(dp.PatchIdUnavailable):
            dp.patch_id(revs[0], str(self.dir / "not-a-repo"))
        with self.assertRaises(dp.PatchIdUnavailable):
            dp.patch_id(revs[0], str(self.dir / "nope" / "missing"))

    def test_patch_id_is_stable_per_content(self):
        repo, revs = self._git_repo()
        self.assertEqual(dp.patch_id(revs[0], str(repo)),
                         dp.patch_id(revs[0], str(repo)))
        self.assertNotEqual(dp.patch_id(revs[0], str(repo)),
                            dp.patch_id(revs[1], str(repo)))


class TestTicketOutcome(TempCase):
    """Spec (c): landed / certified / delivered stay three different things."""

    def test_waiting_ticket_is_landed_not_certified_not_delivered(self):
        rows = self.seeded()
        # t2's landing IS covered by cert-x002 (rev2); a ticket waiting is
        # one whose landing no green certification's revision covers
        out = dp.ticket_outcome(rows, "t2")
        self.assertEqual(out["certified_by"], "cert-x002")
        self.append_delivery([LANDING(7, "t4", revision="rev4", seq=5)])
        rows2, _ = dc.read_rows(self.delivery)
        out = dp.ticket_outcome(rows2, "t4")
        self.assertEqual(out["landed_at"], [{"repo": "r", "revision": "rev4"}])
        self.assertIsNone(out["certified_by"])
        self.assertIsNone(out["delivered_in"])
        self.assertEqual(out["waiting_since"], 1791507005123)

    def test_certified_but_not_delivered(self):
        rows = self.seeded()
        out = dp.ticket_outcome(rows, "t1")
        self.assertEqual(out["landed_at"], [{"repo": "r", "revision": "rev1"}])
        self.assertEqual(out["certified_by"], "cert-x001")
        self.assertIsNone(out["delivered_in"])  # closed != delivered
        self.assertIsNone(out["waiting_since"])

    def test_delivered_is_derived_from_the_promotion_file_alone(self):
        rows = self.seeded()
        row = dp.build_promotion(delivery_rows=rows, **PROM(
            cert_id="cert-x002", main_after=[{"repo": "r", "revision": "rev2"}],
            tickets=["t2"]))
        dp.append_rows([row], self.delivery)
        rows, _ = dc.read_rows(self.delivery)
        out = dp.ticket_outcome(rows, "t2")
        self.assertEqual(out["certified_by"], "cert-x002")
        self.assertEqual(out["delivered_in"], row["id"])
        # t261009-29: one file, one seq — the delivery's own seq is readable
        # off the single cursor (the promotion landed after seq 4)
        self.assertEqual(out["as_of"], {"delivery": 5})

    def test_reverted_at_comes_from_the_withdrawal_relation(self):
        rows = self.seeded()
        # t2 delivered, then withdrawn by t3 whose landing is later delivered
        row = dp.build_promotion(delivery_rows=rows, **PROM(
            cert_id="cert-x002", main_after=[{"repo": "r", "revision": "rev2"}],
            tickets=["t2"]))
        dp.append_rows([row], self.delivery)
        self.append_delivery([LANDING(9, "t3", revision="rev3", seq=9),
                              CERT(3, run="run-c", revision="rev3", seq=10)])
        rows2, _ = dc.read_rows(self.delivery)
        prom3 = dp.build_promotion(delivery_rows=rows2, **PROM(
            cert_id="cert-x003", main_after=[{"repo": "r", "revision": "rev3"}],
            tickets=["t3"], at_ms=1791514000000))
        dp.append_rows([dp.record_relation(
            "withdraws", "t3", "t2", "integration", "undo t2", at_ms=5)],
            self.delivery)
        dp.append_rows([prom3], self.delivery)
        rows2, _ = dc.read_rows(self.delivery)
        out = dp.ticket_outcome(rows2, "t2")
        self.assertEqual(out["delivered_in"], row["id"])
        self.assertEqual(out["reverted_at"], 1791514000000)
        # the withdrawal ticket itself: delivered, not reverted
        out3 = dp.ticket_outcome(rows2, "t3")
        self.assertIsNotNone(out3["delivered_in"])
        self.assertIsNone(out3["reverted_at"])

    def test_projection_is_derived_only_and_carries_the_cursor(self):
        rows = self.seeded()
        out = dp.ticket_outcome(rows, "t1")
        self.assertNotIn("id", out)
        self.assertNotIn("seq", out)
        self.assertNotIn("at", out)
        self.assertEqual(out["as_of"], {"delivery": 4})

    def test_never_landed_ticket(self):
        rows = self.seeded()
        out = dp.ticket_outcome(rows, "t-ghost")
        self.assertIsNone(out["landed_at"])
        self.assertIsNone(out["certified_by"])
        self.assertIsNone(out["delivered_in"])
        self.assertIsNone(out["waiting_since"])

    def test_unnamed_ticket_is_refused(self):
        with self.assertRaises(dp.PromoteError):
            dp.ticket_outcome([], "")

    def test_red_certification_does_not_certify(self):
        rows = self.seeded()
        out = dp.ticket_outcome(rows, "t1", is_green=lambda run: run != "run-a")
        # cert-x001 ran run-a (red by this verdict) — the next green one
        # covers a different revision, so t1 stays waiting
        self.assertIsNone(out["certified_by"])
        self.assertIsNotNone(out["waiting_since"])


if __name__ == "__main__":
    unittest.main()
