# -*- coding: utf-8 -*-
"""t261005-16 bench registry injection (engine side), L1 battery: the
engine-owned production stage path must not replay the in-repo legacy seed
(KI-204 acceptance-rework face).

Faces under test (server/engine/ui_capture_stage.py):
- _write_bench_registry: the Python mirror (shape true source =
  capture-lane.mjs buildBenchRegistry) — schema v1 top-level `project:` LIST
  form (a flat top-level key:/name:/dirs: block is quarantined by both
  parsers, t261005-16 arbitrate round 1), .migrated marker present,
  dirs[0] really existing, occupied target fails loud (O_EXCL);
- up_stage wiring: the cmd carries --fixtures-dir (the created projects root)
  and the runner env carries SANDBAR_TEST_PROJECTS_DIR=/fixtures/projects
  (compose passes it into the container as SANDBAR_PROJECTS_DIR); a failed up
  reclaims the host dir in place;
- down_stage reclaim: the host dir is removed after a successful teardown
  (end-state reclaim matrix: success / unknown project);
- the emitted registry loads through the production loader
  (shared.load_projects_registry with SANDBAR_PROJECTS_DIR at the created
  root) to exactly capture-bench with an existing workspace — the engine-side
  twin of the scenario's E1 face.

Everything goes through the runner injection seam (fake runner + fixed
receipts); zero docker, zero node, zero network; temp dirs reclaimed per test.
Run from the repo root:
`server/engine/.venv/bin/python -m pytest server/engine/tests/test_t261005_16_bench_registry_stage.py -q`.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui_capture_stage as uis  # noqa: E402
import shared as engine_shared  # noqa: E402


GOOD_RECEIPT = json.dumps({"project": "ui-shot-x-g0", "ports": {"console": 21000}})


class FakeRunner:
    def __init__(self, rc=0, out="", err=""):
        self.script = dict(rc=rc, out=out, err=err)
        self.calls = []

    def __call__(self, cmd, cap, env_extra):
        self.calls.append({"cmd": list(cmd), "cap": cap, "env": dict(env_extra or {})})
        return self.script["rc"], self.script["out"], self.script["err"]


def fake_repo(tmp_path):
    """Fake repo root: stage_cli_path only needs integration/stage_docker.py
    to exist."""
    d = tmp_path / "integration"
    d.mkdir(exist_ok=True)
    (d / "stage_docker.py").write_text("", encoding="utf-8")
    return str(tmp_path)


@pytest.fixture(autouse=True)
def _clean_bench_dirs():
    yield
    uis._BENCH_TMP_DIRS.clear()


# ---- _write_bench_registry: shape + fail-loud -------------------------------

def test_bench_registry_shape_and_live_dir(tmp_path):
    root = uis._write_bench_registry(str(tmp_path))
    assert os.path.isfile(os.path.join(root, ".migrated"))
    text = open(os.path.join(root, "capture-bench", "project.yaml"), encoding="utf-8").read()
    # schema v1 list form (never a flat block — both parsers quarantine it,
    # t261005-16 arbitrate round 1)
    assert "schema: v1" in text and "project:" in text
    assert "  - key: capture-bench" in text and "    name: Capture Bench" in text
    dirs = [ln.strip("- ").strip() for ln in text.splitlines()
            if ln.startswith("      - ")]
    # stage pathway (arbitrate round 3): the declared workspace must be the
    # CONTAINER path under the mount — a host temp path is the KI-204 dead-dir
    # defect one path away.
    assert dirs == ["/fixtures/workspace"], dirs
    assert os.path.isdir(os.path.join(str(tmp_path), "workspace"))  # host side really created


def test_bench_registry_target_occupied_fails_loud(tmp_path):
    uis._write_bench_registry(str(tmp_path))
    with pytest.raises(OSError):
        uis._write_bench_registry(str(tmp_path))  # occupied target -> O_EXCL red


def test_bench_registry_loads_via_production_loader(tmp_path, monkeypatch):
    """Engine-side twin of the scenario's E1: the production loader sees exactly
    capture-bench with an existing workspace (zero quarantined entries)."""
    root = uis._write_bench_registry(str(tmp_path))
    old = os.environ.get("SANDBAR_PROJECTS_DIR")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", root)
    try:
        projects, quarantined = engine_shared.load_projects_registry()
        assert [p["key"] for p in projects] == ["capture-bench"]
        # The declared dir is the CONTAINER path (/fixtures/workspace) — valid
        # inside the container, not on this host (arbitrate round 3).
        assert projects[0]["dirs"] == ["/fixtures/workspace"]
        assert quarantined == []
    finally:
        if old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = old


# ---- up_stage wiring --------------------------------------------------------

def test_up_stage_injects_bench_registry(tmp_path):
    r = FakeRunner(rc=0, out=GOOD_RECEIPT + "\n")
    receipt = uis.up_stage("ui-shot-x-g0", repo_root=fake_repo(tmp_path), runner=r)
    assert receipt["ports"]["console"] == 21000
    cmd = r.calls[0]["cmd"]
    i = cmd.index("--fixtures-dir")
    fixtures = cmd[i + 1]
    assert os.path.isfile(os.path.join(fixtures, "capture-bench", "project.yaml"))
    assert r.calls[0]["env"]["SANDBAR_TEST_PROJECTS_DIR"] == "/fixtures/projects"
    # The dir lives until teardown (registered).
    assert uis._BENCH_TMP_DIRS.get("ui-shot-x-g0") == str(Path(fixtures).parent)


def test_up_stage_failure_cleans_bench_dir(tmp_path):
    r = FakeRunner(rc=1, err="STAGE_UP_BOOM\n")
    with pytest.raises(uis.UiStageError):
        uis.up_stage("ui-shot-x-g0", repo_root=fake_repo(tmp_path), runner=r)
    assert uis._BENCH_TMP_DIRS == {}  # a failed up reclaims the host dir in place


def test_down_stage_cleans_bench_dir(tmp_path):
    r = FakeRunner(rc=0, out="stage down\n")
    uis._BENCH_TMP_DIRS["ui-shot-x-g0"] = str(tmp_path)
    uis.down_stage("ui-shot-x-g0", repo_root=fake_repo(tmp_path), runner=r)
    assert uis._BENCH_TMP_DIRS == {}
    assert not tmp_path.exists()  # the host registry dir is really gone (success path)


def test_down_stage_unknown_project_no_raise(tmp_path):
    r = FakeRunner(rc=0, out="stage down\n")
    out = uis.down_stage("never-up", repo_root=fake_repo(tmp_path), runner=r)
    assert out["ok"] is True
