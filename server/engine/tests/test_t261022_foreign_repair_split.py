# -*- coding: utf-8 -*-
"""t261022 (KI-332): merge_check's foreign-file repair reads TWO populations.

Measured defect (host order 261022): the pre-check `foreign_file_repair` runs
before items 1 and 3, so the later items read a repaired branch. It was built
for ONE population — another lane's unlanded work absorbed into this lane by a
worker-settled conflict resolution (foreign_write.py documents that scope) — and
it also ate the SECOND population: the ticket's OWN committed write outside its
write set. That file "belongs to no live lane" too, so the engine deleted it,
landed an engine repair commit, and the write-set judge then diffed a clean
branch and reported green. Measured on t261022-04: scenario
t260915-05-detail-lane-reds commits server/zz_t26091505_probe.py with write set
docs/, expects blocked at merge_check with verify_red, and instead reached
stage=merge awaiting-human with merge_check green.

What this battery pins (all cases run against REAL temp git repos — the
classification is a git-history question, so a stub would assert nothing):

  A. (a) population — a file authored by the conflict-resolution MERGE commit is
     still repaired (restored/removed + one engine commit) and the receipt item
     carries the classification record: population, the evidence, the authoring
     commits, and the repair commit id. The landed commit message names the
     population it decided.
  B. (b) population — the ticket's own out-of-write-set commit is NEVER
     repaired: no repair commit, the file is STILL PRESENT after the check, and
     the round carries a red item that names the file (reason_code
     foreign_ticket_own_out_of_set). The write-set judge owns the verdict: the
     item is placed after the per-scope items, before the merge rehearsal, so
     `blocked_detail` keeps the judge's verify_red as its primary red.
  C. ambiguous populations fail CLOSED to red, never to a repair: mixed
     authorship (a merge commit AND a lane commit) / no authoring commit inside
     base..HEAD / an attribution fault each answer a red refusal item and leave
     every file in place.
  D. replay — the split sits behind workflow.patched(); un-patched histories get
     the PRE-SPLIT face verbatim (same tree, split=False: the own file IS
     repaired, no record, no refusal items), the activity argument defaults to
     False (old payloads), and both lanes pass it inside workflow.patched().
     A real historical history file is not part of this L1 battery: the repo's
     idiom for the replay promise is the un-patched branch plus the argument
     default plus the call-site anchor (see test_t260904_18_gate_pure /
     test_t261019_39_bundle_rework), and the L3 journey exercises the real
     workflow.

Out of scope here (by design): the end-to-end blocked receipt — the in-lane
verify_lane write-set judge naming the file (`verify_red`) is the L3 scenario
integration/t260915-05, which this ticket leaves red for the integration side
(no anchor is registered on this lane).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402

TID = "t261022-10"
WRITE_SET = ["docs/"]
OWN_OUT_OF_SET = "server/zz_probe_t261022.py"
ABSORBED = "server/absorbed_sibling.py"


# ---------- fixtures: real temp git repos ----------

def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return (p.stdout or "").strip()


def _commit(repo: Path, name: str, text: str, msg: str) -> str:
    f = repo / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


def _base_repo(tmp_path: Path) -> Path:
    """main with one commit, a `lane` branch, and `lane` checked out."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "ut@example.com", cwd=repo)
    _git("config", "user.name", "ut", cwd=repo)
    _commit(repo, "base.txt", "base\n", "c0")
    _git("branch", "lane", cwd=repo)
    _git("checkout", "-q", "lane", cwd=repo)
    return repo


def _pollution_lane(tmp_path: Path) -> Path:
    """The (a) shape: main advanced, and the lane's conflict-resolution MERGE
    commit absorbed a sibling file (present in NEITHER parent)."""
    repo = _base_repo(tmp_path)
    _commit(repo, "docs/own.md", "own\n", "ticket write inside the set")
    _git("checkout", "-q", "main", cwd=repo)
    _commit(repo, "m.txt", "m\n", "main advances")
    _git("checkout", "-q", "lane", cwd=repo)
    _git("merge", "--no-commit", "--no-ff", "main", cwd=repo)
    _commit(repo, ABSORBED, "SIBLING = 1\n", "resolution commit: absorbed sibling")
    return repo


def _own_lane(tmp_path: Path) -> Path:
    """The (b) shape: the ticket's own plain lane commit, outside the write set."""
    repo = _base_repo(tmp_path)
    _commit(repo, OWN_OUT_OF_SET, "probe\n", "probe: out-of-write-set write")
    return repo


def _mixed_lane(tmp_path: Path) -> Path:
    """The ambiguous shape: the merge commit absorbed the file and a PLAIN lane
    commit then edited it — the evidence names two different populations."""
    repo = _pollution_lane(tmp_path)
    _commit(repo, ABSORBED, "SIBLING = 2\n", "lane edits the absorbed file")
    return repo


def _check(repo: Path, write_set=WRITE_SET, split=True, ticket_id=TID):
    return aa._foreign_repair_check_item(repo, "lane", list(write_set),
                                         ticket_id, split=split)


# ---------- A. the pollution population is still repaired, with its record ----

def test_pollution_population_is_repaired_with_its_record(tmp_path):
    repo = _pollution_lane(tmp_path)
    out = _check(repo)

    assert out["own_items"] == []
    item = out["item"]
    assert item is not None, out
    assert item["green"] is True, item
    assert item["id"] == aa.FOREIGN_REPAIR_ID
    assert ABSORBED in item["files"]

    rec = out["record"]
    assert rec["patch_id"] == aa.FOREIGN_REPAIR_SPLIT_PATCH_ID
    assert rec["rule"] == aa.FOREIGN_REPAIR_SPLIT_RULE
    entry = rec["files"][ABSORBED]
    assert entry["population"] == aa.FOREIGN_POPULATION_POLLUTION, entry
    assert "conflict-resolution/merge commits" in entry["evidence"], entry
    assert len(entry["commits"]) == 1 and entry["commits"][0]["parents"] >= 2, entry
    assert rec["repaired"] == [ABSORBED]
    assert rec["left_in_place"] == []
    # The record reaches the receipt item itself, not only a log line.
    assert item["foreign_repair"] is rec

    # The repair landed: the file is gone and one engine commit carries it.
    assert not (repo / ABSORBED).exists()
    head = _git("rev-parse", "--short", "HEAD", cwd=repo)
    assert rec["repair_commit"] == head, rec
    assert rec["repair_commit_paths"] == [ABSORBED]
    msg = _git("log", "-1", "--format=%B", cwd=repo)
    assert ("population %s: %s" % (ABSORBED, aa.FOREIGN_POPULATION_POLLUTION)) in msg, msg
    assert "conflict-resolution" in msg, msg   # the rule text rides in the commit too
    # The ticket's own in-write-set write is untouched by the repair.
    assert (repo / "docs" / "own.md").exists()


def test_pollution_and_own_are_split_in_one_round(tmp_path):
    """Both populations in the same diff: only the absorbed file is repaired."""
    repo = _pollution_lane(tmp_path)
    _commit(repo, OWN_OUT_OF_SET, "probe\n", "probe: out-of-write-set write")
    before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo)

    rec = out["record"]
    assert rec["files"][ABSORBED]["population"] == aa.FOREIGN_POPULATION_POLLUTION
    assert rec["files"][OWN_OUT_OF_SET]["population"] == aa.FOREIGN_POPULATION_OWN
    assert rec["repaired"] == [ABSORBED]
    assert rec["left_in_place"] == [OWN_OUT_OF_SET]
    assert out["item"]["green"] is True, out["item"]     # the pole it owns is clean
    assert not (repo / ABSORBED).exists()
    assert (repo / OWN_OUT_OF_SET).exists()              # never repaired, never deleted
    # exactly one new commit (the engine repair), and no commit touched the own file
    assert _git("rev-list", "--count", "%s..HEAD" % before, cwd=repo) == "1"
    assert _git("log", "-1", "--format=%s", "--", OWN_OUT_OF_SET, cwd=repo) \
        == "probe: out-of-write-set write"


# ---------- B. the ticket's own out-of-write-set commit is red, never repaired ----

def test_own_out_of_set_file_is_red_and_still_present(tmp_path):
    repo = _own_lane(tmp_path)
    head_before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo)

    # Nothing repairable => the repair face says nothing (no green item).
    assert out["item"] is None, out
    assert len(out["own_items"]) == 1, out
    red = out["own_items"][0]
    assert red["green"] is False
    assert red["id"] == aa.FOREIGN_REPAIR_ID
    assert red["reason_code"] == "foreign_ticket_own_out_of_set"
    assert red["files"] == [OWN_OUT_OF_SET]
    assert OWN_OUT_OF_SET in red["detail"]
    assert red["next_action"]

    rec = out["record"]
    entry = rec["files"][OWN_OUT_OF_SET]
    assert entry["population"] == aa.FOREIGN_POPULATION_OWN, entry
    assert "this ticket's own lane commit" in entry["evidence"], entry
    assert entry["commits"][0]["sha"] == head_before, entry
    assert entry["commits"][0]["parents"] == 1, entry
    assert rec["repaired"] == [] and rec["repair_commit"] == ""
    assert rec["left_in_place"] == [OWN_OUT_OF_SET]
    assert red["foreign_repair"] is rec                  # the record reaches the red

    # THE defect: no repair commit, and the file the write-set judge must see is
    # still there.
    assert _git("rev-parse", "HEAD", cwd=repo) == head_before
    assert (repo / OWN_OUT_OF_SET).exists()
    assert (repo / OWN_OUT_OF_SET).read_text("utf-8") == "probe\n"


def test_refusal_items_are_placed_before_the_rehearsal_item():
    """Ownership of the primary red: the activity places the refusal items AFTER
    the per-scope items (the write-set judge's verify_red owns blocked_detail)
    and BEFORE the rehearsal item (checks[-1] stays the merge rehearsal, so the
    red is human-classified, never auto-resolved)."""
    src = (POC / "agent_activities.py").read_text("utf-8")
    assert "for _own in foreign_own_reds:\n        checks.insert(max(len(checks) - 1, 0), _own)" in src
    # the insertion sits after the scope loop and before the fuse-B insertion
    i_loop = src.index("core = await _merge_check_one_scope(")
    i_reds = src.index("for _own in foreign_own_reds:")
    i_fuse = src.index("fuse_b_err = multirepo_materialization_error(")
    assert i_loop < i_reds < i_fuse


# ---------- C. ambiguous classifications fail closed to red ----

def test_mixed_authorship_is_ambiguous_and_never_repaired(tmp_path):
    repo = _mixed_lane(tmp_path)
    head_before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo)

    assert out["item"] is None, out
    assert len(out["own_items"]) == 1, out
    red = out["own_items"][0]
    assert red["green"] is False
    assert red["reason_code"] == "foreign_classification_ambiguous"
    assert red["files"] == [ABSORBED]
    rec = out["record"]
    assert rec["files"][ABSORBED]["population"] == aa.FOREIGN_POPULATION_AMBIGUOUS
    assert "mixed authorship" in rec["files"][ABSORBED]["evidence"]
    assert rec["repaired"] == [] and rec["repair_commit"] == ""
    assert _git("rev-parse", "HEAD", cwd=repo) == head_before
    assert (repo / ABSORBED).exists()


def test_no_authoring_commit_is_ambiguous(tmp_path):
    repo = _own_lane(tmp_path)
    base = _git("merge-base", "main", "lane", cwd=repo)
    rec = aa._foreign_population(repo, base, "never_touched_at_all.txt")
    assert rec["population"] == aa.FOREIGN_POPULATION_AMBIGUOUS, rec
    assert "no commit inside base..HEAD" in rec["evidence"], rec


def test_attribution_fault_is_ambiguous(tmp_path):
    repo = _own_lane(tmp_path)
    rec = aa._foreign_population(repo, "no-such-ref-for-t261022", OWN_OUT_OF_SET)
    assert rec["population"] == aa.FOREIGN_POPULATION_AMBIGUOUS, rec
    assert "commit attribution fault" in rec["evidence"], rec


# ---------- D. replay: the un-patched path is the pre-split face verbatim ----

def test_unpatched_face_repairs_the_own_file_exactly_as_before(tmp_path):
    """The same tree that is RED under the split is repaired under split=False:
    that is the pre-patch behaviour, byte for byte (an in-flight history that
    evaluates workflow.patched()=False keeps it)."""
    repo = _own_lane(tmp_path)
    head_before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo, split=False)

    assert out["own_items"] == []
    assert out["record"] is None
    item = out["item"]
    assert item is not None and item["green"] is True, item
    assert "foreign_repair" not in item
    assert not (repo / OWN_OUT_OF_SET).exists()           # the OLD behaviour: deleted
    assert _git("rev-list", "--count", "%s..HEAD" % head_before, cwd=repo) == "1"
    assert _git("log", "-1", "--format=%an", cwd=repo) == aa._FOREIGN_COMMIT_NAME


def test_split_flag_defaults_to_false_on_the_activity_argument():
    """A pre-patch event payload carries no such field => the activity reads the
    default => the pre-split face."""
    assert shared.MergeCheckArgs(ticket_id=TID).foreign_repair_split is False


def _squeeze(text: str) -> str:
    """Whitespace-insensitive view: the call site may be one line or wrapped."""
    return "".join(text.split())


def test_both_lanes_gate_the_flag_behind_the_patch_marker():
    dl = (POC / "dev_lane.py").read_text("utf-8")
    ll = (POC / "light_lane.py").read_text("utf-8")
    for src, name in ((dl, "dev_lane.py"), (ll, "light_lane.py")):
        assert ("foreign_repair_split=workflow.patched(FOREIGN_REPAIR_SPLIT_PATCH_ID))"
                in _squeeze(src)), name
    # one id, one rule: the marker is the activity's constant, imported by both
    assert "FOREIGN_REPAIR_SPLIT_PATCH_ID," in dl
    assert "FOREIGN_REPAIR_SPLIT_PATCH_ID," in ll
    assert aa.FOREIGN_REPAIR_SPLIT_PATCH_ID == "t261022-foreign-repair-split-v1"
    # the record of the decision is not a log-only artefact: it is a receipt key
    assert aa.FOREIGN_REPAIR_SPLIT_RULE.startswith("population rule (t261022)")


def test_unusable_write_set_fails_closed_with_its_named_reason(tmp_path):
    """No usable write set => no population verdict is trustworthy (every changed
    path reads foreign): the split face answers the SAME named red as the
    pre-split face and repairs nothing — never a classification into a repair."""
    repo = _pollution_lane(tmp_path)
    head_before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo, write_set=[])

    assert out["own_items"] == []
    item = out["item"]
    assert item["green"] is False
    assert item["reason_code"] == "foreign_file_remaining"
    assert "write_set empty or absent" in item["detail"], item["detail"]
    assert out["record"]["skipped"]
    assert out["record"]["files"] == {}                  # nothing was classified
    assert _git("rev-parse", "HEAD", cwd=repo) == head_before
    assert (repo / ABSORBED).exists()
