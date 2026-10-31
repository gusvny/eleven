"""t261031-30 unit battery (declared evidence: kind=l1_battery, this file).

Measured fault (261031): `integration/test_anchors.json` is a JSON manifest with one
label per engine test and per registered scenario, judged by
`integration/lint_tests.py` L16/L18. Git cannot marker-merge a JSON object, so ANY two
tickets that each add one anchor entry conflict at squash time. Four landings were
blocked that night; one was refused outright. Each cost a lane resync, a hand union
and a hand recount of `_header.labelled_counts`.

Contract under test (design (b), union with a verified recount):
  - two sides that each add a distinct entry merge to BOTH entries present;
  - an entry only on the main side survives, and so does one only on the lane side;
  - the header counts equal the real dict lengths after the merge, always;
  - an entry-dropping shape (the same key edited on both sides, a dropped key, a
    wrong count) is refused BY NAME, never silently merged;
  - a malformed or absent manifest on either side is a named refusal, never a crash;
  - the no-conflict path is byte-identical to today (the manifest is not touched);
  - a real two-branch landing through the real entry point
    (`agent_activities._squash_merge_core`, the shared recipe used by the main
    close-out AND the develop-line landing) lands both entries and the landed tree
    passes the REAL L16 lint;
  - the merge_check rehearsal judges an anchors-only conflict green only when the
    SAME resolver verifies the union, and names the refusal otherwise.

Zero Temporal server / zero model / zero network. Real `git init` fixtures in tmp
directories; the lint and the canonical writer come from the real tree (copied).

Malformed inputs are fixed fixture strings, never an external source.
"""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]        # server/engine
REPO = Path(__file__).resolve().parents[3]       # tree root
sys.path.insert(0, str(POC))

import agent_activities as aa   # noqa: E402
import anchor_merge as am       # noqa: E402
from shared import MergeCheckArgs  # noqa: E402

MANIFEST = am.MANIFEST_PATH
BASE_TEST = "server/engine/tests/test_fixture_base.py"
MAIN_TEST = "server/engine/tests/test_fixture_main.py"
LANE_TEST = "server/engine/tests/test_fixture_lane.py"


# ---------------------------------------------------------------- helpers

class _Proc:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert not check or p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p


def _entry(tag, anchor="behaviour", **extra):
    out = {"anchor": anchor, "note": "fixture entry %s" % tag}
    out.update(extra)
    return out


def _manifest(engine_tests=None, scenarios=None, header=None):
    hdr = {
        "basis": "fixture basis",
        "labelled_counts": {"engine_tests": len(engine_tests or {}),
                            "scenarios": len(scenarios or {})},
        "vocab": list(am.ANCHOR_VOCAB),
        "what": "fixture manifest (t261031-30 battery)",
    }
    if header:
        hdr.update(header)
    return {"_header": hdr, "engine_tests": dict(engine_tests or {}),
            "scenarios": dict(scenarios or {})}


def _text(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


class _ShowGit:
    """A `git show <ref>:<path>` stand-in: maps ref -> text | _Proc | Exception."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, argv, cwd, timeout=60):
        self.calls.append(list(argv))
        ref = str(argv[1]).split(":", 1)[0]
        val = self.mapping.get(ref)
        if isinstance(val, Exception):
            raise val
        if isinstance(val, _Proc):
            return val
        if val is None:
            return _Proc(1, "", "fatal: path 'x' does not exist in %r" % ref)
        return _Proc(0, val, "")


def _resolve(texts, files=(MANIFEST,)):
    return am.resolve_conflict(_ShowGit(texts), REPO, "ours", "theirs", list(files))


# ---------------------------------------------------------------- fixtures

def _init_repo(path: Path, manifest_obj=None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "integration").mkdir()
    (path / "server/engine/tests").mkdir(parents=True)
    for name in ("lint_tests.py", "run_scenarios.py", "lib_fault_injection.py",
                 "lib_registry.py"):
        shutil.copy2(REPO / "integration" / name, path / "integration" / name)
    base = manifest_obj if manifest_obj is not None else _manifest(
        {BASE_TEST: _entry("base")})
    (path / MANIFEST).write_text(_text(base), encoding="utf-8")
    (path / BASE_TEST).write_text("def test_base():\n    assert True\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _add_entry(repo: Path, test_path: str, tag: str, branch: str = None) -> None:
    """Add one engine-test file plus its anchor entry on the current branch."""
    if branch:
        _git("checkout", "-B", branch, cwd=repo)
    obj = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    (repo / test_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / test_path).write_text("def test_%s():\n    assert True\n" % tag,
                                  encoding="utf-8")
    obj["engine_tests"][test_path] = _entry(tag)
    obj["_header"]["labelled_counts"]["engine_tests"] = len(obj["engine_tests"])
    (repo / MANIFEST).write_text(_text(obj), encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "add anchor %s" % tag, cwd=repo)


def _relabel(repo: Path, test_path: str, anchor: str, msg: str) -> None:
    """Rewrite one entry's anchor on the current branch and commit it."""
    obj = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    obj["engine_tests"][test_path] = _entry("base", anchor=anchor)
    (repo / MANIFEST).write_text(_text(obj), encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)


def _two_branch_repo(tmp_path: Path) -> Path:
    """main adds MAIN_TEST, lane adds LANE_TEST: both sides change the manifest."""
    repo = _init_repo(tmp_path / "proj")
    _git("checkout", "-B", "lane", cwd=repo)
    _add_entry(repo, LANE_TEST, "lane")
    _git("checkout", "main", cwd=repo)
    _add_entry(repo, MAIN_TEST, "main")
    return repo


def _lint16(repo: Path):
    return subprocess.run([sys.executable, "integration/lint_tests.py", "--rules=L16"],
                          cwd=str(repo), capture_output=True, text=True, timeout=180)


# ---------------------------------------------------------------- 1. the union

def test_both_sides_adding_a_distinct_entry_keep_both():
    ours = _manifest({BASE_TEST: _entry("base"), MAIN_TEST: _entry("main")})
    theirs = _manifest({BASE_TEST: _entry("base"), LANE_TEST: _entry("lane")})
    merged, note = am.union_manifests(ours, theirs)
    assert set(merged["engine_tests"]) == {BASE_TEST, MAIN_TEST, LANE_TEST}
    assert merged["_header"]["labelled_counts"] == {"engine_tests": 3, "scenarios": 0}
    assert "main-only=1" in note and "lane-only=1" in note and "shared=1" in note
    am.verify_union([("main", ours), ("lane", theirs)], merged)


def test_main_only_entry_survives():
    ours = _manifest({MAIN_TEST: _entry("main")})
    theirs = _manifest({LANE_TEST: _entry("lane")})
    merged, _note = am.union_manifests(ours, theirs)
    assert merged["engine_tests"][MAIN_TEST] == _entry("main")


def test_lane_only_entry_survives():
    ours = _manifest({MAIN_TEST: _entry("main")})
    theirs = _manifest({LANE_TEST: _entry("lane")})
    merged, _note = am.union_manifests(ours, theirs)
    assert merged["engine_tests"][LANE_TEST] == _entry("lane")


def test_counts_equal_real_lengths_for_both_trees():
    sc_main = "integration/t26103130/sc_main.py"
    sc_lane = "integration/t26103130/sc_lane.py"
    ours = _manifest({MAIN_TEST: _entry("main")}, {sc_main: _entry("scmain")})
    theirs = _manifest({LANE_TEST: _entry("lane")}, {sc_lane: _entry("sclane")})
    merged, _note = am.union_manifests(ours, theirs)
    counts = merged["_header"]["labelled_counts"]
    assert counts == {"engine_tests": len(merged["engine_tests"]),
                      "scenarios": len(merged["scenarios"])}
    assert counts == {"engine_tests": 2, "scenarios": 2}
    am.verify_union([("main", ours), ("lane", theirs)], merged)


def test_identical_entry_on_both_sides_is_kept_once():
    entry = _entry("shared")
    ours = _manifest({MAIN_TEST: entry})
    theirs = _manifest({MAIN_TEST: dict(entry)})
    merged, _note = am.union_manifests(ours, theirs)
    assert merged["engine_tests"] == {MAIN_TEST: entry}


def test_displaced_duplicate_of_a_judged_entry_is_dropped_and_named():
    """Measured 261031: this tree's own manifest carried five correct entries one
    level too high. L16/L18 read only the trees, so the rot was invisible."""
    judged = {BASE_TEST: _entry("base"), MAIN_TEST: _entry("main")}
    ours = dict(_manifest(judged))
    ours[MAIN_TEST] = _entry("main", anchor="contract")  # the displaced duplicate
    theirs = _manifest(judged)
    merged, note = am.union_manifests(ours, theirs)
    assert MAIN_TEST not in merged                       # no rot at the top level
    assert merged["engine_tests"][MAIN_TEST] == _entry("main")
    assert "dropped 1 displaced duplicate" in note and MAIN_TEST in note
    am.verify_union([("main", ours), ("lane", theirs)], merged)


def test_displaced_unjudged_entry_is_moved_into_its_tree():
    ours = dict(_manifest({BASE_TEST: _entry("base")}))
    ours[LANE_TEST] = _entry("lane")                     # displaced, not judged yet
    theirs = _manifest({BASE_TEST: _entry("base")})
    merged, note = am.union_manifests(ours, theirs)
    assert LANE_TEST not in merged
    assert merged["engine_tests"][LANE_TEST] == _entry("lane")
    assert merged["_header"]["labelled_counts"]["engine_tests"] == 2
    assert "moved 1 displaced entry" in note
    am.verify_union([("main", ours), ("lane", theirs)], merged)


def test_two_sides_disagreeing_on_a_displaced_entry_refused_by_name():
    ours = dict(_manifest({BASE_TEST: _entry("base")}))
    ours[LANE_TEST] = _entry("lane", anchor="behaviour")
    theirs = dict(_manifest({BASE_TEST: _entry("base")}))
    theirs[LANE_TEST] = _entry("lane", anchor="contract")
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_TOPLEVEL_DIVERGED


def test_displaced_entry_with_an_unnamed_tree_refused_by_name():
    ours = dict(_manifest({BASE_TEST: _entry("base")}))
    ours["notes/somewhere.py"] = _entry("odd")
    theirs = _manifest({BASE_TEST: _entry("base")})
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_MALFORMED


# ---------------------------------------------------------------- 2. refusals

def test_same_key_different_values_refused_by_name():
    ours = _manifest({MAIN_TEST: _entry("main", anchor="behaviour")})
    theirs = _manifest({MAIN_TEST: _entry("main", anchor="contract")})
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_ENTRY_CONFLICT
    assert ei.value.name in str(ei.value) and MAIN_TEST in ei.value.detail


def test_header_prose_divergence_refused_by_name():
    ours = _manifest({MAIN_TEST: _entry("main")})
    theirs = _manifest({MAIN_TEST: _entry("main")},
                       header={"what": "a different sentence"})
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_HEADER_DIVERGED


def test_unlabelled_entry_refused_by_name():
    ours = _manifest({MAIN_TEST: {"note": "no anchor at all"}})
    theirs = _manifest({LANE_TEST: _entry("lane")})
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_UNLABELLED
    assert MAIN_TEST in ei.value.detail

    ours = _manifest({MAIN_TEST: _entry("main", anchor="vibes")})
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_UNLABELLED


def test_snapshot_entry_without_sync_path_refused_by_name():
    ours = _manifest({MAIN_TEST: _entry("main", anchor="production-snapshot")})
    theirs = _manifest({LANE_TEST: _entry("lane")})
    with pytest.raises(am.AnchorRefusal) as ei:
        am.union_manifests(ours, theirs)
    assert ei.value.name == am.R_SNAPSHOT_NO_SYNC


def test_verify_refuses_a_dropped_entry_and_a_changed_one():
    ours = _manifest({MAIN_TEST: _entry("main")})
    theirs = _manifest({LANE_TEST: _entry("lane")})
    merged, _note = am.union_manifests(ours, theirs)

    dropped = json.loads(json.dumps(merged))
    del dropped["engine_tests"][MAIN_TEST]
    dropped["_header"]["labelled_counts"]["engine_tests"] = 1
    with pytest.raises(am.AnchorRefusal) as ei:
        am.verify_union([("main", ours), ("lane", theirs)], dropped)
    assert ei.value.name == am.R_LOST and MAIN_TEST in ei.value.detail

    changed = json.loads(json.dumps(merged))
    changed["engine_tests"][LANE_TEST] = _entry("lane", anchor="contract")
    with pytest.raises(am.AnchorRefusal) as ei:
        am.verify_union([("main", ours), ("lane", theirs)], changed)
    assert ei.value.name == am.R_LOST

    wrong_count = json.loads(json.dumps(merged))
    wrong_count["_header"]["labelled_counts"]["engine_tests"] = 7
    with pytest.raises(am.AnchorRefusal) as ei:
        am.verify_union([("main", ours), ("lane", theirs)], wrong_count)
    assert ei.value.name == am.R_COUNT and "7" in ei.value.detail


@pytest.mark.parametrize("text,name,needle", [
    ("{not json at all", am.R_MALFORMED, "not JSON"),
    ("[]", am.R_MALFORMED, "not an object"),
    (json.dumps({"_header": {"labelled_counts": {}}}), am.R_MALFORMED, "engine_tests"),
    (json.dumps({"_header": {"labelled_counts": {}}, "engine_tests": {},
                 "scenarios": {}, "extra_section": {}}),
     am.R_MALFORMED, "neither an engine test nor a scenario path"),
    (json.dumps({"engine_tests": {}, "scenarios": {}}), am.R_MALFORMED, "_header"),
])
def test_malformed_side_is_a_named_refusal_not_a_crash(text, name, needle):
    good = _text(_manifest({MAIN_TEST: _entry("main")}))
    res = _resolve({"ours": good, "theirs": text})
    assert res.status == "refused"
    assert res.name == name and needle in res.detail


def test_absent_manifest_on_a_side_is_a_named_refusal():
    good = _text(_manifest({MAIN_TEST: _entry("main")}))
    res = _resolve({"ours": good, "theirs": None})
    assert res.status == "refused" and res.name == am.R_UNREADABLE
    assert "theirs" in res.detail
    res = _resolve({"ours": None, "theirs": good})
    assert res.status == "refused" and res.name == am.R_UNREADABLE
    assert "ours" in res.detail


def test_a_faulting_git_runner_is_a_named_refusal():
    res = am.resolve_conflict(_ShowGit({"ours": RuntimeError("git vanished")}),
                              REPO, "ours", "theirs", [MANIFEST])
    assert res.status == "refused" and res.name == am.R_RESOLVER
    assert "git vanished" in res.detail


def test_non_anchor_conflicts_are_not_ours():
    res = _resolve({}, files=("src/app.py",))
    assert res.status == "not_applicable"
    res = _resolve({}, files=(MANIFEST, "src/app.py"))
    assert res.status == "not_applicable" and "src/app.py" in res.detail


def test_refusal_names_are_declared_stable_protocol_words():
    names = [am.R_UNREADABLE, am.R_MALFORMED, am.R_HEADER_DIVERGED,
             am.R_ENTRY_CONFLICT, am.R_UNLABELLED, am.R_SNAPSHOT_NO_SYNC,
             am.R_LOST, am.R_COUNT, am.R_TOPLEVEL_DIVERGED, am.R_WRITER,
             am.R_RESOLVER, am.R_STAGE]
    assert len(set(names)) == len(names)
    assert all(n.startswith("anchors_") for n in names)


# ---------------------------------------------------------------- 3. writer

def test_apply_uses_the_canonical_writer_and_reads_back(tmp_path):
    repo = _init_repo(tmp_path / "proj")
    ours = _manifest({MAIN_TEST: _entry("main")})
    theirs = _manifest({LANE_TEST: _entry("lane")})
    merged, note = am.union_manifests(ours, theirs)
    res = am.Resolution("resolved", obj=merged, note=note)
    target = am.apply_resolution(repo, res)
    on_disk = target.read_text(encoding="utf-8")
    assert on_disk == am.canonical_bytes(repo, merged)
    assert json.loads(on_disk) == merged

    with pytest.raises(am.AnchorRefusal) as ei:
        am.apply_resolution(repo, am.Resolution("refused", name=am.R_LOST))
    assert ei.value.name == am.R_RESOLVER


# ---------------------------------------------------------------- 4. real git

def test_real_landing_keeps_both_entries_and_passes_l16(tmp_path):
    repo = _two_branch_repo(tmp_path)
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip() == "main"

    core = aa._squash_merge_core(repo, "lane")
    assert core.status == "merged", core.error
    assert core.refusal == ""
    assert "anchor manifest unioned" in core.resolution_note
    assert core.staged_empty is False
    _git("commit", "-m", "landing t26103130 fixture", cwd=repo)

    obj = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    assert set(obj["engine_tests"]) == {BASE_TEST, MAIN_TEST, LANE_TEST}
    assert obj["engine_tests"][MAIN_TEST] == _entry("main")
    assert obj["engine_tests"][LANE_TEST] == _entry("lane")
    assert obj["_header"]["labelled_counts"] == {
        "engine_tests": len(obj["engine_tests"]),
        "scenarios": len(obj["scenarios"])}
    # a single landing commit on main, one parent (the squash shape is unchanged)
    assert _git("rev-list", "--count", "HEAD", cwd=repo).stdout.strip() == "3"
    assert len(_git("rev-list", "--parents", "-n", "1", "HEAD",
                    cwd=repo).stdout.split()) == 2

    lint = _lint16(repo)
    assert lint.returncode == 0, lint.stdout + lint.stderr
    assert "LINT done: 0 error / 0 warn" in lint.stdout, lint.stdout
    # the real coverage line fired (it starts with this ASCII prefix)
    assert "ok    L16 anchor" in lint.stdout, lint.stdout


def test_no_conflict_path_is_byte_identical(tmp_path):
    """Only the lane moved the manifest: git merges it cleanly and the resolver
    must not touch it (today's bytes, not a re-serialization)."""
    repo = _init_repo(tmp_path / "proj")
    _git("checkout", "-B", "lane", cwd=repo)
    _add_entry(repo, LANE_TEST, "lane")
    lane_bytes = _git("show", "lane:%s" % MANIFEST, cwd=repo).stdout
    _git("checkout", "main", cwd=repo)

    core = aa._squash_merge_core(repo, "lane")
    assert core.status == "merged", core.error
    assert core.resolution_note == "" and core.refusal == ""
    _git("commit", "-m", "landing t26103130 fixture", cwd=repo)
    assert (repo / MANIFEST).read_text(encoding="utf-8") == lane_bytes


def test_real_delete_modify_shape_is_named_and_tree_restored(tmp_path):
    """The lane deletes the manifest: absent on one side is a NAMED refusal, and the
    three-step cleanup still restores the tree (no unmerged residue)."""
    repo = _init_repo(tmp_path / "proj")
    _git("checkout", "-B", "lane", cwd=repo)
    _git("rm", "-q", MANIFEST, cwd=repo)
    _git("commit", "-m", "lane drops the manifest", cwd=repo)
    _git("checkout", "main", cwd=repo)
    _add_entry(repo, MAIN_TEST, "main")

    core = aa._squash_merge_core(repo, "lane")
    assert core.status == "conflict"
    assert core.refusal == am.R_UNREADABLE
    assert am.R_UNREADABLE in core.error
    # the conflict state is restored: no unmerged entries, no merge in progress
    assert _git("ls-files", "-u", cwd=repo).stdout.strip() == ""
    assert "UU" not in _git("status", "--porcelain", cwd=repo).stdout
    main_obj = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))
    assert set(main_obj["engine_tests"]) == {BASE_TEST, MAIN_TEST}


def test_real_same_key_edit_on_both_sides_is_named_and_tree_restored(tmp_path):
    repo = _init_repo(tmp_path / "proj")
    _git("checkout", "-B", "lane", cwd=repo)
    _relabel(repo, BASE_TEST, "contract", "lane relabels the base entry")
    _git("checkout", "main", cwd=repo)
    _relabel(repo, BASE_TEST, "source-text", "main relabels the base entry")

    core = aa._squash_merge_core(repo, "lane")
    assert core.status == "conflict" and core.refusal == am.R_ENTRY_CONFLICT
    assert am.R_ENTRY_CONFLICT in core.error
    assert _git("ls-files", "-u", cwd=repo).stdout.strip() == ""


# ---------------------------------------------------------------- 5. rehearsal

def _merge_check_args(lane: Path, branch: str, write_set):
    return MergeCheckArgs(ticket_id="t26103130ut", worktree=str(lane),
                          branch=branch, write_set=list(write_set))


def _no_verify_spawn(*a, **k):
    raise RuntimeError("verify spawn stubbed (this case judges the rehearsal only)")


def _rehearsal_item(repo: Path, lane: Path, branch: str, monkeypatch):
    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _no_verify_spawn)
    sc = {"tree": lane, "repo": repo, "branch": branch, "base_ref": "main",
          "write_set": [MANIFEST], "name": "", "repo_rel": ""}
    core = asyncio.run(aa._merge_check_one_scope(
        _merge_check_args(lane, branch, [MANIFEST]), sc, lane, False))
    items = [c for c in core["checks"] if c.get("id") == "merge_rehearsal"]
    assert len(items) == 1
    assert core["checks"][-1].get("id") == "merge_rehearsal"  # position pinned
    return items[0], core


def test_rehearsal_judges_an_anchors_only_conflict_green(tmp_path, monkeypatch):
    repo = _two_branch_repo(tmp_path)
    lane = tmp_path / "lane"
    _git("worktree", "add", str(lane), "lane", cwd=repo)
    item, core = _rehearsal_item(repo, lane, "lane", monkeypatch)
    assert item["green"] is True, item
    assert "anchor manifest unioned" in item["detail"]
    assert core["rehearsal_green"] is True


def test_rehearsal_names_a_refused_anchors_conflict(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "proj")
    _git("checkout", "-B", "lane", cwd=repo)
    _relabel(repo, BASE_TEST, "contract", "lane relabels the base entry")
    _git("checkout", "main", cwd=repo)
    _relabel(repo, BASE_TEST, "source-text", "main relabels the base entry")
    lane = tmp_path / "lane"
    _git("worktree", "add", str(lane), "lane", cwd=repo)
    item, core = _rehearsal_item(repo, lane, "lane", monkeypatch)
    assert item["green"] is False, item
    assert am.R_ENTRY_CONFLICT in item["detail"]
    assert core["rehearsal_green"] is False
