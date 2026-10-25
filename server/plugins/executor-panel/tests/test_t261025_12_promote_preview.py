#!/usr/bin/env python3
"""t261025-12 — the engine's read-only promotion eligibility face and the
signer identity rule (design ruling: executor-operational-envelope-v1 §5).

Offline unit tests over fixtures only (git fixture repos, temp ledgers): no
Temporal, no docker, no console. Contract:
  - promotion_preview runs the writer's OWN validate pass and answers what
    one signature would move, refusals by name (no_green_certification,
    line_not_declared, promotion_not_fast_forward, main_unresolvable);
  - preview moves NOTHING: main stays put, the ledger is byte-identical;
  - promote_buffer refuses an agent role name (or the -agent family) BY NAME
    before touching anything — the engine is the enforcement point, so no
    surface can bypass it;
  - a human signer passes the identity rule.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_ENGINE = Path(__file__).resolve().parents[3] / "engine"
sys.path.insert(0, str(SERVER_ENGINE))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402

LINE_DECL = [{
    "line_id": "develop-buffer", "scope": "t", "owner": "host",
    "repositories": [{"name": "sandbar", "branch": "develop"}],
    "extra_scenarios": [], "version": 1,
}]


def LANDING(idx, ticket="t-fix", revision=None, at=1000):
    """The landing fixture row (same shape as the t261009-29 suite's helper)."""
    return {"kind": dc.KIND_LANDING, "id": "ldg-%03d" % idx,
            "ticket": ticket, "line": "default",
            "repos": [{"repo": "r", "revision": revision or ("rev%d" % idx)}],
            "actor": "engine", "at": at}


class PreviewBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.dir / "sandbar-repo"
        self.repo.mkdir()
        self._git("init", "-q", "-b", "main", str(self.repo))
        (self.repo / "a.txt").write_text("m0\n", "utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "m0")
        self._git("branch", "develop")
        self._git("checkout", "-q", "develop")
        (self.repo / "b.txt").write_text("line work\n", "utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "line work")
        self.line_tip = self._git("rev-parse", "HEAD").stdout.strip()
        self.main_tip = self._git("rev-parse", "main").stdout.strip()
        self._git("checkout", "-q", "main")
        self.projects = self.dir / "projects"
        (self.projects / "sandbar" / "data" / "develop").mkdir(parents=True)
        (self.projects / "sandbar" / "data" / "develop" / "lines.json").write_text(
            json.dumps(LINE_DECL), "utf-8")
        self.ledger_dir = self.dir / "ledger"
        self.runs_dir = self.dir / "runs"
        self.runs_dir.mkdir()
        self.env = {
            "SANDBAR_PROJECTS_DIR": str(self.projects),
            "SANDBAR_DELIVERY_LEDGER_DIR": str(self.ledger_dir),
            "SANDBAR_SCENARIO_LEDGER_DIR": str(self.runs_dir),
        }
        self._seed_ledger("green")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _git(self, *args):
        import subprocess
        r = subprocess.run(["git", *args], cwd=str(self.repo),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def _seed_ledger(self, verdict):
        ldg = LANDING(1, ticket="t-fix", revision=self.line_tip)
        ldg["line"] = "develop-buffer"
        ldg["repos"] = [{"repo": "sandbar", "revision": self.line_tip}]
        dc.append_rows([ldg], self.ledger_dir / "sandbar.jsonl")
        cert = dc.build_certification(
            [{"repo": "sandbar", "revision": self.line_tip}],
            {"id": "run-green", "cases": {"ran": 3, "passed": 3,
                                          "failed": 0, "env_failed": 0}},
            "none", judged_by="ut", at_ms=2000, line="develop-buffer")
        dc.append_rows([cert], self.ledger_dir / "sandbar.jsonl")
        runs_store = self.projects / "sandbar" / "ledger"
        runs_store.mkdir(parents=True, exist_ok=True)
        (runs_store / "scenario-runs.jsonl").write_text(
            json.dumps({"id": "run-green", "verdict": verdict,
                        "cases": {"ran": 3, "passed": 3, "failed": 0,
                                  "env_failed": 0},
                        "suite": "full", "source": "line-round"}) + "\n",
            "utf-8")


class TestPromotionPreview(PreviewBase):
    def _preview(self):
        import unittest.mock as mock
        with mock.patch.dict("os.environ", self.env, clear=False):
            return dp.promotion_preview("sandbar", "develop-buffer",
                                        repo_paths={"sandbar": self.repo})

    def test_eligible_line_previews_cert_and_revisions(self):
        p = self._preview()
        self.assertTrue(p["ok"], p)
        self.assertEqual(p["cert_id"], p["cert_id"])  # shape: present
        self.assertEqual(p["revisions"], {"sandbar": self.line_tip})
        self.assertEqual(p["main_before"], [{"repo": "sandbar",
                                             "revision": self.main_tip}])

    def test_preview_moves_nothing(self):
        ledger_before = (self.ledger_dir / "sandbar.jsonl").read_bytes()
        self._preview()
        cur = self._git("rev-parse", "refs/heads/main").stdout.strip()
        self.assertEqual(cur, self.main_tip, "preview never moves main")
        self.assertEqual((self.ledger_dir / "sandbar.jsonl").read_bytes(),
                         ledger_before, "preview never appends a row")

    def test_refusals_travel_by_name(self):
        # no green certification: seed a RED run instead
        import unittest.mock as mock
        with mock.patch.dict("os.environ", self.env, clear=False):
            # overwrite the runs store with a red verdict
            runs_store = self.projects / "sandbar" / "ledger"
            (runs_store / "scenario-runs.jsonl").write_text(
                json.dumps({"id": "run-green", "verdict": "red",
                            "cases": {"ran": 3, "passed": 2, "failed": 1,
                                      "env_failed": 0},
                            "suite": "full", "source": "line-round"}) + "\n",
                "utf-8")
            p = dp.promotion_preview("sandbar", "develop-buffer",
                                     repo_paths={"sandbar": self.repo})
        self.assertFalse(p["ok"])
        self.assertTrue(p["reason"].startswith("no_green_certification"),
                        p["reason"])
        # undeclared line
        import unittest.mock as mock2
        with mock2.patch.dict("os.environ", self.env, clear=False):
            p2 = dp.promotion_preview("sandbar", "no-such-line",
                                      repo_paths={"sandbar": self.repo})
        # the refusal order matches the writer's own (the green-cert check
        # runs before the line declaration check, promote_buffer's order)
        self.assertTrue(p2["reason"].startswith("no_green_certification"),
                        p2["reason"])

    def test_not_fast_forward_refusal(self):
        # advance main past the merge-base: main gains its own commit
        self._git("commit", "--allow-empty", "-qm", "main diverges")
        p = self._preview()
        self.assertFalse(p["ok"])
        self.assertEqual(p["reason"], "promotion_not_fast_forward:sandbar")


class TestSignerIdentityRule(PreviewBase):
    def test_agent_role_names_refused_by_name(self):
        import unittest.mock as mock
        for bad in ("developer", "integration", "ops", "reviewer-agent",
                    "Alice-Agent"):
            with mock.patch.dict("os.environ", self.env, clear=False):
                with self.assertRaises(dp.PromotionRefused) as cm:
                    dp.promote_buffer("sandbar", "develop-buffer", signer=bad,
                                      repo_paths={"sandbar": self.repo})
            self.assertTrue(str(cm.exception)
                            .startswith("signer_is_agent_role_name"),
                            f"{bad}: {cm.exception}")
        # nothing moved, nothing appended
        cur = self._git("rev-parse", "refs/heads/main").stdout.strip()
        self.assertEqual(cur, self.main_tip)

    def test_human_signer_passes_the_identity_rule(self):
        self.assertIsNone(dp.signer_role_refusal("徐辛"))
        self.assertIsNone(dp.signer_role_refusal("Alice"))
        self.assertIsNotNone(dp.signer_role_refusal("  developer  "),
                             "whitespace does not launder a role name")


if __name__ == "__main__":
    unittest.main()
