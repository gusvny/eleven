#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261031-17 L1 battery — per-scope changed-file baseline (merged with t261029-18).

The defect this ticket reports: every gate round on a multi-repo lane ran the whole
suite because merge-base could not produce a changed-file list — the collector took
the suffix-less `lane/<id>` while a multi-repo lane names one branch per repo
(`lane/<id>-<repo>`, plus `lane/<id>-root` for the root-repo tree).

The line (`develop-buffer`) fixed the same defect as t261029-18 with
`_lane_branch_resolve` and a `resolved` receipt field; this file pins the merged shape,
so both tickets' guarantees hold at once:

1. one branch, tree and repo per manifest entry, resolved through the line's helper
   (`rev-parse --verify --quiet <candidate>^{commit}`), with the suffix-less name never
   reaching git;
2. anchors per call: resolve, merge-base and diff at the owning repo root, status in
   the lane tree (the only place that move is falsifiable on this fixture);
3. project-root-relative paths: a member path keeps its `repo_rel/` prefix;
4. sibling mounts are not changes, in both measured shapes (`?? <repo>/` from status,
   the gitlink path `<repo>` from diff), while an ordinary untracked `dir/` stays;
5. fail-closed and named, never a raise: an unresolvable branch, the manifest-absent
   twin refusal, a failed merge-base/diff/status, a missing tree, a corrupt manifest,
   and a manifest `repo` value that is absolute or carries `..`;
6. `subprocess.TimeoutExpired` still propagates; the pure decision chain keeps the
   ticket's economics (member-only change → localized, shared-base face → full run).

Stub git only (the unit tier forbids real git, conftest.py). The merged module needs the
line's `shared.ChangedFilesResult(resolved=…)` and `shared.lane_branch_candidates`, so
this file runs on a tree that carries the line.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa
import shared
from shared import ChangedFilesArgs

_ENGINE = Path(__file__).resolve().parents[1]

#: The engine write set, used for the pure decision chain.
_ENGINE_WRITE_SET = ["server/engine/", "integration/", "verify.yaml"]


def _rc(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _manifest(lane: Path, entries) -> None:
    """Write the lane manifest where the engine writes it (new coordination name)."""
    dot = lane / ".sandbar"
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "repo_worktrees.json").write_text(json.dumps(entries), "utf-8")


def _multirepo_lane(tmp_path, members=("member-trainer", "fpv-core")) -> Path:
    """A fake multi-repo lane on disk: `<tmp>/proj/.lane/t1` plus one owning repo and
    one lane tree per member. No git runs; each case stubs `_git`."""
    lane = tmp_path / "proj" / ".lane" / "t1"
    lane.mkdir(parents=True)
    entries = [{"repo": "", "name": "root", "branch": "lane/t1-root", "base_ref": ""}]
    for m in members:
        entries.append({"repo": m, "name": m, "branch": "lane/t1-%s" % m,
                        "base_ref": ""})
        (lane / m).mkdir(parents=True)
        (tmp_path / "proj" / m).mkdir(parents=True)
    _manifest(lane, entries)
    return lane


def _single_lane(tmp_path, under_convention: bool) -> Path:
    """A single-repo lane: no manifest. `under_convention` builds `<tmp>/proj/.lane/t1`
    (the resolver answers the project root); otherwise `<tmp>/lane1` carries a `.git`
    marker and the resolver answers the tree itself."""
    if under_convention:
        lane = tmp_path / "proj" / ".lane" / "t1"
        lane.mkdir(parents=True)
        return lane
    lane = tmp_path / "lane1"
    (lane / ".git").mkdir(parents=True)
    return lane


def _key(args, cwd):
    """Dispatch key: a resolve probe names the ref it asks for, the other verbs do not."""
    if args and args[0] == "rev-parse":
        return ("rev-parse", str(cwd), args[-1])
    return (args[0], str(cwd))


def _stub_git(monkeypatch, responses, calls=None):
    """Dispatch `_git` on (verb, cwd[, ref]). An unexpected call fails loudly: a
    silently wrong command must never look like a pass."""
    log = calls if calls is not None else []

    def fake_git(args, cwd, timeout=60):
        log.append((list(args), str(cwd)))
        key = _key(args, cwd)
        if key not in responses:
            raise AssertionError("unexpected git call: %s in %s" % (args, cwd))
        r = responses[key]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(aa, "_git", fake_git)
    return log


def _probe(cwd, ref, ok=True):
    """One resolve probe answer (`rev-parse --verify --quiet <ref>^{commit}`)."""
    return {("rev-parse", str(cwd), "%s^{commit}" % ref): (_rc(ref + "\n") if ok else _rc())}


def _run(args: ChangedFilesArgs):
    return asyncio.run(aa.changed_files(args))


# ---------------- 1. single-repo lanes: the legacy list ----------------

def test_single_repo_lane_keeps_the_list(tmp_path, monkeypatch):
    lane = _single_lane(tmp_path, under_convention=False)
    resp = {}
    resp.update(_probe(lane, "lane-1"))
    resp[("merge-base", str(lane))] = _rc("abc123\n")
    resp[("diff", str(lane))] = _rc("app/a.ts\nnotes/x.md\napp/a.ts\n")
    resp[("status", str(lane))] = _rc("?? integration/t260925-04/\0 M notes/x.md\0")
    calls = _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane-1"))

    assert r.error == "", r.error
    # order preserved, duplicates dropped, the collapsed `dir/` entry survives
    assert r.files == ["app/a.ts", "notes/x.md", "integration/t260925-04/"], r.files
    assert r.resolved == ["root:lane-1"], r.resolved
    assert calls[0][0] == ["rev-parse", "--verify", "--quiet", "lane-1^{commit}"]
    assert calls[1][0] == ["merge-base", "main", "lane-1"]
    assert calls[2][0] == ["diff", "--name-only", "abc123...lane-1"]
    assert calls[3][0][0] == "status" and "--untracked-files=all" in calls[3][0]


def test_single_repo_lane_under_convention_anchors_each_call(tmp_path, monkeypatch):
    """Acceptance item: resolve/merge-base/diff at the owning repo root, status in the
    lane tree. One object store makes this invisible on a real single-repo fixture."""
    lane = _single_lane(tmp_path, under_convention=True)
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1"))
    resp[("merge-base", str(project))] = _rc("abc123\n")
    resp[("diff", str(project))] = _rc("app/a.ts\n")
    resp[("status", str(lane))] = _rc(" M app/a.ts\0")
    calls = _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))

    assert r.error == "", r.error
    assert r.files == ["app/a.ts"], r.files          # bare: project-root-relative
    assert calls[0][1] == str(project)               # resolve at the owning repo
    assert calls[1][1] == str(project)               # merge-base at the owning repo
    assert calls[2][1] == str(project)               # diff at the owning repo
    assert calls[3][1] == str(lane)                  # status in the lane tree
    assert r.resolved == ["root:lane/t1"], r.resolved


# ---------------- 2. multi-repo lanes: one branch per repo ----------------

def test_multirepo_lane_asks_each_repo_for_its_own_branch(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path)
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1-root"))
    resp[("merge-base", str(project))] = _rc("rootbase\n")
    resp[("diff", str(project))] = _rc("docs/x.md\n")
    resp[("status", str(lane))] = _rc("")
    resp.update(_probe(project / "member-trainer", "lane/t1-member-trainer"))
    resp[("merge-base", str(project / "member-trainer"))] = _rc("trainerbase\n")
    resp[("diff", str(project / "member-trainer"))] = _rc("src/a.dart\n")
    resp[("status", str(lane / "member-trainer"))] = _rc("?? app/newdir/\0")
    resp.update(_probe(project / "fpv-core", "lane/t1-fpv-core"))
    resp[("merge-base", str(project / "fpv-core"))] = _rc("corebase\n")
    resp[("diff", str(project / "fpv-core"))] = _rc("lib/b.dart\n")
    resp[("status", str(lane / "fpv-core"))] = _rc("")
    calls = _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))

    assert r.error == "", r.error
    # project-root-relative, member paths carry their repo prefix, order preserved
    assert r.files == ["docs/x.md", "member-trainer/src/a.dart",
                       "member-trainer/app/newdir/", "fpv-core/lib/b.dart"], r.files
    # every scope resolved and used ITS manifest branch; the suffix-less name is absent
    assert r.resolved == ["root:lane/t1-root",
                          "member-trainer:lane/t1-member-trainer",
                          "fpv-core:lane/t1-fpv-core"], r.resolved
    asked = {a for c in calls for a in c[0]}
    assert "lane/t1" not in asked and "lane/t1^{commit}" not in asked, sorted(asked)
    # anchors: resolve, merge-base and diff at the owning repo; status in the lane tree
    for repo, tree in ((project, lane),
                       (project / "member-trainer", lane / "member-trainer"),
                       (project / "fpv-core", lane / "fpv-core")):
        assert any(c[0][0] == "rev-parse" and c[1] == str(repo) for c in calls)
        assert any(c[0][0] == "merge-base" and c[1] == str(repo) for c in calls)
        assert any(c[0][0] == "diff" and c[1] == str(repo) for c in calls)
        assert any(c[0][0] == "status" and c[1] == str(tree) for c in calls)


def test_multirepo_lane_dedupes_across_scopes(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path, members=("member-trainer",))
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1-root"))
    resp[("merge-base", str(project))] = _rc("b1\n")
    resp[("diff", str(project))] = _rc("a.txt\nb.txt\n")
    resp[("status", str(lane))] = _rc("?? b.txt\0?? c.txt\0")
    resp.update(_probe(project / "member-trainer", "lane/t1-member-trainer"))
    resp[("merge-base", str(project / "member-trainer"))] = _rc("b2\n")
    resp[("diff", str(project / "member-trainer"))] = _rc("a.txt\n")
    resp[("status", str(lane / "member-trainer"))] = _rc("")
    _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    assert r.error == "", r.error
    assert r.files == ["a.txt", "b.txt", "c.txt", "member-trainer/a.txt"], r.files


def test_multirepo_lane_reads_the_legacy_manifest_location(tmp_path, monkeypatch):
    lane = tmp_path / "proj" / ".lane" / "t1"
    (lane / shared.DOT_DIR_OLD).mkdir(parents=True)     # old coordination name only
    (lane / "member-trainer").mkdir(parents=True)
    (tmp_path / "proj" / "member-trainer").mkdir(parents=True)
    (lane / shared.DOT_DIR_OLD / "repo_worktrees.json").write_text(json.dumps([
        {"repo": "member-trainer", "name": "member-trainer",
         "branch": "lane/t1-member-trainer", "base_ref": ""},
    ]), "utf-8")
    repo = tmp_path / "proj" / "member-trainer"
    resp = {}
    resp.update(_probe(repo, "lane/t1-member-trainer"))
    resp[("merge-base", str(repo))] = _rc("x\n")
    resp[("diff", str(repo))] = _rc("src/a.dart\n")
    resp[("status", str(lane / "member-trainer"))] = _rc("")
    calls = _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    assert r.error == "", r.error
    assert r.files == ["member-trainer/src/a.dart"], r.files
    assert calls[0][0] == ["rev-parse", "--verify", "--quiet",
                           "lane/t1-member-trainer^{commit}"], calls[0]


# ---------------- 3. sibling mounts are not changes ----------------

def test_sibling_mounts_are_dropped_on_both_faces(tmp_path, monkeypatch):
    """Both measured shapes: `?? <repo>/` in the root tree's status and `<repo>` in the
    root tree's diff (the gitlink a lane-root `git add -A` records)."""
    lane = _multirepo_lane(tmp_path)
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1-root"))
    resp[("merge-base", str(project))] = _rc("b0\n")
    resp[("diff", str(project))] = _rc("member-trainer\nfpv-core\nnotes/x.md\n")
    resp[("status", str(lane))] = _rc("?? member-trainer/\0?? fpv-core/\0?? notes/y.md\0?? dir/\0")
    for m in ("member-trainer", "fpv-core"):
        resp.update(_probe(project / m, "lane/t1-%s" % m))
        resp[("merge-base", str(project / m))] = _rc("b-%s\n" % m)
        resp[("diff", str(project / m))] = _rc("")
        resp[("status", str(lane / m))] = _rc("")
    _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))

    assert r.error == "", r.error
    assert r.files == ["notes/x.md", "notes/y.md", "dir/"], r.files
    # a kept collapsed entry means "shared" BY DESIGN (t260925-04 rule); with the
    # sibling mounts gone the rest of the list classifies as localized
    assert shared.changed_files_blast_radius(
        [f for f in r.files if not f.endswith("/")]) == "localized"


def test_a_member_own_untracked_directory_is_kept(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path, members=("member-trainer",))
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1-root"))
    resp[("merge-base", str(project))] = _rc("b0\n")
    resp[("diff", str(project))] = _rc("")
    resp[("status", str(lane))] = _rc("")
    resp.update(_probe(project / "member-trainer", "lane/t1-member-trainer"))
    resp[("merge-base", str(project / "member-trainer"))] = _rc("b1\n")
    resp[("diff", str(project / "member-trainer"))] = _rc("")
    resp[("status", str(lane / "member-trainer"))] = _rc("?? app/newdir/\0")
    _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    assert r.error == "", r.error
    assert r.files == ["member-trainer/app/newdir/"], r.files


# ---------------- 4. fail-closed, always named ----------------

def test_unresolvable_branch_fails_closed_with_the_scope_tag(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path, members=("member-trainer",))
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1-root"))
    resp[("merge-base", str(project))] = _rc("b0\n")
    resp[("diff", str(project))] = _rc("docs/x.md\n")
    resp[("status", str(lane))] = _rc("")
    resp.update(_probe(project / "member-trainer", "lane/t1-member-trainer", ok=False))
    _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    assert r.files == [] and r.resolved == [], r.files
    assert "[member-trainer]" in r.error and "resolvable branch" in r.error, r.error


def test_manifest_absent_twin_is_refused(tmp_path, monkeypatch):
    """A manifest-free lane whose own name does not resolve but whose root-tree twin
    does: the twin proves a multi-repo root, and without the manifest the member trees
    cannot be enumerated — fail closed instead of returning the root's files."""
    lane = _single_lane(tmp_path, under_convention=True)
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1", ok=False))
    resp.update(_probe(project, "lane/t1-root"))
    _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    assert r.files == [] and r.resolved == [], r.files
    low = r.error.lower()
    assert any(w in low for w in ("manifest", "member", "multi-repo")), r.error
    assert shared.targeted_rerun_plan(["docs/x.md"], ["sc_prev"],
                                      changed_files=r.files, diff_error=r.error) == []


def test_merge_base_diff_and_status_failures_name_the_scope(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path, members=("member-trainer",))
    project = tmp_path / "proj"
    good = {}
    good.update(_probe(project, "lane/t1-root"))
    good[("merge-base", str(project))] = _rc("b0\n")
    good[("diff", str(project))] = _rc("docs/x.md\n")
    good[("status", str(lane))] = _rc("")
    member = project / "member-trainer"
    tree = lane / "member-trainer"

    faults = [
        ("merge-base", dict(list(_probe(member, "lane/t1-member-trainer").items())
                            + [(("merge-base", str(member)),
                                _rc(returncode=128, stderr="fatal: no branch"))]),
         "merge-base failed for branch"),
        ("diff", dict(list(_probe(member, "lane/t1-member-trainer").items())
                      + [(("merge-base", str(member)), _rc("b1\n")),
                         (("diff", str(member)),
                          _rc(returncode=128, stderr="fatal: bad revision"))]),
         "failed in repo"),
        ("status", dict(list(_probe(member, "lane/t1-member-trainer").items())
                        + [(("merge-base", str(member)), _rc("b1\n")),
                           (("diff", str(member)), _rc("")),
                           (("status", str(tree)), _rc(returncode=1, stderr="fatal"))]),
         "failed in tree"),
    ]
    for label, extra, marker in faults:
        resp = dict(good)
        resp.update(extra)
        _stub_git(monkeypatch, resp)
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
        assert r.files == [], (label, r.files)
        assert marker in r.error, (label, r.error)
        assert "[member-trainer]" in r.error, (label, r.error)


def test_missing_tree_answers_a_named_error(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path, members=("member-trainer",))
    project = tmp_path / "proj"
    resp = {}
    resp.update(_probe(project, "lane/t1-root"))
    resp[("merge-base", str(project))] = _rc("b0\n")
    resp[("diff", str(project))] = _rc("")
    resp[("status", str(lane))] = _rc("")
    # a missing cwd makes `_git` raise OSError from Popen; the activity names it
    resp.update({k: FileNotFoundError("no such tree")
                 for k in _probe(project / "member-trainer", "lane/t1-member-trainer")})
    _stub_git(monkeypatch, resp)
    r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
    assert r.files == [] and "unreadable" in r.error, r.error


def test_timeout_still_propagates(tmp_path, monkeypatch):
    lane = _single_lane(tmp_path, under_convention=False)
    resp = {}
    resp.update({k: subprocess.TimeoutExpired(cmd=["git"], timeout=60)
                 for k in _probe(lane, "b")})
    _stub_git(monkeypatch, resp)
    try:
        _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="b"))
    except subprocess.TimeoutExpired:
        return
    raise AssertionError("a git timeout must propagate, never become a receipt")


# ---------------- 5. manifest faults (agent-written external input) ----------------

def test_manifest_faults_return_a_named_error(tmp_path, monkeypatch):
    _stub_git(monkeypatch, {})            # a manifest fault must stop before git
    faults = [
        ("bad json", "{not json"),
        ("not a list", json.dumps({"repo": ""})),
        ("empty list", json.dumps([])),
        ("missing branch", json.dumps([{"repo": "member-trainer", "name": "x"}])),
        ("branch not a string",
         json.dumps([{"repo": "member-trainer", "name": "x", "branch": 7}])),
        ("missing repo", json.dumps([{"name": "x", "branch": "lane/t1-x"}])),
        ("repo not a string", json.dumps([{"repo": 5, "name": "x", "branch": "b"}])),
    ]
    for label, payload in faults:
        lane = tmp_path / label.replace(" ", "_") / "proj" / ".lane" / "t1"
        lane.mkdir(parents=True)
        _manifest(lane, [])
        (lane / ".sandbar" / "repo_worktrees.json").write_text(payload, "utf-8")
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
        assert r.files == [], label
        assert "lane manifest" in r.error, (label, r.error)


def test_manifest_repo_that_escapes_is_refused(tmp_path, monkeypatch):
    """The manifest value is joined into a path without validation, so an absolute
    value or a `..` component would run git outside the lane."""
    _stub_git(monkeypatch, {})
    for label, repo, why in (("absolute", "/tmp/elsewhere", "absolute"),
                             ("dotdot", "../x", "escapes"),
                             ("inner dotdot", "a/../b", "escapes")):
        lane = tmp_path / label.replace(" ", "_") / "proj" / ".lane" / "t1"
        lane.mkdir(parents=True)
        _manifest(lane, [{"repo": repo, "name": "x", "branch": "lane/t1-x"}])
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
        assert r.files == [], (label, r.files)
        assert why in r.error and "[x]" in r.error, (label, r.error)


def test_manifest_repo_escape_truth_table():
    """The escape judge works on path components, not on a substring: a directory that
    merely carries two dots in its name stays legal."""
    for ok in ("", "member-trainer", "a/b", "a..b", "x..y/z"):
        assert aa._manifest_repo_escape(ok) == "", ok
    for bad in ("/abs", "../x", "a/../b", ".."):
        assert aa._manifest_repo_escape(bad), bad


# ---------------- 6. the pure decision chain (the ticket's economics) ----------------

def test_member_change_no_longer_forces_a_full_run(tmp_path, monkeypatch):
    lane = _multirepo_lane(tmp_path, members=("member-trainer",))
    project = tmp_path / "proj"
    member = project / "member-trainer"

    def _files(root_diff):
        resp = {}
        resp.update(_probe(project, "lane/t1-root"))
        resp[("merge-base", str(project))] = _rc("b0\n")
        resp[("diff", str(project))] = _rc(root_diff)
        resp[("status", str(lane))] = _rc("")
        resp.update(_probe(member, "lane/t1-member-trainer"))
        resp[("merge-base", str(member))] = _rc("b1\n")
        resp[("diff", str(member))] = _rc("src/a.dart\n")
        resp[("status", str(lane / "member-trainer"))] = _rc("")
        _stub_git(monkeypatch, resp)
        r = _run(ChangedFilesArgs(ticket_id="t", worktree=str(lane), branch="lane/t1"))
        assert r.error == "", r.error
        return r.files

    files = _files("")
    assert files == ["member-trainer/src/a.dart"], files
    assert shared.changed_files_blast_radius(files) == "localized"
    assert shared.targeted_rerun_plan(_ENGINE_WRITE_SET, ["sc_a", "sc_b"],
                                      changed_files=files) == ["sc_a", "sc_b"]

    # safety track: a shared-base face inside the root repo still means "run all"
    files_shared = _files("verify.yaml\n")
    assert shared.changed_files_blast_radius(files_shared) == "shared"
    assert shared.targeted_rerun_plan(_ENGINE_WRITE_SET, ["sc_a"],
                                      changed_files=files_shared) == []


# ---------------- 7. structure locks (the merged shape) ----------------

def test_structure_locks():
    act = (_ENGINE / "agent_activities.py").read_text(encoding="utf-8")
    body = act.split("async def changed_files(")[1].split("\n@activity.defn")[0]
    # the line's resolver is what names each scope's branch; the placeholder is never
    # handed to git
    assert "branch, br_trace = _lane_branch_resolve(" in body
    assert "allow_root_twin=allow_twin" in body
    assert "_merge_base_ref(branch, sc[\"repo\"])" in body
    assert 'st = _git(["status", "--porcelain", "-z", "--untracked-files=all"], sc["tree"])' \
        in body
    # this ticket's two guarantees
    assert "_manifest_repo_escape(" in body and "_scope_path_inside(" in body
    assert "_drop_sibling_tree_paths(" in body
    # the receipt carries the per-scope resolution (the line's field) and one collector
    assert "resolved=resolved" in body
    assert "_collect_lane_changed_files" not in act
    # the decision writer stays unique (this collector never classifies)
    assert "changed_files_blast_radius(" not in body
    # worker registration is untouched (a missing registration only shows at runtime)
    assert "changed_files," in act and "ALL_AGENT_ACTIVITIES" in act


if __name__ == "__main__":
    import tempfile

    class _MP:                                  # minimal monkeypatch for a direct run
        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, value):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def undo(self):
            for obj, name, old in reversed(self._undo):
                setattr(obj, name, old)
            self._undo = []

    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        mp = _MP()
        args = list(fn.__code__.co_varnames[:fn.__code__.co_argcount])
        kwargs = {}
        if "monkeypatch" in args:
            kwargs["monkeypatch"] = mp
        try:
            if "tmp_path" in args:
                with tempfile.TemporaryDirectory(prefix="t26103117-") as tmp:
                    kwargs["tmp_path"] = Path(tmp)
                    fn(**kwargs)
            else:
                fn(**kwargs)
        finally:
            mp.undo()
        print("ok   ", fn.__name__)
    print("SUMMARY pass=%d fail=0 env_fail=0 na=0" % len(fns))
