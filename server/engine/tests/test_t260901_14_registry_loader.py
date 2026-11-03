"""t260901-14 registry-loader：装载器 intent 承接（t260904-02 重指）。

原形态：subprocess 跑 integration/t260901-14/registry-loader.py——该目录随 sandbar
迁仓未入本仓（悬空 latent red，本仓 integration/ 只有 t260903-10/12/13，ls 可证）。
t260904-02 把装载器上收 engine/shared.py（KI-032 单一真源）后，本 intent 的
合法落点=直接驱动 shared 装载器：legacy / per-key / 隔离 / 空 / 未知 五态最小集。
全量用例（含 env 现读、key 白名单畸形、check_paths、硬闸行为级）在
test_t260904_02_registry_anchor.py——本文件保持原票号可见 + 最小五态，不重复全量。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （夹具注册表+atexit 回收）

import shared  # noqa: E402


def _mk(root, key, content):
    d = Path(root) / key
    d.mkdir(parents=True)
    (d / "project.yaml").write_text(content, encoding="utf-8")
    return d


_GOOD = "schema: v1\nproject:\n  - key: %s\n    name: n\n    dirs:\n      - /tmp/%s\n"


class RegistryLoaderLegacyIntent(unittest.TestCase):
    def test_legacy_env_mode(self):
        tmp = str(mkdtemp_reclaimed("t260901-14-r-"))
        legacy = os.path.join(tmp, "projects.yaml")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("projects:\n  - key: legacy\n    name: 旧档\n    dirs:\n      - /tmp/legacy\n")
        os.environ["SANDBAR_PROJECTS_YAML"] = legacy
        try:
            projects, quarantined = shared.load_projects_registry()
            self.assertEqual(projects[0]["key"], "legacy")
            self.assertEqual(quarantined, [])
        finally:
            del os.environ["SANDBAR_PROJECTS_YAML"]

    def test_per_key_scan_and_quarantine(self):
        tmp = str(mkdtemp_reclaimed("t260901-14-p-"))
        _mk(tmp, "good-one", _GOOD % ("good-one", "g"))
        _mk(tmp, "sick-one", "schema: v1\nproject:\n  - key: sick-one\n    name: n\n    dirs:\n      - /tmp/s\nxxx-bad-line: 1\n")
        os.environ["SANDBAR_PROJECTS_DIR"] = tmp
        try:
            projects, quarantined = shared.load_projects_registry()
            self.assertEqual([p["key"] for p in projects], ["good-one"])
            self.assertEqual(len(quarantined), 1)
            # 隔离条目按 key 可见原因
            with self.assertRaises(ValueError) as cm:
                shared.lookup_project("sick-one")
            self.assertIn("is quarantined", str(cm.exception))
        finally:
            del os.environ["SANDBAR_PROJECTS_DIR"]

    def test_unknown_and_empty(self):
        tmp = str(mkdtemp_reclaimed("t260901-14-u-"))
        _mk(tmp, "only", _GOOD % ("only", "o"))
        os.environ["SANDBAR_PROJECTS_DIR"] = tmp
        try:
            with self.assertRaises(ValueError) as cm:
                shared.lookup_project("ghost")
            self.assertIn("unknown project", str(cm.exception))
        finally:
            del os.environ["SANDBAR_PROJECTS_DIR"]
        with self.assertRaises(ValueError) as cm2:
            shared.assert_registry_nonempty([], [])
        self.assertIn("no project entries at all", str(cm2.exception))


if __name__ == "__main__":
    unittest.main()


# ======================================================================
# t261103-11 — docs roots (1/2): ONE declaration, ONE resolution
# (design docs/design/project-docs-roots-v1.md goals 1-4, 9-11; the engine/gate
# half: declaration truth table, the three named refusals, one root and many).
# The declaration lives in the registry entry the engine already owns
# (`paths.docs_roots`), so these legs drive the real reader over a real
# temporary registry - no real ~/.sandbar ledger, no network.
# ======================================================================

import docs_roots  # noqa: E402


class DocsRootsDeclarationTest(unittest.TestCase):
    """The declaration truth table and the three refused states."""

    def setUp(self):
        self.tmp = Path(mkdtemp_reclaimed("t261103-11-roots-"))
        self.projects = self.tmp / "projects"
        self.projects.mkdir(parents=True)
        # the project root (a real tree; the documentation roots live inside it)
        self.root = self.tmp / "tree"
        self.root.mkdir()
        (self.root / "docs").mkdir()
        (self.root / "guide").mkdir()
        (self.root / "web").mkdir()
        (self.root / "web" / "docs").mkdir()
        self._old_env = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(self.projects)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = self._old_env
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def entry(self, block=""):
        """One registry entry in the real shape; `block` is the paths content."""
        d = self.projects / "probe"
        d.mkdir(parents=True, exist_ok=True)
        (d / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: probe\n    name: probe\n    dirs:\n"
            "      - %s\npaths:\n%s" % (self.root, block), encoding="utf-8")

    # ---- truth table -------------------------------------------------

    def test_absent_block_is_the_implied_default_root(self):
        self.entry("  dsh_bin: /bin/sh\n")
        res = docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(res.source, "implied")
        self.assertEqual(res.paths(), ("docs",))
        self.assertEqual(res.roots[0].directory, self.root / "docs")

    def test_no_entry_at_all_is_the_implied_default_root(self):
        res = docs_roots.resolve("ghost", tree=self.root)
        self.assertEqual(res.source, "implied")
        self.assertEqual(res.paths(), ("docs",))

    def test_one_declared_root(self):
        self.entry("  docs_roots:\n    - repository: .\n      path: guide\n")
        res = docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(res.source, "declared")
        self.assertEqual(res.paths(), ("guide",))
        self.assertEqual(res.roots[0].directory, self.root / "guide")

    def test_many_declared_roots_keep_declaration_order(self):
        self.entry("  docs_roots:\n"
                   "    - repository: .\n      path: guide\n"
                   "    - repository: .\n      path: docs\n")
        res = docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(res.paths(), ("guide", "docs"))

    def test_declared_roots_split_by_repository(self):
        self.entry("  docs_roots:\n"
                   "    - repository: .\n      path: guide\n"
                   "    - repository: web\n      path: docs\n")
        here = docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(here.paths(), ("guide",))
        there = docs_roots.resolve("probe", tree=self.root / "web")
        self.assertEqual(there.paths(), ("docs",))
        self.assertEqual(there.roots[0].repository, "web")

    def test_declared_elsewhere_is_a_named_state_not_an_empty_answer(self):
        self.entry("  docs_roots:\n    - repository: web\n      path: docs\n")
        other = self.tmp / "unrelated"
        other.mkdir()
        res = docs_roots.resolve("probe", tree=other)
        self.assertEqual(res.roots, ())
        self.assertEqual(res.reason, "declared_elsewhere")

    # ---- malformed shapes are never read as "nothing declared" -------

    def test_unknown_entry_key_is_named(self):
        self.entry("  docs_roots:\n    - repo: .\n      path: guide\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(cm.exception.code,
                         docs_roots.STOP_DECLARATION_MALFORMED)

    def test_entry_missing_a_key_is_named(self):
        self.entry("  docs_roots:\n    - repository: .\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(cm.exception.code,
                         docs_roots.STOP_DECLARATION_MALFORMED)
        self.assertIn("path", str(cm.exception))

    def test_duplicate_root_is_named(self):
        self.entry("  docs_roots:\n"
                   "    - repository: .\n      path: guide\n"
                   "    - repository: .\n      path: guide\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(cm.exception.code, docs_roots.STOP_DUPLICATE)

    def test_absolute_and_escaping_paths_are_named(self):
        for bad in ("/etc", "../outside", "guide/"):
            self.entry("  docs_roots:\n    - repository: .\n      path: %s\n" % bad)
            with self.assertRaises(docs_roots.DocsRootsStop) as cm:
                docs_roots.resolve("probe", tree=self.root)
            self.assertEqual(cm.exception.code,
                             docs_roots.STOP_DECLARATION_MALFORMED, bad)

    def test_whole_repository_root_is_refused(self):
        # `path: .` would exclude the whole tree: the false-green shape.
        self.entry("  docs_roots:\n    - repository: .\n      path: .\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(cm.exception.code,
                         docs_roots.STOP_DECLARATION_MALFORMED)

    # ---- the three required refusals, each naming what it looked for --

    def test_refusal_absent_names_the_declaration_and_the_directory(self):
        self.entry("")
        (self.root / "docs").rmdir()
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        e = cm.exception
        self.assertEqual(e.code, docs_roots.STOP_ABSENT)
        self.assertIn("paths.docs_roots", e.message)   # the declaration looked for
        self.assertIn(str(self.root / "docs"), e.message)   # the path looked for

    def test_refusal_declared_absent_names_the_declaration_and_the_path(self):
        self.entry("  docs_roots:\n    - repository: .\n      path: moved\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        e = cm.exception
        self.assertEqual(e.code, docs_roots.STOP_ROOT_ABSENT)
        self.assertIn("project.yaml", e.declaration)
        self.assertIn("moved", e.message)
        self.assertIn(str(self.root / "moved"), e.message)

    def test_refusal_declared_unreadable_names_the_path(self):
        # a file where a directory was declared: present, unreadable as a root
        (self.root / "notes-as-root").write_text("x", encoding="utf-8")
        self.entry("  docs_roots:\n    - repository: .\n      path: notes-as-root\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        e = cm.exception
        self.assertEqual(e.code, docs_roots.STOP_ROOT_UNREADABLE)
        self.assertIn(str(self.root / "notes-as-root"), e.message)

    def test_refusal_permission_denied_root_is_unreadable(self):
        target = self.root / "locked"
        target.mkdir()
        os.chmod(target, 0o000)
        try:
            if os.access(str(target), os.R_OK | os.X_OK):
                self.skipTest("permission bits do not deny this user (root?)")
            self.entry("  docs_roots:\n    - repository: .\n      path: locked\n")
            with self.assertRaises(docs_roots.DocsRootsStop) as cm:
                docs_roots.resolve("probe", tree=self.root)
            self.assertEqual(cm.exception.code,
                             docs_roots.STOP_ROOT_UNREADABLE)
        finally:
            os.chmod(target, 0o755)

    def test_refusal_unknown_repository_names_it(self):
        self.entry("  docs_roots:\n    - repository: nope\n      path: docs\n")
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.resolve("probe", tree=self.root)
        self.assertEqual(cm.exception.code,
                         docs_roots.STOP_REPOSITORY_UNKNOWN)
        self.assertIn(str(self.root / "nope"), cm.exception.message)


class DocsRootsReaderFacesTest(unittest.TestCase):
    """Every reader face tolerates the declaration (t260928-13 lesson: an engine
    key that falls outside one reader quarantines the project)."""

    def setUp(self):
        self.tmp = Path(mkdtemp_reclaimed("t261103-11-faces-"))
        self.projects = self.tmp / "projects"
        entry = self.projects / "probe"
        entry.mkdir(parents=True)
        self.root = self.tmp / "tree"
        (self.root / "guide").mkdir(parents=True)
        (entry / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: probe\n    name: probe\n    dirs:\n"
            "      - %s\npaths:\n  dsh_bin: /bin/sh\n"
            "  docs_roots:\n    - repository: .\n      path: guide\n" % self.root,
            encoding="utf-8")
        self._old_env = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(self.projects)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = self._old_env
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_registry_loader_tolerates_the_block(self):
        projects, quarantined = shared.load_projects_registry()
        self.assertEqual([p["key"] for p in projects], ["probe"])
        self.assertEqual(quarantined, [])

    def test_paths_reader_tolerates_the_block(self):
        info = shared.project_paths("probe")
        self.assertEqual(str(info["dsh_bin"]), "/bin/sh")
        self.assertIn("docs_roots", info and shared.PATHS_DECL_KEYS)

    def test_a_scalar_value_for_the_block_is_still_refused(self):
        d = self.projects / "probe"
        (d / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: probe\n    name: probe\n    dirs:\n"
            "      - %s\npaths:\n  docs_roots: docs\n" % self.root,
            encoding="utf-8")
        with self.assertRaises(shared.ProjectPathsError) as cm:
            shared.project_paths("probe")
        self.assertIn("paths.docs_roots", str(cm.exception))
