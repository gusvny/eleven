"""t261009-28 — the landing act writes the delivery ledger's row (unit tests;
zero Temporal server / zero model / zero network; real `git init` fixture
repos in tmp_path, isolated delivery ledger via SANDBAR_DELIVERY_LEDGER_DIR).

Contract under test (create_plan gen1, review_plan gen1 pass):
  - the landing act appends ONE row — the delivery ledger's `kind: "landing"`
    row — through develop_certify.append_rows, so the row carries a `seq`
    assigned inside the shared ordering space (visible to derive_range and
    validate_row, not a second shape);
  - the second shape is retired: an existing landings.jsonl is refused BY
    NAME (LandingLegacyLedgerError), never read as "no landings";
  - `base` is not stored: the ancestor check runs at act time from the
    ledger-derived latest certification (merge-base --is-ancestor), with the
    declared interim fallback before the line's first certification;
  - borrowed-writer fault modes carried: torn delivery ledger, rejected row
    (written != 1), duplicate (ticket, line) — each a named failure, no
    record; the git-level all-or-nothing behaviour is unchanged.
Malformed-input discipline: corrupt JSONL, non-dict rows, wrong-prefix ids —
fixed strings written to the isolated ledger, never an external source.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[2] / "server" / "engine"
sys.path.insert(0, str(POC))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import shared  # noqa: E402


# ------------------------------------------------------------------ fixtures

def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "main.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _lane_commit(repo: Path, fname: str, text: str, msg: str, branch="lane") -> str:
    _git("checkout", "-B", branch, "main", cwd=repo)
    (repo / fname).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    return tmp_path


def _declare(project="proj", line_id="buffer"):
    decl = [{"line_id": line_id, "scope": "epic x", "owner": "integration",
             "repositories": [{"name": "r", "branch": "develop"}],
             "extra_scenarios": [], "version": 1}]
    d = shared.develop_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")


@pytest.fixture()
def line_and_repo(env):
    _declare()
    r = _init_repo(env / "repo")
    return dl.load_line("proj", "buffer"), r


def _landing_rows(project="proj"):
    path = dc.ledger_path(project)
    rows, bad = dc.read_rows(path)
    assert not bad, bad
    return dc._of_kind(rows, dc.KIND_LANDING)


def _certify(row_id, revision, project="proj"):
    """A green certification row on the line, appended through the ledger's
    own writer — the fixture for the ancestor check."""
    row = {"kind": dc.KIND_CERT, "id": row_id, "line": "buffer",
           "repos": [{"repo": "r", "revision": revision}],
           "run": "run-00000000000000000000000000", "booked_red": "baseline@x",
           "judged_by": "ut", "at": 1791507005123}
    res = dc.append_rows([row], dc.ledger_path(project))
    assert res["written"] == 1, res


# ------------------------------------------------------- one record, one home

def test_landing_row_lands_in_delivery_ledger(env, line_and_repo):
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    res = dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert res.ok and res.record is not None
    rows = _landing_rows()
    assert len(rows) == 1
    row = rows[0]
    # the delivery ledger's shape, validated by its own face — not a second one
    clean, why = dc.validate_row(row)
    assert clean is not None, why
    assert row["kind"] == "landing"
    assert row["id"].startswith("ldg-") and len(row["id"]) == 4 + 26
    assert row["ticket"] == "t1" and row["line"] == "buffer"
    assert row["repos"] == [{"repo": "r",
                             "revision": _git("rev-parse", "develop", cwd=repo).stdout.strip()}]
    assert row["actor"] == "engine" and isinstance(row["at"], int)
    # `seq` was assigned by the writer inside the shared ordering space
    assert isinstance(row["seq"], int) and row["seq"] >= 1
    # the shape the faces read: derive_range sees it as a covered landing
    all_rows, _ = dc.read_rows(dc.ledger_path("proj"))
    rng = dc.derive_range(all_rows, "buffer")
    assert [l["id"] for l in rng["covered_landings"]] == [row["id"]]
    # the retired fields are gone
    assert "base" not in row and "revisions" not in row and "line_id" not in row \
        and "by" not in row
    assert res.record["seq"] == row["seq"]  # the receipt carries the assigned seq


def test_seq_grows_across_landings(env, line_and_repo):
    line, repo = line_and_repo
    _lane_commit(repo, "a.txt", "a\n", "one")
    dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    _lane_commit(repo, "b.txt", "b\n", "two", branch="lane2")
    dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    rows = _landing_rows()
    assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)
    assert len({r["seq"] for r in rows}) == 2


# ------------------------------------------------ one landing per ticket etc.

def test_duplicate_ticket_refused_from_delivery_ledger(env, line_and_repo):
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    n = len(_landing_rows())
    with pytest.raises(dl.LandingDuplicateError):
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert len(_landing_rows()) == n


def test_conflict_bounce_leaves_no_delivery_row(env, line_and_repo):
    line, repo = line_and_repo
    _lane_commit(repo, "first.txt", "one\n", "first lane work")
    dl.land_ticket(line, "proj", {"r": repo}, "t0", "engine")
    _git("checkout", "-B", "lane", "main", cwd=repo)
    (repo / "conflict.txt").write_text("lane side\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "lane side", cwd=repo)
    wt = shared.develop_dir("proj") / "wt" / "r"
    (wt / "conflict.txt").write_text("line side\n", encoding="utf-8")
    _git("add", "-A", cwd=wt)
    _git("commit", "-m", "line side", cwd=wt)
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    assert "conflict" in str(ei.value)
    assert len(_landing_rows()) == 1  # only the first landing
    assert _git("status", "--porcelain", cwd=wt).stdout.strip() == ""


def test_rejected_row_is_a_named_failure_with_no_record(env, line_and_repo,
                                                        monkeypatch):
    """Borrowed-writer fault mode carried: append_rows rejecting (not raising)
    the single row means written != 1 while the merges are already committed —
    the landing names the failure and records nothing."""
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    monkeypatch.setattr(dl, "append_rows",
                        lambda rows, path: {"written": 0, "seqs": [],
                                            "rejected": [{"index": 0, "reason": "x"}]})
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert "delivery ledger rejected" in str(ei.value)


def test_torn_delivery_ledger_refused_by_name(env, line_and_repo):
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    path = dc.ledger_path("proj")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{torn\n", encoding="utf-8")  # fixed malformed fixture row
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert "delivery ledger" in str(ei.value)
    # nothing was appended over the torn line: byte-for-byte unchanged
    assert path.read_text(encoding="utf-8") == "{torn\n"


def test_malformed_inputs_fail_closed(env, line_and_repo):
    line, repo = line_and_repo
    for ticket, by in [("", "engine"), (None, "engine"), ("t6", ""), ("t6", None)]:
        with pytest.raises(dl.LandingError):
            dl.land_ticket(line, "proj", {"r": repo}, ticket, by)
    assert _landing_rows() == []


# ------------------------------------------------------- the second shape retires

def test_legacy_landings_jsonl_refused_by_name(env, line_and_repo):
    """No backward magic: the retired ledger is refused BY NAME, its rows are
    never read as data, and no merge is attempted."""
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    legacy = shared.develop_dir("proj") / "landings.jsonl"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(
        {"id": "ldg-01M4GE0C2QV0F10V1STXN1K6E1", "ticket": "t-old",
         "line_id": "buffer", "revisions": {"r": "9f3c2a1b"},
         "base": {"r": "3a91be07"}, "at": 1791507005123, "by": "engine",
         "version": 1}) + "\n", encoding="utf-8")
    with pytest.raises(dl.LandingLegacyLedgerError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert "landings.jsonl" in str(ei.value) and "delivery ledger" in str(ei.value)
    # the legacy row was NOT read as a landing: the delivery ledger is empty
    assert _landing_rows() == []
    # no landing happened at all
    with pytest.raises(AssertionError):
        _git("rev-parse", "--verify", "develop", cwd=repo)  # branch never seeded


def test_absent_legacy_ledger_is_fine(env, line_and_repo):
    line, repo = line_and_repo
    assert not (shared.develop_dir("proj") / "landings.jsonl").exists()
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    assert dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine").ok


# ------------------------------------------------- derived state / ancestor check

def test_ancestor_check_refuses_landing_over_unrelated_certified_content(
        env, line_and_repo):
    """The check the design asks for, at act time: a landing whose line does
    not contain the certified revision refuses by name (adversarial fixture:
    the ledger certifies a revision the line branch does not carry)."""
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    _certify("cert-00000000000000000000000000", "0" * 40)  # unreachable sha
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert "ancestor check failed" in str(ei.value)
    assert _landing_rows() == []


def test_ancestor_check_passes_when_certified_content_is_on_the_line(
        env, line_and_repo):
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    landed = _git("rev-parse", "develop", cwd=repo).stdout.strip()
    _certify("cert-00000000000000000000000000", landed)
    _lane_commit(repo, "more.txt", "two\n", "more lane work", branch="lane2")
    res = dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    assert res.ok
    assert len(_landing_rows()) == 2


def test_pre_first_certification_fallback_passes(env, line_and_repo):
    """No certification yet: the declared interim check is the fail-closed
    merge-base assertion — the landing proceeds without a stored base."""
    line, repo = line_and_repo
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    res = dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert res.ok and "base" not in res.record


def test_recovery_face_appends_delivery_row(env, line_and_repo):
    """KI-213 face on the new home: a crashed landing's pre-existing merge
    commit gets its missing delivery-ledger row, history untouched."""
    line, repo = line_and_repo
    sha = _lane_commit(repo, "feat.txt", "one\n", "lane work")
    _git("worktree", "add", str(shared.develop_dir("proj") / "wt" / "r"),
         "-b", "develop", "main", cwd=repo)
    wt = shared.develop_dir("proj") / "wt" / "r"
    _git("merge", "--no-ff", "--no-commit", sha, cwd=wt)
    _git("commit", "--no-edit", "-m", "pre-landed by a crashed process", cwd=wt)
    head_before = _git("rev-parse", "develop", cwd=repo).stdout.strip()
    res = dl.land_ticket(line, "proj", {"r": repo}, "t9", "engine")
    assert res.ok
    rows = _landing_rows()
    assert len(rows) == 1 and rows[0]["ticket"] == "t9"
    assert rows[0]["repos"] == [{"repo": "r", "revision": head_before}]
    assert any("recovered" in f for f in res.faces.values())
