# -*- coding: utf-8 -*-
"""t261009-29 — the promotion joins the delivery records' ordering space.

ONE ledger file (``delivery.jsonl``), ONE writer
(``develop_certify.append_rows``), ONE seq space for landings,
certifications, promotions and relations. What this battery pins:

1. the shared writer admits the promotion and relation kinds and stamps
   them into the SAME monotonic seq space (the promotion row keeps every
   field it had and GAINS the ``seq`` — ticket item (1));
2. the legacy sibling file ``promotion.jsonl`` is either migrated — seq
   order preserved by ``at`` then file order — or refused BY NAME, never
   silently read as "no promotions" (ticket item (2), review condition 2:
   the refusal sits on every consumer-reachable face);
3. the projection reads one list; ``as_of`` is the single cursor; no
   comparison spans files because there is one file (ticket item (3)).

External-input discipline: the legacy file is external input — malformed
lines, invalid rows, duplicates and half-migrated states are all fixture
cases here, never a real external source. Pure unit tests over temp dirs;
no git, no network, no integration entry (UT discipline).
"""
import json
import tempfile
import unittest
from pathlib import Path

import develop_certify as dc
import develop_promote as dp


def LANDING(idx, ticket="t1", revision=None, at=1000):
    return {"kind": dc.KIND_LANDING, "id": "ldg-%03d" % idx,
            "ticket": ticket, "line": "default",
            "repos": [{"repo": "r", "revision": revision or ("rev%d" % idx)}],
            "actor": "engine", "at": at}


def CERT(idx, revision="rev1", run="run-a", at=2000):
    return {"kind": dc.KIND_CERT, "id": "cert-%03d" % idx, "line": "default",
            "repos": [{"repo": "r", "revision": revision}], "run": run,
            "booked_red": "none", "judged_by": "integration", "at": at}


def PROM(idx, tickets=("t1",), cert_id="cert-001", at=3000):
    return {"kind": dc.KIND_PROMOTION, "id": "prom-%03d" % idx,
            "certification": cert_id, "line": "default",
            "repos": [{"repo": "r", "revision": "rev1"}],
            "tickets": list(tickets),
            "main_before": [{"repo": "r", "revision": "old"}],
            "main_after": [{"repo": "r", "revision": "rev1"}],
            "signer": "integration", "on_behalf_of": None,
            "authority": None, "at": at}


def REL(idx, kind, from_t, to_t, at=4000):
    # t261009-62: relation rows carry evidence in the declared shape
    return {"kind": kind, "id": "rel-%03d" % idx, "from": from_t, "to": to_t,
            "recorded_by": "integration", "reason": "t261009-29 test",
            "evidence": {"what": "ticket", "ref": to_t},
            "at": at}


class TempCase(unittest.TestCase):
    """Temp-dir plumbing reclaimed in tearDown (lint L8)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.delivery = self.dir / "delivery.jsonl"
        self.legacy = self.dir / "promotion.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def append(self, rows, path=None):
        res = dp.append_rows(rows, path or self.delivery)
        self.assertEqual(res["rejected"], [], res)
        return res

    def rows(self, path=None):
        rows, bad = dc.read_rows(path or self.delivery)
        self.assertEqual(bad, [])
        return rows


class TestOneSeqSpace(TempCase):
    """Ticket item (1): one writer, one monotonic seq across every kind."""

    def test_shared_writer_admits_promotion_and_relation(self):
        self.append([LANDING(1)])
        self.append([CERT(1)])
        self.append([PROM(1)])
        self.append([REL(1, dp.REL_KIND_WITHDRAWS, "t2", "t1")])
        rows = self.rows()
        self.assertEqual([r["kind"] for r in rows],
                         ["landing", "certification", "promotion", "withdraws"])
        # ONE monotonic space — the promotion GAINED the shared seq
        self.assertEqual([r["seq"] for r in rows], [1, 2, 3, 4])
        self.assertEqual(rows[2]["certification"], "cert-001")
        self.assertEqual(rows[2]["signer"], "integration")

    def test_promotion_row_keeps_every_field_it_had(self):
        row = dict(PROM(1), on_behalf_of="host", authority="host order",
                   note="n")
        self.append([row])
        back = self.rows()[0]
        for f in ("id", "certification", "line", "repos", "tickets",
                  "main_before", "main_after", "signer", "on_behalf_of",
                  "authority", "note", "at"):
            self.assertEqual(back[f], row[f], f)
        self.assertIn("seq", back)

    def test_cert_after_landing_rule_now_spans_the_former_split(self):
        # the load-bearing rule the record-models doc states: landings after
        # the previous certification are computable — with the promotion in
        # the SAME space, a certification appended after a promotion still
        # orders against the landing it covers.
        self.append([LANDING(1), PROM(1), CERT(1, revision="rev1")])
        rows = self.rows()
        landing = next(r for r in rows if r["kind"] == "landing")
        cert = next(r for r in rows if r["kind"] == "certification")
        self.assertGreater(cert["seq"], landing["seq"])

    def test_bad_promotion_row_refused_by_name_through_shared_writer(self):
        res = dp.append_rows([dict(PROM(1), certification="ldg-1")],
                             self.delivery)
        self.assertEqual(res["written"], 0)
        self.assertEqual(res["rejected"][0]["reason"],
                         "promotion_without_named_certification")
        res = dp.append_rows([dict(PROM(1), id="ldg-9")], self.delivery)
        self.assertEqual(res["rejected"][0]["reason"], "promotion_id_not_prom")
        res = dp.append_rows([dict(PROM(1), on_behalf_of="host")],
                             self.delivery)
        self.assertEqual(res["rejected"][0]["reason"], "delegation_incomplete")
        # all-rejected means zero bytes
        self.assertFalse(self.delivery.exists())


class TestLegacyMigration(TempCase):
    """Ticket item (2): migrate or refuse by name — never a silent empty."""

    def test_migration_preserves_at_then_file_order(self):
        # file order: late-at row FIRST, then two equal-at rows (their file
        # order must survive the tie), then an early one
        # the delivery space already holds seqs 1-2 BEFORE the legacy file
        # is written, so the migration continues the shared seq space
        self.append([LANDING(1), CERT(1)])
        self.legacy.write_text("\n".join(json.dumps(r) for r in [
            PROM(1, at=9000),
            PROM(2, at=1000),
            PROM(3, at=1000),
            LANDING(7, at=1000),
        ]) + "\n", encoding="utf-8")
        res = dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertEqual(res["migrated"], 4)
        self.assertTrue(res["renamed"])
        rows = self.rows()
        by_id = {r["id"]: r["seq"] for r in rows}
        # at ascending; the equal-at pair keeps file order; every seq is
        # assigned by the SHARED writer, continuing the space
        self.assertEqual(
            sorted(by_id.items(), key=lambda kv: kv[1]),
            [("ldg-001", 1), ("cert-001", 2), ("prom-002", 3),
             ("prom-003", 4), ("ldg-007", 5), ("prom-001", 6)])
        self.assertFalse(self.legacy.exists())
        self.assertTrue(Path(str(self.legacy) + ".migrated").exists())

    def test_second_run_is_a_clean_noop(self):
        self.legacy.write_text(json.dumps(PROM(1)) + "\n", encoding="utf-8")
        dp.migrate_legacy_promotion_ledger(self.delivery)
        again = dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertEqual(again, {"migrated": 0, "renamed": False, "seqs": []})
        self.assertEqual(len(self.rows()), 1)

    def test_no_legacy_file_is_a_noop(self):
        res = dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertEqual(res["migrated"], 0)
        self.assertFalse(self.delivery.exists())

    def test_malformed_legacy_line_refuses_by_name(self):
        self.legacy.write_text("{not json}\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertTrue(str(ctx.exception).startswith(
            "legacy_has_malformed_lines:"))

    def test_invalid_legacy_row_refuses_by_name(self):
        self.legacy.write_text(json.dumps(
            dict(PROM(1), tickets=[])) + "\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertTrue(str(ctx.exception).startswith(
            "legacy_row_invalid:prom-001:promotion_tickets_invalid"))

    def test_duplicate_inside_legacy_file_refuses_by_name(self):
        row = PROM(1)
        self.legacy.write_text(
            json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertEqual(str(ctx.exception), "legacy_row_duplicate:prom-001")
        # nothing landed, nothing renamed
        self.assertFalse(self.delivery.exists())
        self.assertTrue(self.legacy.exists())

    def test_id_already_in_delivery_ledger_refuses_by_name(self):
        self.append([PROM(1)])
        self.legacy.write_text(json.dumps(PROM(1)) + "\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertEqual(str(ctx.exception),
                         "id_already_in_delivery_ledger:prom-001")

    def test_malformed_delivery_ledger_blocks_migration_loudly(self):
        self.legacy.write_text(json.dumps(PROM(1)) + "\n", encoding="utf-8")
        self.delivery.write_text("junk\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.migrate_legacy_promotion_ledger(self.delivery)
        self.assertTrue(str(ctx.exception).startswith(
            "ledger_has_malformed_lines:"))

    def test_migration_never_targets_itself(self):
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.migrate_legacy_promotion_ledger(self.legacy)
        self.assertEqual(str(ctx.exception), "legacy_file_is_delivery_ledger")


class TestUnmigratedLegacyRefusal(TempCase):
    """Review condition 2: the refusal sits on EVERY consumer-reachable
    face — the read wrapper and the append face alike."""

    def test_read_face_refuses_unmigrated_legacy_with_rows(self):
        self.legacy.write_text(json.dumps(PROM(1)) + "\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError) as ctx:
            dp.read_promotion_rows(self.delivery)
        self.assertTrue(str(ctx.exception).startswith(
            "legacy_promotion_file_not_migrated:promotion.jsonl:"))

    def test_append_face_refuses_unmigrated_legacy_with_rows(self):
        self.legacy.write_text(json.dumps(PROM(1)) + "\n", encoding="utf-8")
        with self.assertRaises(dp.PromoteError):
            dp.append_rows([LANDING(1)], self.delivery)
        self.assertFalse(self.delivery.exists())

    def test_empty_legacy_file_is_not_a_refusal(self):
        self.legacy.write_text("", encoding="utf-8")
        rows, bad = dp.read_promotion_rows(self.delivery)
        self.assertEqual((rows, bad), ([], []))
        self.assertEqual(dp.append_rows([LANDING(1)], self.delivery)["written"],
                         1)

    def test_no_legacy_file_is_not_a_refusal(self):
        rows, _ = dp.read_promotion_rows(self.delivery)
        self.assertEqual(rows, [])


class TestSingleSpaceProjection(TempCase):
    """Ticket item (3): the projection reads ONE list; one cursor."""

    def test_outcome_reads_one_list_across_all_kinds(self):
        self.append([LANDING(1), CERT(1), PROM(1),
                     REL(1, dp.REL_KIND_SUPERSEDES, "t-new", "t1")])
        rows = self.rows()
        v = dp.ticket_outcome(rows, "t1")
        self.assertEqual(v["landed_at"], [{"repo": "r", "revision": "rev1"}])
        self.assertEqual(v["certified_by"], "cert-001")
        self.assertEqual(v["delivered_in"], "prom-001")
        self.assertEqual(v["superseded_by"], "t-new")
        # the SINGLE cursor of the ONE ordering space
        self.assertEqual(v["as_of"], {"delivery": 4})

    def test_withdrawal_relation_orders_in_the_same_space(self):
        self.append([LANDING(1), CERT(1), PROM(1),
                     REL(1, dp.REL_KIND_WITHDRAWS, "t-w", "t1", at=5000),
                     LANDING(2, ticket="t-w", revision="rev-w", at=6000),
                     CERT(2, revision="rev-w", run="run-b", at=7000),
                     PROM(2, tickets=("t-w",), cert_id="cert-002", at=8000)])
        rows = self.rows()
        v = dp.ticket_outcome(rows, "t1")
        self.assertEqual(v["delivered_in"], "prom-001")
        self.assertEqual(v["reverted_at"], 8000)
        self.assertEqual(v["ending"], "reverted")

    def test_guard_reads_one_list(self):
        self.append([LANDING(1), LANDING(2, ticket="t-w", revision="rev-w"),
                     REL(1, dp.REL_KIND_WITHDRAWS, "t-w", "t1")])
        rows = self.rows()
        # a withdraws relation whose target never landed is loud
        self.append([REL(3, dp.REL_KIND_WITHDRAWS, "t-w", "t-ghost")])
        rows = self.rows()
        with self.assertRaises(dp.WithdrawnTargetUnknown):
            dp.withdrawn_patch_ids(rows, lambda rev, name: "p", "r")

    def test_guard_resolves_landed_targets_from_the_same_list(self):
        self.append([LANDING(1), LANDING(2, ticket="t-w", revision="rev-w"),
                     REL(1, dp.REL_KIND_WITHDRAWS, "t-w", "t1"),
                     LANDING(3, ticket="t-w2", revision="rev-x"),
                     REL(2, dp.REL_KIND_WITHDRAWS, "t-w2", "t1")])
        rows = self.rows()
        guard = dp.withdrawn_patch_ids(rows, lambda rev, name: "pid-" + rev, "r")
        self.assertEqual(list(guard.values()), ["rel-002"])

    def test_malformed_rows_in_the_list_never_crash_the_projection(self):
        junk = ["junk", 3, None, {"kind": "withdraws", "to": "t1"}]
        v = dp.ticket_outcome(junk + [LANDING(1)], "t1")
        self.assertIsNone(v["withdrawn_at"])
        self.assertEqual(v["ending"], "open")


class TestPromoteBufferDriver(unittest.TestCase):
    """The wired driver (t261013): a green certified prefix promotes main
    (fast-forward) and the record lands; a red/absent cert refuses before any
    ref moves. Fixture repo + isolated ledgers via the env seams."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        import subprocess
        self._git = lambda *a: subprocess.run(
            ["git"] + list(a), cwd=str(self.repo), check=True,
            capture_output=True, text=True)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "it@t29")
        self._git("config", "user.name", "it")
        (self.repo / "a.txt").write_text("a\n", "utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "m0")
        self._git("branch", "develop")
        self._git("checkout", "-q", "develop")
        (self.repo / "b.txt").write_text("b\n", "utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "line work")
        self.line_tip = self._git("rev-parse", "HEAD").stdout.strip()
        self.main_tip = self._git("rev-parse", "main").stdout.strip()
        self._git("checkout", "-q", "main")
        # isolated stores: projects root (line decl) + delivery ledger + runs
        self.projects = self.dir / "projects"
        (self.projects / "sandbar" / "data" / "develop").mkdir(parents=True)
        (self.projects / "sandbar" / "data" / "develop" / "lines.json"
         ).write_text(json.dumps(
             [{"line_id": "develop-buffer", "scope": "t", "owner": "host",
               "repositories": [{"name": "sandbar", "branch": "develop"}],
               "extra_scenarios": [], "version": 1}]), "utf-8")
        self.ledger_dir = self.dir / "ledger"
        self.runs_dir = self.dir / "runs"
        self.runs_dir.mkdir()
        self._env = {"SANDBAR_PROJECTS_DIR": str(self.projects),
                     "SANDBAR_DELIVERY_LEDGER_DIR": str(self.ledger_dir),
                     "SANDBAR_SCENARIO_LEDGER_DIR": str(self.runs_dir)}

    def tearDown(self):
        self._tmp.cleanup()

    def _seed_ledger(self, verdict="green"):
        _ldg = LANDING(1, ticket="t-fix", revision=self.line_tip)
        _ldg["line"] = "develop-buffer"
        # the LANDING helper's fixture repo is "r"; this driver fixture names
        # the repo "sandbar" (the line declaration matches) — align it
        _ldg["repos"] = [{"repo": "sandbar", "revision": self.line_tip}]
        dc.append_rows([_ldg], self.ledger_dir / "sandbar.jsonl")
        cert = dc.build_certification(
            [{"repo": "sandbar", "revision": self.line_tip}],
            {"id": "run-green", "cases": {"ran": 3, "passed": 3,
                                          "failed": 0, "env_failed": 0}},
            "none", judged_by="ut", at_ms=2000, line="develop-buffer")
        dc.append_rows([cert], self.ledger_dir / "sandbar.jsonl")
        # the run record lives at the per-project store (the shape the
        # wired reader reads: perkey root / project / ledger)
        runs_store = (self.projects / "sandbar" / "ledger")
        runs_store.mkdir(parents=True, exist_ok=True)
        (runs_store / "scenario-runs.jsonl").write_text(
            json.dumps({"id": "run-green", "verdict": verdict,
                        "cases": {"ran": 3, "passed": 3, "failed": 0,
                                  "env_failed": 0},
                        "suite": "full", "source": "line-round"})
            + "\n", "utf-8")
        return cert["id"]

    def test_green_prefix_promotes_main_and_records(self):
        cert_id = self._seed_ledger("green")
        import unittest.mock as mock
        with mock.patch.dict("os.environ", self._env, clear=False):
            row = dp.promote_buffer("sandbar", "develop-buffer", signer="host",
                                    note="t", repo_paths={"sandbar": self.repo})
        self.assertEqual(row["certification"], cert_id)
        self.assertEqual(row["signer"], "host")
        self.assertEqual(row["tickets"], ["t-fix"])
        # the act: main moved to the certified revision (ff-only)
        cur = self._git("rev-parse", "refs/heads/main").stdout.strip()
        self.assertEqual(cur, self.line_tip)
        # and the worktree followed (main checkout was clean + on main)
        self.assertEqual((self.repo / "b.txt").read_text("utf-8"), "b\n")
        # the record landed in the shared ledger
        rows, bad = dc.read_rows(self.ledger_dir / "sandbar.jsonl")
        self.assertEqual(bad, [])
        promos = [r for r in rows if r.get("kind") == dc.KIND_PROMOTION]
        self.assertEqual(len(promos), 1)
        self.assertEqual(promos[0]["certification"], cert_id)

    # ---- 261015: a certified TIP carries the landings it contains -----------

    def _advance_line_and_certify_the_tip(self):
        """The buffer shape a line reaches after being advanced past its last
        landing: ``develop`` gets another commit (the merge/fix), the last
        landing still points at the OLD tip, and the certification covers the
        NEW tip. Returns (landed_rev, tip_rev)."""
        landed = self.line_tip
        self._git("checkout", "-q", "develop")
        (self.repo / "c.txt").write_text("c\n", "utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "advance past the landing")
        tip = self._git("rev-parse", "refs/heads/develop").stdout.strip()
        self._git("checkout", "-q", "main")
        ldg = LANDING(1, ticket="t-fix", revision=landed)
        ldg["line"] = "develop-buffer"
        ldg["repos"] = [{"repo": "sandbar", "revision": landed}]
        dc.append_rows([ldg], self.ledger_dir / "sandbar.jsonl")
        cert = dc.build_certification(
            [{"repo": "sandbar", "revision": tip}],
            {"id": "run-green", "cases": {"ran": 3, "passed": 3,
                                          "failed": 0, "env_failed": 0}},
            "none", judged_by="ut", at_ms=2000, line="develop-buffer")
        dc.append_rows([cert], self.ledger_dir / "sandbar.jsonl")
        runs_store = (self.projects / "sandbar" / "ledger")
        runs_store.mkdir(parents=True, exist_ok=True)
        (runs_store / "scenario-runs.jsonl").write_text(
            json.dumps({"id": "run-green", "verdict": "green",
                        "cases": {"ran": 3, "passed": 3, "failed": 0,
                                  "env_failed": 0},
                        "suite": "full", "source": "line-round"}) + "\n",
            "utf-8")
        return landed, tip

    def test_certified_tip_carries_the_landings_its_ancestry_contains(self):
        landed, tip = self._advance_line_and_certify_the_tip()
        import unittest.mock as mock
        with mock.patch.dict("os.environ", self._env, clear=False):
            row = dp.promote_buffer("sandbar", "develop-buffer", signer="host",
                                    note="t", repo_paths={"sandbar": self.repo})
        # the landed ticket is delivered by this promotion (contained, and main
        # did not have it) — before 261015 the exact-equality rule carried
        # nothing and the promotion of an advanced line was impossible
        self.assertEqual(row["tickets"], ["t-fix"])
        self.assertEqual(row["main_after"],
                         [{"repo": "sandbar", "revision": tip}])
        self.assertEqual(self._git("rev-parse", "refs/heads/main"
                                   ).stdout.strip(), tip)

    def test_landing_the_certified_revision_does_not_contain_is_omitted(self):
        landed, tip = self._advance_line_and_certify_the_tip()
        self._git("checkout", "-q", "-b", "side", "main")
        (self.repo / "side.txt").write_text("s\n", "utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "side work never merged")
        side = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("checkout", "-q", "main")
        ldg = LANDING(2, ticket="t-side", revision=side)
        ldg["line"] = "develop-buffer"
        ldg["repos"] = [{"repo": "sandbar", "revision": side}]
        dc.append_rows([ldg], self.ledger_dir / "sandbar.jsonl")
        import unittest.mock as mock
        with mock.patch.dict("os.environ", self._env, clear=False):
            row = dp.promote_buffer("sandbar", "develop-buffer", signer="host",
                                    note="t", repo_paths={"sandbar": self.repo})
        # the side landing is NOT inside the certified revision: this promotion
        # does not deliver it, and the row must not claim it
        self.assertEqual(row["tickets"], ["t-fix"])
        self.assertEqual(self._git("rev-parse", "refs/heads/main"
                                   ).stdout.strip(), tip)

    def test_builder_refuses_a_carried_ticket_the_seam_rejects(self):
        """The builder re-checks every carried ticket; the caller's list is
        never trusted, and the default (no seam) keeps the v1 equality rule."""
        rows = [dict(LANDING(1, ticket="t1", revision="rev1"), seq=1),
                dict(CERT(1, revision="rev2", run="run-a"), seq=2)]
        common = dict(delivery_rows=rows, is_green=lambda rid: True,
                      signer="host",
                      main_before=[{"repo": "r", "revision": "rev1"}],
                      main_after=[{"repo": "r", "revision": "rev2"}])
        # no seam: the v1 equality rule refuses (the landing is not the cert's rev)
        with self.assertRaises(dp.PromotionRefused) as ctx:
            dp.build_promotion("cert-001", "default", ["t1"], **common)
        self.assertIn("tickets_not_covered:t1", str(ctx.exception))
        # seam says "not contained": still refused
        with self.assertRaises(dp.PromotionRefused) as ctx:
            dp.build_promotion("cert-001", "default", ["t1"],
                               tickets_contained_fn=lambda rev, repo: False,
                               **common)
        self.assertIn("tickets_not_covered:t1", str(ctx.exception))
        # seam says "contained": accepted
        row = dp.build_promotion("cert-001", "default", ["t1"],
                                 tickets_contained_fn=lambda rev, repo: True,
                                 **common)
        self.assertEqual(row["tickets"], ["t1"])

    def test_red_cert_refuses_before_any_ref_moves(self):
        self._seed_ledger("red")
        main_before = self._git("rev-parse", "refs/heads/main").stdout.strip()
        import unittest.mock as mock
        with mock.patch.dict("os.environ", self._env, clear=False):
            with self.assertRaises(dp.PromotionRefused) as ctx:
                dp.promote_buffer("sandbar", "develop-buffer", signer="host",
                                  repo_paths={"sandbar": self.repo})
        self.assertIn("no_green_certification", str(ctx.exception))
        # nothing moved, nothing recorded
        self.assertEqual(
            self._git("rev-parse", "refs/heads/main").stdout.strip(),
            main_before)
        rows, _ = dc.read_rows(self.ledger_dir / "sandbar.jsonl")
        self.assertFalse([r for r in rows if r.get("kind") == dc.KIND_PROMOTION])


if __name__ == "__main__":
    unittest.main()
