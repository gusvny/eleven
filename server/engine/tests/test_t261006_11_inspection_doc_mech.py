"""UT for the doc-face mechanical layer (M1-M7) — t261006-11.

Truth-table discipline (lexical-constant rule 10): every rule fires / does not
fire on a planted fixture, including the review-pinned cases:
  - S10-fixed resolution: a path that resolves under the repo root but NOT under
    the document's own directory MUST fire (no repo-root fallback);
  - glob shapes (*.d.ts) are never treated as paths;
  - historical face (docs/design) does not fire for path drift;
  - malformed inputs (broken index.json, unreadable page, bogus diff paths) degrade
    with meta caveats, never crash, never fake green;
  - ids are content-stable across two identical runs (mint_finding_id).
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inspection_doc_mech import (  # noqa: E402
    DocMechError, collect_exemptions, extract_paths, frontmatter_defects,
    parse_frontmatter, run_doc_mech)


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


FM = ("---\ntitle: t\ncategory: reference\ntags: [x]\n"
      "status: active\nupdated: 2026-10-06\n---\n\n")


# tmp reclaim (L8 hygiene): every fixture tree is tracked and removed on exit and
# again per-test via tearDown
_TMP_DIRS: list = []


def _reap_tmp() -> None:
    for d in _TMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)
    _TMP_DIRS.clear()


atexit.register(_reap_tmp)


def _mk_repo(**pages: str) -> Path:
    """Minimal library: index + README + the pages given as kwargs (rel → text)."""
    repo = Path(tempfile.mkdtemp(prefix="docmech-ut-"))
    _TMP_DIRS.append(repo)
    (repo / "docs").mkdir()
    index = {"docs": [{"path": rel[len("docs/"):] if rel.startswith("docs/") else rel}
                      for rel in sorted(set(pages) | {"docs/README.md"})]}
    (repo / "docs" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    readme_rows = "\n".join("| `%s` | x |" % rel
                            for rel in sorted(set(pages) | {"docs/README.md"}))
    _write(repo, "docs/README.md", FM + "# docs index\n" + readme_rows + "\n")
    for rel, text in pages.items():
        _write(repo, rel, text)
    return repo


def _run(repo, **kw):
    return run_doc_mech(str(repo), **kw)


def _scans(res):
    return [f["scan"] for f in res["findings"]]


class ExtractPathsTest(unittest.TestCase):
    def test_explicit_shapes_only(self):
        toks = [t for t, _ in extract_paths("see `server/engine/x.py` and [g](../a/b.md)")]
        self.assertEqual(sorted(toks), ["../a/b.md", "server/engine/x.py"])

    def test_glob_and_url_never_paths(self):
        toks = [t for t, _ in extract_paths("`*.d.ts` `src/*` [k](https://e.com/a.md) [s](#anchor)")]
        self.assertEqual(toks, [])


class FrontmatterTest(unittest.TestCase):
    def test_five_fields_ok(self):
        f, well = parse_frontmatter(FM + "body")
        self.assertTrue(well)
        self.assertEqual(frontmatter_defects(f, well), [])

    def test_missing_field_and_bad_date(self):
        f, well = parse_frontmatter("---\ntitle: t\ncategory: nope\nupdated: 2026/1/1\n---\n")
        d = frontmatter_defects(f, well)
        self.assertTrue(any("tags" in x for x in d))
        self.assertTrue(any("status" in x for x in d))
        self.assertTrue(any("updated" in x for x in d))

    def test_unterminated_block_degrades(self):
        f, well = parse_frontmatter("---\ntitle: t\nno close")
        self.assertFalse(well)
        self.assertTrue(frontmatter_defects(f, well))


class M1Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()

    def test_unregistered_page_fires(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "a"})
        # drop the page from the index: it exists but is not registered
        (repo / "docs" / "index.json").write_text(
            json.dumps({"docs": [{"path": "README.md"}]}), encoding="utf-8")
        res = _run(repo)
        self.assertIn("doc-m1-index", _scans(res))

    def test_registered_missing_in_readme_fires_readme_leg(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "a"})
        # remove the README row the fixture wrote
        (repo / "docs" / "README.md").write_text(FM + "# docs index\n", encoding="utf-8")
        res = _run(repo)
        self.assertIn("doc-m1-readme", _scans(res))

    def test_ghost_entry_fires(self):
        repo = _mk_repo()
        idx = json.loads((repo / "docs" / "index.json").read_text())
        idx["docs"].append({"path": "reference/gone.md"})
        (repo / "docs" / "index.json").write_text(json.dumps(idx), encoding="utf-8")
        res = _run(repo)
        m1 = [f for f in res["findings"] if f["scan"] == "doc-m1-index"
              and any("gone" in (e.get("quote") or "") or "gone" in f["subject"]
                      for e in f["evidence"])]
        self.assertEqual(len(m1), 1)

    def test_missing_frontmatter_field_fires(self):
        repo = _mk_repo(**{"docs/reference/a.md": "---\ntitle: t\n---\nbody"})
        res = _run(repo)
        self.assertIn("doc-m1-frontmatter", _scans(res))

    def test_broken_index_degrades_with_caveat(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "a"})
        (repo / "docs" / "index.json").write_text("{not json", encoding="utf-8")
        res = _run(repo)
        self.assertFalse(res["meta"]["heartbeat"])   # frontmatter/README legs still judged
        self.assertTrue(any("index" in c for c in res["meta"]["caveats"]))


class M2Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_unreachable_link_in_reference_page_fires(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [x](../notes/epics/missing.md)"})
        res = _run(repo)
        self.assertIn("doc-m2-unreachable", _scans(res))

    def test_root_shaped_backtick_resolves_from_repo_root(self):
        """Integration-gate RC1 semantics: a root-shaped backtick path
        (`src/code.py`, no ./ ../ prefix) resolves from the REPO ROOT, never
        doc-relative — repo-shaped paths are the docs' dominant style; the
        doc-relative reading of them was the 140-FP shape."""
        repo = _mk_repo(**{"docs/reference/rel.md": FM + "uses `src/code.py`",
                           "src/code.py": "x"})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))
        # ...and a root-shaped path that is missing anywhere still fires
        repo2 = _mk_repo(**{"docs/reference/rel.md": FM + "uses `src/gone.py`",
                            "src/code.py": "x"})
        res2 = _run(repo2)
        m2 = [f for f in res2["findings"] if f["scan"] == "doc-m2-unreachable"]
        self.assertEqual(len(m2), 1)
        self.assertIn("src/gone.py", m2[0]["subject"])

    def test_explicit_doc_relative_shape_is_doc_directory_only(self):
        """An explicit `../` shape is a doc-relative claim: `../g.md` from
        docs/reference/ resolves to docs/g.md — if that is missing it FIRES even
        though a same-named file exists elsewhere under the root."""
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [g](../g.md)",
                           "src/g.md": "x"})
        res = _run(repo)
        m2 = [f for f in res["findings"] if f["scan"] == "doc-m2-unreachable"]
        self.assertEqual(len(m2), 1)
        self.assertIn("../g.md", m2[0]["subject"])

    def test_bare_filename_found_by_basename_passes(self):
        """A bare filename that exists ANYWHERE in the repo is reachable by name;
        firing on it would recreate the 140-FP shape (bare-name refs are the
        docs' dominant style). The drift still surfaces via the M1 README leg."""
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [g](testing-guide.md)",
                           "docs/testing-guide.md": FM + "g"})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))

    def test_doc_dir_relative_link_passes(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [b](b.md)",
                           "docs/reference/b.md": FM + "b"})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))

    def test_command_line_backtick_never_fires(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM +
                           "run `python3 docs/scripts/build_index.py` and `admin.py call x`"})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))

    def test_glob_never_fires(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see `*.d.ts` and `src/*.py`"})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))

    def test_historical_face_exempt_from_path_drift(self):
        hist = ("---\ntitle: t\ncategory: design\ntags: [x]\nstatus: active\n"
                "updated: 2026-01-01\n---\nsee [old](../reference/gone-forever.md)")
        repo = _mk_repo(**{"docs/design/old.md": hist})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))

    def test_exemption_comment_suppresses_and_counts(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM +
                           "<!-- doc-exempt: doc-m2-unreachable -->\nsee [x](missing.md)"})
        res = _run(repo)
        self.assertNotIn("doc-m2-unreachable", _scans(res))
        self.assertIn("doc-m2-unreachable", res["meta"]["exempted"])


class M3Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_new_cjk_line_in_docs_fires_existing_not(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "old \u4e2d\u6587 line stays\nnew line\n"})
        added = {"docs/reference/a.md": {8: "\u65b0\u589e\u4e00\u884c\u4e2d\u6587"}}
        res = _run(repo, added_lines=added, base_head="x")
        m3 = [f for f in res["findings"] if f["scan"] == "doc-m3-language-docs"]
        self.assertEqual(len(m3), 1)
        self.assertEqual(m3[0]["evidence"][0]["line"], 8)

    def test_declared_language_exceptions_pass(self):
        repo = _mk_repo(**{"docs/terminology.md": FM + "\u672f\u8bed"})
        res = _run(repo, added_lines={"docs/terminology.md": {8: "\u672f\u8bed\u8868"}},
                   base_head="x")
        self.assertNotIn("doc-m3-language-docs", _scans(res))

    def test_fenced_code_and_inline_code_skipped(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "```\n\u4e2d\u6587\n```\nkeep `\u4e2d\u6587` inline\n"})
        res = _run(repo, added_lines={"docs/reference/a.md": {12: "keep `\u4e2d\u6587` inline"}},
                   base_head="x")
        self.assertNotIn("doc-m3-language-docs", _scans(res))

    def test_notes_pure_english_new_line_fires(self):
        repo = _mk_repo(**{"notes/d.md": FM + "\u65e7\u884c\u4e2d\u6587\n"})
        res = _run(repo, added_lines={"notes/d.md": {8: "this is a plain english line"}},
                   base_head="x")
        self.assertIn("doc-m3-language-notes", _scans(res))

    def test_no_diff_skips_m3_with_caveat(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "\u4e2d\u6587\u5b58\u91cf"})
        res = _run(repo)
        self.assertNotIn("doc-m3-language-docs", _scans(res))
        self.assertFalse(res["meta"]["diff_rules_ran"])


class M4Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_checkbox_in_docs_fires_notes_not(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "- [ ] do later\n",
                           "notes/x.md": FM + "- [ ] scratch\n"})
        res = _run(repo)
        hits = [f for f in res["findings"] if f["scan"] == "doc-m4-progress-list"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["subject"].startswith("docs/reference/a.md") or
                        hits[0]["evidence"][0]["path"] == "docs/reference/a.md")

    def test_ticket_list_line_fires_single_id_not(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM +
                           "t260901-01 t260901-02 t260901-03\nalso t260901-04 only\n"})
        res = _run(repo)
        hits = [f for f in res["findings"] if f["scan"] == "doc-m4-ticket-list"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["evidence"][0]["line"], 9)


class M5Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_missing_ticket_on_new_line_fires(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "body t269999-99 ref\n"})
        res = _run(repo, added_lines={"docs/reference/a.md": {8: "t269999-99"}},
                   base_head="x", ticket_exists=lambda t: False)
        hits = [f for f in res["findings"] if f["scan"] == "doc-m5-ticket"]
        self.assertEqual(len(hits), 1)

    def test_existing_ticket_and_predicate_none_degrades(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "t261006-11 ok\n"})
        res = _run(repo, added_lines={"docs/reference/a.md": {8: "t261006-11"}},
                   base_head="x", ticket_exists=lambda t: True)
        self.assertNotIn("doc-m5-ticket", _scans(res))
        res2 = _run(repo, added_lines={"docs/reference/a.md": {8: "t261006-11"}}, base_head="x")
        self.assertNotIn("doc-m5-ticket", _scans(res2))
        self.assertTrue(any("ticket" in c for c in res2["meta"]["caveats"]))

    def test_historical_face_exempt_from_commit_check(self):
        repo = _mk_repo(**{"docs/design/old.md": FM + "sha\n"})
        repo2 = repo
        res = _run(repo2, added_lines={"docs/design/old.md": {8: "deadbeef" * 5 + "x"}},
                   base_head="x", commit_exists=lambda s: False)
        self.assertNotIn("doc-m5-commit", _scans(res))

    def test_bogus_diff_paths_degrade_silently(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "ok\n"})
        res = _run(repo, added_lines={"no/such/file.md": {8: "\u4e2d\u6587"}},
                   base_head="x", ticket_exists=lambda t: False)
        self.assertEqual([f for f in res["findings"] if f["scan"].startswith("doc-m3")], [])


class M6Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def _dep(self, body=""):
        return ("---\ntitle: t\ncategory: design\ntags: [x]\nstatus: deprecated\n"
                "updated: 2026-01-01\n---\n" + body)

    def test_deprecated_without_pointer_fires(self):
        repo = _mk_repo(**{"docs/design/old.md": self._dep()})
        res = _run(repo)
        self.assertIn("doc-m6-supersede", _scans(res))

    def test_deprecated_with_pointer_passes(self):
        repo = _mk_repo(**{"docs/design/old.md": self._dep("Superseded by `docs/design/new.md`")})
        res = _run(repo)
        self.assertNotIn("doc-m6-supersede", _scans(res))

    def test_active_design_page_not_judged(self):
        repo = _mk_repo(**{"docs/design/ok.md": FM + "fine"})
        res = _run(repo)
        self.assertNotIn("doc-m6-supersede", _scans(res))


class M7Test(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_changed_code_named_by_page_gives_low_pointer(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "uses `server/engine/x.py`\n"})
        res = _run(repo, changed_files=["server/engine/x.py"])
        ptr = [f for f in res["findings"] if f["scan"] == "doc-m7-must-check"]
        self.assertEqual(len(ptr), 1)
        self.assertEqual(ptr[0]["severity"], "low")

    def test_changed_page_naming_missing_surface_fires_med(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "uses `server/engine/gone.py`\n"})
        res = _run(repo, changed_files=["docs/reference/a.md"])
        hits = [f for f in res["findings"] if f["scan"] == "doc-m7-stale"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["severity"], "med")

    def test_unchanged_surface_no_pointer(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "uses `server/engine/x.py`\n"})
        res = _run(repo, changed_files=["server/engine/other.py"])
        self.assertNotIn("doc-m7-must-check", _scans(res))


class ShapeAndStabilityTest(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_finding_shape_matches_agent_contract(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [x](missing.md)"})
        res = _run(repo)
        for f in res["findings"]:
            self.assertEqual(set(f) >= {"id", "scan", "severity", "subject",
                                        "evidence", "why", "suggestion"}, True)
            ev = f["evidence"][0]
            self.assertEqual(set(ev) >= {"path", "line", "quote"}, True)
            self.assertIn(f["severity"], ("high", "med", "low"))
            self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in f["subject"] + f["why"]))

    def test_ids_content_stable_across_runs(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [x](missing.md)"})
        ids1 = [f["id"] for f in _run(repo)["findings"]]
        ids2 = [f["id"] for f in _run(repo)["findings"]]
        self.assertEqual(ids1, ids2)
        # bare content-hash ids (mint_finding_id): the scan tag carries the rule id
        self.assertTrue(all(len(i) == 8 for i in ids1))

    def test_deterministic_order(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "see [x](missing.md)\n- [ ] t\n"})
        res = _run(repo)
        keys = [(f["severity"], f["scan"], f["subject"]) for f in res["findings"]]
        self.assertEqual(keys, sorted(keys))

    def test_all_green_is_heartbeat(self):
        repo = _mk_repo(**{"docs/reference/b.md": FM + "fine\n"})
        res = _run(repo)
        self.assertEqual(res["findings"], [])
        self.assertTrue(res["meta"]["heartbeat"])


class FailClosedTest(unittest.TestCase):
    def tearDown(self):
        _reap_tmp()
    def test_missing_repo_root_raises(self):
        with self.assertRaises(DocMechError):
            run_doc_mech("/no/such/dir-t261006-11")

    def test_unreadable_page_degrades(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "a"})
        (repo / "docs" / "reference" / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        res = _run(repo)
        self.assertIn("doc-m1-index", _scans(res))   # scan continues past the bad page

    def test_notes_library_without_docs_dir(self):
        repo = Path(tempfile.mkdtemp(prefix="docmech-notes-"))
        _write(repo, "notes/x.md", FM + "x")
        res = _run(repo)
        self.assertEqual(res["meta"]["pages_scanned"], 1)


class ExemptHelperTest(unittest.TestCase):
    def test_collect_family_prefix(self):
        self.assertEqual(collect_exemptions("<!-- doc-exempt: doc-m1, doc-m2-unreachable -->"),
                         {"doc-m1", "doc-m2-unreachable"})


class ActivityShellTest(unittest.TestCase):
    """IO shell (activities.run_inspection_doc_mech): input gate, predicates, no_diff."""

    def setUp(self):
        import activities
        self.activities = activities
        self.repo = _mk_repo(**{"docs/reference/a.md": FM + "fine\n"})

    def tearDown(self):
        _reap_tmp()

    def _run(self, **kw):
        import asyncio
        return asyncio.run(self.activities.run_inspection_doc_mech(kw))

    def test_missing_base_dir_fails_closed(self):
        res = self._run(base_dir="")
        self.assertFalse(res["ok"])
        res = self._run(base_dir="/no/such/dir-t261006-11")
        self.assertFalse(res["ok"])

    def test_no_diff_scan_ok(self):
        res = self._run(base_dir=str(self.repo), no_diff=True, project_key="sandbar")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertTrue(res["result"]["meta"]["heartbeat"])
        self.assertFalse(res["result"]["meta"]["diff_rules_ran"])

    def test_ticket_predicate_resolves_project_archive(self):
        """The predicate resolves <projects_root>/<key>/data/tickets/<id> — the
        shared.ticket_data_dir convention — with a shape-gated key."""
        import asyncio
        from activities import run_inspection_doc_mech as shell
        # direct predicate behavior via the scan: plant a new line naming the ticket
        repo = _mk_repo(**{"docs/reference/a.md": FM + "ref t261006-11\n"})
        projects = repo.parent / "projects-fake"
        (projects / "sandbar" / "data" / "tickets" / "t261006-11").mkdir(parents=True,
                                                                         exist_ok=True)
        import os
        old = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(projects)
        try:
            res = asyncio.run(shell({"base_dir": str(repo), "no_diff": True,
                                     "project_key": "sandbar",
                                     "added_lines": {"docs/reference/a.md": {8: "t261006-11"}},
                                     "base_head": "x"}))
        finally:
            if old is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old
        self.assertTrue(res["ok"], res.get("error"))
        # existing ticket → no finding
        self.assertNotIn("doc-m5-ticket",
                         [f["scan"] for f in res["result"]["findings"]])


if __name__ == "__main__":
    unittest.main()
