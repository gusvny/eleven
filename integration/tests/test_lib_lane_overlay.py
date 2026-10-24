#!/usr/bin/env python3
"""Unit battery for the lane sandbox overlay home (t261021-10).

Covers the ticket's hard requirement BOTH ways on the one predicate
(`overlay_path_is_lawful`): the runner's out-of-tree overlay home passes, and a
hand-written file under `integration/<ticket>/` — next to where the incident
overlay sat — is still refused. Malformed external input (ticket ids, the env
knob) fails closed by name. Pure stdlib; every fixture lives in pytest tmp
dirs, never the real tree.
"""
import os
import sys
import unittest
from pathlib import Path

INTEG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INTEG))

import lib_lane_overlay as lo  # noqa: E402
import lint_tests  # noqa: E402  (import is safe: side effects are tmp-dir only)


def _run_rule(root):
    """Run the L26 rule against an injected walk root; return (errors, warns)."""
    saved_e, saved_w = lint_tests.errors, lint_tests.warns
    lint_tests.errors, lint_tests.warns = [], []
    try:
        lint_tests.lint_lane_overlay_location(root)
        return list(lint_tests.errors), list(lint_tests.warns)
    finally:
        lint_tests.errors, lint_tests.warns = saved_e, saved_w


class TestPredicateBothDirections(unittest.TestCase):
    def test_out_of_tree_overlay_home_is_lawful(self):
        root = Path("/private-tmp/sandbar-lane-overlay/t261021-99")
        self.assertTrue(lo.overlay_path_is_lawful(root / "server" / "engine",
                                                  "/repo"))

    def test_incident_shape_is_refused(self):
        # The exact blocked path class: an overlay dir under the ticket's
        # integration dir, inside the measured tree.
        bad = "/repo/integration/t261021-05/overlay/server/engine/.venv"
        self.assertFalse(lo.overlay_path_is_lawful(bad, "/repo"))

    def test_hand_written_file_next_to_it_is_still_refused(self):
        # The fix opens NOTHING about integration/ generally.
        self.assertFalse(lo.overlay_path_is_lawful(
            "/repo/integration/t261021-05/sc_hand_edit.py", "/repo"))
        self.assertFalse(lo.overlay_path_is_lawful(
            "/repo/integration/t261021-05/overlay-bin/tool", "/repo"))

    def test_repo_root_itself_is_refused_outside_is_lawful(self):
        self.assertFalse(lo.overlay_path_is_lawful("/repo", "/repo"))
        # Outside the tree IS lawful (the positive face of the same predicate).
        self.assertTrue(lo.overlay_path_is_lawful("/elsewhere", "/repo"))

    def test_malformed_paths_fail_closed_false(self):
        for bad in (None, 123, "", "\x00bad"):
            with self.subTest(bad=bad):
                self.assertFalse(lo.overlay_path_is_lawful(bad, "/repo"))

    def test_symlink_escape_is_resolved(self):
        # A symlink planted OUTSIDE the tree pointing INTO it is judged by its
        # target, not its location (realpath on both sides).
        import shutil as _sh
        import tempfile
        base = Path(tempfile.mkdtemp(prefix="lane-overlay-pred-"))
        try:
            repo = base / "repo"
            (repo / "integration").mkdir(parents=True)
            link = base / "outside-link"
            link.symlink_to(repo, target_is_directory=True)
            self.assertFalse(lo.overlay_path_is_lawful(
                link / "integration" / "x", repo))
            # And the reverse: a repo-internal symlink pointing OUT lands
            # lawful (the target is what the gate would measure... nothing).
            out = base / "elsewhere"
            out.mkdir()
            inner = repo / "integration" / "out-link"
            inner.symlink_to(out, target_is_directory=True)
            self.assertTrue(lo.overlay_path_is_lawful(inner / "ov", repo))
        finally:
            _sh.rmtree(base, ignore_errors=True)


class TestOverlayRootFailClosed(unittest.TestCase):
    def _env(self, tmp, **kw):
        e = dict(os.environ)
        e.pop(lo.OVERLAY_ROOT_ENV, None)
        e.pop("SANDBAR_REPO_ROOT", None)
        e["SANDBAR_REPO_ROOT"] = str(tmp / "repo")
        e.update({k: v for k, v in kw.items() if v is not None})
        return e

    def test_default_home_is_system_temp(self):
        home = lo.overlay_root("t261021-99", env={})
        self.assertIn("sandbar-lane-overlay", str(home))
        self.assertTrue(str(home).endswith("t261021-99"))

    def test_malformed_ticket_ids_refused_by_name(self):
        env = {}
        for bad in ("", "../escape", "t261021", "t261021-9", "a/b",
                    "t261021-99/..", None, 123, "t261021-99 ",
                    "t261021-999"):
            with self.subTest(bad=bad):
                with self.assertRaises(lo.OverlayLocationError):
                    lo.overlay_root(bad, env=env)

    def test_env_knob_honoured(self):
        env = {lo.OVERLAY_ROOT_ENV: "/scratch/overlays"}
        self.assertEqual(str(lo.overlay_root("t261021-99", env=env)),
                         "/scratch/overlays/t261021-99")

    def test_env_knob_inside_repo_tree_refused(self):
        root = "/tmp/fake-repo"
        env = {lo.OVERLAY_ROOT_ENV: root + "/integration",
               "SANDBAR_REPO_ROOT": root}
        with self.assertRaises(lo.OverlayLocationError):
            lo.overlay_root("t261021-99", env=env)
        # The knob may not BE the repo root either.
        env[lo.OVERLAY_ROOT_ENV] = root
        with self.assertRaises(lo.OverlayLocationError):
            lo.overlay_root("t261021-99", env=env)


class TestBuildDisposeLifecycle(unittest.TestCase):
    def test_build_then_dispose_all_states(self):
        env = {}
        home = lo.build_overlay("t261021-98", {"server/engine/.venv-marker": "x"},
                                env=env)
        try:
            self.assertTrue((home / "server" / "engine" /
                             ".venv-marker").is_file())
        finally:
            gone = lo.dispose_overlay("t261021-98", env=env)
            self.assertFalse(Path(gone).exists())

    def test_traversal_rel_refused(self):
        env = {}
        with self.assertRaises(lo.OverlayLocationError):
            lo.build_overlay("t261021-97", {"../escaped.txt": "x"}, env=env)
        lo.dispose_overlay("t261021-97", env=env)  # nothing left behind

    def test_dispose_is_tolerant_of_absent_home(self):
        env = {}
        home = lo.dispose_overlay("t261021-96", env=env)
        self.assertFalse(Path(home).exists())


class TestLintRuleL26Mechanism(unittest.TestCase):
    """The static brake bites on the incident shape and stays quiet on a
    clean tree — proven against a tmp fixture, never the real tree."""

    def _tree(self, overlay=False, sibling=False):
        import shutil
        import tempfile
        base = Path(tempfile.mkdtemp(prefix="lane-overlay-l26-"))
        ticket = base / "t261021-05"
        ticket.mkdir()
        if overlay:
            (ticket / "overlay" / "server" / "engine").mkdir(parents=True)
            (ticket / "overlay" / "server" / "engine" / ".venv").symlink_to(
                base)  # shape only; target arbitrary for the walk
        if sibling:
            (ticket / "sc_hand_edit.py").write_text("# hand-written\n",
                                                    encoding="utf-8")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        return base

    def test_clean_tree_is_green(self):
        errs, _ = _run_rule(self._tree(sibling=True))
        self.assertEqual(errs, [])

    def test_overlay_dir_is_named_error(self):
        errs, _ = _run_rule(self._tree(overlay=True, sibling=True))
        self.assertEqual(len(errs), 1)
        self.assertIn("L26", errs[0])
        self.assertIn("t261021-05/overlay", errs[0])
        self.assertIn("overlay_root", errs[0])  # points at the lawful home

    def test_deep_overlay_and_skip_dirs(self):
        import shutil
        import tempfile
        base = Path(tempfile.mkdtemp(prefix="lane-overlay-l26-"))
        try:
            deep = base / "t1" / "node_modules" / "overlay"
            deep.mkdir(parents=True)
            errs, _ = _run_rule(base)
            self.assertEqual(errs, [])  # skip-dir'd walks are not judged
            plain = base / "t2" / "overlay"
            plain.mkdir(parents=True)
            errs, _ = _run_rule(base)
            self.assertEqual(len(errs), 1)
            self.assertIn("t2/overlay", errs[0])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_rule_is_registered_for_the_selector(self):
        self.assertIn("L26", lint_tests.RULES)


if __name__ == "__main__":
    unittest.main()
