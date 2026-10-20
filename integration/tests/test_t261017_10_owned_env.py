#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261017-10 L1 unit battery: a fixture owns the env it tests (developer stage).

Incident (host order 261012, measured): the line round pins
``SANDBAR_LEDGER_REUSE=0`` and exports ``SANDBAR_INTEG_LEDGER_SOURCE=lane:line-round``;
the reuse pin is a BARE name outside every prefix family in
``lib_env.clean_narrowing_env()``'s scrub table, so it leaked into the spawned
real runner inside t260930-01-ledger-reuse-round and t261011-... drivers, and
flipped the exact behaviour those cases prove. Fix under test here:

- the kill-switch name joins ``NARROWING_ENV_NAMES`` (scrub-then-inject, both the
  py and the mjs twin table);
- the py/mjs vocab lock still reports empty for the real pair;
- a fixture declares the contradiction BY NAME via ``owned_env_note``.

Pure functions over injected env dicts — offline, zero subprocess, zero ports.
"""
import io
import os
import sys
from pathlib import Path

INTEG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INTEG))
import lib_env  # noqa: E402


CLEAN = {"PATH": "/usr/bin:/bin", "HOME": "/tmp"}


# ---------------------------------------------------------------- A scrub table

def test_a_reuse_kill_switch_is_scrubbed():
    """The round's pin must not reach the fixture's spawned runner env."""
    base = dict(CLEAN, SANDBAR_LEDGER_REUSE="0")
    env = lib_env.clean_narrowing_env(base=base)
    assert "SANDBAR_LEDGER_REUSE" not in env, env.get("SANDBAR_LEDGER_REUSE")


def test_a_explicit_declaration_survives_the_scrub():
    """Scrub-then-inject: the kill-switch leg (extra pin) keeps working."""
    base = dict(CLEAN, SANDBAR_LEDGER_REUSE="0")
    env = lib_env.clean_narrowing_env({"SANDBAR_LEDGER_REUSE": "0"}, base=base)
    assert env["SANDBAR_LEDGER_REUSE"] == "0"


def test_a_ledger_source_still_scrubbed_and_declared_value_kept():
    """The exported lane:line-round source stays prefix-scrubbed; a case-declared
    source survives (t261013-04 contract)."""
    base = dict(CLEAN, SANDBAR_INTEG_LEDGER_SOURCE="lane:line-round")
    env = lib_env.clean_narrowing_env(
        {"SANDBAR_INTEG_LEDGER_SOURCE": "lane:t261013-04"}, base=base)
    assert env["SANDBAR_INTEG_LEDGER_SOURCE"] == "lane:t261013-04"
    bare = lib_env.clean_narrowing_env(base=base)
    assert "SANDBAR_INTEG_LEDGER_SOURCE" not in bare


def test_a_no_narrowing_env_strips_the_pin_in_process():
    """The in-process context manager strips the same bare name (same table)."""
    saved = os.environ.pop("SANDBAR_LEDGER_REUSE", None)
    try:
        os.environ["SANDBAR_LEDGER_REUSE"] = "0"
        with lib_env.no_narrowing_env():
            assert "SANDBAR_LEDGER_REUSE" not in os.environ
        assert os.environ.get("SANDBAR_LEDGER_REUSE") == "0"
    finally:
        if saved is None:
            os.environ.pop("SANDBAR_LEDGER_REUSE", None)
        else:
            os.environ["SANDBAR_LEDGER_REUSE"] = saved


def test_a_shared_truth_carries_the_new_name():
    """narrow_env_names() is the single truth guards/docs read — it must list it."""
    prefixes, names = lib_env.narrow_env_names()
    assert "SANDBAR_LEDGER_REUSE" in names
    assert not any("SANDBAR_LEDGER_REUSE".startswith(p) for p in prefixes)


# ---------------------------------------------------------------- B vocab lock

def test_b_py_mjs_twin_tables_stay_locked():
    """After adding the entry on both sides the lock report must be empty."""
    py_src = (INTEG / "lib_env.py").read_text(encoding="utf-8")
    mjs_src = (INTEG / "lib_env.mjs").read_text(encoding="utf-8")
    rep = lib_env.narrowing_lock_report(py_src, mjs_src)
    assert rep == [], rep


# ---------------------------------------------------------------- C owned note

def test_c_contradicting_pins_named_by_name():
    env = dict(CLEAN, SANDBAR_LEDGER_REUSE="0",
               SANDBAR_INTEG_LEDGER_SOURCE="lane:line-round")
    buf = io.StringIO()
    line = lib_env.owned_env_note(
        ("SANDBAR_LEDGER_REUSE", "SANDBAR_INTEG_LEDGER_SOURCE"),
        env=env, out=buf)
    assert line == buf.getvalue().strip()
    assert lib_env.OWNED_ENV_NOTE_PREFIX in line
    assert "SANDBAR_LEDGER_REUSE=0" in line
    assert "SANDBAR_INTEG_LEDGER_SOURCE=lane:line-round" in line


def test_c_clean_env_is_silent():
    buf = io.StringIO()
    line = lib_env.owned_env_note(("SANDBAR_LEDGER_REUSE",), env=dict(CLEAN), out=buf)
    assert line is None and buf.getvalue() == ""


def test_c_names_outside_the_asked_set_are_not_claimed():
    """Only the asked names are claimed — the note stays scoped, not a dump."""
    env = dict(CLEAN, SANDBAR_POOL_CONC="3")
    line = lib_env.owned_env_note(("SANDBAR_LEDGER_REUSE",), env=env, out=io.StringIO())
    assert line is None


def test_c_malformed_values_are_named_verbatim():
    """Empty / whitespace / odd-byte values are named as-is; no crash, no lying."""
    env = dict(CLEAN, SANDBAR_LEDGER_REUSE="", SANDBAR_INTEG_LEDGER_SOURCE="  ")
    buf = io.StringIO()
    line = lib_env.owned_env_note(
        ("SANDBAR_LEDGER_REUSE", "SANDBAR_INTEG_LEDGER_SOURCE"),
        env=env, out=buf)
    assert line is not None
    assert "SANDBAR_LEDGER_REUSE=" in line and "SANDBAR_INTEG_LEDGER_SOURCE=  " in line
