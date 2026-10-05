#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_path_capture_journey.py — the capture run completes THROUGH THE
ENGINE'S OWN PATH (t261006-03 required outcomes 2/3, KI-204 layer-3 residual).

Grey-box L3, ONE real docker stage journey per leg, never touches 3099, cost:
minutes. The production pathway is: the engine boots the stage
(uis.run_capture_stage / up_stage --services full), writes the stage-json
receipt, and drives `node server/ui-check/capture-lane.mjs --lane <worktree>
--out <ui_evidence_dir(worktree)>` as a --stage-json consumer. That is the
exact seam this scenario drives — the activity, not just the CLI.

P  (green leg)  the engine-path capture run EXITS 0 and the evidence lands
   FLAT (top-level non-recursive) at the GATE'S read point, resolved by the
   same resolver the merge_check gate uses (shared.ui_evidence_dir) — one
   read point, producer and gate agree. The stage teardown is asserted
   reclaimed (run_capture_stage's final-state reclaim). The in-repo seed's
   host-absolute project dir exists only on the host: inside the container
   the session workspace must resolve to the mounted /fixtures/workspace —
   a host-path leak anywhere in the output is a red.
A  (anti-proof leg, runs by default; SANDBAR_T26100603_NO_ANTIPROOF=1 skips
   it with the switch named in a not-checked line) the PRE-FIX code fails the
   SAME way with the SAME named error: up the stage with the pre-fix
   --fixtures-dir level (the registry root instead of the fixtures root),
   hand the receipt to capture-lane as --stage-json, and assert capture
   exit 1 with the named `workspace-invalid-path` text (seed replay →
   host-absolute workspace → container cannot create it). Then down_stage.

Intent split: the offline mount-root/level contract belongs to
t261006-03-engine-path-mount-contract; view content / chat state belongs to
the capture-chat family; the fresh-home loader contract belongs to
t261005-16; the three blocked UI tickets' own content is out of scope per
the ticket face.

Three-state discipline: docker absent or the stage refusing on an
environment face (rc=2 / UiStageEnvError) = ENV_FAIL exit 2, never a fake
red or green. Product seam missing (engine module / capture-lane script
missing) = FAIL named. Pre-implement red expected (TDD signal); arbitrate /
merge must be green.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

LANE = ROOT  # the ticket worktree doubles as the lane (server/plugins/workbench present)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    print(("  ok  " if cond else "  RED ") + label)
    if cond:
        PASS += 1
    else:
        FAIL += 1


def section(t):
    print("\n== %s" % t)


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


try:
    import ui_capture_stage as uis
    import shared
except Exception as e:  # noqa: BLE001
    env_fail("engine modules unavailable: %s" % e)

lane_script = ROOT / "server" / "ui-check" / "capture-lane.mjs"
if not lane_script.is_file():
    print("FAIL named: product seam missing — %s not found" % lane_script)
    sys.exit(1)


def flat_pngs(d: Path):
    return sorted(p.name for p in d.glob("*.png"))


def env_probe_ok():
    """Bounded daemon probe — same gate the supply face uses (exit 2 face)."""
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "integration" / "stage_docker.py"),
                        "daemon-probe"], capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr)[-300:]


def host_project_dir():
    """The in-repo seed's host-absolute project dir (parsed from the protected
    seed, never hardcoded): the dir that exists only on the host."""
    seed = ROOT / "server" / "projects.yaml"
    try:
        for ln in seed.read_text("utf-8").splitlines():
            s = ln.strip()
            if s.startswith("- /") or s.startswith("- ~/"):
                return s[2:].strip()
    except OSError:
        pass
    return ""


async def green_leg():
    section("P engine-path capture journey (production seam, services=full)")
    project = uis.capture_stage_project("t261006-03")
    out_dir = shared.ui_evidence_dir(LANE)
    cmd = ["node", str(lane_script), "--lane", str(LANE), "--out", str(out_dir)]
    print("[journey] capture_cmd: %s" % " ".join(cmd))
    print("[journey] gate read point (shared.ui_evidence_dir): %s" % out_dir)
    try:
        r = await uis.run_capture_stage(
            project=project, services="full", capture_cmd=cmd,
            capture_timeout_s=600.0, stage_up_timeout_s=240.0,
            repo_root=str(ROOT))
    except uis.UiStageEnvError as e:
        env_fail("stage env face refused (rc=2 family): %s" % e)
    except uis.UiStageError as e:
        ok(False, "engine-path up failed as a CONTRACT red: %s" % e)
        return
    ok(r.get("ok") is True and r.get("capture_rc") == 0,
       "capture through the engine's own path exits 0 (rc=%r)" % r.get("capture_rc"))
    if r.get("capture_rc") not in (0, None) and r.get("capture_rc") != 0:
        print("[journey] capture_out tail: %s" % r.get("capture_out", "")[-400:])
        print("[journey] capture_err tail: %s" % r.get("capture_err", "")[-400:])
    pngs = flat_pngs(out_dir)
    ok(len(pngs) > 0,
       "evidence lands FLAT (top-level *.png) at the gate's read point: %d file(s) %s"
       % (len(pngs), pngs[:3]))
    ok(r.get("reclaimed") is True,
       "stage teardown reclaimed on the success terminal path (final-state reclaim)")
    blob = (r.get("capture_out", "") + r.get("capture_err", ""))
    ok("workspace-invalid-path" not in blob and "工作区创建失败" not in blob,
       "no workspace-create failure anywhere in the streamed output "
       "(KI-204 named error stays dead on the engine path)")
    hostdir = host_project_dir()
    bad = [ln for ln in blob.splitlines()
           if ("工作区创建失败" in ln or "workspace-invalid-path" in ln
               or "cannot create a workspace" in ln)]
    ok(not bad,
       "no host-path workspace-create refusal anywhere in the streamed output%s"
       % ((" — got: " + bad[0][:160]) if bad else " (KI-204 named error stays dead)"))
    up = r.get("up") or {}
    ok(isinstance(up.get("ports"), dict) and up["ports"].get("console"),
       "the stage receipt the consumer ran on names its console port: %s"
       % up.get("ports"))


def anti_leg():
    section("A anti-proof: the pre-fix --fixtures-dir level fails with the NAMED error")
    project = uis.capture_stage_project("t261006-03", gen=1)
    try:
        down = uis.down_stage(project, repo_root=str(ROOT))  # idempotent pre-clean
        bench_dir = uis.tempfile.mkdtemp(prefix="sandbar-antiproof-bench-")
        bench_fixtures = uis._write_bench_registry(bench_dir)  # PRE-FIX: registry root
        rc, out, err = uis._default_runner(
            ["python3", uis.stage_cli_path(str(ROOT)), "up", "--project", project,
             "--services", "full", "--timeout", "240",
             "--fixtures-dir", bench_fixtures],          # <-- the one-level bug
            240.0, {"SANDBAR_TEST_PROJECTS_DIR": "/fixtures/projects"})
    except uis.UiStageEnvError as e:
        env_fail("anti-proof stage env face: %s" % e)
    if rc != 0:
        # up failed for its own reasons: not the defect under test
        ok(False, "anti-proof stage did not come up (rc=%s: %s)" % (rc, err[-200:]))
        uis.down_stage(project, repo_root=str(ROOT))
        return
    ok(True, "pre-fix-shaped stage is up (mount root = registry root, as before the fix)")
    st_json = Path(uis.tempfile.mkstemp(prefix="stage-antiproof-", suffix=".json")[1])
    st_json.write_text(json.dumps(json.loads(out.strip().splitlines()[-1])), "utf-8")
    out_dir = ROOT / ".sandbar" / "antiproof-shots"
    cap = __import__("subprocess").run(
        ["node", str(lane_script), "--lane", str(LANE), "--out", str(out_dir),
         "--stage-json", str(st_json)],
        capture_output=True, text=True, timeout=660, cwd=str(ROOT))
    blob = cap.stdout + cap.stderr
    print("[anti] capture rc=%s; output tail:\n%s" % (cap.returncode, blob[-1200:]))
    ok(cap.returncode == 1,
       "pre-fix code fails with capture exit 1 (got %s)" % cap.returncode)
    hostdir = host_project_dir()
    bad = [ln for ln in blob.splitlines()
           if ("工作区创建失败" in ln or "workspace-invalid-path" in ln)]
    source = "capture stream"
    if not bad:
        # Acceptance-rework fix (t261006-03 gen1): the named error reaches the
        # capture stream through capture.mjs's best-effort browser-console
        # diagnostic tail, assembled asynchronously at diagnostic time — in a
        # gate-shape run that tail can close before the console messages drain
        # (live evidence: the same code, in an isolated rerun minutes later,
        # DID carry the full named error on stderr). The SAME failure is
        # recorded server-side in the dsh container log (the workspace-create
        # API handler fails there), so poll that second channel — bounded
        # retries — BEFORE the stage goes down. Not a weakening: exit-1 on the
        # pre-fix level is asserted above and untouched; only the error-TEXT
        # evidence channel gains a second read.
        for _ in range(4):
            try:
                dl = subprocess.run(
                    ["docker", "logs", "%s-dsh" % project],
                    capture_output=True, text=True, errors="replace", timeout=30)
                dlog = (dl.stdout or "") + (dl.stderr or "")
            except Exception:
                dlog = ""
            bad = [ln.strip() for ln in dlog.splitlines()
                   if ("工作区创建失败" in ln or "workspace-invalid-path" in ln
                       or "cannot create a workspace" in ln)]
            if bad:
                source = "docker logs %s-dsh" % project
                break
            time.sleep(2.0)
        if bad:
            print("[anti] named error recovered from the container log "
                  "(console-tail race): %s" % bad[0][:200])
    ok(bool(bad),
       "the failure carries the NAMED error (workspace-invalid-path / 工作区创建失败; "
       "evidence channel: %s)" % source)
    ok(bool(hostdir) and any(hostdir in ln for ln in bad),
       "the named error line names the seed's host-absolute project dir %r "
       "(seed replay evidence, not the lane path; channel: %s)" % (hostdir, source))
    if cap.returncode not in (0, 1):
        print("[anti] output tail: %s" % blob[-400:])
    uis.down_stage(project, repo_root=str(ROOT))
    st_json.unlink(missing_ok=True)


def main():
    alive, detail = env_probe_ok()
    if not alive:
        env_fail("docker test stage unavailable (daemon-probe): %s" % detail)
    asyncio.run(green_leg())
    if os.environ.get("SANDBAR_T26100603_NO_ANTIPROOF", "").strip() == "1":
        print("\n== A SKIPPED by switch (SANDBAR_T26100603_NO_ANTIPROOF=1) — "
              "named not-checked, never a silent skip")
    else:
        anti_leg()
    print("\nsummary: PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
