#!/usr/bin/env python3
"""t261009-38 bundle-out-face carve-out unit tests (L1).

A declared build chain's output is a lawful deliverable when the ticket's own
write set covers the paired src prefix (ticket t261009-38; precedent
t261004-25). Faces under test:
  1. path_gates.parse_bundle_pairs — the single pure declaration parser
     (accept-only-the-fixed-shape, raise on broken lines, fail-closed input);
  2. path_gates.bundle_out_face — the pure predicate (evidence matrix in BOTH
     directions: src in write set -> admitted; src absent -> refused;
     declaration missing/malformed -> refused; malformed inputs -> refused);
  3. path_gates.judge_stage_paths wiring — named pass on write_set/join/
     self_heal only, named note content, no widening on other kinds;
  4. agent_activities._read_bundle_pairs_for_gate — the caller-side loader
     (absent file = lawful opt-out, silent; malformed = named diag, fail-closed)
     and the settle wiring passing the pairs through (monkeypatched judge).
No network / real Temporal / real git in UT (tmp files only).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_gates as pg  # noqa: E402

SRC = "server/plugins/workbench/src/client/"
OUT = "server/plugins/workbench/lib/"
OUT_FILE = "server/plugins/workbench/lib/client.js"
PAIRS = [(SRC, OUT)]
WS = [SRC]
GOOD_YAML = "# comment\nbundle_pairs:\n  - src: %s\n    out: %s\n" % (SRC, OUT)


# ---------------- 1. parser ----------------

def test_parse_good_file():
    assert pg.parse_bundle_pairs(GOOD_YAML) == [(SRC, OUT)]  # declared values verbatim


def test_parse_absent_section_and_comments():
    assert pg.parse_bundle_pairs("# only comments\n\nother_key: 1\n") == []


def test_parse_entry_without_out_is_dropped():
    text = "bundle_pairs:\n  - src: a/\n  - src: b/\n    out: c/\n"
    assert pg.parse_bundle_pairs(text) == [("b/", "c/")]


def test_parse_malformed_line_raises():
    with pytest.raises(ValueError):
        pg.parse_bundle_pairs("bundle_pairs:\n  - src: a/\n    bogus: x\n")


def test_parse_non_string_fail_closed():
    assert pg.parse_bundle_pairs(None) == []
    assert pg.parse_bundle_pairs(b"bundle_pairs:\n") == []


# ---------------- 2. predicate ----------------

def test_predicate_src_in_write_set_admits():
    assert pg.bundle_out_face(OUT_FILE, WS, PAIRS) == SRC.rstrip("/")


def test_predicate_src_not_in_write_set_refuses():
    assert pg.bundle_out_face(OUT_FILE, ["server/other/"], PAIRS) is None


def test_predicate_out_not_declared_refuses():
    assert pg.bundle_out_face("server/other/lib/x.js", WS, PAIRS) is None


def test_predicate_src_absent_from_declaration_refuses():
    # out prefix declared as an out with NO src in the write set: the pair whose
    # src is missing/empty never admits.
    assert pg.bundle_out_face(OUT_FILE, WS, [("", OUT)]) is None
    assert pg.bundle_out_face(OUT_FILE, WS, [(None, OUT)]) is None


def test_predicate_empty_declaration_refuses():
    assert pg.bundle_out_face(OUT_FILE, WS, []) is None
    assert pg.bundle_out_face(OUT_FILE, WS, None) is None


def test_predicate_empty_write_set_refuses_fail_closed():
    assert pg.bundle_out_face(OUT_FILE, [], PAIRS) is None
    assert pg.bundle_out_face(OUT_FILE, None, PAIRS) is None


def test_predicate_malformed_inputs_refuse():
    bad_paths = [None, "", "  ", "/abs/x", "../x", "a/../../x", "a\\b", "x?!y",
                 "./server/plugins/workbench/lib/client.js"]  # last one: equivalent spelling
    for p in bad_paths[:-1]:
        assert pg.bundle_out_face(p, WS, PAIRS) is None, p
    # equivalent spelling normalizes to the real path and IS judged (same stance
    # as the write-set match): dot-slash resolves into the declared out prefix.
    assert pg.bundle_out_face(
        "./server/plugins/workbench/lib/client.js", WS, PAIRS) == SRC.rstrip("/")
    bad_pairs = [("a"), ("a", "b", "c"), (SRC, 5), (5, OUT), (SRC, "/abs"),
                 (SRC, "a/../.."), (SRC, "")]
    for pr in bad_pairs:
        assert pg.bundle_out_face(OUT_FILE, WS, [pr]) is None, pr


def test_predicate_protected_path_still_refused_by_its_own_gate():
    # The bundle rule must not become a general escape: a protected source-of-
    # truth file is refused by judge_protected_paths regardless of declarations.
    pv, reason = pg.judge_protected_paths(["server/merge-checks.yaml"],
                                          exists_at_base=lambda p: True)
    assert pv == ["server/merge-checks.yaml"] and reason == "protected_path"


# ---------------- 3. judge wiring ----------------

def _note(rules_note):
    return rules_note


def test_judge_write_set_named_pass():
    notes: list = []
    ok, viol, reason = pg.judge_stage_paths(
        "implement", [OUT_FILE], write_set=WS, ticket_id="t261009-38",
        notes_out=notes, bundle_pairs=PAIRS)
    assert ok and not viol and reason == ""
    assert len(notes) == 1
    assert "bundle-out-face rule" in notes[0]
    assert OUT_FILE in notes[0]
    assert "src " + SRC.rstrip("/") in notes[0]


def test_judge_src_outside_write_set_refused():
    notes: list = []
    ok, viol, reason = pg.judge_stage_paths(
        "implement", [OUT_FILE], write_set=["server/other/"],
        ticket_id="t261009-38", notes_out=notes, bundle_pairs=PAIRS)
    assert not ok and viol == [OUT_FILE] and reason == "unauthorized_path"
    assert notes == []  # refusal is named by the refusal note, not a carve note


def test_judge_declaration_missing_refused():
    ok, viol, reason = pg.judge_stage_paths(
        "implement", [OUT_FILE], write_set=WS, ticket_id="t261009-38",
        bundle_pairs=None)
    assert not ok and reason == "unauthorized_path"


def test_judge_join_and_self_heal_get_fallback():
    for stage in ("integ_join", "merge_check"):
        notes: list = []
        ok, _, _ = pg.judge_stage_paths(
            stage, [OUT_FILE], write_set=WS, ticket_id="t261009-38",
            notes_out=notes, bundle_pairs=PAIRS)
        assert ok, stage
        assert notes and "bundle-out-face rule" in notes[0]


def test_judge_other_kinds_do_not_widen():
    # prefixes / result_files / ui_dirs / ticket_receipts / test_face faces keep
    # today's behaviour: the bundle rule adds nothing there.
    bad = [
        ("design_integration_tests", None),
        ("create_plan", None),
        ("ui_evidence", ("ui",)),
        ("run_integration_tests", None),
        ("arbitrate", None),
    ]
    for stage, ui in bad:
        notes: list = []
        ok, _, reason = pg.judge_stage_paths(
            stage, [OUT_FILE], write_set=WS, ticket_id="t261009-38",
            ui_dirs=ui, notes_out=notes, bundle_pairs=PAIRS)
        assert not ok, (stage, reason)
        assert reason in ("unauthorized_path", "ui_dirs_missing"), (stage, reason)
        assert notes == []


def test_judge_result_files_still_pass_and_protected_still_red_together():
    # result files pass everywhere; a protected hit still refuses even when the
    # rest of the batch is clean (refusal text keeps stage-first semantics).
    ok, _, _ = pg.judge_stage_paths(
        "implement", [".sandbar/stage_x.json"], write_set=WS, bundle_pairs=PAIRS)
    assert ok


def test_judge_default_param_byte_identical_legacy():
    # No bundle_pairs argument (legacy callers): behaviour identical to before —
    # the same file is refused exactly as the pre-ticket gate refused it.
    ok, viol, reason = pg.judge_stage_paths(
        "implement", [OUT_FILE], write_set=WS, ticket_id="t261009-38")
    assert not ok and viol == [OUT_FILE] and reason == "unauthorized_path"


def test_judge_rebuild_red_not_weakened():
    # Item 6: the src change itself must stay IN the write set to be judged at
    # all — the rule admits only the rebuilt out; a src outside the write set
    # (ticket forgot its own src) is still refused, declaration or not.
    ok, _, reason = pg.judge_stage_paths(
        "implement", ["server/plugins/workbench/src/client/app.ts"],
        write_set=["server/other/"], bundle_pairs=PAIRS)
    assert not ok and reason == "unauthorized_path"


# ---------------- 4. caller-side loader + settle wiring ----------------

def test_loader_reads_declared_pairs(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "merge-checks.yaml").write_text(GOOD_YAML)
    import agent_activities as aa
    pairs, diag = aa._read_bundle_pairs_for_gate(tmp_path)
    assert pairs == [(SRC, OUT)]
    assert diag == ""


def test_loader_absent_file_lawful_opt_out_silent(tmp_path):
    import agent_activities as aa
    pairs, diag = aa._read_bundle_pairs_for_gate(tmp_path)
    assert pairs == [] and diag == ""  # M1: no warning on the lawful opt-out


def test_loader_malformed_file_named_diag_fail_closed(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "merge-checks.yaml").write_text(
        "bundle_pairs:\n  - src: a/\n    junk_line: nope\n")
    import agent_activities as aa
    pairs, diag = aa._read_bundle_pairs_for_gate(tmp_path)
    assert pairs == []
    assert "unreadable/malformed" in diag and "merge-checks.yaml" in diag


def test_loader_none_cwd_named_diag():
    import agent_activities as aa
    pairs, diag = aa._read_bundle_pairs_for_gate(None)
    assert pairs == [] and "fail-closed" in diag


def test_merge_check_parser_delegates_to_single_source():
    # C1: one parser implementation; the activity module is a thin delegate.
    import agent_activities as aa
    assert aa._parse_bundle_pairs(GOOD_YAML) == pg.parse_bundle_pairs(GOOD_YAML)
    with pytest.raises(ValueError):
        aa._parse_bundle_pairs("bundle_pairs:\n  - src: a/\n    junk: x\n")


# ---------------- 5. merge-gate widen face (t261009-38 gen3) ----------------

def test_bundle_out_prefixes_admits_when_src_covered():
    assert pg.bundle_out_prefixes(WS, PAIRS) == [OUT.rstrip("/")]


def test_bundle_out_prefixes_refuses_when_src_not_covered():
    assert pg.bundle_out_prefixes(["server/other/"], PAIRS) == []


def test_bundle_out_prefixes_fail_closed_inputs():
    assert pg.bundle_out_prefixes([], PAIRS) == []
    assert pg.bundle_out_prefixes(None, PAIRS) == []
    assert pg.bundle_out_prefixes(WS, []) is not None and pg.bundle_out_prefixes(WS, []) == []
    assert pg.bundle_out_prefixes(WS, None) == []
    assert pg.bundle_out_prefixes(WS, [("", OUT), (SRC, 5), ("a", "b", "c")]) == []


def test_bundle_out_prefixes_dedup_keeps_order():
    pairs = [(SRC, OUT), ("srcs/other/", OUT)]
    assert pg.bundle_out_prefixes([SRC, "srcs/other/"], pairs) == [OUT.rstrip("/")]


def test_widen_helper_widens_and_names(lane_like_yaml):
    import agent_activities as aa
    eff, note = aa._bundle_widened_write_set(lane_like_yaml, WS)
    assert eff == WS + [OUT.rstrip("/")]
    assert "bundle-out-face rule" in note and OUT.rstrip("/") in note


def test_widen_helper_no_declaration_no_widening_silent(tmp_path):
    import agent_activities as aa
    eff, note = aa._bundle_widened_write_set(tmp_path, WS)
    assert eff == WS and note == ""  # lawful opt-out, no warning noise


def test_widen_helper_malformed_declaration_named_fail_closed(tmp_path):
    import agent_activities as aa
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "merge-checks.yaml").write_text(
        "bundle_pairs:\n  - src: a/\n    junk: x\n")
    eff, note = aa._bundle_widened_write_set(tmp_path, WS)
    assert eff == WS and "no widening" in note


def test_widen_helper_none_write_set_fail_closed(tmp_path):
    import agent_activities as aa
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "merge-checks.yaml").write_text(GOOD_YAML)
    eff, note = aa._bundle_widened_write_set(tmp_path, None)
    assert eff == [] and note == ""


@pytest.fixture
def lane_like_yaml(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "merge-checks.yaml").write_text(GOOD_YAML)
    return tmp_path
