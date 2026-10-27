#!/usr/bin/env python3
"""t261027-16 — the certification receipt's size discipline.

The host report: the Certification tab died because the adapter emitted the
WHOLE run ledger on per_line.<line>.input (every header, now carrying the
t261026-15 failed_detail evidence tails) while the panel spawns with a 1 MB
maxBuffer — the size death read back as "not valid JSON".

Offline unit tests over a generated fixture ledger (no real store, no
Temporal, no docker). Contract:
  - bounded_runs keeps the certification range (every cited run) plus the
    newest RUNS_WINDOW_CAP headers, and states the window (never a silent
    truncate);
  - each kept run is projected to header-level counts/verdict/revision —
    failed_detail / fail_receipts / name lists NEVER reach the face;
  - the receipt, serialized, stays under RECEIPT_MAX_BYTES with a
    real-shape (3.6k+ rows) fixture, and the green judgment set is identical
    to the unbounded read;
  - a deliberately oversized receipt refuses BY NAME
    ("receipt too large: N bytes, window ...");
  - malformed headers (cases as string / null / garbage list) yield named
    absences, never a crash, never an invented verdict.
"""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent / "src" / "host" / "certification-adapter.py"

spec = importlib.util.spec_from_file_location("certification_adapter", ADAPTER)
ca = importlib.util.module_from_spec(spec)
sys.modules["certification_adapter"] = ca
spec.loader.exec_module(ca)


def header(idx, started=None, verdict="green", cases="DEFAULT", fat=0):
    """One run header in the ledger's own shape; `fat` appends a fat
    failed_detail evidence tail (the t261026-15 inflation)."""
    if cases == "DEFAULT":
        cases = {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0}
    h = {
        "v": "run-ledger-v1",
        "id": "run-%06d" % idx,
        "repos": [{"repo": "sandbar", "revision": "r%08d" % idx}],
        "suite": "full",
        "source": "lane:line-round",
        "started_at": started if started is not None else idx,
        "cases": cases,
        "verdict": verdict,
    }
    if fat:
        h["failed_detail"] = {"case-x": {"evidence": "E" * fat}}
        h["fail_receipts"] = {"case-x": {"status": "not-checked", "evidence": "R" * fat}}
    return h


class BoundedRunsTest(unittest.TestCase):
    def test_window_keeps_recent_plus_cited_and_states_it(self):
        headers = [header(i, started=i) for i in range(100)]
        runs, window = ca.bounded_runs(headers, {"run-000003"})
        ids = {r["id"] for r in runs}
        self.assertEqual(len(runs), window["shown"])
        self.assertEqual(window["total"], 100)
        self.assertEqual(window["older"], 100 - len(runs))
        self.assertEqual(window["cap"], ca.RUNS_WINDOW_CAP)
        # the certification range survives: a cited run older than the window
        # is still on the face
        self.assertIn("run-000003", ids)
        # the newest headers are on the face
        self.assertIn("run-000099", ids)
        self.assertLessEqual(len(runs), ca.RUNS_WINDOW_CAP + 1)

    def test_projection_carries_counts_only(self):
        headers = [header(1, fat=50_000)]
        runs, _ = ca.bounded_runs(headers, set())
        r = runs[0]
        self.assertEqual(r["cases"], {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0})
        blob = json.dumps(r)
        self.assertNotIn("failed_detail", blob)
        self.assertNotIn("fail_receipts", blob)
        self.assertIn("verdict", blob)
        self.assertIn("repos", blob)  # the revision set

    def test_malformed_cases_yields_named_absence(self):
        for bad in ("garbage", None, [1, "x"], 42):
            with self.subTest(bad=bad):
                runs, _ = ca.bounded_runs([header(1, cases=bad)], set())
                c = runs[0]["cases"]
                self.assertEqual(c["ran"], 0)
                self.assertIn("absent", c)

    def test_non_numeric_started_at_sorts_last_never_crashes(self):
        h_bad = header(1)
        h_bad["started_at"] = "not-a-number"
        runs, _ = ca.bounded_runs([header(2, started=2), h_bad], set())
        self.assertEqual(len(runs), 2)


class ReceiptSizeTest(unittest.TestCase):
    """End-to-end main() over a temp project: bounded receipt under the cap,
    same green judgment; oversized receipts refuse by name."""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["SANDBAR_PROJECTS_ROOT"] = str(self.dir)
        self.addCleanup(os.environ.pop, "SANDBAR_PROJECTS_ROOT", None)
        self.addCleanup(self.tmp.cleanup)
        # the project's own files the adapter reads
        pdir = self.dir / "sandbar" / "data"
        (pdir / "develop").mkdir(parents=True)
        (self.dir / "sandbar" / "ledger").mkdir(parents=True)
        (pdir / "develop" / "lines.json").write_text(json.dumps([{
            "line_id": "develop-buffer", "scope": "t", "owner": "host",
            "repositories": [{"name": "sandbar", "branch": "develop"}],
            "extra_scenarios": [], "version": 1,
        }]), encoding="utf-8")
        # an empty delivery ledger: no certs -> no fail-closed path
        (self.dir / "sandbar" / "ledger" / "delivery.jsonl").write_text("", encoding="utf-8")
        self.ledger = self.dir / "runs.jsonl"

    def _write_ledger(self, headers, fat=0):
        with open(self.ledger, "w", encoding="utf-8") as fh:
            for h in headers:
                fh.write(json.dumps(h) + "\n")
        os.environ["SANDBAR_RUNS_LEDGER"] = str(self.ledger)
        self.addCleanup(os.environ.pop, "SANDBAR_RUNS_LEDGER", None)

    def _run_main(self, cap=None):
        import io
        old_cap = ca.RECEIPT_MAX_BYTES
        if cap is not None:
            ca.RECEIPT_MAX_BYTES = cap
        self.addCleanup(setattr, ca, "RECEIPT_MAX_BYTES", old_cap)
        buf, err = io.StringIO(), io.StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = buf, err
        try:
            code = ca.main(["certification-adapter.py", "sandbar"])
        finally:
            sys.stdout, sys.stderr = old
        return code, buf.getvalue()

    def test_real_shape_ledger_stays_under_cap_with_same_judgment(self):
        # a 3.6k+ row ledger with fat failed_detail tails (the measured shape)
        headers = [header(i, started=i, fat=800 if i % 50 == 0 else 0)
                   for i in range(3600)]
        headers[-1]["verdict"] = "red"
        headers[-1]["cases"] = {"ran": 3, "passed": 1, "failed": 2, "env_failed": 0}
        self._write_ledger(headers)
        code, out = self._run_main()
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertTrue(doc["ok"])
        size = len(out.encode("utf-8"))
        self.assertLess(size, ca.RECEIPT_MAX_BYTES)
        win = doc["runs_window"]
        self.assertEqual(win["total"], 3600)
        self.assertGreater(win["older"], 0)
        runs = doc["per_line"]["develop-buffer"]["input"]["runs"]
        self.assertEqual(len(runs), win["shown"])
        blob = out
        self.assertNotIn("failed_detail", blob)
        # the derived face still reports the same verdict/range: the newest
        # header (red) is in the window and carries its counts
        newest = runs[0]
        self.assertEqual(newest["id"], headers[-1]["id"])
        self.assertEqual(newest["verdict"], "red")
        self.assertEqual(newest["cases"]["failed"], 2)

    def test_oversized_receipt_refuses_by_name(self):
        self._write_ledger([header(i, started=i) for i in range(50)])
        code, out = self._run_main(cap=200)  # deliberately tiny cap
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertFalse(doc["ok"])
        self.assertIn("receipt too large:", doc["reason"])
        self.assertIn("window", doc["reason"])
        self.assertLess(len(out.encode("utf-8")), ca.RECEIPT_MAX_BYTES * 10)

    def test_max_buffer_matches_the_reader_spawn_constant(self):
        reader = (HERE.parent / "src" / "host" / "certification-reader.ts").read_text(encoding="utf-8")
        self.assertIn("SPAWN_MAX_BUFFER = 1_000_000", reader)
        self.assertEqual(ca.RECEIPT_MAX_BYTES, 1_000_000)


if __name__ == "__main__":
    unittest.main()
