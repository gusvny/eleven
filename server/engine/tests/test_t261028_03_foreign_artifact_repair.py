# -*- coding: utf-8 -*-
"""t261028-04 (KI-379): the repair's self-consistency floor judges IMPORTABILITY,
not path shape.

Measured defect: a lane branch tracked a JSON build stamp that main does not
have (`server/plugins/workbench/.build-stamp.json`). merge_check classified it as
a foreign file and tried the sanctioned repair (return main's version = remove
it); the floor read ANY non-`.py` path as an importer hit ("<not-a-module>") and
refused the WHOLE repair, so the ticket could never land. The diagnostic was
false for a data file — nothing imports a build stamp.

What this battery pins at the floor seam, against REAL temp git repos (the
classification is a git-history question, so a stub would assert nothing):

  A. a foreign `.json` artifact whose blob main lacks is REMOVED by the repair:
     green item, one engine repair commit, file gone, no floor refusal;
  B. a foreign `.py` that is genuinely still imported is still REFUSED, by
     name — the text names the importer file and the module, never
     "<not-a-module>", and the refusal is whole (zero writes, no commit);
  C. the artifact is never the reason: with both in one round the repair is
     refused for the real module and the artifact stays in place too (no
     partial repair), and the refusal text carries the artifact nowhere.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402

TID = "t261028-04"
WRITE_SET = ["docs/"]
STAMP = "server/plugins/workbench/.build-stamp.json"
ABSORBED = "server/absorbed_sibling.py"
IMPORTER = "server/engine/consumer_sibling.py"


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


def _base_repo(tmp_path: Path, main_files: dict = None) -> Path:
    """main with one commit (plus `main_files`), a `lane` branch, `lane` checked out."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "ut@example.com", cwd=repo)
    _git("config", "user.name", "ut", cwd=repo)
    _commit(repo, "base.txt", "base\n", "c0")
    for rel, text in (main_files or {}).items():
        _commit(repo, rel, text, "main gets %s" % rel)
    _git("branch", "lane", cwd=repo)
    _git("checkout", "-q", "lane", cwd=repo)
    return repo


def _pollution_lane(tmp_path: Path, absorbed: dict,
                    main_files: dict = None) -> Path:
    """The repairable shape: main advanced, and the lane's conflict-resolution
    MERGE commit absorbed `absorbed` (present in NEITHER parent — main never had
    it, the lane never wrote it as its own commit). `main_files` land on main
    BEFORE the lane branches, so they stay out of the lane's diff."""
    repo = _base_repo(tmp_path, main_files)
    _commit(repo, "docs/own.md", "own\n", "ticket write inside the set")
    _git("checkout", "-q", "main", cwd=repo)
    _commit(repo, "m.txt", "m\n", "main advances")
    _git("checkout", "-q", "lane", cwd=repo)
    _git("merge", "--no-commit", "--no-ff", "main", cwd=repo)
    for rel, text in absorbed.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "resolution commit: absorbed sibling files", cwd=repo)
    return repo


def _check(repo: Path):
    return aa._foreign_repair_check_item(repo, "lane", list(WRITE_SET), TID,
                                         split=True)


# ---------- A. a data artifact is removed, never refused -----------------------

def test_foreign_json_artifact_is_removed_not_refused(tmp_path):
    repo = _pollution_lane(tmp_path, {STAMP: '{"rev": 1}\n'})
    before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo)

    assert out["own_items"] == [], out
    item, rec = out["item"], out["record"]
    assert item is not None and item["green"] is True, item
    assert item.get("reason_code") != "foreign_repair_refused_importers", item
    assert rec["files"][STAMP]["population"] == aa.FOREIGN_POPULATION_POLLUTION
    assert rec["repaired"] == [STAMP], rec
    assert rec["left_in_place"] == []

    # the sanctioned repair really ran: file gone, one engine commit carries it
    assert not (repo / STAMP).exists()
    assert rec["repair_commit"] == _git("rev-parse", "--short", "HEAD", cwd=repo)
    assert rec["repair_commit_paths"] == [STAMP]
    assert _git("rev-list", "--count", "%s..HEAD" % before, cwd=repo) == "1"
    assert _git("log", "-1", "--format=%an", cwd=repo) == aa._FOREIGN_COMMIT_NAME
    # the ticket's own in-write-set write is untouched by the repair
    assert (repo / "docs" / "own.md").exists()


# ---------- B. a real module still imported is still refused, by name --------

def test_foreign_module_still_imported_is_refused_by_name(tmp_path):
    repo = _pollution_lane(tmp_path, {ABSORBED: "VALUE = 1\n"},
                           main_files={IMPORTER: "import absorbed_sibling\n"})
    before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo)

    item = out["item"]
    assert item is not None and item["green"] is False, item
    assert item["reason_code"] == "foreign_repair_refused_importers", item
    detail = item["detail"]
    assert IMPORTER in detail, detail        # WHICH file imports it
    assert ABSORBED in detail, detail        # WHICH module is being removed
    assert "<not-a-module>" not in detail, detail

    # the refusal is WHOLE: zero writes, no engine commit, module still present
    assert (repo / ABSORBED).exists()
    assert (repo / ABSORBED).read_text("utf-8") == "VALUE = 1\n"
    assert _git("rev-parse", "HEAD", cwd=repo) == before
    assert out["record"]["repaired"] == []


# ---------- C. the artifact is never the reason for a refusal ----------------

def test_artifact_is_never_the_reason_for_a_refusal(tmp_path):
    repo = _pollution_lane(tmp_path,
                           {STAMP: '{"rev": 1}\n', ABSORBED: "VALUE = 1\n"},
                           main_files={IMPORTER: "import absorbed_sibling\n"})
    before = _git("rev-parse", "HEAD", cwd=repo)
    out = _check(repo)

    item = out["item"]
    assert item is not None and item["green"] is False, item
    assert item["reason_code"] == "foreign_repair_refused_importers", item
    assert set(item["files"]) == {STAMP, ABSORBED}, item
    assert STAMP not in item["detail"], item["detail"]
    assert ABSORBED in item["detail"], item["detail"]
    # whole refusal: the artifact is not partially repaired either
    assert (repo / STAMP).exists() and (repo / ABSORBED).exists()
    assert _git("rev-parse", "HEAD", cwd=repo) == before
