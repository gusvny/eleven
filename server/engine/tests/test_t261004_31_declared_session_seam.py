# -*- coding: utf-8 -*-
"""t261004-31 - unit tests for the declared-executor-session seam
(caller_gate.resolve_identity new tier).

Root cause this closes: this project's (sandbar) main directory IS the engine repo
tree, so its named executor session's repo-tree cwd used to resolve to src=none
forever — the grants were never gated (all writes passed exempt), the action ledger
was never written, and the panel Recent actions block was empty by construction.
The seam: cwd under an exclude tree + ignoring the exclusion the cwd still resolves
to exactly one registered project + the caller session id named in that project's
executor_sessions => declared (src="declared-session"). The C1 repo-tree exclusion
red line is unchanged for the unnamed, the session-less, and ambiguous hits. Pure
function calls only, zero environment dependencies.
"""
from pathlib import Path

import pytest

import caller_gate

# Mirrored shape of "the project main directory sits inside the engine repo tree":
# sandbar's registered directory = the repo tree itself (this ticket's root cause).
PROJ = [{"key": "sandbar", "dirs": ["/repo"]}]
TREE = ("/repo",)


def _resolve(cwd, sessions_by_key=None, session="", projects=PROJ, trees=TREE):
    return caller_gate.resolve_identity(
        "", "", cwd=cwd, exclude_trees=trees, projects=projects,
        caller_session=session, declared_sessions_by_key=sessions_by_key or {})


def test_seam_fires_for_named_session_under_repo_tree():
    out = _resolve("/repo", {"sandbar": ("sess-exec-1",)}, "sess-exec-1")
    assert out == {"value": "sandbar", "src": "declared-session",
                   "identity_class": "declared"}


def test_seam_fires_for_subdirectory_of_repo_tree():
    out = _resolve("/repo/server/engine", {"sandbar": ("s",)}, "s")
    assert out["src"] == "declared-session" and out["value"] == "sandbar"


def test_seam_silent_when_session_absent():
    # Fail-closed (review #3): no session id => the seam stays closed, still undeclared.
    out = _resolve("/repo", {"sandbar": ("s",)}, "")
    assert out == {"value": "", "src": "none", "identity_class": "undeclared"}


def test_seam_silent_when_session_not_named():
    out = _resolve("/repo", {"sandbar": ("s",)}, "sess-other")
    assert out == {"value": "", "src": "none", "identity_class": "undeclared"}


def test_seam_silent_when_declaration_absent_or_malformed():
    # Declaration absent (empty map) => the seam stays closed; a malformed file is
    # already folded into an empty list at the loading layer (client-side discipline).
    assert _resolve("/repo", {}, "s")["src"] == "none"


def test_seam_silent_when_cwd_hits_no_project_even_if_named():
    # The cwd hits no registered project even ignoring the exclusion => no project
    # anchor, the seam stays closed.
    out = _resolve("/somewhere-else", {"sandbar": ("s",)}, "s")
    assert out["src"] == "none"


def test_seam_silent_on_ambiguous_multi_project_cwd():
    # Ignoring the exclusion, several registered projects match (overlapping prefixes)
    # => longest-prefix still picks a single anchor; two equal-length identical dirs are
    # impossible (registry keys are unique). This locks the longest-prefix single-anchor
    # semantics.
    projects = [{"key": "sandbar", "dirs": ["/repo"]},
                {"key": "sandbar-docs", "dirs": ["/repo/docs"]}]
    out = _resolve("/repo/docs", {"sandbar": ("s",), "sandbar-docs": ("s",)}, "s",
                   projects=projects)
    assert out["src"] == "declared-session" and out["value"] == "sandbar-docs"


def test_seam_not_consulted_when_cwd_outside_exclude_trees():
    # The cwd hits normally (not inside an exclude tree) => the original cwd channel,
    # src stays "cwd" (the seam never takes over the main channel).
    projects = [{"key": "dengzhufpv", "dirs": ["/work/dz"]}]
    out = _resolve("/work/dz", {"dengzhufpv": ("s",)}, "s",
                   projects=projects, trees=("/repo",))
    assert out == {"value": "dengzhufpv", "src": "cwd", "identity_class": "declared"}


def test_arg_and_env_still_win_over_seam():
    out = caller_gate.resolve_identity(
        "sandbar", "", cwd="/repo", exclude_trees=TREE, projects=PROJ,
        caller_session="s", declared_sessions_by_key={"sandbar": ("s",)})
    assert out["src"] == "arg" and out["value"] == "sandbar"
    out = caller_gate.resolve_identity(
        "", "dengzhufpv", cwd="/repo", exclude_trees=TREE, projects=PROJ,
        caller_session="s", declared_sessions_by_key={"sandbar": ("s",)})
    assert out["src"] == "env" and out["value"] == "dengzhufpv"


def test_registry_missing_means_seam_absent_not_crash():
    out = _resolve("/repo", {"sandbar": ("s",)}, "s", projects=None)
    assert out["src"] == "none"


def test_legacy_call_signature_unchanged():
    # The legacy call face (without the new parameters) behaves byte-for-byte the
    # same: the repo-tree exclusion as before, the seam absent as a whole.
    out = caller_gate.resolve_identity("", "", cwd="/repo",
                                       exclude_trees=TREE, projects=PROJ)
    assert out == {"value": "", "src": "none", "identity_class": "undeclared"}


def test_is_executor_channel_declared_session_gated():
    import executor_grants as eg
    assert eg.is_executor_channel("declared-session", "", ("s",), "s") is True
    # empty session id: fail-closed (review #3)
    assert eg.is_executor_channel("declared-session", "", ("s",), "") is False
    # session not named: False
    assert eg.is_executor_channel("declared-session", "", ("s",), "x") is False
    # declaration absent: False
    assert eg.is_executor_channel("declared-session", "", (), "s") is False
