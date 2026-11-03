"""UT for the doc-face mechanical layer (M1-M7) — t261006-11.

Truth-table discipline (lexical-constant rule 10): every rule fires / does not
fire on a planted fixture, including the review-pinned cases:
  - S10-fixed resolution: a path that resolves under the repo root but NOT under
    the document's own directory MUST fire (no repo-root fallback);
  - glob shapes (*.d.ts) are never treated as paths;
  - historical face (docs/design) does not fire for path drift;
  - malformed inputs (broken index.json, unreadable page, bogus diff paths) degrade
    with meta caveats, never crash, never fake green;
  - ids are content-stable across two identical runs (mint_finding_id);
  - SCHEMA-AWARE frontmatter (host ruling 261029): a docs/epics/ page is judged by
    the epic schema (code / retired / summary, code == file stem) and a malformed
    epic page is still a named finding — never an exemption;
  - catalogue ROWS are resolved, never blindly docs/-prefixed (host ruling 261029):
    a bare row resolves into the docs sub-directory that holds it, a repository-root
    row is a non-library reference, a genuinely missing row still fires, and an
    ambiguous bare name is never guessed away.
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

import docs_index  # noqa: E402  (t261103-12: the derived documentation index)
import docs_roots  # noqa: E402  (t261103-12: the ONE roots resolution)
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


EPIC_FM = "---\ncode: {code}\nretired: {retired}\nsummary: one sentence.\n---\n\n"


def _epic_findings(res):
    return [f for f in res["findings"] if f["scan"] == "doc-m1-frontmatter-epic"]


class EpicSchemaTest(unittest.TestCase):
    """Host ruling 261029: docs/epics/ keeps ITS OWN frontmatter schema
    (code / retired / summary, docs/design/epic-registry-v1.md). The checker
    learns it — and a malformed epic page is still a named finding."""

    def tearDown(self):
        _reap_tmp()

    def _repo_with_epic(self, text: str):
        repo = _mk_repo(**{"docs/epics/alpha.md": text})
        idx = json.loads((repo / "docs" / "index.json").read_text())
        for d in idx["docs"]:
            d["category"] = "epics" if d["path"].startswith("epics/") else "reference"
        (repo / "docs" / "index.json").write_text(json.dumps(idx), encoding="utf-8")
        return repo

    def test_well_formed_epic_page_passes_both_rules(self):
        repo = self._repo_with_epic(
            EPIC_FM.format(code="alpha", retired="false") + "# alpha\n")
        scans = _scans(_run(repo))
        self.assertNotIn("doc-m1-frontmatter", scans)        # five fields never demanded
        self.assertNotIn("doc-m1-frontmatter-epic", scans)

    def test_code_not_matching_stem_is_named(self):
        repo = self._repo_with_epic(
            EPIC_FM.format(code="beta", retired="false") + "# alpha\n")
        epic = _epic_findings(_run(repo))
        self.assertEqual(len(epic), 1)
        self.assertIn("does not match the file stem", epic[0]["subject"])

    def test_missing_summary_and_bad_retired_are_named(self):
        repo = self._repo_with_epic(
            "---\ncode: alpha\nretired: partly\n---\n\n# alpha\n")
        epic = _epic_findings(_run(repo))
        self.assertEqual(len(epic), 1)
        self.assertIn("summary empty", epic[0]["subject"])
        self.assertIn("not true/false", epic[0]["subject"])

    def test_epic_page_without_frontmatter_is_named_not_exempted(self):
        epic = _epic_findings(_run(self._repo_with_epic("# alpha\n")))
        self.assertEqual(len(epic), 1)
        self.assertIn("missing or unterminated frontmatter block", epic[0]["subject"])

    def test_indexed_epic_needs_no_readme_catalogue_row(self):
        repo = self._repo_with_epic(
            EPIC_FM.format(code="alpha", retired="true") + "# alpha\n")
        (repo / "docs" / "README.md").write_text(
            FM + "# docs index\n\n| `docs/README.md` | x |\n", encoding="utf-8")
        self.assertNotIn("doc-m1-readme", _scans(_run(repo)))


class ReadmeRowResolutionTest(unittest.TestCase):
    """Host ruling 261029 (c): a catalogue row is RESOLVED, never blindly
    prefixed with docs/ — the README writes some rows from the section they sit
    in and some from the repository root."""

    def tearDown(self):
        _reap_tmp()

    def _readme(self, repo, body: str):
        (repo / "docs" / "README.md").write_text(FM + "# docs index\n\n" + body,
                                                 encoding="utf-8")

    def test_bare_row_resolves_into_a_docs_subdirectory(self):
        repo = _mk_repo(**{"docs/reference/writing-standard.md": FM + "std"})
        self._readme(repo, "| `docs/README.md` | x |\n| `writing-standard.md` | std |\n")
        self.assertNotIn("doc-m1-readme", _scans(_run(repo)))

    def test_repository_root_rows_are_not_catalogue_rows(self):
        repo = _mk_repo(**{"docs/reference/a.md": FM + "a",
                           "notes/README.md": "# notes\n"})
        (repo / "CLAUDE.md").write_text("# entry\n", encoding="utf-8")
        self._readme(repo, "| `docs/README.md` | x |\n| `docs/reference/a.md` | a |\n\n"
                           "The ledger is `notes/README.md`; the root `CLAUDE.md` is the entry.\n")
        self.assertNotIn("doc-m1-readme", _scans(_run(repo)))

    def test_missing_row_still_fires(self):
        repo = _mk_repo()
        self._readme(repo, "| `docs/README.md` | x |\n| `design/gone.md` | gone |\n")
        self.assertIn("doc-m1-readme", _scans(_run(repo)))

    def test_ambiguous_bare_row_is_never_guessed(self):
        repo = _mk_repo(**{"docs/reference/dup.md": FM + "r",
                           "docs/design/dup.md": FM + "d"})
        self._readme(repo, "| `docs/README.md` | x |\n| `dup.md` | ambiguous |\n")
        rows = [f for f in _run(repo)["findings"]
                if f["scan"] == "doc-m1-readme" and "does not exist" in f["subject"]]
        self.assertEqual([f["evidence"][0]["quote"] for f in rows], ["docs/dup.md"])


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
        # t261009-69: the mint widened 8 -> 16 hex (collision-margin ruling)
        self.assertTrue(all(len(i) == 16 for i in ids1))

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
        # t261103-11 (design docs/design/project-docs-roots-v1.md goal 4): a tree
        # with no documentation root and no declaration used to be scanned as an
        # empty library (green heartbeat = "no documents" and "documents not
        # found" reading alike). That state is now a NAMED refusal that says
        # what was looked for; the notes/ library is not a substitute root.
        import docs_roots
        repo = Path(tempfile.mkdtemp(prefix="docmech-notes-"))
        _write(repo, "notes/x.md", FM + "x")
        with self.assertRaises(DocMechError) as ctx:
            _run(repo)
        msg = str(ctx.exception)
        self.assertIn(docs_roots.STOP_ABSENT, msg)
        self.assertIn("docs", msg)          # names the path that was looked for


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

# ========================================================================
# t261103-12 — the derived documentation index (docs/design/project-docs-roots-v1.md)
#
# The index + presentation half: ONE declaration (`paths.docs_roots` inside the project
# declaration the engine and the console both read), ONE resolution
# (`docs_roots.project_roots`, the same module the gate half owns and this half extends),
# one scan over the resolved roots, and the derived index in the project's data
# directory with its four reader states. Every fixture uses a temp projects root.
# ========================================================================


def _registry_entry(perkey: Path, key: str, dirs: list, paths_block: str = "") -> Path:
    """One project declaration in the real shape (`paths:` holds the roots block)."""
    perkey.mkdir(parents=True, exist_ok=True)
    body = ("schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n%s\n"
            % (key, key, "".join("      - %s\n" % d for d in dirs)))
    if paths_block:
        body += "paths:\n" + paths_block
    target = perkey / "project.yaml"
    target.write_text(body, encoding="utf-8")
    return target


def _roots_block(entries) -> str:
    """`paths:` content for the given (repository, path, projections) entries."""
    out = "  docs_roots:\n"
    for entry in entries:
        repo, path = entry[0], entry[1]
        projections = entry[2] if len(entry) > 2 else ""
        out += "    - repository: %s\n      path: %s\n" % (repo, path)
        if projections:
            out += "      projections: %s\n" % projections
    return out


class DocsRootsDeclarationTests(unittest.TestCase):
    """The ONE declaration + resolution: `paths.docs_roots`, project scope."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="docsroots-ut-"))
        _TMP_DIRS.append(self.root)
        self.projects = self.root / "projects"
        self.repo = self.root / "repo-a"
        (self.repo / "docs").mkdir(parents=True)

    def _entry(self, dirs: list = None, block: str = "", key: str = "proj") -> Path:
        dirs = dirs if dirs is not None else [str(self.repo)]
        return _registry_entry(self.projects / key, key, dirs, block)

    # ---- truth table -------------------------------------------------

    def test_undeclared_project_gets_the_implied_default_root(self):
        self._entry()
        _write(self.repo, "docs/design/a.md", FM + "a\n")
        res = docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(res.source, "implied")
        self.assertEqual(res.paths(), ("docs",))
        self.assertEqual(res.roots[0].directory, self.repo / "docs")
        self.assertEqual(res.projections(), ())     # no declaration = no projection

    def test_undeclared_and_no_docs_directory_is_a_named_refusal(self):
        self._entry()
        (self.repo / "docs").rmdir()
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(cm.exception.code, docs_roots.STOP_ABSENT)
        self.assertIn("paths.docs_roots", cm.exception.message)
        self.assertIn(str(self.repo / "docs"), cm.exception.message)

    def test_one_declared_non_default_root(self):
        (self.repo / "kb").mkdir()
        _write(self.repo, "kb/x.md", FM + "x\n")
        self._entry(block=_roots_block([(".", "kb")]))
        res = docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(res.source, "declared")
        self.assertEqual(res.paths(), ("kb",))
        self.assertEqual(res.roots[0].directory, self.repo / "kb")

    def test_many_declared_roots_keep_order_and_identities(self):
        """`repository` is relative to the project root (the entry's first dirs item)."""
        repo_b = self.repo / "repo-b"
        (repo_b / "handbook").mkdir(parents=True)
        (self.repo / "handbook").mkdir()
        self._entry(block=_roots_block([(".", "handbook"), ("repo-b", "handbook")]))
        res = docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(len(res.roots), 2)
        self.assertEqual([r.repository or "." for r in res.roots], [".", "repo-b"])
        ids = {r.identity for r in res.roots}
        self.assertEqual(len(ids), 2)         # equal relative paths never share identity

    def test_declared_root_absent_is_refused_not_empty(self):
        self._entry(block=_roots_block([(".", "moved")]))
        with self.assertRaises(docs_roots.DocsRootsStop) as cm:
            docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(cm.exception.code, docs_roots.STOP_ROOT_ABSENT)
        self.assertIn("moved", cm.exception.message)
        self.assertIn("project.yaml", cm.exception.declaration)

    def test_declared_empty_root_is_served_but_empty(self):
        (self.repo / "kb").mkdir()
        _write(self.repo, "kb/notes.txt", "not a page\n")
        self._entry(block=_roots_block([(".", "kb")]))
        res = docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(res.paths(), ("kb",))
        self.assertEqual(docs_roots.root_state(res.roots[0]), docs_roots.ROOT_STATE_EMPTY)
        _write(self.repo, "kb/page.md", FM + "p\n")
        self.assertEqual(docs_roots.root_state(res.roots[0]), docs_roots.ROOT_STATE_SERVED)

    def test_malformed_declarations_are_refused_with_location(self):
        cases = {
            "unknown projection": _roots_block([(".", "kb", "vectors")]),
            "absolute path": "  docs_roots:\n    - repository: .\n      path: /etc\n",
            "parent segment": "  docs_roots:\n    - repository: .\n      path: ../out\n",
            "whole repository": "  docs_roots:\n    - repository: .\n      path: .\n",
            "unknown entry key": "  docs_roots:\n    - repo: .\n      path: kb\n",
            "missing path": "  docs_roots:\n    - repository: .\n",
            "no entries": "  docs_roots:\n",
            "duplicate root": ("  docs_roots:\n    - repository: .\n      path: kb\n"
                               "    - repository: .\n      path: kb\n"),
        }
        (self.repo / "kb").mkdir(exist_ok=True)
        for label, block in cases.items():
            with self.subTest(label):
                self._entry(block=block)
                with self.assertRaises(docs_roots.DocsRootsStop) as cm:
                    docs_roots.project_roots("proj", projects_root_dir=self.projects)
                self.assertIn(cm.exception.code,
                              (docs_roots.STOP_DECLARATION_MALFORMED,
                               docs_roots.STOP_DUPLICATE), label)
                self.assertIn("docs_roots", cm.exception.message + cm.exception.code, label)

    def test_projections_are_declared_per_root_and_default_off(self):
        (self.repo / "kb").mkdir(exist_ok=True)
        self._entry(block=_roots_block([(".", "docs"), (".", "kb", "entries,fulltext")]))
        res = docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(res.projections(), ("entries", "fulltext"))

    def test_the_old_sibling_declaration_file_is_ignored(self):
        """One declaration only: a stray docs_roots.yaml must change nothing."""
        (self.projects / "proj").mkdir(parents=True, exist_ok=True)
        (self.projects / "proj" / "docs_roots.yaml").write_text(
            "schema: v1\ndocs_roots:\n  - repo: /elsewhere\n    path: kb\n", encoding="utf-8")
        self._entry()
        _write(self.repo, "docs/a.md", FM + "a\n")
        res = docs_roots.project_roots("proj", projects_root_dir=self.projects)
        self.assertEqual(res.source, "implied")
        self.assertEqual(res.paths(), ("docs",))

    def test_index_home_is_the_project_data_directory(self):
        home = docs_roots.index_dir("proj", self.projects)
        self.assertEqual(home, self.projects / "proj" / "data" / "docs")
        self.assertFalse(str(home).startswith(str(self.repo)))


class DocsIndexBuilderTests(unittest.TestCase):
    """The builder: one scan over the resolved roots -> the project's data directory."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="docsindex-ut-"))
        _TMP_DIRS.append(self.root)
        self.projects = self.root / "projects"
        self.repo = self.root / "repo-a"
        (self.repo / "docs").mkdir(parents=True)
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)])

    def _declare(self, entries) -> None:
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)],
                        _roots_block(entries))

    def test_categories_come_from_the_documents(self):
        """No fixed category subdirectories: the walk covers the whole root."""
        _write(self.repo, "docs/anything/page.md",
               "---\ntitle: P\ncategory: ops\nstatus: active\nupdated: 2026-11-01\n---\nbody\n")
        _write(self.repo, "docs/root-page.md",
               "---\ntitle: R\ncategory: reference\nstatus: active\nupdated: 2026-11-01\n---\nr\n")
        payload = docs_index.build(
            docs_roots.project_roots("proj", projects_root_dir=self.projects))
        self.assertEqual(payload["total"], 2)
        self.assertEqual(sorted(d["category"] for d in payload["docs"]), ["ops", "reference"])
        self.assertEqual(sorted(payload["categories"]), ["ops", "reference"])
        self.assertIn("anything/page.md", [d["path"] for d in payload["docs"]])

    def test_index_lands_in_the_project_data_directory_not_the_repository(self):
        _write(self.repo, "docs/a.md", FM + "a\n")
        res = docs_index.rebuild("proj", self.projects, trigger="inspection")
        self.assertTrue(res["ok"], res.get("reason"))
        index_path = self.projects / "proj" / "data" / "docs" / "index.json"
        self.assertTrue(index_path.is_file())
        self.assertFalse((self.repo / "docs" / "index.json").exists())
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], docs_index.SCHEMA)
        self.assertEqual(payload["total"], 1)
        self.assertTrue(payload["built_at"])
        self.assertEqual(payload["roots"][0]["repository"], ".")

    def test_many_roots_merge_without_shadowing(self):
        repo_b = self.repo / "repo-b"
        (repo_b / "kb").mkdir(parents=True)
        _write(self.repo, "docs/same.md", FM + "left\n")
        _write(repo_b, "kb/same.md", FM + "right\n")
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)],
                        _roots_block([(".", "docs"), ("repo-b", "kb")]))
        payload = docs_index.build(
            docs_roots.project_roots("proj", projects_root_dir=self.projects))
        self.assertEqual(payload["total"], 2)
        self.assertEqual(len({d["id"] for d in payload["docs"]}), 2)

    def test_moved_root_rebuilds_from_the_new_place(self):
        _write(self.repo, "docs/old.md", FM + "old\n")
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        (self.repo / "kb").mkdir()
        _write(self.repo, "kb/new.md", FM + "new\n")
        self._declare([(".", "kb")])
        result = docs_index.rebuild("proj", self.projects)
        self.assertTrue(result["ok"], result.get("reason"))
        payload = json.loads((self.projects / "proj" / "data" / "docs" / "index.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual([d["path"] for d in payload["docs"]], ["new.md"])
        self.assertNotEqual(payload["total"], 0)

    def test_projections_are_off_by_default_and_on_when_declared(self):
        _write(self.repo, "docs/a.md", FM + "a body\n")
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        data = self.projects / "proj" / "data" / "docs"
        self.assertFalse((data / "entries.json").exists())
        self.assertFalse((data / "fulltext.json").exists())
        self._declare([(".", "docs", "entries,fulltext")])
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        entries = json.loads((data / "entries.json").read_text(encoding="utf-8"))
        fulltext = json.loads((data / "fulltext.json").read_text(encoding="utf-8"))
        self.assertEqual(entries["total"], 1)
        self.assertEqual(entries["entries"][0]["root"], ".:docs")
        self.assertIn("a body", fulltext["docs"][0]["text"])
        self._declare([(".", "docs")])          # withdrawing the declaration
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        self.assertFalse((data / "entries.json").exists())
        self.assertFalse((data / "fulltext.json").exists())

    def test_unreadable_page_degrades_alone(self):
        _write(self.repo, "docs/good.md", FM + "good\n")
        (self.repo / "docs" / "bad.md").write_bytes(b"---\ntitle: \xff\xfe\n---\n")
        payload = docs_index.build(
            docs_roots.project_roots("proj", projects_root_dir=self.projects))
        self.assertEqual([d["path"] for d in payload["docs"]], ["good.md"])
        self.assertEqual([r["path"] for r in payload["review"]["unreadable"]], ["bad.md"])


class DocsIndexReaderStateTests(unittest.TestCase):
    """The four reader states, told apart, and the read path that never writes."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="docsread-ut-"))
        _TMP_DIRS.append(self.root)
        self.projects = self.root / "projects"
        self.repo = self.root / "repo"
        (self.repo / "docs").mkdir(parents=True)
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)])
        _write(self.repo, "docs/a.md", FM + "a\n")

    def test_absent_before_any_build(self):
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_ABSENT)
        self.assertEqual(read.entries, [])
        # the roots are still known: "no index yet" is not "no documents"
        self.assertEqual(len(read.roots_now), 1)

    def test_current_after_a_build(self):
        built = docs_index.rebuild("proj", self.projects)
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_CURRENT)
        self.assertEqual(read.built_at, built["built_at"])
        self.assertEqual([d["path"] for d in read.entries], ["a.md"])

    def test_stale_names_the_last_build_time(self):
        built = docs_index.rebuild("proj", self.projects)
        page = self.repo / "docs" / "a.md"
        later = float(built["built_at_ts"]) + 60
        os.utime(page, (later, later))
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_STALE)
        self.assertEqual(read.built_at, built["built_at"])
        self.assertIn("newer than the build", read.stale_reason)

    def test_stale_when_the_roots_changed_since_the_build(self):
        """A moved root leaves the old index stale, never looking current."""
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        (self.repo / "kb").mkdir()
        _write(self.repo, "kb/b.md", FM + "b\n")
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)],
                        _roots_block([(".", "kb")]))
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_STALE)
        self.assertIn("roots in effect changed", read.stale_reason)

    def test_failed_is_named_and_serves_no_old_entries(self):
        """A failed rebuild is named with its reason; the old index is not served."""
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        data = self.projects / "proj" / "data" / "docs"
        (data / "rebuild-failed.json").write_text(json.dumps(
            {"schema": "v1", "project": "proj", "failed_at_ts": 9e12,
             "code": "docs_index_rebuild_failed",
             "reason": "permission denied writing index"}), encoding="utf-8")
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_FAILED)
        self.assertIn("permission denied", read.reason)
        self.assertEqual(read.entries, [])
        self.assertNotEqual(read.state, docs_index.ST_ABSENT)

    def test_a_refused_declaration_is_failed_not_an_empty_library(self):
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)],
                        _roots_block([(".", "gone")]))
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_FAILED)
        self.assertEqual(read.code, docs_roots.STOP_ROOT_ABSENT)
        self.assertIn("gone", read.reason)
        # a rebuild records the same refusal and never writes an empty library
        built = docs_index.rebuild("proj", self.projects)
        self.assertFalse(built["ok"])
        self.assertEqual(built["state"], docs_index.ST_FAILED)
        self.assertFalse((self.projects / "proj" / "data" / "docs" / "index.json").exists())

    def test_read_path_never_writes(self):
        """Every writer raises; the reader still answers (read path is write-free)."""
        self.assertTrue(docs_index.rebuild("proj", self.projects)["ok"])
        data = self.projects / "proj" / "data" / "docs"
        before = sorted(p.name for p in data.iterdir())

        def boom(*_a, **_k):
            raise AssertionError("the read path must never write")

        old_write, old_rebuild = docs_index._write_json, docs_index.rebuild
        docs_index._write_json = boom
        docs_index.rebuild = boom
        try:
            read = docs_index.read_index("proj", self.projects)
        finally:
            docs_index._write_json, docs_index.rebuild = old_write, old_rebuild
        self.assertEqual(read.state, docs_index.ST_CURRENT)
        self.assertEqual(sorted(p.name for p in data.iterdir()), before)

    def test_absent_stays_absent_on_read(self):
        """Reading must not create the index directory either."""
        read = docs_index.read_index("proj", self.projects)
        self.assertEqual(read.state, docs_index.ST_ABSENT)
        self.assertFalse((self.projects / "proj" / "data" / "docs").exists())


class DocsIndexInspectionTriggerTests(unittest.TestCase):
    """The documentation inspection is the ONLY automatic writer; nothing else writes."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="docstrigger-ut-"))
        _TMP_DIRS.append(self.root)
        self.projects = self.root / "projects"
        self.repo = self.root / "repo"
        (self.repo / "docs").mkdir(parents=True)
        _write(self.repo, "docs/a.md", FM + "a\n")
        _registry_entry(self.projects / "proj", "proj", [str(self.repo)])

    def test_pass_without_the_hook_does_not_write(self):
        run_doc_mech(str(self.repo))
        self.assertFalse((self.projects / "proj" / "data").exists())

    def test_pass_with_the_hook_records_and_writes(self):
        res = run_doc_mech(str(self.repo),
                           index_rebuild=lambda: docs_index.inspection_rebuild(
                               "proj", self.projects))
        self.assertTrue((self.projects / "proj" / "data" / "docs" / "index.json").is_file())
        self.assertEqual(res["meta"]["docs_index"]["state"], docs_index.ST_CURRENT)
        self.assertEqual(res["meta"]["docs_index"]["trigger"], "inspection")

    def test_a_failing_rebuild_is_recorded_not_raised(self):
        def boom():
            raise RuntimeError("disk full")

        res = run_doc_mech(str(self.repo), index_rebuild=boom)
        self.assertEqual(res["meta"]["docs_index"]["state"], "failed")
        self.assertIn("disk full", res["meta"]["docs_index"]["reason"])

    def test_activity_shell_rebuilds_only_when_asked(self):
        """The IO shell wires the writer only for a run that opted in (and a valid key)."""
        import asyncio

        from activities import run_inspection_doc_mech as shell
        old = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(self.projects)
        try:
            off = asyncio.run(shell({"base_dir": str(self.repo), "no_diff": True,
                                     "project_key": "proj"}))
            self.assertNotIn("docs_index", off["result"]["meta"])
            self.assertFalse((self.projects / "proj" / "data").exists())
            on = asyncio.run(shell({"base_dir": str(self.repo), "no_diff": True,
                                    "project_key": "proj", "docs_index_rebuild": True}))
            self.assertEqual(on["result"]["meta"]["docs_index"]["state"],
                             docs_index.ST_CURRENT)
            self.assertTrue((self.projects / "proj" / "data" / "docs" / "index.json")
                            .is_file())
        finally:
            if old is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old


if __name__ == "__main__":
    unittest.main()


# ======================================================================
# t261103-11 — docs roots (1/2): the scan root comes from the ONE declaration
# (design docs/design/project-docs-roots-v1.md goals 2 and 4). Contract:
#   - a project that declares nothing and owns docs/ scans docs/ exactly as
#     before (the implied default root, reported as "implied", never declared);
#   - a declared root is scanned, and the old directory name is NOT (a moved
#     root must not scan nothing, and must not keep scanning the old place);
#   - many roots in one repository are all scanned;
#   - a declared root that is absent is a NAMED refusal, not a green empty scan.
# ======================================================================

class DocsRootFollowsDeclarationTest(unittest.TestCase):
    """The scan follows `paths.docs_roots`; nothing here touches a real registry."""

    FM = "---\ntitle: t\ncategory: reference\ntags:\n  - x\nstatus: active\nupdated: 2026-11-03\n---\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="docmech-roots-"))
        _TMP_DIRS.append(self.tmp)
        self.projects = self.tmp / "projects"
        self.repo = self.tmp / "tree"
        self.repo.mkdir(parents=True)
        self._old_env = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(self.projects)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = self._old_env

    def declaration(self, block):
        d = self.projects / "probe"
        d.mkdir(parents=True, exist_ok=True)
        (d / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: probe\n    name: probe\n    dirs:\n"
            "      - %s\npaths:\n%s" % (self.repo, block), encoding="utf-8")

    def library(self, root, pages):
        """A minimal library at `root`: index + README + the given pages."""
        (self.repo / root).mkdir(parents=True, exist_ok=True)
        index = {"docs": [{"path": rel}
                          for rel in sorted(set(pages) | {"README.md"})]}
        (self.repo / root / "index.json").write_text(json.dumps(index),
                                                     encoding="utf-8")
        rows = "\n".join("| `%s` | x |" % rel
                         for rel in sorted(set(pages) | {"README.md"}))
        _write(self.repo, root + "/README.md", self.FM + "# index\n" + rows + "\n")
        for rel, text in pages.items():
            _write(self.repo, root + "/" + rel, self.FM + text)

    def scans(self, res):
        return [f["scan"] for f in res["findings"]]

    def subjects(self, res):
        """The evidence paths a finding points at (the agent finding shape keeps
        the path inside evidence[]; `subject` is the human sentence)."""
        return [e.get("path") for f in res["findings"] for e in f["evidence"]]

    def test_default_off_scans_the_implied_root(self):
        self.library("docs", {"reference/a.md": "a\n"})
        res = run_doc_mech(str(self.repo))
        self.assertEqual(res["meta"]["docs_roots"]["source"], "implied")
        self.assertEqual(res["meta"]["pages_scanned"], 2)   # README + the page
        self.assertEqual(res["findings"], [])

    def test_declared_root_is_the_one_scanned(self):
        self.library("guide", {"reference/a.md": "a\n"})
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "stale.md").write_text(self.FM + "s\n", encoding="utf-8")
        self.declaration("  docs_roots:\n    - repository: .\n      path: guide\n")
        # an unregistered page in the declared root: M1 must fire on it
        _write(self.repo, "guide/reference/extra.md", self.FM + "e\n")
        res = run_doc_mech(str(self.repo), project_key="probe")
        self.assertEqual(res["meta"]["docs_roots"]["source"], "declared")
        self.assertIn("doc-m1-index", self.scans(res))
        self.assertIn("guide/reference/extra.md", self.subjects(res))
        # the old directory name is prose content now: it is not this library
        self.assertFalse([s for s in self.subjects(res) if s.startswith("docs/")])

    def test_many_declared_roots_are_all_scanned(self):
        self.library("guide", {"reference/a.md": "a\n"})
        self.library("manual", {"reference/b.md": "b\n"})
        self.declaration("  docs_roots:\n"
                         "    - repository: .\n      path: guide\n"
                         "    - repository: .\n      path: manual\n")
        _write(self.repo, "guide/reference/extra.md", self.FM + "e\n")
        _write(self.repo, "manual/reference/extra.md", self.FM + "e\n")
        res = run_doc_mech(str(self.repo), project_key="probe")
        self.assertEqual(len(res["meta"]["docs_roots"]["roots"]), 2)
        subjects = self.subjects(res)
        self.assertIn("guide/reference/extra.md", subjects)
        self.assertIn("manual/reference/extra.md", subjects)

    def test_declared_but_absent_root_is_a_named_refusal(self):
        self.library("docs", {"reference/a.md": "a\n"})
        self.declaration("  docs_roots:\n    - repository: .\n      path: moved\n")
        with self.assertRaises(DocMechError) as cm:
            run_doc_mech(str(self.repo), project_key="probe")
        self.assertIn("docs_roots_root_absent", str(cm.exception))
        self.assertIn("moved", str(cm.exception))

    def test_explicit_root_argument_wins_for_ops_callers(self):
        self.library("guide", {"reference/a.md": "a\n"})
        res = run_doc_mech(str(self.repo), docs_root="guide")
        self.assertEqual(res["meta"]["docs_roots"]["source"], "argument")
        self.assertEqual(res["meta"]["pages_scanned"], 2)
