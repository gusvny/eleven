"""t261006-12: review ledger and the least-recently-reviewed slice unit tests
(inspection_review_ledger.py).

Coverage (ticket L1-L5 + plan table R1 borrowed-implementation failure modes,
item by item):
- L1 ledger: missing file = everything unreviewed (never an error); corrupt
  rows / torn trailing line / non-dict / bad path / bad ts dropped line by line
  and counted; last row per path wins; non-UTF-8 bytes (replacement-char
  damage) do not crash;
- paths: override > SANDBAR_REVIEW_LEDGER_DIR > project directory; hostile
  project_key (`..`, separators, dot-prefix, NUL, empty) rejected by name;
  empty env = unset;
- L2 slice: never-reviewed first (path ascending) -> oldest ts -> path
  ascending (tie rule); slice_max cap; inventory < slice_min reviews in full
  with a note; min>max clamps with a note; deterministic (same input, same
  output);
- coverage (L5): reviewed and not-reviewed as **full lists** (never a count
  only), disjoint, counts self-consistent, the statement says "not reviewed is
  not no problem";
- L3/L4 write-back: one batched append, re-readable afterwards (last wins); a
  write failure (path = directory) is a note, never raises; empty list / no
  path = named skip;
- managed inventory: excluded trees, symlinks skipped, missing dir = empty
  list (no whole-repo fallback);
- scope assembly: slice_rows join the scope list (meta["slice"]); None = the
  old form byte-for-byte;
- declaration: review_slice accepts true/false only; slice_min/max positive
  integers, non-positive rejected; defaults None/0.

Run: PYTHONPYCACHEPREFIX=.sandbar/pycache server/engine/.venv/bin/python -B -m \\
    pytest server/engine/tests/test_t261006_12_review_ledger.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_review_ledger as rl  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_decl as decl  # noqa: E402


# ========================================================================================
# Path derivation (failure modes 1/2/9)
# ========================================================================================

def test_validate_path_component_rejects_hostile_keys():
    for bad in ("", "  ", None, "a/b", "a\\b", "..", ".", ".hidden", "x\0y"):
        ok, _ = rl.validate_path_component(bad)
        assert not ok, "hostile project_key %r must be rejected" % (bad,)
    ok, reason = rl.validate_path_component("sandbar")
    assert ok and reason == ""


def test_ledger_path_priority_override_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv(rl.REVIEW_LEDGER_ENV, str(tmp_path / "env.jsonl"))
    p, note = rl.review_ledger_path("sandbar", override=str(tmp_path / "ovr.jsonl"))
    assert note == "" and p.name == "ovr.jsonl"


def test_ledger_path_env_beats_projects_root(monkeypatch, tmp_path):
    monkeypatch.setenv(rl.REVIEW_LEDGER_ENV, str(tmp_path / "env.jsonl"))
    p, note = rl.review_ledger_path("sandbar")
    assert note == "" and p == tmp_path / "env.jsonl"


def test_ledger_path_projects_root_and_empty_env_is_unset(monkeypatch, tmp_path):
    monkeypatch.setenv(rl.PROJECTS_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(rl.REVIEW_LEDGER_ENV, "   ")   # whitespace = unset (mode 1)
    p, note = rl.review_ledger_path("sandbar")
    assert note == ""
    assert p == tmp_path / "sandbar" / "inspection" / "reviewed.jsonl"


def test_ledger_path_hostile_key_named_not_raised():
    p, note = rl.review_ledger_path("../evil")
    assert p is None and "project_key" in note


# ========================================================================================
# Ledger read (failure modes 3/4/5/6/7/10)
# ========================================================================================

def test_load_missing_ledger_is_everything_unreviewed(tmp_path):
    rows, notes = rl.load_review_ledger(tmp_path / "absent.jsonl")
    assert rows == {}
    assert "absent" in notes.get("ledger_note", "")


def test_load_torn_and_corrupt_lines_dropped_and_counted(tmp_path):
    p = tmp_path / "reviewed.jsonl"
    good = json.dumps({"path": "a.py", "period": "20261006", "ts": 1.0})
    p.write_text(good + "\n{torn last line\nnot json\n[1,2]\n", encoding="utf-8")
    rows, notes = rl.load_review_ledger(p)
    assert rows == {"a.py": {"period": "20261006", "ts": 1.0}}
    assert notes["ledger_corrupt_lines"] == 3


def test_load_rejects_malformed_rows(tmp_path):
    p = tmp_path / "reviewed.jsonl"
    lines = [
        json.dumps({"path": "x\0y", "period": "p", "ts": 1.0}),   # NUL path
        json.dumps({"period": "p", "ts": 1.0}),                    # missing path
        json.dumps({"path": "a.py", "ts": 1.0}),                   # missing period
        json.dumps({"path": "a.py", "period": "p"}),               # missing ts
        json.dumps({"path": "a.py", "period": "p", "ts": True}),   # bool is not a ts
        json.dumps({"path": "a.py", "period": "p", "ts": "x"}),    # non-numeric ts
        json.dumps(["not", "a", "dict"]),                          # non-dict row
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows, notes = rl.load_review_ledger(p)
    assert rows == {} and notes["ledger_corrupt_lines"] == len(lines)


def test_load_last_row_wins_per_path(tmp_path):
    p = tmp_path / "reviewed.jsonl"
    p.write_text(
        json.dumps({"path": "a.py", "period": "20261005", "ts": 1.0}) + "\n" +
        json.dumps({"path": "a.py", "period": "20261006", "ts": 2.0}) + "\n",
        encoding="utf-8")
    rows, _ = rl.load_review_ledger(p)
    assert rows["a.py"]["period"] == "20261006"


def test_load_non_utf8_bytes_degrade_not_crash(tmp_path):
    p = tmp_path / "reviewed.jsonl"
    p.write_bytes(b'{"path": "\xff\xfe", "period": "p", "ts": 1.0}\n')
    rows, notes = rl.load_review_ledger(p)   # replacement chars; either a parsed
    # garbage-path row or a corrupt-row count — must never raise
    assert isinstance(rows, dict) and isinstance(notes, dict)


def test_load_unreadable_path_is_a_named_note(tmp_path):
    rows, notes = rl.load_review_ledger(tmp_path)   # a directory, not a file
    assert rows == {} and "unreadable" in notes.get("ledger_note", "")


# ========================================================================================
# Managed inventory and slice (L2)
# ========================================================================================

def _make_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    for n in ("b.py", "a.py", "c.py"):
        (tmp_path / "src" / n).write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "r.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "junk.log").write_text("x\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x\n", encoding="utf-8")
    try:
        (tmp_path / "link.py").symlink_to(tmp_path / "src" / "a.py")
    except OSError:
        pass
    return tmp_path


def test_enumerate_managed_files_excludes_and_sorts(tmp_path):
    base = _make_tree(tmp_path)
    files = rl.enumerate_managed_files(base)
    assert "src/a.py" in files and "docs/r.md" in files
    assert not any(f.startswith("out/") or f.startswith("node_modules/") for f in files)
    assert not any(f.startswith("link") for f in files), "symlinks are not managed files"
    assert files == sorted(files)


def test_enumerate_missing_dir_is_empty_not_all(tmp_path):
    assert rl.enumerate_managed_files(tmp_path / "nope") == []
    assert rl.enumerate_managed_files(None) == []


def test_select_slice_order_never_reviewed_then_oldest():
    managed = ["a.py", "b.py", "c.py", "d.py"]
    ledger = {"b.py": {"period": "p1", "ts": 10.0},
              "c.py": {"period": "p0", "ts": 5.0},
              "d.py": {"period": "p0", "ts": 5.0}}   # ts tie -> path asc
    s, notes = rl.select_slice(managed, ledger, slice_min=2, slice_max=4)
    assert s == ["a.py", "c.py", "d.py", "b.py"]
    assert notes["never_reviewed"] == 1 and notes["total_managed"] == 4


def test_select_slice_caps_at_max_and_is_deterministic():
    managed = ["f%02d.py" % i for i in range(100)]
    s1, _ = rl.select_slice(managed, {}, slice_min=40, slice_max=60)
    s2, _ = rl.select_slice(managed, {}, slice_min=40, slice_max=60)
    assert len(s1) == 60 and s1 == s2


def test_select_slice_small_inventory_reviews_all_with_note():
    managed = ["a.py", "b.py"]
    s, notes = rl.select_slice(managed, {}, slice_min=40, slice_max=60)
    assert s == ["a.py", "b.py"]
    assert "below slice_min" in notes.get("slice_note", "")


def test_select_slice_min_gt_max_clamps_with_note():
    s, notes = rl.select_slice(["a.py", "b.py", "c.py"], {}, slice_min=3, slice_max=1)
    assert len(s) == 3 and "clamped" in notes.get("slice_clamped", "")


# ========================================================================================
# Coverage (L5: lists, not counts)
# ========================================================================================

def test_coverage_returns_full_lists_not_only_counts():
    cov = rl.coverage_section(["b.py", "a.py", "b.py"], ["a.py", "b.py", "c.py"], "20261006")
    assert cov["reviewed_files"] == ["a.py", "b.py"]           # deduped + sorted
    assert cov["not_reviewed_files"] == ["c.py"]               # full list, not a count
    assert cov["reviewed_count"] + cov["not_reviewed_count"] == cov["total_managed"] == 3
    assert cov["period"] == "20261006"
    assert "not reviewed is not" in cov["statement"]
    assert not (set(cov["reviewed_files"]) & set(cov["not_reviewed_files"]))


def test_coverage_counts_are_derived_from_lists():
    cov = rl.coverage_section([], ["a.py"], "p")
    assert cov["reviewed_files"] == [] and cov["reviewed_count"] == 0
    assert cov["not_reviewed_files"] == ["a.py"] and cov["not_reviewed_count"] == 1


# ========================================================================================
# Write-back (L3/L4)
# ========================================================================================

def test_append_then_reload_roundtrip(tmp_path):
    p = tmp_path / "sandbar" / "inspection" / "reviewed.jsonl"
    notes = rl.append_reviewed(p, ["a.py", "b.py"], "20261006", ts=7.0)
    assert notes.get("ledger_written") == 2
    rows, _ = rl.load_review_ledger(p)
    assert rows["a.py"] == {"period": "20261006", "ts": 7.0}
    # A second period reviews the same path again: last row wins (rotation advances)
    rl.append_reviewed(p, ["a.py"], "20261007", ts=8.0)
    rows, _ = rl.load_review_ledger(p)
    assert rows["a.py"]["period"] == "20261007"


def test_append_failure_is_a_note_never_raises(tmp_path):
    d = tmp_path / "is-a-dir"
    d.mkdir()
    notes = rl.append_reviewed(d, ["a.py"], "p")
    assert "append failed" in notes.get("write_note", "")


def test_append_no_path_or_no_files_is_named_skip():
    assert "skipped" in rl.append_reviewed(None, ["a.py"], "p").get("write_note", "")
    assert "skipped" in rl.append_reviewed("/tmp/x.jsonl", [], "p").get("write_note", "")


def test_append_drops_malformed_file_names(tmp_path):
    p = tmp_path / "reviewed.jsonl"
    notes = rl.append_reviewed(p, ["ok.py", "", "  ", "bad\0name", None], "p")
    assert notes.get("ledger_written") == 1


# ========================================================================================
# Scope assembly (the slice joins the scope list; None = old form unchanged)
# ========================================================================================

def test_scope_block_with_slice_rows_and_meta():
    block, meta = ins.build_change_scope_text(
        ["M\ta.py"], [], [], {}, "", 4, 40,
        slice_rows=["s1.py", "s2.py"],
        slice_notes={"never_reviewed": 2, "ledger_note": "absent"})
    assert "Review-rotation slice" in block and "- s1.py" in block and "- s2.py" in block
    assert meta["slice"]["files"] == ["s1.py", "s2.py"]
    assert meta["slice"]["never_reviewed"] == 2
    assert "ledger_note" in block   # the input-face note is visible in the slice section


def test_scope_block_without_slice_is_byte_identical_to_old_form():
    a, ma = ins.build_change_scope_text(["M\ta.py"], ["suite red"], ["KI-1 open"], {}, "prev", 4, 40)
    b, mb = ins.build_change_scope_text(["M\ta.py"], ["suite red"], ["KI-1 open"], {}, "prev", 4, 40,
                                        slice_rows=None, slice_notes=None)
    assert a == b and ma == mb
    assert "Review-rotation slice" not in a


# ========================================================================================
# Declaration surface (review_slice / slice_min / slice_max)
# ========================================================================================

_DECL_TMPL = ("schema: v1\n"
              "instances:\n"
              "  - id: simplify-face\n"
              "    enabled: true\n"
              "    project_key: sandbar\n"
              "%s"
              "    schedule:\n"
              "      kind: cron\n"
              "      cron: 30 9 * * *\n"
              "    workflow: InspectionPeriodicWorkflow\n"
              "    template: inspection-lite\n")


def _parse(tmp_path, extra: str):
    p = tmp_path / "inspection.yaml"
    p.write_text(_DECL_TMPL % extra, "utf-8")
    return decl.load_inspection_decl(p)


def test_decl_review_slice_keys_parse(tmp_path):
    d = _parse(tmp_path, "    review_slice: true\n    slice_min: 50\n    slice_max: 60\n")
    it = d.instance("simplify-face")
    assert it.review_slice is True and it.slice_min == 50 and it.slice_max == 60
    plan = decl._plan_from_decl(d, "simplify-face")
    assert plan["ok"] is True
    assert plan["inspect"]["review_slice"] is True
    assert plan["inspect"]["slice_min"] == 50 and plan["inspect"]["slice_max"] == 60


def test_decl_review_slice_defaults_are_unset(tmp_path):
    d = _parse(tmp_path, "")
    it = d.instance("simplify-face")
    assert it.review_slice is None and it.slice_min == 0 and it.slice_max == 0


@pytest.mark.parametrize("extra", [
    "    review_slice: yes\n",
    "    slice_min: 0\n",
    "    slice_min: -3\n",
    "    slice_max: abc\n",
    "    slice_max: 0\n",
])
def test_decl_bad_review_keys_fail_closed(tmp_path, extra):
    with pytest.raises(decl.DeclError):
        _parse(tmp_path, extra)


def test_decl_unknown_keys_still_rejected(tmp_path):
    with pytest.raises(decl.DeclError):
        _parse(tmp_path, "    review_slices: true\n")
