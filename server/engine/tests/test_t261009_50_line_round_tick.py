#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-50 — the tick actually runs the line round: the scheduled call
site, the event trigger, the scheduled backstop and the idle case.

White-box over server/engine/develop_certify.py's tick face
(``line_round_tick`` + ``resolve_runner`` + ``backstop_ms_from_env``), on
injected seams. The public face is what is pinned — the tick calls
``should_certify`` and ``run_line_round``, it never re-implements either
(review R2). Zero docker, zero Temporal, never touches 3099; the suite is
never executed here (the runner is a stub; the real runner is t261009-46's).
"""

import json
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE_A = "alpha"
LINE_B = "beta"


def ledger(tmp_path):
    return tmp_path / "ledger" / "delivery.jsonl"


def guard_path(tmp_path):
    return tmp_path / "ledger" / "tick-anchor"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def landing(repo, rev, ticket="t1", at=1, line=LINE_A):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": line, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def green_header(ran=10):
    return {"id": dc.mint_id("run"), "cases": {"ran": ran, "failed": 0,
                                               "env_failed": 0}}


def runner_ok(calls):
    def _run(candidate):
        calls.append(candidate)
        return green_header()
    return _run


def resolver(calls, mapping=None):
    """resolve_runner_fn stand-in: records (line, env); None ⇒ runner_missing."""
    def _resolve(line, env):
        calls.append((line, env))
        if mapping is None:
            return runner_ok([])
        return mapping.get(line)
    return _resolve


def tick(tmp_path, lines=(LINE_A,), rows=None, mapping=None, resolver_calls=None,
         backstop_ms=1000, now_ms=10_000, env=None, load_lines=None):
    p = ledger(tmp_path)
    if rows:
        dc.append_rows(rows, p)
    return dc.line_round_tick(
        "proj",
        load_lines=load_lines or (lambda key: {l: object() for l in lines}),
        read_rows=reader(p),
        append_rows=writer(p),
        resolve_runner_fn=resolver(resolver_calls or [], mapping),
        guard_path=str(guard_path(tmp_path)),
        now_ms=now_ms,
        backstop_ms=backstop_ms,
        env=env or {})


# ---- the two trigger shapes + the idle case --------------------------------

def test_event_trigger_rounds_and_records_change(tmp_path):
    calls = []
    out = tick(tmp_path, rows=[landing("r", "a1", at=1)],
               mapping={LINE_A: runner_ok(calls)})
    e = out["lines"][0]
    assert e["trigger"] == "change"          # EVENT shape, on the record
    assert e["reason"] == "range_non_empty"
    assert e["rounds"][0]["state"] in ("certified", "red")


def test_backstop_trigger_never_certified(tmp_path):
    out = tick(tmp_path, rows=[], mapping={LINE_A: runner_ok([])})
    e = out["lines"][0]
    assert e["trigger"] == "backstop"        # SCHEDULED BACKSTOP shape
    assert e["reason"] == "never_certified"


def test_backstop_trigger_elapsed(tmp_path):
    # certified long ago, nothing since → the backstop asks anyway
    cert = {"kind": dc.KIND_CERT, "id": "cert-x", "line": LINE_A,
            "repos": [{"repo": "r", "revision": "a0"}], "run": "run-x",
            "booked_red": "v", "judged_by": "t", "at": 1, "seq": 1}
    out = tick(tmp_path, rows=[cert], now_ms=dc.LINE_BACKSTOP_MS_DEFAULT + 2,
               backstop_ms=dc.LINE_BACKSTOP_MS_DEFAULT,
               mapping={LINE_A: runner_ok([])})
    e = out["lines"][0]
    assert e["trigger"] == "backstop"
    assert e["reason"] == "backstop_elapsed"


def test_idle_writes_nothing(tmp_path):
    p = ledger(tmp_path)
    cert = {"kind": dc.KIND_CERT, "id": "cert-x", "line": LINE_A,
            "repos": [{"repo": "r", "revision": "a0"}], "run": "run-x",
            "booked_red": "v", "judged_by": "t", "at": 1, "seq": 1}
    dc.append_rows([cert], p)
    before = p.read_text(encoding="utf-8")
    out = tick(tmp_path, now_ms=5_000, backstop_ms=1_000_000,
               mapping={LINE_A: runner_ok([])})
    e = out["lines"][0]
    assert e["state"] == "idle"
    assert e["reason"] == "backstop_not_elapsed"
    assert p.read_text(encoding="utf-8") == before  # nothing appended


def test_idle_never_calls_runner_or_round(tmp_path):
    calls = []
    out = tick(tmp_path, rows=[], resolver_calls=calls, now_ms=5_000,
               backstop_ms=1_000_000, mapping={LINE_A: runner_ok([])})
    assert out["lines"][0]["state"] == "idle"


# ---- the tick does not queue up rounds --------------------------------------

def test_guard_held_joins_and_leaves_records_alone(tmp_path):
    p = ledger(tmp_path)
    gp = guard_path(tmp_path)
    gp.parent.mkdir(parents=True, exist_ok=True)
    held = dc.guard_acquire(gp, "someone-else")
    assert held is not None
    dc.append_rows([landing("r", "a1", at=1)], p)
    before = p.read_text(encoding="utf-8")
    guard_before = (gp.parent / dc.GUARD_NAME).read_text(encoding="utf-8")
    calls = []
    out = tick(tmp_path, mapping={LINE_A: runner_ok(calls)})
    e = out["lines"][0]
    assert e["state"] == "joined"
    assert calls == []                       # no second round started
    assert (gp.parent / dc.GUARD_NAME).read_text(encoding="utf-8") == guard_before
    assert p.read_text(encoding="utf-8") == before  # zero rows written


# ---- failures are named, never swallowed ------------------------------------

def test_runner_missing_is_named_not_silent(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("r", "a1", at=1)], p)
    out = tick(tmp_path, rows=None, mapping={LINE_A: None})
    assert out["lines"][0]["state"] == "runner_missing"
    # operator surface only: no delivery-ledger row for the missing runner
    rows, _ = dc.read_rows(p)
    assert [r["kind"] for r in rows] == ["landing"]


def test_runner_missing_summary_names_the_tick(tmp_path):
    out = tick(tmp_path, rows=[], mapping={LINE_A: None})
    assert "not-runnable" in out["summary"]
    assert "alpha" in out["summary"]


def test_broken_line_does_not_kill_the_tick(tmp_path):
    calls = []

    def boom(candidate):
        raise dc.CertifyError("guard_held_by_stale_holder")

    out = tick(tmp_path, lines=(LINE_B, LINE_A),
               rows=[landing("r", "a1"), landing("r", "b1", at=2, line=LINE_B)],
               mapping={LINE_A: runner_ok(calls), LINE_B: boom})
    states = {e["line"]: e for e in out["lines"]}
    assert states[LINE_B]["state"] == "error"
    assert "guard_held_by_stale_holder" in states[LINE_B]["error"]
    assert states[LINE_A]["trigger"] == "change"   # the other line still ran
    assert len(calls) == 1


def test_missing_declaration_is_a_named_entry(tmp_path):
    def missing(key):
        raise FileNotFoundError("lines.json")
    out = tick(tmp_path, load_lines=missing)
    assert out["lines"][0]["error"].startswith("line_declaration_unreadable")
    assert "declaration unreadable" in out["summary"]


def test_corrupt_ledger_is_named_and_blocks_nothing_else(tmp_path):
    p = ledger(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"kind": "landing"\n', encoding="utf-8")  # torn line
    out = tick(tmp_path, rows=None, mapping={LINE_A: runner_ok([])})
    assert out["lines"][0]["error"].startswith("ledger_has_malformed_lines")


def test_corrupt_guard_is_a_named_error(tmp_path):
    gp = guard_path(tmp_path)
    gp.parent.mkdir(parents=True, exist_ok=True)
    (gp.parent / dc.GUARD_NAME).write_text("{not json", encoding="utf-8")
    calls = []
    out = tick(tmp_path, rows=[], mapping={LINE_A: runner_ok(calls)})
    assert out["lines"][0]["state"] == "error"
    assert "guard_unreadable" in out["lines"][0]["error"]
    assert calls == []


def test_lines_asked_once_each_per_tick(tmp_path):
    calls = []
    tick(tmp_path, lines=(LINE_B, LINE_A),
         rows=[landing("r", "a1"), landing("r", "b1", at=2, line=LINE_B)],
         mapping={LINE_A: runner_ok(calls), LINE_B: runner_ok(calls)})
    assert len(calls) == 2  # one ask per declared line, never two for one


# ---- the production runner seam ---------------------------------------------

def test_resolve_runner_none_when_undeclared():
    assert dc.resolve_runner(LINE_A, env={}) is None


def test_resolve_runner_rejects_bad_timeout_by_name():
    with pytest.raises(dc.CertifyError, match="runner_timeout_not_int"):
        dc.resolve_runner(LINE_A, env={dc.RUNNER_CMD_ENV: "true",
                                       dc.RUNNER_TIMEOUT_ENV: "soon"})


def test_runner_success_shape(tmp_path):
    script = ("printf '%s' '{\"id\":\"%s\",\"cases\":{\"ran\":3,"
              "\"failed\":0,\"env_failed\":0}}' \"$LINE_ROUND_MARK\"")
    env = {dc.RUNNER_CMD_ENV:
           'printf \'{"id":"run-x","cases":{"ran":3,"failed":0,'
           '"env_failed":0}}\'', "LINE_ROUND_MARK": "ignored"}
    runner = dc.resolve_runner(LINE_A, env=env)
    header = runner([{"repo": "r", "revision": "a1"}])
    assert header["id"] == "run-x"
    assert header["cases"]["ran"] == 3


def test_runner_carries_candidate_set_in_env(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, os, sys\n"
        "sys.stdout.write(json.dumps("
        "{'echo': json.loads(os.environ['SANDBAR_LINE_ROUND_CANDIDATES'])}))\n",
        encoding="utf-8")
    runner = dc.resolve_runner(
        LINE_A, env={dc.RUNNER_CMD_ENV: "%s %s" % (sys.executable, probe)})
    header = runner([{"repo": "r", "revision": "a1"}])
    assert header == {"echo": [{"repo": "r", "revision": "a1"}]}


@pytest.mark.parametrize("stdout,why", [
    ("", "runner_header_malformed"),
    ("not json", "runner_header_malformed"),
    ('"[1,2]"', "runner_header_not_object"),
])
def test_runner_malformed_headers_fail_by_name(tmp_path, stdout, why):
    runner = dc.resolve_runner(
        LINE_A, env={dc.RUNNER_CMD_ENV:
                     "%s %s" % (sys.executable,
                                _echo_script(tmp_path, stdout))})
    with pytest.raises(dc.CouldNotRun, match=why):
        runner([])


def _echo_script(tmp_path, text):
    s = tmp_path / ("echo_%d.py" % abs(hash(text)))
    s.write_text("import sys; sys.stdout.write(%r)" % text, encoding="utf-8")
    return str(s)


def test_runner_nonzero_exit_is_could_not_run(tmp_path):
    s = tmp_path / "fail.py"
    s.write_text("import sys; sys.exit(3)", encoding="utf-8")
    runner = dc.resolve_runner(LINE_A, env={dc.RUNNER_CMD_ENV:
                                            "%s %s" % (sys.executable, s)})
    with pytest.raises(dc.CouldNotRun, match="runner_failed_exit_3"):
        runner([])


def test_runner_timeout_is_named(tmp_path):
    s = tmp_path / "slow.py"
    s.write_text("import time; time.sleep(30)", encoding="utf-8")
    runner = dc.resolve_runner(
        LINE_A, env={dc.RUNNER_CMD_ENV: "%s %s" % (sys.executable, s),
                     dc.RUNNER_TIMEOUT_ENV: "1"})
    with pytest.raises(dc.CouldNotRun, match="runner_timeout"):
        runner([])


def test_runner_could_not_run_records_growth_not_freeze(tmp_path):
    # the round's own goal-24 path: a failing runner grows the range, opens
    # no freeze — the tick inherits this from run_line_round untouched.
    p = ledger(tmp_path)
    dc.append_rows([landing("r", "a1", at=1)], p)

    def boom(candidate):
        raise dc.CouldNotRun("runner_failed_exit_3")

    out = dc.line_round_tick(
        "proj", load_lines=lambda k: {LINE_A: object()},
        read_rows=reader(p), append_rows=writer(p),
        resolve_runner_fn=lambda line, env: boom,
        guard_path=str(guard_path(tmp_path)), now_ms=10_000,
        backstop_ms=1)
    assert any("rounds" in e for e in out["lines"])
    # could_not_run_row IS a ledger row (range growth), written by the round
    rows, _ = dc.read_rows(p)
    assert any(r["kind"] == dc.KIND_RANGE_GROWTH for r in rows)
    assert not any(r["kind"] == dc.KIND_FREEZE for r in rows)


# ---- the backstop env --------------------------------------------------------

def test_backstop_env_default():
    assert dc.backstop_ms_from_env({}) == dc.LINE_BACKSTOP_MS_DEFAULT


def test_backstop_env_valid():
    assert dc.backstop_ms_from_env({dc.BACKSTOP_MS_ENV: "42"}) == 42


@pytest.mark.parametrize("raw,why", [
    ("soon", "backstop_ms_not_int"),
    ("0", "backstop_ms_not_positive"),
    ("-5", "backstop_ms_not_positive"),
    ("  ", "default"),
])
def test_backstop_env_malformed(raw, why):
    if why == "default":
        assert dc.backstop_ms_from_env({dc.BACKSTOP_MS_ENV: raw}) == \
            dc.LINE_BACKSTOP_MS_DEFAULT
    else:
        with pytest.raises(dc.CertifyError, match=why):
            dc.backstop_ms_from_env({dc.BACKSTOP_MS_ENV: raw})


# ---- the production activity body --------------------------------------------

def test_activity_body_wires_real_seams(tmp_path, monkeypatch):
    # SANDBAR_DELIVERY_LEDGER_DIR isolates the ledger; a real declared line
    # with no runner declared ⇒ runner_missing on the operator surface.
    import shared
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.delenv(dc.RUNNER_CMD_ENV, raising=False)
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(
        [{"line_id": LINE_A, "scope": "epic", "owner": "integration",
          "repositories": [{"name": "r", "branch": "develop"}],
          "extra_scenarios": [], "version": 1}]), encoding="utf-8")
    out = dc.line_round_tick_activity("proj")
    assert out["lines"][0]["line"] == LINE_A
    assert out["lines"][0]["state"] == "runner_missing"


def test_activity_body_missing_declaration_is_named(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    out = dc.line_round_tick_activity("proj")
    assert out["lines"][0]["error"].startswith("line_declaration_unreadable")


# ---- the engine-level enumeration -------------------------------------------

def test_declared_line_projects_enumerates_only_declared(tmp_path, monkeypatch):
    import shared
    root = tmp_path / "projects"
    (root / "withlines" / "data" / "develop").mkdir(parents=True)
    (root / "withlines" / "data" / "develop" / "lines.json").write_text(
        "[]", encoding="utf-8")
    (root / "nolines" / "data").mkdir(parents=True)
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    assert dc.declared_line_projects() == ["withlines"]
    assert dc.declared_line_projects(root) == ["withlines"]


def test_declared_line_projects_unreadable_root_is_named(tmp_path):
    with pytest.raises(dc.CertifyError, match="projects_root_unreadable"):
        dc.declared_line_projects(tmp_path / "missing-root" / "deeper")


def test_engine_tick_reports_per_project(tmp_path, monkeypatch):
    import shared
    root = tmp_path / "projects"
    d = root / "proj" / "data" / "develop"
    d.mkdir(parents=True)
    (d / "lines.json").write_text(json.dumps(
        [{"line_id": LINE_A, "scope": "epic", "owner": "integration",
          "repositories": [{"name": "r", "branch": "develop"}],
          "extra_scenarios": [], "version": 1}]), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.delenv(dc.RUNNER_CMD_ENV, raising=False)
    out = dc.line_round_tick_engine()
    assert out["projects"]["proj"]["lines"][0]["state"] == "runner_missing"
    assert "proj" in out["summary"]


def test_engine_tick_unreadable_declaration_is_named(tmp_path, monkeypatch):
    d = tmp_path / "projects" / "broken" / "data" / "develop"
    d.mkdir(parents=True)
    (d / "lines.json").write_text("{torn", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    out = dc.line_round_tick_engine()
    assert out["projects"]["broken"]["lines"][0]["error"].startswith(
        "line_declaration_unreadable")


# ---- arbitration gen0 F6c: malformed backstop at the face --------------------

def test_non_int_backstop_at_face_is_named_per_line(tmp_path):
    # a certified line + a garbage backstop must come back as a whole dict
    # result with a NAMED per-line error entry — never a raw TypeError out.
    p = ledger(tmp_path)
    dc.append_rows([landing("r", "a1", at=1)], p)
    out = dc.line_round_tick(
        "proj", load_lines=lambda k: {LINE_A: object()},
        read_rows=reader(p), append_rows=writer(p),
        resolve_runner_fn=lambda line, env: runner_ok([]),
        guard_path=str(guard_path(tmp_path)), now_ms=10_000,
        backstop_ms="not-a-number")
    assert isinstance(out, dict)
    assert len(out["lines"]) == 1
    e = out["lines"][0]
    assert e["line"] == LINE_A
    assert e["state"] == "error"
    assert e["error"].startswith("backstop_ms_not_int")


def test_negative_and_bool_backstop_at_face_named_too(tmp_path):
    for bad in (-5, True):
        out = dc.line_round_tick(
            "proj", load_lines=lambda k: {LINE_A: object()},
            read_rows=lambda: ([], []), append_rows=lambda b: {"written": 0},
            resolve_runner_fn=lambda line, env: None,
            guard_path=str(guard_path(tmp_path)), now_ms=10_000,
            backstop_ms=bad)
        assert out["lines"][0]["error"].startswith("backstop_ms_not_int")


def test_non_int_now_ms_at_face_is_named_per_line(tmp_path):
    out = dc.line_round_tick(
        "proj", load_lines=lambda k: {LINE_A: object()},
        read_rows=lambda: ([], []), append_rows=lambda b: {"written": 0},
        resolve_runner_fn=lambda line, env: None,
        guard_path=str(guard_path(tmp_path)), now_ms="soon", backstop_ms=1)
    assert out["lines"][0]["error"].startswith("backstop_needs_now_ms")


def test_valid_backstop_still_reaches_the_round(tmp_path):
    calls = []
    out = tick(tmp_path, rows=[landing("r", "a1", at=1)],
               mapping={LINE_A: runner_ok(calls)})
    assert out["lines"][0]["trigger"] == "change"
    assert len(calls) == 1
