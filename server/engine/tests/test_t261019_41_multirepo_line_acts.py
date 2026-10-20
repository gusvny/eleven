# -*- coding: utf-8 -*-
"""t261019-41 — the multi-repository develop line (host ruling 261019 a2).

L1 truth table for the multi-repo acts over a REAL two-repository git
fixture (every repository is a tmp-local git repo; zero Temporal, zero
network, zero integration entry — UT discipline):

  act      | input                                        | expected
  ---------+----------------------------------------------+---------------------------
  land     | declared repo_proven, both repos contain own | ok; ONE landing row naming
           | main                                         | both repos; both line
           |                                              | branches advanced; mains
           |                                              | untouched
  land     | repo_proven missing one declared repo        | named refusal; no landing
           |                                              | row; no line branch created
  land     | repo_proven carries an undeclared repo       | named refusal; nothing moved
  land     | repo B's proven sha lacks B's OWN main       | refusal names repo B BEFORE
           | (A's proven contains A's main)               | any pin: A's lane tree not
           |                                              | detached, no landing row
  land     | corrupt lane manifest                        | named refusal (never a
           |                                              | single-repo fallback)
  land     | repo B's lane tree dirty (pin fails)         | named refusal, no line-side
           |                                              | state moved, no row
  land     | repo B conflicts with its line branch        | LandingError; BOTH lane
           |                                              | trees merge-clean; no row
  certify  | round over the multi-repo landing range      | cert names BOTH repos
  promote  | green cert, both repos fast-forwardable      | promotion row; BOTH mains
           |                                              | moved; per-repo
           |                                              | main_before/main_after
  promote  | repo A cannot fast-forward                   | PromotionRefused BEFORE any
           |                                              | move: A and B mains
           |                                              | unchanged, no row
  promote  | act-phase fault on repo B (update-ref        | rollback: A's main ref AND
           | fault-injected)                              | working tree back at
           |                                              | main_before; no row; error
           |                                              | names the rollback
  declare  | two lines naming the same (repo, branch)     | DuplicateBranchError (the
           |                                              | refusal is untouched)

Fault-mode carry-over (review condition 2, t261019-41): the multi branch of
``land_to_line`` carries the single-repo path's fault modes in the same
order — malformed inputs, already-landed (261016, outranks the revision
guards), contains-OWN-current-main per repo (261015, per-repo form here),
pin-before-act, then ``land_ticket``'s own stack (freeze consultation,
ancestor gate, KI-213 recovery faces, duplicate-landing, legacy-ledger,
all-or-nothing rollback). The single-repo path itself is asserted
byte-identical by ``test_t261009_46_lane_version_optin.py`` (unchanged) and
``test_t261011_24_landing_squash.py``.

Fixture reclamation: all tmp dirs go through ``_tmp_reclaim``
 (mkdtemp_reclaimed), per the 260926 disk-leak discipline.

End-to-end honesty (review condition 5): this battery drives the ACTIVITIES
directly. The workflow-side wiring that populates ``repo_proven`` lives in
``dev_lane`` (outside this ticket's write set) and is a follow-up — until it
lands a real multi-repo ticket gets the named refusal, fail-closed.
"""
import asyncio
import json
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_activities as aa  # noqa: E402
import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import develop_promote as dp  # noqa: E402
import shared  # noqa: E402

PROJECT = "proj"
TICKET = "t41"
REPOS = (("rA", "develop-a"), ("rB", "develop-b"))


def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-qm", "base", cwd=path)
    return path


def _lane_commit(repo: Path, fname: str, text: str) -> str:
    """A lane commit on a dedicated lane branch (the proven revision)."""
    _git("checkout", "-q", "-B", "lane/t41", "main", cwd=repo)
    (repo / fname).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "lane work %s" % fname, cwd=repo)
    sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    _git("checkout", "-q", "main", cwd=repo)
    return sha


@pytest.fixture()
def two(tmp_path, monkeypatch):
    """A real two-repository project + lane: repos rA/rB, each with a lane
    worktree under the lane container and a declared two-repo line."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    lane = tmp_path / "lane"
    lane.mkdir()
    repos, proven, manifest = {}, {}, []
    for name, branch in REPOS:
        repo = _init_repo(tmp_path / name)
        sha = _lane_commit(repo, "%s.txt" % name, "feature %s\n" % name)
        _git("worktree", "add", str(lane / name), "lane/t41", cwd=repo)
        repos[name] = repo
        proven[name] = sha
        manifest.append({"repo": name, "name": name, "branch": "lane/t41"})
    mf = shared.multi_manifest_path(lane, create=True)
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    decl = [{"line_id": "buffer", "scope": "epic", "owner": "integration",
             "repositories": [{"name": n, "branch": b} for n, b in REPOS],
             "extra_scenarios": [], "version": 1}]
    d = shared.develop_dir(PROJECT)
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")
    return {"tmp": tmp_path, "lane": lane, "repos": repos, "proven": proven,
            "ledger": tmp_path / "ledger" / ("%s.jsonl" % PROJECT)}


def _land(two, **over):
    kwargs = dict(ticket_id=TICKET, project_key=PROJECT, line_id="buffer",
                  worktree=str(two["lane"]), proven_sha="",
                  repo_proven=dict(two["proven"]))
    kwargs.update(over)
    return asyncio.run(aa.land_to_line(aa.LandToLineArgs(**kwargs)))


def _landings(two_repo):
    rows, bad = dc.read_rows(dc.ledger_path(PROJECT))
    assert not bad
    return [r for r in rows if r.get("kind") == dc.KIND_LANDING]


def _branch_sha(repo, branch):
    p = _git("rev-parse", "--verify", "refs/heads/%s" % branch, cwd=repo,
             check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def _lane_tree_head(two, name):
    return _git("rev-parse", "HEAD", cwd=two["lane"] / name).stdout.strip()


def _merging(two, name):
    return _git("rev-parse", "--verify", "MERGE_HEAD",
                cwd=two["lane"] / name, check=False).returncode == 0


# --------------------------------------------------------------- land: happy

def test_multirepo_landing_lands_both_repos_in_one_act(two):
    base_mains = {n: _branch_sha(r, "main") for n, r in two["repos"].items()}
    res = _land(two)
    assert res.ok, res.error
    rows = _landings(two)
    assert len(rows) == 1, "one landing row per ticket"
    assert {r["repo"] for r in rows[0]["repos"]} == {"rA", "rB"}
    for name, branch in REPOS:
        assert res.revisions[name] == _branch_sha(two["repos"][name], branch)
        assert "feature %s" % name in _git(
            "show", "%s:%s.txt" % (branch, name),
            cwd=two["repos"][name]).stdout
        # the landing never touches main
        assert _branch_sha(two["repos"][name], "main") == base_mains[name]


def test_multirepo_landing_refuses_missing_repo_proven(two):
    res = _land(two, repo_proven={"rA": two["proven"]["rA"]})
    assert not res.ok and "rB" in res.error and "never assumed" in res.error
    assert _landings(two) == []
    assert _branch_sha(two["repos"]["rA"], "develop-a") == ""


def test_multirepo_landing_refuses_undeclared_repo_proven(two):
    res = _land(two, repo_proven=dict(two["proven"], rC="0" * 40))
    assert not res.ok and "rC" in res.error
    assert _landings(two) == []


def test_multirepo_landing_per_repo_main_guard_is_per_repo(two):
    """Review condition 3: a sha that contains repo A's main but not repo
    B's OWN main is refused for B only — and BEFORE any pin, so A's lane
    tree is not even detached (no lane-side scratch state either)."""
    repo_b = two["repos"]["rB"]
    tree = _git("rev-parse", "main^{tree}", cwd=repo_b).stdout.strip()
    moved = _git("commit-tree", tree, "-p", "main", "-m", "b moves on",
                 cwd=repo_b).stdout.strip()
    _git("update-ref", "refs/heads/main", moved, cwd=repo_b)
    head_a = _lane_tree_head(two, "rA")
    res = _land(two)
    assert not res.ok and "rB" in res.error \
        and "does not contain its own current main" in res.error
    assert _landings(two) == []
    assert _lane_tree_head(two, "rA") == head_a, "repo A must stay untouched"


def test_multirepo_landing_refuses_corrupt_manifest(two):
    mf = shared.multi_manifest_path(two["lane"])
    mf.write_text("{not json", encoding="utf-8")
    res = _land(two)
    assert not res.ok and "manifest" in res.error
    assert _landings(two) == []


def test_multirepo_landing_pin_failure_moves_no_line_state(two):
    """Review condition 1: a pin refusal is claimed as 'no LINE-side state
    moved' — a lane worktree detached by an earlier pin is scratch state,
    but no line branch may exist and no row may be written."""
    lane_b = two["lane"] / "rB"
    # repo B's lane branch moves OFF its proven sha AND the scope tree picks
    # up dirt, so the pin can neither quietly no-op (HEAD == proven
    # short-circuits BEFORE the dirty check) nor checkout — LandNotPinnedError.
    # The lane commit is made INSIDE the lane worktree (git refuses to check
    # out a branch another worktree already holds).
    (lane_b / "moved.txt").write_text("moved\n", encoding="utf-8")
    _git("add", "-A", cwd=lane_b)
    _git("commit", "-qm", "lane moves on", cwd=lane_b)
    (lane_b / "dirt.txt").write_text("dirty\n", encoding="utf-8")
    res = _land(two)
    assert not res.ok and "rB" in res.error
    assert _landings(two) == []
    for name, branch in REPOS:
        assert _branch_sha(two["repos"][name], branch) == ""


def test_multirepo_landing_conflict_rolls_both_repos_back(two):
    """The existing per-repo all-or-nothing, now proven over TWO repos: repo
    B conflicts, so repo A's already-committed landing work is rolled back
    and NO record exists."""
    repo_b = two["repos"]["rB"]
    # the line branch pre-exists and touches the SAME file as the lane work
    # (otherwise git auto-merges and there is no conflict to prove)
    _git("branch", "develop-b", "main", cwd=repo_b)
    _git("checkout", "-q", "develop-b", cwd=repo_b)
    (repo_b / "base.txt").write_text("line-side divergence\n", encoding="utf-8")
    _git("add", "-A", cwd=repo_b)
    _git("commit", "-qm", "line side moves base.txt", cwd=repo_b)
    _git("checkout", "-q", "main", cwd=repo_b)
    # the lane branch also moves base.txt; the lane worktree itself carries
    # the commit, so the new tip IS the declared proven sha
    lane_b = two["lane"] / "rB"
    (lane_b / "base.txt").write_text("lane-side divergence\n", encoding="utf-8")
    _git("add", "-A", cwd=lane_b)
    _git("commit", "-qm", "lane side moves base.txt", cwd=lane_b)
    two["proven"]["rB"] = _git("rev-parse", "HEAD", cwd=lane_b).stdout.strip()
    res = _land(two)
    assert not res.ok and "rB" in res.error
    assert _landings(two) == []
    for name, _branch in REPOS:
        assert not _merging(two, name), "%s left a MERGE_HEAD" % name


# -------------------------------------------------------------- declare: (repo, branch)

def test_duplicate_repo_branch_refusal_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    d = shared.develop_dir(PROJECT)
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps([
        {"line_id": "one", "scope": "s", "owner": "o",
         "repositories": [{"name": "r", "branch": "develop"}],
         "extra_scenarios": [], "version": 1},
        {"line_id": "two", "scope": "s", "owner": "o",
         "repositories": [{"name": "r", "branch": "develop"}],
         "extra_scenarios": [], "version": 1},
    ]), encoding="utf-8")
    with pytest.raises(dl.LineDeclarationError):
        dl.load_lines(PROJECT)


# --------------------------------------------------------------- certify

def test_certificate_names_every_repo_of_the_multirepo_landing(two):
    assert _land(two).ok
    rows, _bad = dc.read_rows(dc.ledger_path(PROJECT))
    landings = [r for r in rows if r.get("kind") == dc.KIND_LANDING]
    cand = dc.candidate_set(landings)
    assert {c["repo"] for c in cand} == {"rA", "rB"}
    cert = dc.build_certification(
        cand, {"id": "run-g", "cases": {"ran": 3, "failed": 0}}, "none",
        judged_by="ut", line="buffer")
    assert {r["repo"] for r in cert["repos"]} == {"rA", "rB"}
    revs = {r["repo"]: r["revision"] for r in cert["repos"]}
    for name, branch in REPOS:
        assert revs[name] == _branch_sha(two["repos"][name], branch)


# --------------------------------------------------------------- promote

def _certified(two, verdict="green"):
    """Land + a green certification over both repos; returns the cert id."""
    assert _land(two).ok
    rows, _bad = dc.read_rows(dc.ledger_path(PROJECT))
    landings = [r for r in rows if r.get("kind") == dc.KIND_LANDING]
    cert = dc.build_certification(
        dc.candidate_set(landings),
        {"id": "run-g", "cases": {"ran": 3, "failed": 0}}, "none",
        judged_by="ut", line="buffer")
    dc.append_rows([cert], dc.ledger_path(PROJECT))
    runs_store = Path(__import__("os").environ["SANDBAR_PROJECTS_DIR"]) \
        / PROJECT / "ledger"
    runs_store.mkdir(parents=True, exist_ok=True)
    (runs_store / "scenario-runs.jsonl").write_text(
        json.dumps({"id": "run-g", "verdict": verdict,
                    "cases": {"ran": 3, "failed": 0}, "suite": "full",
                    "source": "ut"}) + "\n", encoding="utf-8")
    return cert["id"]


def test_promotion_fast_forwards_every_repo_or_records_nothing(two):
    cert_id = _certified(two)
    before = {n: _branch_sha(r, "main") for n, r in two["repos"].items()}
    row = dp.promote_buffer(PROJECT, "buffer", signer="host",
                            repo_paths=two["repos"])
    assert row["certification"] == cert_id
    assert row["tickets"] == [TICKET]
    mb = {r["repo"]: r["revision"] for r in row["main_before"]}
    ma = {r["repo"]: r["revision"] for r in row["main_after"]}
    for name, branch in REPOS:
        assert mb[name] == before[name]
        assert ma[name] == _branch_sha(two["repos"][name], branch)
        assert _branch_sha(two["repos"][name], "main") == ma[name]
    rows, _bad = dc.read_rows(dc.ledger_path(PROJECT))
    assert len([r for r in rows
                if r.get("kind") == dc.KIND_PROMOTION]) == 1


def test_promotion_not_fast_forward_refuses_before_any_move(two):
    _certified(two)
    # repo A's main advances past the line's base: the fast-forward is gone
    repo_a = two["repos"]["rA"]
    (repo_a / "unrelated.txt").write_text("main moves alone\n", encoding="utf-8")
    _git("add", "-A", cwd=repo_a)
    _git("commit", "-qm", "main moves alone", cwd=repo_a)
    before = {n: _branch_sha(r, "main") for n, r in two["repos"].items()}
    with pytest.raises(dp.PromotionRefused, match="promotion_not_fast_forward:rA"):
        dp.promote_buffer(PROJECT, "buffer", signer="host",
                          repo_paths=two["repos"])
    # NOTHING moved: both mains unchanged, no promotion row
    for name, _branch in REPOS:
        assert _branch_sha(two["repos"][name], "main") == before[name]
    rows, _bad = dc.read_rows(dc.ledger_path(PROJECT))
    assert not [r for r in rows if r.get("kind") == dc.KIND_PROMOTION]


def test_promotion_act_failure_rolls_moved_repos_back(two):
    """Review condition 4: the rollback reconciles an in-place-merged main
    CHECKOUT too — ref AND working tree back at main_before."""
    _certified(two)
    repo_a = two["repos"]["rA"]
    before_a = _branch_sha(repo_a, "main")
    # repo B's main checkout is NOT a clean on-main checkout, so its act step
    # goes through update-ref — where the fault is injected (repo A stays a
    # clean on-main checkout, so its step is the in-place ff that must be
    # rolled back by ref AND working tree)
    (two["repos"]["rB"] / "dirt.txt").write_text("dirty\n", encoding="utf-8")
    real_git = dp._git

    def faulting_git(args, wt, timeout=60):
        if args[:2] == ["update-ref", "refs/heads/main"] \
                and str(wt) == str(two["repos"]["rB"]):
            return subprocess.CompletedProcess(args, 1, "", "injected fault")
        return real_git(args, wt, timeout=timeout)

    with mock.patch.object(dp, "_git", faulting_git):
        with pytest.raises(dp.PromoteError) as exc:
            dp.promote_buffer(PROJECT, "buffer", signer="host",
                              repo_paths=two["repos"])
    assert "rolled back" in str(exc.value) and "rB" in str(exc.value)
    assert _branch_sha(repo_a, "main") == before_a
    # the in-place-merged checkout followed its ref back (the lane file is
    # gone from the working tree again)
    assert not (repo_a / "rA.txt").exists()
    rows, _bad = dc.read_rows(dc.ledger_path(PROJECT))
    assert not [r for r in rows if r.get("kind") == dc.KIND_PROMOTION]
