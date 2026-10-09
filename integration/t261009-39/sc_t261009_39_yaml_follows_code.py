#!/usr/bin/env python3
"""t261009-39 — the generated workflow yaml follows the code that generates it.

User-facing face: server/workflows/dev-lane.yaml and light-lane.yaml are
read-only reference snapshots of the engine template classes (consumed by
server/tools/workflow.py for the lane diagrams). A user reading them must see
what the code actually runs. KI-154 is this exact fault mode (source copy
edited, generated file left stale -> mechanical gate long-red). Ticket
t261008-47 anglicized the engine copy; this scenario pins, mechanically and
without trusting that any human re-ran the generator:

  A  content-follows-code: copy server/engine (code only) + the committed
     server/workflows + server/tools/workflow.py into a throwaway tree, run the
     generator in FULL there, and byte-compare every produced yaml against the
     committed tree. Zero diff = the committed yaml is exactly what the code
     generates today (regenerated artefact == committed artefact, both faces).
  B  drift injection (negative control, KI-154): hand-edit one yaml in the
     throwaway tree; --check must go red and NAME the drifted file; a full
     generation must repair it back to the committed bytes. Proves the
     detector can actually fail and the generator is the lawful repair.
  C  the real tree's --check is green and read-only: exit 0 and the committed
     yaml bytes are unchanged after the check (a check that mutated its input
     would make this whole ticket meaningless).

Intent split (anti-duplication): t23-yaml-chain-truth (t260901-23) already owns
the "check is green + readable chain order on the real tree" intent; this
scenario owns the idempotent-regeneration face (byte equality between a fresh
generation and the committed artefacts) plus the inject/repair negative control,
which no registered scenario covers.

Three-state contract: engine venv missing or temporalio unimportable = ENV_FAIL
exit 2 (environment red, never a silent green). Any assertion miss = exit 1.
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ENGINE = REPO / "server" / "engine"
WORKFLOWS = REPO / "server" / "workflows"
WF_TOOL = REPO / "server" / "tools" / "workflow.py"
VENV_PY = ENGINE / ".venv" / "bin" / "python"
GEN = "gen_workflows_doc.py"

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


def run_gen(tree, *args):
    """Run the generator inside a throwaway tree; (rc, output)."""
    return subprocess.run(
        [str(VENV_PY), GEN, *args],
        cwd=str(tree / "server" / "engine"),
        capture_output=True, text=True, timeout=180,
    )


def yaml_fingerprint(directory):
    """{relative name: sha256} for every yaml snapshot in a workflows dir."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.glob("*.yaml"))
    }


def build_temp_tree(tmp):
    """Mirror the layout the generator derives from __file__: <tree>/server/
    {engine,tools,workflows}. Code only in engine (no venv/bin/caches/tests) —
    the generator needs the template-class modules and nothing else."""
    eng = tmp / "server" / "engine"
    shutil.copytree(
        ENGINE, eng,
        ignore=shutil.ignore_patterns(
            ".venv", "__pycache__", "bin", "node_modules", "tests", "out", "*.pyc"),
    )
    (tmp / "server" / "tools").mkdir(parents=True)
    shutil.copy2(WF_TOOL, tmp / "server" / "tools" / "workflow.py")
    shutil.copytree(WORKFLOWS, tmp / "server" / "workflows")
    return eng


def main():
    print("== t261009-39 yaml-follows-code ==")
    if not VENV_PY.is_file():
        print("ENV_FAIL: engine venv python missing: %s" % VENV_PY)
        return 2
    probe = subprocess.run(
        [str(VENV_PY), "-c", "import temporalio"],
        capture_output=True, timeout=60,
    )
    if probe.returncode != 0:
        print("ENV_FAIL: engine venv cannot import temporalio (generator premise)")
        return 2

    real_before = yaml_fingerprint(WORKFLOWS)
    ok(len(real_before) >= 2, "committed snapshots present (%d yaml files)" % len(real_before))

    with tempfile.TemporaryDirectory(prefix="t26100939-") as td:
        tmp = Path(td)
        build_temp_tree(tmp)

        # A. regenerate into the temp tree, compare with the committed bytes.
        r = run_gen(tmp)
        ok(r.returncode == 0, "full generation inside temp tree exits 0")
        ok(yaml_fingerprint(tmp / "server" / "workflows") == real_before,
           "fresh generation reproduces the committed yaml byte-for-byte (content follows code)")
        rc = run_gen(tmp, "--check")
        ok(rc.returncode == 0, "temp tree is green after regeneration")

        # B. inject drift (the KI-154 fault mode); detector names it, generator repairs it.
        target = tmp / "server" / "workflows" / "dev-lane.yaml"
        target.write_text(target.read_text("utf-8") + "\n# hand edit\n", "utf-8")
        rc = run_gen(tmp, "--check")
        ok(rc.returncode != 0, "injected hand-edit turns --check red")
        ok("dev-lane" in (rc.stdout + rc.stderr), "red names the drifted file")
        rc = run_gen(tmp)
        ok(rc.returncode == 0, "full generation repairs the drift")
        ok(yaml_fingerprint(tmp / "server" / "workflows") == real_before,
           "repaired artefact equals the committed bytes (generator is the lawful writer)")

    # C. the real tree: check green and read-only.
    rc = subprocess.run(
        [str(VENV_PY), GEN, "--check"],
        cwd=str(ENGINE), capture_output=True, text=True, timeout=180,
    )
    ok(rc.returncode == 0, "real-tree --check green (%s)" % rc.stdout.strip().splitlines()[-1:] or "")
    ok(yaml_fingerprint(WORKFLOWS) == real_before,
       "real-tree check is read-only (committed bytes unchanged)")

    print("== pass=%d fail=%d ==" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
