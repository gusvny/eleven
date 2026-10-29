#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261029-18 L1 battery: lane branch name resolution + the per-scope changed-file list.

Root cause this ticket fixes: a multi-repo lane's ``meta.branch`` is the placeholder
``lane/<id>`` while the root tree sits on ``lane/<id>-root``. ``changed_files`` handed
the placeholder to git, the merge-base failed, and the file-level blast radius degraded
to "run the whole suite" on every round of every such ticket.

Layers pinned here (stub git only — the unit tier forbids real git, conftest.py:5):
  1. the naming source: `shared.lane_branch` / `shared.lane_branch_candidates`
     (malformed input, the root-tree twin, no ``-root-root``, no twin for a member
     scope) plus the mint lock that keeps the suffix in one place;
  2. `_lane_branch_resolve`: first hit, the root-tree fallback trace, both miss (names
     the candidates, the refs and the merge-base it blocks; never asks the literal main);
  3. `changed_files`: the manifest-present shape (the manifest branch is used and the
     helper is not consulted), the manifest-absent shape (the twin resolves), the
     per-scope union with repo prefixes, the corrupt-manifest fail-closed red, the named
     diff/status failures with a scope tag, and the carried `-uall` face;
  4. `lane_head_sha`: the third consumer of the same placeholder (review K2 / A10);
  5. the wall-clock contract: the success path reports ``wall_s`` above zero (review C7).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402
from shared import ChangedFilesArgs  # noqa: E402

_ENGINE = Path(__file__).resolve().parents[1]
_TWIN = shared.ROOT_TREE_NAME  # "root"


def _rc(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class StubGit:
    """Answers by git verb; records every call. Never runs git.

    resolve: branch name -> bool (the ``rev-parse --verify --quiet <ref>^{commit}`` probe)
    heads:   ref -> sha (the plain ``rev-parse --verify <ref>`` probe of lane_head_sha)
    base:    branch name -> merge-base sha (absent = the name has no baseline)
    diff/status: str(cwd) -> (rc, stdout, stderr); absent = rc 0, empty output
    """

    def __init__(self, resolve=None, heads=None, base=None, diff=None, status=None,
                 delay=0.0):
        self.calls = []
        self.resolve = dict(resolve or {})
        self.heads = dict(heads or {})
        self.base = dict(base or {})
        self.diff = dict(diff or {})
        self.status = dict(status or {})
        self.delay = delay

    def verbs(self):
        return [c[0][0] for c in self.calls]

    def refs(self):
        return [c[0][-1] for c in self.calls if c[0][0] == "rev-parse"]

    def __call__(self, args, cwd, timeout=60):
        self.calls.append((list(args), str(cwd)))
        verb = args[0]
        if self.delay:
            time.sleep(self.delay)
        if verb == "rev-parse":
            if "--quiet" in args:
                assert args[-1].endswith("^{commit}"), args
                name = args[-1][:-len("^{commit}")]
                ok = bool(self.resolve.get(name))
                return _rc("deadbeef\n" if ok else "", 0 if ok else 1,
                           "" if ok else "fatal: Needed a single revision")
            sha = self.heads.get(args[-1])
            return _rc((sha + "\n") if sha else "", 0 if sha else 1,
                       "" if sha else "fatal: bad revision")
        if verb == "merge-base":
            sha = self.base.get(args[2])
            if sha is None:
                return _rc("", 128, "fatal: Not a valid object name %s" % args[2])
            return _rc(sha + "\n")
        if verb in ("diff", "status"):
            rc, out, err = getattr(self, verb).get(str(cwd), (0, "", ""))
            return _rc(out, rc, err)
        raise AssertionError("unexpected git verb: %r" % (args,))


def _lane(tmp_path, entries=None, name="t1"):
    """A lane directory; `entries` written through the engine's own manifest path."""
    lane = tmp_path / ".lane" / name
    lane.mkdir(parents=True, exist_ok=True)
    if entries is not None:
        mf = shared.multi_manifest_path(lane, create=True)
        mf.parent.mkdir(parents=True, exist_ok=True)
        mf.write_text(json.dumps(entries), encoding="utf-8")
    return lane


def _run(args):
    return asyncio.run(aa.changed_files(args))


# ---------------- 1. the naming source ----------------

def test_lane_branch_candidates_table():
    assert shared.lane_branch_candidates("lane/t1") == ["lane/t1", "lane/t1-root"]
    # no second suffix: -root-root is unrepresentable
    assert shared.lane_branch_candidates("lane/t1-root") == ["lane/t1-root"]
    # a member scope never asks for a twin
    assert shared.lane_branch_candidates("lane/t1-member", allow_root_twin=False) == \
        ["lane/t1-member"]
    # a name that is not a lane branch has no twin
    assert shared.lane_branch_candidates("feature/x") == ["feature/x"]
    # a lane segment that is not refname-safe gets no invented twin
    assert shared.lane_branch_candidates("lane/odd name") == ["lane/odd name"]
    # malformed input = no candidate (the caller treats it as fail-closed)
    for bad in (None, "", "   ", 42, [], object()):
        assert shared.lane_branch_candidates(bad) == [], bad
    # whitespace is stripped before the twin is built
    assert shared.lane_branch_candidates("  lane/t1  ") == ["lane/t1", "lane/t1-root"]


def test_naming_source_is_single():
    # the mint and the resolution agree by construction (review C4 / A8)
    assert shared.lane_branch("t1", shared.ROOT_TREE_NAME) == \
        shared.lane_branch_candidates("lane/t1")[1]
    assert shared.lane_branch("t1") == "lane/t1"
    assert shared.lane_branch("t1", "member") == "lane/t1-member"
    shared_src = (_ENGINE / "shared.py").read_text(encoding="utf-8")
    mint = shared_src.split("def build_repo_worktrees(", 1)[1].split("\ndef ", 1)[0]
    assert "lane_branch(lane_dir_name, name)" in mint
    assert "ROOT_TREE_NAME" in mint
    assert '"lane/%s-%s"' not in mint, "a second copy of the branch shape crept into the mint"
    act_src = (_ENGINE / "agent_activities.py").read_text(encoding="utf-8")
    resolve = act_src.split("def _lane_branch_resolve(", 1)[1].split("\ndef ", 1)[0]
    assert "shared.lane_branch_candidates(" in resolve
    assert '"-root"' not in resolve, "the suffix must come from shared, not a literal here"


# ---------------- 2. the resolver ----------------

def test_resolver_first_hit_and_fallback_and_miss(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    # first hit: no trace, exactly one probe
    g = StubGit(resolve={"lane/t1": True})
    aa._git = g
    try:
        ref, trace = aa._lane_branch_resolve("lane/t1", repo)
    finally:
        aa._git = aa_git
    assert (ref, trace) == ("lane/t1", "")
    assert g.refs() == ["lane/t1^{commit}"]
    # fallback: the trace names both names, and only branch names are asked
    g = StubGit(resolve={"lane/t1-root": True})
    aa._git = g
    try:
        ref, trace = aa._lane_branch_resolve("lane/t1", repo)
    finally:
        aa._git = aa_git
    assert ref == "lane/t1-root"
    assert "lane/t1" in trace and "lane/t1-root" in trace and "root-tree" in trace
    assert [r[:-len("^{commit}")] for r in g.refs()] == ["lane/t1", "lane/t1-root"]
    # both miss: fail-closed, every candidate + the last git error + the blocked
    # merge-base named; the literal main is never asked
    g = StubGit(resolve={})
    aa._git = g
    try:
        ref, trace = aa._lane_branch_resolve("lane/t1", repo)
    finally:
        aa._git = aa_git
    assert ref == ""
    for part in ("lane/t1", "lane/t1-root", "tried", "Needed a single revision"):
        assert part in trace, (part, trace)
    assert "main" not in trace
    # malformed branch name: no candidate, never raises
    assert aa._lane_branch_resolve("", repo)[0] == ""
    assert aa._lane_branch_resolve(None, repo)[0] == ""


aa_git = aa._git  # the real module function, restored after every stub leg


# ---------------- 3. changed_files ----------------

def test_changed_files_manifest_present_uses_the_manifest_branch(tmp_path):
    """A1a: the reported shape. The manifest already carries lane/<id>-root, so the
    manifest branch is used and the twin helper is never consulted."""
    lane = _lane(tmp_path, [{"repo": "", "name": "root", "branch": "lane/t1-root",
                             "base_ref": "abc"}])
    g = StubGit(resolve={"lane/t1-root": True},
                base={"lane/t1-root": "abc123"}, diff={})
    aa._git = g
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.error == ""
    assert r.resolved == ["root:lane/t1-root"]
    # the helper was not consulted: exactly one probe, for the manifest branch
    assert [x[:-len("^{commit}")] for x in g.refs()] == ["lane/t1-root"]


def test_changed_files_manifest_absent_multi_repo_fails_closed(tmp_path):
    """A1b + the arbitration contract: the root twin resolving is EVIDENCE that the lane
    root is a multi-repo root. With no manifest the member trees cannot be enumerated,
    so the call fails closed by name instead of returning the root tree's files (that
    would read localized and narrow the round while member work stays unseen)."""
    lane = _lane(tmp_path, None)
    g = StubGit(resolve={"lane/t1-root": True},
                base={"lane/t1-root": "abc123"},
                diff={str(tmp_path): (0, "docs/note.md\n", "")})
    aa._git = g
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.files == [] and r.resolved == []
    assert r.wall_s > 0
    low = r.error.lower()
    assert any(w in low for w in ("manifest", "member", "multi-repo")), r.error
    assert "lane/t1-root" in r.error
    # the error rides the full-run sentinel: the round cannot narrow
    assert shared.targeted_rerun_plan(["docs/note.md"], ["sc_prev_red"],
                                      changed_files=r.files, diff_error=r.error) == []


def test_changed_files_single_repo_control_unchanged(tmp_path):
    """C4 control: a manifest-free SINGLE-repo lane resolves its own name first, so the
    twin guard never touches it and the legacy list comes back."""
    lane = _lane(tmp_path, None)
    g = StubGit(resolve={"lane/t1-single": True}, base={"lane/t1-single": "abc"},
                diff={str(tmp_path): (0, "docs/x.md\n", "")})
    aa._git = g
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane),
                                  branch="lane/t1-single"))
    finally:
        aa._git = aa_git
    assert r.error == "" and r.files == ["docs/x.md"]
    assert r.resolved == ["root:lane/t1-single"]
    assert [x[:-len("^{commit}")] for x in g.refs()] == ["lane/t1-single"]


def test_changed_files_manifest_present_twin_fallback_still_returns_the_list(
        tmp_path, caplog):
    """The twin stays wired for a manifest-bearing lane whose scope branch is stale: the
    manifest proves the tree set, the twin repairs the name, the list is returned, and
    the log line names both names (review C6)."""
    # a legacy manifest that still carries the placeholder form: its twin is the
    # real root-tree name, and the manifest proves the tree set is complete
    lane = _lane(tmp_path, [{"repo": "", "name": "root", "branch": "lane/t1"}])
    g = StubGit(resolve={"lane/t1-root": True},
                base={"lane/t1-root": "abc123"},
                diff={str(tmp_path): (0, "docs/note.md\n", "")})
    aa._git = g
    try:
        with caplog.at_level("INFO"):
            r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane),
                                      branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.error == "" and r.files == ["docs/note.md"]
    assert r.resolved == ["root:lane/t1-root"]
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "changed_files: scope=root branch=lane/t1-root" in text
    assert "root-tree name" in text


def test_changed_files_per_scope_union_and_prefix(tmp_path):
    """A3: a member-tree commit and a member-tree dirty file both appear, prefixed. A
    member scope never asks for a root twin."""
    lane = _lane(tmp_path, [
        {"repo": "member", "name": "member", "branch": "lane/t1-member"},
        {"repo": "", "name": "root", "branch": "lane/t1-root"},
    ])
    member_tree = str(lane / "member")
    g = StubGit(resolve={"lane/t1-member": True, "lane/t1-root": True},
                base={"lane/t1-member": "aaa111", "lane/t1-root": "bbb222"},
                # diff anchors on each scope's REPO, status on each scope's TREE
                diff={str(tmp_path / "member"): (0, "parts/cad/x.json\n", ""),
                      str(tmp_path): (0, "docs/readme.md\n", "")},
                status={member_tree: (0, "?? scratch.txt\0", "")})
    aa._git = g
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.error == "", r.error
    assert r.files == ["member/parts/cad/x.json", "member/scratch.txt", "docs/readme.md"]
    assert r.resolved == ["member:lane/t1-member", "root:lane/t1-root"]
    probed = [x[:-len("^{commit}")] for x in g.refs()]
    assert "lane/t1-root-root" not in probed and "lane/t1-member-root" not in probed


def test_changed_files_corrupt_manifest_is_named_fail_closed(tmp_path):
    """A4: a corrupt manifest is a named red, never a raise and never a partial list."""
    lane = _lane(tmp_path, None)
    mf = shared.multi_manifest_path(lane, create=True)
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text("{not json", encoding="utf-8")
    g = StubGit()
    aa._git = g
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.files == [] and r.error
    assert "lane manifest unreadable" in r.error
    assert r.wall_s > 0


def test_changed_files_named_failures_and_scope_tag(tmp_path):
    """A4: every failing check is named, and a multi-scope red carries its tree tag."""
    lane = _lane(tmp_path, [{"repo": "member", "name": "member",
                             "branch": "lane/t1-member"}])
    member_tree = str(lane / "member")
    member_repo = str(tmp_path / "member")
    cases = []
    # no candidate resolves
    cases.append((StubGit(resolve={}),
                  ("changed-file list unavailable", "[member]")))
    # the name resolves but the baseline does not
    cases.append((StubGit(resolve={"lane/t1-member": True}),
                  ("merge-base failed", "[member]")))
    # the diff fails
    cases.append((StubGit(resolve={"lane/t1-member": True},
                          base={"lane/t1-member": "abc"},
                          diff={member_repo: (128, "", "fatal: bad revision")}),
                  ("git diff", "[member]")))
    # the status fails
    cases.append((StubGit(resolve={"lane/t1-member": True},
                          base={"lane/t1-member": "abc"},
                          status={member_tree: (1, "", "fatal")}),
                  ("git status", "[member]")))
    for stub, (needle, tag) in cases:
        aa._git = stub
        try:
            r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane),
                                      branch="lane/t1"))
        finally:
            aa._git = aa_git
        assert r.files == [], (needle, r.files)
        assert needle in r.error and tag in r.error, (needle, tag, r.error)
        assert r.wall_s > 0


def test_changed_files_keeps_uall_and_timeout(tmp_path):
    """A6: the carried faces — `-uall` on status, and a git timeout still raises."""
    lane = _lane(tmp_path, None)
    seen = []

    def fake(args, cwd, timeout=60):
        seen.append(list(args))
        if args[0] == "rev-parse":
            return _rc("deadbeef\n")
        if args[0] == "merge-base":
            return _rc("abc\n")
        if args[0] == "status":
            return _rc("?? dir/\0 M ok.md\0")
        return _rc("")

    aa._git = fake
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.error == "" and r.files == ["dir/", "ok.md"]
    status_args = next(a for a in seen if a[0] == "status")
    assert "--untracked-files=all" in status_args and "-z" in status_args

    def boom(args, cwd, timeout=60):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    aa._git = boom
    try:
        try:
            _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
            raise AssertionError("a git timeout must propagate (the caller full-runs)")
        except subprocess.TimeoutExpired:
            pass
    finally:
        aa._git = aa_git


def test_changed_files_wall_s_on_success(tmp_path):
    """C7: the phase-timing contract — the success path reports a positive wall time."""
    lane = _lane(tmp_path, None)
    g = StubGit(resolve={"lane/t1": True}, base={"lane/t1": "abc"}, delay=0.002)
    aa._git = g
    try:
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    finally:
        aa._git = aa_git
    assert r.error == "" and r.wall_s > 0


# ---------------- 4. lane_head_sha (review K2 / A10) ----------------

def test_lane_head_sha_resolves_the_root_twin(tmp_path):
    lane = _lane(tmp_path, None)
    g = StubGit(resolve={"lane/t1-root": True}, heads={"lane/t1-root": "cafe1234"})
    aa._git = g
    try:
        r = asyncio.run(aa.lane_head_sha(aa.LaneHeadShaArgs(
            ticket_id="t", worktree=str(lane), branch="lane/t1")))
    finally:
        aa._git = aa_git
    assert r.ok is True and r.sha == "cafe1234"
    # fail-closed: a name that resolves nowhere still reports a named error
    g = StubGit(resolve={})
    aa._git = g
    try:
        r = asyncio.run(aa.lane_head_sha(aa.LaneHeadShaArgs(
            ticket_id="t", worktree=str(lane), branch="lane/t1")))
    finally:
        aa._git = aa_git
    assert r.ok is False and r.sha == ""
    assert "lane/t1" in r.error and "lane/t1-root" in r.error


# ---------------- 5. the gate run caliber (arbitration round 4) ----------------

def _caliber_self(monkeypatch=None):
    """A DevLaneWorkflow shell for `_integ_run_args` (no workflow run, no IO)."""
    import dev_lane as dl
    wf = object.__new__(dl.DevLaneWorkflow)
    wf.ticket_id = "t26102918ut"
    wf.meta = {"worktree": "/w"}
    wf._gen = lambda step: 0
    wf._effective_write_set = lambda: ["integration/"]
    wf._handover_debt_legs = lambda: []
    return dl, wf


def test_integ_run_args_unions_declared_own_into_the_pointed_face():
    """A pointed round that declares an own scenario must RUN it. The runner executes
    exactly the pointed list, so the caliber (one writer) does the union; otherwise the
    own-coverage guard turns the receipt into a startup-level error and every pass of
    that round is voided (the closing recheck measured on this ticket)."""
    dl, wf = _caliber_self()
    args = wf._integ_run_args(["sc_a", "sc_b"], own_names=["own_sc"])
    assert args.only_names == ["sc_a", "sc_b", "own_sc"]
    assert args.own_names == ["own_sc"]
    # the property the guard actually checks: the declared set is covered
    assert shared.own_coverage_error(args.own_names, args.only_names) == ""
    # idempotent: an own name already listed is not duplicated
    args2 = wf._integ_run_args(["sc_a", "own_sc"], own_names=["own_sc"])
    assert args2.only_names == ["sc_a", "own_sc"]
    # an own name that is a member of a tuple input is handled like a list
    args3 = wf._integ_run_args(("sc_a",), own_names=("own_sc",))
    assert args3.only_names == ["sc_a", "own_sc"]


def test_integ_run_args_full_run_is_never_turned_into_a_pointed_one():
    """An empty pointed face = the full run. Adding own names there would narrow the
    full run, and the own names run anyway."""
    dl, wf = _caliber_self()
    for only in ((), [], None):
        args = wf._integ_run_args(only, own_names=["own_sc"])
        assert args.only_names == [], only
        assert args.own_names == ["own_sc"]
    # no own face at all: the caliber is byte-identical to the old behavior
    args = wf._integ_run_args(["sc_a"])
    assert args.only_names == ["sc_a"] and args.own_names == []


def test_integ_run_args_both_declaring_call_sites_route_through_the_writer():
    """Source lock: the main run and the closing arm both declare own names through the
    single writer (a second writer or a dropped own_names argument is how this came
    apart in the first place)."""
    src = (_ENGINE / "dev_lane.py").read_text(encoding="utf-8")
    assert src.count("def _integ_run_args(self, only_names=(), own_names=()):") == 1
    assert "own_names=_own_face_names" in src       # the main run site
    assert "own_names=_closing_own" in src          # the closing arm
    assert "own_names=list((quick_scope or {}).get(\"own_names\") or [])" in src
    # the caliber union lives in the writer, not at a call site
    body = src.split("def _integ_run_args(", 1)[1].split("\n    async def ", 1)[0]
    assert "for _n in (own_names or ()):" in body


if __name__ == "__main__":
    import inspect
    import tempfile
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    with tempfile.TemporaryDirectory(prefix="t26102918ut-") as _tmp:
        for fn in fns:
            kwargs = {}
            for pname in inspect.signature(fn).parameters:
                if pname == "tmp_path":
                    kwargs[pname] = Path(_tmp) / fn.__name__
                    kwargs[pname].mkdir(parents=True, exist_ok=True)
            fn(**kwargs)
            print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
