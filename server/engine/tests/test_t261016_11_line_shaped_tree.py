"""t261016-11 ② evidence item 2: a REAL line-shaped git tree keeps its content.

Reproduces the measured bb73e620 shape end-to-end: a clone of a line revision
carries landed engine content main does not have yet; the three-dot diff
`merge-base(main, line)...line` classifies those paths as changed-outside-any
write set. With the line candidate refs injected, `foreign_files` must never
classify them foreign — the repair has nothing to delete and the tree survives.

Fixture: a tempfile git repo (real git subprocesses), main branch WITHOUT the
content, line branch carrying it. Content source: the real `496aa0c8` blobs
when reachable (`git show 496aa0c8:<path>`), else the embedded byte payloads
below — same paths, same "content main lacks" shape, so the case always runs
(no silent skip); the guard under test judges hash equality, which is internal
to whichever payload is used.
"""
import importlib.util
import os
import subprocess
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, os.pardir, "foreign_write.py")

LINE_PATHS = [
    "server/engine/foreign_write.py",
    "server/engine/tests/test_t261012_09_foreign_write_set.py",
    "integration/t261012-09/sc_t26101209_foreign_restore_merge_gate.py",
]

# deterministic fallback payloads (the shape is what the guard judges)
FALLBACK = {
    LINE_PATHS[0]: '"""carried engine module (line content main lacks)"""\nX = 1\n',
    LINE_PATHS[1]: '"""carried engine test"""\ndef test_x():\n    assert True\n',
    LINE_PATHS[2]: '#!/usr/bin/env python3\nprint("scenario")\n',
}


def _load():
    spec = importlib.util.spec_from_file_location("foreign_write_ut2", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fw = _load()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, timeout=60)


@pytest.fixture()
def line_shaped_repo(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("t26101611-line")
    repo = str(tmp / "repo")
    os.makedirs(repo)
    assert _git(repo, "init", "-q").returncode == 0
    _git(repo, "config", "user.email", "ut@t261016-11")
    _git(repo, "config", "user.name", "ut-t261016-11")

    def w(path, data):
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(data)

    def commit(msg):
        assert _git(repo, "add", "-A").returncode == 0
        assert _git(repo, "commit", "-qm", msg).returncode == 0

    # main: base content only — the line content is absent here
    w("own/work.txt", "the ticket's own write\n")
    commit("main base")
    assert _git(repo, "branch", "line").returncode == 0

    # line: carries landed content main does not have yet
    assert _git(repo, "checkout", "-q", "line").returncode == 0
    for p in LINE_PATHS:
        data = FALLBACK[p]
        got = subprocess.run(["git", "show", "496aa0c8:%s" % p],
                             capture_output=True, text=True, timeout=60)
        if got.returncode == 0 and got.stdout:
            data = got.stdout  # the real landing blobs when reachable
        w(p, data)
    w("line_only_extra.txt", "also landed on the line\n")
    commit("line landing")
    assert _git(repo, "checkout", "-q", "main").returncode == 0
    return repo


def _blob_hash(repo, ref, path):
    p = _git(repo, "rev-parse", "--verify", "--quiet", "%s:%s" % (ref, path))
    return p.stdout.strip() if p.returncode == 0 else None


def _changed_paths(repo):
    mb = _git(repo, "merge-base", "main", "line").stdout.strip()
    p = _git(repo, "-c", "core.quotepath=false", "diff", "--name-status", "-z",
             "%s...line" % mb)
    assert p.returncode == 0, p.stderr
    return [f for _st, f in fw.parse_name_status_z(p.stdout)]


def test_line_carried_paths_never_foreign(line_shaped_repo):
    repo = line_shaped_repo
    changed = _changed_paths(repo)
    assert "server/engine/foreign_write.py" in changed

    # own hash = the tree tip (line) blob; candidates judge against the same
    # line ref — the guard is "present at the line tip with equal bytes".
    def line_face(path):
        refs = [{"ref": "line"}]
        return fw.line_owned(path, _blob_hash(repo, "line", path) or "",
                             lambda p, r: _blob_hash(
                                 repo, r.get("ref") if isinstance(r, dict)
                                 else r, p), refs)

    foreign = fw.foreign_files(changed, ["own/"], line_owned=line_face)
    for p in LINE_PATHS:
        assert p not in foreign, p  # the repair has nothing to delete here
    # a genuinely foreign path (on neither side's tip as line content) is still judged
    assert "line_only_extra.txt" not in foreign  # it IS on the line tip -> owned
    assert foreign == [] or all(p not in LINE_PATHS for p in foreign)


def test_positive_control_without_line_refs_they_are_foreign(line_shaped_repo):
    """The guard is not vacuous: the same tree with no line candidates DOES
    classify the landed content foreign (the measured bb73e620 shape)."""
    repo = line_shaped_repo
    changed = _changed_paths(repo)
    foreign = fw.foreign_files(changed, ["own/"])
    for p in LINE_PATHS:
        assert p in foreign, p
    assert "own/work.txt" not in foreign  # the ticket's own write stays judged


def test_line_tip_hash_used_not_main(line_shaped_repo):
    """Hash equality is judged against the LINE candidate, never main — main
    lacks the content by construction, which is exactly the defect's trigger."""
    repo = line_shaped_repo
    assert _blob_hash(repo, "main", LINE_PATHS[0]) is None
    assert _blob_hash(repo, "line", LINE_PATHS[0]) is not None
