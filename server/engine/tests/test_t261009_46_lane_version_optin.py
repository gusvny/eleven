"""t261009-46 — the per-ticket lane-version opt-in and its landing path (unit
tests; zero Temporal server / zero model / zero network; real `git init`
fixture repos in tmp_path, isolated project store + delivery ledger via env).

Contract under test (ticket spec (1)-(6), review conditions 1-3):
  (1) the opt-in is per ticket and explicit: an unknown/malformed version name
      is refused BY NAME at intake (the workflow start — the nearest sound
      seam inside the write set; the test names state this equivalence), never
      defaulted to either version; absence = the ticket did not opt in;
  (2) one settle path: the landing goes through develop_line.land_ticket
      (whose add/commit is the imported _settle_merge_core) — the source
      guards assert no second merge sequence appeared;
  (3) the revision that lands is the PROVEN one: the caller pins the checkout
      (pin_lane_revision); a checkout that cannot be pinned refuses by name;
  (4) the old flow is untouched at unit level: the version gate routes a
      legacy/absent/bad meta to the legacy path and never reaches the new
      surface; the module-level import graph stays one-way;
  (5) nothing here touches main: the landing's destination is the line branch
      (asserted by the fixture repos' main HEAD staying put).
Malformed-input discipline: non-string names, wrong shapes, empty fields,
dirty trees — all fixed in-test, never an external source.
"""
import asyncio
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
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


def _declare(project="proj", line_id="buffer", repos=(("r", "develop"),)):
    decl = [{"line_id": line_id, "scope": "epic x", "owner": "integration",
             "repositories": [{"name": n, "branch": b} for n, b in repos],
             "extra_scenarios": [], "version": 1}]
    d = shared.develop_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")


# ------------------------------------------------- (1) the opt-in is explicit

def test_lawful_names_parse_to_the_registry():
    assert dl.parse_lane_version("legacy-v1") == "legacy-v1"
    assert dl.parse_lane_version("develop-buffer-v1") == "develop-buffer-v1"


def test_absence_resolves_legacy_but_never_a_bad_name():
    # absence = the ticket did not opt in (legacy); this is the ONLY default.
    assert dl.parse_lane_version("") == dl.LANE_VERSION_LEGACY
    assert dl.parse_lane_version(None) == dl.LANE_VERSION_LEGACY


@pytest.mark.parametrize("bad", [
    "develop-buffer",           # unknown (well-formed)
    "legacy",                   # unknown (well-formed)
    "develop-buffer-V1",        # uppercase = malformed shape
    "develop buffer",           # space = malformed
    "develop_buffer_v1",        # underscore = malformed
    " develop-buffer-v1",       # leading whitespace = malformed
    "develop-buffer-v1 ",       # trailing whitespace = malformed
    "-lead",                    # leading dash = malformed
    7,                          # non-string = malformed
    ["develop-buffer-v1"],      # wrong container = malformed
])
def test_unknown_and_malformed_names_refused_by_name(bad):
    with pytest.raises(dl.LaneVersionError) as ei:
        dl.parse_lane_version(bad)
    assert str(ei.value).strip()  # named, never an empty refusal


def test_unknown_names_refused_as_unknown_with_registry_named():
    with pytest.raises(dl.UnknownLaneVersionError) as ei:
        dl.parse_lane_version("develop-buffer")
    msg = str(ei.value)
    assert "develop-buffer" in msg and "legacy-v1" in msg


def test_workflow_start_refusal_is_the_intake_seam():
    # Review condition 2: the refusal point is the workflow start (the nearest
    # sound seam inside this write set) — pinned here so a reader does not
    # hunt for a dispatch-side hook that does not exist yet. The input shape
    # carries the opt-in; _init validates it through parse_lane_version.
    inp = dev_lane.DevLaneTicketInput(ticket_id="t", template_id="dev-lane",
                                      lane_version="develop-buffer-v1",
                                      develop_line_id="buffer")
    assert inp.lane_version == "develop-buffer-v1"
    old = dev_lane.DevLaneTicketInput(ticket_id="t", template_id="dev-lane")
    assert old.lane_version == ""  # in-flight replay shape = legacy


def test_version_gate_routes_and_never_raises():
    assert dev_lane.is_develop_buffer_ticket({"lane_version": "develop-buffer-v1"})
    assert not dev_lane.is_develop_buffer_ticket({})
    assert not dev_lane.is_develop_buffer_ticket({"lane_version": "legacy-v1"})
    assert not dev_lane.is_develop_buffer_ticket({"lane_version": "bogus-v9"})
    assert not dev_lane.is_develop_buffer_ticket(None)


# ------------------------------------- (3) the pin: proven revision, not tip

def test_pin_noop_when_head_already_proven(env, tmp_path):
    repo = _init_repo(tmp_path / "r")
    sha = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert dl.pin_lane_revision(repo, sha) == sha


def test_pin_moves_clean_checkout_to_proven(env, tmp_path):
    repo = _init_repo(tmp_path / "r")
    proven = _lane_commit(repo, "f.txt", "proven\n", "proven")
    tip = _lane_commit(repo, "f.txt", "tip\n", "tip")
    assert tip != proven
    pinned = dl.pin_lane_revision(repo, proven)
    assert pinned == proven
    assert _git("rev-parse", "HEAD", cwd=repo).stdout.strip() == proven


def test_pin_refuses_dirty_checkout_by_name(env, tmp_path):
    repo = _init_repo(tmp_path / "r")
    proven = _lane_commit(repo, "f.txt", "proven\n", "proven")
    _lane_commit(repo, "f.txt", "tip\n", "tip")
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    with pytest.raises(dl.LandNotPinnedError) as ei:
        dl.pin_lane_revision(repo, proven)
    assert "dirty" in str(ei.value)


def test_pin_refuses_unresolvable_revision_by_name(env, tmp_path):
    repo = _init_repo(tmp_path / "r")
    with pytest.raises(dl.LandNotPinnedError) as ei:
        dl.pin_lane_revision(repo, "0" * 40)
    assert "not resolvable" in str(ei.value)


def test_pin_refuses_missing_proven_by_name(env, tmp_path):
    repo = _init_repo(tmp_path / "r")
    with pytest.raises(dl.LandNotPinnedError):
        dl.pin_lane_revision(repo, "  ")


# ------------------------------------------- (2)+(3) the landing activity

def _landing_setup(env, tmp_path, line_repos=(("r", "develop"),)):
    project = "proj"
    _declare(project, "buffer", line_repos)
    repo = _init_repo(tmp_path / "r")
    proven = _lane_commit(repo, "feat.txt", "feature\n", "lane work")
    return project, repo, proven


def test_land_to_line_lands_the_proven_revision(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    base_main = _git("rev-parse", "main", cwd=repo).stdout.strip()
    res = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert res.ok, res.error
    assert res.revisions["r"] == _git("rev-parse", "develop", cwd=repo).stdout.strip()
    # the landed content IS the proven revision's content, in ONE squash
    # commit (t261011-24: a squash landing, so the proven sha is no longer an
    # ancestor of the line — the content is, judged via the tree)
    assert "feature" in _git("show", "develop:feat.txt",
                             cwd=repo).stdout
    parents = _git("log", "-1", "--format=%P", "develop", cwd=repo).stdout.split()
    assert len(parents) == 1, "a landing is one single-parent squash commit"
    rows, bad = dc.read_rows(dc.ledger_path(project))
    assert not bad
    landings = [r for r in rows if r.get("kind") == dc.KIND_LANDING]
    assert len(landings) == 1
    assert landings[0]["ticket"] == "t46"
    assert landings[0]["repos"][0]["revision"] == res.revisions["r"]
    # (5) main is untouched by the landing act: no new commit, no containment
    assert _git("rev-parse", "main", cwd=repo).stdout.strip() == base_main
    assert _git("merge-base", "--is-ancestor", res.revisions["r"], "main",
                cwd=repo, check=False).returncode != 0


def test_land_to_line_refuses_proven_that_lacks_current_main(env, tmp_path):
    """261015 regression: a judged revision is lawful only while it still
    contains the main it was judged against. The green-run face is recorded once
    and reused while main moves under it, so a landing could carry a tree built
    on an older main - measured on t261014-04, where the line then read every
    main-side fix as its own new regression (11 of them). Refuse by name; the
    remedy is a fresh gate round, never falling back to the tip."""
    project, repo, proven = _landing_setup(env, tmp_path)
    # main advances AFTER the gate anchored on `proven` (same tree, new commit:
    # the content is untouched and only the anchor moved)
    tree = _git("rev-parse", "main^{tree}", cwd=repo).stdout.strip()
    moved = _git("commit-tree", tree, "-p", "main", "-m", "main moves on",
                 cwd=repo).stdout.strip()
    _git("update-ref", "refs/heads/main", moved, cwd=repo)
    res = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert not res.ok, res.error
    assert "does not contain current main" in res.error
    rows, _ = dc.read_rows(dc.ledger_path(project))
    assert not [r for r in rows if r.get("kind") == dc.KIND_LANDING]


def test_already_landed_outranks_the_current_main_guard(env, tmp_path):
    """261016 regression: one landing per ticket is judged BEFORE the revision
    guards. After the 261016 release ruling made four merge stages' certification
    wait satisfiable, their retries were refused by the current-main guard
    instead of resuming that wait - the stage's own re-entry contract - because
    the guard fired first and its text contains no "already landed". The act now
    returns a STRUCTURED already_landed flag, and a ticket that already landed is
    never refused for a revision it is not going to use."""
    project, repo, proven = _landing_setup(env, tmp_path)
    first = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert first.ok, first.error
    # main then moves on: the proven sha no longer contains current main, which
    # used to be the refusal a re-entry died on
    tree = _git("rev-parse", "main^{tree}", cwd=repo).stdout.strip()
    moved = _git("commit-tree", tree, "-p", "main", "-m", "main moves on",
                 cwd=repo).stdout.strip()
    _git("update-ref", "refs/heads/main", moved, cwd=repo)
    again = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert again.already_landed is True
    assert not again.ok
    assert "already landed" in again.error
    assert "does not contain current main" not in again.error
    rows, _ = dc.read_rows(dc.ledger_path(project))
    assert len([r for r in rows if r.get("kind") == dc.KIND_LANDING]) == 1


def test_land_to_line_refuses_without_proven(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    res = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha="")))
    assert not res.ok and "proven" in res.error
    rows, _ = dc.read_rows(dc.ledger_path(project))
    assert not [r for r in rows if r.get("kind") == dc.KIND_LANDING]


def test_land_to_line_refuses_dirty_lane_without_landing(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    _lane_commit(repo, "f2.txt", "tip\n", "later tip")
    (repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    res = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert not res.ok and "dirty" in res.error
    rows, _ = dc.read_rows(dc.ledger_path(project))
    assert not [r for r in rows if r.get("kind") == dc.KIND_LANDING]


def test_land_to_line_refuses_unknown_line_and_empty_fields(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    r1 = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="no-such-line",
        worktree=str(repo), proven_sha=proven)))
    assert not r1.ok and "no-such-line" in r1.error
    r2 = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="",
        worktree=str(repo), proven_sha=proven)))
    assert not r2.ok and "develop_line" in r2.error
    r3 = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert not r3.ok and "ticket_id" in r3.error


def test_land_to_line_refuses_multirepo_line_by_name(env, tmp_path):
    project, repo, proven = _landing_setup(
        env, tmp_path, line_repos=(("r", "develop"), ("r2", "develop2")))
    res = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t46", project_key=project, line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert not res.ok and "single-repository" in res.error


def test_land_to_line_duplicate_is_a_named_refusal(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    a1 = aa.LandToLineArgs(ticket_id="t46", project_key=project,
                           line_id="buffer", worktree=str(repo),
                           proven_sha=proven)
    assert asyncio.run(aa.land_to_line(a1)).ok
    r2 = asyncio.run(aa.land_to_line(a1))
    assert not r2.ok and ("already" in r2.error.lower())


# --------------------------------------------- the certification wait face

def _append_landing_and_cert(project, ticket, rev, green=True, run="run-1"):
    landing = {"kind": dc.KIND_LANDING, "id": dc.mint_id("ldg"),
               "line": "buffer", "ticket": ticket, "actor": "ut",
               "repos": [{"repo": "r", "revision": rev}], "at": 1000}
    res = dc.append_rows([landing], dc.ledger_path(project))
    assert res["written"] == 1, res
    if green is not None:
        cert = dc.build_certification(
            [{"repo": "r", "revision": rev}],
            {"id": run, "cases": {"ran": 3, "failed": 0, "env_failed": 0}},
            "none", judged_by="ut", at_ms=2000, line="buffer")
        dc.append_rows([cert], dc.ledger_path(project))
    return landing


def test_cert_wait_waiting_before_any_certification(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    _append_landing_and_cert(project, "t46", proven, green=None)
    res = asyncio.run(aa.certification_wait(aa.CertWaitArgs(
        ticket_id="t46", project_key=project, line_id="buffer")))
    assert res.ok and res.state == "waiting" and res.waiting_for == ""


def test_cert_wait_refuses_to_guess_green_once_certs_exist(env, tmp_path):
    # The honesty rule, updated 261013 when the run-verdict reader got wired
    # (agent_activities.certification_wait now injects a real reader over the
    # runs ledger): a cert citing a run the reader does NOT know must never
    # read green — the landing reads red_implicated (conservative), never
    # certified. Pre-wiring, this same face was the named run_verdict_unreadable.
    project, repo, proven = _landing_setup(env, tmp_path)
    _append_landing_and_cert(project, "t46", proven, green=True)
    res = asyncio.run(aa.certification_wait(aa.CertWaitArgs(
        ticket_id="t46", project_key=project, line_id="buffer")))
    # never certified on an unknown run — that's the whole promise
    assert res.ok and res.state != "certified" and res.state == "red_implicated"


def test_cert_wait_face_certified_with_injected_reader(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    landing = _append_landing_and_cert(project, "t46", proven, green=True)
    rows, bad = dc.read_rows(dc.ledger_path(project))
    assert not bad
    face = aa.cert_wait_face(rows, "buffer", landing, lambda run: True, 3000)
    assert face["state"] == "certified" and face["covered_by"]


def test_cert_wait_without_landing_is_a_named_error(env, tmp_path):
    project, repo, proven = _landing_setup(env, tmp_path)
    res = asyncio.run(aa.certification_wait(aa.CertWaitArgs(
        ticket_id="ghost", project_key=project, line_id="buffer")))
    assert not res.ok and "no landing record" in res.error


# ---------------------------------- (2)+(4) structural one-way-ness guards

DEV_LANE = (POC / "dev_lane.py").read_text("utf-8")
AGENT_ACT = (POC / "agent_activities.py").read_text("utf-8")
DEV_LINE = (POC / "develop_line.py").read_text("utf-8")


def test_no_second_merge_sequence_in_the_landing_path():
    # (2), re-ruled by t261011-24: the squash recipe is _squash_merge_core's
    # single implementation (shared with the main close-out) — the landing
    # path imports it and never stages by itself; its ONE git commit just
    # records the staged squash result under the landing message.
    assert "_squash_merge_core" in DEV_LINE  # imported, not copied
    landing_src = DEV_LINE[DEV_LINE.index("def land_ticket"):DEV_LINE.index("def pin_lane_revision")]
    for banned in ('"add",', "'add',", '"merge",', "'merge',"):
        assert banned not in landing_src, banned
    # the workflow-side landing step only orchestrates the activity
    step_src = DEV_LANE[DEV_LANE.index("async def _dev_buffer_land_step"):
                        DEV_LANE.index("@workflow.run")]
    for banned in ('"add",', "'add',", '"commit",', "git "):
        assert banned not in step_src, banned


def test_module_level_import_graph_stays_one_way():
    # (4): the module-level import graph stays one-way, with ONE declared
    # exception — dev_lane's inert import of develop_line (the wiring itself;
    # every behaviour is behind the version gate). agent_activities carries
    # no module-level reference (its new-surface imports are lazy, inside the
    # declared gate region), and the new surface never imports the running
    # flow's workflow modules.
    for name, src in (("agent_activities", AGENT_ACT), ("dev_lane", DEV_LANE)):
        tree = ast.parse(src)
        for node in tree.body:
            mods = set()
            if isinstance(node, ast.Import):
                mods = {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods = {getattr(node, "module", "") or ""}
            mods = {m for m in mods if m.startswith("develop_")}
            if name == "dev_lane":
                assert mods <= {"develop_line"}, (name, mods)  # the one declared edge
            else:
                assert not mods, (name, mods)


def test_dev_lane_new_surface_references_stay_in_declared_seams():
    # (4) re-stated inert face, unit mirror: outside the declared seams (the
    # is_develop_buffer_ticket predicate, the _dev_buffer_* steps, the _init
    # intake block) dev_lane never names the new surface.
    tree = ast.parse(DEV_LANE)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "is_develop_buffer_ticket":
            continue
        if isinstance(node, ast.ClassDef):  # methods checked below
            for sub in node.body:
                if isinstance(sub, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                        and (sub.name.startswith("_dev_buffer") or sub.name == "_init"):
                    continue
                if isinstance(sub, ast.AnnAssign) \
                        and getattr(sub.target, "id", "") == "develop_line_id":
                    continue  # the declared input field, not a reference
                _assert_no_new_surface(sub, "class body method")
            continue
        _assert_no_new_surface(node, "module body")


def _assert_no_new_surface(node, where):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id.startswith("develop_"):
            raise AssertionError("new-surface reference in %s: %s" % (where, sub.id))
        if isinstance(sub, ast.Attribute) and getattr(sub.value, "id", "").startswith("develop_"):
            raise AssertionError("new-surface reference in %s: %s" % (where, ast.dump(sub)[:80]))
