#!/usr/bin/env python3
"""t260924 inspection teardown honesty — regression battery.

Host order 260924 ("fix all of it"): the inspection round's teardown lied. This
file is the regression rod for that incident (accident rule: one fix, one rod).

  rod 1  budget mismatch: the review budget defaulted to 60 minutes (the root of
         the 260923/260924 timeouts that ended in empty shells).
  rod 2  teardown verified + idempotence spelled out: the lane teardown stopped
         reporting a fake "already clean" (a surviving directory shell is NAMED)
         and the idempotent shapes ("is not a working tree" / "not found") no
         longer report a failure that did not happen.
  rod 3  the sweep recognises directory shells: ``sweep_inspection_lanes``
         collects the bare-shell shape and refuses to tear down a shell that
         contains an unregistered nested repository.
  rod 4  agent_home lane anchor: the ``sanitize_agent_home`` pure-function
         matrix.

SHAPE: this file is a real pytest battery (it used to be a module-level script
that called ``sys.exit`` at import, so pytest reported INTERNALERROR and the
rod was read by no gate at all). Every check below is a test now; run
``python3 -m pytest integration/tests/test_t260924_inspection_teardown_honesty.py``.

Re-pinned by t261028-14 (KI-387 sweep) — two pins had drifted, and BOTH were
stale pins, not product defects (the guarded behaviour is intact):
  - "清扫认裸目录壳 + 三态守卫接线" locked the Chinese refusal text
    「未注册嵌套仓形态」; t261004-36 put code comments and copy in English and the
    text is now "unregistered nested-repo shape". The case now locks the SEAM
    (the same seam is still one line of behaviour): the guard runs BEFORE the
    removal, and the refusal names the embedded repo.
  - "agent_home 守卫唯一接线点" locked ``count == 1``; t260925-01 added the second
    producer (the produce round) with the same guard, so the rule is now "every
    agent_home producer is guarded" — the counts must MATCH, which is what it
    asserts. A third producer without the guard reds it.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
ENG = ROOT / "server" / "engine"
sys.path.insert(0, str(ENG))

from inspection_inspect import (  # noqa: E402
    DEFAULT_INSPECT_TIMEOUT_MIN,
    INSPECT_DEADLINE_MARGIN_SEC,
    sanitize_agent_home,
    stub_embedded_repo,
    sweep_stub_dir_names,
)

ENGINE_SRC = (ENG / "agent_activities.py").read_text(encoding="utf-8")
FLOW_SRC = (ENG / "inspection_flow.py").read_text(encoding="utf-8")
FALLBACK = pathlib.Path("/fallback/agent-home")


# ------------------------------------------------------- rod 1: review budget

def test_review_budget_default_is_sixty_minutes():
    """The 260924 fix raised the default; the timeouts of 260923/260924 were
    caused by a budget that expired before the review could finish."""
    assert DEFAULT_INSPECT_TIMEOUT_MIN == 60


def test_review_budget_exceeds_the_deadline_margin():
    """Inequality shape, not a number: the budget must stay above the margin
    the re-check needs, whatever either value becomes."""
    assert DEFAULT_INSPECT_TIMEOUT_MIN * 60 > INSPECT_DEADLINE_MARGIN_SEC


# ------------------------------------- rod 2/3: the teardown source locks

def test_idempotent_teardown_shapes_stay_silent():
    """"Already gone" is not a failure: both idempotent shapes must stay
    swallowed rather than reported as a red."""
    assert '"is not a working tree" not in err' in ENGINE_SRC
    assert '"not found" not in err' in ENGINE_SRC


def test_teardown_names_a_surviving_directory_shell():
    """The fake "already clean": after the teardown every tree is re-checked on
    disk, and a shell that survived is NAMED instead of being reported as gone."""
    assert "目录壳残留：%s（worktree 登记/分支已清；目录未除）" in ENGINE_SRC
    assert ENGINE_SRC.count("removed_dir_stubs") >= 1


def test_flow_renders_the_shell_count():
    """The read side: the fall-back rendering consumes removed_dir_stubs and
    names how many shells survived."""
    assert FLOW_SRC.count("removed_dir_stubs") >= 2
    assert "目录壳 %d" in FLOW_SRC


def test_sweep_collects_bare_shells_behind_the_nested_repo_guard():
    """Bare directory shells (a directory no git record knows about) are
    collected, and the three-state guard runs BEFORE any removal: a shell that
    embeds a repository is refused and named, never destroyed silently.

    The words in that refusal are copy and may be translated; the SEAM is the
    assertion here — guard first, ``shutil.rmtree`` only after it, and the
    refusal names the embedded repo (t260916-20 discipline)."""
    assert ("from inspection_inspect import stub_embedded_repo, sweep_stub_dir_names"
            in ENGINE_SRC)
    guard = ENGINE_SRC.index("bad = stub_embedded_repo(cand)")
    removal = ENGINE_SRC.index("shutil.rmtree(cand)")
    assert guard < removal, "the nested-repo guard must run before any removal"
    assert "unregistered nested-repo shape" in ENGINE_SRC, \
        "a refused shell must be named (the nested-repo shape)"
    assert "removed_dir_stubs.append" in ENGINE_SRC, \
        "a removed shell must reach the receipt"


def test_every_agent_home_producer_goes_through_the_guard():
    """rod 4's wiring rule, in its current form.

    The rule was "exactly one wiring point" while the inspect round was the only
    producer. t260925-01 added the produce round as a second producer with the
    same guard, so the rule is now equality: every sanitize call carries the
    agent_home it guards, and no producer creates the home behind its back."""
    guarded = ENGINE_SRC.count("sanitize_agent_home(")
    created = ENGINE_SRC.count("home.mkdir(parents=True, exist_ok=True)")
    assert guarded >= 1
    assert guarded == created, (
        "%d agent_home producers but %d sanitize_agent_home call sites: a home "
        "would be created without the lane-anchor guard" % (created, guarded))
    assert "Path(agent_home_raw).mkdir" not in ENGINE_SRC
    assert "agent_home_raw" in ENGINE_SRC, "the raw anchor must still be reported"


# ------------------------------------------- rod 4: the pure-function matrix

def test_sanitize_agent_home_matrix():
    # an isolated /tmp bench carries no .lane segment: pass through untouched
    tmp_home = pathlib.Path("/tmp/agent-home-t260924/x")
    home, note = sanitize_agent_home(tmp_home, FALLBACK, "it-1")
    assert home == tmp_home and note == ""

    # a lane anchor (.lane segment) falls back to the main checkout, named
    lane_home = pathlib.Path(
        "/repo/.lane/inspection-integration-tests-20260924/server/engine/out/x")
    home, note = sanitize_agent_home(lane_home, FALLBACK, "it-1")
    assert home == FALLBACK / "it-1" and "泳道锚回落" in note

    # only a whole segment matches: a sibling such as ".lanefoo" is not an anchor
    sibling = pathlib.Path("/repo/lane-x/home")
    home, note = sanitize_agent_home(sibling, FALLBACK, "it-1")
    assert home == sibling and note == ""


def test_sweep_stub_dir_names_matrix():
    listing = ["inspection-integration-tests-20260924", "integration-tests-20260924",
               "inspection-integration-tests-20260925", "t260922-04", "dev-x"]
    # targeted: both shapes of THIS period, no other period, no dev lanes
    assert sweep_stub_dir_names(listing, "integration-tests", target="20260924") == [
        "inspection-integration-tests-20260924", "integration-tests-20260924"]
    # water level: shells older than the level are self-healing; this period is untouched
    assert sweep_stub_dir_names(listing, "integration-tests", keep="20260926") == [
        "inspection-integration-tests-20260924",
        "inspection-integration-tests-20260925",
        "integration-tests-20260924"]
    # no instance / both empty: nothing is judged, nothing is touched
    assert sweep_stub_dir_names(listing, "integration-tests") == []
    assert sweep_stub_dir_names(listing, "") == []
    # a malformed (non-numeric) period is not guessed at
    assert sweep_stub_dir_names(
        ["inspection-integration-tests-x1", "integration-tests-abc"],
        "integration-tests", target="20260924") == []


def test_stub_embedded_repo_three_state_matrix():
    """260926 refinement: a worktree trace, a repository root and an
    unregistered nested repository are three different states. Only the first
    and the plain-junk shell may be removed; the other two are refused by name."""
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td)
        # state 1: a top-level .git FILE is a worktree trace — the shell may go
        gitfile = t / "gitfile_stub"
        gitfile.mkdir()
        (gitfile / ".git").write_text("gitdir: ../x", encoding="utf-8")
        (gitfile / "junk.txt").write_text("x", encoding="utf-8")
        assert stub_embedded_repo(gitfile) is None
        # state 2: a top-level .git DIRECTORY is its own repository root — refused
        repo_stub = t / "repo_stub"
        repo_stub.mkdir()
        (repo_stub / ".git").mkdir()
        assert stub_embedded_repo(repo_stub) == repo_stub / ".git"
        # state 3: a nested .git is an unregistered nested repository — refused
        nested = t / "nested_stub"
        nested.mkdir()
        (nested / "sub").mkdir()
        (nested / "sub" / ".git").mkdir()
        assert stub_embedded_repo(nested) == nested / "sub" / ".git"
        # plain junk (no .git anywhere) may be removed
        bare = t / "bare_stub"
        bare.mkdir()
        (bare / "agent-home").mkdir()
        assert stub_embedded_repo(bare) is None
