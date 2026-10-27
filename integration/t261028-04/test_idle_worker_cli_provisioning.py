#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 battery: the idle-worker faces never download a Temporal CLI (t261028-07).

KI-380 (the incident this pins): both faces of scenario t261019-42 called
temporalio ``WorkflowEnvironment.start_local()`` with no binary path, so
temporalio fetched the CLI from https://temporal.download/cli/default. A slow or
refused download raised ``RuntimeError("Failed starting Temporal dev server:
error sending request for url (...)")``, which the runner booked as an ordinary
assertion red — a network condition reddened a line round and froze
develop-buffer.

What this battery owns (spec points 1, 2 and 4):
  A resolution order — ``$SANDBAR_TEMPORAL_BIN`` wins over the bundled copy; an
    explicit pointer naming a nonexistent path is a NAMED miss and is never
    silently bypassed;
  B the bundled copy — with the env key unset the resolution goes to
    ``server/engine/bin/temporal`` through the suite's one asset resolver
    (``integration/bench.py resolve_temporal_bin``), and a missing bundled copy
    is a NAMED miss naming the env key and the path;
  C the miss is an ENVIRONMENT failure, not a content red — no network is
    attempted while resolving, and each real face turns the miss into
    ``ENV_FAIL: ...`` with exit code 2 naming the key and the path;
  D the good path — each face hands back the EXISTING binary the pointer names
    (that value is what start_local receives as dev_server_existing_path; the
    source lock over the call sites lives next to the faces, in
    ``integration/t261019-42/test_faces_start_local_with_path.py``).

The scenario itself is not run (it needs a dev server); this battery drives the
provisioning seam each face calls before start_local, plus the resolution logic.
"""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FACES_DIR = HERE.parent / "t261019-42"
sys.path.insert(0, str(FACES_DIR))

import lib_temporal_cli as cli  # noqa: E402

FACE_FILES = (
    FACES_DIR / "sc_t261019_42_idle_worker_fast_turnover.py",
    FACES_DIR / "face_b_busy_worker_driver.py",
)

#: The miss that must never become a content red.
MISSING_POINTER = "/nonexistent/t261028-07/temporal"


def _bundled_sentinel(tmp_path):
    """An existing file standing in for the repo copy in the unit faces."""
    p = tmp_path / "bin" / "temporal"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return p


def _boom(*_a, **_kw):
    raise AssertionError("the bundled lookup must NOT run on this path")


# ---------------- A: resolution order, explicit pointer wins ----------------


def test_env_pointer_wins_over_the_bundled_copy(tmp_path):
    pointed = tmp_path / "custom-temporal"
    pointed.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    got = cli.resolve_temporal_cli(
        env={cli.TEMPORAL_BIN_ENV: str(pointed)}, bundled_resolver=_boom)
    assert got == str(pointed)
    assert Path(got).is_file()


def test_missing_pointer_is_a_named_miss_not_a_silent_fallback():
    with pytest.raises(cli.TemporalCliMissing) as caught:
        cli.resolve_temporal_cli(
            env={cli.TEMPORAL_BIN_ENV: MISSING_POINTER}, bundled_resolver=_boom)
    exc = caught.value
    reason = str(exc)
    # which check failed: named, with both the key and the path it honoured
    assert cli.TEMPORAL_BIN_ENV in reason
    assert MISSING_POINTER in reason
    assert "does not exist" in reason
    # the bundled copy is reported as the second path probed, and was NOT used
    assert str(cli.BUNDLED_CLI) in reason
    assert exc.tried == (MISSING_POINTER, str(cli.BUNDLED_CLI))
    assert exc.env_key == cli.TEMPORAL_BIN_ENV


def test_pointer_to_a_directory_is_a_named_miss(tmp_path):
    with pytest.raises(cli.TemporalCliMissing) as caught:
        cli.resolve_temporal_cli(
            env={cli.TEMPORAL_BIN_ENV: str(tmp_path)}, bundled_resolver=_boom)
    assert "is not a file" in str(caught.value)
    assert str(tmp_path) in str(caught.value)


# --------------- B: the bundled copy when the env key is unset ---------------


def test_bundled_copy_is_used_when_the_env_key_is_unset(tmp_path):
    bundled = _bundled_sentinel(tmp_path)
    got = cli.resolve_temporal_cli(env={}, bundled_resolver=lambda: str(bundled))
    assert got == str(bundled)
    assert Path(got).is_file()


def test_bundled_lookup_failure_is_a_named_miss():
    def broken():
        raise RuntimeError("lane copy missing and no main-tree fallback")

    with pytest.raises(cli.TemporalCliMissing) as caught:
        cli.resolve_temporal_cli(env={}, bundled_resolver=broken)
    reason = str(caught.value)
    assert cli.TEMPORAL_BIN_ENV in reason
    assert str(cli.BUNDLED_CLI) in reason
    assert "bundled lookup failed" in reason
    assert "RuntimeError" in reason          # which failure, not just "missing"


def test_bundled_lookup_returning_a_nonexistent_path_is_a_named_miss(tmp_path):
    ghost = tmp_path / "nope" / "temporal"
    with pytest.raises(cli.TemporalCliMissing) as caught:
        cli.resolve_temporal_cli(env={}, bundled_resolver=lambda: str(ghost))
    reason = str(caught.value)
    assert str(ghost) in reason and "not a file" in reason


def test_default_resolver_is_the_suite_asset_resolver(monkeypatch, tmp_path):
    """One resolution point: lib_temporal_cli delegates to integration/bench.py."""
    sys.path.insert(0, str(cli.INTEG_DIR))
    import bench

    bundled = _bundled_sentinel(tmp_path)
    monkeypatch.setattr(bench, "resolve_temporal_bin", lambda: bundled)
    assert cli.resolve_temporal_cli(env={}) == str(bundled)


def test_real_checkout_resolves_the_repo_copy_or_names_the_miss():
    """With SANDBAR_TEMPORAL_BIN unset this checkout picks its repo copy.

    The binary is gitignored and provisioned per checkout, so both outcomes are
    lawful here and both are pinned: a resolved file that IS a repo copy
    (server/engine/bin/temporal of the lane or of the main tree), or a NAMED
    miss. Never a silent assumption.
    """
    code = (
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "import lib_temporal_cli as cli\n"
        "try:\n"
        "    print(json.dumps({'resolved': cli.resolve_temporal_cli(env={})}))\n"
        "except cli.TemporalCliMissing as exc:\n"
        "    print(json.dumps({'miss': str(exc)}))\n" % str(FACES_DIR))
    env = {k: v for k, v in os.environ.items() if k != cli.TEMPORAL_BIN_ENV}
    proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(HERE),
                          env=env, capture_output=True, text=True,
                          # SANCTIONED-WAIT: hung-interpreter kill ceiling; resolution answers in ms
                          timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    if "resolved" in out:
        path = Path(out["resolved"])
        assert path.is_file()
        assert path.parts[-4:] == ("server", "engine", "bin", "temporal"), out
    else:
        assert cli.TEMPORAL_BIN_ENV in out["miss"], out
        assert "server/engine/bin/temporal" in out["miss"], out


# ------------- C: a miss attempts no network (the KI-380 shape) -------------


@pytest.mark.parametrize("env", [
    {cli.TEMPORAL_BIN_ENV: MISSING_POINTER},          # broken pointer
    {},                                               # bundled lookup fails
])
def test_the_miss_path_touches_no_network(monkeypatch, env):
    def forbidden(*_a, **_kw):
        raise AssertionError("no network may be attempted while provisioning")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)

    def broken():
        raise RuntimeError("bundled copy absent")

    with pytest.raises(cli.TemporalCliMissing):
        cli.resolve_temporal_cli(env=env, bundled_resolver=broken)


# --------- D: the real faces classify the miss as ENV_FAIL exit 2 ----------
# Driven in a SUBPROCESS so the faces' own env_fail() (sys.exit(2)) is judged as
# the runner would see it, with an audit hook that makes any socket attempt
# visible (the hook fires in place of the KI-380 download).

_SUBPROCESS_DRIVER = r'''
import importlib.util
import sys


def _audit(event, args):
    if event in ("socket.connect", "socket.getaddrinfo",
                 "socket.gethostbyname", "urllib.Request"):
        print("NETWORK_ATTEMPTED: %s" % event, flush=True)
        raise RuntimeError("network attempted: %s" % event)


sys.addaudithook(_audit)

spec = importlib.util.spec_from_file_location("face_under_test", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
cli = mod.provision_dev_server_cli()
print("PROVISIONED=%s" % cli, flush=True)
'''

_FACE_IDS = [p.name for p in FACE_FILES]


def _run_face(path, env):
    return subprocess.run([sys.executable, "-B", "-c", _SUBPROCESS_DRIVER, str(path)],
                          cwd=str(HERE), env=env, capture_output=True, text=True,
                          # SANCTIONED-WAIT: hung-interpreter kill ceiling; provisioning answers in ms
                          timeout=120)


@pytest.mark.parametrize("face", FACE_FILES, ids=_FACE_IDS)
def test_face_miss_is_env_fail_exit_2_naming_key_and_path(face):
    env = dict(os.environ)
    env[cli.TEMPORAL_BIN_ENV] = MISSING_POINTER
    proc = _run_face(face, env)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2, out
    assert "ENV_FAIL:" in proc.stdout, out
    assert cli.TEMPORAL_BIN_ENV in proc.stdout, out
    assert MISSING_POINTER in proc.stdout, out       # the path it honoured
    assert str(cli.BUNDLED_CLI) in proc.stdout, out  # the path it also probed
    assert "NETWORK_ATTEMPTED" not in out, out
    assert "PROVISIONED=" not in out, out
    # never an assertion red: no PASS/FAIL bookkeeping line was reached
    assert "PASS=" not in out, out


@pytest.mark.parametrize("face", FACE_FILES, ids=_FACE_IDS)
def test_face_hands_back_the_existing_binary_the_pointer_names(face, tmp_path):
    real = tmp_path / "temporal"
    real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    env = dict(os.environ)
    env[cli.TEMPORAL_BIN_ENV] = str(real)
    proc = _run_face(face, env)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert ("PROVISIONED=%s" % real) in proc.stdout, out
    assert "NETWORK_ATTEMPTED" not in out, out
