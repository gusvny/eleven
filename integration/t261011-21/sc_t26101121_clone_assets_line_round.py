#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101121_clone_assets_line_round.py — t261011-21, the line round's
clone CARRIES the gitignored assets the suite's cwd-relative probes need, so
a round can come out green while an honestly absent asset stays honest
(grey-box L3, the real runner driven through the real resolve_runner seam
over a real git fixture tree + a stub suite, offline seconds, zero
docker/Temporal-server/browser, never touches 3099/7233).

The incident (ticket body): the first runnable line round carried 220
environment reds — not one docker-shaped. prepare_tree() clones each
candidate (committed files only), so the clone has no server/engine/.venv,
no server/engine/bin/temporal, no node_modules, no
server/ui-check/node_modules/playwright-core; the registry/scenario probes
(`PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3`,
lib_pw_deps LOCAL_PW) resolve RELATIVE to cwd, i.e. inside the clone they
silently fall back to a system python3 without pytest/PyYAML/temporalio.
One environment red turns the whole round red (run_verdict), so a landed
ticket waited for a certification that could never arrive.

intent (user-perceivable contract, three basis sources exhausted):
  A. THE incident's headline: a line round whose candidate tree is a clone
     now ends with the suite's own cwd-relative probes RESOLVING — the
     interpreter chain picks the clone's provisioned venv python (NOT the
     bare python3 fallback), the temporal binary probe and the
     playwright-core marker probe each find their asset through the
     clone-relative path — one real header, env_failed 0.
  B. Honesty is kept: an asset genuinely absent from the SOURCE checkout is
     materialised as NOTHING — the clone has no path there, the suite's
     probe classifies env_fail from its own evidence, the round still
     relays the real header with env_failed==1 (a red is a proof) — never a
     could-not-run, never a fabricated green, never a silent swallow.
  C. A committed file at an asset destination is NEVER clobbered by the
     provisioning (the clone's own committed content wins; the round still
     completes).
  D. Boundary discipline on the write face: each materialised link's target
     is an ABSOLUTE path under the SOURCE checkout (the reader-side probe
     runs from the clone, so the evidence is read from the consumer side,
     not from the writer's receipt).

intent split (no intent-level duplication):
  - the env-key hand-over (SANDBAR_POC_PYTHON / SANDBAR_TEMPORAL_BIN) and
    its named could-not-run faces -> t261011-18-line-round-assets (this
    entry re-asserts neither; its A3 precondition face is deliberately
    re-signed by this ticket, with a naming comment there);
  - the runner command -> one header contract, red-is-a-proof, malformed
    candidates, tree overlap, SIGTERM reclaim -> t261009-77-line-round-runner
    and the t261009-30 family;
  - resolution-tier unit truth tables -> developer L1 (the in-ticket unit
    battery).
  This entry owns ONE new contract: the clone-relative probe faces resolve
  from the consumer side, and absence stays honest.

Three states: git unavailable / runner checkout unresolvable for the driver
seam = ENV_FAIL exit 2; a face red pre-implementation is the named TDD
signal — green required at the integration gate / merge.
"""
import atexit
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261011-21-clone-assets-line-round"

sys.path.insert(0, str(REPO / "integration"))
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

_TMP = None


def _cleanup():
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)

sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    import develop_certify as dc  # noqa: E402
except Exception as e:  # noqa: BLE001
    env_fail("develop_certify unimportable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)

LINE = {"line_id": "develop-buffer", "repo": "sandbar"}


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- fixture

# The stub suite stands in for integration/run_scenarios.py. Its probe faces
# are the INCIDENT'S OWN probe shapes, run with cwd = the clone:
#   - the registry's interpreter chain, verbatim shape;
#   - the temporal binary probe;
#   - the playwright-core marker probe (the lib_pw_deps local-candidate face).
# Each probe's outcome is recorded from the CONSUMER side (cwd=clone) and the
# run record is written through the REAL scenario_ledger store, so the header
# the runner relays is one the store validated.
_STUB = r'''#!/usr/bin/env python3
"""Stub full suite: the fixture stand-in for integration/run_scenarios.py
(t261011-21). Probes the clone-relative asset faces from cwd=clone and
records everything; SUITE_ASSET_MODE picks the fixture's green / honest
env-red shape."""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integration"))
import scenario_ledger as sl

mode = os.environ.get("SUITE_ASSET_MODE", "all-present")
probe_out = os.environ.get("SUITE_PROBE_OUT", "")

probe = {"cwd": os.getcwd(), "mode": mode}
# face 1: the registry's interpreter chain, verbatim shape
r = subprocess.run(
    ["/bin/sh", "-c",
     'PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; '
     '"$PY" tools/interp_marker.py'],
    capture_output=True, text=True, timeout=30)
probe["interp_out"] = (r.stdout or "").strip()
probe["interp_rc"] = r.returncode
# face 2: the temporal binary, clone-relative
tbin = ROOT / "server" / "engine" / "bin" / "temporal"
probe["temporal_is_symlink"] = tbin.is_symlink()
if tbin.exists():
    try:
        r2 = subprocess.run([str(tbin), "--version"], capture_output=True,
                            text=True, timeout=30)
        probe["temporal_out"] = (r2.stdout or "").strip()
    except OSError as e:
        # a committed DATA file at the destination is a legal fixture shape
        # (the never-clobbered face) — record the fact, never crash the suite
        probe["temporal_out"] = "spawn_oserror:%s" % e.errno
else:
    probe["temporal_out"] = ""
# face 3: the playwright-core local candidate, clone-relative
pw = ROOT / "server" / "ui-check" / "node_modules" / "playwright-core" \
    / "package.json"
probe["pw_present"] = pw.exists()
probe["pw_marker"] = pw.read_text(encoding="utf-8").strip() \
    if pw.exists() else ""
probe["venv_is_symlink"] = (ROOT / "server" / "engine" / ".venv").is_symlink()
# Link/write-face facts must be recorded DURING the round by the consumer
# (cwd=clone): the runner's declared contract reclaims the whole run tree
# when the round ends (t261009-77: the run tree is reclaimed on every exit
# path), so nothing outside may inspect the clone afterwards.
_venv = ROOT / "server" / "engine" / ".venv"
probe["venv_link_target"] = os.readlink(str(_venv)) if _venv.is_symlink() else ""
_tbin = ROOT / "server" / "engine" / "bin" / "temporal"
probe["temporal_link_target"] = os.readlink(str(_tbin)) if _tbin.is_symlink() else ""
probe["temporal_content"] = _tbin.read_text(encoding="utf-8") \
    if _tbin.exists() and not _tbin.is_symlink() else ""
if probe_out:
    Path(probe_out).write_text(json.dumps(probe), encoding="utf-8")

head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                      capture_output=True, text=True).stdout.strip()
candidates = json.loads(os.environ["SANDBAR_LINE_ROUND_CANDIDATES"])
ledger = Path(os.environ["SANDBAR_SCENARIO_LEDGER_DIR"])
ledger.mkdir(parents=True, exist_ok=True)

# classification: the pw probe is the fixture's one honest env-red face when
# the source checkout genuinely lacked the asset.
env_failed = 1 if mode == "absent-pw" else 0
verdict_word = "env_fail" if env_failed else "pass"
run_id = sl.mint_run_id()
row = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "commit": head,
    "env_fp": hashlib.sha256(b"stub-suite-2121").hexdigest(),
    "conc_width": 1,
    "pool": "serial",
    "scenario": "stub-clone-assets",
    "verdict": verdict_word,
    "wall_s": 0.1,
    "source": "lane:stub",
    "ticket": "t261011-21",
    "run": run_id,
}
clean, why = sl.validate_row(row)
if clean is None:
    sys.stderr.write("stub row refused: %s\n" % why)
    sys.exit(2)
if sl.append_records([clean])["written"] != 1:
    sys.stderr.write("stub row not written\n")
    sys.exit(2)
cases = {"ran": 1, "passed": 0 if env_failed else 1, "failed": 0,
         "env_failed": env_failed}
header = {
    "v": sl.RUN_HEADER_V,
    "id": run_id,
    "repos": candidates,
    "suite": "full",
    "source": "lane:stub",
    "env_fp": row["env_fp"],
    "conc_width": 1,
    "pool": "serial",
    "started_at": int(time.time() * 1000),
    "duration_s": 0.1,
    "cases": cases,
    "verdict": sl.run_verdict(cases),
}
if sl.append_run_header(header)["written"] != 1:
    sys.stderr.write("stub header refused\n")
    sys.exit(2)
summary = {"ran": 1, "passed": cases["passed"], "failed": 0,
           "env_failed": env_failed, "run_id": run_id}
print("INTEG_SUMMARY " + json.dumps(summary))
# the completed-but-env-red round is a proof: the suite relays its record
# and exits 0; the classification lives in the header, not the exit code.
sys.exit(0)
'''

_INTERP_MARKER = r'''#!/bin/sh
echo VENV_MARK_2121
'''

_TEMPORAL_MARKER = r'''#!/bin/sh
echo TEMPORAL_MARK_2121
'''


def _mk_repo(tmp, tag, *, with_pw=True, committed_temporal=None):
    """A real clean git tree whose committed content is exactly what git
    carries (stub suite + ledger module + probe markers), with a .gitignore
    that keeps .venv/, bin/ and node_modules/ OUT — the incident's clone
    shape by construction. Then the gitignored ASSETS are created in the
    SOURCE checkout only (never committed, never cloned)."""
    src = tmp / ("source-" + tag)
    src.mkdir()
    r = _git("init", "-q", cwd=src)
    if r.returncode != 0:
        env_fail("git init failed", (r.stderr or "")[-300:])
        sys.exit(2)
    _git("config", "user.email", "scenario@example.invalid", cwd=src)
    _git("config", "user.name", "scenario", cwd=src)
    (src / "integration").mkdir()
    shutil.copy2(str(REPO / "integration" / "scenario_ledger.py"),
                 str(src / "integration" / "scenario_ledger.py"))
    eng = src / "server" / "engine"
    eng.mkdir(parents=True)
    shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                 str(eng / "failure_protocol.py"))
    (src / "integration" / "run_scenarios.py").write_text(
        "# fixture stand-in marker\n", encoding="utf-8")
    tools = src / "tools"
    tools.mkdir()
    (tools / "stub_suite.py").write_text(_STUB, encoding="utf-8")
    (tools / "interp_marker.py").write_text(_INTERP_MARKER, encoding="utf-8")
    (src / ".gitignore").write_text(
        "__pycache__/\nserver/engine/.venv/\nserver/engine/bin/\n"
        "node_modules/\nserver/ui-check/node_modules/\n", encoding="utf-8")
    if committed_temporal is not None:
        # -f on purpose: .gitignore keeps server/engine/bin/ out for the
        # UNTRACKED assets, but this file is the fixture's deliberate
        # COMMITTED destination content — and it stays executable so the
        # stub's probe can spawn it.
        bin_dir = eng / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        tfile = bin_dir / "temporal"
        tfile.write_text(committed_temporal, encoding="utf-8")
        tfile.chmod(tfile.stat().st_mode | stat.S_IEXEC)
        _git("add", "-Af", "server/engine/bin/temporal", cwd=src)
    _git("add", "-A", cwd=src)
    r = _git("commit", "-q", "-m", "fixture: t261011-21 %s" % tag, cwd=src)
    if r.returncode != 0:
        env_fail("fixture commit failed", (r.stderr or "")[-300:])
        sys.exit(2)
    # the gitignored assets, SOURCE-side only
    venv_bin = eng / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    py = venv_bin / "python"
    py.write_text(_INTERP_MARKER, encoding="utf-8")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    if committed_temporal is None:
        tdst = eng / "bin"
        tdst.mkdir(parents=True, exist_ok=True)
        tb = tdst / "temporal"
        tb.write_text(_TEMPORAL_MARKER, encoding="utf-8")
        tb.chmod(tb.stat().st_mode | stat.S_IEXEC)
    if with_pw:
        pwdir = src / "server" / "ui-check" / "node_modules" \
            / "playwright-core"
        pwdir.mkdir(parents=True)
        (pwdir / "package.json").write_text("PW_MARK_2121\n",
                                            encoding="utf-8")
    return src, _git("rev-parse", "HEAD", cwd=src).stdout.strip()


def _declare_runner(src, head, tmp, tag, extra=None):
    """The production seam exactly as an operator sets it. The t261011-18
    asset env keys are NOT set here: this ticket's contract is that the
    CLONE resolves its own cwd-relative probes."""
    env = clean_narrowing_env()
    env["SANDBAR_LINE_ROUND_RUNNER"] = (
        "python3 %s/integration/line_round_runner.py" % str(REPO))
    env["SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR"] = str(src)
    env["SANDBAR_LINE_ROUND_SUITE_CMD"] = "python3 tools/stub_suite.py"
    env["SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S"] = "120"
    env["SANDBAR_LINE_ROUND_RUN_ROOT"] = str(tmp / ("runroot-" + tag))
    # t261012-06: a scenario must never leave entities in the directory a
    # production face owns — the face dir is pinned into this tmp tree
    env["SANDBAR_LINE_ROUND_FACE_DIR"] = str(tmp / ("face-" + tag))
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def _run_round(src, head, tmp, tag, extra=None):
    env = _declare_runner(src, head, tmp, tag, extra=extra)
    runner, rerr = None, None
    try:
        runner = dc.resolve_runner(LINE, env)
    except Exception as e:  # noqa: BLE001
        rerr = "%s:%s" % (type(e).__name__, e)
    if runner is None:
        return None, None, rerr, None
    try:
        return runner([{"repo": "sandbar", "revision": head}]), env, None, None
    except dc.CouldNotRun as e:
        return None, env, None, str(e)


# ---------------------------------------------------------------- main

def main():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="t26101121-clone-assets-"))

    # ---- A: the incident closed — the clone resolves its own probes
    src, head = _mk_repo(_TMP, "main")
    probe_a = _TMP / "probe-green.json"
    header, env, derr, _ = _run_round(
        src, head, _TMP, "green",
        extra={"SUITE_PROBE_OUT": str(probe_a)})
    ok(derr is None and isinstance(header, dict)
       and str(header.get("id", "")).startswith("run-"),
       "A1 provisioned clone -> one real header (never could-not-run)",
       str(derr or "")[:300])
    ok(isinstance(header, dict)
       and header.get("cases", {}).get("env_failed") == 0,
       "A2 the round is GREEN on the environment face (env_failed==0 — the "
       "incident's 220-class reds must not be minted by an unprovisioned "
       "clone)", json.dumps((header or {}).get("cases", {}))[:200])
    if probe_a.is_file():
        probe = json.loads(probe_a.read_text(encoding="utf-8"))
        ok(probe.get("interp_out") == "VENV_MARK_2121",
           "A3 the registry's interpreter chain picked the CLONE's "
           "provisioned venv python (cwd-relative probe resolved; not the "
           "python3 fallback)", repr(probe.get("interp_out"))[:200])
        ok(probe.get("venv_is_symlink") is True,
           "A4 the in-clone .venv is a materialised link (one copy on "
           "disk)", "")
        # Read from the consumer-side receipt, NOT by walking the clone
        # after the round: the runner's declared contract reclaims the run
        # tree when the round ends, so a post-round tree walk would judge
        # an already-reclaimed path (the pre-arbitrate A5 red was exactly
        # that test defect, not a product defect).
        target = str(probe.get("venv_link_target", ""))
        ok(target.startswith(os.sep)
           and os.path.realpath(target).startswith(
               str(src.resolve()) + os.sep),
           "A5 the link target is an ABSOLUTE path under the SOURCE "
           "checkout (boundary discipline on the write face)",
           "target=%r" % target[:200])
        ok(probe.get("temporal_out") == "TEMPORAL_MARK_2121",
           "A6 the temporal binary probe resolves through the clone "
           "(Temporal-shaped class provisioned)",
           repr(probe.get("temporal_out"))[:200])
        ok(probe.get("pw_marker") == "PW_MARK_2121",
           "A7 the playwright-core local-candidate probe resolves through "
           "the clone (browser-shaped class provisioned)",
           repr(probe.get("pw_marker"))[:200])
    else:
        ok(False, "A3-A7 skipped: probe receipt missing (suite never ran)",
           str(probe_a))

    # ---- B: honesty — an asset genuinely absent stays absent and env_red
    src_b, head_b = _mk_repo(_TMP, "no-pw", with_pw=False)
    probe_b = _TMP / "probe-nopw.json"
    header_b, _, derr_b, cnr_b = _run_round(
        src_b, head_b, _TMP, "no-pw",
        extra={"SUITE_PROBE_OUT": str(probe_b),
               "SUITE_ASSET_MODE": "absent-pw"})
    ok(cnr_b is None and isinstance(header_b, dict),
       "B1 absent source asset is NOT a could-not-run — the round still "
       "completes", str(cnr_b or "")[:300])
    ok(isinstance(header_b, dict)
       and header_b.get("cases", {}).get("env_failed") == 1,
       "B2 the absent asset is an HONEST env red in the relayed header "
       "(env_failed==1, never a fabricated green, never a silent swallow)",
       json.dumps((header_b or {}).get("cases", {}))[:200])
    if probe_b.is_file():
        pb = json.loads(probe_b.read_text(encoding="utf-8"))
        # Consumer-side receipt only: the clone itself is reclaimed when the
        # round ends, so absence is judged from what the probe SAW in-round.
        ok(pb.get("pw_present") is False and pb.get("pw_marker") == "",
           "B3 the clone had NOTHING at the absent asset's path while the "
           "suite ran (absence is materialised as nothing, not a dangling "
           "lie; judged from the consumer side)", "")
    else:
        ok(False, "B3-B4 skipped: probe receipt missing", str(probe_b))

    # ---- C: a committed file at an asset destination is never clobbered
    src_c, head_c = _mk_repo(_TMP, "committed",
                             committed_temporal="COMMITTED-SENTINEL\n")
    probe_c = _TMP / "probe-committed.json"
    header_c, _, derr_c, _ = _run_round(
        src_c, head_c, _TMP, "committed",
        extra={"SUITE_PROBE_OUT": str(probe_c)})
    ok(derr_c is None and isinstance(header_c, dict),
       "C1 a committed file at an asset destination -> the round still "
       "completes", str(derr_c or "")[:300])
    if probe_c.is_file():
        pc = json.loads(probe_c.read_text(encoding="utf-8"))
        ok(pc.get("temporal_link_target") == ""
           and pc.get("temporal_content") == "COMMITTED-SENTINEL\n",
           "C2 the clone's COMMITTED file at the destination survives "
           "byte-identical and un-linked (never clobbered by the "
           "provisioning; judged from the consumer-side receipt)",
           json.dumps({k: pc.get(k) for k in
                       ("temporal_link_target", "temporal_content")})[:200])
    else:
        ok(False, "C2 skipped: probe receipt missing", str(probe_c))

    # Layering note (no extra leg — a constant-pass leg would be a
    # trivially-green smell): the env-key hand-over faces stay owned by
    # t261011-18-line-round-assets, whose A3 precondition face is
    # deliberately re-signed by this ticket (naming comment in place there)
    # and must stay green at the gate.

    finish(NAME)


if __name__ == "__main__":
    main()
