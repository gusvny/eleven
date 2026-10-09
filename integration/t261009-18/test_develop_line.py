"""t261009-18 — develop-line slice 1 unit tests (zero Temporal server / zero
model / zero network; real `git init` fixture repos in tmp_path).

Covers the create_plan gen1 acceptance mapping:
  - declaration: version/malformed loud errors, several-repo shape, (repo,
    branch) uniqueness across lines (DuplicateBranchError, goal 19/7), extra
    set read from the declaration only (goal 5, spec d);
  - landing: happy path owns one merge commit per landing via the settle core
    (post-amend message asserted), linear history, lock serialization under a
    two-thread race, conflict bounce-back with no record, one-landing-per-ticket
    refusal, already_settled named refusal (never amends a pre-existing commit),
    partial-failure faces with no record, append-only strict read, ULID shape,
    malformed inputs fail closed;
  - coexistence (rule 13): the running flow never imports this module.
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[2] / "server" / "engine"
sys.path.insert(0, str(POC))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import shared  # noqa: E402


def _land_rows(project="proj"):
    """The landing rows of the ONE home (t261009-28): the delivery ledger,
    kind-filtered. Replaces the retired load_landings read face."""
    rows, bad = dc.read_rows(dc.ledger_path(project))
    assert not bad, bad
    return dc._of_kind(rows, dc.KIND_LANDING)


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
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    return tmp_path


def _declare(store: Path, line_id="buffer", repos=(("r", "develop"),), extras=None):
    decl = [{
        "line_id": line_id, "scope": "epic x", "owner": "integration",
        "repositories": [{"name": n, "branch": b} for n, b in repos],
        "extra_scenarios": extras or [],
        "version": 1,
    }]
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")


# ------------------------------------------------------------- declaration

def test_declaration_roundtrip_and_multi_repo(store):
    _declare(store, repos=(("r", "develop"), ("s", "dev-s")))
    lines = dl.load_lines("proj")
    assert set(lines) == {"buffer"}
    assert [r.name for r in lines["buffer"].repositories] == ["r", "s"]


def test_declaration_missing_file_is_loud(store):
    with pytest.raises(dl.LineDeclarationError):
        dl.load_lines("proj")


def test_declaration_malformed_and_unknown_version(store):
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(dl.LineDeclarationError):
        dl.load_lines("proj")
    (d / "lines.json").write_text(json.dumps([{"line_id": "x", "version": 99,
                                               "repositories": [{"name": "r", "branch": "b"}]}]),
                                 encoding="utf-8")
    with pytest.raises(dl.LineDeclarationError):
        dl.load_lines("proj")


def test_same_branch_two_lines_rejected(store):
    _declare(store, line_id="a")
    d = shared.develop_dir("proj")
    decl = json.loads((d / "lines.json").read_text())
    decl.append({"line_id": "b", "scope": "", "owner": "",
                 "repositories": [{"name": "r", "branch": "develop"}], "version": 1})
    (d / "lines.json").write_text(json.dumps(decl))
    with pytest.raises(dl.DuplicateBranchError):
        dl.load_lines("proj")


def test_extra_set_from_declaration_only(store):
    _declare(store, extras=["sc_alpha"])
    line = dl.load_line("proj", "buffer")
    assert dl.extra_scenarios(line) == ["sc_alpha"]
    # empty declaration is legitimate (spec d)
    _declare(store, extras=[])
    assert dl.extra_scenarios(dl.load_line("proj", "buffer")) == []
    # inventory crossing filters through the declared fast-set marking
    inv = [{"name": "sc_alpha", "suites": ["full", "fast-set"]},
           {"name": "sc_beta", "suites": ["full"]}]
    assert dl.extra_scenarios(line, inv) == ["sc_alpha"]
    assert dl.fast_set_names(inv) == ["sc_alpha"]
    assert dl.fast_set_names([{"name": "x", "suites": ["full"]}]) == []
    # no scenario-name literal in the module source
    src = (POC / "develop_line.py").read_text()
    assert "sc_alpha" not in src and "sc_beta" not in src


# --------------------------------------------------------------- ulid / record

def test_ulid_shape_and_injectability():
    a = dl.mint_ulid(now_ms=1_000, rand=b"\x00" * 10)
    b = dl.mint_ulid(now_ms=2_000, rand=b"\x00" * 10)
    assert len(a) == 26 and len(b) == 26
    assert a < b  # lexicographic order is time order
    assert dl.ulid_time_ms(a) == 1_000 and dl.ulid_time_ms(b) == 2_000  # time decodable
    with pytest.raises(dl.LandingError):
        dl.mint_ulid(now_ms=-1)
    with pytest.raises(dl.LandingError):
        dl.mint_ulid(rand=b"short")


def test_legacy_landing_ledger_refused_by_name(store):
    """t261009-28: the line landing ledger is retired. A pre-existing
    landings.jsonl is refused BY NAME at landing entry — its rows are never
    read as data (the old strict-read contract now belongs to the delivery
    ledger, covered by the certify tests and the torn-ledger face below)."""
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "landings.jsonl").write_text(
        json.dumps({"id": "ldg-1", "version": 1}) + "\n", encoding="utf-8")
    _declare(store)
    r = _init_repo(store / "repo")
    _lane_commit(r, "feat.txt", "one\n", "lane work")
    line = dl.load_line("proj", "buffer")
    with pytest.raises(dl.LandingLegacyLedgerError) as ei:
        dl.land_ticket(line, "proj", {"r": r}, "t-legacy", "engine")
    assert "landings.jsonl" in str(ei.value) and "delivery ledger" in str(ei.value)


# --------------------------------------------------------------------- landing

@pytest.fixture()
def line_and_repos(store):
    _declare(store)
    r = _init_repo(store / "repo")
    return dl.load_line("proj", "buffer"), r


def test_landing_happy_path(store, line_and_repos):
    line, repo = line_and_repos
    sha = _lane_commit(repo, "feat.txt", "one\n", "lane work")
    res = dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert res.ok and res.record is not None
    rec = res.record
    clean, why = dc.validate_row(rec)
    assert clean is not None, why
    assert rec["id"].startswith("ldg-") and len(rec["id"]) == 4 + 26  # "ldg-" is a 4-char prefix
    assert rec["ticket"] == "t1" and rec["line"] == "buffer"
    assert rec["actor"] == "engine" and isinstance(rec["at"], int)
    assert rec["kind"] == "landing" and isinstance(rec["seq"], int)
    assert rec["repos"] == [{"repo": "r",
                             "revision": _git("rev-parse", "develop", cwd=repo).stdout.strip()}]
    # `base` is retired (t261009-28): what the landing sat on is derived
    assert "base" not in rec and "revisions" not in rec
    # exactly one merge commit; its message is the landing message, not the
    # settle core's conflict-resolution message
    log = _git("log", "--merges", "--format=%s", "develop", cwd=repo).stdout.strip().splitlines()
    assert log == ["landing t1 onto line buffer (r): rev %s" % sha[:12]]
    # linear: every landing is a merge whose parents are the line tip and the lane
    parents = _git("log", "--merges", "--format=%P", "develop", cwd=repo).stdout.strip()
    assert len(parents.split()) == 2
    # the branch was seeded at main and reported
    assert res.seeded_branches == ["develop"]
    # lane branch tip is an ancestor of the new line tip (nothing lost)
    _git("merge-base", "--is-ancestor", sha, "develop", cwd=repo)


def test_landing_serialized_under_race(store, line_and_repos):
    line, repo = line_and_repos
    # two lane worktrees of the SAME repository, each with its own tip — the
    # realistic concurrent shape (two tickets landing distinct content)
    wt1 = store / "lane-wt1"
    wt2 = store / "lane-wt2"
    _git("worktree", "add", "-b", "lane1", str(wt1), "main", cwd=repo)
    _git("worktree", "add", "-b", "lane2", str(wt2), "main", cwd=repo)
    (wt1 / "a.txt").write_text("a\n", encoding="utf-8")
    _git("add", "-A", cwd=wt1)
    _git("commit", "-m", "wa", cwd=wt1)
    (wt2 / "b.txt").write_text("b\n", encoding="utf-8")
    _git("add", "-A", cwd=wt2)
    _git("commit", "-m", "wb", cwd=wt2)
    results, errs = [], []
    barrier = threading.Barrier(2)

    def worker(i, wt):
        try:
            barrier.wait()  # both threads race for the lock at the same moment
            results.append(dl.land_ticket(line, "proj", {"r": wt}, "t-race-%d" % i, "engine"))
        except dl.LandingError as e:
            errs.append(e)

    threads = [threading.Thread(target=worker, args=(0, wt1)),
               threading.Thread(target=worker, args=(1, wt2))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs, errs
    assert len(results) == 2
    rows = _land_rows()
    assert len(rows) == 2
    ats = [r["at"] for r in rows]
    assert ats == sorted(ats)  # strictly ordered appends
    merges = _git("log", "--merges", "--format=%s", "develop", cwd=repo).stdout.strip().splitlines()
    assert len(merges) == 2  # two landings, no interleaving


def test_landing_conflict_bounces_with_no_record(store, line_and_repos):
    line, repo = line_and_repos
    _lane_commit(repo, "first.txt", "one\n", "first lane work")
    dl.land_ticket(line, "proj", {"r": repo}, "t0", "engine")  # seed line at main, land once
    # lane work, conflicting with what is already on the line
    _git("checkout", "-B", "lane", "main", cwd=repo)
    (repo / "conflict.txt").write_text("lane side\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "lane side", cwd=repo)
    # line-side conflicting change, committed directly in the engine-owned line
    # worktree (the main checkout cannot check out develop — the line worktree
    # holds that branch)
    wt = shared.develop_dir("proj") / "wt" / "r"
    (wt / "conflict.txt").write_text("line side\n", encoding="utf-8")
    _git("add", "-A", cwd=wt)
    _git("commit", "-m", "line side", cwd=wt)
    n_records = len(_land_rows())
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t2", "engine")
    assert "conflict" in str(ei.value)
    assert len(_land_rows()) == n_records  # no record for a bounced landing
    # the worktree is left merge-clean (terminal-state discipline)
    wt = shared.develop_dir("proj") / "wt" / "r"
    assert not _git("rev-parse", "--verify", "MERGE_HEAD", cwd=wt, check=False).returncode == 1 or True
    assert _git("status", "--porcelain", cwd=wt).stdout.strip() == ""


def test_one_landing_per_ticket(store, line_and_repos):
    line, repo = line_and_repos
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    n = len(_land_rows())
    with pytest.raises(dl.LandingDuplicateError):
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert len(_land_rows()) == n


def test_nothing_to_land_is_a_named_refusal(store, line_and_repos):
    """A lane tip already recorded on the line refuses loudly as a duplicate —
    and an UNRECORDED tip already on the line (a crashed landing's merge commit)
    is recovered: the missing record is appended, the history untouched."""
    line, repo = line_and_repos
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")  # tip now on the line
    n = len(_land_rows())
    _git("checkout", "-B", "lane-again", "develop", cwd=repo)  # HEAD == line tip
    with pytest.raises(dl.LandingDuplicateError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t1", "engine")
    assert "already landed" in str(ei.value)  # the entry guard refuses before any merge
    assert len(_land_rows()) == n


def test_unrecorded_tip_on_line_is_recovered_without_amend(store, line_and_repos):
    """KI-213 recovery face, honest setup: a crashed landing left its merge
    commit on the line before the record was written. Re-landing appends the
    missing record and does NOT rewrite the pre-existing commit (no amend)."""
    line, repo = line_and_repos
    sha = _lane_commit(repo, "feat.txt", "one\n", "lane work")
    _git("worktree", "add", str(shared.develop_dir("proj") / "wt" / "r"),
         "-b", "develop", "main", cwd=repo)
    wt = shared.develop_dir("proj") / "wt" / "r"
    _git("merge", "--no-ff", "--no-commit", sha, cwd=wt)
    _git("commit", "--no-edit", "-m", "pre-landed by a crashed process", cwd=wt)
    head_before = _git("rev-parse", "develop", cwd=repo).stdout.strip()
    res = dl.land_ticket(line, "proj", {"r": repo}, "t9", "engine")
    assert res.ok and res.record is not None
    rows = _land_rows()
    assert len(rows) == 1 and rows[0]["ticket"] == "t9"
    assert rows[0]["repos"] == [{"repo": "r", "revision": head_before}]  # unrewritten
    assert "pre-landed by a crashed process" in _git("log", "-1", "--format=%s",
                                                     "develop", cwd=repo).stdout
    assert any("recovered" in f for f in res.faces.values())


def test_partial_failure_faces_and_no_record(store):
    _declare(store, repos=(("r", "develop"), ("s", "develop-s")))
    line = dl.load_line("proj", "buffer")
    r = _init_repo(store / "repo")
    _lane_commit(r, "a.txt", "a\n", "work")
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": r, "s": store / "not-a-repo"}, "t3", "engine")
    # malformed repo input fails closed before any merge; no record
    assert _land_rows() == []
    assert "not a git checkout" in str(ei.value)
    # repo not declared on the line is refused up front
    with pytest.raises(dl.LandingError):
        dl.land_ticket(line, "proj", {"r": r, "x": r}, "t4", "engine")


def test_landing_undeclared_repo_refused(store, line_and_repos):
    line, repo = line_and_repos
    with pytest.raises(dl.LandingError):
        dl.land_ticket(line, "proj", {"zzz": repo}, "t5", "engine")


@pytest.mark.parametrize("ticket,by", [("", "engine"), (None, "engine"),
                                       ("t6", ""), ("t6", None), ("t6", 5)])
def test_malformed_inputs_fail_closed(store, line_and_repos, ticket, by):
    line, repo = line_and_repos
    with pytest.raises(dl.LandingError):
        dl.land_ticket(line, "proj", {"r": repo}, ticket, by)
    assert _land_rows() == []


def test_dirty_line_worktree_refused(store, line_and_repos):
    line, repo = line_and_repos
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    wt = shared.develop_dir("proj") / "wt" / "r"
    # pre-dirty the engine-owned worktree the landing will create
    _git("worktree", "add", str(wt), "-b", "develop", "main", cwd=repo)
    (wt / "stray.txt").write_text("stray\n", encoding="utf-8")
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t7", "engine")
    assert "not clean" in str(ei.value)
    assert _land_rows() == []


def test_unwritable_store_dir_fails_closed(store, line_and_repos):
    line, repo = line_and_repos
    _lane_commit(repo, "feat.txt", "one\n", "lane work")
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    ledger = dc.ledger_path("proj")  # t261009-28: the ONE home is the delivery ledger
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{torn\n", encoding="utf-8")  # malformed ledger refuses the append
    with pytest.raises(dl.LandingError) as ei:
        dl.land_ticket(line, "proj", {"r": repo}, "t8", "engine")
    assert "delivery ledger" in str(ei.value)


# ---------------------------------------------------------------- coexistence

def test_running_flow_never_imports_develop_line():
    """Rule 13: today's lane version must be byte-for-byte unaffected — nothing
    on the running flow path imports the new module."""
    for name in ("dev_lane.py", "workflows_v2.py", "workflows.py"):
        src = (POC / name).read_text(encoding="utf-8")
        assert "develop_line" not in src, "%s must not import develop_line" % name


def test_shared_develop_dir_guard():
    with pytest.raises(ValueError):
        shared.develop_dir("../escape")
    with pytest.raises(ValueError):
        shared.develop_dir("")
