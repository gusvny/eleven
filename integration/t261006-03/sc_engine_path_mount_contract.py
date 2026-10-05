#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_path_mount_contract.py — the engine stage boots with the bench
registry mounted at the FIXTURES ROOT, not the registry root (t261006-03,
KI-204 layer-3 residual on the engine path).

Grey-box L2, offline seconds, zero docker (runner-injected up_stage seam).
The two capture shapes differ in exactly one thing: which directory each
producer passes as `--fixtures-dir` (compose mounts it at /fixtures, and the
container's SANDBAR_PROJECTS_DIR=/fixtures/projects must resolve INSIDE that
mount):

  - self-booted (works): capture-lane.mjs:506-515 builds
    <tmp>/bench-registry/{projects,workspace} and passes the PARENT
    (bench-registry/) as --fixtures-dir.
  - engine (was red): _write_bench_registry returns the registry root
    <bench_dir>/projects and up_stage passed THAT as --fixtures-dir, so
    /fixtures/projects resolved to <bench_dir>/projects/projects — missing →
    no .migrated → in-repo seed replay (host-absolute dir) → new-session
    workspace create fails inside the container with workspace-invalid-path.

This scenario pins the producer contract at the public up_stage seam:
  A  the --fixtures-dir argument IS the fixtures root: a real directory that
     directly contains projects/ (with .migrated and the capture-bench
     project.yaml declaring the CONTAINER path /fixtures/workspace) and
     workspace/ — i.e. both halves of the injection agree on one mount.
  A2 the runner env carries SANDBAR_TEST_PROJECTS_DIR=/fixtures/projects and
     the declared workspace path inside project.yaml is a container path
     (/fixtures/...), never a host-absolute temp path.
  B  control (the pre-fix shape, pure layout): mounting the registry root as
     --fixtures-dir leaves <mount>/projects nonexistent, so the container's
     SANDBAR_PROJECTS_DIR points at nothing and seed replay is unavoidable —
     the named workspace-invalid-path failure follows deterministically (the
     LIVE anti-proof with real docker lives in
     t261006-03-engine-path-capture-journey).
  C  the two-shape evidence is printed as machine-quotable lines (both
     producers' --fixtures-dir level) so the gate receipt itself carries the
     difference writeup the ticket asks to close with.

Intent split: the truth table of _write_bench_registry's on-disk shape and
validate_stage_receipt's malformed-receipt matrix belong to the developer L1
battery; the real-docker journey (exit 0, flat PNGs, live anti-proof) belongs
to t261006-03-engine-path-capture-journey; registry loader semantics and the
fresh-home contract belong to t261005-16-bench-registry-fresh-home.

Engine module unavailable = ENV_FAIL exit 2. Pre-fix regression (up_stage
passing the registry root again) turns A red with the layout named.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  RED %s" % label)


def section(title):
    print("\n== %s" % title)


try:
    import ui_capture_stage as uis
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: engine module ui_capture_stage unavailable: %s" % e)
    sys.exit(2)

RECEIPT = {
    "project": "ui-shot-t261006-03-g0",
    "services": ["temporal", "dsh"],
    "ports": {"temporal": 7233, "console": 3199},
}


class FakeRunner:
    """Captures the exact command line and env the engine hands stage_docker."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, cap_s, env_extra):
        self.calls.append((list(cmd), float(cap_s), dict(env_extra or {})))
        return 0, json.dumps(RECEIPT), ""


section("A the --fixtures-dir argument is the FIXTURES ROOT (both halves agree)")
runner = FakeRunner()
project = uis.capture_stage_project("t261006-03")
receipt = uis.up_stage(project, repo_root=str(ROOT), runner=runner)
ok(receipt.get("project") == project, "up_stage returns the validated receipt")
ok(len(runner.calls) == 1, "exactly one stage_docker up invocation")
cmd, cap, env = runner.calls[0]
ok("--fixtures-dir" in cmd, "command carries --fixtures-dir")
fx = cmd[cmd.index("--fixtures-dir") + 1]
projects_dir = Path(fx) / "projects"
workspace_dir = Path(fx) / "workspace"
ok(projects_dir.is_dir(), "fixtures root directly contains projects/ (registry)")
ok((projects_dir / ".migrated").is_file(),
   "registry root carries .migrated (the loader's seed-skip criterion)")
ok(workspace_dir.is_dir(), "fixtures root directly contains workspace/")
pyaml = projects_dir / uis._BENCH_PROJECT_KEY / "project.yaml"
ok(pyaml.is_file(), "capture-bench project.yaml present under projects/")
ok(env.get("SANDBAR_TEST_PROJECTS_DIR") == "/fixtures/projects",
   "runner env pins SANDBAR_TEST_PROJECTS_DIR=/fixtures/projects")
ok(os.path.join(fx, "projects") == str(projects_dir),
   "container registry root /fixtures/projects maps INSIDE the mount")

section("A2 mirror check: the self-booted producer passes the same level")
lane_src = (ROOT / "server" / "ui-check" / "capture-lane.mjs").read_text("utf-8")
ok('"--fixtures-dir", benchFixturesDir]' in lane_src
   and "bench-registry" in lane_src,
   "capture-lane's docker path passes the PARENT bench-registry dir "
   "(shape true source; one-level agreement across producers)")

section("B control: the pre-fix shape deterministically re-creates the defect")
bench_dir = Path(fx)
prefx_mount = bench_dir / "projects"          # what up_stage passed BEFORE the fix
ok(not (prefx_mount / "projects").exists(),
   "pre-fix mount root (= registry root) does NOT contain projects/ "
   "-> container SANDBAR_PROJECTS_DIR points at nothing -> seed replay is "
   "unavoidable -> workspace-invalid-path (layout control)")
ok((prefx_mount / ".migrated").is_file() and not (prefx_mount / "projects" / ".migrated").exists(),
   "the .migrated marker sits at the pre-fix mount root, one level above where "
   "the container looks for it — the skip criterion never fires")
text = pyaml.read_text("utf-8")
ok("/fixtures/workspace" in text, "declared workspace is a CONTAINER path")
ok("/tmp/" not in text and "Documents" not in text,
   "no host-absolute temp/host-home path in the declared dirs (KI-204 face)")
uis._cleanup_bench_dir(project)  # reclaim the host bench dir (best-effort)

section("C two-shape evidence (machine-quotable, for the gate receipt)")
print("[two-shape] self-booted  : node server/ui-check/capture-lane.mjs --lane <wt> "
      "--out <wt>/.sandbar/screenshots  (own up: --fixtures-dir <tmp>/bench-registry, "
      "--services full)  -> EXIT=0, 10 flat PNGs (probe 261006, post t261006-02)")
print("[two-shape] engine (pre) : uis.run_capture_stage(services=full) -> stage_docker up "
      "--fixtures-dir <bench_dir>/projects (registry root) -> /fixtures/projects missing "
      "-> seed replay -> capture exit 1 'workspace-invalid-path ... <seed-host-dir>' "
      "(t261005-06 log, after f579cb0)")
print("[two-shape] engine (post): same journey, --fixtures-dir <bench_dir> "
      "(fixtures root, contains projects/ + workspace/) -> regression pinned by A above")

print("\nsummary: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
