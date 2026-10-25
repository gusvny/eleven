"""KI-350 (t261024-12) unit truth tables: a NARROWED (targeted-only) green gate
round records an HONEST `last_green_run` face — `{"ran": N, "narrowed": True}`
plus the sha/at the caller resolves — so the develop-buffer landing anchor
tracks the tree the gate actually judged, and the merge/landing stages judge
the marker BY NAME.

Layers pinned here:
  ① face selection (shared.green_run_face_narrowed) — green narrowed round =>
    the marker face; zero-scenarios targeted round => None (the KI-220 zero-run
    supply face stays fail-closed); red / supply-red / blockers / malformed =>
    None; the legacy shared.green_run_face keeps returning None for every
    targeted-only round (byte-identical replay leg).
  ② merge item (shared.green_run_check_item) — narrowed face + matching sha =>
    GREEN reason_code="narrowed" with the not-a-full-close detail; narrowed face
    + moved HEAD => red stale whose detail names the run that re-anchors (the
    acceptance case: main sync after a narrowed round is refused BY NAME);
    narrowed face with ran=0 => red fail-closed; legacy full / no_scenarios /
    zero-run / malformed faces keep the pre-KI-350 verdicts.
  ③ recorder (dev_lane._ki220_record_green_run, stubbed workflow facade) —
    under the KI-350 patch gate a green targeted round records the marker face
    (with sha/at, no marker on the full-round arm); UN-patched, a targeted
    round records nothing (byte-identical old replay); the lane_head_sha
    failure path on the narrowed arm fires the same fail-closed no-face +
    green_run_note branch as the full arm (hook discipline, review comment 1).
  ④ single-consumer guard (review comment 2) — a source-level L1 row: the only
    readers of `meta.last_green_run` are the merge_check argument wiring and
    the develop-buffer landing step; no release / close-out / closing-verdict
    function reads the face, so a narrowed marker can never mint a full proof
    through any other surface.
  ⑤ land_to_line refusal text (agent_activities, real fixture repo) — the
    contains-main refusal names the remedy: the current lane HEAD and the run
    kind (a green NARROWED round) that would satisfy the precondition.

Run: server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t261024_12_narrowed_green_face.py -q
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

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
KI350 = dev_lane.KI350_NARROWED_FACE_PATCH_ID


class _Receipt:
    def __init__(self, **kw):
        self.ran = kw.get("ran", 0)
        self.passed = kw.get("passed", 0)
        self.failed = kw.get("failed", 0)
        self.env_fail = kw.get("env_fail", 0)
        self.blockers = kw.get("blockers", [])
        self.error = kw.get("error", "")


# ---------------- ① face selection ----------------

def test_narrowed_face_green_targeted_round():
    assert shared.green_run_face_narrowed(3, 0, "", []) == \
        {"ran": 3, "narrowed": True}


def test_narrowed_face_zero_run_targeted_stays_none():
    # fail-closed: the KI-220 zero-run supply face is never minted from a
    # targeted round
    assert shared.green_run_face_narrowed(0, 0, "", []) is None


def test_narrowed_face_red_blockers_and_malformed_stay_none():
    assert shared.green_run_face_narrowed(3, 1, "", []) is None          # failed
    assert shared.green_run_face_narrowed(3, 0, "boom", []) is None      # error
    assert shared.green_run_face_narrowed(
        3, 0, "", ["t261024-12-detail"]) is None                         # blockers
    assert shared.green_run_face_narrowed(None, 0, "", []) is None
    assert shared.green_run_face_narrowed("x", 0, "", []) is None        # malformed ran
    assert shared.green_run_face_narrowed(3, 0, "", None) is None        # malformed blockers


def test_legacy_green_run_face_still_ignores_targeted_only():
    # byte-identical replay leg: the legacy selector never minted a face for a
    # targeted round and still does not
    assert shared.green_run_face(3, 0, "", [], True) is None
    assert shared.green_run_face(3, 0, "", [], False) == {"ran": 3}


# ---------------- ② merge item ----------------

def _narrowed(sha=SHA, ran=3):
    return {"sha": sha, "ran": ran, "at": 1234, "narrowed": True}


def test_check_item_green_narrowed_on_matching_tree():
    it = shared.green_run_check_item(_narrowed(), SHA)
    assert it["green"] is True and it["reason_code"] == "narrowed"
    assert "NARROWED" in it["detail"]
    assert "NOT a full close" in it["detail"]
    assert SHA[:12] in it["detail"]


def test_check_item_stale_narrowed_after_main_sync_names_the_remedy():
    # the acceptance case: a narrowed round on the OLD tree, then the lane
    # syncs main — refused BY NAME, the detail names the run that re-anchors
    it = shared.green_run_check_item(_narrowed(sha=OTHER), SHA)
    assert it["green"] is False and it["reason_code"] == "stale"
    assert OTHER[:12] in it["detail"] and SHA[:12] in it["detail"]
    assert "green gate round on this tree" in it["detail"]
    assert "narrowed" in it["detail"]


def test_check_item_narrowed_with_zero_ran_fails_closed():
    it = shared.green_run_check_item(_narrowed(ran=0), SHA)
    assert it["green"] is False
    assert "narrowed mark with ran=0" in it["detail"]


def test_check_item_legacy_rows_unchanged():
    assert shared.green_run_check_item({}, SHA)["reason_code"] == "zero_run"
    assert shared.green_run_check_item(None, SHA)["reason_code"] == "zero_run"
    assert shared.green_run_check_item(_narrowed(), "")["green"] is False
    assert shared.green_run_check_item({"sha": SHA}, SHA)["reason_code"] == "zero_run"
    full = shared.green_run_check_item({"sha": SHA, "ran": 5}, SHA)
    assert full["green"] is True and full["reason_code"] == "ok"
    assert "NARROWED" not in full["detail"]
    no_sc = shared.green_run_check_item(
        {"sha": SHA, "ran": 0, "no_scenarios": True}, SHA)
    assert no_sc["green"] is True and no_sc["reason_code"] == "no_scenarios"
    bad = shared.green_run_check_item({"sha": SHA, "ran": "x", "narrowed": True}, SHA)
    assert bad["green"] is False
    # a narrowed face whose marker is missing behaves exactly as before KI-350
    unmarked = shared.green_run_check_item({"sha": SHA, "ran": 2}, SHA)
    assert unmarked["green"] is True and unmarked["reason_code"] == "ok"


# ---------------- ③ recorder (stubbed facade) ----------------

class _StubWf:
    ki220 = True
    ki350 = True
    result = {"ok": True, "sha": SHA}

    @staticmethod
    def patched(pid):
        return _StubWf.ki220 if pid != KI350 else _StubWf.ki350

    @staticmethod
    async def execute_activity(name, args=None, **kw):
        res = _StubWf.result
        if isinstance(res, Exception):
            raise res
        return res


def _stub_self(meta=None):
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = meta if meta is not None else {}
    wf.ticket_id = "t261024-12"
    wf._log = lambda *a, **k: None
    wf._now_epoch = lambda: 1234
    return wf


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(dev_lane, "workflow", _StubWf)
    _StubWf.ki220 = True
    _StubWf.ki350 = True
    _StubWf.result = {"ok": True, "sha": SHA}
    yield
    _StubWf.ki220 = True
    _StubWf.ki350 = True
    _StubWf.result = {"ok": True, "sha": SHA}


def test_records_narrowed_face_on_green_targeted_round(stubbed):
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"})
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), True))
    face = wf.meta["last_green_run"]
    assert face["narrowed"] is True
    assert face["sha"] == SHA and face["ran"] == 4 and face["at"] == 1234


def test_full_round_face_carries_no_narrowed_marker(stubbed):
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"})
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=7), False))
    face = wf.meta["last_green_run"]
    assert face["ran"] == 7 and "narrowed" not in face


def test_unpatched_replay_records_nothing_on_targeted_round(stubbed):
    # KI-061 discipline: an old in-flight history (no KI-350 marker) takes the
    # byte-identical old path — no face, and NO lane_head_sha call (the stub's
    # sentinel result stays unconsumed because green_run_face returns None)
    _StubWf.ki350 = False
    wf = _stub_self()
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), True))
    assert "last_green_run" not in wf.meta


def test_narrowed_arm_sha_failure_is_fail_closed_with_note(stubbed):
    # hook discipline (review comment 1): the narrowed arm shares the full
    # arm's lane_head_sha failure paths — no face, named green_run_note
    _StubWf.result = {"ok": False, "sha": "", "error": "rev-parse boom"}
    wf = _stub_self(meta={"worktree": "wt", "branch": "lane/x"})
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), True))
    assert "last_green_run" not in wf.meta
    note = wf.meta["green_run_note"]
    assert note["recorded"] is False and "rev-parse boom" in note["error"]
    # a recovered lane drops the stale note (t261011-17 rule) on the narrowed arm
    _StubWf.result = {"ok": True, "sha": SHA}
    asyncio.run(wf._ki220_record_green_run(_Receipt(ran=4), True))
    assert "green_run_note" not in wf.meta


def test_narrowed_arm_red_round_records_nothing(stubbed):
    wf = _stub_self()
    asyncio.run(wf._ki220_record_green_run(
        _Receipt(ran=4, failed=1, error="red detail"), True))
    asyncio.run(wf._ki220_record_green_run(_Receipt(), True))   # zero-run targeted
    assert "last_green_run" not in wf.meta


# ---------------- ④ single-consumer guard (review comment 2) ----------------

def _fn_src(tree, src, name_pred):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and name_pred(node.name):
            lines = src.splitlines()
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def test_no_release_or_closeout_surface_reads_the_green_run_face():
    # the narrowed marker may refresh the LANDING ANCHOR only: assert at the
    # source level that no release / close-out / closing-verdict function body
    # reads `last_green_run` (its only readers stay the merge_check argument
    # wiring and the develop-buffer landing step, pinned by the allowlist)
    allow = {
        "_ki220_record_green_run",          # the writer
        "_dev_buffer_land_step",            # the landing (merge stage) reader
        "_quick_merge_check",               # light-lane merge_check wiring
        "_light_merge_check",               # light-lane merge_check wiring
        "run",                              # dev-lane main loop (merge_check
                                            # argument wiring lives on the
                                            # straight-line segment there)
        # t261025-08 (KI-356): the enable signal handler — it only NAMES the
        # face in its docstring (it never reads or writes it); the flag it sets
        # widens the RECORDER's eligibility, so the single-consumer property is
        # untouched.
        "enable_narrowed_anchor",
    }
    for fname in ("dev_lane.py", "agent_activities.py", "light_lane.py"):
        src = (POC / fname).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = "\n".join(
                src.splitlines()[node.lineno - 1:node.end_lineno])
            if "last_green_run" not in seg:
                continue
            assert node.name in allow, (
                "%s:%s reads last_green_run but is not in the single-consumer "
                "allowlist — a narrowed marker must never reach a release/"
                "close-out verdict" % (fname, node.name))


# ---------------- ⑤ land_to_line refusal names the remedy ----------------

def _git(*args, cwd, check=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    return tmp_path


def _landing_setup(env, tmp_path):
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(
        [{"line_id": "buffer", "scope": "epic x", "owner": "integration",
          "repositories": [{"name": "r", "branch": "develop"}],
          "extra_scenarios": [], "version": 1}]), encoding="utf-8")
    repo = tmp_path / "r"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "ut@example.com", cwd=repo)
    _git("config", "user.name", "ut", cwd=repo)
    (repo / "main.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    _git("checkout", "-B", "lane", "main", cwd=repo)
    (repo / "feat.txt").write_text("feature\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "lane work", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def test_land_to_line_refusal_names_head_and_run_kind(env, tmp_path):
    repo, proven = _landing_setup(env, tmp_path)
    # main moves AFTER the gate anchored: the proven sha no longer contains it
    tree = _git("rev-parse", "main^{tree}", cwd=repo).stdout.strip()
    moved = _git("commit-tree", tree, "-p", "main", "-m", "main moves on",
                 cwd=repo).stdout.strip()
    _git("update-ref", "refs/heads/main", moved, cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    res = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t2412", project_key="proj", line_id="buffer",
        worktree=str(repo), proven_sha=proven)))
    assert not res.ok, res.error
    assert "does not contain current main" in res.error      # legacy phrase kept
    assert "Remedy, named" in res.error                      # actionable
    assert head[:12] in res.error                            # the sha to anchor on
    assert "NARROWED" in res.error                           # the run kind
    # best-effort head name: an unreadable worktree degrades to the placeholder,
    # never a raise
    res2 = asyncio.run(aa.land_to_line(aa.LandToLineArgs(
        ticket_id="t2412", project_key="proj", line_id="buffer",
        worktree=str(tmp_path / "nope"), proven_sha=proven)))
    assert not res2.ok and "lane HEAD unavailable" in res2.error
