#!/usr/bin/env python3
"""t261029-30 / KI-373 L1 battery: an absent stage premise is a NAMED
environment failure, never a content red.

intent (user-perceivable): the roster can tell an UNVERIFIED case from a BROKEN
one. A case whose assertion needs a stage premise (a uid boundary, a container
stage, a network rig) exits 2 with `ENV_FAIL: <premise> missing (<what was
probed>)` when the machine does not provide that premise, and the SAME case runs
its original assertions unchanged - and can still fail - when the premise is
present. A case that always env-fails would be worse than the bug, so both
directions are proven here.

high-level steps (grey-box, zero real docker stage, zero Temporal, never touches
3099): A the probe truth table (ready / each named miss / unknown premise / a
probe that raises); B the whole-case gate exits 2 through the suite's env-fail
path with the named text; C the injection seam (`SANDBAR_STAGE_PREMISE_INJECT`)
answers either direction and says so loudly; D the uid-boundary face check truth
table (root face / writable target / unreadable uid / clean face); E-J the REAL
converted cases driven as subprocesses against a FATAL-FREE fake docker CLI on
PATH: premise missing at preflight => rc 2 named and no assertion judged; the
KI-373 shape (container face runs as uid 0) => rc 2 named, no content red;
premise present on a healthy rig => rc 0; premise present with a broken product
leg => rc 1 (the assertions bite); the network-table case's two premises each
miss by name; and the runner's own classifier puts the exit-2 case in the
env-failed column, never the failed one.

Injection discipline: the probe is injected (probes= / the env seam), never a
real docker stage. The fake docker CLI exists only to make the premise-present
runs reach the real assertions without a daemon.

Why the file sits under server/engine/tests (t261029-50): the quickmanual gate
runs its declared battery as `pytest server/engine/tests -q <node>`, so a battery
under integration/tests is never collected there - pytest takes the lane root as
rootdir and integration/conftest.py's `pytest_plugins` is then a non-top-level
declaration, which refuses before any case runs.

No copy literal is pasted here (t261004-36 retired the temporary data-id copy
marker, so an engine test may not carry the case's copy or an exemption for it):
the two lock-leg labels are RENDERED from the converted case's own source, and
the legs are named by their product conditions, never by a position in the
output. The assertions are therefore the same pins as before, read from the one
source of truth for that copy.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
INTEG = REPO / "integration"
sys.path.insert(0, str(INTEG))

import lib_env  # noqa: E402

NEGLOCK = INTEG / "t260913-04" / "sc_t26091304_sandbox_neglock.py"
NETTABLE = INTEG / "t260912-02" / "sc_stage_net_table_contract.py"
PY_INTERP = INTEG / "py_interp.sh"
INJ = lib_env.PREMISE_INJECT_ENV

#: The two premise-facing legs of the converted case, named by their own ASCII
#: call shape (the product condition), not by a line number or an output order.
POS_LEG = "C.check(inside_ok,"
NEG_LEG = "C.check(outside_absent(lane, main_repo),"


def case_label(script, leg_call):
    """Render one leg label from the converted case's OWN source.

    The converted case is the single source of truth for its copy, so this
    battery reads the label there instead of pasting it. A case that stops
    judging the leg, or stops rendering a round-tagged label, is refused by name
    here (a silent "" would turn the label assertions vacuous).
    """
    src = script.read_text(encoding="utf-8")
    start = src.find(leg_call)
    assert start != -1, (
        "the converted case no longer judges the leg %r - re-point this battery "
        "at the leg that took it over, do not delete the pin" % leg_call)
    tail = src[start:]
    end = tail.find("% round_tag")
    assert end != -1, (
        "the leg %r no longer renders a round-tagged label - re-point this "
        "battery instead of trusting a stale label" % leg_call)
    fragments = re.findall(r'"((?:[^"\\]|\\.)*)"', tail[:end])
    assert fragments, "no label literal found for the leg %r" % leg_call
    # the case formats its label with the round tag; the baseline round is the
    # one these battery legs drive (`one_round(..., "baseline", ...)`).
    return "".join(fragments).replace("%s", "baseline", 1)


POS_LABEL = case_label(NEGLOCK, POS_LEG)
NEG_LABEL = case_label(NEGLOCK, NEG_LEG)


# ======================================================================================
# helpers: a fake docker CLI (the premise-present face) and a case runner
# ======================================================================================
FAKE_DOCKER = r'''#!%(python)s
"""Fake docker CLI for the premise battery (test asset, never a real daemon).

Honours four switch env vars so one script serves every direction:
  FAKE_INFO_OK=0      `docker info` fails (no daemon)
  FAKE_NETWORK_OK=0   `docker network ls` fails (daemon but no rig)
  FAKE_UID=<n>        the uid the container face reports (`docker exec ... id -u`)
  FAKE_WRITE_INSIDE=0 the agent round writes no workspace file (broken product leg)
State (the round's workdir and the /tmp probe marker) lives in FAKE_STAGE_STATE.
"""
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get("FAKE_STAGE_STATE", "/tmp/fake-stage-state"))
STATE.mkdir(parents=True, exist_ok=True)
ARGS = sys.argv[1:]


def flag(name):
    return os.environ.get(name, "1") == "1"


def main():
    cmd = ARGS[0] if ARGS else ""
    if cmd == "info":
        if flag("FAKE_INFO_OK"):
            print("27.0.0")
            return 0
        sys.stderr.write(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
            "Is the docker daemon running?\n")
        return 1
    if cmd == "image":
        if flag("FAKE_INFO_OK"):
            print("sandbar-agent:test")
            return 0
        return 1
    if cmd == "network":
        return 0 if flag("FAKE_NETWORK_OK") else 1
    if cmd == "compose":
        print("Docker Compose version v2.29.0")
        return 0
    if cmd == "run":
        rest = ARGS[1:]
        for i, a in enumerate(rest[:-1]):
            if a == "-w":
                (STATE / "workdir").write_text(rest[i + 1], encoding="utf-8")
        return 0
    if cmd == "inspect":
        if any("State.Running" in a for a in ARGS[1:]):
            print("true|running")
            return 0
        return 1
    if cmd != "exec":
        return 0
    rest = ARGS[1:]
    i = 0
    while i < len(rest):
        if rest[i] in ("-e", "-u", "-w"):
            i += 2
            continue
        if rest[i].startswith("-"):
            i += 1
            continue
        break
    rest = rest[i + 1:]
    sub = rest[0] if rest else ""
    if sub == "id":
        print(os.environ.get("FAKE_UID", "501"))
        return 0
    if sub == "test":
        if len(rest) >= 3 and rest[1] == "-e" and rest[2] == "/tmp/sb_probe_in.txt":
            return 0 if (STATE / "tmp_probe").exists() else 1
        return 1
    if sub == "git":
        sys.stderr.write("fatal: not a git repository (or any of the parent "
                         "directories): .git\n")
        return 128
    if sub == "dsh":
        if flag("FAKE_WRITE_INSIDE") and (STATE / "workdir").exists():
            wd = Path((STATE / "workdir").read_text(encoding="utf-8").strip())
            (wd / "proof").mkdir(parents=True, exist_ok=True)
            (wd / "proof" / "inside.txt").write_text("in-ok", encoding="utf-8")
            (STATE / "tmp_probe").touch()
        return 0
    return 0


sys.exit(main())
'''


def fake_docker(tmp_path):
    """Install the fake docker CLI and return the env overrides for a case run."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "docker"
    shim.write_text(FAKE_DOCKER % {"python": sys.executable}, encoding="utf-8")
    shim.chmod(0o755)
    return {"PATH": "%s:%s" % (shim_dir, os.environ.get("PATH", "")),
            "FAKE_STAGE_STATE": str(tmp_path / "state")}


def run_case(script, env_extra, tmp_path, timeout=90):
    """Drive a REAL case script as a subprocess (its own exit code is the verdict)."""
    env = dict(os.environ)
    env.pop(INJ, None)
    for key in ("FAKE_INFO_OK", "FAKE_NETWORK_OK", "FAKE_UID", "FAKE_WRITE_INSIDE"):
        env.pop(key, None)
    env.update(fake_docker(tmp_path))
    env.update(env_extra)
    return subprocess.run(["sh", str(PY_INTERP), str(script)], capture_output=True,
                          text=True, timeout=timeout, env=env, cwd=str(REPO))


def out_of(proc):
    return (proc.stdout or "") + (proc.stderr or "")


def content_fails(text):
    """The case's own FAIL lines (`FAIL  <label>` / `  FAIL  <label>`) - an
    ENV_FAIL line is an environment failure and never counts here."""
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("FAIL")]


SUPPLY_READY = ",".join("%s=ready" % p for p in
                        (lib_env.PREM_DOCKER_DAEMON, lib_env.PREM_AGENT_IMAGE,
                         lib_env.PREM_MODEL_CREDENTIALS))


# ======================================================================================
# A. the probe truth table
# ======================================================================================
@pytest.mark.parametrize("premise", lib_env.PREMISE_NAMES)
def test_probe_ready_when_the_premise_is_present(premise):
    probes = {premise: lambda: (True, "observed-here")}
    assert lib_env.probe_stage_premise(premise, probes=probes) == lib_env.PREMISE_READY


@pytest.mark.parametrize("premise", lib_env.PREMISE_NAMES)
def test_each_named_miss_names_premise_probe_and_what_was_looked_for(premise):
    probes = {premise: lambda: (False, "observed-value")}
    miss = lib_env.probe_stage_premise(premise, probes=probes)
    assert isinstance(miss, lib_env.PremiseMiss)
    assert miss.premise == premise
    assert miss.probe == lib_env.PREMISE_PROBE[premise]
    assert miss.looked_for and "observed-value" == miss.observed
    # the whole-case text the roster reads: `<premise> missing (<what was probed>)`
    text = miss.reason()
    assert text.startswith("%s missing (probe %s: looked for " % (premise, miss.probe))
    assert "observed observed-value" in text


def test_unknown_premise_name_is_refused():
    """A case may not invent a premise: the vocabulary is closed."""
    with pytest.raises(ValueError) as exc:
        lib_env.probe_stage_premise("my-own-premise", probes={})
    assert "unknown stage premise" in str(exc.value)


def test_a_raising_probe_is_a_named_miss_never_a_pass():
    def boom():
        raise RuntimeError("probe exploded")

    miss = lib_env.probe_stage_premise(lib_env.PREM_DOCKER_DAEMON,
                                       probes={lib_env.PREM_DOCKER_DAEMON: boom})
    assert isinstance(miss, lib_env.PremiseMiss)
    assert "RuntimeError: probe exploded" in miss.observed


# ======================================================================================
# B. the whole-case gate keeps the exit-code contract
# ======================================================================================
def test_gate_exits_2_with_the_named_env_fail(capsys):
    probes = {lib_env.PREM_DOCKER_DAEMON: lambda: (False, "rc=1 no daemon")}
    with pytest.raises(SystemExit) as exc:
        lib_env.require_stage_premise([lib_env.PREM_DOCKER_DAEMON], probes=probes)
    assert exc.value.code == lib_env.EXIT_ENV_FAIL == 2
    printed = capsys.readouterr().out
    assert "ENV_FAIL: docker-daemon missing (probe docker-info: looked for " in printed
    assert "observed rc=1 no daemon" in printed


def test_gate_is_silent_and_returns_ready_when_every_premise_holds(capsys):
    ready = {p: (lambda: (True, "ok")) for p in lib_env.PREMISE_NAMES}
    assert lib_env.require_stage_premise(probes=ready) == lib_env.PREMISE_READY
    assert "ENV_FAIL" not in capsys.readouterr().out


def test_first_miss_wins_and_stops_the_walk():
    asked = []

    def miss_for(name):
        def probe():
            asked.append(name)
            return (False, "nope")
        return probe

    probes = {p: miss_for(p) for p in lib_env.PREMISE_NAMES}
    miss = lib_env.stage_premise_miss(
        [lib_env.PREM_DOCKER_DAEMON, lib_env.PREM_AGENT_IMAGE], probes=probes)
    assert miss.premise == lib_env.PREM_DOCKER_DAEMON
    assert asked == [lib_env.PREM_DOCKER_DAEMON]


# ======================================================================================
# C. the injection seam (both directions without a real stage)
# ======================================================================================
def test_injection_answers_ready_and_says_so(monkeypatch, capsys):
    monkeypatch.setenv(INJ, "%s=ready" % lib_env.PREM_DOCKER_DAEMON)

    def never_called():
        raise AssertionError("the real probe must not run when the seam covers it")

    result = lib_env.probe_stage_premise(
        lib_env.PREM_DOCKER_DAEMON, probes={lib_env.PREM_DOCKER_DAEMON: never_called})
    assert result == lib_env.PREMISE_READY
    printed = capsys.readouterr().out
    assert "PREMISE_INJECT: docker-daemon -> ready" in printed
    assert "the real probe did NOT run" in printed


def test_injection_answers_a_named_miss_with_the_given_observation(monkeypatch, capsys):
    monkeypatch.setenv(INJ, "stage-uid-boundary=miss:stage uid=0")
    miss = lib_env.probe_stage_premise(lib_env.PREM_STAGE_UID_BOUNDARY, probes={})
    assert isinstance(miss, lib_env.PremiseMiss)
    assert miss.premise == "stage-uid-boundary"
    assert miss.observed == "stage uid=0"
    assert miss.probe.endswith("@injected")
    assert "PREMISE_INJECT: stage-uid-boundary -> miss" in capsys.readouterr().out


def test_injection_does_not_cover_premises_it_does_not_name(monkeypatch):
    monkeypatch.setenv(INJ, "docker-daemon=ready")
    miss = lib_env.probe_stage_premise(
        lib_env.PREM_AGENT_IMAGE,
        probes={lib_env.PREM_AGENT_IMAGE: lambda: (False, "no image")})
    assert isinstance(miss, lib_env.PremiseMiss)


def test_malformed_injection_parts_are_ignored():
    assert lib_env.premise_injections({"SANDBAR_STAGE_PREMISE_INJECT": " ,junk, = "}) == {}


# ======================================================================================
# D. the uid-boundary face check (the KI-373 premise)
# ======================================================================================
def fake_face(uid_out, writable_rc):
    def run(cmd):
        if cmd[:2] == ["id", "-u"]:
            return (0, uid_out, "") if uid_out is not None else (1, "", "exec failed")
        return writable_rc, "", ""
    return run


@pytest.mark.parametrize("uid_out,writable_rc,want_ok", [
    ("501\n", 1, True),      # non-root face, /usr/local refused: the premise holds
    ("0\n", 1, False),       # root face: the OS refuses nothing (KI-373, measured)
    ("501\n", 0, False),     # writable target: the OS refuses nothing
    (None, 1, False),        # uid unreadable: fail closed, named
    ("501\n", 7, False),     # writability unjudgeable: fail closed, named
])
def test_uid_boundary_face_truth_table(uid_out, writable_rc, want_ok):
    ok, observed = lib_env.uid_boundary_check(fake_face(uid_out, writable_rc))
    assert ok is want_ok
    assert observed


def test_uid_boundary_miss_says_why_on_a_root_face():
    ok, observed = lib_env.uid_boundary_check(fake_face("0\n", 1))
    assert not ok
    assert "uid 0" in observed


# ======================================================================================
# E-J. the REAL converted cases, both directions (fake docker CLI, no daemon)
# ======================================================================================
def test_neglock_case_premise_missing_exits_2_and_judges_no_assertion(tmp_path):
    """Direction 1: the preflight premise is absent => exit 2 with the named text,
    and NOT ONE assertion was judged (a content red is impossible)."""
    proc = run_case(NEGLOCK, {"FAKE_INFO_OK": "0"}, tmp_path)
    text = out_of(proc)
    assert proc.returncode == 2, text
    assert "ENV_FAIL: docker-daemon missing (probe docker-info: looked for " in text
    assert content_fails(text) == []
    assert "SUMMARY pass=0 fail=0 env_fail=1" in text


def test_neglock_case_uid_premise_missing_exits_2_named_never_a_content_red(tmp_path):
    """Direction 2 (KI-373 exactly): the stage exists and the round runs, but the
    container face runs as uid 0. The cross-boundary assertion cannot hold, so the
    case reports the premise by name and exits 2 - the negative-lock leg is NOT
    judged and there is no content red at all."""
    proc = run_case(NEGLOCK, {"FAKE_UID": "0", INJ: SUPPLY_READY}, tmp_path)
    text = out_of(proc)
    assert proc.returncode == 2, text
    assert ("ENV_FAIL: stage-uid-boundary missing (probe uid-boundary@docker-exec: "
            "looked for ") in text
    assert "stage uid=0" in text
    assert NEG_LABEL not in text          # the premise-dependent leg was not judged
    assert "  FAIL  " not in text and "fail=0" in text


def test_neglock_case_premise_present_runs_every_original_assertion(tmp_path):
    """Direction 3: the premise IS present (healthy rig) => the original assertions
    run and all pass (rc 0). A case that always env-failed would fail this leg."""
    proc = run_case(NEGLOCK, {INJ: SUPPLY_READY}, tmp_path)
    text = out_of(proc)
    assert proc.returncode == 0, text
    assert "ok    " + NEG_LABEL in text   # the negative lock ran and held
    assert "ok    " + POS_LABEL in text   # the positive lock ran and held
    assert "SUMMARY pass=5 fail=0 env_fail=0" in text


def test_neglock_case_premise_present_assertions_still_bite(tmp_path):
    """Direction 4: same premises, but the product's positive lock is broken (the
    agent round writes no workspace file) => the SAME assertions fail, rc 1. The
    conversion must not have turned a content red into an environment red."""
    proc = run_case(NEGLOCK, {INJ: SUPPLY_READY, "FAKE_WRITE_INSIDE": "0"}, tmp_path)
    text = out_of(proc)
    assert proc.returncode == 1, text
    assert "FAIL  " + POS_LABEL in text   # the same leg, same label, now red
    assert "ENV_FAIL: stage-uid-boundary" not in text
    assert "env_fail=0" in text


def test_net_table_case_names_the_daemon_premise(tmp_path):
    proc = run_case(NETTABLE, {"FAKE_INFO_OK": "0"}, tmp_path)
    text = out_of(proc)
    assert proc.returncode == 2, text
    assert "ENV_FAIL: docker-daemon missing (probe docker-info: looked for " in text
    assert content_fails(text) == []


def test_net_table_case_names_the_rig_premise(tmp_path):
    """The second premise of the same case: a daemon that answers `info` but no
    usable network/compose rig. Distinct name, distinct probe - never one bucket."""
    proc = run_case(NETTABLE, {"FAKE_INFO_OK": "1", "FAKE_NETWORK_OK": "0"}, tmp_path)
    text = out_of(proc)
    assert proc.returncode == 2, text
    assert "ENV_FAIL: stage-network-rig missing (probe docker-network-rig: looked for " in text
    assert "docker network ls` failed" in text
    assert content_fails(text) == []


def test_the_converted_case_reads_as_env_failed_in_the_run_verdict(tmp_path):
    """Requirement 4: the runner classifies the converted case's exit 2 in the
    env-failed column, never in the failed one (the real classifier, not a copy)."""
    proc = run_case(NEGLOCK, {"FAKE_INFO_OK": "0"}, tmp_path)
    assert proc.returncode == 2
    spec = importlib.util.spec_from_file_location(
        "rs_t261029_30_under_test", INTEG / "run_scenarios.py")
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    row = json.loads(rs._spec_from_output(
        "t260913-04-sandbox-neglock", "engine", out_of(proc),
        proc.returncode, 1.0, 0.0))
    assert row["status"] == "not-checked"      # env/not-verified, never "fail"
    assert row["cause"] == "external"
    assert "docker-daemon missing" in row["evidence"]

    import lib_round_face
    counts = lib_round_face.normalize_summary_counts({"ran": 1, "not_checked": 1})
    assert counts == {"ran": 1, "env_fail": 1}


# ======================================================================================
# K. no assertion was weakened away (a source lock on the measured case)
# ======================================================================================
def test_the_measured_case_still_carries_its_original_assertions():
    """The case keeps both lock legs, the premise gate, and the gate's ORDER: the
    premise is decided BEFORE the negative lock is judged, so a missing uid
    boundary can never be judged as a content red. Pins are ASCII (the call
    shapes and the ordering), never a pasted copy literal."""
    src = NEGLOCK.read_text(encoding="utf-8")
    assert POS_LEG in src
    assert NEG_LEG in src
    assert "C.env(uid_miss.reason())" in src
    assert src.index("uid_miss = uid_boundary_miss()") < src.index(NEG_LEG)
    # and both labels really resolve out of that source (a stale pin would be empty)
    assert POS_LABEL.startswith("[baseline] ") and len(POS_LABEL) > len("[baseline] ")
    assert NEG_LABEL.startswith("[baseline] ") and len(NEG_LABEL) > len("[baseline] ")
    assert POS_LABEL != NEG_LABEL
