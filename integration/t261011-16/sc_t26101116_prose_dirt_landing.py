#!/usr/bin/env python3
"""sc_t261011_16_prose_dirt_landing.py — L3 grey-box scenario for ticket t261011-16.

Lands a fixture ticket (real tmp git repo, _squash_merge called directly, no
Temporal / no models / no network) while an exempted prose file
(notes/discussion.md) sits UNCOMMITTED on main, then reads the resulting merge
commit's file list back. Hard evidence required by the ticket:

  A. the merge commit's file list does NOT contain the prose file, and the file
     is still on disk byte-identical after the merge (the 260908 auto-stash red
     line: nobody quietly touches an owner's edits);
  B. INVERTED CONTROL (review comment 3, made concrete): an inline replica of
     the PRE-FIX conservative rule ("any uncommitted tracked change blocks,
     overlapping or not") is asserted to refuse the exact same fixture state —
     the same scenario records both runs, old rule refuses / new rule lands;
  C. canaries keep their teeth: a dirty CODE file refuses (named), a STAGED
     prose file refuses (named), an untracked file colliding with the merge
     surface refuses (named);
  D. a dirty prose file the merge surface DOES touch ends in a NAMED refusal.

Run: python3 integration/t261011-16/sc_t261011_16_prose_dirt_landing.py
     (or via the project venv python; git must be on PATH, else ENV_FAIL exit 2)
Exit: 0 = all green, 1 = red, 2 = environment failure.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "engine"))

import agent_activities as aa  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    print(("  ok   %s" if cond else "  FAIL %s") % label)
    if cond:
        PASS += 1
    else:
        FAIL += 1


def git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        print("  ENV git %s failed: %s" % (" ".join(args), p.stderr.strip()[:200]))
        sys.exit(2)
    return p.stdout


def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "sc@example.com", cwd=path)
    git("config", "user.name", "sc", cwd=path)
    (path / ".gitignore").write_text(".lane/\n", encoding="utf-8")
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    (path / "notes").mkdir()
    (path / "notes" / "discussion.md").write_text("tracked base\n", encoding="utf-8")
    git("add", "-A", cwd=path)
    git("commit", "-m", "base", cwd=path)
    return path


def make_lane(root, ticket="t26101116sc"):
    br = "lane/%s" % ticket
    lane = root / ".lane" / ticket
    git("worktree", "add", "-b", br, str(lane), cwd=root)
    (lane / "f.txt").write_text("lane change\n", encoding="utf-8")
    git("add", "-A", cwd=lane)
    git("commit", "-m", "lane work", cwd=lane)
    return lane, br


def dirty_tracked(repo):
    """The tracked-dirty face of git status, one status read."""
    out = git("status", "--porcelain", cwd=repo)
    names = []
    for line in out.splitlines():
        xy, _, path = line[:2], line[2:3], line[3:]
        if xy.strip() and xy != "??" and path:
            names.append(path.strip())
    return names


def prefix_refuses(repo, branch):
    """INVERTED CONTROL: an inline replica of the PRE-FIX conservative rule (any
    uncommitted tracked change blocks, overlapping or not). Asserted against the
    SAME fixture state the new classifier exempts — old rule refuses, new rule
    lands. Deliberately NOT imported from agent_activities: it must not drift
    with the fix."""
    return bool(dirty_tracked(repo))


def snapshot(repo):
    note = repo / "notes" / "discussion.md"
    return {"stash": git("stash", "list", cwd=repo),
            "bytes": note.read_bytes() if note.exists() else b""}


def main():
    print("== t261011-16 prose-dirt landing (L3, real tmp git repos) ==")
    tmp = Path(tempfile.mkdtemp(prefix="sc_t26101116_"))

    # A. Landing with an exempted prose file dirty on main -------------------
    print("A exempted prose dirt does not block; owner bytes survive")
    root = init_repo(tmp / "a")
    lane, br = make_lane(root)
    note = root / "notes" / "discussion.md"
    note.write_text("owner edit\n", encoding="utf-8")  # unstaged, tracked, prose
    v = aa._classify_main_dirty(root, br)
    ok(v.get("kind") == "", "A1 classifier exempts (kind empty)")
    ok(v.get("exempted") == ["notes/discussion.md"],
       "A2 exemption is observable (exempted names the file)")
    old_rule_refuses = prefix_refuses(root, br)
    ok(old_rule_refuses,
       "B1 inverted control: the pre-fix conservative rule REFUSES this same state")
    ok(old_rule_refuses and v.get("kind") == "",
       "A3 the two rules disagree on this exact state: old refuses, new lands")
    res = aa._squash_merge(root, lane, br, "t26101116sc", defer_teardown=True)
    ok(res.ok and res.action == "merged" and res.merge_commit, "A4 close-out lands")
    if res.ok and res.merge_commit:
        names = git("show", "--name-only", "--format=", res.merge_commit,
                    cwd=root).split()
        ok("f.txt" in names, "A5 the ticket's own delivery is in the commit")
        ok("notes/discussion.md" not in names,
           "A6 the merge commit does NOT contain the prose file")
    ok(note.read_bytes() == b"owner edit\n",
       "A7 the owner's file is byte-identical on disk after the merge")
    ok(snapshot(root)["stash"] == "", "A8 no auto-stash happened")
    ok("prose dirt exempted" in (res.error or ""),
       "A9 the exemption is recorded on the receipt")

    # B. Inverted control, spelled out ---------------------------------------
    print("B inverted control (old rule vs new rule, same fixture)")
    ok(prefix_refuses and v.get("kind") == "",
       "B2 same dirty state: old rule refuse / new rule land (both recorded)")

    # C. Canaries keep their teeth -------------------------------------------
    print("C canaries: code dirt / staged prose / untracked collision")
    root = init_repo(tmp / "c")
    lane, br = make_lane(root)
    (root / "other.py").write_text("tracked base\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-m", "add code", cwd=root)
    (root / "other.py").write_text("code edit\n", encoding="utf-8")
    v = aa._classify_main_dirty(root, br)
    res = aa._squash_merge(root, lane, br, "t26101116sc", defer_teardown=True)
    ok(v.get("kind") == "main_dirty" and "other.py" in v.get("files", []),
       "C1 dirty CODE file refuses, named")
    ok(not res.ok and res.action == "dirty" and res.reason == "main_dirty"
       and "other.py" in res.files, "C2 merge act refuses with the file named")
    ok((root / "other.py").read_bytes() == b"code edit\n",
       "C3 the code file is untouched on the failure path")

    root = init_repo(tmp / "c2")
    lane, br = make_lane(root)
    (root / "notes" / "discussion.md").write_text("owner staged\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    res = aa._squash_merge(root, lane, br, "t26101116sc", defer_teardown=True)
    ok(not res.ok and res.reason == "main_staged"
       and "notes/discussion.md" in res.files, "C4 STAGED prose still refuses")

    root = init_repo(tmp / "c3")
    lane, br = make_lane(root)
    (lane / "g.txt").write_text("new from lane\n", encoding="utf-8")
    git("add", "-A", cwd=lane)
    git("commit", "-m", "add g", cwd=lane)
    (root / "g.txt").write_text("host untracked collision\n", encoding="utf-8")
    res = aa._squash_merge(root, lane, br, "t26101116sc", defer_teardown=True)
    ok(not res.ok and res.reason == "untracked_collision"
       and "g.txt" in res.files, "C5 untracked collision still refuses")

    # D. Overlapping prose dirt -> named refusal ------------------------------
    print("D prose dirt overlapping the merge surface")
    root = init_repo(tmp / "d")
    lane, br = make_lane(root)
    (lane / "notes" / "discussion.md").write_text("lane side\n", encoding="utf-8")
    git("add", "-A", cwd=lane)
    git("commit", "-m", "lane touches the note", cwd=lane)
    (root / "notes" / "discussion.md").write_text("owner edit\n", encoding="utf-8")
    res = aa._squash_merge(root, lane, br, "t26101116sc", defer_teardown=True)
    ok(not res.ok and res.reason == "main_dirty"
       and "notes/discussion.md" in res.files,
       "D1 overlapping prose dirt ends in a NAMED refusal")
    ok((root / "notes" / "discussion.md").read_bytes() == b"owner edit\n",
       "D2 the owner's bytes survive the refusal")
    ok(lane.is_dir(), "D3 the lane stays alive for re-verification")

    # E. Unknown merge surface: prose dirt still refuses (fail-closed) --------
    print("E fail-closed on an unknown merge surface")
    root = init_repo(tmp / "e")
    lane, br = make_lane(root)
    (root / "notes" / "discussion.md").write_text("owner edit\n", encoding="utf-8")
    # A branch git parses as an option makes the merge-surface diff fail: the
    # surface is UNKNOWN, so the exemption must NOT fire (review gen0 binding).
    v = aa._classify_main_dirty(root, "-bad-branch")
    ok(v.get("kind") == "main_dirty" and "notes/discussion.md" in v.get("files", []),
       "E1 with the surface unknown, prose dirt still refuses, named")
    ok("exempted" not in v, "E2 the refusal shape carries no exemption face")

    print("\n%d passed / %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except Exception:
        print("ENV_FAIL: git is not available on PATH")
        sys.exit(2)
    sys.exit(main())
