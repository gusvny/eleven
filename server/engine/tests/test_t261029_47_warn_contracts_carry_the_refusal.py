#!/usr/bin/env python3
"""The resolver keeps refusing by name, and the warn-only call sites fold that refusal
into their receipts (ticket t261029-47, KI-415 fallout of t261029-42).

t261029-42 removed the silent REPO_ROOT fallback: `_lane_repo_root` now REFUSES a path
it cannot place. That strictness is correct and stays. What broke in the line round at
2a2eaa6d was the other half: activities whose documented contract is "return a receipt,
never raise" let the refusal escape (teardown turned it into `ok=False`, settle surfaced
it without its own refusal wording), and two integration cases went red although the
product behavior they guard was never meant to change.

The battery below is the contract, from the outside:

  1  the resolver itself still refuses by name — a direct call raises the NAMED type
     (a RuntimeError, so every existing handler keeps working) carrying the path and
     both checks, and the scope list every merge/settle/check call site builds on top
     of it refuses the same way (nothing was blanket-caught);
  2  the warn-only arms of the same fault answer with a receipt/value, not an
     exception, and the reader still learns the real reason:
       - teardown of a tree that no longer exists = target state already achieved:
         ok=True / action=teardown / EMPTY error (a false alarm over a tree that does
         not exist would be a lie, and the refusal text is in the log);
       - teardown of a tree that still exists = a leftover it could not remove: ok=True
         / action=teardown / error CARRIES the refusal text, and the tree is untouched
         (an unplaceable path is never deleted on a guess);
       - the settle ownership guard's skip arm returns its documented empty note;
       - dependency linking skips a lane it cannot place instead of raising inside
         prepare_workspace;
       - settle_lane, whose contract IS to fail loudly, raises the settle refusal with
         the resolver's text carried inside it (loud, and the reader sees which check
         failed).

Fixtures are temp dirs only; the container reclaim is stubbed so no docker call can
leave this test, and no git repository is created where git is not needed.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_activities as aa  # noqa: E402
from shared import MergeArgs, SettleLaneArgs  # noqa: E402


@pytest.fixture
def no_container(monkeypatch):
    """Teardown's container reclaim stubbed: zero docker calls, and the receipt arm still
    runs it (the returned note is empty, as the host runtime's is)."""
    calls = []

    def _stub(ticket_id, log=None):
        calls.append(ticket_id)
        return ""

    monkeypatch.setattr(aa.agent_runtime, "remove_container", _stub)
    return calls


def _plain_dir(tmp_path: Path, name: str = "stray-lane") -> Path:
    """A directory outside the lane convention that is not a git repo root: exactly the
    shape the resolver refuses."""
    p = tmp_path / name
    p.mkdir()
    return p


# ---------- 1: the refusal is still the resolver's own, by name ----------

def test_direct_resolver_call_still_refuses_by_name(tmp_path):
    plain = _plain_dir(tmp_path)

    with pytest.raises(aa.LaneRootRefusal) as exc:
        aa._lane_repo_root(plain)
    text = str(exc.value)
    assert str(plain) in text, "the refusal must name the path it was given: %r" % text
    assert "not under .lane/.worktrees" in text
    assert "is not a git repo root" in text
    # the type is a RuntimeError on purpose: every existing handler keeps its behavior
    assert isinstance(exc.value, RuntimeError)


def test_the_scope_list_under_every_check_still_refuses(tmp_path):
    """Not blanket-caught: the enumeration merge/merge_check/settle build on refuses the
    same path, so the loud call sites still fail loudly."""
    plain = _plain_dir(tmp_path, "not-a-lane")

    with pytest.raises(aa.LaneRootRefusal):
        aa._lane_scopes(plain)


# ---------- 2a: teardown, gone tree = target state already achieved ----------

def test_teardown_of_a_gone_tree_is_the_silent_receipt(tmp_path, no_container):
    """The ghost input: the path never existed. Nothing is left to remove, so the
    receipt is silent — and the strictness is intact (a direct call would refuse)."""
    ghost = tmp_path / "ghost-lane"
    with pytest.raises(aa.LaneRootRefusal):
        aa._lane_repo_root(ghost)                     # the resolver still refuses it

    res = asyncio.run(aa.teardown_lane(MergeArgs(
        ticket_id="ut47a", worktree=str(ghost), branch="lane/ut47a")))

    assert res.ok is True, res.error
    assert res.action == "teardown"
    assert (res.error or "") == "", res.error        # no false alarm over a gone tree
    assert no_container == ["ut47a"], "the container reclaim still runs on the warn arm"
    assert not ghost.exists()


# ---------- 2b: teardown, leftover tree = named, not destroyed ----------

def test_teardown_of_a_leftover_tree_names_the_refusal(tmp_path, no_container):
    """A tree still on disk that the resolver cannot place: the receipt carries the
    refusal text, the activity stays ok=True (a leftover never blocks a close-out), and
    the directory is NOT removed (an owner repo was never named)."""
    leftover = _plain_dir(tmp_path, "leftover-lane")
    (leftover / "keep.txt").write_text("evidence\n", "utf-8")

    res = asyncio.run(aa.teardown_lane(MergeArgs(
        ticket_id="ut47b", worktree=str(leftover), branch="lane/ut47b")))

    assert res.ok is True, res.error
    assert res.action == "teardown"
    assert "not under .lane/.worktrees" in (res.error or ""), res.error
    assert str(leftover) in (res.error or ""), res.error
    assert (leftover / "keep.txt").read_text("utf-8") == "evidence\n", \
        "an unplaceable tree must not be deleted on a guess"
    assert no_container == ["ut47b"]


# ---------- 2c: the settle-side warn/skip arms ----------

def test_settle_guard_skip_arm_returns_its_empty_note(tmp_path):
    """The per-stage settle of a workspace that is not a git tree answers its documented
    empty note (nothing to settle) instead of raising the resolver's refusal."""
    plain = _plain_dir(tmp_path, "isolated-ws")

    assert aa._settle_worktree_lane(plain, "ut47c", "implement", 1, face="agent") == ""


def test_dependency_link_skips_a_lane_it_cannot_place(tmp_path, monkeypatch):
    """Dependency linking is a skip arm (a foreign lane gets nothing linked out): a
    refused path must not raise inside prepare_workspace."""
    engine = tmp_path / "engine"
    engine.mkdir()
    monkeypatch.setattr(aa, "REPO_ROOT", engine)
    plain = _plain_dir(tmp_path, "unplaceable-lane")

    assert aa._ensure_lane_deps(plain) == ""
    assert not (plain / "server").exists()


# ---------- 2d: settle_lane keeps failing loudly, with the reason ----------

def test_settle_lane_raises_the_settle_refusal_carrying_the_reason(tmp_path):
    """settle_lane's contract IS to fail loudly (a silent fallback to the main tree is
    the t260901-16 fake green). It re-raises — with the resolver's own reason inside the
    message, so the reader sees which check failed."""
    gone = tmp_path / "gone" / "lane"

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(aa.settle_lane(SettleLaneArgs(
            ticket_id="ut47d", worktree=str(gone), stage_id="implement", gen=1)))

    text = str(exc.value)
    # copy-lang-allow:fixture — the refusal word the t260901-16 scenario keys on
    assert "拒绝回退" in text, \
        "the settle refusal must name the refused fallback: %r" % text
    assert "not under .lane/.worktrees" in text, \
        "the resolver's reason must reach the reader: %r" % text
    assert str(gone) in text, text
