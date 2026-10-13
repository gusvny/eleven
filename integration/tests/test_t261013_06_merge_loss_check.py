#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261013-06 unit battery: the merge-loss checker's behaviour (developer stage).

The ticket carries main's steward batch onto the frozen develop line. The
conflict resolution is the one place where content can be lost silently, so the
checker `integration/tools/merge_loss_check.py` has to answer two questions
mechanically: which resolution is lossless per file, and does a settled result
still carry both sides' lines.

These cases pin the answers on a real git fixture (a temp repository with real
branches, real conflicts and real revisions), offline and in seconds. The last
case is the review's condition 2: a line whose only difference is a trailing
delimiter (`narrowed=_narrowed,` against `narrowed=_narrowed)`) must be reported
as `delimiter-only` and must not turn a verbatim resolution into a combine.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "integration" / "tools" / "merge_loss_check.py"

VERBATIM = "f_verbatim.txt"
DELIM = "f_delim.txt"
COMBINE = "f_combine.txt"
MARKER = "f_marker.txt"
ONESIDED = "f_onesided.txt"
SYMBOLS = "f_symbols.txt"
SYMBOL_RE = '"([a-z0-9-]+)"'
FILE_ONLY = "f_merge_only.txt"


def git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-c", "user.name=t261013-06", "-c", "user.email=t261013-06@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"] + list(args),
        cwd=str(repo), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError("git %s failed: %s%s" % (" ".join(args), proc.stdout, proc.stderr))
    return proc


def write(repo, name, lines):
    path = Path(repo) / name
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def commit(repo, message, *names):
    git(repo, "add", "--", *names)
    git(repo, "commit", "-m", message)


class Fixture:
    """A real repository with the four shapes the checker must tell apart."""

    def __init__(self, repo):
        self.repo = repo
        write(repo, VERBATIM, ["a"])
        write(repo, DELIM, ["call()"])
        write(repo, COMBINE, ["x"])
        write(repo, SYMBOLS, ['("x",'])
        commit(repo, "base", VERBATIM, DELIM, COMBINE, SYMBOLS)
        self.base = git(repo, "rev-parse", "HEAD").stdout.strip()

        git(repo, "checkout", "-q", "-b", "line")
        write(repo, VERBATIM, ["a", "line-only"])
        # The real shape of integration/run_scenarios.py: the line carries one
        # more line than theirs, AND the two sides differ by a trailing
        # delimiter on another line.
        write(repo, DELIM, ["call()", "narrowed=_narrowed,", "line-extra"])
        write(repo, COMBINE, ["x", "line-only"])
        # The registry shape: each side registers a name the other lacks.
        write(repo, SYMBOLS, ['("x",', '("alpha-1",'])
        commit(repo, "line side", VERBATIM, DELIM, COMBINE, SYMBOLS)
        self.line = git(repo, "rev-parse", "HEAD").stdout.strip()

        git(repo, "checkout", "-q", "-b", "lane", self.base)
        # Theirs already carries the line's verbatim addition, and one more line.
        write(repo, VERBATIM, ["a", "line-only", "lane-only"])
        # The same line, one delimiter apart (the review's condition 2 shape).
        write(repo, DELIM, ["call()", "narrowed=_narrowed)"])
        write(repo, COMBINE, ["x", "lane-only"])
        write(repo, SYMBOLS, ['("x",', '("beta-2",'])
        # A file only the lane side adds: no resolution decision, so it must not
        # enter the conflict set (the real lane's own new files are this shape).
        write(repo, ONESIDED, ["only the lane has this file"])
        commit(repo, "lane side", VERBATIM, DELIM, COMBINE, SYMBOLS, ONESIDED)
        self.lane = git(repo, "rev-parse", "HEAD").stdout.strip()

        git(repo, "checkout", "-q", "-b", "good", self.base)
        write(repo, VERBATIM, ["a", "line-only", "lane-only"])
        write(repo, DELIM, ["call()", "narrowed=_narrowed)"])
        write(repo, COMBINE, ["x", "line-only", "lane-only"])
        write(repo, SYMBOLS, ['("x",', '("alpha-1",', '("beta-2",'])
        commit(repo, "resolution that keeps both sides", VERBATIM, DELIM, COMBINE, SYMBOLS)
        self.good = git(repo, "rev-parse", "HEAD").stdout.strip()

        git(repo, "checkout", "-q", "-b", "bad", self.base)
        write(repo, VERBATIM, ["a", "lane-only"])
        write(repo, COMBINE, ["x", "lane-only"])
        write(repo, SYMBOLS, ['("x",', '("beta-2",'])
        commit(repo, "resolution that drops the line's lines", VERBATIM, COMBINE, SYMBOLS)
        self.bad = git(repo, "rev-parse", "HEAD").stdout.strip()

        git(repo, "checkout", "-q", "-b", "markers", self.base)
        write(repo, MARKER, ["<<<<<<< .our", "ours", "=======", "theirs", ">>>>>>> .their"])
        commit(repo, "committed conflict markers", MARKER)
        self.markers = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "checkout", "-q", "line")


def run_checker(repo, *args):
    proc = subprocess.run([sys.executable, str(CHECKER), "--repo", str(repo)] + list(args),
                          capture_output=True, text=True, cwd=str(repo))
    payload = None
    if "--json" in args and proc.stdout.strip().startswith("{"):
        payload = json.loads(proc.stdout)
    return proc.returncode, proc.stdout, proc.stderr, payload


class MergeLossCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="t261013-06-")
        repo = Path(cls._tmp.name) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        cls.fx = Fixture(repo)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def classify(self, *extra):
        rc, out, err, payload = run_checker(self.fx.repo, "--classify", "--json",
                                            "--ours", "line", "--theirs", "lane", *extra)
        self.assertEqual(rc, 0, "classify must not fail: %s%s" % (out, err))
        self.assertIsNotNone(payload, "classify --json must print JSON: %s" % out)
        return {row["file"]: row for row in payload["files"]}

    def test_classify_names_the_lossless_resolution_per_file(self):
        rows = self.classify()
        self.assertEqual(rows[VERBATIM]["lossless_resolution"], "theirs-verbatim")
        self.assertEqual(rows[COMBINE]["lossless_resolution"], "combine")

    def test_conflict_set_is_marked_as_the_forecast_without_a_scene(self):
        rc, out, err, payload = run_checker(self.fx.repo, "--classify", "--json",
                                            "--ours", "line", "--theirs", "lane")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["conflict_source"], "forecast")

    def test_conflict_set_comes_from_the_live_merge_when_one_exists(self):
        """Arbitration finding B: the index is authoritative once a scene exists.

        On the carrier the forecast named 15 files while the real merge left 11
        unmerged and auto-merged 4, so resolving from the forecast alone would
        chase files that are not conflicts and skip files that are.
        """
        repo = Path(self._tmp.name) / "live"
        repo.mkdir(exist_ok=True)
        git(repo, "init", "-q")
        write(repo, FILE_ONLY, ["base"])
        git(repo, "add", "--", FILE_ONLY)
        git(repo, "commit", "-m", "base")
        git(repo, "branch", "-m", "main")
        git(repo, "checkout", "-q", "-b", "line")
        write(repo, FILE_ONLY, ["base", "line"])
        git(repo, "commit", "-am", "line side")
        git(repo, "checkout", "-q", "-b", "lane", "main")
        write(repo, FILE_ONLY, ["base", "lane"])
        git(repo, "commit", "-am", "lane side")
        merged = git(repo, "merge", "--no-edit", "line", check=False)
        self.assertNotEqual(merged.returncode, 0, "the fixture must leave a conflict")
        self.assertEqual(git(repo, "ls-files", "-u").stdout.count(FILE_ONLY), 3,
                         "the fixture must leave three unmerged stages")
        rc, out, err, payload = run_checker(repo, "--classify", "--json",
                                            "--ours", "lane", "--theirs", "line")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["conflict_source"], "live-merge")
        self.assertEqual([row["file"] for row in payload["files"]], [FILE_ONLY])

    def test_one_sided_change_is_not_a_conflict(self):
        """Only files both sides touched need a resolution decision.

        Measured on the real lane: three one-sided files (this ticket's own new
        files) inflated the list to 18 against 15 real conflicts.
        """
        raw = git(self.fx.repo, "merge-tree", self.fx.base, "line", "lane").stdout
        one_sided = [ln for ln in raw.splitlines()
                     if ln.strip().endswith((" in local", " in remote"))]
        self.assertTrue(one_sided, "the fixture must produce a one-sided block")
        self.assertIn(ONESIDED, raw)
        self.assertNotIn(ONESIDED, self.classify())

    def test_delimiter_only_line_is_reported_and_never_drives_the_class(self):
        """Review condition 2: a trailing delimiter must not force a combine.

        The real file is `integration/run_scenarios.py`: the line carries one
        line theirs lacks, and one line differs from theirs by a trailing
        delimiter only. The lossless resolution stays `ours-verbatim`, and the
        delimiter shape is named instead of counted as a loss.
        """
        rows = self.classify()
        row = rows[DELIM]
        self.assertEqual(row["lossless_resolution"], "ours-verbatim")
        missing = row["theirs_missing_from_ours"]
        self.assertEqual(len(missing), 1, "the delimiter-only line must still be reported")
        self.assertEqual(missing[0]["kind"], "delimiter-only")
        self.assertIn("narrowed=_narrowed", missing[0]["text"])
        # Both missing lists report the delimiter-only line; only the strict
        # "missing" rows count as lost work, and here that is `line-extra`.
        strict = [m["text"] for m in row["ours_missing_from_theirs"] if m["kind"] == "missing"]
        self.assertEqual(strict, ["line-extra"])
        delimiter_rows = [m["kind"] for m in row["ours_missing_from_theirs"]
                          if m["text"].startswith("narrowed")]
        self.assertEqual(delimiter_rows, ["delimiter-only"])

    def test_loss_mode_passes_a_result_that_keeps_both_sides(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane",
            "--result", "good", "--allow-unmerged-result", "--files", VERBATIM, COMBINE)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["failed_files"], [])
        self.assertTrue(payload["ok"])

    def _declaration(self, name, entries):
        path = Path(self._tmp.name) / name
        path.write_text(json.dumps(entries), encoding="utf-8")
        return str(path)

    def test_declared_deviations_turn_a_known_loss_green(self):
        """Arbitration pass 4, item 2: a hand-authored divergence is declarable.

        Every entry carries its own reason; the check goes green only because
        each undeclared row is gone.
        """
        declared = self._declaration("declared-ok.json", [
            {"file": VERBATIM, "why": "the line's variant was superseded by the lane's",
             "text": "line-only"},
            {"file": SYMBOLS, "why": "the symbol moved into the lane's registry entry",
             "symbol": "alpha-1"},
        ])
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "bad",
            "--allow-unmerged-result", "--files", VERBATIM,
            "--symbol-file", SYMBOLS, "--symbol-regex", SYMBOL_RE, "--declared", declared)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(payload["ok"])
        # A text declaration accepts every occurrence of that text in that file:
        # `line-only` reaches the result from both sides, so two rows are
        # accepted there, plus the one declared symbol.
        self.assertEqual(payload["declared_count"], 3)
        self.assertEqual(payload["stale_declarations"], [])
        why = [item["declared_why"] for item in payload["files"][0]["declared"]]
        self.assertIn("superseded", why[0])

    def test_undeclared_rows_stay_red(self):
        declared = self._declaration("declared-partial.json", [
            {"file": SYMBOLS, "why": "only the symbol is declared here", "symbol": "alpha-1"},
        ])
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "bad",
            "--allow-unmerged-result", "--files", VERBATIM,
            "--symbol-file", SYMBOLS, "--symbol-regex", SYMBOL_RE, "--declared", declared)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(VERBATIM, payload["failed_files"])

    def test_stale_declaration_fails(self):
        """A declaration that matches nothing must not sit there accepting nothing."""
        declared = self._declaration("declared-stale.json", [
            {"file": VERBATIM, "why": "no such line exists in this result",
             "text": "a line that is not in either side"},
        ])
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "good",
            "--allow-unmerged-result", "--files", VERBATIM, "--declared", declared)
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(len(payload["stale_declarations"]), 1)
        self.assertIn("not in either side", payload["stale_declarations"][0]["text"])

    def test_declaration_without_a_reason_is_refused_by_name(self):
        declared = self._declaration("declared-no-why.json", [
            {"file": VERBATIM, "text": "line-only"},
        ])
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "bad",
            "--allow-unmerged-result", "--files", VERBATIM, "--declared", declared)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("declared_entry_missing_reason", payload["error"])

    def test_declaration_entry_needs_exactly_one_of_text_or_symbol(self):
        declared = self._declaration("declared-both.json", [
            {"file": VERBATIM, "why": "both fields", "text": "line-only", "symbol": "x"},
        ])
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "bad",
            "--allow-unmerged-result", "--files", VERBATIM, "--declared", declared)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("declared_entry_needs_exactly_one_of_text_symbol", payload["error"])

    def test_unreadable_declaration_is_refused(self):
        path = Path(self._tmp.name) / "declared-broken.json"
        path.write_text("{not json", encoding="utf-8")
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "bad",
            "--allow-unmerged-result", "--files", VERBATIM, "--declared", str(path))
        self.assertEqual(rc, 2, out + err)
        self.assertIn("declared_unreadable", payload["error"])

    def test_loss_mode_fails_a_result_that_drops_the_lines_additions(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane",
            "--result", "bad", "--allow-unmerged-result", "--files", VERBATIM, COMBINE)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(VERBATIM, payload["failed_files"])
        dropped = [row["text"] for row in payload["files"][0]["unexplained"]]
        self.assertIn("line-only", dropped)

    def test_loss_mode_refuses_an_unsettled_result_by_name(self):
        """Arbitration finding 2: an unmerged lane tip must not read as a loss list.

        Before the merge exists, `--result HEAD` (the plain lane tip) lacks both
        sides, and every other side's line then reads as lost. The check refuses
        by name instead, so a missing prerequisite is never mistaken for a
        deliverable gap.
        """
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "bad")
        self.assertEqual(rc, 2, out + err)
        self.assertFalse(payload["ok"])
        self.assertIn("result_not_settled", payload["error"])

    def test_loss_mode_accepts_a_real_settled_merge(self):
        """The settled shape: a merge commit whose parents are the two sides."""
        repo = self.fx.repo
        git(repo, "checkout", "-q", "-b", "settled", "line")
        merged = git(repo, "merge", "--no-edit", "-X", "ours", "lane", check=False)
        if merged.returncode != 0:          # a conflicted merge still needs its commit
            git(repo, "add", "-A")
            git(repo, "commit", "--no-edit", "-m", "resolution merge")
        parents = git(repo, "log", "-1", "--pretty=%P").stdout.split()
        self.assertEqual(len(parents), 2, "the fixture must build a real merge commit")
        rc, out, err, payload = run_checker(
            repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "settled",
            "--files", COMBINE)
        self.assertIn(rc, (0, 1), out + err)
        self.assertTrue(payload["settled"])
        git(repo, "checkout", "-q", "line")

    def test_classify_emits_a_resolution_command_per_file(self):
        """The command applies a verbatim resolution without writing the index."""
        rows = self.classify()
        self.assertIn("git show", rows[VERBATIM]["resolution_command"])
        self.assertIn(VERBATIM, rows[VERBATIM]["resolution_command"])
        self.assertEqual(rows[COMBINE]["resolution_command"], "")

    def test_symbol_check_passes_when_both_sides_names_survive(self):
        """The registry case (arbitration): a one-sided resolution drops names."""
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane",
            "--result", "good", "--allow-unmerged-result", "--files", SYMBOLS,
            "--symbol-file", SYMBOLS, "--symbol-regex", SYMBOL_RE)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(payload["symbol_check"]["missing"], [])
        self.assertEqual(payload["symbol_check"]["ours"], 2)
        self.assertEqual(payload["symbol_check"]["theirs"], 2)
        self.assertEqual(payload["symbol_check"]["result"], 3)

    def test_symbol_check_fails_when_a_side_s_name_is_dropped(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane",
            "--result", "bad", "--allow-unmerged-result", "--files", SYMBOLS,
            "--symbol-file", SYMBOLS, "--symbol-regex", SYMBOL_RE)
        self.assertEqual(rc, 1, out + err)
        missing = {row["symbol"]: row["on"] for row in payload["symbol_check"]["missing"]}
        self.assertIn("alpha-1", missing)
        self.assertEqual(missing["alpha-1"], ["ours"])

    def test_symbol_check_flags_must_come_together(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "good",
            "--allow-unmerged-result", "--files", SYMBOLS, "--symbol-file", SYMBOLS)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("symbol_check_incomplete", payload["error"])

    def test_symbol_regex_is_validated(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane", "--result", "good",
            "--allow-unmerged-result", "--files", SYMBOLS,
            "--symbol-file", SYMBOLS, "--symbol-regex", "([a-z")
        self.assertEqual(rc, 2, out + err)
        self.assertIn("symbol_regex_invalid", payload["error"])

    def test_loss_mode_fails_on_committed_markers(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "lane",
            "--result", "markers", "--allow-unmerged-result", "--files", MARKER)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(MARKER, payload["failed_files"])
        self.assertEqual(len(payload["files"][0]["markers"]), 3)

    def test_unknown_revision_fails_closed(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "does-not-exist", "--theirs", "lane")
        self.assertEqual(rc, 2, out + err)
        self.assertFalse(payload["ok"])
        self.assertIn("merge-base", payload["error"])

    def test_clean_merge_is_not_a_pass(self):
        rc, out, err, payload = run_checker(
            self.fx.repo, "--json", "--ours", "line", "--theirs", "line")
        self.assertEqual(rc, 2, out + err)
        self.assertIn("empty set is never a pass", payload["error"])

    def test_non_utf8_bytes_do_not_crash_the_checker(self):
        repo = Path(self._tmp.name) / "latin1"
        repo.mkdir(exist_ok=True)
        git(repo, "init", "-q")
        (repo / "f.txt").write_bytes(b"base\n")
        commit(repo, "base", "f.txt")
        git(repo, "checkout", "-q", "-b", "line")
        (repo / "f.txt").write_bytes(b"base\ncaf\xe9 line-only\n")
        commit(repo, "line", "f.txt")
        git(repo, "checkout", "-q", "-b", "lane", "main")
        (repo / "f.txt").write_bytes(b"base\ncaf\xe9 lane-only\n")
        commit(repo, "lane", "f.txt")
        rc, out, err, payload = run_checker(repo, "--json", "--ours", "line", "--theirs", "lane",
                                            "--result", "lane", "--allow-unmerged-result")
        self.assertIn(rc, (0, 1), out + err)
        self.assertNotIn("Traceback", err)
        self.assertIsNotNone(payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
