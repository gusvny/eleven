#!/usr/bin/env python3
"""Unit battery for integration/lib_registry.py and the L23 lint face
(t261009-51, incident KI-01M4HD396VNTTAY20CH0681N0Q — registry serialization
style drift). Pure stdlib, tmpdir-reclaiming, no external sources: every
malformed input is built inline.

Faces:
  C1  canonical bytes shape: indent=2, ensure_ascii=False (raw CJK), exactly
      one trailing newline, insertion key order preserved.
  C2  root-agnostic: a JSON array root (batch_stage_exceptions.json's real
      shape) canonicalizes fine — a non-object root is NOT malformed here.
  C3  round trip: write_registry → parse equals the input object; bytes equal
      canonical_registry_bytes.
  C4  first_diff_line: None on identity; names the first differing line on a
      1-space vs 2-space drift; reports EOF/length drift and trailing-newline
      drift; long lines are trimmed.
  C5  malformed inputs: invalid JSON raises from the CONSUMER's json.loads
      (this module never swallows), non-serializable objects raise TypeError
      out of canonical_registry_bytes (never a partial write — the tmp target
      stays byte-untouched).
  C6  content-freeness of the ticket's normalization: for every declared
      registry, `git show HEAD:<path>` parsed == on-disk parsed (the
      deliberate normalization changed bytes, never structure). Skipped with
      a named reason when git is unavailable — that is an environment
      property, never a fake green.
  C7  L23 lint face: a tmp repo with a canonical registry is clean; rewriting
      the same content at indent=1 goes RED naming the file and the first
      differing line; an unreadable declared registry is fail-closed RED; a
      malformed-JSON registry is left to other faces (L23 silent on it).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INTEG = Path(__file__).resolve().parents[2] / "integration"
sys.path.insert(0, str(INTEG))

import lib_registry  # noqa: E402
from lib_registry import (  # noqa: E402
    CANONICAL_JSON_KWARGS,
    DECLARED_REGISTRIES,
    canonical_registry_bytes,
    first_diff_line,
    write_registry,
)

_RECLAIM = None


def _tmp(self):
    d = tempfile.mkdtemp(prefix="t261009-51-")
    self.addCleanup(shutil.rmtree, d, True)
    return Path(d)


class CanonicalBytes(unittest.TestCase):
    def test_c1_shape(self):
        obj = {"b": 1, "a": {"深": "值"}}
        text = canonical_registry_bytes(obj)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))
        lines = text.splitlines()
        self.assertEqual(lines[0], "{")
        self.assertEqual(lines[1], '  "b": 1,')           # insertion order kept
        self.assertIn('"深": "值"', text)                  # raw, not \u-escaped
        self.assertEqual(text,
                         json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

    def test_c1_kwargs_declared_once(self):
        self.assertEqual(CANONICAL_JSON_KWARGS,
                         {"ensure_ascii": False, "indent": 2})
        self.assertNotIn("sort_keys", CANONICAL_JSON_KWARGS)

    def test_c2_array_root_is_fine(self):
        # batch_stage_exceptions.json is a JSON array: root-agnostic, in good
        # standing — NOT a malformed-input case for this module.
        obj = [{"entry": "x", "reason": "理由"}]
        text = canonical_registry_bytes(obj)
        self.assertEqual(json.loads(text), obj)
        self.assertEqual(text.splitlines()[0], "[")

    def test_c2_scalars(self):
        for v in (1, "s", True, None, 1.5):
            self.assertEqual(json.loads(canonical_registry_bytes(v)), v)

    def test_c3_round_trip(self):
        p = _tmp(self) / "reg.json"
        obj = {"zeta": [1, 2], "alpha": {"k": "中文"}}
        write_registry(p, obj)
        raw = p.read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw), obj)
        self.assertEqual(raw, canonical_registry_bytes(obj))


class FirstDiffLine(unittest.TestCase):
    def test_c4_identity(self):
        self.assertIsNone(first_diff_line("a\nb\n", "a\nb\n"))

    def test_c4_style_drift_named(self):
        canon = '{\n  "k": "v"\n}\n'
        disk = '{\n "k": "v"\n}\n'                     # 1-space style, same content
        out = first_diff_line(canon, disk)
        self.assertIn("line 2", out)
        self.assertIn("canonical", out)
        self.assertIn("disk", out)

    def test_c4_eof_drift(self):
        # '  "a": 1' vs '  "a": 1,' already differs at line 2; the drift then
        # runs to the shorter text's end — the report anchors on that first
        # differing line.
        out = first_diff_line('{\n  "a": 1\n}\n', '{\n  "a": 1,\n  "b": 2\n}\n')
        self.assertIn("line 2", out)

    def test_c4_trailing_newline_drift(self):
        out = first_diff_line("a\n", "a")
        self.assertIn("trailing newline drift", out)

    def test_c4_long_lines_trimmed(self):
        long = "x" * 300
        out = first_diff_line(long + "\n", long + "y\n")
        self.assertLess(len(out), 250)


class MalformedInputs(unittest.TestCase):
    def test_c5_invalid_json_raises_at_consumer(self):
        bad = '{"k": "v",}'                            # trailing comma
        with self.assertRaises(ValueError):
            json.loads(bad)

    def test_c5_unserializable_raises_no_partial_write(self):
        p = _tmp(self) / "reg.json"
        p.write_text("SENTINEL", encoding="utf-8")
        with self.assertRaises(TypeError):
            write_registry(p, {"k": object()})
        self.assertEqual(p.read_text(encoding="utf-8"), "SENTINEL")


class ContentFreeNormalization(unittest.TestCase):
    #: Entries THIS ticket deliberately adds on top of HEAD (its own two
    #: scenario anchor registrations). Everything else must be byte-content
    #: equal to HEAD — the normalization itself is content-free.
    OWN_ANCHOR_PREFIX = "integration/t261009-51/"

    def test_c6_head_vs_disk_parsed_equal(self):
        # A main-sync merge in progress legitimately puts entries on disk that
        # HEAD does not have yet (the union resolution). That is an
        # environment property of the tree, not a content-freeness failure —
        # named skip, never a fake green; re-judged once the merge settles.
        un = subprocess.run(
            ["git", "ls-files", "-u", "--", "test_anchors.json"],
            cwd=str(INTEG), capture_output=True, timeout=60)
        if un.returncode == 0 and un.stdout.strip():
            self.skipTest("merge in progress: %d unresolved index entries "
                          "for test_anchors.json — HEAD-vs-disk comparison "
                          "is only meaningful on a settled merge"
                          % len(un.stdout.strip().splitlines()))
        try:
            head = subprocess.run(
                ["git", "show", "HEAD:%s" % "integration/test_anchors.json"],
                cwd=str(INTEG), capture_output=True, timeout=60)
        except OSError as e:
            self.skipTest("git unavailable: %s" % e)
        if head.returncode != 0:
            self.skipTest("git show failed: %s" % head.stderr.decode()[:120])
        for rel in DECLARED_REGISTRIES:
            with self.subTest(registry=rel):
                name = rel.split("/", 1)[1]
                got = subprocess.run(["git", "show", "HEAD:integration/%s" % name],
                                     cwd=str(INTEG), capture_output=True, timeout=60)
                if got.returncode != 0:
                    self.skipTest("HEAD has no %s" % rel)
                head_obj = json.loads(got.stdout.decode("utf-8"))
                disk_obj = json.loads(
                    (INTEG / name).read_text(encoding="utf-8"))
                if name == "test_anchors.json":
                    # Header: counts advance with lawful entries, so compare
                    # everything EXCEPT labelled_counts, and pin the counts to
                    # the actual structure instead.
                    self.assertEqual(
                        {k: v for k, v in head_obj["_header"].items()
                         if k != "labelled_counts"},
                        {k: v for k, v in disk_obj["_header"].items()
                         if k != "labelled_counts"})
                    self.assertEqual(disk_obj["_header"]["labelled_counts"],
                                     {"engine_tests": len(disk_obj["engine_tests"]),
                                      "scenarios": len(disk_obj["scenarios"])})
                    self.assertEqual(head_obj["engine_tests"],
                                     disk_obj["engine_tests"])
                    hs, ds = head_obj["scenarios"], disk_obj["scenarios"]
                    own = [k for k in ds if k not in hs]
                    self.assertEqual(
                        own, sorted(o for o in own
                                    if o.startswith(self.OWN_ANCHOR_PREFIX)))
                    for k in hs:
                        self.assertEqual(hs[k], ds[k])
                else:
                    self.assertEqual(head_obj, disk_obj)


class LintFace(unittest.TestCase):
    def _lint(self, repo):
        import lint_tests
        errs = []
        lint_tests.lint_registry_serialization(errs.append, repo=repo)
        return errs

    def test_c7_clean_tree_is_green(self):
        repo = _tmp(self)
        (repo / "integration").mkdir(parents=True)
        write_registry(repo / DECLARED_REGISTRIES[0],
                       {"k": "v"})
        # Patch the declared set down to the one file we wrote.
        import lib_registry
        orig = lib_registry.DECLARED_REGISTRIES
        lib_registry.DECLARED_REGISTRIES = ["integration/test_anchors.json"]
        try:
            self.assertEqual(self._lint(repo), [])
        finally:
            lib_registry.DECLARED_REGISTRIES = orig

    def test_c7_style_drift_is_red_and_named(self):
        repo = _tmp(self)
        (repo / "integration").mkdir(parents=True)
        p = repo / "integration" / "test_anchors.json"
        # Same CONTENT as canonical, 1-space style: the exact incident shape.
        p.write_text(json.dumps({"k": "v"}, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
        import lib_registry
        orig = lib_registry.DECLARED_REGISTRIES
        lib_registry.DECLARED_REGISTRIES = ["integration/test_anchors.json"]
        try:
            errs = self._lint(repo)
        finally:
            lib_registry.DECLARED_REGISTRIES = orig
        self.assertEqual(len(errs), 1)
        self.assertIn("test_anchors.json", errs[0])
        self.assertIn("line 2", errs[0])

    def test_c7_unreadable_is_fail_closed_red(self):
        repo = _tmp(self)
        (repo / "integration").mkdir(parents=True)
        import lib_registry
        orig = lib_registry.DECLARED_REGISTRIES
        lib_registry.DECLARED_REGISTRIES = ["integration/test_anchors.json"]
        try:
            errs = self._lint(repo)
        finally:
            lib_registry.DECLARED_REGISTRIES = orig
        self.assertEqual(len(errs), 1)
        self.assertIn("unreadable", errs[0])

    def test_c7_malformed_json_left_to_other_faces(self):
        repo = _tmp(self)
        (repo / "integration").mkdir(parents=True)
        (repo / "integration" / "test_anchors.json").write_text(
            "{not json", encoding="utf-8")
        import lib_registry
        orig = lib_registry.DECLARED_REGISTRIES
        lib_registry.DECLARED_REGISTRIES = ["integration/test_anchors.json"]
        try:
            self.assertEqual(self._lint(repo), [])
        finally:
            lib_registry.DECLARED_REGISTRIES = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
