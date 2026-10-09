"""t261009-39 — the generated workflows/*.yaml follow the code, mechanically.

The ticket's question (settled on evidence): server/workflows/dev-lane.yaml and
light-lane.yaml are generator output (server/engine/gen_workflows_doc.py from
the template classes' STAGES), never hand-edited. These tests pin that
invariant so the assertion does not depend on a human having run the
generator:

  - check green on the real tree: the generator's own --check passes on the
    repo as committed;
  - regenerate into a temp copy and byte-compare: a full generation run in a
    throwaway copy of the tree reproduces the committed yaml byte for byte;
  - the check can actually fail: a corrupted temp copy is reported as drift
    (non-zero exit, named files) — for the right reason, not an import crash;
  - malformed input: a torn yaml in the temp copy exercises the check's
    mismatch path the same way.

Layout note (review_plan condition 1): the generator resolves everything from
its own __file__ (REPO = parents[1]), so the temp copy must reproduce
<tmp>/server/engine, <tmp>/server/tools/workflow.py and <tmp>/server/workflows.
cwd is pinned explicitly in every subprocess call; it does not affect
resolution but pinning keeps the run reproducible.

Offline: zero Temporal / docker / network; everything runs in a tmp_path copy
with a subprocess timeout, torn down on pass, fail and timeout paths.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "server" / "engine"
GENERATOR = ENGINE / "gen_workflows_doc.py"
WORKFLOWS = REPO / "server" / "workflows"
YAML_IDS = ("dev-lane", "light-lane")
TIMEOUT = 120


def _run(generator: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the generator in a copy of the tree, with a hard timeout.

    subprocess.run raises TimeoutExpired on timeout; the caller's tmp_path
    fixture (pytest's TemporaryDirectory) tears the copy down either way, so
    every path — pass, fail, timeout — ends with full cleanup and no stray
    process outlives the call (run() kills the child before raising).
    """
    return subprocess.run(
        [sys.executable, str(generator), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def _make_temp_repo(tmp_path: Path) -> Path:
    """Copy the minimum tree the generator needs into tmp_path.

    server/engine (code only — the venv and caches stay behind; the
    interpreter is inherited via sys.executable), server/tools/workflow.py
    (the read-back check loads it by path), and server/workflows (the
    committed snapshots under test).
    """
    repo = tmp_path / "repo"
    (repo / "server" / "tools").mkdir(parents=True)
    shutil.copytree(
        ENGINE, repo / "server" / "engine",
        ignore=shutil.ignore_patterns(".venv", "__pycache__"),
    )
    shutil.copy2(REPO / "server" / "tools" / "workflow.py",
                 repo / "server" / "tools" / "workflow.py")
    shutil.copytree(WORKFLOWS, repo / "server" / "workflows")
    return repo


def test_check_green_on_committed_tree() -> None:
    """The generator's own check is green on the repo as committed."""
    r = _run(GENERATOR, ENGINE, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    # copy-lang-allow:fixture — asserts the generator's own Chinese status output verbatim.
    assert "check 绿" in r.stdout  # copy-lang-allow:fixture — generator's status line, not new copy


def test_regen_in_temp_copy_matches_committed_yaml(tmp_path: Path) -> None:
    """Full regeneration in a throwaway copy reproduces the committed yaml.

    Byte comparison, both files — the "content follows the code" assertion.
    """
    repo = _make_temp_repo(tmp_path)
    r = _run(repo / "server" / "engine" / GENERATOR.name,
             repo / "server" / "engine")
    assert r.returncode == 0, r.stdout + r.stderr
    for tid in YAML_IDS:
        generated = (repo / "server" / "workflows" / f"{tid}.yaml").read_bytes()
        committed = (WORKFLOWS / f"{tid}.yaml").read_bytes()
        assert generated == committed, f"{tid}.yaml drifted from the generator"


@pytest.mark.parametrize("mutate", ["append_garbage", "truncate"])
def test_check_fails_on_drifted_copy(tmp_path: Path, mutate: str) -> None:
    """A drifted temp copy is reported as drift — the right reason, exit 1.

    Malformed-input cases: appended garbage makes the file differ from the
    render; a truncated file is torn yaml. Either way the check must name the
    drifted template and exit 1, never crash on import.
    """
    repo = _make_temp_repo(tmp_path)
    target = repo / "server" / "workflows" / "dev-lane.yaml"
    if mutate == "append_garbage":
        target.write_text(  # copy-lang-allow:fixture — quotes the generator's drift line shape
            target.read_text("utf-8") + "\n手改行 hand edit\n", "utf-8")
    else:
        target.write_text(target.read_text("utf-8")[:200], "utf-8")
    r = _run(repo / "server" / "engine" / GENERATOR.name,
             repo / "server" / "engine", "--check")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "dev-lane" in r.stdout
    # copy-lang-allow:fixture — the check's verdict word, from the generator.
    assert "漂移" in r.stdout
