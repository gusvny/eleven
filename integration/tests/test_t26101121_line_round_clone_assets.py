#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-21 L1 unit battery: the line round's clone carries the
gitignored assets its probes need (developer stage).

The incident: the 261011-1649 round's clone carried no
server/engine/.venv and no node_modules (a git clone only carries
committed files), so every cwd-relative probe (`PY=server/engine/.venv/
bin/python; [ -x "$PY" ] || PY=python3`, lib_pw_deps.mjs's LOCAL_PW
chain) silently fell back inside the clone and 220 lines went red on
environment, not product. The fix: prepare_tree() materialises the
declared CLONE_ASSETS into each clone as one symlink per entry pointing
at the source checkout's copy; an entry genuinely absent from the source
is skipped with a named stderr line (honest absence, never faked).

Offline seconds, zero docker/Temporal/port/console, never touches 3099.
Direct unit calls into prepare_tree/materialise_assets over a real git
fixture repo whose clone shape is the incident's clone (real .git dir,
gitignored asset trees).
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "integration"

import sys  # noqa: E402
sys.path.insert(0, str(INTEG))
import line_round_runner as runner  # noqa: E402


def make_source_repo(tmp, with_assets):
    """A tiny git repo whose HEAD carries integration/run_scenarios.py
    (the primary-tree detection's minimum). When with_assets, it also
    carries UNCOMMITTED gitignored asset trees — exactly what a real
    checkout has and a clone of it cannot."""
    src = Path(tmp) / "source-sandbar"
    (src / "integration").mkdir(parents=True)
    (src / "integration" / "run_scenarios.py").write_text("# stub tree\n")
    (src / ".gitignore").write_text(
        "server/engine/.venv/\nserver/engine/bin/\nnode_modules/\n"
        "server/ui-check/node_modules/\n")
    assets = [
        "server/engine/.venv/bin/python",
        "server/engine/bin/temporal",
        "node_modules/.package-lock.json",
        "server/ui-check/node_modules/playwright-core/index.mjs",
    ]
    if with_assets:
        for rel in assets:
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/bin/sh\n# fixture asset\n")
            if rel.endswith(("python", "temporal")):
                p.chmod(0o755)  # the registry probe requires the exec bit
    for argv in (
            ["git", "init", "-q", str(src)],
            ["git", "-C", str(src), "config", "user.email", "t@t"],
            ["git", "-C", str(src), "config", "user.name", "t"],
            ["git", "-C", str(src), "add", "-A"],
            ["git", "-C", str(src), "commit", "-qm", "fixture"],
    ):
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("git fixture failed: %s: %s"
                               % (argv, proc.stderr))
    sha = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    return src, sha


class CloneAssetsLeg(unittest.TestCase):
    """prepare_tree must leave each clone with the declared assets as
    symlinks resolving to the source checkout's copy."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="t26101121-ut-")
        self.tmp = Path(self._tmp.name)
        self.src, self.sha = make_source_repo(self.tmp, with_assets=True)
        self.run_root = self.tmp / "run"
        self.run_root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def env(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("SANDBAR_")}
        env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(self.src)
        # t261012-06 hygiene: this file drives the round runner module, so
        # it carries the face-dir pin even though today only prepare_tree()
        # runs — if a leg ever spawns a real round, the pin is in place
        env["SANDBAR_LINE_ROUND_FACE_DIR"] = str(self.tmp / "face")
        return env

    def prepare(self):
        return runner.prepare_tree(
            {"repo": "sandbar", "revision": self.sha},
            self.run_root, self.env())[0]

    def test_a_clone_carries_symlinked_assets_resolving_to_source(self):
        clone = self.prepare()
        for rel in runner.CLONE_ASSETS:
            link = clone / rel
            self.assertTrue(link.is_symlink(),
                            "clone lacks asset link: %s" % rel)
            self.assertTrue(link.exists(),
                            "asset link dangles: %s" % rel)
            self.assertEqual(Path(os.path.realpath(link)),
                             Path(os.path.realpath(self.src / rel)),
                             "asset link does not resolve to the source "
                             "copy: %s" % rel)
        probe = clone / "server" / "engine" / ".venv" / "bin" / "python"
        self.assertTrue(os.access(probe, os.X_OK),
                        "cwd-relative interpreter probe would miss")

    def test_b_idempotent_rematerialisation_is_stable(self):
        clone = self.prepare()
        before = {rel: os.readlink(str(clone / rel))
                  for rel in runner.CLONE_ASSETS}
        runner.materialise_assets(clone, self.src)
        after = {rel: os.readlink(str(clone / rel))
                 for rel in runner.CLONE_ASSETS}
        self.assertEqual(before, after,
                         "re-materialisation must not disturb live links")

    def test_c_committed_clone_path_is_never_overwritten(self):
        clone = self.prepare()
        rel = "server/ui-check/node_modules/playwright-core"
        committed = clone / rel
        committed.parent.mkdir(parents=True, exist_ok=True)
        if committed.is_symlink() or committed.exists():
            committed.unlink()
        committed.mkdir()  # pretend the clone committed this path
        (committed / "index.mjs").write_text("// tracked truth\n")
        runner.materialise_assets(clone, self.src)
        self.assertFalse(committed.is_symlink(),
                         "a committed clone path must never be replaced "
                         "by a link")
        self.assertEqual((committed / "index.mjs").read_text(),
                         "// tracked truth\n")


class HonestAbsenceLeg(unittest.TestCase):
    """An entry genuinely absent from the source stays absent — skipped
    with a named stderr line, never faked, never a failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="t26101121-abs-")
        self.tmp = Path(self._tmp.name)
        self.src, self.sha = make_source_repo(self.tmp, with_assets=False)
        self.run_root = self.tmp / "run"
        self.run_root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_d_absent_asset_is_skipped_and_named(self):
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            clone = runner.prepare_tree(
                {"repo": "sandbar", "revision": self.sha},
                self.run_root,
                {"SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR": str(self.src)})[0]
        for rel in runner.CLONE_ASSETS:
            self.assertFalse((clone / rel).exists()
                             or (clone / rel).is_symlink(),
                             "absent asset must not appear: %s" % rel)
        self.assertIn("asset_absent_in_source:server/engine/.venv",
                      err.getvalue(), "absence must be named on stderr")

    def test_e_absent_asset_survives_a_later_materialise_call(self):
        clone = self.tmp / "manual-clone"
        clone.mkdir()
        runner.materialise_assets(clone, self.src)
        self.assertEqual(sorted(p.name for p in clone.iterdir()), [],
                         "nothing may be linked for an asset-free source")

    def test_f_partial_source_links_only_what_exists(self):
        (self.src / "server" / "engine" / ".venv" / "bin").mkdir(
            parents=True, exist_ok=True)
        (self.src / "server" / "engine" / ".venv" / "bin" / "python") \
            .write_text("#!/bin/sh\n")
        clone = self.tmp / "partial-clone"
        clone.mkdir()
        runner.materialise_assets(clone, self.src)
        self.assertTrue((clone / "server/engine/.venv").is_symlink())
        self.assertTrue((clone / "server/engine/.venv/bin/python").exists(),
                        "probe through the dir link must resolve")
        self.assertFalse((clone / "node_modules").exists())


class FailureFaceLeg(unittest.TestCase):
    """A failed link is a named could-not-run, never a silent
    half-provisioned clone."""

    def test_g_link_failure_dies_named(self):
        import io
        import contextlib
        tmp = tempfile.TemporaryDirectory(prefix="t26101121-fail-")
        try:
            src = Path(tmp.name) / "src"
            rel = "server/engine/.venv"
            (src / rel).mkdir(parents=True)
            clone = Path(tmp.name) / "clone"
            clone.mkdir()
            # a directory sitting where the symlink must go, inside a
            # non-writable parent, makes os.symlink raise OSError
            dst_parent = clone / "server" / "engine"
            dst_parent.mkdir(parents=True)
            real_symlink = os.symlink

            def broken_symlink(*a, **kw):
                raise OSError(13, "Permission denied")

            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                saved = os.symlink
                os.symlink = broken_symlink
                try:
                    with self.assertRaises(SystemExit) as cm:
                        runner.materialise_assets(clone, src)
                finally:
                    os.symlink = saved
            self.assertEqual(cm.exception.code, 2)
            self.assertIn("asset_link_failed:%s" % rel, err.getvalue())
            self.assertFalse((clone / rel).exists())
        finally:
            tmp.cleanup()
        # silence linters about the unused alias
        del real_symlink


if __name__ == "__main__":
    unittest.main()
