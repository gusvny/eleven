"""t261016-21 (KI-01M52NS7A3290FBAWY1XYSBG0E) unit tests: multi-repo lanes settle
EVERY scope at the agent-stage assembly point.

Under test: agent_activities._settle_with_gate (per-scope rewrite), its post-settle
hardening helper _unpersisted_scope_note, and the merge_check self-heal call in
_merge_check_one_scope (which now carries the per-scope repo anchor).

Coverage (zero Temporal server / zero model / zero network; git fixtures self-contained
in tmp):
  A. THE DEFECT, fixed — a multi-repo lane (manifest with a root tree + one member
     repo) where the agent dirtied BOTH trees and never committed: one settle call
     produces one commit per scope, the member scope's note is tagged "[repo_a]",
     the root scope's note keeps the plain worker-settle wording.
  B. Single-repo byte identity — no manifest: exactly one commit and the note is the
     old literal worker-settle wording; a clean workspace keeps the old clean note;
     a non-worktree cwd still returns "" verbatim (a dir-isolated workspace is a
     lawful no-op, never the "settle empty" production wording).
  C. Refusal aggregation (review gen0 condition 1) — when a later scope's gate
     refuses, the earlier scopes' settle notes STAY in the returned text, the refused
     scope's note lands last tagged by name, and the refusal dict is populated.
  D. Loud empty note (review gen0 condition 2) — in a multi-scope lane an
     ownership-guard empty note is rendered as the tagged "settle empty" wording, never
     absorbed into a silent join.
  E. Hardening _unpersisted_scope_note — 0 commits relative to base + dirty worktree =
     the named NOT-persisted note; non-zero commits / no base_ref / unresolvable
     base_ref = "" (fail toward silence); a failed dirty listing = the UNKNOWN wording,
     never a false dirty claim; a tagged hard note rides under the scope's tag in the
     aggregated note.
  F. Manifest fail-closed — corrupted JSON raises RuntimeError, never a silent
     single-repo fallback (malformed external input discipline).
  G. Heal anchor — a dirty member scope self-heals inside _merge_check_one_scope into
     a real commit (pre-fix: the ownership guard returned "" for every member tree and
     the receipt read the "settle empty (see the re-check)" wording; the heal call omitted repo=).
"""
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
import agent_activities as aa  # noqa: E402
import shared  # noqa: E402

TICKET = "t26101621ut"


def _git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _commits(cwd) -> int:
    return int(_git(cwd, "rev-list", "--count", "HEAD"))


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "ut@example.com")
    _git(path, "config", "user.name", "ut")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


class _Args:
    """Minimal AgentStageArgs stand-in (only the fields the code under test reads)."""

    def __init__(self, write_set=None, base_ref="", path_gate=False):
        self.ticket_id = TICKET
        self.stage_id = "implement"
        self.gen = 0
        self.write_set = list(write_set or [])
        self.base_ref = base_ref
        self.path_gate = path_gate
        self.path_gate_rules = {}
        self.authorizations = []
        self.skip_settle = False


def _write_manifest(lane, root_base, member_base):
    """Multi-repo lane manifest: a root tree + one member repo (the resolved .sandbar path)."""
    mf = shared.multi_manifest_path(lane)
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(
        '[{"name": "root", "repo": "", "branch": "lane/ut-root", "base_ref": "%s"},\n'
        ' {"name": "repo_a", "repo": "repo_a", "branch": "lane/ut-repo_a", '
        '"base_ref": "%s"}]\n' % (root_base, member_base),
        encoding="utf-8")
    return mf


@pytest.fixture
def mixed_lane(tmp_path):
    """Multi-repo project (root repo + repo_a) + registered lane worktrees (both trees) + manifest."""
    root = _init_repo(tmp_path / "proj")
    a = _init_repo(root / "repo_a")
    # the project declares its member repo ignored in the root repo (the real
    # multi-repo stance: git must never fold the member worktree into the root
    # tree's status, or the gitlink guard would rightly refuse the settle)
    (root / ".gitignore").write_text("repo_a/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ignore member repo")
    lane = root / ".lane" / "wt"
    _git(root, "worktree", "add", "-q", "-b", "lane/ut-root", str(lane))
    _git(a, "worktree", "add", "-q", "-b", "lane/ut-repo_a", str(lane / "repo_a"))
    _write_manifest(lane, _git(root, "rev-parse", "HEAD"), _git(a, "rev-parse", "HEAD"))
    return root, a, lane


@pytest.fixture
def single_lane(tmp_path):
    """Single-repo project + registered lane worktree (no manifest = the legacy single-anchor fallback)."""
    root = _init_repo(tmp_path / "proj")
    lane = root / ".lane" / "wt"
    _git(root, "worktree", "add", "-q", "-b", "lane/ut-single", str(lane))
    return root, lane


# ---------- A. the defect, fixed ----------

def test_multirepo_dirty_lane_and_member_both_get_a_commit(mixed_lane):
    root, a, lane = mixed_lane
    (lane / "file_root.txt").write_text("root work\n", encoding="utf-8")
    (lane / "repo_a" / "a_member.txt").write_text("member work\n", encoding="utf-8")
    root_c0, a_c0 = _commits(lane), _commits(lane / "repo_a")

    note = aa._settle_with_gate(_Args(), lane)

    assert _commits(lane) == root_c0 + 1
    assert _commits(lane / "repo_a") == a_c0 + 1
    # member scope named loudly; root scope keeps the plain wording (the prepended
    # fixture-registry diagnostic is environment noise, present pre-change too)
    # copy-lang-allow:t261016-21 (assertions quote production note copy)
    assert note.count("worker 代落盘 commit") == 2  # one per scope
    assert "[repo_a]" in note and "[root]" in note  # each scope tagged
    assert "1 项：file_root.txt" in note  # copy-lang-allow:t261016-21
    assert "1 项：a_member.txt" in note  # copy-lang-allow:t261016-21
    # workspaces are clean afterwards
    assert not aa._dirty_files_from_status_z(subprocess.run(
        ["git", "-C", str(lane / "repo_a"), "status", "--porcelain", "-z",
         "--untracked-files=all", "--"] + aa.SETTLE_PATHSPEC,
        capture_output=True, text=True).stdout)


# ---------- B. single-repo byte identity ----------

def test_single_repo_dirty_lane_one_commit_old_wording(single_lane):
    root, lane = single_lane
    (lane / "x.txt").write_text("work\n", encoding="utf-8")
    c0 = _commits(lane)

    note = aa._settle_with_gate(_Args(), lane)

    assert _commits(lane) == c0 + 1
    assert "worker 代落盘 commit " in note  # copy-lang-allow:t261016-21
    assert "（1 项：x.txt）" in note  # copy-lang-allow:t261016-21
    assert not note.startswith("[")  # single scope: no tag prefix on the settle note


def test_single_repo_clean_and_non_worktree_return_verbatim(single_lane, tmp_path):
    root, lane = single_lane
    assert aa._settle_with_gate(_Args(), lane) == "工作区已干净，无需代落盘"  # copy-lang-allow:t261016-21
    # a dir-isolated / non-worktree workspace: the old "" return (lawful no-op),
    # never the "settle empty" failure wording
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    assert aa._settle_with_gate(_Args(), plain) == ""


# ---------- C. refusal aggregation keeps earlier scopes' evidence ----------

def test_refusal_keeps_earlier_scope_notes_and_tags_refused_scope(mixed_lane):
    root, a, lane = mixed_lane
    (lane / "file_root.txt").write_text("root work\n", encoding="utf-8")
    (lane / "repo_a" / "rogue.txt").write_text("out of set\n", encoding="utf-8")
    refusal = {}

    note = aa._settle_with_gate(_Args(write_set=["file_root.txt"], path_gate=True),
                                lane, refusal=refusal)

    # root scope really settled
    assert "worker 代落盘 commit" in note  # copy-lang-allow:t261016-21
    # the refused scope lands last, tagged, with the gate-refusal marker
    assert note.rstrip().endswith("path_gate_reason=") or "path_gate_reason=" in note
    tail = note.split("；")[-1]
    assert tail.startswith("[repo_a] ") and "path_gate_reason=" in tail
    assert "rogue.txt" in tail
    assert refusal  # structured detail collected
    # the root scope's file is committed, the member's rogue file stays in place
    assert not (lane / "repo_a" / "rogue.txt").exists() is False  # untouched on disk
    assert _commits(lane / "repo_a") == 1  # 0 new commits on the member lane branch


# ---------- D. loud empty note on an ownership-guard failure (multi-scope) ----------

def test_multirepo_ownership_guard_failure_named_not_silent(mixed_lane, monkeypatch):
    root, a, lane = mixed_lane
    calls = {"n": 0}

    real = aa._settle_worktree_lane

    def spy(tree, *args_, **kw):
        calls["n"] += 1
        if calls["n"] == 2:  # the member scope's call
            kw = dict(kw)
            kw["repo"] = None  # force the ownership guard to fail
        return real(tree, *args_, **kw)

    monkeypatch.setattr(aa, "_settle_worktree_lane", spy)
    note = aa._settle_with_gate(_Args(), lane)
    # copy-lang-allow:t261016-21
    assert "[repo_a] settle 返回空" in note


# ---------- E. hardening helper ----------

def test_unpersisted_note_names_zero_commit_dirty_scope(mixed_lane):
    root, a, lane = mixed_lane
    base = _git(a, "rev-parse", "HEAD")
    sc = {"tree": lane / "repo_a", "repo": a, "base_ref": base,
          "write_set": [], "name": "repo_a", "branch": "lane/ut-repo_a"}
    assert aa._unpersisted_scope_note(sc) == ""  # clean + 0 commits = lawful
    (lane / "repo_a" / "late.txt").write_text("unpersisted\n", encoding="utf-8")
    note = aa._unpersisted_scope_note(sc)
    assert "0 commits relative to base" in note and "NOT persisted" in note
    assert "late.txt" in note
    _git(lane / "repo_a", "add", "-A")
    _git(lane / "repo_a", "commit", "-q", "-m", "landed")
    assert aa._unpersisted_scope_note(sc) == ""  # 1 commit = green


def test_unpersisted_note_fail_toward_silence_and_unknown(mixed_lane):
    root, a, lane = mixed_lane
    (lane / "repo_a" / "late.txt").write_text("x\n", encoding="utf-8")
    sc = {"tree": lane / "repo_a", "repo": a, "base_ref": "", "write_set": []}
    assert aa._unpersisted_scope_note(sc) == ""        # no base = no claim
    sc["base_ref"] = "definitely-not-a-ref"
    assert aa._unpersisted_scope_note(sc) == ""        # unresolvable base = silence
    sc["base_ref"] = _git(a, "rev-parse", "HEAD")
    real = aa._git

    def broken_git(args, cwd, **kw):
        if args[:2] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(args, 128, "", "fatal: boom")
        return real(args, cwd, **kw)

    orig = aa._git
    aa._git = broken_git
    try:
        note = aa._unpersisted_scope_note(sc)
    finally:
        aa._git = orig
    assert "UNKNOWN" in note and "NOT persisted" not in note


def test_hard_note_rides_scope_tag_in_aggregated_note(mixed_lane, monkeypatch):
    root, a, lane = mixed_lane
    monkeypatch.setattr(aa, "_unpersisted_scope_note",
                        lambda sc: "0 commits relative to base X and dirty")
    note = aa._settle_with_gate(_Args(), lane)
    assert "[repo_a] 0 commits relative to base X and dirty" in note


# ---------- F. manifest fail-closed ----------

def test_corrupted_manifest_raises_never_silent_fallback(mixed_lane):
    root, a, lane = mixed_lane
    shared.multi_manifest_path(lane).write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="manifest corrupted"):
        aa._settle_with_gate(_Args(), lane)


# ---------- G. heal anchor ----------

def test_merge_check_self_heal_commits_dirty_member_scope(mixed_lane):
    root, a, lane = mixed_lane
    member = lane / "repo_a"
    base = _git(a, "rev-parse", "HEAD")
    (member / "healed.txt").write_text("heal me\n", encoding="utf-8")
    scopes = aa._lane_scopes(lane, write_set=["repo_a/healed.txt"])
    sc = [s for s in scopes if s["name"] == "repo_a"][0]
    assert sc["write_set"] == ["healed.txt"]  # per-repo rebase feeds the heal admission
    args = _Args(write_set=["repo_a/healed.txt"], base_ref=base)

    import asyncio
    res = asyncio.run(aa._merge_check_one_scope(args, sc, lane, True))

    commits = _commits(member)
    assert commits >= 2  # base commit + the self-heal commit
    clean = [c for c in res["checks"] if c.get("id") == "worktree_clean"]
    assert clean and clean[0]["green"] is True
    # the incident shape is gone: no "settle empty" wording anywhere on the receipt
    # copy-lang-allow:t261016-21
    assert all("settle 返回空" not in str(c.get("detail", "")) for c in res["checks"])
