"""t261019-12 UT: the epic registry moves to docs/epics with one enforced boolean.

Covers (design authority = docs/design/epic-registry-v1.md, host-ruled 261019):

- resolve_epics_dir: the default resolution is docs/epics at BOTH anchor levels
  (engine anchor and per-project home); the env override SANDBAR_EPICS_DIR still
  wins when set (an explicit operator override, visible and deliberate — a stale
  env value pointing at notes/epics must not silently reappear as a default);
- validate_epic_code enforcement (the single validation point): retired:true
  refuses a new ticket BY NAME (same voice as the unknown-code refusal, names the
  file it read); retired:false accepts; a missing/malformed front-matter block or
  a non-boolean retired value fails CLOSED (never accepts); the unknown-code and
  shape refusals keep their messages;
- shared fixture corpus (tests/fixtures/epic_registry_t261019/) — the same corpus
  the executor-panel contract test reads, so the python and node parsers cannot
  drift on what counts as fail-closed;
- hard cut: no notes/epics fallback exists in the resolution path.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared  # noqa: E402

FIXTURE_CORPUS = Path(__file__).resolve().parent / "fixtures" / "epic_registry_t261019"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class _Env:
    """Env override context (SANDBAR_EPICS_DIR / SANDBAR_PROJECTS_DIR)."""

    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


class TestResolveEpicsDirDocsAnchor(unittest.TestCase):
    def test_engine_anchor_defaults_to_docs_epics(self):
        with _Env(SANDBAR_EPICS_DIR=None):
            self.assertTrue(str(shared._epics_dir()).endswith(os.path.join("docs", "epics")))

    def test_project_anchor_defaults_to_docs_epics(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "proj"
            home.mkdir()
            # Registry layout = one <key>/project.yaml subdir per entry (the loader's shape).
            regdir = Path(tmp) / "reg" / "k1"
            regdir.mkdir(parents=True)
            (regdir / "project.yaml").write_text(
                "schema: v1\nproject:\n  - key: k1\n    name: K1\n    dirs:\n      - %s\n" % home,
                encoding="utf-8")
            with _Env(SANDBAR_EPICS_DIR=None, SANDBAR_PROJECTS_DIR=str(Path(tmp) / "reg")):
                d = shared.resolve_epics_dir("k1")
            self.assertEqual(d, home / "docs" / "epics")

    def test_env_override_still_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _Env(SANDBAR_EPICS_DIR=tmp):
                self.assertEqual(shared.resolve_epics_dir("k1"), Path(tmp))
                self.assertEqual(shared._epics_dir(), Path(tmp))

    def test_no_notes_epics_fallback_anywhere(self):
        # The hard cut: the resolution path never assembles notes/epics.
        with _Env(SANDBAR_EPICS_DIR=None):
            self.assertNotIn(os.path.join("notes", "epics"), str(shared._epics_dir()))


class TestValidateEpicCodeRetired(unittest.TestCase):
    def test_retired_true_refuses_by_name(self):
        with self.assertRaises(ValueError) as cm:
            shared.validate_epic_code("retired", str(FIXTURE_CORPUS))
        msg = str(cm.exception)
        self.assertIn("is retired", msg)
        self.assertIn("no longer accepts tickets", msg)
        self.assertIn(str(FIXTURE_CORPUS / "retired.md"), msg)  # names the file it read
        self.assertIn("retired: true", msg)

    def test_retired_false_accepts(self):
        self.assertEqual(shared.validate_epic_code("online", str(FIXTURE_CORPUS)), "online")

    def test_malformed_front_matter_fails_closed(self):
        with self.assertRaises(ValueError) as cm:
            shared.validate_epic_code("malformed", str(FIXTURE_CORPUS))
        msg = str(cm.exception)
        self.assertIn("refuses tickets", msg)
        self.assertIn("front-matter", msg)

    def test_prose_retired_value_fails_closed(self):
        with self.assertRaises(ValueError) as cm:
            shared.validate_epic_code("badretired", str(FIXTURE_CORPUS))
        self.assertIn("retired: false", str(cm.exception))

    def test_missing_front_matter_file_fails_closed(self):
        # A doc whose front-matter was stripped to an empty block must not accept.
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp) / "empty.md", "")
            with self.assertRaises(ValueError) as cm:
                shared.validate_epic_code("empty", tmp)
            self.assertIn("refuses tickets", str(cm.exception))

    def test_unreadable_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(Path(tmp) / "locked.md", "---\ncode: locked\nretired: false\n---\n")
            os.chmod(p, 0o000)
            try:
                if os.access(p, os.R_OK):  # running as root: skip the unreadable leg
                    self.skipTest("current user can read 000 files (root)")
                with self.assertRaises(ValueError) as cm:
                    shared.validate_epic_code("locked", tmp)
                self.assertIn("could not be read", str(cm.exception))
            finally:
                os.chmod(p, 0o644)

    def test_unknown_code_message_unchanged(self):
        with self.assertRaises(ValueError) as cm:
            shared.validate_epic_code("nope", str(FIXTURE_CORPUS))
        msg = str(cm.exception)
        self.assertIn("epic code not found", msg)
        self.assertIn("nope", msg)

    def test_illegal_shape_message_unchanged(self):
        with self.assertRaises(ValueError) as cm:
            shared.validate_epic_code("../escape", str(FIXTURE_CORPUS))
        self.assertIn("illegal epic code shape", str(cm.exception))

    def test_empty_code_passes(self):
        self.assertEqual(shared.validate_epic_code("", str(FIXTURE_CORPUS)), "")

    def test_real_docs_epics_registry_matches_contract(self):
        # The registry integration authored on main: every entry must parse at the
        # enforcement point, and its verdict must equal its front-matter boolean
        # (retired:true entries legitimately refuse — retired is the only state).
        docs = Path(__file__).resolve().parents[3] / "docs" / "epics"
        if not docs.is_dir():
            self.skipTest("docs/epics not present in this checkout")
        checked = 0
        for f in sorted(docs.glob("*.md")):
            fields = shared.parse_epic_front_matter(f.read_text(encoding="utf-8"))
            self.assertEqual(fields.get("code"), f.stem, f)
            retired = fields.get("retired")
            self.assertIn(retired, ("true", "false"), f)
            if retired == "false":
                self.assertEqual(shared.validate_epic_code(f.stem, str(docs)), f.stem, f)
            else:
                with self.assertRaises(ValueError, msg=str(f)):
                    shared.validate_epic_code(f.stem, str(docs))
            checked += 1
        self.assertGreaterEqual(checked, 16)  # the 16 migrated entries


class TestParseEpicFrontMatter(unittest.TestCase):
    def test_healthy_fields(self):
        fields = shared.parse_epic_front_matter((FIXTURE_CORPUS / "online.md").read_text(encoding="utf-8"))
        self.assertEqual(fields["code"], "epic-online")
        self.assertEqual(fields["retired"], "false")
        self.assertTrue(fields["summary"].startswith("A healthy registry entry"))
        self.assertEqual(fields["started"], "2026-10-19")

    def test_no_block_raises(self):
        with self.assertRaises(ValueError):
            shared.parse_epic_front_matter("# just a heading\n")

    def test_unterminated_block_raises(self):
        with self.assertRaises(ValueError):
            shared.parse_epic_front_matter("---\ncode: x\n")

    def test_malformed_line_raises(self):
        with self.assertRaises(ValueError):
            shared.parse_epic_front_matter("---\ncode x\n---\n")

    def test_body_after_block_is_not_parsed(self):
        fields = shared.parse_epic_front_matter(
            "---\ncode: x\nretired: false\n---\n\nbody mentions retired: true\n")
        self.assertEqual(fields["retired"], "false")


if __name__ == "__main__":
    unittest.main()
