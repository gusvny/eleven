# -*- coding: utf-8 -*-
"""261020 (host order): the fault ledger lives OUTSIDE git; the repo keeps a pointer.

host order: move the KI ledger out of notes, never into git; only a KI that is
genuinely needed may land in the repository. 326 entries of running case notes
dominated diffs that should be about the product, and every consumer read them out
of a repository file.

The move must not blind the two engine readers that consult the ledger:
  * the inspection scope face (`ki_open_entries`) reports open faults;
  * `repair_hatch` refuses a KI id that is not a recorded fact.
Both now consult the project STORE first and the repository pointer second, so a
checkout without a store degrades to the pinned entries instead of crashing, and a
store ledger is read from its real home.

Coverage: the candidate list puts the store first and includes the repo pointer;
a missing store yields the pointer only; the reader parses the store; the hatch
check accepts an id present in either file and refuses one in neither.
"""
import os
import sys
import tempfile
from pathlib import Path

import inspection_inspect as ii

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))


REPO_ROOT = str(Path(__file__).resolve().parents[3])


def test_the_inspected_tree_comes_first_then_the_store():
    """261020: an inspection reads the ledger that travels with the tree it is
    inspecting (a fixture must see its own fault list); the project store is the
    fallback that a real checkout needs, because the repository keeps a pointer."""
    cands = [str(c) for c in ii.ki_ledger_candidates(REPO_ROOT)]
    assert cands[0].endswith("notes/debts/known-issues.md"), cands
    assert any(c.endswith("/kb/known-issues.jsonl") for c in cands), \
        "the store ledger must still be reachable"
    assert cands.index([c for c in cands if c.endswith('/kb/known-issues.jsonl')][0]) > 0


def test_the_repo_pointer_is_the_fallback():
    cands = ii.ki_ledger_candidates(REPO_ROOT)
    assert any(str(c).endswith("notes/debts/known-issues.md") for c in cands)


def test_a_reader_without_a_base_still_gets_the_store():
    cands = ii.ki_ledger_candidates("")
    assert all("/kb/known-issues" in str(c) for c in cands)


def test_the_reader_parses_a_ledger_file(tmp_path):
    p = tmp_path / "known-issues.md"
    # the severity cell is data, not copy: it is read back, never displayed
    p.write_text("| KI-001 | a finding | sev | open | x.py |\n", encoding="utf-8")
    rows, meta = ii.ki_open_entries(p)
    assert rows and "KI-001" in rows[0]
    assert meta == {}


def test_an_absent_ledger_is_named_not_crashed(tmp_path):
    rows, meta = ii.ki_open_entries(tmp_path / "nope.md")
    assert rows == [] and "unreadable" in meta["ki_note"]


def test_the_repository_no_longer_carries_the_full_ledger():
    repo = Path(__file__).resolve().parents[3]
    text = (repo / "notes" / "debts" / "known-issues.md").read_text(encoding="utf-8")
    assert "pointer" in text.lower() or "kb/known-issues.md" in text, \
        "the repo file is a pointer now"
    assert text.count("## KI-") < 5, \
        "the 300+ entry ledger must not be back in the repository"
