"""Unit battery for the tier-admission inspection criteria (t261004-42).

The end-to-end admission rule (docs/reference/test-tiers-and-e2e-admission.md)
is enforced in three places; the inspection face is the test-face criteria list
`PROFILE_TEXTS['test']` in inspection_inspect.py — the single declared home the
inspect-agent prompt interpolates, so a reader sees one list, not two. This
battery locks:

  1. the three items A/B/C are present, labelled item by item;
  2. the never-stay-silent rule: an unanswerable item must say so and name the
     missing input;
  3. the report-only discipline: the criteria never instruct a demotion or a
     rewrite (a cleanup is its own ticket);
  4. build_inspect_prompt(face='test') carries all three labels end to end;
  5. no vocabulary drift: WIRED_FACES and PROFILE_FACES stay the same set
     (adding criteria text must not add a face).

Run: server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_t261004_42_inspect_tier_criteria.py -q
"""
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_decl as decl_mod  # noqa: E402
import inspection_inspect as inspect_mod  # noqa: E402

CRITERIA = inspect_mod.PROFILE_TEXTS["test"]


def test_three_items_present_labelled():
    for label, name in (("A.", "Demotion candidates"), ("B.", "Trend"),
                        ("C.", "Repeats")):
        assert label in CRITERIA and name in CRITERIA, (label, name)


def test_never_stay_silent_rule_present():
    assert "never" in CRITERIA and "stay silent" in CRITERIA
    assert "name the missing input" in CRITERIA


def test_report_only_discipline_present():
    # the page: the inspection reports candidates first; a cleanup is its own
    # ticket — the criteria must never instruct a demotion or a rewrite
    assert "never demote or rewrite" in CRITERIA


def test_trend_inputs_named():
    # wall time source (suite receipt) and expensive count source (SCENARIOS
    # registry) are named so the agent can answer item B
    assert "suite receipt" in CRITERIA and "SCENARIOS" in CRITERIA
    assert "10 minutes" in CRITERIA  # the page's budget threshold


def test_source_page_named():
    assert "docs/reference/test-tiers-and-e2e-admission.md" in CRITERIA


def test_prompt_carries_all_three_labels_end_to_end():
    prompt = inspect_mod.build_inspect_prompt(
        instance_id="integration-tests", period="t", face="test",
        base_dir="/tmp", base_head="h", max_findings=5)
    for token in ("A.", "B.", "C.", "Demotion candidates", "Trend", "Repeats"):
        assert token in prompt, token


def test_no_face_vocabulary_drift():
    # criteria text is not a face: adding A/B/C must not touch the face set lock
    assert set(decl_mod.WIRED_FACES) == set(inspect_mod.PROFILE_FACES)
    assert "test" in inspect_mod.PROFILE_TEXTS
