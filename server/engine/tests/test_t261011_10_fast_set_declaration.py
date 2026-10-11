"""t261011-10 L1: `parse_fast_set_declaration` truth table (pure parser).

The parser reads the executor's declared `--print-fast-set` output shape
(members + budget + REFUSED face). Malformed input must be a LOUD
LineDeclarationError — never guessed into an empty set; a REFUSED declaration
is never an empty legitimate set.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import develop_line as dl  # noqa: E402
import pytest  # noqa: E402


def _decl_output(*names, budget=2):
    lines = ["FAST_SET_DECLARATION members=%d budget_min=%d" % (len(names), budget),
             "FAST_SET_BUDGET headroom, not a target"]
    for n in names:
        lines.append("  member %s pool=ro serial=no measured=0.42s fast-catch: x" % n)
    lines.append('FAST_SET_ESTIMATE {"wall_s": 2.2}')
    return "\n".join(lines) + "\n"


def test_happy_two_members():
    d = dl.parse_fast_set_declaration(_decl_output("sc-a", "sc-b"))
    assert d.members == ["sc-a", "sc-b"]
    assert d.budget_min == 2
    assert d.refusals == []


def test_refused_face_is_not_an_empty_set():
    out = ("REFUSED [__fast_set__] fast-set member on the known-red roster: sc-a\n"
           "FAST_SET_DECLARATION refused (1 named errors) — nothing ran\n")
    d = dl.parse_fast_set_declaration(out)
    assert d.members == []
    assert len(d.refusals) == 1
    assert "sc-a" in d.refusals[0]


def test_refused_lines_before_header_still_win():
    # A refused face has no usable header; refusals must be detected even
    # though a members=0 header line follows.
    out = ("REFUSED [__fast_set__] boom\n"
           "FAST_SET_DECLARATION refused (1 named errors) — nothing ran\n")
    d = dl.parse_fast_set_declaration(out)
    assert d.refusals and d.members == [] and d.budget_min == 0


def test_empty_string_is_loud():
    with pytest.raises(dl.LineDeclarationError):
        dl.parse_fast_set_declaration("")


def test_whitespace_only_is_loud():
    with pytest.raises(dl.LineDeclarationError):
        dl.parse_fast_set_declaration("   \n  \n")


def test_non_string_is_loud():
    with pytest.raises(dl.LineDeclarationError):
        dl.parse_fast_set_declaration(None)
    with pytest.raises(dl.LineDeclarationError):
        dl.parse_fast_set_declaration(b"bytes not text")


def test_header_absent_is_loud():
    out = "  member sc-a pool=ro measured=0.1s fast-catch: x\n"
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration(out)
    assert "header absent" in str(ei.value)


def test_member_line_without_name_is_not_counted_loud():
    # A "member" line carrying no name is not counted as a member, so the
    # header count no longer matches the body — a LOUD mismatch, never a
    # silent half fast set.
    out = ("FAST_SET_DECLARATION members=1 budget_min=2\n"
           "  member \n")
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration(out)
    assert "count mismatch" in str(ei.value)


def test_garbage_budget_is_loud():
    out = _decl_output("sc-a").replace("budget_min=2", "budget_min=two")
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration(out)
    assert "malformed" in str(ei.value)


def test_missing_budget_is_loud():
    out = _decl_output("sc-a").replace(" budget_min=2", "")
    with pytest.raises(dl.LineDeclarationError):
        dl.parse_fast_set_declaration(out)


def test_zero_budget_is_loud():
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration(_decl_output("sc-a", budget=0))
    assert "out of range" in str(ei.value)


def test_count_mismatch_is_loud():
    out = _decl_output("sc-a", "sc-b").replace("members=2", "members=1")
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration(out)
    assert "count mismatch" in str(ei.value)


def test_duplicate_member_is_loud():
    out = _decl_output("sc-a", "sc-a")
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration(out)
    assert "duplicate" in str(ei.value)


def test_error_carries_excerpt():
    with pytest.raises(dl.LineDeclarationError) as ei:
        dl.parse_fast_set_declaration("total garbage line\n")
    assert "garbage" in str(ei.value)
